"""alarms 0023 run on rows (landing review 2, N5 d): every shape of an existing alarm gets its place, or none and is
counted; the alarms stay append-only after it; one activity-log entry says what it did."""
from datetime import datetime, timezone as utc

from django.db import DatabaseError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from farm.models import ProductionDepartment, Site, System, Tank
from farm.tests.helpers import point_of
from farm.tests.test_stock import make_unit
from sensors.models import AlarmEvent, AlarmRule, Binding
from sensors.tests import make_channel, make_connection, make_device, make_format

BEFORE = [('alarms', '0022_water_limit_without_point')]
AT = datetime(2026, 11, 1, 8, 0, tzinfo=utc.utc)
LABEL = 'alarms 0023: the place of every alarm'


def rows(sql, params=None):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall() if cursor.description else None


class AlarmPlaceMigrationTests(TransactionTestCase):
    serialized_rollback = True

    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)

    def tearDown(self):
        self.migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())

    def alarm(self, summary, source='system', parameter='x', point=None, event=None, device=None):
        return rows('INSERT INTO alarms (source, severity, opened_at, summary, point_id, sensor_event_id, site_id, '
                    'parameter, device_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id',
                    [source, 'warning', AT, summary, point and point.pk, event and event.pk, self.site.pk,
                     parameter, device and device.pk])[0][0]

    def test_every_shape_gets_its_place_or_is_counted(self):
        self.site = Site.objects.create(name='Bergen', code='BG')
        hall = ProductionDepartment.objects.create(site=self.site, name='Hall A', code='HA')
        loop = System.objects.create(site=self.site, production_department=hall, name='Loop one', code='S-01')
        units = {code: make_unit(code, hall, system=loop if code == 'T-02' else None)
                 for code in ('T-01', 'T-02', 'T-03', 'T-04', 'T-06')}
        old = make_unit('T-05', hall)
        Tank.objects.filter(pk=old.pk).update(is_deleted=True)
        make_unit('T-05', hall)                                        # a deleted unit's code used again (N5 c)
        device = make_device(make_connection(), make_format(), self.site)
        channel = make_channel(device, 'oxygen_mg_l')
        binding = Binding.objects.create(channel=channel, point=point_of(units['T-01']), valid_from=AT)
        rule = AlarmRule.objects.create(channel=channel, kind='no_data', severity='warning')
        event = AlarmEvent.objects.create(rule=rule, channel_no=channel.channel_no, binding=binding, opened_at=AT)
        self.migrate(BEFORE)
        made = {
            'point': self.alarm('T-01 · Middle: pH 5.5 (critical)', 'water_limit', 'ph', point=point_of(units['T-01'])),
            'loop': self.alarm('T-02, from S-01 · Loop: pH 5.5 (critical)', 'water_limit', 'ph',
                               point=point_of(loop)),
            'unevaluated': self.alarm('T-03: the water could not be evaluated'),
            'no point': self.alarm('T-04 holds fish and has no active sampling point for its own water'),
            'ambiguous': self.alarm('T-05: the water could not be evaluated'),
            'subject': self.alarm('Oxygen 3.1 (critical)', 'water_limit', 'oxygen_mg_l'),
            'sensor': self.alarm('O2: No fresh value · PROBE', 'sensor_rule', '', event=event),
            'clock': self.alarm('DEV-1: 5 s ahead of the platform', parameter='device_clock', device=device),
        }
        rows("INSERT INTO alarm_subject_state (key, open_alarm_id, updated_at, own_held) VALUES (%s, %s, now(), false)",
             [f'water:unit:{units["T-06"].pk}:oxygen:critical', made['subject']])
        self.migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())
        found = {pk: (unit and str(unit), system and str(system))
                 for pk, unit, system in rows('SELECT id, unit_id, system_id FROM alarms')}
        unit = {code: str(each.pk) for code, each in units.items()}
        self.assertEqual({name: found[pk] for name, pk in made.items()}, {
            'point': (unit['T-01'], None), 'loop': (unit['T-02'], str(loop.pk)), 'unevaluated': (unit['T-03'], None),
            'no point': (unit['T-04'], None), 'ambiguous': (None, None), 'subject': (unit['T-06'], None),
            'sensor': (unit['T-01'], None), 'clock': (None, None)})
        (changes,) = rows('SELECT changes FROM audit_log WHERE entity_label = %s', [LABEL])[0]
        self.assertEqual({label: pair[1] for label, pair in changes.items() if label != 'Note'}, {
            'Placed on a unit': '6', 'Placed on a system only': '0',
            'Not placed: a unit code several units of its site have had': '1', 'About no unit': '1'})
        with self.assertRaises(DatabaseError), transaction.atomic():
            rows('UPDATE alarms SET summary = %s WHERE id = %s', ['rewritten', made['point']])

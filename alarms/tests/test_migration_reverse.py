"""Cross review F13 and F14, on the migrations: an event the sensors' check had closed is carried into the alarms with the
clearance cause "the sensor rule no longer holds" (event_closed), never "back inside the limit"; and alarms 0004 (the
system alarms) refuses to go back, saying why, once a system alarm exists (the append-only alarms cannot be removed)."""
from datetime import datetime, timezone as utc

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from farm.models import Site
from sensors.models import AlarmRule
from sensors.tests import make_channel, make_connection, make_device, make_format

AT = datetime(2026, 11, 1, 8, 0, tzinfo=utc.utc)


def rows(sql, params=None):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall() if cursor.description else None


class MigrationTests(TransactionTestCase):
    serialized_rollback = True

    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)

    def tearDown(self):
        self.migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())

    def test_a_closed_sensor_event_is_carried_with_the_cause_event_closed(self):
        site = Site.objects.create(name='Bergen', code='BG')
        channel = make_channel(make_device(make_connection(), make_format(), site), 'flow_m3_h')
        rule = AlarmRule.objects.create(kind='low', severity='critical', channel=channel, threshold=10)
        self.migrate([('sensors', '0007_device_site')])
        rows('INSERT INTO sensors_alarm_event (rule_id, channel_no, opened_at, closed_at, peak) VALUES (%s, %s, %s, %s, 4)',
             [rule.pk, channel.channel_no, AT, datetime(2026, 11, 1, 9, 0, tzinfo=utc.utc)])
        self.migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())
        self.assertEqual(rows('SELECT cause FROM alarm_clearances'), [('event_closed',)])

    def test_going_back_past_the_system_alarms_says_why_it_cannot(self):
        rows("INSERT INTO alarms (source, parameter, severity, opened_at, summary) "
             "VALUES ('system', 'sensors_failed', 'critical', %s, 'The sensors cannot be read')", [AT])
        with self.assertRaisesRegex(RuntimeError, 'system alarm'):
            self.migrate([('alarms', '0003_levels')])

    def cleared(self, causes):
        """{cause: alarm id} of alarms cleared with these causes (a device's clock alarm for "device removed")."""
        from farm.models import ProductionDepartment
        from farm.tests.helpers import point_of
        from farm.tests.test_stock import make_unit
        site = Site.objects.create(name='Bergen', code='BG')
        point = point_of(make_unit('T-01', ProductionDepartment.objects.create(site=site, name='Hall', code='H')))
        device = make_device(make_connection(), make_format(), site)
        ids = {}
        for cause in causes:
            water = cause != 'device_removed'
            ids[cause] = rows('INSERT INTO alarms (source, point_id, device_id, parameter, severity, opened_at, summary) '
                              "VALUES (%s, %s, %s, %s, 'critical', %s, %s) RETURNING id",
                              ['water_limit' if water else 'system', point.pk if water else None,
                               None if water else device.pk, 'ph' if water else 'device_clock', AT,
                               f'an alarm cleared as {cause}'])[0][0]
            rows('INSERT INTO alarm_clearances (alarm_id, cleared_at, cause) VALUES (%s, %s, %s)', [ids[cause], AT, cause])
        return ids

    def test_going_back_past_the_new_clearance_causes_maps_each_to_the_nearest_old_one_and_logs_it(self):
        """Round-2 review N2: alarms 0009 and 0007 go back with clearances of the causes they added ("limit removed",
        "unit removed", "merged"): each becomes the nearest cause there was before, "no longer judged (no fish or no
        limit)" (`structural`), and the activity log says so per alarm. Nothing is deleted."""
        ids = self.cleared(['merged', 'unit_removed', 'limit_removed'])
        self.migrate([('alarms', '0006_severity_rules_kept')])
        self.assertEqual(dict(rows('SELECT alarm_id, cause FROM alarm_clearances')),
                         {alarm_id: 'structural' for alarm_id in ids.values()})
        notes = rows("SELECT entity_id, changes::text FROM audit_log WHERE entity_type = 'alarm' "
                     "AND changes::text LIKE '%%reversed%%'")
        self.assertEqual(sorted(entity for entity, _changes in notes), sorted(str(alarm_id) for alarm_id in ids.values()))

    def test_going_back_past_the_device_clock_with_a_device_removed_says_why_it_cannot(self):
        """Round-2 review N2: "the device was removed" has no honest older word (the alarms before 0010 knew no
        devices), so alarms 0010 refuses to go back once such a clearance exists, as 0004 does, saying why."""
        self.cleared(['device_removed'])
        with self.assertRaisesRegex(RuntimeError, 'device was removed'):
            self.migrate([('alarms', '0009_clearance_causes')])

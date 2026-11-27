"""alarms 0025 run on rows (review 2, H1): before it, an open alarm, a cleared one and a sensor rule's alarm opened and
cleared; after it, the queue (`alarm_open`) holds exactly the open one, and the triggers keep it from there on. The
triggers come before the fill, so no alarm written between the two is lost. Going back drops the triggers, their
functions and the table."""
from datetime import datetime, timezone as utc

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from farm.models import Site
from sensors.models import AlarmEvent, AlarmRule
from sensors.tests import make_channel, make_connection, make_device, make_format

BEFORE = [('alarms', '0024_attempts_sent_at_index')]
AFTER = [('alarms', '0025_open_alarms')]
AT = datetime(2026, 11, 1, 8, 0, tzinfo=utc.utc)


def rows(sql, params=None):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall() if cursor.description else None


class OpenAlarmsMigrationTests(TransactionTestCase):
    serialized_rollback = True

    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)

    def tearDown(self):
        self.migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())

    def alarm(self, summary, source='system', parameter='x', event=None):
        return rows('INSERT INTO alarms (source, severity, opened_at, summary, sensor_event_id, site_id, parameter) '
                    'VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id',
                    [source, 'warning', AT, summary, event and event.pk, self.site.pk, parameter])[0][0]

    def clear(self, alarm):
        rows("INSERT INTO alarm_clearances (alarm_id, cleared_at, cause) VALUES (%s, %s, 'restored')", [alarm, AT])

    def objects(self):
        """The triggers and their functions there are."""
        return sorted(name for (name,) in rows(
            "SELECT tgname FROM pg_trigger WHERE tgname IN ('trg_alarms_open', 'trg_alarm_clearances_open') "
            "UNION ALL SELECT proname FROM pg_proc WHERE proname IN ('alarm_open_opened', 'alarm_open_cleared')"))

    def test_the_queue_is_filled_with_the_open_alarms_and_kept_and_going_back_drops_it(self):
        self.site = Site.objects.create(name='Bergen', code='BG')
        device = make_device(make_connection(), make_format(), self.site)
        channel = make_channel(device, 'oxygen_mg_l')
        rule = AlarmRule.objects.create(channel=channel, kind='no_data', severity='warning')
        event = AlarmEvent.objects.create(rule=rule, channel_no=channel.channel_no, opened_at=AT, closed_at=AT)
        self.migrate(BEFORE)
        made = {'open': self.alarm('open'), 'cleared': self.alarm('cleared'),
                'sensor': self.alarm('O2: No fresh value · PROBE', 'sensor_rule', '', event=event)}
        self.clear(made['cleared'])
        self.clear(made['sensor'])
        self.migrate(AFTER)
        self.assertEqual(rows('SELECT alarm_id FROM alarm_open'), [(made['open'],)])
        self.assertEqual(self.objects(), ['alarm_open_cleared', 'alarm_open_opened', 'trg_alarm_clearances_open',
                                          'trg_alarms_open'])
        later = self.alarm('later')                                    # kept from here on, by the triggers
        self.assertEqual(sorted(rows('SELECT alarm_id FROM alarm_open')), sorted([(made['open'],), (later,)]))
        self.clear(made['open'])
        self.assertEqual(rows('SELECT alarm_id FROM alarm_open'), [(later,)])
        self.migrate(BEFORE)
        self.assertEqual(rows("SELECT to_regclass('alarm_open')"), [(None,)])
        self.assertEqual(self.objects(), [])

    def test_the_triggers_are_made_before_the_fill(self):
        """CREATE TRIGGER waits for the writers under way and holds the later ones out until the migration commits:
        made first, the fill sees every alarm and clearance there is, and none is written between the two (H1)."""
        from importlib import import_module
        operations = import_module('alarms.migrations.0025_open_alarms').Migration.operations
        sql = [str(getattr(operation, 'sql', '')) for operation in operations]
        triggers = next(index for index, text in enumerate(sql) if 'CREATE TRIGGER trg_alarms_open' in text)
        fill = next(index for index, text in enumerate(sql) if 'INSERT INTO alarm_open' in text and 'opened' not in text)
        self.assertLess(triggers, fill)
        self.assertIn('ON CONFLICT DO NOTHING', sql[fill])

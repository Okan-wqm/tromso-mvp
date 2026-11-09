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

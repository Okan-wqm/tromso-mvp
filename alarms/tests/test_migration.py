"""The acknowledgement has one home: the sensors' events kept who acknowledged them on the event itself; the migration that
removes those columns carries every event into the alarms (an alarm, its clearance when it closed) and every
acknowledgement into an Acknowledgement row, and going back writes them on the events again. Nothing is lost either way."""
from datetime import datetime, timezone as utc

from django.contrib.auth import get_user_model
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import SimpleTestCase, TransactionTestCase

from farm.models import Site
from sensors.models import AlarmRule
from sensors.tests import make_channel, make_connection, make_device, make_format

BEFORE = [('sensors', '0007_device_site')]
AT = datetime(2026, 11, 1, 8, 0, tzinfo=utc.utc)


def rows(sql, params=None):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall() if cursor.description else None


class AcknowledgementMigrationTests(TransactionTestCase):
    serialized_rollback = True

    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)

    def tearDown(self):
        self.migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())

    def test_the_events_and_their_acknowledgements_move_into_the_alarms_and_back(self):
        site = Site.objects.create(name='Bergen', code='BG')
        channel = make_channel(make_device(make_connection(), make_format(), site), 'flow_m3_h')
        rule = AlarmRule.objects.create(kind='low', severity='critical', channel=channel, threshold=10)
        person = get_user_model().objects.create_user('tech', 'tech@example.com', 'x')
        self.migrate(BEFORE)
        rows('INSERT INTO sensors_alarm_event (rule_id, channel_no, opened_at, closed_at, peak, acknowledged_by_id, '
             'acknowledged_at) VALUES (%s, %s, %s, %s, 4, %s, %s), (%s, %s, %s, NULL, 3, NULL, NULL)',
             [rule.pk, channel.channel_no, AT, datetime(2026, 11, 1, 9, 0, tzinfo=utc.utc), person.pk,
              datetime(2026, 11, 1, 8, 5, tzinfo=utc.utc), rule.pk, channel.channel_no,
              datetime(2026, 11, 2, 8, 0, tzinfo=utc.utc)])
        self.migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())
        alarms = rows('SELECT a.source, a.severity, a.site_id, a.opened_at, c.cleared_at FROM alarms a '
                      'LEFT JOIN alarm_clearances c ON c.alarm_id = a.id ORDER BY a.opened_at')
        self.assertEqual(alarms, [('sensor_rule', 'critical', site.pk, AT, datetime(2026, 11, 1, 9, 0, tzinfo=utc.utc)),
                                  ('sensor_rule', 'critical', site.pk, datetime(2026, 11, 2, 8, 0, tzinfo=utc.utc),
                                   None)])
        self.assertEqual(rows('SELECT user_id, acknowledged_at, app, device FROM alarm_acknowledgements'),
                         [(person.pk, datetime(2026, 11, 1, 8, 5, tzinfo=utc.utc), 'console', '')])
        self.assertEqual(rows("SELECT count(*) FROM information_schema.columns WHERE table_name = 'sensors_alarm_event' "
                              "AND column_name LIKE 'acknowledged%%'"), [(0,)])
        self.migrate(BEFORE)
        self.assertEqual(rows('SELECT acknowledged_by_id, acknowledged_at FROM sensors_alarm_event ORDER BY opened_at'),
                         [(person.pk, datetime(2026, 11, 1, 8, 5, tzinfo=utc.utc)), (None, None)])


class FarmDependencyTests(SimpleTestCase):
    """The alarms' migrations need the farm only as far as the tables they read (sites, departments, sampling points:
    farm 0019). A later farm dependency (one the autodetector adds because it was the leaf) makes a farm migration test
    that goes back and forward to the farm's leaf alone leave the alarms half unapplied for the tests after it."""

    def test_no_alarms_migration_depends_on_a_later_farm_migration(self):
        from django.db.migrations.loader import MigrationLoader
        loader = MigrationLoader(None, ignore_no_migrations=True)
        found = sorted((key[1], dependency[1]) for key, migration in loader.disk_migrations.items()
                       if key[0] == 'alarms' for dependency in migration.dependencies
                       if dependency[0] == 'farm' and dependency[1] > '0019_water_points')
        self.assertEqual(found, [])

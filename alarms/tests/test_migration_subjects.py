"""Cross review F7: the subjects of the water alarms were keyed by the point that stood for the unit; migration 0007 keys
them by the unit. Two points of one unit with an alarm open at the same level are one subject: the earliest alarm stays
open as its alarm, the others are cleared with the cause "merged" (the record says why), and the timers are merged the
safe way (the earliest pending, the latest bad value, no clear timer running)."""
from datetime import datetime, timezone as utc

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from farm.models import ProductionDepartment, SamplingPoint, Site
from farm.tests.helpers import point_of
from farm.tests.test_stock import make_unit

BEFORE = [('alarms', '0006_severity_rules_kept')]
AT = datetime(2026, 11, 1, 8, 0, tzinfo=utc.utc)


def rows(sql, params=None):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall() if cursor.description else None


class SubjectKeyMigrationTests(TransactionTestCase):
    serialized_rollback = True

    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)

    def tearDown(self):
        self.migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())

    def alarm(self, point, severity, at):
        return rows("INSERT INTO alarms (source, point_id, parameter, severity, opened_at, summary) "
                    "VALUES ('water_limit', %s, 'ph', %s, %s, 'pH') RETURNING id", [point.pk, severity, at])[0][0]

    def test_point_keys_become_unit_keys_and_duplicates_are_merged_honestly(self):
        site = Site.objects.create(name='Bergen', code='BG')
        hall = ProductionDepartment.objects.create(site=site, name='Hall A', code='HA')
        unit = make_unit('T-01', hall)
        old = point_of(unit)
        new = SamplingPoint.objects.create(unit=unit, kind='depth', name='Bottom', depth_m=1)
        self.migrate(BEFORE)
        first = self.alarm(old, 'critical', AT)
        second = self.alarm(new, 'critical', datetime(2026, 11, 1, 9, 0, tzinfo=utc.utc))
        warning = self.alarm(old, 'warning', AT)
        rows('INSERT INTO alarm_subject_state (key, open_alarm_id, pending_since, last_bad_at, updated_at) VALUES '
             '(%s, %s, NULL, %s, now()), (%s, %s, NULL, %s, now()), (%s, %s, NULL, %s, now()), '
             '(%s, NULL, %s, NULL, now())',
             [f'water:{old.pk}:ph:critical', first, AT, f'water:{new.pk}:ph:critical', second,
              datetime(2026, 11, 1, 9, 30, tzinfo=utc.utc), f'water:{old.pk}:ph:warning', warning, AT,
              f'water:{new.pk}:ph:warning', AT])
        self.migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())
        self.assertEqual(rows('SELECT key, open_alarm_id, last_bad_at FROM alarm_subject_state ORDER BY key'), [
            (f'water:unit:{unit.pk}:ph:critical', first, datetime(2026, 11, 1, 9, 30, tzinfo=utc.utc)),
            (f'water:unit:{unit.pk}:ph:warning', warning, AT)])
        self.assertEqual(rows('SELECT alarm_id, cause FROM alarm_clearances'), [(second, 'merged')])

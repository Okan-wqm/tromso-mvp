"""The data-layering audit, M-1: the reference rows a migration seeds and the application only reads and changes (the
platform settings, the scheduling settings, the water's freshness rules) are kept by the database, never deleted and
never soft deleted (core.operations.KeepRows), and reading them is a read: nothing is written on a page or an alarm pass.
A row lost all the same (by hand, as the database's owner) is refused loudly where it is read, never made again from the
code's constants and never stood in for by them."""
from datetime import timedelta
from unittest import mock

from django.db import DatabaseError, IntegrityError, connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from farm.models import WaterFreshness
from farm.water import evaluate, freshness, parameters
from hr.models import SchedulingSettings

from .models import PlatformSettings

KEPT = {PlatformSettings: 'platform_settings', SchedulingSettings: 'scheduling_settings',
        WaterFreshness: 'water_freshness'}


def lose(table, where='true'):
    """Deletes rows of a kept table as only its owner could: the trigger set aside for the statement, inside the test's
    transaction (rolled back with it)."""
    with connection.cursor() as cursor:
        cursor.execute(f'ALTER TABLE {table} DISABLE TRIGGER trg_{table}_kept')
        cursor.execute(f'DELETE FROM {table} WHERE {where}')
        cursor.execute(f'ALTER TABLE {table} ENABLE TRIGGER trg_{table}_kept')


class KeptRowsTests(TestCase):
    def setUp(self):
        freshness.forget()
        self.addCleanup(freshness.forget)

    def test_the_database_refuses_to_delete_them(self):
        for model in KEPT:
            with self.subTest(model=model.__name__), self.assertRaises(IntegrityError), transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(f'DELETE FROM {KEPT[model]}')

    def test_the_database_refuses_to_soft_delete_them(self):
        for model in KEPT:
            with self.subTest(model=model.__name__), self.assertRaises(IntegrityError), transaction.atomic():
                model.all_objects.update(is_deleted=True)

    def test_every_water_parameter_has_its_freshness_row(self):
        self.assertEqual(set(WaterFreshness.objects.values_list('parameter', flat=True)), set(parameters.BY_CODE))

    def test_reading_them_writes_nothing(self):
        with CaptureQueriesContext(connection) as queries:
            PlatformSettings.get()
            SchedulingSettings.get()
            for code in parameters.BY_CODE:
                freshness.hours(code)
            freshness.tolerance()
        written = [query['sql'] for query in queries if not query['sql'].lstrip().upper().startswith('SELECT')]
        self.assertEqual(written, [])

    def test_a_lost_freshness_row_is_refused_never_made_again(self):
        lose('water_freshness', "parameter = 'ph'")
        now = timezone.now()
        with self.assertRaises(freshness.Missing) as refused:
            freshness.hours('ph')
        self.assertIn("'ph'", str(refused.exception))
        with self.assertRaises(freshness.Missing):
            evaluate.is_fresh(parameters.get('ph'), now - timedelta(hours=1), now)
        self.assertFalse(WaterFreshness.all_objects.filter(parameter='ph').exists())
        self.assertEqual(freshness.hours('temperature_c'), 24)          # the others are read as they are

    def test_unreadable_rows_are_the_callers_error_never_the_codes_defaults(self):
        with mock.patch.object(freshness, '_load', side_effect=DatabaseError('the database is not there')):
            with self.assertRaises(DatabaseError):
                freshness.hours('ph')
            with self.assertRaises(DatabaseError):
                freshness.tolerance()

    def test_the_code_holds_no_default_to_stand_in_for_the_rows(self):
        for name in ('SEEDS', '_defaults'):
            with self.subTest(name=name):
                self.assertFalse(hasattr(freshness, name))

    def test_a_lost_settings_row_is_refused_never_made_again(self):
        for model, table in ((PlatformSettings, 'platform_settings'), (SchedulingSettings, 'scheduling_settings')):
            with self.subTest(model=model.__name__), transaction.atomic():
                lose(table)
                with self.assertRaises(model.DoesNotExist):
                    model.get()
                self.assertEqual(model.all_objects.count(), 0)
                transaction.set_rollback(True)

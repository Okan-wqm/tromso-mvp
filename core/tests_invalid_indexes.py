"""core.W006 (core/checks.py invalid_indexes): an index a concurrent build left invalid is named, with the command that
removes it, by `manage.py check --database default`; the check is quiet once it is gone. The index is made invalid
the way it happens on a farm: a CREATE INDEX CONCURRENTLY that fails part-way (a unique index over a duplicate)."""
from django.db import IntegrityError, connection
from django.test import TransactionTestCase

from . import checks


class InvalidIndexCheckTests(TransactionTestCase):
    serialized_rollback = True            # the next test finds the rows the migrations made

    def setUp(self):
        with connection.cursor() as cursor:
            cursor.execute('CREATE TABLE w006_probe (x integer)')
            cursor.execute('INSERT INTO w006_probe VALUES (1), (1)')
        self.addCleanup(self.drop)

    def drop(self):
        with connection.cursor() as cursor:
            cursor.execute('DROP TABLE IF EXISTS w006_probe')

    def test_an_index_a_failed_concurrent_build_left_is_named_with_its_remedy(self):
        self.assertEqual(checks.invalid_indexes(None), [])
        with connection.cursor() as cursor:
            with self.assertRaises(IntegrityError):                   # the duplicate: the build fails part-way
                cursor.execute('CREATE UNIQUE INDEX CONCURRENTLY w006_probe_x ON w006_probe (x)')
        (warning,) = checks.invalid_indexes(None)
        self.assertEqual(warning.id, 'core.W006')
        self.assertIn('public.w006_probe_x', warning.msg)
        self.assertIn('DROP INDEX CONCURRENTLY IF EXISTS public.w006_probe_x;', warning.hint)
        with connection.cursor() as cursor:                           # the remedy, as the hint says it
            cursor.execute(warning.hint.split(';')[0])
        self.assertEqual(checks.invalid_indexes(None), [])

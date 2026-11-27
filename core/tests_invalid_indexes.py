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

    def test_a_partitioned_tables_invalid_index_is_named_with_a_drop_it_accepts(self):
        """An index made ON ONLY a partitioned table is invalid until its partitions' indexes are attached; PostgreSQL
        refuses DROP INDEX CONCURRENTLY on it, so the hint drops it plainly."""
        with connection.cursor() as cursor:
            cursor.execute('CREATE TABLE w006_parted (x integer) PARTITION BY RANGE (x)')
            self.addCleanup(lambda: connection.cursor().execute('DROP TABLE IF EXISTS w006_parted'))
            cursor.execute('CREATE TABLE w006_part PARTITION OF w006_parted FOR VALUES FROM (0) TO (10)')
            cursor.execute('CREATE INDEX w006_parted_x ON ONLY w006_parted (x)')
        (warning,) = checks.invalid_indexes(None)
        self.assertIn('DROP INDEX IF EXISTS public.w006_parted_x;', warning.hint)
        with connection.cursor() as cursor:
            cursor.execute(warning.hint.split(';')[0])
        self.assertEqual(checks.invalid_indexes(None), [])

from django.db import connection, transaction
from django.test import TestCase

from farm.models import Site

from .codes import next_code


class NextCodeTests(TestCase):
    """The generated code of a record kind (batches and experiments call it): one rule, tested on sites, a
    model that has a code and `all_objects`."""

    def site(self, code, **fields):
        return Site.objects.create(name=f'Site {code}', code=code, **fields)

    def test_the_first_number_of_a_prefix_is_001_and_each_prefix_counts_alone(self):
        self.assertEqual(next_code(Site, 'ZZ-2026-'), 'ZZ-2026-001')
        self.site('ZZ-2026-001')
        self.site('ZZ-2025-007')
        self.assertEqual(next_code(Site, 'ZZ-2026-'), 'ZZ-2026-002')
        self.assertEqual(next_code(Site, 'ZZ-2025-'), 'ZZ-2025-008')
        self.assertEqual(next_code(Site, 'ZZ-2027-'), 'ZZ-2027-001')

    def test_the_number_follows_the_highest_not_the_count_and_deleted_records_still_hold_theirs(self):
        self.site('ZZ-2026-002')
        gone = self.site('ZZ-2026-009')
        self.assertEqual(next_code(Site, 'ZZ-2026-'), 'ZZ-2026-010')
        gone.soft_delete(None)
        self.assertFalse(Site.objects.filter(pk=gone.pk).exists())
        self.assertEqual(next_code(Site, 'ZZ-2026-'), 'ZZ-2026-010')

    def test_the_numbers_pass_999_without_losing_their_order(self):
        self.site('ZZ-2026-999')
        self.assertEqual(next_code(Site, 'ZZ-2026-'), 'ZZ-2026-1000')
        self.site('ZZ-2026-1000')
        self.assertEqual(next_code(Site, 'ZZ-2026-'), 'ZZ-2026-1001')

    def test_it_takes_the_advisory_lock_of_the_models_table_for_the_transaction(self):
        """Two creators of one kind take turns: the lock is keyed on the table, so batches keep the key
        `hashtext('batches.code')` they always had."""
        def held(table):
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND pid = pg_backend_pid() "
                    "AND ((hashtext(%s)::bigint >> 32) & 4294967295) = classid::bigint "
                    "AND (hashtext(%s)::bigint & 4294967295) = objid::bigint", [f'{table}.code'] * 2)
                return cursor.fetchone()[0]
        with transaction.atomic():
            self.assertEqual(held('sites'), 0)
            next_code(Site, 'ZZ-2026-')
            self.assertEqual(held('sites'), 1)
            self.assertEqual(held('batches'), 0)

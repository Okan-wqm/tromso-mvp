"""The revision table `core_rev` (core.rev): a counter per (scope, key) that the database moves whenever a tracked row
changes, so a stored figure can prove it is still valid. Each tracked table's triggers note the changed keys while
the transaction runs and apply them at commit, sorted, once per key (two writers in opposite order never deadlock);
raw SQL, bulk inserts, soft deletes and date edits are all seen, because no Python code bumps anything.

A TestCase never commits, so its deferred triggers are fired with `rev.settle()`; the concurrency tests use their own
connections and commit."""
import threading
from datetime import date, timedelta

import psycopg
from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, transaction
from django.test import TestCase, TransactionTestCase

from farm.models import ProductionDepartment, Site, Species, StockMovement, StockOperation
from farm.stock import services
from farm.tests.helpers import make_species, stock_fish
from farm.tests.test_stock import make_unit

from . import rev
from .operations import TrackRev


def row(scope, key):
    """(rev, dirty_epoch, dirty_from) of a key, or None."""
    with connection.cursor() as cursor:
        cursor.execute('SELECT rev, dirty_epoch, dirty_from FROM core_rev WHERE scope = %s AND key = %s', [scope, str(key)])
        return cursor.fetchone()


class Farm:
    def make_farm(self):
        self.user = get_user_model().objects.create_user('rev', 'rev@example.com', 'x')
        site = Site.objects.create(name='Bergen', code='BG')
        hall = ProductionDepartment.objects.create(site=site, name='Hall A', code='HA')
        self.t1, self.t2 = make_unit('T-01', hall), make_unit('T-02', hall)
        self.salmon = make_species()
        self.today = services.local_today(self.t1)

    def operation(self, days_ago, kind='weighing'):
        return StockOperation.objects.create(kind=kind, date=self.today - timedelta(days=days_ago), created_by=self.user,
                                             updated_by=self.user)

    def weighing_sql(self, operation, batch, unit):
        return ("INSERT INTO stock_movements (operation_id, batch_id, unit_id, kind, count_delta, avg_weight_g, reason, "
                "size_class) VALUES (%s, %s, %s, 'weighing', 0, 60, '', '')", [operation.pk, batch.pk, unit.pk])


class BumpTests(TestCase):
    def note(self, scope, key, day=None):
        with connection.cursor() as cursor:
            cursor.execute('SELECT core_rev_note(%s, %s, %s)', [scope, str(key), day])

    def test_noted_keys_are_applied_once_with_the_earliest_day(self):
        self.note('t', 1, date(2026, 3, 5))
        self.note('t', 1, date(2026, 3, 1))
        self.note('t', 1, date(2026, 3, 9))
        self.note('t', 2)
        self.assertIsNone(row('t', 1))                       # nothing is written before the apply
        rev.settle()
        self.assertEqual(row('t', 1), (1, 0, date(2026, 3, 1)))
        self.assertEqual(row('t', 2), (1, 0, None))          # a table scope has no day

    def test_a_key_changed_again_after_an_apply_moves_again(self):
        self.note('t', 1, date(2026, 3, 5))
        rev.settle()
        self.note('t', 1, date(2026, 3, 7))
        rev.settle()
        self.assertEqual(row('t', 1), (2, 0, date(2026, 3, 5)))

    def test_a_revision_is_never_negative_and_a_key_is_unique(self):
        self.note('t', 1)
        rev.settle()
        with self.assertRaises(IntegrityError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("UPDATE core_rev SET rev = -1 WHERE scope = 't'")
        with self.assertRaises(IntegrityError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("INSERT INTO core_rev (scope, key, rev, dirty_epoch) VALUES ('t', '1', 5, 0)")

    def test_rev_reads_a_missing_key_as_none_and_stamp_reads_many_in_one_query(self):
        self.note('t', 1)
        self.note('u', 0)
        rev.settle()
        self.assertIsNone(rev.rev('t', 9))
        self.assertEqual(rev.rev('t', 1), 1)
        with self.assertNumQueries(1):
            stamp = rev.stamp([('u', 0), ('t', 1), ('t', 9)])
        self.assertEqual(stamp, 't:1:1 t:9:- u:0:1')        # sorted; a missing key says so

    def test_mark_built_sets_the_epoch_only_when_the_revision_has_not_moved(self):
        self.note('t', 1, date(2026, 3, 5))
        rev.settle()
        self.assertTrue(rev.mark_built('t', 1, 1))
        self.assertEqual(row('t', 1), (1, 1, None))
        self.assertFalse(rev.mark_built('t', 1, 0))          # built from an older revision: refused
        self.assertEqual(row('t', 1), (1, 1, None))

    def test_a_write_after_mark_built_in_the_same_transaction_moves_the_revision(self):
        # mark_built forgets the transaction's notes of that key, so a later change in the same transaction counts.
        self.note('t', 1, date(2026, 3, 5))
        rev.settle()
        rev.mark_built('t', 1, 1)
        self.note('t', 1, date(2026, 3, 9))
        rev.settle()
        self.assertEqual(row('t', 1), (2, 1, date(2026, 3, 9)))

    def test_rebuild_moves_every_revision_past_every_stamp_and_clears_the_days(self):
        self.note('t', 1, date(2026, 3, 5))
        self.note('t', 2)
        rev.settle()
        with connection.cursor() as cursor:
            cursor.execute("UPDATE core_rev SET rev = 7 WHERE key = '2'")
        rev.rebuild(stamped=[8])                              # a stored figure stamped 8 (a restore can go back)
        self.assertEqual(row('t', 1), (9, 9, None))
        self.assertEqual(row('t', 2), (9, 9, None))
        # A key seen for the first time after the rebuild starts above the floor: a figure stamped before the restore
        # can never meet its revision again.
        self.note('t', 3)
        rev.settle()
        self.assertEqual(row('t', 3), (10, 0, None))


class StockTrackingTests(Farm, TestCase):
    """Every way the stock ledger changes moves the revision of the batches it touches, with the earliest day changed."""

    def setUp(self):
        self.make_farm()
        self.batch = stock_fish(self.user, self.t1, 1000, '50', 20, species=self.salmon)
        rev.settle()
        rev.mark_built('batch', self.batch.pk, rev.rev('batch', self.batch.pk))

    def day(self, days_ago):
        return self.today - timedelta(days=days_ago)

    def test_the_services_write_moves_the_batch(self):
        fresh = stock_fish(self.user, self.t2, 500, '40', 5, species=self.salmon)
        services.record_mortality(self.user, unit=self.t1, batch=self.batch, day=self.day(3), count=10, cause='disease')
        rev.settle()
        self.assertEqual(row('batch', fresh.pk), (1, 0, self.day(5)))
        self.assertEqual(row('batch', self.batch.pk), (2, 1, self.day(3)))

    def test_bulk_create_and_raw_sql_move_the_batch(self):
        StockMovement.objects.bulk_create([StockMovement(
            operation=self.operation(4), batch=self.batch, unit=self.t1, kind='weighing', count_delta=0,
            avg_weight_g=55)])
        rev.settle()
        self.assertEqual(row('batch', self.batch.pk)[2], self.day(4))
        rev.mark_built('batch', self.batch.pk, rev.rev('batch', self.batch.pk))
        with connection.cursor() as cursor:
            cursor.execute(*self.weighing_sql(self.operation(2), self.batch, self.t1))
        rev.settle()
        self.assertEqual(row('batch', self.batch.pk), (3, 2, self.day(2)))

    def test_a_void_and_a_restore_move_the_batch_of_every_line(self):
        operation = services.record_mortality(self.user, unit=self.t1, batch=self.batch, day=self.day(6), count=5,
                                              cause='disease')
        rev.settle()
        rev.mark_built('batch', self.batch.pk, rev.rev('batch', self.batch.pk))
        services.void(self.user, operation, 'Entered twice')
        rev.settle()
        self.assertEqual(row('batch', self.batch.pk), (3, 2, self.day(6)))
        rev.mark_built('batch', self.batch.pk, 3)
        StockOperation.all_objects.filter(pk=operation.pk).update(is_deleted=False, void_reason='')
        rev.settle()
        self.assertEqual(row('batch', self.batch.pk), (4, 3, self.day(6)))

    def test_a_date_edit_marks_the_earlier_of_the_two_days(self):
        operation = services.record_mortality(self.user, unit=self.t1, batch=self.batch, day=self.day(6), count=5,
                                              cause='disease')
        rev.settle()
        rev.mark_built('batch', self.batch.pk, 2)
        StockOperation.all_objects.filter(pk=operation.pk).update(date=self.day(12))
        rev.settle()
        self.assertEqual(row('batch', self.batch.pk), (3, 2, self.day(12)))
        rev.mark_built('batch', self.batch.pk, 3)
        StockOperation.all_objects.filter(pk=operation.pk).update(date=self.day(1))
        rev.settle()
        self.assertEqual(row('batch', self.batch.pk), (4, 3, self.day(12)))

    def test_an_edit_of_a_column_the_fold_does_not_read_moves_nothing(self):
        operation = StockOperation.objects.get(movements__batch=self.batch)
        StockOperation.all_objects.filter(pk=operation.pk).update(notes='checked')
        rev.settle()
        self.assertEqual(row('batch', self.batch.pk), (1, 1, None))

    def test_a_species_change_marks_the_whole_history(self):
        trout = make_species('RBT', 'Rainbow trout', 'Oncorhynchus mykiss', local_name='', saltwater=False)
        type(self.batch).all_objects.filter(pk=self.batch.pk).update(species=trout)
        rev.settle()
        self.assertEqual(row('batch', self.batch.pk), (2, 1, rev.EVERYTHING))

    def test_a_deleted_line_and_a_line_moved_to_another_batch_move_both(self):
        other = stock_fish(self.user, self.t2, 300, '40', 30, species=self.salmon)
        rev.settle()
        rev.mark_built('batch', other.pk, 1)
        line = StockMovement.objects.create(operation=self.operation(8), batch=self.batch, unit=self.t1,
                                            kind='weighing', count_delta=0, avg_weight_g=52)
        rev.settle()
        rev.mark_built('batch', self.batch.pk, 2)
        with connection.cursor() as cursor:
            cursor.execute('UPDATE stock_movements SET batch_id = %s WHERE id = %s', [other.pk, line.pk])
        rev.settle()
        self.assertEqual(row('batch', self.batch.pk), (3, 2, self.day(8)))
        self.assertEqual(row('batch', other.pk), (2, 1, self.day(8)))
        rev.mark_built('batch', other.pk, 2)
        StockMovement.objects.filter(pk=line.pk).delete()
        rev.settle()
        self.assertEqual(row('batch', other.pk), (3, 2, self.day(8)))


class PresenceTests(TestCase):
    def test_every_declared_trigger_is_there_and_enabled(self):
        self.assertEqual(rev.missing(), [])
        self.assertTrue(rev.TRACKED)

    def test_a_disabled_or_dropped_trigger_is_reported(self):
        with connection.cursor() as cursor:
            cursor.execute('ALTER TABLE stock_movements DISABLE TRIGGER core_rev_stock_movements_batch_note')
        self.assertEqual(rev.missing(), ['core_rev_stock_movements_batch_note'])

    def test_the_declared_set_is_what_the_migrations_made(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT tgname FROM pg_trigger WHERE tgname LIKE 'core\\_rev\\_%%' AND NOT tgisinternal")
            made = {name for (name,) in cursor.fetchall()}
        self.assertEqual(made, {name for track in rev.TRACKED for name in rev.trigger_names(*track)})


class TrackRevOperationTests(TestCase):
    """The migration operation on a table of its own: forwards makes the two triggers, backwards removes them."""

    def test_forwards_and_backwards(self):
        operation = TrackRev('rev_probe', 'probe', keys='{row}.owner_id', day='{row}.on_day')
        with connection.cursor() as cursor:
            cursor.execute('CREATE TABLE rev_probe (id serial PRIMARY KEY, owner_id bigint, on_day date, note text)')
        with connection.schema_editor(atomic=False) as editor:
            operation.database_forwards('core', editor, None, None)
        with connection.cursor() as cursor:
            cursor.execute("INSERT INTO rev_probe (owner_id, on_day) VALUES (4, '2026-01-02'), (4, '2026-01-01')")
        rev.settle()
        self.assertEqual(row('probe', 4), (1, 0, date(2026, 1, 1)))
        with connection.schema_editor(atomic=False) as editor:
            operation.database_backwards('core', editor, None, None)
        with connection.cursor() as cursor:
            cursor.execute("INSERT INTO rev_probe (owner_id, on_day) VALUES (5, '2026-01-02')")
            cursor.execute("SELECT count(*) FROM pg_proc WHERE proname = 'core_rev_rev_probe_probe'")
            self.assertEqual(cursor.fetchone()[0], 0)
        rev.settle()
        self.assertIsNone(row('probe', 5))


class ConcurrencyTests(Farm, TransactionTestCase):
    """Two writers on their own connections, committing."""
    serialized_rollback = True      # the rows migrations write (the equipment types) come back for later tests

    def setUp(self):
        self.make_farm()
        self.b1 = stock_fish(self.user, self.t1, 1000, '50', 20, species=self.salmon)
        self.b2 = stock_fish(self.user, self.t2, 1000, '50', 20, species=self.salmon)
        self.ops = [self.operation(days) for days in range(1, 9)]

    def connect(self):
        params = connection.get_connection_params()
        params.pop('cursor_factory', None)
        params.pop('context', None)
        return psycopg.connect(**params)

    def test_an_open_writer_does_not_block_another_writer_of_the_same_batch(self):
        with self.connect() as first, self.connect() as second:
            first.execute(*self.weighing_sql(self.ops[0], self.b1, self.t1))    # open, not committed
            second.execute("SET statement_timeout = '3s'")
            second.execute(*self.weighing_sql(self.ops[1], self.b1, self.t1))
            second.commit()                                                     # the bump waits for no one
            first.commit()
        self.assertEqual(rev.rev('batch', self.b1.pk), 3)                       # the stocking, then two commits

    def test_two_writers_in_opposite_order_never_deadlock(self):
        failures, rounds = [], 15
        for number in range(rounds):
            ops = [self.operation(30 + 2 * number), self.operation(31 + 2 * number)]
            with self.connect() as first, self.connect() as second:
                first.execute(*self.weighing_sql(ops[0], self.b1, self.t1))
                first.execute(*self.weighing_sql(ops[0], self.b2, self.t2))
                second.execute(*self.weighing_sql(ops[1], self.b2, self.t2))
                second.execute(*self.weighing_sql(ops[1], self.b1, self.t1))
                start = threading.Barrier(2)

                def commit(conn):
                    start.wait()
                    try:
                        conn.commit()
                    except psycopg.Error as error:
                        failures.append(error)
                threads = [threading.Thread(target=commit, args=(conn,)) for conn in (first, second)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()
        self.assertEqual(failures, [])
        self.assertEqual((rev.rev('batch', self.b1.pk), rev.rev('batch', self.b2.pk)), (1 + 2 * rounds, 1 + 2 * rounds))


class RebuildCommandTests(TestCase):
    def test_the_command_moves_every_revision_and_names_missing_triggers(self):
        from io import StringIO

        from django.core.management import call_command
        with connection.cursor() as cursor:
            cursor.execute("SELECT core_rev_note('t', '1', NULL)")
        rev.settle()
        with connection.cursor() as cursor:
            cursor.execute('ALTER TABLE batches DISABLE TRIGGER core_rev_batches_batch_note')
        out, err = StringIO(), StringIO()
        call_command('core_rev_rebuild', stdout=out, stderr=err)
        self.assertEqual(row('t', 1), (2, 2, None))
        self.assertIn('Every revision is now 2', out.getvalue())
        self.assertIn('core_rev_batches_batch_note', err.getvalue())

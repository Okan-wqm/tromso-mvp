"""A move that carries a withdrawal to another batch and a harvest of that batch take turns (review of S-03, F-2 and
F-7). With the lots, a move of held fish into T-02 holds the fish of T-02 wherever they went afterwards, so it changes
the withdrawal of a batch that is harvested from T-03 at that very moment. Before, the move locked its own batch and
units and the harvest its own: no lock in common, both committed, neither saw the other, and the harvest went to food
inside a withdrawal with no warning, no acknowledgement and no critical line.

Both writes now lock every batch whose withdrawal they can change (farm.stock.services.lock_fish), the batches in one
statement in primary-key order before any unit: checked here with two REAL transactions on two connections, in both
orders, and by the lock statements each write sends. The second class is the schedule in which that lock comes from
the reach alone (verification V-9), with the two mutants that show the race when it is cut out."""
import threading
import time as clock
from datetime import datetime, time
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection, connections, transaction
from django.test import TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext

from .. import withdrawal_gate
from ..health import services as health_services, withdrawal
from ..health.withdrawal import WithdrawalChanged
from ..models import (HandlingAcknowledgement, Medicine, MedicineWithdrawal, ProductionDepartment, Site,
                      StockMovement)
from ..models.site import zone_of
from ..stock import read as stock_read, services as stock_services
from ..stock.dates import local_today
from ..water import services as water_services
from .helpers import going_on, make_facility, point_of
from .test_stock import make_species, make_unit, stock_fish


def outcome(value):
    """What a write did, for an assertion's message: the kind of the operation it recorded, or how it was refused."""
    if isinstance(value, WithdrawalChanged):
        found = value.change
        return (f'asked {value.message_dict}: harvested {len(found.harvested)}, released {len(found.released)}, '
                f'combined {[(each.batch.code, each.unit.code) for each in found.combined]}')
    if isinstance(value, ValidationError):
        return f'refused {value.message_dict}'
    if isinstance(value, Exception):
        return f'failed {type(value).__name__}: {value}'
    return value.kind


class TakeTurnsTests(TransactionTestCase):
    """T-01: A, bathed 6 days ago (harvest from 2 days ahead). T-02: B, never treated; 500 of B went on to T-03 two days
    ago. The move: 500 of A into T-02, dated 3 days ago, which holds B in T-02 and in T-03. The harvest: B out of
    T-03, today."""
    serialized_rollback = True      # the rows migrations write come back for later tests

    def setUp(self):
        self.user = get_user_model().objects.create_superuser('root', 'root@example.com', 'x')
        site = Site.objects.create(name='Bergen', code='BG', timezone='UTC')
        hall = ProductionDepartment.objects.create(site=site, name='Hall A', code='HA')
        self.t1, self.t2, self.t3 = (make_unit(code, hall) for code in ('T-01', 'T-02', 'T-03'))
        self.today = local_today(self.t1)
        salmon = make_species()
        self.a = stock_fish(self.user, self.t1, 2000, '125', 10, species=salmon)
        self.b = stock_fish(self.user, self.t2, 3000, '125', 9, species=salmon)
        self.facility = make_facility()
        bath = Medicine.objects.create(name='Salmosan vet.', kind='lice', administration='bath',
                                       active_substance='azamethiphos', lice_report_code='AZAMETHIPHOS')
        with withdrawal_gate.opened('test fixture: a withdrawal row straight in the database'):
            MedicineWithdrawal.objects.create(medicine=bath, species=None, days=7, safety_margin_pct=0, note='')
        health_services.record_treatment(self.user, units=[self.t1], method='bath', reason='sea_lice',
                                         start_date=self.day(6), end_date=self.day(6), medicine=bath)
        stock_services.record_transfer(self.user, source=self.t2, batch=self.b, day=self.day(2),
                                       legs=[(self.t3, 500)], reason='density')

    def day(self, days_ago):
        from datetime import timedelta
        return self.today - timedelta(days=days_ago)

    def move(self, **fields):
        return stock_services.record_transfer(self.user, source=self.t1, batch=self.a, day=self.day(3),
                                              legs=[(self.t2, 500)], reason='density', **fields)

    def harvest(self, **fields):
        return stock_services.record_harvest(self.user, unit=self.t3, batch=self.b, day=self.today, count=100,
                                             measured_weight_kg=Decimal('13'), facility=self.facility, **fields)

    def one_after_the_other(self, first, second):
        """Runs `first` in a thread up to its first reading of the withdrawals (inside its transaction, its locks
        taken), starts `second` in another, sees whether it WAITS FOR A LOCK, lets the first finish, and returns what
        each did: {'first': result or error, 'second': ..., 'waited': whether the second was blocked on a lock}.

        `waited` is read from the database (`blocked`): a session with a lock asked for and not granted. A write that
        is merely slow is not waiting (verification V-9: the thread still being alive after three seconds counted as
        waiting, also where the two writes had no lock in common). Waiting alone proves nothing (a write can wait
        after it has read): each test asserts what the later write saw."""
        reached, go, done = threading.Event(), threading.Event(), {}
        read = withdrawal.snapshot

        def paused(*args, **kwargs):
            if threading.current_thread().name == 'first' and not reached.is_set():
                reached.set()
                go.wait(30)
            return read(*args, **kwargs)

        def run(name, job):
            try:
                done[name] = job()
            except Exception as error:      # noqa: BLE001 - the outcome is what the test is about
                done[name] = error
            finally:
                connections.close_all()

        with mock.patch.object(withdrawal, 'snapshot', paused):
            one = threading.Thread(target=run, args=('first', first), name='first')
            two = threading.Thread(target=run, args=('second', second), name='second')
            one.start()
            self.assertTrue(reached.wait(30), 'the first write never reached its guard')
            two.start()
            done['waited'] = self.blocked(two)
            go.set()
            one.join(60)
            two.join(60)
        return done

    def blocked(self, thread, seconds=60):
        """Whether the write running in `thread` comes to wait for a lock another session holds: True as soon as the
        database shows a lock asked for and not granted; False when the thread ends without ever waiting (or never
        waits within `seconds`)."""
        deadline = clock.monotonic() + seconds
        while clock.monotonic() < deadline:
            with connection.cursor() as cursor:
                # pg_locks is the whole server's: under --parallel the other workers' databases are on it, and their
                # lock tests wait too (such a wait lets the first write go early: the later write may then see the
                # earlier one, as the downstream mutant once did). Only a session of THIS database counts; a row wait
                # is a wait for a transaction id, a lock with no database, so the session's database is asked.
                cursor.execute('SELECT count(*) FROM pg_locks AS asked JOIN pg_stat_activity AS activity '
                               'ON activity.pid = asked.pid WHERE NOT asked.granted AND asked.pid <> pg_backend_pid() '
                               'AND activity.datname = current_database()')
                if cursor.fetchone()[0]:
                    return True
            if not thread.is_alive():
                return False
            clock.sleep(0.05)
        return False

    def locks(self, job):
        """(the first statement that locks batches, whether it comes before any lock of a unit) of a write."""
        with CaptureQueriesContext(connection) as queries:
            try:
                job()
            except (ValidationError, WithdrawalChanged):
                pass
        found = [query['sql'] for query in queries.captured_queries if 'FOR UPDATE' in query['sql']]
        batches = next(index for index, sql in enumerate(found) if 'FROM "batches"' in sql)
        units = next(index for index, sql in enumerate(found) if 'FROM "tanks"' in sql)
        return found[batches], batches < units

    def answered(self):
        """The tick of the move's own question (it combines held fish with B: asked), read beforehand; nothing is
        written."""
        with transaction.atomic():
            try:
                self.move()
            except WithdrawalChanged as asked:
                return asked.change.fingerprint
            transaction.set_rollback(True)
        return None

    def test_the_harvest_waits_for_the_move_and_then_sees_the_withdrawal_it_brought(self):
        seen = self.answered()
        done = self.one_after_the_other(lambda: self.move(withdrawal_ack=seen), self.harvest)
        self.assertTrue(done['waited'], 'the harvest did not wait for the move: no lock in common')
        self.assertEqual(done['first'].kind, 'transfer')
        self.assertIsInstance(done['second'], ValidationError)
        self.assertEqual(done['second'].message_dict,
                         {'handling_ack': ['Tick the box to go on despite these warnings.']})
        self.assertFalse(StockMovement.objects.filter(kind='harvest').exists())

    def test_the_move_waits_for_the_harvest_and_is_then_asked_about_it(self):
        seen = self.answered()                                 # of the warnings before the harvest existed
        done = self.one_after_the_other(self.harvest, lambda: self.move(withdrawal_ack=seen))
        self.assertTrue(done['waited'], 'the move did not wait for the harvest: no lock in common')
        self.assertEqual(done['first'].kind, 'harvest')
        self.assertIsInstance(done['second'], WithdrawalChanged)
        self.assertEqual([found.operation_id for found in done['second'].change.harvested], [done['first'].pk])
        self.assertFalse(StockMovement.objects.filter(kind='transfer_in', unit=self.t2).exists())
        self.assertFalse(HandlingAcknowledgement.objects.exists())

    def test_both_lock_the_harvested_batch_first_in_one_statement_before_any_unit(self):
        """The order that keeps two such writes from a deadlock: each takes its batches in ONE statement, in
        primary-key order, and only then its units."""
        for job in (self.move, self.harvest):
            statement, first = self.locks(job)
            self.assertIn(self.b.pk.hex, statement.replace('-', ''))
            self.assertIn('ORDER BY', statement)
            self.assertTrue(first)


class TwoHopsTests(TakeTurnsTests):
    """The verifier's schedule (V-9): as above, and C in T-04; 200 of the B fish of T-03 went on to T-04 yesterday and
    300 of C went on to T-05 today. The harvest: C out of T-05, today. C was never in a unit of the move (T-01, T-02)
    nor in T-03, so the only lock the two writes have in common is the one `_reach` adds (read.downstream): with it
    cut out, the tests of this class fail, and the last two show what happens then."""

    def setUp(self):
        super().setUp()
        hall = self.t1.production_department
        self.t4, self.t5 = make_unit('T-04', hall), make_unit('T-05', hall)
        self.c = stock_fish(self.user, self.t4, 3000, '125', 9, species=self.a.species)
        stock_services.record_transfer(self.user, source=self.t3, batch=self.b, day=self.day(1),
                                       legs=[(self.t4, 200)], reason='density')
        stock_services.record_transfer(self.user, source=self.t4, batch=self.c, day=self.today,
                                       legs=[(self.t5, 300)], reason='density')

    def harvest(self, **fields):
        return stock_services.record_harvest(self.user, unit=self.t5, batch=self.c, day=self.today, count=100,
                                             measured_weight_kg=Decimal('13'), facility=self.facility, **fields)

    def test_the_harvested_batch_was_never_in_a_unit_of_the_move(self):
        presence = stock_read.Presence.of_batches({self.c.pk})
        self.assertEqual(set(presence.units[self.c.pk]), {self.t4.pk, self.t5.pk})

    def test_both_lock_the_harvested_batch_first_in_one_statement_before_any_unit(self):
        for job in (self.move, self.harvest):
            statement, first = self.locks(job)
            self.assertIn(self.c.pk.hex, statement.replace('-', ''))
            self.assertTrue(first)

    def unseen(self, cut):
        """The harvest first, then the move, with a part of the reach cut out: what each did, and the harvests left
        inside a withdrawal with no acknowledgement."""
        seen = self.answered()
        with cut:
            done = self.one_after_the_other(self.harvest, lambda: self.move(withdrawal_ack=seen))
        return done, [found.operation_id for found in withdrawal.harvests_inside()]

    def test_without_the_reach_the_two_writes_do_not_wait_and_the_harvest_goes_unseen(self):
        """What the lock is for, shown by taking it away: the tests above cannot pass without `_reach`. (The move
        still comes to wait at its very end: the acknowledgement row it stores names the harvested batch, a foreign
        key the harvest's lock holds. By then it has read, and seen no harvest: a wait is no proof, what the later
        write SAW is.)"""
        done, inside = self.unseen(mock.patch.object(
            stock_services, '_reach', lambda unit_ids, batch_ids, first: set(batch_ids)))
        self.assertEqual((outcome(done['first']), outcome(done['second'])), ('harvest', 'transfer'))
        self.assertEqual(inside, [done['first'].pk])                   # inside a withdrawal, and nobody was asked
        self.assertFalse(HandlingAcknowledgement.objects.filter(operation=done['first']).exists())

    def test_without_the_batches_downstream_neither(self):
        done, inside = self.unseen(mock.patch.object(stock_read, 'downstream', lambda found, unit_ids, first=None: set()))
        self.assertEqual((outcome(done['first']), outcome(done['second'])), ('harvest', 'transfer'))
        self.assertEqual(inside, [done['first'].pk])


class WhatAWriteLocksTests(TestCase):
    """TakeTurnsTests' farm, in one transaction: the batches a write locks, read from the lock statements it sends (each
    write rolled back). Not the race itself (TakeTurnsTests): which batches are in the one statement taken first."""
    setUp = TakeTurnsTests.setUp
    day = TakeTurnsTests.day
    move = TakeTurnsTests.move

    def first_batch_lock(self, job):
        """(the first statement of the write that locks batches, without dashes; whether it comes before any lock of
        a unit). The write is rolled back, whatever it did."""
        with CaptureQueriesContext(connection) as queries, transaction.atomic():
            try:
                job()
            except (ValidationError, WithdrawalChanged):
                pass
            transaction.set_rollback(True)
        found = [query['sql'] for query in queries.captured_queries if 'FOR UPDATE' in query['sql']]
        batches = next(index for index, sql in enumerate(found) if 'FROM "batches"' in sql)
        units = next(index for index, sql in enumerate(found) if 'FROM "tanks"' in sql)
        return found[batches].replace('-', ''), batches < units

    def test_a_write_dated_today_about_the_treated_tank_locks_the_fish_its_withdrawal_holds_elsewhere(self):
        """Verification V-9, `held_with`: after the move, A's withdrawal holds B in T-02 and in T-03; yesterday the
        500 A went on from T-02 to T-04, so no fish of A is beside B today. A water sample in T-01 today can change A's
        end (a degree-day medicine) and so B's: it must lock B, which a harvest of B locks. B was never in T-01 and the
        fish of T-01 share no unit with B from today on (read.downstream), so only `held_with` brings B in: with it
        cut out, B is not locked, and the sample and a harvest of B no longer take turns."""
        going_on(self.move)
        t4 = make_unit('T-04', self.t1.production_department)
        stock_services.record_transfer(self.user, source=self.t2, batch=self.a, day=self.day(1), legs=[(t4, 500)],
                                       reason='density')
        site = self.t1.production_department.site

        def sample():
            return water_services.record(self.user, point=point_of(self.t1), source='manual',
                                         measured_at=datetime.combine(self.today, time(9), tzinfo=zone_of(site)),
                                         values={'temperature_c': Decimal('8')})
        statement, _first = self.first_batch_lock(sample)
        self.assertIn(self.b.pk.hex, statement)
        with mock.patch.object(withdrawal, 'held_with', lambda *args, **kwargs: set()):
            statement, _first = self.first_batch_lock(sample)
        self.assertIn(self.a.pk.hex, statement)
        self.assertNotIn(self.b.pk.hex, statement)

    def test_a_grading_locks_like_every_other_write(self):
        """Verification W-3: a grading locked its own batch and its units first, then (in `_commit`) the batches it
        can reach: the reverse of every other write's order, so a grading and a harvest of B crossing could deadlock.
        Now it takes its batches, B among them, in one statement before any unit, as a transfer does."""
        def grade():
            return stock_services.record_grading(self.user, source=self.t1, batch=self.a, day=self.day(3),
                                                 outputs=[(self.t2, 500, Decimal('130'), 'large')],
                                                 remainder_avg_weight_g=Decimal('120'))
        for job in (grade, self.move):
            statement, first = self.first_batch_lock(job)
            self.assertIn(self.b.pk.hex, statement)
            self.assertIn('ORDER BY', statement)
            self.assertTrue(first)

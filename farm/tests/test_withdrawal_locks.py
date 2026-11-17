"""A move that carries a withdrawal to another batch and a harvest of that batch take turns (review of S-03, F-2 and
F-7). With the lots, a move of held fish into T-02 holds the fish of T-02 wherever they went afterwards, so it changes
the withdrawal of a batch that is harvested from T-03 at that very moment. Before, the move locked its own batch and
units and the harvest its own: no lock in common, both committed, neither saw the other, and the harvest went to food
inside a withdrawal with no warning, no acknowledgement and no critical line.

Both writes now lock every batch whose withdrawal they can change (farm.stock.services.lock_fish), the batches in one
statement in primary-key order before any unit: checked here with two REAL transactions on two connections, in both
orders, and by the lock statements each write sends."""
import threading
import time as clock
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection, connections, transaction
from django.test import TransactionTestCase
from django.test.utils import CaptureQueriesContext

from .. import withdrawal_gate
from ..health import services as health_services, withdrawal
from ..health.withdrawal import WithdrawalChanged
from ..models import (HandlingAcknowledgement, Medicine, MedicineWithdrawal, ProductionDepartment, Site,
                      StockMovement)
from ..stock import services as stock_services
from ..stock.dates import local_today
from .helpers import make_facility
from .test_stock import make_species, make_unit, stock_fish


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
        taken), starts `second` in another, sees that it WAITS, lets the first finish, and returns what each did:
        {'first': result or error, 'second': ..., 'waited': whether the second was still waiting}."""
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
            clock.sleep(3)                                     # the second reaches its locks meanwhile
            done['waited'] = two.is_alive()
            go.set()
            one.join(60)
            two.join(60)
        return done

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
        def locks(job):
            with CaptureQueriesContext(connection) as queries:
                try:
                    job()
                except (ValidationError, WithdrawalChanged):
                    pass
            found = [query['sql'] for query in queries.captured_queries if 'FOR UPDATE' in query['sql']]
            batches = next(index for index, sql in enumerate(found) if 'FROM "batches"' in sql)
            units = next(index for index, sql in enumerate(found) if 'FROM "tanks"' in sql)
            return found[batches], batches < units

        for job in (self.move, self.harvest):
            statement, first = locks(job)
            self.assertIn(self.b.pk.hex, statement.replace('-', ''))
            self.assertIn('ORDER BY', statement)
            self.assertTrue(first)

"""The store's one write path (inventory/services.py) with worked numbers: a delivery, an issue, a transfer, a
write-off, a return, a count and its variance, voids; the feeding drawn first expired first out over two lots,
a shortfall shown and never refused; the rules of lots, locations, suppliers, dates and the form's token; the
integrity check."""
import io
import threading
from datetime import timedelta

from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.test import TransactionTestCase

from core.models import AuditLog
from farm.feeding import services as feeding_services
from farm.models import Feed, Tank
from farm.models.supplier import SupplyCategory
from farm.tests.helpers import correction_window, make_species, may_record, stock_fish

from .. import integrity, read, services
from ..models import InventoryItem, InventoryLine, InventoryLot, InventoryOperation, StorageLocation
from .helpers import D, StoreFixtures, StoreTestCase


class LedgerTests(StoreTestCase):
    def test_delivery_issue_transfer_write_off_return_count_and_void_with_worked_numbers(self):
        delivery = self.receive('1000', days_ago=10, cost='12.5', currency='nok', reference='DN-4711')
        lot = self.lot()
        issued = services.issue(self.user, location=self.store, lot=lot, day=self.day(9), quantity=D(50),
                                reason='samples')
        moved = services.transfer(self.user, source=self.store, lot=lot, destination=self.silo, day=self.day(8),
                                  quantity=D(300))
        services.write_off(self.user, location=self.store, lot=lot, day=self.day(7), quantity=D(20), reason='damaged')
        before_return = self.on_hand(self.store, day=self.day(7))
        services.return_to_supplier(self.user, location=self.store, lot=lot, day=self.day(6), quantity=D(100),
                                    supplier=self.mill, reference='RN-1')
        # 1000 − 50 − 300 − 20 = 630 before the return; the return takes 100 out (the source added it, STR-03).
        self.assertEqual((before_return, self.on_hand(self.store, day=self.day(6))), (630, 530))
        counted = services.count(self.user, location=self.store, day=self.day(5), lines=[(lot, D(520))])
        self.assertEqual(read.count_variances(counted), [(lot, D(530), D(520), D(-10))])
        self.assertEqual((self.on_hand(self.store), self.on_hand(self.silo)), (520, 300))

        # The rows as stored: one line a departure, a pair for the transfer, the cost on the delivered line.
        self.assertEqual(list(delivery.lines.values_list('kind', 'quantity', 'unit_cost', 'currency')),
                         [('in', D(1000), D('12.5'), 'NOK')])
        self.assertEqual((delivery.supplier, delivery.reference), (self.mill, 'DN-4711'))
        self.assertEqual(sorted(moved.lines.values_list('kind', 'quantity', 'location__code', 'pair')),
                         [('transfer_in', D(300), 'SI-1', 1), ('transfer_out', D(-300), 'WH-1', 1)])
        self.assertEqual(list(issued.lines.values_list('kind', 'quantity')), [('out', D(-50))])
        self.assertEqual(issued.reason, 'samples')

        # A later issue from the silo needs the transfer: voiding it is refused, naming the issue.
        taken = services.issue(self.user, location=self.silo, lot=lot, day=self.day(4), quantity=D(200),
                               reason='treatment')
        errors = self.refused(services.void, self.user, moved, 'wrong silo')
        self.assertIn('The issue of', errors['__all__'][0])
        self.assertIn('SI-1', errors['__all__'][0])
        services.void(self.user, taken, 'typed in the wrong row')
        services.void(self.user, moved, 'wrong silo')
        moved.refresh_from_db()
        self.assertEqual((moved.is_deleted, moved.void_reason), (True, 'wrong silo'))
        # The count still sets the store to 520 at the end of its day; the silo holds nothing again.
        self.assertEqual((self.on_hand(self.store), self.on_hand(self.silo)), (520, 0))
        self.assertEqual(AuditLog.objects.filter(action='void').count(), 2)
        self.assertStoreAddsUp()

    def test_a_departure_is_checked_against_every_later_day(self):
        self.receive('100', days_ago=10)
        lot = self.lot()
        services.write_off(self.user, location=self.store, lot=lot, day=self.day(3), quantity=D(80), reason='spilled')
        errors = self.refused(services.issue, self.user, location=self.store, lot=lot, day=self.day(5),
                              quantity=D(30), reason='samples')
        self.assertIn('would be left without its stock', errors['__all__'][0])
        errors = self.refused(services.write_off, self.user, location=self.store, lot=lot, day=self.day(1),
                              quantity=D(25), reason='spilled')
        self.assertEqual(errors['quantity'], [f'Only 20 kg of {self.feed}, lot L1, are in WH-1 on '
                                              f'{read_date(self.day(1))}.'])
        self.assertEqual(InventoryOperation.objects.count(), 2)

    def test_voiding_a_delivery_voids_its_lot_and_a_new_delivery_may_name_it_again(self):
        delivery = self.receive('100', expiry_in=None)
        services.void(self.user, delivery, 'wrong expiry')
        self.assertFalse(InventoryLot.objects.exists())
        self.assertTrue(InventoryLot.all_objects.get().is_deleted)
        self.receive('100', expiry_in=30)
        self.assertEqual(self.lot().expiry_date, self.today + timedelta(days=30))
        self.assertStoreAddsUp()

    def test_a_count_finds_a_lot_the_book_did_not_have(self):
        self.receive('100')
        services.count(self.user, location=self.silo, day=self.day(2), lines=[],
                       found=[(self.feed, 'F-9', None, D('42.5')), (self.feed, 'L1', None, D(10))])
        self.assertEqual((self.on_hand(self.silo, 'F-9'), self.on_hand(self.silo, 'L1')), (D('42.5'), 10))
        self.assertEqual(self.on_hand(self.store, 'L1'), 100)
        self.assertStoreAddsUp()


def read_date(day):
    from farm.stock.dates import shown_date
    return shown_date(day)


class FeedingTests(StoreTestCase):
    """Feed consumption is read from the feeding records of the site's units, first expired first out over the
    site's lots; a feeding is never refused, a shortfall shows as feeding beyond the book."""

    def setUp(self):
        super().setUp()
        # 100 m³ at 50 kg/m³: 5 t.
        self.unit = Tank.objects.create(name='Tank 1', code='T-01', kind='tank', production_department=self.hall,
                                        water_type='freshwater', status='preparing', shape='rectangular',
                                        material='fiberglass', length=10, width=5, depth=2, max_density_kg_m3=50)
        stock_fish(self.user, self.unit, count=8000, weight='500', days_ago=20, species=make_species())   # 4 t

    def feed_fish(self, kilos, days_ago):
        may_record(self.user, 'add_feedingrecord')  # the feeding service asks (L-6)
        return feeding_services.record_feeding(self.user, unit=self.unit, day=self.day(days_ago), feed=self.feed,
                                               amount_kg=D(kilos), ack=True)

    def test_feeding_draws_two_lots_first_expired_first_out_and_a_shortfall_is_shown_never_refused(self):
        self.receive('500', days_ago=10, number='LATE', expiry_in=40, location=self.silo)
        self.receive('300', days_ago=10, number='SOON', expiry_in=20, location=self.silo)
        self.feed_fish('400', days_ago=5)            # 300 of SOON, 100 of LATE
        self.assertEqual((self.on_hand(self.silo, 'SOON'), self.on_hand(self.silo, 'LATE')), (0, 400))
        record = self.feed_fish('600', days_ago=4)   # 400 left: recorded all the same
        self.assertFalse(record.is_deleted)
        summary = read.overview()
        entry = next(item for item in summary.site_items if item.site == self.bergen)
        self.assertEqual((entry.on_hand, entry.uncovered, entry.uncovered_since), (0, 200, self.day(4)))
        self.assertEqual(entry.fed_week, 1000)
        # The missing delivery, recorded on its day, covers it (owner decision Q-S1).
        self.receive('250', days_ago=4, number='MISSED', expiry_in=50, location=self.store)
        entry = next(item for item in read.overview().site_items if item.site == self.bergen)
        self.assertEqual((entry.on_hand, entry.uncovered), (50, 0))
        self.assertEqual(entry.cover_days, D(50) / (D(1000) / 7))
        self.assertStoreAddsUp()

    def test_a_departure_is_never_refused_because_of_the_feeding(self):
        self.receive('100', days_ago=10)
        self.feed_fish('80', days_ago=6)
        services.write_off(self.user, location=self.store, lot=self.lot(), day=self.day(3), quantity=D(100),
                           reason='expired')
        entry = next(item for item in read.overview().site_items if item.site == self.bergen)
        self.assertEqual((entry.on_hand, entry.uncovered), (0, 80))

    def test_feeding_at_another_site_draws_nothing_here(self):
        self.receive('100', days_ago=10, location=self.far)
        self.feed_fish('30', days_ago=2)
        self.assertEqual(self.on_hand(self.far), 100)


class RuleTests(StoreTestCase):
    def test_a_known_lot_is_reused_and_another_expiry_is_refused(self):
        self.receive('100', number='L1', expiry_in=60)
        self.receive('50', number='l1', expiry_in=None, location=self.silo)       # any case, expiry taken from it
        self.assertEqual(InventoryLot.objects.count(), 1)
        errors = self.refused(self.receive, '10', number='L1', expiry_in=61)
        self.assertIn('is recorded with the expiry date', errors['lines'][0])
        self.receive('10', number='', expiry_in=10)
        self.receive('10', number='', expiry_in=10, location=self.silo)
        self.receive('10', number='', expiry_in=11)
        self.assertEqual(InventoryLot.objects.filter(number='').count(), 2)    # one unnumbered lot per expiry

    def test_lot_number_and_expiry_are_required_where_the_category_needs_them(self):
        services._check_lot(SupplyCategory.FEED, '', None)
        errors = self.refused(services._check_lot, SupplyCategory.MEDICINES, 'M-1', None)
        self.assertIn('needs its number and its expiry date', errors['lines'][0])

    def test_inactive_and_deleted_locations_and_the_dates(self):
        self.store.status = StorageLocation.Status.INACTIVE
        self.store.save()
        self.assertIn('is inactive', self.refused(self.receive, '10')['location'][0])
        self.receive('10', location=self.silo)
        lot = self.lot()
        self.assertIn('is inactive', self.refused(
            services.transfer, self.user, source=self.silo, lot=lot, destination=self.store, day=self.day(1),
            quantity=D(5))['destination'][0])
        self.assertIn('future', self.refused(self.receive, '10', days_ago=-1, location=self.silo)['date'][0])
        self.assertIn('31 days back', self.refused(self.receive, '10', days_ago=32, location=self.silo)['date'][0])
        with correction_window(60):
            self.assertIn('60 days back', self.refused(self.receive, '10', days_ago=61, location=self.silo)['date'][0])
        self.silo.soft_delete(self.user)
        self.assertIn('is deleted', self.refused(self.receive, '10', location=self.silo)['location'][0])

    def test_the_supplier_must_supply_the_items_category_and_keeps_it(self):
        errors = self.refused(self.receive, '10', supplier=self.vet)
        self.assertIn('is not a supplier of feed', errors['supplier'][0])
        self.receive('10')
        self.mill.supplies = ['transport']
        with self.assertRaises(Exception) as caught:
            self.mill.full_clean()
        self.assertIn('1 delivery or return of the store names it for “Feed”', str(caught.exception))

    def test_a_form_sent_twice_records_once(self):
        token = __import__('uuid').uuid4()
        first = self.receive('10', token=token)
        with self.assertRaises(services.AlreadyRecorded) as caught:
            self.receive('10', token=token)
        self.assertEqual(caught.exception.operation, first)
        self.assertEqual(InventoryOperation.objects.count(), 1)

    def test_a_transfer_between_sites_is_dated_on_both_clocks(self):
        self.receive('100', days_ago=10)
        moved = services.transfer(self.user, source=self.store, lot=self.lot(), destination=self.far,
                                  day=self.day(2), quantity=D(40))
        self.assertEqual((self.on_hand(self.store), self.on_hand(self.far)), (60, 40))
        self.assertIn('Choose another location', self.refused(
            services.transfer, self.user, source=self.store, lot=self.lot(), destination=self.store,
            day=self.day(1), quantity=D(1))['destination'][0])
        self.assertEqual(moved.lines.count(), 2)

    def test_the_database_refuses_what_the_service_would(self):
        self.receive('10')
        line = InventoryLine.objects.get()
        for change in ({'quantity': D(-1)}, {'kind': 'out'}, {'currency': 'NOK'}, {'pair': 1}):
            with self.subTest(change=change), self.assertRaises(IntegrityError), transaction.atomic():
                InventoryLine.objects.filter(pk=line.pk).update(**change)
        operation = InventoryOperation.objects.get()
        for change in ({'supplier': None}, {'reason': 'expired'}, {'location': self.store}):
            with self.subTest(change=change), self.assertRaises(IntegrityError), transaction.atomic():
                InventoryOperation.objects.filter(pk=operation.pk).update(**change)
        with self.assertRaises(IntegrityError), transaction.atomic():
            InventoryItem.objects.create(feed=None, unit='kg')
        other = Feed.objects.create(name='Starter 1', code='ST-1', feed_type='starter')
        with self.assertRaises(IntegrityError), transaction.atomic():
            InventoryItem.objects.create(feed=other, unit='units')


class IntegrityTests(StoreTestCase):
    def test_check_inventory_reports_rows_that_got_past_the_service(self):
        self.receive('100')
        lot = self.lot()
        taken = services.issue(self.user, location=self.store, lot=lot, day=self.day(1), quantity=D(40),
                               reason='samples')
        call_command('check_inventory', stdout=io.StringIO())
        InventoryLine.objects.filter(operation=taken).update(quantity=D(-140))
        InventoryOperation.objects.filter(pk=taken.pk).update(kind='write_off', reason='spilled')
        found = integrity.problems()
        self.assertTrue(any('takes its lot below 0' in problem for problem in found), found)
        with self.assertRaisesMessage(Exception, 'problem(s) in the store'):
            call_command('check_inventory', stdout=io.StringIO())


class ConcurrencyTests(StoreFixtures, TransactionTestCase):
    """Two write-offs of the same stock at once: the item's lock makes them take turns, so the second sees the
    first and only one passes."""

    serialized_rollback = True      # the rows migrations write (the equipment types) come back for later tests

    def test_two_departures_at_once_cannot_take_the_same_stock(self):
        case = self
        case.receive('100')
        lot = case.lot()
        results, gate = [], threading.Barrier(2)

        def take():
            gate.wait()
            try:
                services.write_off(case.user, location=case.store, lot=lot, day=case.day(1), quantity=D(60),
                                   reason='spilled')
                results.append('ok')
            except Exception as error:     # noqa: BLE001  the refusal is the expected outcome of one of them
                results.append(type(error).__name__)
            finally:
                connection.close()

        threads = [threading.Thread(target=take) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(results), ['ValidationError', 'ok'])
        self.assertEqual(InventoryOperation.objects.filter(kind='write_off').count(), 1)
        self.assertEqual(case.on_hand(case.store), 40)

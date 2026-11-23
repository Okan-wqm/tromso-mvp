"""The opening balance (F-197): the fish already on the farm when it starts using the platform, registered by the platform
owner with their real stocking date and year class beyond the correction window, the count and weight of the takeover day
inside it, and a source document; every read of the ledger takes them as stock that was already there."""
import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.urls import reverse

from core import access, navigation
from core.models import AuditLog

from ..feeding import read as feeding_read
from ..models import Batch, OpeningBalance, StockOperation
from ..stock import integrity, read, services
from .helpers import OPENING_WAY_OUT, WINDOW_WAY_OUT, role
from .test_stock import STOCK_KEEPER, StockTestCase

OWNER = ('view_platformsettings', 'change_platformsettings', 'view_openingbalance')


class OpeningBalanceTestCase(StockTestCase):
    def setUp(self):
        super().setUp()
        self.owner = get_user_model().objects.create_user('eier', 'eier@example.com', 'x')
        self.owner.groups.add(role('Platform owner', *OWNER, *STOCK_KEEPER))
        self.stocked_on = self.day(400)

    def open(self, user=None, lines=None, **fields):
        values = {'species': self.salmon, 'input_stage': 'smolt', 'origin': 'own_hatchery', 'stocked_on': self.stocked_on,
                  'day': self.day(2), 'year_class': self.stocked_on.year, 'document': 'Old system export 2026-11-01',
                  'lines': lines or [(self.t1, 1500, Decimal('850'))], **fields}
        return services.record_opening_balance(user or self.owner, **values)

    def batch(self):
        return Batch.objects.get()


class RulesTests(OpeningBalanceTestCase):
    def test_only_the_platform_owner_registers_one(self):
        with self.assertRaises(PermissionDenied):
            self.open(self.user)                          # a stock keeper may stock, not take over
        self.assertEqual(Batch.objects.count(), 0)
        self.open()
        self.assertEqual(Batch.objects.count(), 1)

    def test_the_real_stocking_date_may_be_beyond_the_window_the_takeover_day_may_not(self):
        self.assertEqual(self.refused(self.open, day=self.day(32)),
                         {'date': [f'Operations can be dated at most 31 days back. {WINDOW_WAY_OUT}']})
        self.assertEqual(self.refused(self.open, stocked_on=self.day(1)),
                         {'stocked_on': ['The fish were stocked on or before the takeover day.']})
        self.open()
        batch = self.batch()
        self.assertEqual((batch.input_date, batch.code), (self.stocked_on, f'B-{self.stocked_on.year}-001'))
        self.assertEqual(StockOperation.objects.get().date, self.day(2))

    def test_the_year_class_and_the_source_document_are_required(self):
        self.assertEqual(self.refused(self.open, year_class=None),
                         {'year_class': ['Give the year class of fish taken over.']})
        self.assertEqual(self.refused(self.open, document='  '),
                         {'document': ['Say which document the counts come from.']})


class LedgerTests(OpeningBalanceTestCase):
    def test_the_unit_holds_the_fish_at_their_weight_from_the_takeover_day(self):
        self.open()
        stock = read.stock_of([self.t1])[self.t1.pk]
        self.assertEqual((stock.count, stock.biomass_kg), (1500, Decimal('1275')))
        self.assertEqual(read.stock_on([self.t1], self.day(3)), {})       # nothing before the takeover day
        self.assertEqual(self.fish(self.t1), 1500)

    def test_days_stocked_count_from_the_real_stocking_date_and_the_weight_is_measured_on_the_takeover_day(self):
        self.open()
        share = read.stock_of([self.t1])[self.t1.pk].shares[0]
        self.assertEqual((share.since, share.last_weighed), (self.stocked_on, self.day(2)))
        self.assertEqual(read.stock_of([self.t1])[self.t1.pk].days(self.today), 400)

    def test_the_feeding_projection_starts_from_the_takeover_weight(self):
        self.open()
        projection = feeding_read.project([self.t1.pk], days=[(self.t1.pk, self.today)])
        estimate = next(item for item in projection.days[(self.t1.pk, self.today)].shares)
        self.assertEqual(estimate.measured_on, self.day(2))

    def test_check_stock_accepts_it_and_still_finds_a_stocking_off_its_date(self):
        self.open()
        self.assertEqual(integrity.problems(), [])
        other = self.stock(self.t2)
        Batch.objects.filter(pk=other.pk).update(input_date=self.day(20))
        self.assertEqual(len([problem for problem in integrity.problems() if 'is not on the stocking date' in problem]), 1)
        Batch.objects.filter(pk=self.batch_of(self.t1).pk).update(input_date=self.day(1))
        self.assertTrue(any('opening balance' in problem and 'after its takeover day' in problem
                            for problem in integrity.problems()))

    def batch_of(self, unit):
        return Batch.objects.get(movements__unit=unit)

    def test_voiding_it_voids_its_batch(self):
        operation = self.open()
        services.void(self.owner, operation, 'Counted the wrong tank')
        self.assertTrue(Batch.all_objects.get().is_deleted)
        self.assertEqual(self.fish(self.t1), 0)
        self.assertEqual(OpeningBalance.objects.count(), 0)                  # out of sight with its operation
        self.assertEqual(OpeningBalance.all_objects.count(), 1)

    def test_it_is_named_and_logged_as_an_opening_balance(self):
        operation = self.open()
        self.assertEqual(str(operation), f'Opening balance {self.day(2).isoformat()}')
        entry = AuditLog.objects.get(entity_type='stock operation')
        self.assertTrue(entry.entity_label.startswith('Opening balance · T-01 · B-'), entry.entity_label)
        self.assertEqual(entry.severity, AuditLog.Severity.CRITICAL)
        self.assertEqual(entry.changes['Source document'], [None, 'Old system export 2026-11-01'])
        self.assertEqual(entry.changes['Stocked on'], [None, self.stocked_on.isoformat()])


class PageTests(OpeningBalanceTestCase):
    def data(self, **values):
        data = {'token': str(uuid.uuid4()), 'species': str(self.salmon.pk), 'input_stage': 'smolt',
                'origin': 'own_hatchery', 'input_date': self.stocked_on.isoformat(), 'day': self.day(2).isoformat(),
                'count': '1500', 'avg_weight_g': '850', 'year_class': str(self.stocked_on.year),
                'document': 'Count sheet 1 Nov', 'provenance': '', 'supplier': '', 'supplier_batch_ref': '',
                'strain': '', 'name': '', 'expected_harvest_date': '', 'notes': '',
                'units-TOTAL_FORMS': '1', 'units-INITIAL_FORMS': '0', 'units-MIN_NUM_FORMS': '0',
                'units-MAX_NUM_FORMS': '1000', 'units-0-unit': str(self.t1.pk), 'units-0-count': '1500'}
        return {**data, **values}

    def test_it_sits_under_company_administration_and_is_read_with_its_own_right(self):
        place = navigation.place('farm.view_openingbalance')
        self.assertEqual((place.workspace.key, str(place.group.label)), ('company', 'Administration'))
        area = next(area for area in access.areas() if area.model == 'farm.OpeningBalance')
        self.assertEqual(area.actions, ('view',))

    def test_the_list_and_the_register_form_are_the_owners(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('farm:opening_balances')).status_code, 403)
        self.assertEqual(self.client.post(reverse('farm:opening_balance_create'), self.data()).status_code, 403)
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(reverse('farm:opening_balances')), reverse('farm:opening_balance_create'))
        response = self.client.post(reverse('farm:opening_balance_create'), self.data())
        self.assertEqual(response.status_code, 302)
        page = self.client.get(reverse('farm:opening_balances'))
        self.assertContains(page, 'Count sheet 1 Nov')
        self.assertContains(page, self.batch().code)

    def test_a_reader_without_the_owners_right_sees_the_list_but_not_the_register_link(self):
        reader = get_user_model().objects.create_user('les', 'les@example.com', 'x')
        reader.groups.add(role('Reader', 'view_openingbalance'))
        self.client.force_login(reader)
        page = self.client.get(reverse('farm:opening_balances'))
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, reverse('farm:opening_balance_create'))

    def test_the_form_says_what_is_wrong(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse('farm:opening_balance_create'), self.data(day=self.day(40).isoformat()))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.context['form'].errors['day'],
                         [f'Operations can be dated at most 31 days back. {WINDOW_WAY_OUT}'])
        response = self.client.post(reverse('farm:opening_balance_create'), self.data(document=''))
        self.assertIn('document', response.context['form'].errors)
        self.assertEqual(Batch.objects.count(), 0)

    def test_registering_twice_with_one_form_registers_once(self):
        self.client.force_login(self.owner)
        data = self.data()
        self.client.post(reverse('farm:opening_balance_create'), data)
        self.client.post(reverse('farm:opening_balance_create'), data)
        self.assertEqual(Batch.objects.count(), 1)


class ExistingStockingTests(OpeningBalanceTestCase):
    def test_a_normal_stocking_keeps_its_rules(self):
        batch = self.stock(days_ago=5)
        share = read.stock_of([self.t1])[self.t1.pk].shares[0]
        self.assertEqual((share.since, share.last_weighed), (self.day(5), None))
        self.assertEqual(str(StockOperation.objects.get(movements__batch=batch)), f'Stocking {self.day(5).isoformat()}')
        self.assertEqual(batch.input_date, self.day(5))

    def test_the_window_still_bounds_a_normal_stocking(self):
        self.assertEqual(self.refused(self.stock, days_ago=32), {'date': [
            f'Operations can be dated at most 31 days back. {OPENING_WAY_OUT} {WINDOW_WAY_OUT}']})

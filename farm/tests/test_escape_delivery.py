"""The escape and the live delivery out of the company as stock operations (OUR-03, OUR-04, D-10): their service and dialog,
the record each keeps beside its operation, the fold and `check_stock`, the void, and the database's checks."""
import uuid
from datetime import time
from decimal import Decimal

from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.urls import reverse

from core.models import AuditLog

from ..models import DeliveryRecord, EscapeRecord, StockMovement, StockOperation, Tank
from ..stock import integrity, read, services
from .test_stock import StockTestCase


def setUpModule():
    call_command('compile_catalogs', verbosity=0)


class EscapeTests(StockTestCase):
    def setUp(self):
        super().setUp()
        self.batch = self.stock(count=2000, weight='125', days_ago=10)          # 250 kg in T-01

    def escape(self, count=300, days_ago=2, **fields):
        return services.record_escape(self.user, unit=self.t1, batch=self.batch, day=self.day(days_ago), count=count,
                                      cause=fields.pop('cause', 'A net tore in the storm'), **fields)

    def test_an_escape_takes_the_fish_out_at_the_average_with_its_record_and_is_logged(self):
        operation = self.escape(found_time=time(6, 15), health_status='Treated for lice a week before', recaptured=12,
                                notes='Storm, wind 20 m/s')
        line = operation.movements.get()
        self.assertEqual((operation.kind, line.kind, line.count_delta, line.reason), ('adjustment', 'adjustment', -300,
                                                                                      'escape'))
        record = EscapeRecord.objects.get()
        self.assertEqual((record.operation, record.found_time, record.suspected, record.cause, record.health_status,
                          record.recaptured), (operation, time(6, 15), False, 'A net tore in the storm',
                                               'Treated for lice a week before', 12))
        stock = read.stock_of([self.t1])[self.t1.pk]
        self.assertEqual((stock.count, stock.biomass_kg, stock.avg_weight_g), (1700, Decimal('212.5'), 125))
        logged = AuditLog.objects.filter(entity_type='stock operation').latest('created_at')
        self.assertEqual(logged.changes['Cause'], [None, 'A net tore in the storm'])
        self.assertEqual(logged.changes['Fish recaptured'], [None, '12'])
        self.assertStockAddsUp()

    def test_a_suspected_escape_is_the_same_with_the_flag(self):
        self.escape(suspected=True)
        self.assertTrue(EscapeRecord.objects.get().suspected)

    def test_what_the_service_refuses(self):
        self.assertEqual(self.refused(self.escape, cause='  ')['cause'], ['Say what caused it, or what is thought to '
                                                                           'have.'])
        self.assertIn('count', self.refused(self.escape, count=5000))
        self.assertFalse(StockOperation.objects.filter(kind='adjustment').exists())

    def test_a_void_brings_the_fish_back_and_the_record_goes_with_it(self):
        operation = self.escape()
        services.void(self.user, operation, 'Counted twice')
        self.assertEqual(read.stock_of([self.t1])[self.t1.pk].count, 2000)
        self.assertFalse(EscapeRecord.objects.exists())
        self.assertTrue(EscapeRecord.all_objects.exists())              # kept, out of sight with its operation
        self.assertStockAddsUp()

    def test_the_dialog_records_it_and_the_drawer_tells_what_happened(self):
        url = reverse('farm:stock_escape', args=[self.t1.pk])
        form = self.client.get(url, headers={'X-Modal': '1'})
        self.assertContains(form, 'Record escape')
        self.assertIn('suspected', form.context['form'].fields)
        data = {'token': str(uuid.uuid4()), 'batch': str(self.batch.pk), 'date': self.day(1).isoformat(),
                'count': '120', 'suspected': 'on', 'found_time': '06:15', 'cause': 'Seals', 'health_status': 'Healthy',
                'recaptured': '3', 'notes': ''}
        self.assertEqual(self.client.post(url, data, headers={'X-Modal': '1'}).status_code, 204)
        record = EscapeRecord.objects.get()
        self.assertEqual((record.suspected, record.found_time, record.cause, record.recaptured),
                         (True, time(6, 15), 'Seals', 3))
        page = self.client.get(reverse('farm:production_units'), {'unit': self.t1.pk})
        self.assertContains(page, 'Escape recorded: 120 fish of ' + self.batch.code + ' from T-01.')
        self.assertContains(page, 'Suspected escape · Seals · found 06:15 · Healthy · 3 recaptured')
        wrong = self.client.post(url, {**data, 'token': str(uuid.uuid4()), 'cause': '', 'count': '99999'})
        self.assertEqual(wrong.status_code, 422)
        self.assertEqual(set(wrong.context['form'].errors), {'cause'})

    def test_check_stock_finds_an_escape_without_its_record_and_a_record_on_another_operation(self):
        bare = StockOperation.objects.create(kind='adjustment', date=self.day(3))
        StockMovement.objects.create(operation=bare, batch=self.batch, unit=self.t1, kind='adjustment', count_delta=-5,
                                     reason='escape')
        mortality = self.mortality(self.batch, 4)
        EscapeRecord.all_objects.create(operation=mortality, cause='x')
        found = integrity.problems()
        self.assertIn(f'Count adjustment {bare.pk} of {bare.date} has no escape record (a count adjustment on its own '
                      'is an escape).', found)
        self.assertIn(f'Mortality {mortality.pk} has an escape record.', found)

    def test_the_database_wants_a_cause(self):
        operation = StockOperation.objects.create(kind='adjustment', date=self.day(3))
        with self.assertRaises(IntegrityError), transaction.atomic():
            EscapeRecord.all_objects.create(operation=operation, cause='')


class DeliveryTests(StockTestCase):
    def setUp(self):
        super().setUp()
        self.batch = self.stock(count=2000, weight='125', days_ago=10)

    def deliver(self, count=500, days_ago=2, **fields):
        return services.record_delivery(
            self.user, unit=self.t1, batch=self.batch, day=self.day(days_ago), count=count,
            destination=fields.pop('destination', 'Nordic Smolt AS'), **fields)

    def test_live_fish_leave_the_company_at_the_average_with_where_they_went(self):
        operation = self.deliver(destination_site_number=31234, measured_weight_kg=Decimal('62.5'))
        line = operation.movements.get()
        self.assertEqual((operation.kind, line.kind, line.count_delta, line.measured_weight_kg),
                         ('delivery', 'delivery', -500, Decimal('62.500')))
        record = DeliveryRecord.objects.get()
        self.assertEqual((record.operation, record.destination, record.destination_site_number),
                         (operation, 'Nordic Smolt AS', 31234))
        stock = read.stock_of([self.t1])[self.t1.pk]
        self.assertEqual((stock.count, stock.biomass_kg), (1500, Decimal('187.5')))
        self.assertEqual(AuditLog.objects.filter(entity_type='stock operation').latest('created_at').changes['Delivered to'],
                         [None, 'Nordic Smolt AS'])
        self.assertStockAddsUp()

    def test_the_last_fish_out_empty_the_unit_and_a_void_puts_them_back(self):
        operation = self.deliver(count=2000)
        self.assertEqual(Tank.objects.get(pk=self.t1.pk).status, 'fallow')
        services.void(self.user, operation, 'Wrong customer')
        self.assertEqual((read.stock_of([self.t1])[self.t1.pk].count, Tank.objects.get(pk=self.t1.pk).status),
                         (2000, 'active'))
        self.assertFalse(DeliveryRecord.objects.exists())

    def test_what_the_service_refuses(self):
        self.assertEqual(self.refused(self.deliver, destination=' ')['destination'], ['Say who received the fish.'])
        self.assertIn('count', self.refused(self.deliver, count=3000))
        self.assertFalse(StockOperation.objects.filter(kind='delivery').exists())

    def test_the_dialog_runs_the_transport_check_and_records_it(self):
        url = reverse('farm:stock_delivery', args=[self.t1.pk])
        form = self.client.get(url, headers={'X-Modal': '1'})
        self.assertContains(form, 'Deliver fish')
        self.assertEqual(form.context['form'].handling_kind, 'transport')
        data = {'token': str(uuid.uuid4()), 'batch': str(self.batch.pk), 'date': self.day(1).isoformat(),
                'count': '400', 'measured_weight_kg': '', 'destination': 'Nordic Smolt AS',
                'destination_site_number': '31234', 'notes': '', 'handling_ack': ''}
        self.assertEqual(self.client.post(url, data, headers={'X-Modal': '1'}).status_code, 204)
        self.assertEqual(DeliveryRecord.objects.get().destination_site_number, 31234)
        page = self.client.get(reverse('farm:production_units'), {'unit': self.t1.pk})
        self.assertContains(page, 'Delivery recorded: 400 fish of ' + self.batch.code + ' from T-01 to Nordic Smolt AS.')
        self.assertContains(page, 'To Nordic Smolt AS · 31234')
        wrong = self.client.post(url, {**data, 'token': str(uuid.uuid4()), 'destination_site_number': '123'})
        self.assertIn('destination_site_number', wrong.context['form'].errors)

    def test_the_database_wants_a_destination_and_a_five_digit_site(self):
        operation = StockOperation.objects.create(kind='delivery', date=self.day(3))
        for fields in ({'destination': ''}, {'destination': 'x', 'destination_site_number': 999}):
            with self.subTest(fields), self.assertRaises(IntegrityError), transaction.atomic():
                DeliveryRecord.all_objects.create(operation=operation, **{'destination': 'x', **fields})

    def test_check_stock_finds_a_delivery_without_its_destination(self):
        bare = StockOperation.objects.create(kind='delivery', date=self.day(3))
        StockMovement.objects.create(operation=bare, batch=self.batch, unit=self.t1, kind='delivery', count_delta=-5)
        self.assertIn(f'Delivery {bare.pk} of {bare.date} has no delivery record (who received the fish).',
                      integrity.problems())

    def test_the_new_line_kinds_are_in_the_checks_of_the_database(self):
        operation = StockOperation.objects.create(kind='delivery', date=self.day(3))
        good = {'operation': operation, 'batch': self.batch, 'unit': self.t1}
        for fields in ({'kind': 'delivery', 'count_delta': 5},                 # a delivery takes fish out
                       {'kind': 'delivery', 'count_delta': -5, 'reason': 'x'}):       # and has no reason
            with self.subTest(fields), self.assertRaises(IntegrityError), transaction.atomic():
                StockMovement.objects.create(**good, **fields)
        StockMovement.objects.create(**good, kind='delivery', count_delta=-5, measured_weight_kg=Decimal('1.5'))

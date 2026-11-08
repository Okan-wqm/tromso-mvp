"""A form sent twice creates one record, whatever the record (F-232): a double click, a retried request or two
sendings at once on any tab's new-record form. The form carries a key (core.crud.ENTRY_KEY); the key is stored with
the record it created, in one table for every kind of record (core.models.EntryKey), so the second sending opens the
record the first created instead of creating another."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import NoReverseMatch, reverse

from core.crud import ENTRY_KEY, Resource
from core.models import AuditLog
from farm.models import HealthEvent, Site
from farm.stock.dates import site_today


class EveryNewRecordFormTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser('root', 'root@example.com', 'x'))

    def test_every_tabs_new_record_form_carries_a_key(self):
        missing = []
        for resource in Resource.registry:
            for mount in (None, *resource.mounts):
                try:
                    url = reverse(resource.url_name('create', mount))
                except NoReverseMatch:
                    continue
                response = self.client.get(url)
                if response.status_code == 200 and 'form' in response.context:
                    if ENTRY_KEY not in response.context['form'].fields:
                        missing.append(f'{resource.__name__} {url}')
        self.assertEqual(missing, [])

    def test_a_health_event_sent_twice_is_created_once(self):
        # A notifiable-disease observation counted twice would be reported twice.
        site = Site.objects.create(name='Bergen', code='BG')
        url = reverse('farm:healthevent_create')
        key = self.client.get(url).context['form'][ENTRY_KEY].value()
        data = {'site': str(site.pk), 'units': [], 'date': site_today(site).isoformat(), 'kind': 'observation', 'signs': [], 'diagnosis': '',
                'confirmation': '', 'examined_by': '', 'vet': '', 'lab': '', 'lab_reference': '', 'findings': 'Pale gills',
                'recommendations': '', 'closed_on': '', 'outcome': '', ENTRY_KEY: str(key)}
        first, second = self.client.post(url, data), self.client.post(url, data)
        self.assertEqual(first.status_code, 302, first.context and first.context['form'].errors)
        event = HealthEvent.objects.get()
        self.assertEqual(first['Location'], second['Location'])
        self.assertEqual(AuditLog.objects.filter(entity_id=str(event.pk), action='create').count(), 1)


class WritePathKeyTests(TestCase):
    """The write paths of their own (a stock operation, a feeding, a treatment, a sea-lice count, a storage operation, a
    water sample, an experiment's copy) keep their form's key in the same one table (cross review F7a): one mechanism."""

    def test_no_record_keeps_a_key_column_of_its_own(self):
        from experiments.models import Experiment
        from farm.models import FeedingRecord, LiceCount, StockOperation, Treatment, WaterMeasurement
        from inventory.models import InventoryOperation
        for model in (StockOperation, FeedingRecord, Treatment, LiceCount, InventoryOperation, WaterMeasurement,
                      Experiment):
            self.assertNotIn(ENTRY_KEY, {field.name for field in model._meta.fields}, model.__name__)

    def test_a_stocking_sent_twice_is_recorded_once_and_its_key_is_in_the_one_table(self):
        import uuid
        from decimal import Decimal

        from core.models import EntryKey
        from farm.models import ProductionDepartment, StockOperation
        from farm.stock import services
        from farm.tests.helpers import make_species
        from farm.tests.test_stock import make_unit
        user = get_user_model().objects.create_superuser('root', 'root@example.com', 'x')
        hall = ProductionDepartment.objects.create(site=Site.objects.create(name='Bergen', code='BG'), name='Hall',
                                                   code='HA')
        unit, species, token = make_unit('T-01', hall), make_species(), uuid.uuid4()

        def stock():
            return services.record_input(user, species=species, input_stage='fry', origin='own_hatchery',
                                         day=services.local_today(unit), lines=[(unit, 100, Decimal('5'))], token=token)
        first = stock()
        with self.assertRaises(services.AlreadyRecorded) as caught:
            stock()
        self.assertEqual(caught.exception.operation, first)
        self.assertEqual(EntryKey.record_of(token, StockOperation), first)
        self.assertEqual(StockOperation.objects.count(), 1)

"""A batch's year class and whether its fish are farmed or wild-caught, given after the stocking (farm/stock/services.py
`correct_batch`, the dialog of the Production units drawer): who may, what is refused, the activity log, and the batch's
version a filed report is compared by, each checked against the stored rows."""
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.urls import reverse

from core.audit import message
from core.models import AuditLog

from ..models import Batch, Supplier
from ..stock import services
from .helpers import make_species, role
from .test_stock import StockTestCase


def setUpModule():
    call_command('compile_catalogs', verbosity=0)


class BatchDetailsTests(StockTestCase):
    def setUp(self):
        super().setUp()
        self.supplier = Supplier.objects.create(name='Smolt Sales AS', code='SMS', supplies=['live_fish'])
        self.bought = self.stock(origin='purchased', supplier=self.supplier)     # no year class, no provenance
        self.own = self.stock(self.t2)                                           # the own hatchery's: farmed
        self.url = reverse('farm:stock_batch', args=[self.bought.pk]) + f'?unit={self.t1.pk}'

    def test_a_bought_batch_gets_its_year_class_and_provenance_and_it_is_logged_with_a_new_version(self):
        self.assertEqual((self.bought.year_class, self.bought.provenance), (None, ''))
        form = self.client.get(self.url, headers={'X-Modal': '1'})
        self.assertContains(form, 'Batch details: ' + self.bought.code)
        response = self.client.post(self.url, {'year_class': '2025', 'provenance': 'wild_caught'},
                                    headers={'X-Modal': '1'})
        self.assertEqual(response.status_code, 204)
        stored = Batch.objects.get(pk=self.bought.pk)
        self.assertEqual((stored.year_class, stored.provenance, stored.version, stored.updated_by),
                         (2025, 'wild_caught', self.bought.version + 1, self.user))
        entry = AuditLog.objects.get(entity_type='batch', action='update')
        self.assertEqual(entry.changes, {'Year class': [None, '2025'],
                                         'Farmed or wild-caught': [None, message('Wild-caught')]})
        page = self.client.get(reverse('farm:production_units'), {'unit': self.t1.pk})
        self.assertContains(page, 'Year class 2025')

    def test_nothing_changed_writes_nothing(self):
        services.correct_batch(self.user, batch=self.bought, year_class=2025, provenance='farmed')
        version = Batch.objects.get(pk=self.bought.pk).version
        services.correct_batch(self.user, batch=self.bought, year_class=2025, provenance='farmed')
        self.assertEqual(Batch.objects.get(pk=self.bought.pk).version, version)
        self.assertEqual(AuditLog.objects.filter(entity_type='batch', action='update').count(), 1)

    def test_the_own_hatcherys_fish_are_farmed_whatever_is_given_and_the_year_can_be_cleared(self):
        errors = self.refused(services.correct_batch, self.user, batch=self.own, year_class=2025,
                              provenance='wild_caught')
        self.assertEqual(errors['provenance'], ['Fish of the own hatchery are farmed, fish caught in the wild '
                                                'wild-caught.'])
        services.correct_batch(self.user, batch=self.own, year_class=2025, provenance='')
        self.assertEqual(Batch.objects.get(pk=self.own.pk).provenance, 'farmed')
        services.correct_batch(self.user, batch=self.own, year_class=None, provenance='')
        self.assertIsNone(Batch.objects.get(pk=self.own.pk).year_class)

    def test_a_bought_cleaner_fish_must_say_farmed_or_wild_caught(self):
        lump = make_species('LUM', 'Lumpfish', 'Cyclopterus lumpus', local_name='Rognkjeks', freshwater=False,
                            cleaner_fish_type='lumpfish')
        Batch.objects.filter(pk=self.bought.pk).update(species=lump)
        errors = self.refused(services.correct_batch, self.user, batch=Batch.objects.get(pk=self.bought.pk),
                              year_class=2025, provenance='')
        self.assertEqual(errors['provenance'], ['Farmed or wild-caught? The cleaner-fish report asks it of every '
                                                'cleaner fish.'])

    def test_the_dialog_refuses_a_year_out_of_range_and_a_voided_batch_has_none(self):
        response = self.client.post(self.url, {'year_class': '1900', 'provenance': 'farmed'},
                                    headers={'X-Modal': '1'})
        self.assertEqual(response.status_code, 422)
        self.assertTrue(response.context['form'].errors['year_class'])
        self.assertIsNone(Batch.objects.get(pk=self.bought.pk).year_class)
        services.void(self.user, self.bought.movements.get().operation, 'Entered by mistake')
        with self.assertRaises(ValidationError):
            services.correct_batch(self.user, batch=self.bought, year_class=2025, provenance='farmed')
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_only_who_may_record_stock_gets_the_dialog_and_the_drawer_link(self):
        page = self.client.get(reverse('farm:production_units'), {'unit': self.t1.pk})
        self.assertContains(page, reverse('farm:stock_batch', args=[self.bought.pk]))
        reader = get_user_model().objects.create_user('ola', 'ola@example.com', 'x')
        reader.groups.add(role('Stock reader', 'view_stockoperation'))
        self.client.force_login(reader)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.url, {'year_class': '2025'}).status_code, 403)
        page = self.client.get(reverse('farm:production_units'), {'unit': self.t1.pk})
        self.assertNotContains(page, reverse('farm:stock_batch', args=[self.bought.pk]))
        self.assertContains(page, 'No year class')

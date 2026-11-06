"""Every live unit is on a site (F-212, F-020, F-191, F-114): a site's fish are in its reports and its feed in the
site's stock only through its production departments, so a site is not deleted from under live units, a live production
department is always on a site (the database holds it for every new or changed row), and the few departments a deleted
site left without one before (legacy rows) take no fish until they are put on a site again."""
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import CommandError, call_command
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from core.softdelete import plan_delete

from ..forms.stock import stockable_units
from ..models import ProductionDepartment, Site, Tank
from ..stock import integrity, services
from .helpers import leave_without_site, make_species, stock_fish
from .test_production_departments import production_department_data
from .test_stock import make_unit


class SiteStructureTestCase(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser('root', 'root@example.com', 'x')
        self.client.force_login(self.user)
        self.bergen = Site.objects.create(name='Bergen', code='BG')
        self.hall = ProductionDepartment.objects.create(site=self.bergen, name='Hall A', code='HA')
        self.salmon = make_species()


class SiteDeleteTests(SiteStructureTestCase):
    def test_a_site_with_a_live_unit_cannot_be_deleted(self):
        make_unit('T-01', self.hall)
        self.assertEqual(plan_delete(self.bergen).blockers, ['1 unit still belongs to it.'])
        self.client.post(reverse('farm:site_delete', args=[self.bergen.pk]))
        self.assertTrue(Site.objects.filter(pk=self.bergen.pk).exists())
        self.assertEqual(ProductionDepartment.objects.get().site, self.bergen)

    def test_a_deleted_unit_does_not_hold_the_site(self):
        make_unit('T-01', self.hall).soft_delete(self.user)
        self.assertTrue(plan_delete(self.bergen).can_delete)

    def test_its_production_departments_are_deleted_with_it_none_is_left_without_a_site(self):
        self.client.post(reverse('farm:site_delete', args=[self.bergen.pk]))
        self.assertFalse(Site.objects.exists())
        self.assertFalse(ProductionDepartment.objects.exists())
        self.assertTrue(ProductionDepartment.all_objects.get().is_deleted)


class DepartmentOnASiteTests(SiteStructureTestCase):
    def test_the_database_refuses_a_live_production_department_without_a_site(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProductionDepartment.objects.create(name='Hall B', code='HB')
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProductionDepartment.objects.filter(pk=self.hall.pk).update(site=None)
        ProductionDepartment.objects.create(name='Old hall', code='OH', is_deleted=True)   # a deleted one may lack it

    def test_a_department_left_without_a_site_is_put_on_one_when_edited(self):
        leave_without_site(self.hall)
        url = reverse('farm:productiondepartment_edit', args=[self.hall.pk])
        form = self.client.get(url).context['form']
        self.assertFalse(form.fields['site'].disabled)
        self.assertTrue(form.fields['site'].required)
        response = self.client.post(url, production_department_data(None, name='Hall A', code='HA', version='1'))
        self.assertIn('site', response.context['form'].errors)
        self.client.post(url, production_department_data(self.bergen, name='Hall A', code='HA', version='1'))
        self.hall.refresh_from_db()
        self.assertEqual(self.hall.site, self.bergen)

    def test_a_department_on_a_site_stays_on_it(self):
        form = self.client.get(reverse('farm:productiondepartment_edit', args=[self.hall.pk])).context['form']
        self.assertTrue(form.fields['site'].disabled)


class UnitWithoutASiteTests(SiteStructureTestCase):
    def setUp(self):
        super().setUp()
        self.unit = make_unit('T-01', self.hall)
        self.other = make_unit('T-02', self.hall)

    def test_a_unit_without_a_site_takes_no_fish(self):
        leave_without_site(self.hall)
        with self.assertRaisesMessage(ValidationError, 'T-01 is not on any site'):
            stock_fish(self.user, self.unit, species=self.salmon)
        self.assertNotIn(self.unit, stockable_units())

    def test_fish_already_in_it_are_not_moved_into_another_unit_without_a_site(self):
        batch = stock_fish(self.user, self.unit, species=self.salmon)
        leave_without_site(self.hall)
        with self.assertRaisesMessage(ValidationError, 'T-02 is not on any site'):
            services.record_transfer(self.user, source=self.unit, batch=batch, day=services.local_today(self.unit),
                                     legs=[(self.other, 10)], reason='density')

    def test_a_new_unit_goes_only_into_a_department_on_a_site(self):
        leave_without_site(self.hall)
        unit = Tank(name='Unit T-03', code='T-03', kind='tank', production_department=self.hall, water_type='freshwater',
                    shape='rectangular', material='fiberglass', length=10, width=5, depth=2)
        with self.assertRaises(ValidationError) as caught:
            unit.full_clean()
        self.assertEqual(caught.exception.message_dict['production_department'],
                         ['This production department is not on any site; choose one that is.'])

    def test_check_stock_names_fish_in_a_unit_without_a_site_and_a_department_without_one(self):
        stock_fish(self.user, self.unit, species=self.salmon, days_ago=3)
        leave_without_site(self.hall)
        found = integrity.problems()
        self.assertIn('Unit T-01 holds 1000 fish but is not on any site.', found)
        self.assertIn('Production department HA is not on any site.', found)
        with self.assertRaises(CommandError):
            call_command('check_stock', stdout=StringIO())

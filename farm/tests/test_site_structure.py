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
from ..models.stock import takes_fish
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


def immediately():
    """Runs the deferred checks now (they otherwise run at commit, which a test's transaction never reaches)."""
    from django.db import connection
    with connection.cursor() as cursor:
        cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')


class LiveSiteTests(SiteStructureTestCase):
    """"On a site" means a live unit in a live department on a live site (cross review F1): a deleted department or site
    still holds its link, so a unit left live under one would be in no report as surely as one on no site."""

    def setUp(self):
        super().setUp()
        self.unit = make_unit('T-01', self.hall)

    def strand(self, department=True, site=True):
        """A live unit under a deleted department and/or site, as a race between a site's delete and a unit's create
        could leave it before the database refused it (farm 0030): written with the database's own triggers off."""
        from django.db import connection
        triggers = (('production_departments', 'trg_departments_on_a_live_site'),
                    ('sites', 'trg_sites_without_live_departments'))
        with connection.cursor() as cursor:
            cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')    # a table with pending deferred checks cannot be altered
            for table, trigger in triggers:
                cursor.execute(f'ALTER TABLE {table} DISABLE TRIGGER {trigger}')
            if department:
                ProductionDepartment.objects.filter(pk=self.hall.pk).update(is_deleted=True)
            if site:
                Site.objects.filter(pk=self.bergen.pk).update(is_deleted=True)
            for table, trigger in triggers:
                cursor.execute(f'ALTER TABLE {table} ENABLE TRIGGER {trigger}')
        self.unit = Tank.all_objects.get(pk=self.unit.pk)

    def test_a_live_unit_under_a_deleted_department_or_site_takes_no_fish(self):
        for department, site in ((True, False), (False, True)):
            with self.subTest(department=department, site=site), transaction.atomic():
                self.strand(department, site)
                self.assertFalse(takes_fish(self.unit))
                self.assertNotIn(self.unit, stockable_units())
                with self.assertRaisesMessage(ValidationError, 'T-01 is not on any site'):
                    stock_fish(self.user, self.unit, species=self.salmon)
                transaction.set_rollback(True)

    def test_check_stock_names_live_units_and_departments_under_deleted_records(self):
        with transaction.atomic():
            self.strand(department=False, site=True)
            self.assertIn('Production department HA is on the deleted site BG.', integrity.problems())
            transaction.set_rollback(True)
        self.strand(department=True, site=False)
        self.assertIn('Unit T-01 is live in the deleted production department HA.', integrity.problems())

    def test_a_new_unit_goes_only_into_a_live_department_on_a_live_site(self):
        self.strand(department=False, site=True)
        unit = Tank(name='Unit T-03', code='T-03', kind='tank', production_department_id=self.hall.pk,
                    water_type='freshwater',
                    shape='rectangular', material='fiberglass', length=10, width=5, depth=2, max_density_kg_m3=50)
        with self.assertRaises(ValidationError) as caught:
            unit.full_clean()
        self.assertEqual(caught.exception.message_dict,
                         {'production_department': ['This production department is not on any site; choose one that is.']})

    def test_the_database_refuses_a_live_unit_under_a_deleted_department_or_site(self):
        for statement in (lambda: ProductionDepartment.objects.filter(pk=self.hall.pk).update(is_deleted=True),
                          lambda: Site.objects.filter(pk=self.bergen.pk).update(is_deleted=True),
                          lambda: make_unit('T-02', ProductionDepartment.objects.create(
                              site=self.bergen, name='Old', code='OL', is_deleted=True))):
            with self.subTest(statement=statement), self.assertRaises(IntegrityError), transaction.atomic():
                statement()
                immediately()

    def test_a_unit_saved_locks_its_department_and_site(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as queries, transaction.atomic():
            make_unit('T-04', self.hall)
        locks = [query['sql'] for query in queries.captured_queries if 'FOR' in query['sql'] and 'UPDATE' in query['sql']]
        self.assertTrue(any('"production_departments"' in sql for sql in locks), locks)
        self.assertTrue(any('"sites"' in sql for sql in locks), locks)


class ResitingTests(SiteStructureTestCase):
    """A department a deleted site left without a site goes back on a site by a clear rule (owner, cross review F4): its
    units' past figures belong to the site they were recorded on, so with stock records it goes back only to that site
    (restored first); without any it may go to any live site."""

    def setUp(self):
        super().setUp()
        self.tromso = Site.objects.create(name='Tromso', code='TR')
        self.unit = make_unit('T-01', self.hall)

    def leave(self):
        """As the source's site delete left it: the department detached (logged so) and the site deleted."""
        from core import audit
        from core.models import AuditLog
        with audit.source_language():
            audit.record(self.user, AuditLog.Action.UPDATE, self.hall, {'Site': [str(self.bergen), None]})
        leave_without_site(self.hall)
        Site.objects.filter(pk=self.bergen.pk).update(is_deleted=True)

    def errors(self, site):
        self.hall.refresh_from_db()
        self.hall.site = site
        try:
            self.hall.full_clean()
        except ValidationError as error:
            return error.message_dict.get('site')
        return None

    def test_without_stock_records_it_may_go_to_any_live_site(self):
        self.leave()
        self.assertIsNone(self.errors(self.tromso))

    def test_with_stock_records_it_goes_back_only_to_the_site_they_were_recorded_on(self):
        stock_fish(self.user, self.unit, species=self.salmon, days_ago=3)
        self.leave()
        self.assertEqual(self.errors(self.tromso),
                         ['Its units have stock records on Bergen (BG): restore that site and choose it.'])
        Site.all_objects.filter(pk=self.bergen.pk).update(is_deleted=False)
        self.assertIsNone(self.errors(Site.objects.get(pk=self.bergen.pk)))

    def test_with_stock_records_and_no_known_site_it_is_refused_with_the_reason(self):
        stock_fish(self.user, self.unit, species=self.salmon, days_ago=3)
        leave_without_site(self.hall)
        self.assertEqual(self.errors(self.tromso),
                         ['Its units have stock records, and the site they were recorded on is not known: it cannot be '
                          'put on another one.'])

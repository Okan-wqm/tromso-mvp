from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from core.models import AuditLog

from ..models import ProductionDepartment, Site
from .helpers import role

PRODUCTION_DEPARTMENT_MANAGER = (
    'view_productiondepartment', 'add_productiondepartment', 'change_productiondepartment', 'delete_productiondepartment',
    'view_site', 'delete_site', 'view_auditlog',
)


def production_department_data(site=None, **overrides):
    data = {'name': 'Hatchery hall', 'code': 'hat-a', 'type': 'hatchery', 'site': str(site.pk) if site else '',
            'capacity': '', 'notes': ''}
    data.update(overrides)
    return data


class ProductionDepartmentTestCase(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('ali', 'ali@example.com', 'eski-sifre-123')
        self.user.groups.add(role('Production department manager', *PRODUCTION_DEPARTMENT_MANAGER))
        self.client.force_login(self.user)
        self.bergen = Site.objects.create(name='Bergen', code='BG')
        self.tromso = Site.objects.create(name='Tromso', code='TR')

    def make(self, site=None, **fields):
        fields.setdefault('name', 'Hall A')
        fields.setdefault('code', 'HA')
        return ProductionDepartment.objects.create(site=site or self.bergen, **fields)


class DepartmentRoundTripTests(ProductionDepartmentTestCase):
    def test_create_read_edit_delete(self):
        # Create
        self.client.post(reverse('farm:productiondepartment_create'), production_department_data(
            self.bergen, capacity='1500.5', notes='North building'))
        department = ProductionDepartment.objects.get()
        self.assertEqual(
            (department.name, department.code, department.type, department.site, department.capacity,
             department.notes, department.status, department.created_by),
            ('Hatchery hall', 'HAT-A', 'hatchery', self.bergen, Decimal('1500.50'), 'North building', 'active',
             self.user),
        )
        # Read: listed, and the edit form is filled from the database (notes included)
        self.assertEqual(list(self.client.get(reverse('farm:productiondepartment_list')).context['objects']), [department])
        form = self.client.get(reverse('farm:productiondepartment_edit', args=[department.pk])).context['form']
        self.assertEqual(form['notes'].value(), 'North building')
        # Edit: change values and clear optional ones; the site cannot be moved
        self.client.post(reverse('farm:productiondepartment_edit', args=[department.pk]), production_department_data(
            self.tromso, name='Hatchery hall B', type='nursery', capacity='', notes='', version='1'))
        department.refresh_from_db()
        self.assertEqual((department.name, department.type, department.site, department.capacity, department.notes,
                          department.version), ('Hatchery hall B', 'nursery', self.bergen, None, '', 2))
        # Delete
        self.client.post(reverse('farm:productiondepartment_delete', args=[department.pk]))
        self.assertFalse(ProductionDepartment.objects.exists())
        self.assertTrue(ProductionDepartment.all_objects.get().is_deleted)


class DepartmentValidationTests(ProductionDepartmentTestCase):
    def errors(self, **data):
        return self.client.post(reverse('farm:productiondepartment_create'), production_department_data(**data)).context['form'].errors

    def test_site_name_and_code_are_required(self):
        self.assertEqual(set(self.errors(name='', code='')), {'site', 'name', 'code'})

    def test_name_and_code_need_two_characters(self):
        errors = self.errors(site=self.bergen, name='A', code='B')
        self.assertEqual(errors['name'], ['Name must be at least 2 characters.'])
        self.assertEqual(errors['code'], ['Code must be at least 2 characters.'])

    def test_code_is_unique_across_the_company(self):
        self.make(code='HAT-A')
        errors = self.errors(site=self.tromso, name='Other hall', code='hat-a')
        self.assertEqual(errors['code'], ['Another production department already uses this code.'])

    def test_name_is_unique_within_a_site_only(self):
        self.make(name='Hatchery hall', code='X1')
        errors = self.errors(site=self.bergen, code='X2')
        self.assertEqual(errors['name'], ['This site already has a production department with this name.'])
        self.client.post(reverse('farm:productiondepartment_create'), production_department_data(self.tromso, code='X3'))
        self.assertTrue(ProductionDepartment.objects.filter(site=self.tromso, name='Hatchery hall').exists())

    def test_deleted_department_frees_its_code_and_name(self):
        self.make(name='Hatchery hall', code='HAT-A').soft_delete(self.user)
        self.client.post(reverse('farm:productiondepartment_create'), production_department_data(self.bergen))
        self.assertEqual(ProductionDepartment.objects.count(), 1)

    def test_capacity_cannot_be_negative(self):
        self.assertIn('capacity', self.errors(site=self.bergen, capacity='-1'))
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make(capacity=-1)

    def test_only_live_sites_can_be_chosen(self):
        self.tromso.soft_delete(self.user)
        self.assertIn('site', self.errors(site=self.tromso))


class DepartmentListTests(ProductionDepartmentTestCase):
    def names(self, **query):
        return [d.name for d in self.client.get(reverse('farm:productiondepartment_list'), query).context['objects']]

    def test_search_and_site_filter(self):
        self.make(name='Hall A', code='HA')
        self.make(site=self.tromso, name='Smolt hall', code='SM')
        self.assertEqual(self.names(), ['Hall A', 'Smolt hall'])
        self.assertEqual(self.names(q='sm'), ['Smolt hall'])
        self.assertEqual(self.names(site=str(self.tromso.pk)), ['Smolt hall'])
        self.assertEqual(self.names(site='not-a-site'), ['Hall A', 'Smolt hall'])


class DepartmentSiteLinkTests(ProductionDepartmentTestCase):
    def test_departments_left_without_a_site_are_flagged_and_filterable(self):
        self.make(name='Hall A', code='HA')
        self.client.post(reverse('farm:site_delete', args=[self.bergen.pk]))
        self.assertContains(self.client.get(reverse('farm:productiondepartment_list')), '1 production department is not on any site.')
        response = self.client.get(reverse('farm:productiondepartment_list'), {'site': 'none'})
        self.assertEqual([d.name for d in response.context['objects']], ['Hall A'])

    def test_a_department_without_a_site_can_still_be_edited(self):
        hall = self.make(name='Hall A', code='HA')
        ProductionDepartment.objects.filter(pk=hall.pk).update(site=None)
        self.client.post(reverse('farm:productiondepartment_edit', args=[hall.pk]),
                         production_department_data(None, name='Hall A2', code='HA', version='1'))
        hall.refresh_from_db()
        self.assertEqual((hall.name, hall.site), ('Hall A2', None))


class DepartmentAuditAndPermissionTests(ProductionDepartmentTestCase):
    def test_changes_are_logged(self):
        self.client.post(reverse('farm:productiondepartment_create'), production_department_data(self.bergen))
        department = ProductionDepartment.objects.get()
        self.client.post(reverse('farm:productiondepartment_edit', args=[department.pk]),
                         production_department_data(self.bergen, type='nursery', version='1'))
        log = list(AuditLog.objects.order_by('created_at').values_list('action', 'changes'))
        self.assertEqual(log[0][1]['Site'], [None, 'Bergen (BG)'])
        self.assertEqual(log[1], ('update', {'Type': ['Hatchery', 'Nursery']}))

    def test_read_only_role_cannot_change_production_departments(self):
        viewer = get_user_model().objects.create_user('ola', 'ola@example.com', 'x')
        viewer.groups.add(role('Viewer', 'view_productiondepartment'))
        self.client.force_login(viewer)
        department = self.make()
        self.assertEqual(self.client.get(reverse('farm:productiondepartment_list')).status_code, 200)
        self.assertEqual(
            self.client.post(reverse('farm:productiondepartment_create'), production_department_data(self.bergen)).status_code, 403)
        self.assertEqual(self.client.post(reverse('farm:productiondepartment_delete', args=[department.pk])).status_code, 403)
        self.assertNotContains(self.client.get(reverse('home')), reverse('farm:site_list'))

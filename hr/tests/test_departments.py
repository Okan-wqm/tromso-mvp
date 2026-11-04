from django.contrib.admin.sites import site as admin_site
from django.db import IntegrityError, connection, transaction
from django.urls import reverse

from django.core.exceptions import ValidationError

from core import softdelete
from core.models import AuditLog
from core.softdelete import plan_delete
from farm.models import ProductionDepartment, Site

from ..models import OfficeDepartment
from .helpers import HrTestCase, fields_of, user


def data(site=None, **overrides):
    values = {'name': 'Finance', 'code': 'fin', 'parent': '', 'site': str(site.pk) if site else '', 'manager': '',
              'status': 'active', 'description': ''}
    values.update(overrides)
    return values


class OfficeDepartmentTestCase(HrTestCase):
    def setUp(self):
        super().setUp()
        self.bergen = Site.objects.create(name='Bergen', code='BG')

    def make(self, **fields):
        fields.setdefault('name', 'Finance')
        fields.setdefault('code', 'FIN')
        fields.setdefault('site', self.bergen)
        return OfficeDepartment.objects.create(**fields)


class RoundTripTests(OfficeDepartmentTestCase):
    def test_create_read_edit_delete_every_column(self):
        manager = user('kari')
        parent = self.make(name='Administration', code='ADM')
        # Create: every stored column
        self.client.post(reverse('hr:officedepartment_create'), data(
            self.bergen, parent=str(parent.pk), manager=str(manager.pk), description='Books and pay run'))
        department = OfficeDepartment.objects.get(code='FIN')
        stored = {name: getattr(department, name) for name in fields_of(OfficeDepartment)}
        self.assertEqual(stored, {'parent': parent, 'site': self.bergen, 'name': 'Finance', 'code': 'FIN',
                                  'status': 'active', 'manager': manager, 'description': 'Books and pay run'})
        self.assertEqual(department.created_by, self.user)
        # Read: the list shows it, the form is filled from the database
        listed = [row.obj for row in self.client.get(reverse('hr:officedepartment_list')).context['objects']]
        self.assertIn(department, listed)
        form = self.client.get(reverse('hr:officedepartment_edit', args=[department.pk])).context['form']
        self.assertEqual((form['description'].value(), form['manager'].value(), form['parent'].value()),
                         ('Books and pay run', manager.pk, parent.pk))
        # Edit: change values and clear the optional ones; the version moves on
        self.client.post(reverse('hr:officedepartment_edit', args=[department.pk]), data(
            self.bergen, name='Finance and pay', status='inactive', version='1'))
        department.refresh_from_db()
        self.assertEqual((department.name, department.status, department.parent, department.manager,
                          department.description, department.version),
                         ('Finance and pay', 'inactive', None, None, '', 2))
        # Delete: soft, and logged
        self.client.post(reverse('hr:officedepartment_delete', args=[department.pk]))
        self.assertFalse(OfficeDepartment.objects.filter(pk=department.pk).exists())
        self.assertTrue(OfficeDepartment.all_objects.get(pk=department.pk).is_deleted)
        actions = list(AuditLog.objects.filter(entity_id=str(department.pk)).order_by('created_at')
                       .values_list('action', flat=True))
        self.assertEqual(actions, ['create', 'update', 'delete'])

    def test_an_edit_on_an_outdated_version_is_refused(self):
        department = self.make()
        OfficeDepartment.objects.filter(pk=department.pk).update(version=5)
        self.client.post(reverse('hr:officedepartment_edit', args=[department.pk]),
                         data(self.bergen, name='Changed', version='1'))
        department.refresh_from_db()
        self.assertEqual(department.name, 'Finance')

    def test_a_new_department_needs_a_site_and_a_name_and_code_of_two_characters(self):
        errors = self.client.post(reverse('hr:officedepartment_create'), data(name='A', code='B')
                                  ).context['form'].errors
        self.assertEqual(set(errors), {'name', 'code', 'site'})
        self.assertFalse(OfficeDepartment.objects.exists())

    def test_the_form_refuses_a_cycle_on_the_field(self):
        top = self.make(name='Top', code='TOP')
        middle = self.make(name='Middle', code='MID', parent=top)
        errors = self.client.post(reverse('hr:officedepartment_edit', args=[top.pk]),
                                  data(self.bergen, name='Top', code='TOP', parent=str(middle.pk), version='1')
                                  ).context['form'].errors
        self.assertIn('parent', errors)
        top.refresh_from_db()
        self.assertIsNone(top.parent)

    def test_only_active_people_are_offered_as_manager(self):
        gone = user('gone')
        gone.is_active = False
        gone.save()
        form = self.client.get(reverse('hr:officedepartment_create')).context['form']
        self.assertNotIn(gone, form.fields['manager'].queryset)


class ConstraintTests(OfficeDepartmentTestCase):
    """What the database refuses, whatever writes (raw rows, not the form)."""

    def refused(self, **fields):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make(**fields)

    def test_the_code_is_unique_among_live_departments_and_free_again_after_a_delete(self):
        first = self.make()
        self.refused(name='Other')
        first.soft_delete(self.user)
        again = self.make()
        self.assertEqual(again.code, 'FIN')

    def test_a_name_is_unique_under_one_parent_and_among_the_top_level_ones(self):
        top = self.make(name='Top', code='TOP')
        self.make(name='Ledger', code='LED', parent=top)
        self.refused(name='Ledger', code='LED2', parent=top)
        self.make(name='Ledger', code='LED3')                    # under no parent: another place
        self.refused(name='Ledger', code='LED4')                 # the top level counts the missing parent as one value

    def test_a_department_cannot_be_its_own_parent(self):
        department = self.make()
        with self.assertRaises(IntegrityError), transaction.atomic():
            OfficeDepartment.objects.filter(pk=department.pk).update(parent=department)

    def test_the_code_and_the_status_are_checked(self):
        department = self.make()
        with self.assertRaises(IntegrityError), transaction.atomic():
            OfficeDepartment.objects.bulk_create([OfficeDepartment(name='Bad', code='low case')])
        with self.assertRaises(IntegrityError), transaction.atomic():
            OfficeDepartment.objects.filter(pk=department.pk).update(status='closed')

    def test_the_trigger_refuses_a_cycle_however_it_is_written(self):
        a = self.make(name='A dept', code='AA')
        b = self.make(name='B dept', code='BB', parent=a)
        c = self.make(name='C dept', code='CC', parent=b)
        with self.assertRaises(IntegrityError), transaction.atomic():
            OfficeDepartment.objects.filter(pk=a.pk).update(parent=c)       # A under C under B under A
        with connection.cursor() as cursor, self.assertRaises(IntegrityError), transaction.atomic():
            cursor.execute('UPDATE office_departments SET parent_id = %s WHERE id = %s', [b.pk, a.pk])
        a.refresh_from_db()
        self.assertIsNone(a.parent)
        # moving a leaf elsewhere stays allowed
        OfficeDepartment.objects.filter(pk=c.pk).update(parent=a)
        c.refresh_from_db()
        self.assertEqual(c.parent, a)

    def test_the_trigger_also_walks_deleted_departments(self):
        a = self.make(name='A dept', code='AA')
        b = self.make(name='B dept', code='BB', parent=a)
        b.soft_delete(self.user)
        with self.assertRaises(IntegrityError), transaction.atomic():
            OfficeDepartment.all_objects.filter(pk=a.pk).update(parent=b)


class UnionReadTests(OfficeDepartmentTestCase):
    """The production departments are HR departments by themselves: the same row, never a copy."""

    def rows(self, **query):
        response = self.client.get(reverse('hr:officedepartment_list'), query)
        return [(row.kind, row.name) for row in response.context['objects']]

    def test_a_production_department_appears_renames_and_goes_with_no_hr_write(self):
        before = (OfficeDepartment.all_objects.count(), AuditLog.objects.count())
        self.assertEqual(self.rows(), [])
        hall = ProductionDepartment.objects.create(site=self.bergen, name='Hatchery hall', code='HAT')
        self.assertEqual(self.rows(), [('production', 'Hatchery hall')])
        ProductionDepartment.objects.filter(pk=hall.pk).update(name='Hatchery A')
        self.assertEqual(self.rows(), [('production', 'Hatchery A')])
        hall.soft_delete(self.user)
        self.assertEqual(self.rows(), [])
        self.assertEqual((OfficeDepartment.all_objects.count(), AuditLog.objects.count()), before)

    def test_both_kinds_are_listed_production_first_and_the_office_ones_in_tree_order(self):
        ProductionDepartment.objects.create(site=self.bergen, name='Hatchery hall', code='HAT')
        top = self.make(name='Administration', code='ADM')
        self.make(name='Finance', code='FIN', parent=top)
        response = self.client.get(reverse('hr:officedepartment_list'))
        self.assertEqual([(row.kind, row.name, row.depth) for row in response.context['objects']],
                         [('production', 'Hatchery hall', 0), ('office', 'Administration', 0), ('office', 'Finance', 1)])
        self.assertContains(response, reverse('hr:officedepartment_edit', args=[top.pk]))

    def test_search_and_the_filters_narrow_the_one_list(self):
        ProductionDepartment.objects.create(site=self.bergen, name='Hatchery hall', code='HAT')
        self.make(name='Finance', code='FIN', status='inactive')
        self.assertEqual(self.rows(q='fin'), [('office', 'Finance')])
        self.assertEqual(self.rows(q='HAT'), [('production', 'Hatchery hall')])
        self.assertEqual(self.rows(kind='production'), [('production', 'Hatchery hall')])
        self.assertEqual(self.rows(status='inactive'), [('office', 'Finance')])
        self.assertEqual(len(self.rows(kind='nonsense', status='nonsense')), 2)

    def test_a_production_row_links_to_the_farms_own_form_only_for_who_may_edit_it(self):
        hall = ProductionDepartment.objects.create(site=self.bergen, name='Hatchery hall', code='HAT')
        edit = reverse('farm:productiondepartment_edit', args=[hall.pk])
        self.assertNotContains(self.client.get(reverse('hr:officedepartment_list')), edit)
        self.client.force_login(user('boss', 'view_officedepartment', 'change_productiondepartment',
                                     'view_productiondepartment'))
        self.assertContains(self.client.get(reverse('hr:officedepartment_list')), edit)


class DeleteAndRestoreTests(OfficeDepartmentTestCase):
    def test_a_department_with_departments_below_it_is_not_deleted(self):
        top = self.make(name='Top', code='TOP')
        self.make(name='Child', code='CHD', parent=top)
        plan = plan_delete(top)
        self.assertFalse(plan.can_delete)
        self.client.post(reverse('hr:officedepartment_delete', args=[top.pk]))
        self.assertTrue(OfficeDepartment.objects.filter(pk=top.pk).exists())

    def test_the_admin_restores_a_deleted_department_checked_like_a_new_one(self):
        top = self.make(name='Top', code='TOP')
        child = self.make(name='Child', code='CHD', parent=top)
        child.soft_delete(self.user)
        top.soft_delete(self.user)
        self.assertIn(OfficeDepartment, admin_site._registry)
        with self.assertRaises(ValidationError):                    # its parent is deleted
            softdelete.restore(OfficeDepartment.all_objects.get(pk=child.pk), self.user)
        softdelete.restore(OfficeDepartment.all_objects.get(pk=top.pk), self.user)
        softdelete.restore(OfficeDepartment.all_objects.get(pk=child.pk), self.user)
        self.assertEqual(OfficeDepartment.objects.count(), 2)
        self.assertEqual(AuditLog.objects.filter(action='restore').count(), 2)

    def test_a_restore_is_refused_when_the_code_was_taken_meanwhile(self):
        first = self.make()
        first.soft_delete(self.user)
        self.make(name='Finance again')
        with self.assertRaises(ValidationError):
            softdelete.restore(OfficeDepartment.all_objects.get(pk=first.pk), self.user)
        self.assertTrue(OfficeDepartment.all_objects.get(pk=first.pk).is_deleted)


class PermissionTests(OfficeDepartmentTestCase):
    def test_a_reader_cannot_add_edit_or_delete(self):
        department = self.make()
        self.client.force_login(user('reader', 'view_officedepartment'))
        self.assertEqual(self.client.get(reverse('hr:officedepartment_list')).status_code, 200)
        self.assertEqual(self.client.get(reverse('hr:officedepartment_create')).status_code, 403)
        self.assertEqual(self.client.post(reverse('hr:officedepartment_edit', args=[department.pk]),
                                          data(self.bergen, name='X1', version='1')).status_code, 403)
        self.assertEqual(self.client.post(reverse('hr:officedepartment_delete', args=[department.pk])).status_code, 403)
        department.refresh_from_db()
        self.assertEqual((department.name, department.is_deleted), ('Finance', False))

    def test_the_page_needs_its_read_permission(self):
        self.client.force_login(user('nobody'))
        self.assertEqual(self.client.get(reverse('hr:officedepartment_list')).status_code, 403)

"""A deleted record can be brought back from the admin, checked like a new one."""
from django.apps import apps
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from core import softdelete
from core.models import AuditedModel, AuditLog

from ..models import ProductionDepartment, Site, System
from .helpers import role


class RestoreTestCase(TestCase):
    def setUp(self):
        self.admin_user = get_user_model().objects.create_superuser('root', 'root@example.com', 'x')
        self.site = Site.objects.create(name='Bergen', code='BG')
        self.system = System.objects.create(site=self.site, name='RAS', code='RAS-1')


class RestoreTests(RestoreTestCase):
    def test_a_restored_record_is_live_again_and_the_change_is_logged(self):
        self.system.soft_delete(self.admin_user)
        softdelete.restore(System.all_objects.get(), self.admin_user)
        system = System.objects.get()
        self.assertEqual((system.is_deleted, system.deleted_at, system.deleted_by, system.version, system.updated_by),
                         (False, None, None, 3, self.admin_user))
        self.assertEqual(AuditLog.objects.get(action='restore').entity_label, 'RAS (RAS-1)')

    def test_it_is_refused_while_a_record_it_points_at_is_deleted(self):
        self.system.soft_delete(self.admin_user)
        self.site.soft_delete(self.admin_user)
        with self.assertRaisesMessage(ValidationError, 'Site “Bergen (BG)” is deleted.'):
            softdelete.restore(System.all_objects.get(), self.admin_user)
        self.assertEqual(System.objects.count(), 0)
        softdelete.restore(Site.all_objects.get(), self.admin_user)
        softdelete.restore(System.all_objects.get(), self.admin_user)
        self.assertEqual(System.objects.count(), 1)

    def test_it_is_refused_when_the_code_was_taken_meanwhile(self):
        self.system.soft_delete(self.admin_user)
        System.objects.create(site=self.site, name='New RAS', code='RAS-1')
        with self.assertRaisesMessage(ValidationError, 'This site already has a system with this code.'):
            softdelete.restore(System.all_objects.get(code='RAS-1', is_deleted=True), self.admin_user)
        self.assertEqual(AuditLog.objects.filter(action='restore').count(), 0)

    def test_only_the_record_itself_comes_back_not_what_was_deleted_with_it(self):
        child = System.objects.create(site=self.site, name='Loop', code='LP', parent=self.system)
        self.client.force_login(self.admin_user)
        self.client.post(reverse('farm:system_delete', args=[self.system.pk]))
        softdelete.restore(System.all_objects.get(pk=self.system.pk), self.admin_user)
        self.assertEqual(list(System.objects.all()), [System.objects.get(pk=self.system.pk)])
        self.assertTrue(System.all_objects.get(pk=child.pk).is_deleted)


class AdminTests(RestoreTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin_user)

    def test_every_farm_record_type_is_in_the_admin_without_being_listed_by_hand(self):
        farm_records = [m for m in apps.get_app_config('farm').get_models() if issubclass(m, AuditedModel)]
        self.assertGreaterEqual(len(farm_records), 3)
        for model in farm_records:
            self.assertIn(model, admin.site._registry, model.__name__)

    def test_the_admin_shows_deleted_records_but_cannot_edit_or_delete_anything(self):
        self.system.soft_delete(self.admin_user)
        page = self.client.get(reverse('admin:farm_system_changelist'))
        self.assertContains(page, 'RAS')
        self.assertNotContains(page, reverse('admin:farm_system_add'))
        change = reverse('admin:farm_system_change', args=[self.system.pk])
        self.assertEqual(self.client.post(change, {'name': 'Hacked'}).status_code, 403)
        self.assertEqual(self.client.post(reverse('admin:farm_system_delete', args=[self.system.pk])).status_code, 403)
        self.assertEqual(System.all_objects.get().name, 'RAS')

    def restore_via_admin(self, *records):
        return self.client.post(reverse('admin:farm_system_changelist'), {
            'action': 'restore', '_selected_action': [str(r.pk) for r in records],
        }, follow=True)

    def test_the_restore_action_brings_records_back(self):
        self.system.soft_delete(self.admin_user)
        response = self.restore_via_admin(self.system)
        self.assertContains(response, '1 record restored.')
        self.assertEqual(System.objects.count(), 1)

    def test_the_restore_action_explains_why_a_record_stays_deleted(self):
        self.system.soft_delete(self.admin_user)
        self.site.soft_delete(self.admin_user)
        response = self.restore_via_admin(self.system)
        self.assertContains(response, 'was not restored: Site “Bergen (BG)” is deleted.')
        self.assertEqual(System.objects.count(), 0)

    def test_restoring_needs_the_edit_permission_of_the_record_type(self):
        staff = get_user_model().objects.create_user('ola', 'ola@example.com', 'x', is_staff=True)
        staff.groups.add(role('Read only', 'view_system'))
        self.client.force_login(staff)
        self.system.soft_delete(self.admin_user)
        self.assertEqual(self.client.get(reverse('admin:farm_system_changelist')).status_code, 200)
        self.restore_via_admin(self.system)
        self.assertEqual(System.objects.count(), 0)


    def test_users_and_roles_cannot_be_changed_in_the_admin_where_nothing_is_logged(self):
        for url in ('admin:auth_user_changelist', 'admin:auth_group_changelist'):
            with self.assertRaises(Exception):   # no such route: they have their own screens
                reverse(url)
        self.assertEqual(self.client.get('/admin/auth/user/').status_code, 404)


class DeleteConfirmationPromiseTests(RestoreTestCase):
    def test_what_the_confirmation_promises_is_true_for_every_farm_record_type(self):
        # "It can be restored from the admin": a type missing from the admin would make that a lie.
        department = ProductionDepartment.objects.create(site=self.site, name='Hall', code='HA')
        self.client.force_login(self.admin_user)
        for url in (reverse('farm:site_delete', args=[self.site.pk]),
                    reverse('farm:productiondepartment_delete', args=[department.pk]),
                    reverse('farm:system_delete', args=[self.system.pk])):
            self.assertContains(self.client.get(url), 'restored from the admin')
        for name in ('site', 'productiondepartment', 'system'):
            self.assertEqual(self.client.get(reverse(f'admin:farm_{name}_changelist')).status_code, 200)

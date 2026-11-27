"""A deleted record can be brought back from the admin, checked like a new one."""
from unittest import mock

from django.apps import apps
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from core import softdelete
from core.models import AuditedModel, AuditLog

from ..models import ProductionDepartment, Site, Species, System
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

    def test_what_the_same_delete_took_with_it_comes_back_with_it(self):
        # F-029, F-067: a restore reverses the delete it undoes; a record deleted on its own before stays deleted.
        child = System.objects.create(site=self.site, name='Loop', code='LP', parent=self.system)
        earlier = System.objects.create(site=self.site, name='Old loop', code='OL', parent=self.system)
        self.client.force_login(self.admin_user)
        self.client.post(reverse('farm:system_delete', args=[earlier.pk]))
        self.client.post(reverse('farm:system_delete', args=[self.system.pk]))
        self.assertEqual(System.objects.count(), 0)
        softdelete.restore(System.all_objects.get(pk=self.system.pk), self.admin_user)
        self.assertEqual(set(System.objects.all()), {System.objects.get(pk=self.system.pk), System.objects.get(pk=child.pk)})
        self.assertTrue(System.all_objects.get(pk=earlier.pk).is_deleted)
        self.assertEqual(sorted(AuditLog.objects.filter(action='restore').values_list('entity_label', flat=True)),
                         ['Loop (LP)', 'RAS (RAS-1)'])

    def test_a_site_comes_back_with_its_production_departments(self):
        department = ProductionDepartment.objects.create(site=self.site, name='Hall', code='HA')
        self.client.force_login(self.admin_user)
        self.client.post(reverse('farm:site_delete', args=[self.site.pk]))
        softdelete.restore(Site.all_objects.get(), self.admin_user)
        self.assertEqual(ProductionDepartment.objects.get(), department)
        self.assertEqual(System.objects.get(), self.system)

    def test_a_record_restored_meanwhile_is_not_restored_twice(self):
        # F-003: two restores of one record take turns on its row; the second finds it live.
        self.system.soft_delete(self.admin_user)
        stale = System.all_objects.get()
        softdelete.restore(System.all_objects.get(), self.admin_user)
        with self.assertRaisesMessage(ValidationError, 'is not deleted'):
            softdelete.restore(stale, self.admin_user)
        self.assertEqual(AuditLog.objects.filter(action='restore').count(), 1)

    def test_a_clash_only_the_database_catches_is_refused_as_a_reason_not_a_failure(self):
        # F-003: the code taken by a record committed between the check and the write.
        self.system.soft_delete(self.admin_user)
        System.objects.create(site=self.site, name='New RAS', code='RAS-1')
        with mock.patch.object(System, 'validate_constraints'), mock.patch.object(System, 'validate_unique'):
            with self.assertRaises(ValidationError):
                softdelete.restore(System.all_objects.get(code='RAS-1', is_deleted=True), self.admin_user)
        self.assertEqual(System.objects.count(), 1)


class AdminTests(RestoreTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin_user)

    def test_every_record_type_of_every_app_is_in_the_admin_without_being_listed_by_hand(self):
        # Every app's records, not only the farm's: a new app's deleted records can be restored, or this fails (OUR-25).
        # Messages are the one exception, on purpose: the platform admin is not a member of other people's
        # conversations, and the Django admin does not list the messaging tables (README, Messages).
        records = [model for config in apps.get_app_configs() for model in config.get_models()
                   if issubclass(model, AuditedModel) and config.label != 'messaging']
        self.assertGreaterEqual(len({model._meta.app_label for model in records}), 4)
        for model in records:
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
        species = Species.objects.create(common_name='Atlantic salmon', scientific_name='Salmo salar', code='SAL',
                                         saltwater=True)
        self.client.force_login(self.admin_user)
        for url in (reverse('farm:site_delete', args=[self.site.pk]),
                    reverse('farm:productiondepartment_delete', args=[department.pk]),
                    reverse('farm:system_delete', args=[self.system.pk]),
                    reverse('farm:species_delete', args=[species.pk])):
            self.assertContains(self.client.get(url), 'restored from the admin')
        for name in ('site', 'productiondepartment', 'system', 'species'):
            self.assertEqual(self.client.get(reverse(f'admin:farm_{name}_changelist')).status_code, 200)

    def test_a_record_its_service_alone_writes_is_not_promised_a_restore(self):
        """The review of the HR branch, F-2: the admin offers no restore of a planned day, so the confirmation, in both
        looks, says it is entered again on its page instead."""
        from datetime import date, time

        from hr.models import Employee, Shift, ShiftAssignment
        person = Employee.objects.create(employee_number='E-1', last_name='Alfa', joined_on=date(2026, 1, 1))
        shift = Shift.objects.create(name='Early', code='EARLY', starts_at=time(6), ends_at=time(14))
        plan = ShiftAssignment.objects.create(employee=person, day=date(2026, 3, 2), shift=shift)
        self.client.force_login(self.admin_user)
        url = reverse('hr:shiftassignment_delete', args=[plan.pk])
        for look in ('classic', 'next'):
            with self.subTest(look=look):
                page = self.client.get(url, {'ui': look})
                self.assertNotContains(page, 'it can be restored from the admin')
                self.assertContains(page, 'It is not restored from the admin: one deleted by mistake is entered again on '
                                          'its page.')


class ConfirmedVersionTests(RestoreTestCase):
    """The review of the HR branch, F-3: a delete is of the record as the person confirmed it. The confirmation carries
    its version, as an edit does, and a record changed since is not deleted: said, as an edit is."""

    def test_the_confirmation_carries_the_version_in_both_looks(self):
        self.client.force_login(self.admin_user)
        url = reverse('farm:system_delete', args=[self.system.pk])
        self.assertContains(self.client.get(url, {'ui': 'classic'}), 'name="version" value="1"')
        self.assertEqual(self.client.get(url, {'ui': 'next'}).context['props']['version'], 1)

    def test_a_record_changed_since_its_confirmation_is_not_deleted(self):
        self.client.force_login(self.admin_user)
        System.objects.filter(pk=self.system.pk).update(name='RAS renamed', version=2)      # someone else's edit
        response = self.client.post(reverse('farm:system_delete', args=[self.system.pk]), {'version': '1'})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(System.all_objects.get(pk=self.system.pk).is_deleted)
        said = [str(message) for message in response.wsgi_request._messages]
        self.assertTrue(any('Someone else changed this' in text for text in said), said)
        self.client.post(reverse('farm:system_delete', args=[self.system.pk]), {'version': '2'})
        self.assertTrue(System.all_objects.get(pk=self.system.pk).is_deleted)

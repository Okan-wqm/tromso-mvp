"""The platform owner's settings (Company › Administration › Platform settings): one row, bounded by database checks,
read through core.platform only, changed on its page by who holds Platform settings: Edit, every change logged."""
import ast

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.urls import reverse

from farm.tests.helpers import role

from . import access, navigation, platform
from .middleware import PlatformSettingsMiddleware
from .models import AuditLog, PlatformSettings


class RowTests(TestCase):
    def test_the_migration_makes_the_one_row_with_todays_rules(self):
        row = PlatformSettings.objects.get()
        self.assertEqual((row.correction_window_days, row.second_approval_withdrawal), (31, False))

    def test_the_database_keeps_it_one_row(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            PlatformSettings.objects.create()

    def test_the_database_bounds_the_correction_window(self):
        for days in (0, 3651):
            with self.subTest(days=days), self.assertRaises(IntegrityError), transaction.atomic():
                PlatformSettings.objects.update(correction_window_days=days)
        PlatformSettings.objects.update(correction_window_days=3650)
        PlatformSettings.objects.update(correction_window_days=1)

    def test_the_database_keeps_the_row(self):
        # Never deleted, so never made again on a read (core 0015; core/tests_kept_rows.py).
        with self.assertRaises(IntegrityError), transaction.atomic():
            PlatformSettings.objects.all().delete()
        self.assertEqual(PlatformSettings.objects.count(), 1)


class ReaderTests(TestCase):
    def test_the_window_is_read_from_the_row(self):
        self.assertEqual(platform.correction_window_days(), 31)
        PlatformSettings.objects.update(correction_window_days=60)
        self.assertEqual(platform.correction_window_days(), 60)

    def test_the_old_constant_is_gone(self):
        self.assertFalse(hasattr(settings, 'STOCK_BACKDATE_DAYS'))

    def test_the_window_is_defined_here_only(self):
        """No area keeps a window of its own beside the setting (HR kept a fixed 31 days: the architecture audit of
        26.11.2026, H-1): every function of that name in the production code is this module's."""
        from .tests_data_access import production_modules
        found = [path for path, tree in production_modules() for node in ast.walk(tree)
                 if isinstance(node, ast.FunctionDef) and node.name == 'correction_window_days']
        self.assertEqual(found, ['core/platform.py'])

    def test_second_approval_follows_the_setting(self):
        self.assertFalse(platform.second_approval_required('withdrawal'))
        PlatformSettings.objects.update(second_approval_withdrawal=True)
        self.assertTrue(platform.second_approval_required('withdrawal'))

    def test_an_unknown_acknowledgement_is_an_error_not_a_no(self):
        with self.assertRaises(ValueError):
            platform.second_approval_required('fast')

    def test_the_alarms_rules_are_not_here(self):
        # The escalation time, the delays and the deadbands are the alarms' reference data (alarms.SeverityPolicy,
        # alarms.ParameterDeadband), per severity and per parameter: owner, alarm plan §7c.
        self.assertFalse(hasattr(platform, 'escalation_after'))


class RequestMemoTests(TestCase):
    """A page asks for the window once per row it lists; the row is read once per request."""

    def call(self, view):
        request = RequestFactory().get('/')
        return PlatformSettingsMiddleware(view)(request)

    def test_one_read_per_request(self):
        def view(request):
            for _ in range(5):
                platform.correction_window_days()
            return HttpResponse()
        with self.assertNumQueries(1):
            self.call(view)
        with self.assertNumQueries(1):          # the next request reads it again
            self.call(view)

    def test_a_save_in_the_request_is_read_at_once(self):
        def view(request):
            self.assertEqual(platform.correction_window_days(), 31)
            row = PlatformSettings.get()
            row.correction_window_days = 45
            row.save()
            self.assertEqual(platform.correction_window_days(), 45)
            return HttpResponse()
        self.call(view)

    def test_outside_a_request_every_call_reads(self):
        platform.correction_window_days()
        PlatformSettings.objects.update(correction_window_days=50)
        self.assertEqual(platform.correction_window_days(), 50)


class PageTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user('eier', 'eier@example.com', 'x')
        self.owner.groups.add(role('Platform owner', 'view_platformsettings', 'change_platformsettings'))
        self.reader = User.objects.create_user('les', 'les@example.com', 'x')
        self.reader.groups.add(role('Reader', 'view_platformsettings'))
        self.other = User.objects.create_user('annen', 'annen@example.com', 'x')
        self.row = PlatformSettings.get()

    def edit(self, **values):
        data = {'correction_window_days': 31, 'clock_tolerance_seconds': 300, 'unknown_withdrawal_days': 180,
                'version': self.row.version, **values}
        if data.pop('second_approval_withdrawal', False):
            data['second_approval_withdrawal'] = 'on'
        return self.client.post(reverse('core:platformsettings_edit', args=[self.row.pk]), data)

    def test_it_sits_under_company_administration_and_in_the_matrix(self):
        place = navigation.place('core.view_platformsettings')
        self.assertEqual((place.workspace.key, str(place.group.label)), ('company', 'Administration'))
        area = next(area for area in access.areas() if area.model == 'core.PlatformSettings')
        self.assertEqual(area.actions, ('view', 'change'))

    def test_reading_needs_the_right(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse('core:platformsettings_list')).status_code, 403)
        self.client.force_login(self.reader)
        page = self.client.get(reverse('core:platformsettings_list'))
        self.assertContains(page, '31')
        self.assertNotContains(page, reverse('core:platformsettings_edit', args=[self.row.pk]))

    def test_only_the_owner_changes_it_and_the_change_is_logged(self):
        self.client.force_login(self.reader)
        self.assertEqual(self.edit(correction_window_days=60).status_code, 403)
        self.client.force_login(self.owner)
        self.edit(correction_window_days=60, second_approval_withdrawal=True)
        self.row.refresh_from_db()
        self.assertEqual((self.row.correction_window_days, self.row.second_approval_withdrawal), (60, True))
        entry = AuditLog.objects.get(entity_type='platform settings', action='update')
        self.assertEqual(entry.changes['Correction window (days)'], ['31', '60'])
        self.assertEqual(entry.user, self.owner)

    def test_the_form_refuses_what_the_database_would(self):
        self.client.force_login(self.owner)
        for days in (0, 3651):
            with self.subTest(days=days):
                response = self.edit(correction_window_days=days)
                self.assertTrue(response.context['form'].errors['correction_window_days'])
        self.assertEqual(PlatformSettings.get().correction_window_days, 31)

    def test_nobody_adds_or_deletes_it(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get('/administration/platform-settings/new/').status_code, 404)
        self.assertEqual(self.client.post(f'/administration/platform-settings/{self.row.pk}/delete/').status_code, 404)

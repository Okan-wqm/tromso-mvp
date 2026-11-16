"""No link led to Leave types (flow fault B-03): its menu entry is hidden ("reached from Scheduling settings"), and the
Scheduling settings page linked Shifts and Holidays only, so the first leave request could not be filed (the type list
was empty and nothing said why). The page now lists the leave types and links their tab, the leave request form says
what is missing while no active type exists, and, for the class: every hidden menu entry is linked from the page of a
visible entry of its own group, so a hidden page can always be reached by clicking."""
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import translation

from core import navigation

from ..models import LeaveType
from .test_leave import LeaveTestCase
from .test_scheduling_settings import SettingsTestCase


class SchedulingSettingsPageTests(SettingsTestCase):
    def test_the_page_lists_the_leave_types_and_leads_to_their_tab(self):
        self.user.groups.first().permissions.add(*_perms('view_leavetype'))
        self.user = get_user_model().objects.get(pk=self.user.pk)            # the permission cache is the user's
        self.client.force_login(self.user)
        page = self.client.get(reverse('hr:schedulingsettings_list'))
        self.assertContains(page, 'No leave types yet: a leave request cannot be filed until there is one.')
        self.assertContains(page, f'href="{reverse("hr:leavetype_list")}"')
        self.assertContains(page, 'Manage leave types')
        LeaveType.objects.create(name='Annual leave', code='ANNUAL', annual_days=25)
        LeaveType.objects.create(name='Sick leave', code='SICK', needs_approval=False, status='inactive')
        page = self.client.get(reverse('hr:schedulingsettings_list'))
        self.assertContains(page, 'Annual leave (ANNUAL) · 25 days a year')
        self.assertContains(page, 'Sick leave (SICK) · granted without approval · Inactive')
        self.assertNotContains(page, 'No leave types yet')

    def test_without_the_right_to_read_them_the_link_is_not_offered(self):
        page = self.client.get(reverse('hr:schedulingsettings_list'))
        self.assertNotContains(page, reverse('hr:leavetype_list'))


def _perms(*codenames):
    from django.contrib.auth.models import Permission
    return Permission.objects.filter(codename__in=codenames)


class LeaveRequestFormHintTests(LeaveTestCase):
    HINT = 'There is no active leave type yet, so a request cannot be filed.'

    def test_the_form_says_what_is_missing_while_no_active_leave_type_exists(self):
        self.client.force_login(self.ann_user)
        url = reverse('hr:production_leaverequest_create')
        self.assertNotContains(self.client.get(url), self.HINT)              # three active types: nothing to say
        LeaveType.objects.update(status='inactive')
        page = self.client.get(url)
        self.assertContains(page, self.HINT)
        self.assertContains(page, 'Scheduling settings › Leave types')
        self.assertEqual(list(page.context['form'].fields['leave_type'].queryset), [])

    def test_the_hint_names_the_place_by_the_menus_own_names(self):
        """The path was typed into the sentence (review F-09); it is read from the menu, as the correction window's
        refusal reads its own (core.navigation.trail, B-07), so it follows the menu."""
        LeaveType.objects.update(status='inactive')
        from ..forms.leave import LeaveRequestForm

        def hint():
            return str(LeaveRequestForm(user=self.ann_user).fields['leave_type'].help_text)

        where = navigation.trail('hr.view_schedulingsettings', '')
        self.assertEqual(where, 'Company › HR › Time & shifts › Scheduling settings')
        self.assertEqual(hint(), f'{self.HINT} Leave types are added in {where} › Leave types, by a person whose role '
                                 'may.')
        with mock.patch.object(navigation, 'trail', return_value='Company › People › Planning'):
            self.assertEqual(hint(), f'{self.HINT} Leave types are added in Company › People › Planning › Leave '
                                     'types, by a person whose role may.')

    def test_the_hint_is_translated(self):
        self.addCleanup(translation.activate, 'en')
        LeaveType.objects.update(status='inactive')
        from ..forms.leave import LeaveRequestForm
        for language in ('nb', 'tr'):
            with translation.override(language):
                text = str(LeaveRequestForm(user=self.ann_user).fields['leave_type'].help_text)
                self.assertTrue(text and 'There is no active' not in text, language)
                self.assertIn({'nb': 'i Selskap › HR › Tid og skift › Planleggingsinnstillinger › Permisjonstyper, ',
                               'tr': ', Şirket › İK › Zaman ve vardiyalar › Planlama ayarları › İzin türleri altında, '}
                              [language], text)


class HiddenEntriesAreLinkedTests(TestCase):
    """The class of B-03: an entry without a menu line must be reachable from a page that has one."""

    def test_every_hidden_menu_entry_is_linked_from_a_visible_page_of_its_group(self):
        boss = get_user_model().objects.create_superuser('root', 'root@example.com', 'x')
        self.client.force_login(boss)
        hidden = [(group, entry) for workspace in navigation.workspaces() for section in workspace.sections
                  for group in section.groups for entry in group.entries if entry.hidden]
        self.assertTrue(hidden)                                              # there are such entries to check
        for group, entry in hidden:
            with self.subTest(entry=entry.url_name):
                link = f'href="{entry.url()}"'
                pages = [self.client.get(each.url()) for each in group.entries if not each.hidden]
                self.assertTrue(any(link in page.content.decode() for page in pages if page.status_code == 200),
                                f'No visible page of “{group.label}” links {entry.url()}')

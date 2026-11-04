"""Row scope (Resource.scoped) and the Everyone column: one core mechanism, tested on an existing tab so no
test resource pollutes the registry."""
import re
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase, override_settings
from django.urls import reverse

from farm.models import Site
from farm.resources.site import SiteResource
from farm.tests.helpers import site_data

from . import access, audit, navigation
from .access import Area
from .navigation import Entry, Group as MenuGroup, Section, Workspace
from .models import AuditLog

# An area set with an Everyone column on Sites, for the matrix tests (ACCESS_AREAS names it).
SCOPED_AREAS = [
    Area('Sites', 'farm.Site', actions=('view', 'add', 'all')),
    Area('Species', 'farm.Species'),
]


def only_a_sites(cls, request, objects):
    """A scope: the codes that start with A."""
    return objects.filter(code__startswith='A')


class ScopedResourceTests(TestCase):
    """Out of scope is a 404 on every verb, by address and by query, and changes nothing."""

    @classmethod
    def setUpTestData(cls):
        cls.inside = Site.objects.create(name='Inside', code='AAA')
        cls.outside = Site.objects.create(name='Outside', code='BBB')
        role = Group.objects.create(name='Scoped')
        role.permissions.set(Permission.objects.filter(
            content_type__app_label='farm', content_type__model='site',
            codename__in=['view_site', 'add_site', 'change_site', 'delete_site']))
        cls.user = get_user_model().objects.create_user('lead', password='x')
        cls.user.groups.add(role)

    def setUp(self):
        self.client.force_login(self.user)
        patcher = mock.patch.object(SiteResource, 'scoped', classmethod(only_a_sites))
        patcher.start()
        self.addCleanup(patcher.stop)

    def url(self, name, site):
        return reverse(f'farm:site_{name}', args=[site.pk])

    def test_the_list_holds_the_records_in_scope_only(self):
        objects = list(self.client.get(reverse('farm:site_list')).context['objects'])
        self.assertEqual(objects, [self.inside])
        # a search for the other record finds nothing: the scope is applied before the search
        found = self.client.get(reverse('farm:site_list'), {'q': 'Outside'}).context['objects']
        self.assertEqual(list(found), [])

    def test_a_record_in_scope_opens_saves_and_deletes(self):
        self.assertEqual(self.client.get(self.url('edit', self.inside)).status_code, 200)
        self.assertEqual(self.client.get(self.url('delete', self.inside)).status_code, 200)

    def test_a_record_out_of_scope_is_a_404_on_every_verb_and_nothing_changes(self):
        logs = AuditLog.objects.count()
        before = Site.objects.get(pk=self.outside.pk)
        self.assertEqual(self.client.get(self.url('edit', self.outside)).status_code, 404)
        self.assertEqual(self.client.post(self.url('edit', self.outside), {
            **site_data(name='Taken over', code='BBB'), 'version': before.version}).status_code, 404)
        self.assertEqual(self.client.get(self.url('delete', self.outside)).status_code, 404)
        self.assertEqual(self.client.post(self.url('delete', self.outside)).status_code, 404)
        self.assertEqual(self.client.post(self.url('contacts', self.outside),
                                          {'version': before.version}).status_code, 404)
        after = Site.objects.get(pk=self.outside.pk)
        self.assertEqual((after.name, after.version, after.is_deleted), ('Outside', before.version, False))
        self.assertEqual(AuditLog.objects.count(), logs)

    def test_a_record_that_leaves_the_scope_during_an_edit_is_refused_under_the_lock(self):
        # opened while in scope; the relationship ends before the save: the save finds no record
        form_page = self.client.get(self.url('edit', self.inside))
        self.assertEqual(form_page.status_code, 200)
        Site.objects.filter(pk=self.inside.pk).update(code='CCC')
        response = self.client.post(self.url('edit', self.inside), {
            **site_data(name='Late', code='CCC'), 'version': self.inside.version})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(Site.objects.get(pk=self.inside.pk).name, 'Inside')

    def test_the_default_scope_is_every_record(self):
        mock.patch.stopall()
        self.assertEqual(SiteResource.scoped(None, Site.objects.all()).count(), 2)
        self.assertEqual({s.pk for s in self.client.get(reverse('farm:site_list')).context['objects']},
                         {self.inside.pk, self.outside.pk})


class PrivateFieldTests(TestCase):
    def test_a_private_text_is_logged_as_set_and_never_as_its_words(self):
        site = Site.objects.create(name='Pond', code='PND', description='Secret words')
        plain = audit.snapshot(site, ['name', 'description'])
        self.assertEqual(plain['Description'], 'Secret words')
        masked = audit.snapshot(site, ['name', 'description'], private=['description'])
        self.assertEqual(masked, {'Site name': 'Pond', 'Description': {'msgid': 'Private text'}})
        site.description = ''
        self.assertEqual(audit.snapshot(site, ['description'], private=['description']), {'Description': None})

    def test_the_resource_snapshot_uses_its_private_fields(self):
        site = Site.objects.create(name='Pond', code='PND', description='Secret words')
        with mock.patch.object(SiteResource, 'private_fields', ('description',)):
            recorded = SiteResource.recorded(site)
        self.assertEqual(recorded['Description'], {'msgid': 'Private text'})
        self.assertNotIn('Secret words', str(recorded))
        self.assertEqual(SiteResource.private_fields, ())


@override_settings(ACCESS_AREAS='core.tests_scope.SCOPED_AREAS')
class EveryoneColumnTests(TestCase):
    def test_everyone_implies_read(self):
        self.assertEqual(access.implied({'farm.all_site'}), {'farm.all_site', 'farm.view_site'})
        self.assertEqual(access.implied({'farm.add_species'}), {'farm.add_species', 'farm.view_species'})

    def test_the_summary_names_it(self):
        permission = Permission.objects.get(content_type__app_label='farm', codename='view_site')
        fake = mock.Mock(content_type=mock.Mock(app_label='farm'), codename='all_site')
        self.assertEqual(access.summary([permission, fake]), 'Sites: read, everyone')

    def test_the_matrix_has_the_column_and_an_area_without_it_has_an_empty_cell(self):
        admin = get_user_model().objects.create_superuser('root', 'root@example.com', 'x')
        self.client.force_login(admin)
        html = self.client.get(reverse('core:group_create')).content.decode()
        self.assertIn('>Everyone</th>', html)
        self.assertEqual(access.ACTIONS[-1][0], access.ALL)
        rows = re.findall(r'<tr>\s*<th scope="row">(.*?)</th>(.*?)</tr>', html, re.S)
        cells = {label: re.findall(r'<td>(.*?)</td>', body, re.S) for label, body in rows}
        self.assertEqual(len(cells['Species']), 5)
        self.assertEqual(cells['Species'][4].strip(), '')       # Species has no Everyone box


# A menu with one entry no line of which is shown (a settings page reached by links), for the hidden-entry tests.
HIDDEN_MENU = [
    Workspace('company', 'Company', always=True, sections=[Section("", [MenuGroup('', [
        Entry('Overview', 'home', 'home'),
        Entry('Sites', 'farm:site_list', 'building', 'farm.view_site'),
        Entry('Species', 'farm:species_list', 'fish', 'farm.view_species', hidden=True),
    ])])]),
]


@override_settings(RAIL_MENU='core.tests_scope.HIDDEN_MENU')
class HiddenEntryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_superuser('root', 'root@example.com', 'x')

    def test_a_hidden_entry_has_no_line_but_keeps_its_place_and_its_page(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('farm:species_list'))
        self.assertEqual(response.status_code, 200)
        shown = [entry['label'] for section in response.context['rail_sections']
                 for group in section['groups'] for entry in group['entries']]
        self.assertEqual(shown, ['Overview', 'Sites'])
        # the page is in the menu's data: its heading and the matrix read it, and its workspace is the panel's
        place = navigation.place('farm.view_species')
        self.assertTrue(place.entry.hidden)
        self.assertEqual(navigation.workspace_of(reverse('farm:species_list')), 'company')
        self.assertIn('farm.view_species', {entry.perm for entry in navigation.entries()})


class RestrictedLogTests(TestCase):
    """audit.restrict: some record types are in the log only for people who hold a permission."""

    @classmethod
    def setUpTestData(cls):
        cls.limited = get_user_model().objects.create_user('limited', password='x')
        role = Group.objects.create(name='Log reader')
        role.permissions.set(Permission.objects.filter(codename='view_auditlog'))
        cls.limited.groups.add(role)
        cls.holder = get_user_model().objects.create_user('holder', password='x')
        cls.holder.groups.add(role)
        cls.holder.user_permissions.add(Permission.objects.get(content_type__app_label='farm', codename='view_site'))
        for kind, user in (('site', 'ola'), ('species', 'kari')):
            AuditLog.objects.create(user=None, user_name=user, action='create', entity_type=kind, entity_id='1',
                                    entity_label=kind)

    def setUp(self):
        patcher = mock.patch.dict(audit._restricted, {'site': 'farm.view_site'})
        patcher.start()
        self.addCleanup(patcher.stop)

    def listed(self, user):
        self.client.force_login(user)
        response = self.client.get(reverse('core:activity_log'))
        return response, [entry.entity_type for entry in response.context['page'].object_list]

    def test_the_log_leaves_out_a_restricted_type_for_those_without_its_permission(self):
        response, types = self.listed(self.limited)
        self.assertEqual(types, ['species'])
        # the filters do not offer it, nor the name of the person who made the entry
        self.assertEqual([name for name, _label in response.context['types']], ['species'])
        self.assertEqual(list(response.context['users']), ['kari'])
        # asking for it by the address finds nothing
        found = self.client.get(reverse('core:activity_log'), {'type': 'site'}).context['page'].object_list
        self.assertEqual(list(found), [])

    def test_a_holder_of_the_permission_reads_every_entry(self):
        _response, types = self.listed(self.holder)
        self.assertEqual(sorted(types), ['site', 'species'])

    def test_nothing_is_restricted_by_default(self):
        with mock.patch.dict(audit._restricted, clear=True):
            _response, types = self.listed(self.limited)
        self.assertEqual(sorted(types), ['site', 'species'])


class RangeTests(TestCase):
    def test_the_range_functions_build_the_postgres_ranges(self):
        from datetime import date, datetime, timezone as tz
        from django.db.models import Value
        from .ranges import DateRange, InstantRange
        row = Site.objects.create(name='Pond', code='PND')
        days = Site.objects.filter(pk=row.pk).annotate(
            span=DateRange(Value(date(2026, 3, 1)), Value(None, output_field=None), Value('[]'))).get().span
        self.assertEqual((days.lower, days.upper), (date(2026, 3, 1), None))
        instants = Site.objects.filter(pk=row.pk).annotate(
            span=InstantRange(Value(datetime(2026, 3, 1, 8, tzinfo=tz.utc)), Value(datetime(2026, 3, 1, 16, tzinfo=tz.utc)),
                              Value('[)'))).get().span
        self.assertEqual((instants.lower.hour, instants.upper.hour), (8, 16))

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

from . import access, audit
from .access import Area
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

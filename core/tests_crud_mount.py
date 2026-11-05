"""A tab served a second time under a Mount (core.crud.Mount): the same Resource, views and records under another address
and panel, narrowed by the tab's own `scoped`. Tested on an existing tab (Sites) with a test URL configuration and a test
menu, so no test resource pollutes the registry."""
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.template import Context, Template
from django.test import RequestFactory, TestCase, override_settings
from django.urls import URLResolver, include, path, reverse

from config import navigation as project_menu, urls as project_urls
from farm import urls as farm_urls
from farm.models import Site
from farm.resources.site import SiteResource
from farm.tests.helpers import contacts_data, site_data

from .crud import Mount, Resource, mount_of, mounted_name
from .models import AuditLog
from .navigation import Entry, Group as MenuGroup, Section, Workspace

LAB = Mount('lab', 'lab/sites')


def _mounted_routes():
    with mock.patch.object(SiteResource, 'mounts', (LAB,)):
        return [route for route in SiteResource.urls() if route.name.startswith('lab_')]


def _with_mounted_farm(patterns):
    """The project's URLs with the mounted Sites routes added to the farm namespace."""
    farm = farm_urls.urlpatterns + _mounted_routes()
    return [path('', include((farm, 'farm'))) if isinstance(item, URLResolver) and item.app_name == 'farm' else item
            for item in patterns]


urlpatterns = _with_mounted_farm(project_urls.urlpatterns)

# The project's menu plus a Lab panel whose one entry is the mounted Sites list (its heading and title are the mount's).
MENU = project_menu.WORKSPACES + [
    Workspace('lab', 'Lab', sections=[Section('Lab section', [MenuGroup('Lab group', [
        Entry('Lab sites', 'farm:lab_site_list', 'building', 'farm.view_site'),
    ])])]),
]


def lab_scope(cls, request, objects):
    """A scope that narrows only under the mount: there, the codes that start with A."""
    return objects.filter(code__startswith='A') if mount_of(request) == LAB else objects


class MountNamesTests(TestCase):
    def test_a_url_name_without_a_mount_is_unchanged_and_with_one_carries_its_key(self):
        self.assertEqual(SiteResource.url_name('list'), 'farm:site_list')
        self.assertEqual(SiteResource.url_name('list', None), 'farm:site_list')
        self.assertEqual(SiteResource.url_name('edit', LAB), 'farm:lab_site_edit')

    def test_mounted_name_prefixes_the_name_inside_its_namespace(self):
        self.assertEqual(mounted_name('hr:punch', LAB), 'hr:lab_punch')
        self.assertEqual(mounted_name('hr:punch', None), 'hr:punch')
        self.assertEqual(mounted_name('home', LAB), 'lab_home')

    def test_a_request_without_a_mount_has_none(self):
        self.assertIsNone(mount_of(RequestFactory().get('/')))
        self.assertIsNone(mount_of(None))

    def test_a_tab_without_mounts_has_its_routes_only_and_the_registry_one_entry_per_model(self):
        self.assertEqual(SiteResource.mounts, ())
        names = [route.name for route in SiteResource.urls()]
        self.assertEqual(names, ['site_list', 'site_create', 'site_edit', 'site_delete', 'site_contacts'])
        with mock.patch.object(SiteResource, 'mounts', (LAB,)):
            names = [route.name for route in SiteResource.urls()]
            self.assertEqual(names[:5], ['site_list', 'site_create', 'site_edit', 'site_delete', 'site_contacts'])
            self.assertEqual(names[5:], ['lab_site_list', 'lab_site_create', 'lab_site_edit', 'lab_site_delete',
                                         'lab_site_contacts'])
            self.assertEqual(str(SiteResource.urls()[5].pattern), 'lab/sites/')
        models = [tab.model for tab in Resource.registry]
        self.assertEqual(len(models), len(set(models)), 'one tab per model')


@override_settings(ROOT_URLCONF='core.tests_crud_mount', RAIL_MENU='core.tests_crud_mount.MENU')
class MountedPagesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.inside = Site.objects.create(name='Inside', code='AAA')
        cls.outside = Site.objects.create(name='Outside', code='BBB')
        role = Group.objects.create(name='Sites')
        role.permissions.set(Permission.objects.filter(
            content_type__app_label='farm', content_type__model='site',
            codename__in=['view_site', 'add_site', 'change_site', 'delete_site']))
        cls.user = get_user_model().objects.create_user('lead', password='x')
        cls.user.groups.add(role)

    def setUp(self):
        self.client.force_login(self.user)
        for name, value in (('scoped', classmethod(lab_scope)), ('mounts', (LAB,))):
            patcher = mock.patch.object(SiteResource, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def url(self, name, site=None):
        return reverse(f'farm:lab_site_{name}', args=[site.pk] if site else [])

    def test_the_mounted_routes_are_under_the_mount_address(self):
        self.assertEqual(self.url('list'), '/lab/sites/')
        self.assertEqual(self.url('create'), '/lab/sites/new/')
        self.assertEqual(self.url('edit', self.inside), f'/lab/sites/{self.inside.pk}/')

    def test_the_mounted_list_holds_the_mount_rows_and_the_plain_one_all(self):
        mounted = self.client.get(self.url('list'))
        self.assertEqual(list(mounted.context['objects']), [self.inside])
        self.assertEqual(mounted.context['list_url'], '/lab/sites/')
        self.assertEqual(mounted.context['create_url'], '/lab/sites/new/')
        plain = self.client.get(reverse('farm:site_list'))
        self.assertEqual({site.pk for site in plain.context['objects']}, {self.inside.pk, self.outside.pk})
        self.assertEqual(plain.context['list_url'], reverse('farm:site_list'))

    def test_the_mounted_page_takes_its_heading_and_title_and_panel_from_the_mounted_entry(self):
        mounted = self.client.get(self.url('list'))
        self.assertEqual((str(mounted.context['group']), str(mounted.context['title'])), ('Lab group', 'Lab sites'))
        self.assertEqual(mounted.context['workspace']['key'], 'lab')
        plain = self.client.get(reverse('farm:site_list'))
        self.assertEqual((str(plain.context['group']), str(plain.context['title'])), ('Facility', 'Sites'))

    def test_a_record_outside_the_mount_is_a_404_on_every_mounted_verb_and_nothing_changes(self):
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
        # the same record opens on the plain route
        self.assertEqual(self.client.get(reverse('farm:site_edit', args=[self.outside.pk])).status_code, 200)

    def test_a_create_on_the_mount_opens_the_new_record_on_the_mount(self):
        response = self.client.post(self.url('create'), site_data(name='Arendal', code='ARD'))
        created = Site.objects.get(code='ARD')
        self.assertRedirects(response, self.url('edit', created), fetch_redirect_response=False)

    def test_a_save_on_the_mount_returns_to_the_mounted_list(self):
        response = self.client.post(self.url('edit', self.inside), {
            **site_data(name='Inside again', code='AAA'), 'version': self.inside.version})
        self.assertRedirects(response, self.url('list'), fetch_redirect_response=False)
        self.assertEqual(Site.objects.get(pk=self.inside.pk).name, 'Inside again')

    def test_an_outdated_save_on_the_mount_returns_to_the_mounted_form(self):
        Site.objects.filter(pk=self.inside.pk).update(version=self.inside.version + 1)
        response = self.client.post(self.url('edit', self.inside), {
            **site_data(name='Late', code='AAA'), 'version': self.inside.version})
        self.assertRedirects(response, self.url('edit', self.inside), fetch_redirect_response=False)

    def test_a_delete_on_the_mount_returns_to_the_mounted_list(self):
        response = self.client.post(self.url('delete', self.inside))
        self.assertRedirects(response, self.url('list'), fetch_redirect_response=False)
        self.assertTrue(Site.all_objects.get(pk=self.inside.pk).is_deleted)

    def test_a_row_list_on_the_mount_returns_to_the_mounted_form(self):
        get = self.client.get(self.url('contacts', self.inside))
        self.assertRedirects(get, self.url('edit', self.inside), fetch_redirect_response=False)
        saved = self.client.post(self.url('contacts', self.inside), contacts_data([], record=self.inside))
        self.assertRedirects(saved, self.url('edit', self.inside), fetch_redirect_response=False)

    def test_the_mounted_filter_names_a_route_under_the_request_mount(self):
        template = Template("{% load crud %}{% url 'farm:site_list'|mounted:request %}")
        plain = RequestFactory().get('/')
        self.assertEqual(template.render(Context({'request': plain})), reverse('farm:site_list'))
        on_mount = RequestFactory().get('/lab/sites/')
        on_mount.mount = LAB
        self.assertEqual(template.render(Context({'request': on_mount})), '/lab/sites/')

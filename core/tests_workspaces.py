"""The console is split into panels (workspaces), switched from the top left."""
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.test import RequestFactory, TestCase
from django.urls import reverse

from farm.resources.site import SiteResource
from farm.resources.system import SystemResource
from farm.tests.helpers import role

from . import access, navigation
from .resources import RoleResource


class WorkspaceTestCase(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('ali', 'ali@example.com', 'x')
        self.admin = get_user_model().objects.create_superuser('root', 'root@example.com', 'x')

    def sign_in(self, user):
        self.client.force_login(user)

    def page(self, url):
        return self.client.get(url)

    def labels(self, response):
        return [entry['label'] for section in response.context['rail_sections']
                for group in section['groups'] for entry in group['entries']]


class WorkspaceOfPathTests(TestCase):
    def test_every_menu_entry_belongs_to_exactly_one_panel(self):
        owners = {}
        for workspace in navigation.workspaces():
            for entry in workspace.entries():
                self.assertNotIn(entry.url_name, owners, f'{entry.url_name} is in two panels')
                owners[entry.url_name] = workspace.key

    def test_a_page_is_found_in_its_panel(self):
        self.assertEqual(navigation.workspace_of(reverse('home')), 'company')
        self.assertEqual(navigation.workspace_of(reverse('farm:site_list')), 'company')
        self.assertEqual(navigation.workspace_of(reverse('production_home')), 'production')
        self.assertEqual(navigation.workspace_of(reverse('farm:system_edit', args=['00000000-0000-0000-0000-000000000001'])), 'production')
        self.assertEqual(navigation.workspace_of(reverse('farm:productiondepartment_list')), 'production')
        self.assertEqual(navigation.workspace_of(reverse('core:group_list')), 'company')

    def test_a_page_in_no_menu_has_no_panel(self):
        self.assertIsNone(navigation.workspace_of(reverse('password_change')))


class PanelSwitcherTests(WorkspaceTestCase):
    def test_company_shows_administration_and_sites_and_production_shows_the_farm_side(self):
        self.sign_in(self.admin)
        company = self.page(reverse('farm:site_list'))
        self.assertEqual(company.context['workspace']['key'], 'company')
        self.assertEqual(self.labels(company), ['Overview', 'Sites', 'Storage locations', 'Library', 'Knowledge entries',
                                                 'Activity log', 'Roles', 'Users', 'Database'])
        production = self.page(reverse('farm:system_list'))
        self.assertEqual(production.context['workspace']['key'], 'production')
        self.assertEqual(self.labels(production), ['Overview', 'Production departments', 'Systems', 'Equipment',
                                                    'Tanks, ponds & cages', 'Monitoring boards', 'Sampling points', 'Species', 'Feeds',
                                                    'Water limits', 'Medicines', 'Handling rules', 'Slaughter facilities',
                                                    'Suppliers', 'Production units', 'Monitoring', 'Water chemistry', 'Storage', 'Tasks',
                                                    'Recurring tasks', 'Meal board', 'Records', 'Protocols', 'Assignments',
                                                    'Harvested', 'Harvest plan', 'Production plans', 'Treatments',
                                                    'Health events', 'Sea-lice counts', 'Regulatory reports', 'Messages'])

    def test_the_switcher_lists_the_panels_and_marks_the_current_one(self):
        self.sign_in(self.admin)
        response = self.page(reverse('farm:system_list'))
        self.assertEqual([(p['key'], p['label']) for p in response.context['workspaces']],
                         [('company', 'Company'), ('production', 'Production'), ('sensors', 'Sensors')])
        self.assertContains(response, 'data-menu-toggle', count=2)    # the switcher and the user menu
        self.assertContains(response, '<span class="workspace-name">Production</span>', html=True)
        self.assertContains(response, 'aria-current="true">Production</a>')
        self.assertContains(response, f'href="{reverse("home")}"')

    def test_each_panel_links_to_its_first_page_for_this_person(self):
        self.sign_in(self.admin)
        panels = {p['key']: p['url'] for p in self.page(reverse('home')).context['workspaces']}
        self.assertEqual(panels, {'company': reverse('home'), 'production': reverse('production_home'),
                                  'sensors': reverse('sensors:home')})
        production_only = get_user_model().objects.create_user('per', 'per@example.com', 'x')
        production_only.groups.add(role('Systems', 'view_system'))
        self.sign_in(production_only)
        self.assertEqual({p['key']: p['url'] for p in self.page(reverse('home')).context['workspaces']},
                         {'company': reverse('home'), 'production': reverse('production_home')})

    def test_a_panel_the_person_may_not_use_is_not_offered(self):
        self.user.groups.add(role('Sites only', 'view_site'))
        self.sign_in(self.user)
        response = self.page(reverse('farm:site_list'))
        self.assertEqual([p['key'] for p in response.context['workspaces']], ['company'])
        self.assertNotContains(response, 'workspace-panel')    # one panel: a plain brand, no switcher
        self.assertContains(response, '<span class="workspace-name">Company</span>', html=True)

    def test_someone_with_only_production_rights_reaches_production(self):
        self.user.groups.add(role('Systems only', 'view_system'))
        self.sign_in(self.user)
        self.assertEqual(self.labels(self.page(reverse('home'))), ['Overview'])    # everyone has the company overview
        response = self.page(reverse('farm:system_list'))
        self.assertEqual(response.context['workspace']['key'], 'production')
        self.assertEqual(self.labels(response), ['Overview', 'Systems'])

    def test_everyone_has_the_overview_and_nothing_else_without_rights(self):
        self.sign_in(self.user)
        response = self.page(reverse('home'))
        self.assertEqual([p['key'] for p in response.context['workspaces']], ['company'])
        self.assertEqual(self.labels(response), ['Overview'])
        self.assertNotContains(response, 'workspace-panel')


class PanelMemoryTests(WorkspaceTestCase):
    def test_a_page_in_no_panel_keeps_the_panel_the_person_came_from(self):
        self.sign_in(self.admin)
        self.page(reverse('farm:system_list'))
        self.assertEqual(self.client.session['workspace'], 'production')
        response = self.page(reverse('password_change'))
        self.assertEqual(response.context['workspace']['key'], 'production')
        self.assertEqual(self.labels(response), ['Overview', 'Production departments', 'Systems', 'Equipment',
                                                  'Tanks, ponds & cages', 'Monitoring boards', 'Sampling points', 'Species', 'Feeds',
                                                  'Water limits', 'Medicines', 'Handling rules', 'Slaughter facilities',
                                                  'Suppliers', 'Production units', 'Monitoring', 'Water chemistry', 'Storage', 'Tasks',
                                                  'Recurring tasks', 'Meal board', 'Records', 'Protocols', 'Assignments',
                                                  'Harvested', 'Harvest plan', 'Production plans', 'Treatments',
                                                  'Health events', 'Sea-lice counts', 'Regulatory reports', 'Messages'])
        self.page(reverse('farm:site_list'))
        self.assertEqual(self.page(reverse('password_change')).context['workspace']['key'], 'company')

    def test_a_remembered_panel_the_person_lost_access_to_is_not_used(self):
        self.user.groups.add(role('Systems only', 'view_system'))
        self.sign_in(self.user)
        self.page(reverse('farm:system_list'))
        self.user.groups.clear()
        self.user.groups.add(role('Sites only', 'view_site'))
        response = self.page(reverse('password_change'))
        self.assertEqual(response.context['workspace']['key'], 'company')

    def test_the_sign_in_page_has_no_menu_and_remembers_nothing(self):
        self.client.logout()
        response = self.client.get(reverse('login'))
        self.assertNotIn('workspace', response.context)
        self.assertNotIn('workspace', self.client.session)


class MainHeadingTests(WorkspaceTestCase):
    """Production's menu has main headings (Setup, Operations) over its groups."""

    def headings(self, response):
        return [(section['label'], [group['label'] for group in section['groups']])
                for section in response.context['rail_sections']]

    def test_production_puts_its_structure_under_setup_and_its_daily_records_under_operations(self):
        self.sign_in(self.admin)
        response = self.page(reverse('farm:system_list'))
        self.assertEqual(self.headings(response),
                         [('', ['']), ('Setup', ['Facility structure', 'Reference data', 'Harvest and logistics',
                                                 'Purchasing']),
                          ('Operations', ['', 'Feeding', 'Harvest', 'Health']), ('Reports', ['']),
                          ('Communication', [''])])
        self.assertContains(response, '<p class="rail-section">Operations</p>', html=True)
        self.assertContains(response, '<p class="rail-section">Setup</p>', html=True)
        self.assertContains(response, '<p class="rail-group">Facility structure</p>', html=True)
        self.assertContains(response, '<p class="rail-group">Reference data</p>', html=True)
        self.assertContains(response, '<p class="rail-group">Harvest and logistics</p>', html=True)
        self.assertContains(response, '<p class="rail-group">Purchasing</p>', html=True)

    def test_company_has_no_main_headings(self):
        self.sign_in(self.admin)
        response = self.page(reverse('home'))
        self.assertEqual(self.headings(response), [('', ['', 'Facility', 'Knowledge', 'Administration'])])
        self.assertNotContains(response, 'rail-section')

    def test_a_heading_with_nothing_the_person_may_read_is_not_shown(self):
        self.sign_in(self.user)
        self.user.groups.add(role('Sites only', 'view_site'))
        response = self.page(reverse('production_home'))
        self.assertEqual(self.headings(response), [('', ['', 'Facility'])])    # the company menu: no Production rights


class MenuPlacementTests(TestCase):
    """The menu is the one place that says where a page sits; the role matrix and the small heading
    above a tab's title follow it, so they cannot drift apart."""

    def test_a_page_is_placed_where_its_menu_entry_is(self):
        place = navigation.place('farm.view_system')
        self.assertEqual((place.workspace.key, place.section.label, place.group.label),
                         ('production', 'Setup', 'Facility structure'))
        self.assertEqual(str(place.path), 'Production · Setup · Facility structure')
        self.assertEqual(str(navigation.place('farm.view_site').path), 'Company · Facility')

    def test_the_role_matrix_groups_areas_as_the_menu_does(self):
        groups = {area.model: str(area.group) for area in access.areas()}
        self.assertEqual(groups, {
            'farm.Site': 'Company · Facility',
            'inventory.StorageLocation': 'Company · Facility',
            'farm.ProductionDepartment': 'Production · Setup · Facility structure',
            'farm.System': 'Production · Setup · Facility structure',
            'farm.Equipment': 'Production · Setup · Facility structure',
            'farm.Tank': 'Production · Setup · Facility structure',
            'monitoring.MonitorBoard': 'Production · Setup · Facility structure',
            'farm.SamplingPoint': 'Production · Setup · Facility structure',
            'farm.Species': 'Production · Setup · Reference data',
            'farm.Feed': 'Production · Setup · Reference data',
            'farm.WaterLimit': 'Production · Setup · Reference data',
            'farm.Medicine': 'Production · Setup · Reference data',
            'farm.SlaughterFacility': 'Production · Setup · Harvest and logistics',
            'farm.HandlingRule': 'Production · Setup · Reference data',
            'farm.Supplier': 'Production · Setup · Purchasing',
            'farm.StockOperation': 'Production · Operations',
            'farm.FeedingRecord': 'Production · Operations · Feeding',
            'farm.FeedingProtocol': 'Production · Operations · Feeding',
            'farm.ProtocolAssignment': 'Production · Operations · Feeding',
            'farm.WaterMeasurement': 'Production · Operations',
            'inventory.InventoryOperation': 'Production · Operations',
            'farm.HarvestRecord': 'Production · Operations · Harvest',
            'farm.HandlingPlanItem': 'Production · Operations · Harvest',
            'farm.ProductionPlan': 'Production · Operations · Harvest',
            'farm.Treatment': 'Production · Operations · Health',
            'farm.HealthEvent': 'Production · Operations · Health',
            'farm.LiceCount': 'Production · Operations · Health',
            'reports.Report': 'Production · Reports',
            'messaging.Conversation': 'Production · Communication',
            'tasks.Task': 'Production · Operations',
            'tasks.TaskSeries': 'Production · Operations',
            'knowledge.Document': 'Company · Knowledge',
            'knowledge.KnowledgeEntry': 'Company · Knowledge',
            'sensors.Connection': 'Sensors · Setup',
            'sensors.PayloadFormat': 'Sensors · Setup',
            'sensors.Device': 'Sensors · Setup',
            'sensors.Channel': 'Sensors · Setup',
            'sensors.Binding': 'Sensors · Setup',
            'sensors.Credential': 'Sensors · Administration',
            'core.AuditLog': 'Company · Administration',
        })

    def test_a_tab_heading_shows_its_menu_group(self):
        self.assertEqual(str(SiteResource.group()), 'Facility')
        self.assertEqual(str(SystemResource.group()), 'Facility structure')
        self.assertEqual(str(RoleResource.group()), 'Administration')

    def test_an_entry_in_a_group_without_a_label_is_headed_by_its_section(self):
        place = navigation.place('farm.view_stockoperation')        # Operations, in its unlabelled group
        self.assertEqual((str(place.group.label), str(place.heading)), ('', 'Operations'))
        place = navigation.place('farm.view_site')
        self.assertEqual(str(place.heading), 'Facility')
        home = navigation.page('production_home')                     # an unlabelled group of an unlabelled section
        self.assertEqual(str(home.heading), 'Production')

    def test_a_permission_with_no_menu_entry_is_a_configuration_error(self):
        with self.assertRaisesMessage(ImproperlyConfigured, "'farm.view_nothing'"):
            navigation.place('farm.view_nothing')


class RailContextTests(TestCase):
    def test_anonymous_requests_get_no_menu(self):
        request = RequestFactory().get('/')
        request.user = type('Anonymous', (), {'is_authenticated': False})()
        self.assertEqual(navigation.rail(request), {})


class OverviewTests(WorkspaceTestCase):
    def test_each_panel_has_its_own_overview(self):
        self.sign_in(self.admin)
        company, production = self.page(reverse('home')), self.page(reverse('production_home'))
        self.assertEqual((company.context['workspace']['key'], production.context['workspace']['key']),
                         ('company', 'production'))
        self.assertContains(company, 'Company overview')
        self.assertContains(production, 'Production overview')

    def test_the_overviews_show_the_counts_of_what_the_person_may_see(self):
        from farm.models import ProductionDepartment, Site, System
        site = Site.objects.create(name='Bergen', code='BG')
        ProductionDepartment.objects.create(site=site, name='Hall', code='HA')
        System.objects.create(site=site, name='RAS', code='R1')
        System.objects.create(site=site, name='Pond', code='P1', status='maintenance')
        self.sign_in(self.admin)
        self.assertEqual([(t['label'], t['count']) for t in self.page(reverse('home')).context['tiles']], [('Sites', 1)])
        production = self.page(reverse('production_home'))
        self.assertEqual([(t['label'], t['count']) for t in production.context['tiles']],
                         [('Production departments', 1), ('Systems', 2), ('Equipment', 0), ('Tanks, ponds & cages', 0)])
        by_status = {item['value']: item['count'] for item in production.context['systems_by_status']}
        self.assertEqual((by_status['operational'], by_status['maintenance'], by_status['offline']), (1, 1, 0))

    def test_tiles_and_breakdown_are_left_out_for_what_the_person_may_not_see(self):
        self.user.groups.add(role('Systems only', 'view_system'))
        self.sign_in(self.user)
        self.assertEqual(self.page(reverse('home')).context['tiles'], [])
        production = self.page(reverse('production_home'))
        self.assertEqual([t['label'] for t in production.context['tiles']], ['Systems'])
        self.assertEqual(production.context['units_by_kind'], [])
        self.user.groups.clear()
        self.assertEqual(self.page(reverse('production_home')).context['systems_by_status'], [])


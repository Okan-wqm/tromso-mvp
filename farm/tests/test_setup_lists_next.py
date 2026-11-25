"""The Setup lists in the new look (?ui=next) on THE test world (core/test_world.py `world`, the clock at its MOMENT): Company's
Sites and Storage locations and Production › Setup's facility structure and reference data, each drawn by the shared list
page (island `list-page`, core/listprops.py: each tab's `list_rows`), each says everything its classic page says
(core.pagesays) in English, Norwegian and Turkish, nothing on it opens the classic dialog, and its props are kept for the
browser test (frontend/test/prodrest.pages.ts, .build/island-props by core/island_props.py: never a recording of a real
database). Systems is held by farm/tests/test_systems_next.py."""
import re
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from core.island_props import keep, props_of
from core.pagesays import unsaid
from core.test_world import MOMENT, world
from core.testing import FrozenClock

MANIFEST = str(Path(__file__).resolve().parents[2] / 'core' / 'testdata' / 'islands-prodrest-manifest.json')

# {name: route}: every Setup list this branch draws in the new look
PAGES = {
    'setup-sites': 'farm:site_list',
    'setup-storage': 'inventory:storagelocation_list',
    'setup-departments': 'farm:productiondepartment_list',
    'setup-equipment': 'farm:equipment_list',
    'setup-tanks': 'farm:tank_list',
    'setup-sampling': 'farm:samplingpoint_list',
    'setup-species': 'farm:species_list',
    'setup-feeds': 'farm:feed_list',
    'setup-limits': 'farm:waterlimit_list',
    'setup-freshness': 'farm:waterfreshness_list',
    'setup-medicines': 'farm:medicine_list',
    'setup-handling': 'farm:handlingrule_list',
    'setup-slaughter': 'farm:slaughterfacility_list',
    'setup-suppliers': 'farm:supplier_list',
    'setup-boards': 'monitoring:monitorboard_list',
    'setup-cardtemplates': 'monitoring:cardtemplate_list',
    'setup-cardrules': 'monitoring:cardtemplateassignment_list',
    'setup-phscales': 'monitoring:phwindowscale_list',
}


@override_settings(ISLANDS_MANIFEST=MANIFEST)
class SetupListsNextTests(FrozenClock, TestCase):
    NOW = MOMENT

    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser('test.admin', 'test.admin@example.com', 'x')
        made = world(cls.admin, Client())
        refused = [each for each in made if each.rsplit(': ', 1)[-1].isdigit() and not each.endswith(': 302')]
        if refused:
            raise AssertionError(f'the test world was not built: {refused}')

    def setUp(self):
        self.client.force_login(self.admin)

    def pages(self, route, query, language):
        from core.language import save_account_language
        save_account_language(self.admin, language)
        self.client.cookies['django_language'] = language
        old = self.client.get(reverse(route), {**query, 'ui': 'classic'}).content.decode()
        new = self.client.get(reverse(route), {**query, 'ui': 'next'}).content.decode()
        return old, new

    def held(self, name, route, query, language):
        old, new = self.pages(route, query, language)
        props = props_of(new, 'list-page')
        self.assertNotIn('class="data-table"', new)
        # Sites' cards: the classic card repeats its facts' labels (Type, Location, …) on every card, as layout; the new
        # cards draw them from the columns' labels, each said once at least (`once`)
        once = {column['label'] for column in props['table']['columns']} if props.get('cards') else ()
        self.assertEqual(unsaid(old, props, new_html=new, once=once), [])
        main = new[new.index('<main'):new.index('</main>')]
        self.assertIsNone(re.search(r'\sdata-modal[\s>=]', main), 'nothing opens the classic dialog')
        return props

    def test_every_list_says_everything_its_classic_page_says_in_three_languages(self):
        for language in ('en', 'nb', 'tr'):
            for name, route in PAGES.items():
                with self.subTest(page=name, language=language):
                    props = self.held(name, route, {}, language)
                    self.assertTrue(props['table']['rows'], 'the test world has rows on every list')
                    if language == 'en' or name in ('setup-sites', 'setup-limits'):
                        keep(f'{name}-{language}', {'island': 'list-page', 'props': props})

    def test_one_owners_points_and_a_search_with_no_match(self):
        """Sampling points of one unit (the links of Tanks and Equipment): its points, "Show all" and "Add a point to it";
        a search that matches nothing says so with the way back, on a list of every kind."""
        from farm.models import Tank
        tank = Tank.objects.get(code='TT-01')
        for language in ('en', 'nb', 'tr'):
            with self.subTest(language=language):
                props = self.held('setup-sampling', 'farm:samplingpoint_list', {'unit': str(tank.pk)}, language)
                [narrowed] = [each for each in props['notices'] if each['key'] == 'narrowed']
                self.assertEqual(narrowed['link']['href'], reverse('farm:samplingpoint_list'))
                self.assertEqual(narrowed['more'], [{'href': f"{reverse('farm:samplingpoint_create')}?unit={tank.pk}",
                                                     'label': narrowed['more'][0]['label']}])
                self.assertEqual({row['cells']['owner']['text'] for row in props['table']['rows']}, {'TT-01'})
                # the unit is kept by the toolbar's form: a filter or a search stays on its points
                self.assertIn({'name': 'unit', 'value': str(tank.pk)}, props['toolbar']['keep'])
        # Water freshness and pH window scales have no search fields: a search keeps every row (their classic pages' too)
        for name, route in ((name, route) for name, route in PAGES.items() if name not in ('setup-freshness', 'setup-phscales')):
            with self.subTest(page=name, search='none'):
                props = self.held(name, route, {'q': 'zz-no-such-record'}, 'en')
                self.assertEqual(props['table']['rows'], [])
                self.assertEqual(props['empty']['link']['href'], reverse(route))

    def test_sites_are_cards_and_water_limits_a_plate_per_species(self):
        _old, new = self.pages('farm:site_list', {}, 'en')
        sites = props_of(new, 'list-page')
        self.assertEqual(sites['cards'], {'chip': 'status', 'foot': ['created']})
        north = next(row for row in sites['table']['rows'] if row['cells']['site']['text'] == 'Test Site North')
        self.assertEqual(north['cells']['status']['chip'], {'kind': 'ok', 'text': 'Active'})
        self.assertEqual(north['cells']['contact']['text'], 'north@example.com')
        self.assertRegex(north['cells']['created']['text'], r'^Created \d{2}\.\d{2}\.\d{4}$')
        _old, new = self.pages('farm:waterlimit_list', {}, 'en')
        limits = props_of(new, 'list-page')
        keys = [key for group in limits['groups'] for key in group['rows']]
        self.assertEqual(sorted(keys), sorted(row['key'] for row in limits['table']['rows']))
        self.assertEqual(len(keys), len(set(keys)))
        self.assertIn('Atlantic salmon', {group['title'].split(' · ')[0] for group in limits['groups']})

    def test_a_status_is_its_classic_badges_tone_and_a_missing_fact_is_a_warning(self):
        from core import listprops as L
        self.assertEqual(L.badge('operational', 'Operational')['chip']['kind'], 'ok')
        self.assertEqual(L.badge('maintenance', 'Maintenance')['chip']['kind'], 'warning')
        self.assertEqual(L.badge('out_of_service', 'Out of service')['chip']['kind'], 'critical')
        self.assertEqual(L.badge('something new', 'New')['chip']['kind'], 'neutral')
        _old, new = self.pages('farm:equipment_list', {}, 'en')
        equipment = props_of(new, 'list-page')
        # a piece of equipment linked to no system: the classic page's warning, its link to them, and its row says so
        unlinked = [each for each in equipment['notices'] if each['key'] == 'unlinked']
        if unlinked:
            self.assertEqual(unlinked[0]['tone'], 'warning')
            self.assertEqual(unlinked[0]['link']['href'], '?system=none')
            self.assertTrue(any(row['cells']['systems'].get('chip') == {'kind': 'warning', 'text': 'No system'}
                                for row in equipment['table']['rows']))

"""Production › Production units in the new look (?ui=next, farm.stock.views.production_units): the table on the shared
list page (farm/stock/units_next.py) and the unit's drawer as the server draws it. On THE test world (core/test_world.py,
clock at MOMENT) the page says everything the classic page says in three languages (core.pagesays), with and without a
drawer open; two things it says another way, each named: the classic filter buttons' links are the toolbar's selects
(the same values, the server reads the same address), and a water value's title (its status, moment and age) is its
status chip and its origin-and-age line. A row opens its drawer, Edit opens the unit's form; the props and the page are
kept for the browser test (frontend/test/prodrest.pages.ts)."""
import html as htmllib
import re
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from core.island_props import keep, props_of
from core.pagesays import unsaid
from core.test_world import MOMENT, world
from core.testing import FrozenClock

from ..models import Tank

MANIFEST = str(Path(__file__).resolve().parents[2] / 'core' / 'testdata' / 'islands-prodrest-manifest.json')
BUTTON = re.compile(r'<a href="([^"]+)" aria-pressed="(?:true|false)">')
VALUE_TITLE = re.compile(r'class="(?:num )?wq wq-[^"]*" title="([^"]*)"')


def said_another_way(old):
    """The classic page's filter buttons' addresses and its water values' titles (see the module's docstring)."""
    return {htmllib.unescape(each) for each in BUTTON.findall(old)} | \
        {' '.join(htmllib.unescape(each).split()) for each in VALUE_TITLE.findall(old)}


@override_settings(ISLANDS_MANIFEST=MANIFEST)
class ProductionUnitsNextTests(FrozenClock, TestCase):
    NOW = MOMENT

    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser('test.admin', 'test.admin@example.com', 'x')
        world(cls.admin, Client())
        cls.unit = Tank.objects.get(code='TT-01')

    def setUp(self):
        self.client.force_login(self.admin)

    def pages(self, language='en', **query):
        from core.language import save_account_language
        save_account_language(self.admin, language)
        self.client.cookies['django_language'] = language
        url = reverse('farm:production_units')
        old = self.client.get(url, {**query, 'ui': 'classic'}).content.decode()
        # a dialog's way back (`next`) is the page asked for: ?ui=classic on the one, ?ui=next on the other
        old = old.replace('ui%3Dclassic', 'ui%3Dnext').replace('ui=classic', 'ui=next')
        new = self.client.get(url, {**query, 'ui': 'next'}).content.decode()
        return old, new

    def test_the_new_page_says_everything_the_classic_page_says_in_three_languages(self):
        for language in ('en', 'nb', 'tr'):
            for query in ({}, {'unit': str(self.unit.pk)}, {'occupancy': 'stocked', 'q': 'TT'}):
                with self.subTest(language=language, query=query):
                    old, new = self.pages(language, **query)
                    props = props_of(new, 'list-page')
                    self.assertTrue(props['table']['rows'])
                    self.assertEqual(unsaid(old, props, new_html=new, ignore=said_another_way(old)), [])
            old, new = self.pages(language)
            keep(f'production-units-{language}', {'island': 'list-page', 'props': props_of(new, 'list-page')})
        old, new = self.pages('en', unit=str(self.unit.pk))
        keep('production-units-drawer-en', {'html': new[new.index('<main'):new.index('</main>') + len('</main>')]})

    def test_a_row_opens_its_drawer_and_edit_opens_the_units_form(self):
        _old, new = self.pages('en', occupancy='stocked')
        props = props_of(new, 'list-page')
        row = next(each for each in props['table']['rows'] if each['cells']['unit']['text'] == 'TT-01')
        drawer = f"{reverse('farm:production_units')}?occupancy=stocked&unit={self.unit.pk}"
        self.assertEqual(row['cells']['unit']['href'], drawer)
        self.assertEqual([action['href'] for action in row['actions']],
                         [drawer, reverse('farm:tank_edit', args=[self.unit.pk])])
        filters = {each['name']: each for each in props['toolbar']['filters']}
        self.assertEqual(filters['occupancy']['value'], 'stocked')
        self.assertEqual([option['value'] for option in filters['occupancy']['options']], ['', 'stocked', 'empty'])

    def test_the_drawer_is_the_classic_drawer_beside_the_list(self):
        old, new = self.pages('en', unit=str(self.unit.pk))
        self.assertIn('aria-labelledby="drawer-title"', new)
        self.assertIn(reverse('farm:tank_water', args=[self.unit.pk]), new)          # History: Tank › Water
        self.assertEqual(old.count('class="drawer-section"'), new.count('class="drawer-section"'))

    def test_a_water_value_is_never_drawn_as_ok_when_it_is_not(self):
        _old, new = self.pages('en')
        for row in props_of(new, 'list-page')['table']['rows']:
            for key in ('temperature', 'oxygen'):
                cell = row['cells'].get(key)
                if cell and cell.get('chip'):
                    self.assertIn(cell['chip']['kind'], ('critical', 'warning', 'stale'))

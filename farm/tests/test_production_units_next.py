"""Production › Production units in the new look (?ui=next, farm.stock.views.production_units): the table on the shared
list page (farm/stock/units_next.py) and the unit's drawer as the server draws it. On THE test world (core/test_world.py,
clock at MOMENT) the page says everything the classic page says in three languages (core.pagesays), with and without a
drawer open; the things it says another way, each named: the classic filter buttons' links are the toolbar's selects
(the same values, the server reads the same address; the kind and fish selects' first options say what they are where
the buttons say "All"), a water value's title (its status, moment and age) is its status chip and its origin-and-age
line, and the density with its share of capacity are two lines (the design's). Never a value that was critical or a
warning when it went stale (`wq-was-…`, F-244): its title is held to the new cell's words. A row opens its drawer, Edit
opens the unit's form; the props and the page are kept for the browser test (frontend/test/prodrest.pages.ts)."""
import html as htmllib
import re
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import translation
from django.utils.translation import gettext

from core import listprops as L
from core.island_props import keep, props_of
from core.pagesays import unsaid
from core.test_world import MOMENT, stale_water_world, world
from core.testing import FrozenClock

from ..models import Tank

MANIFEST = str(Path(__file__).resolve().parents[2] / 'core' / 'testdata' / 'islands-prodrest-manifest.json')
BUTTON = re.compile(r'<a href="([^"]+)" aria-pressed="(?:true|false)">')
# a water value's title, but never one of a value that was critical or a warning before it went stale (wq-was-…)
VALUE_TITLE = re.compile(r'class="(?:num )?wq wq-(?:(?!wq-was-)[^"])*" title="([^"]*)"')
WAS_TITLE = re.compile(r'class="(?:num )?wq wq-[^"]*wq-was-[^"]*" title="([^"]*)"')
DENSITY = re.compile(r'<span class="ui-gauge-text">([^<]*)</span>')


def was_unsaid(old, props):
    """The words of each classic title of a value that was critical or a warning (`wq-was-…`: "Stale · Critical · <moment>
    · <age> ago") that the new page does not carry: each part must be in a string of the props (its case aside: the
    new cell says "Stale, was critical"), never ignored."""
    from core.pagesays import strings
    carried = [each.casefold() for each in strings(props)]
    missing = []
    for title in re.findall(r'wq-was-[a-z]+[^"]*" title="([^"]*)"', old):
        for part in ' '.join(htmllib.unescape(title).split()).split(' · '):
            if not any(part.casefold() in each for each in carried):
                missing.append(part)
    return missing


def said_another_way(old, language='en'):
    """The classic page's filter buttons' addresses and its water values' titles (one of a value that was critical or a
    warning only once `was_unsaid` found each of its words) and densities (see the module's docstring), and the kind and
    fish buttons' bare "All" in `language`: the selects' first options say "All kinds" and "Stocked and empty"."""
    with translation.override(language):
        everything = gettext('All')
    return {htmllib.unescape(each) for each in BUTTON.findall(old)} | \
        {' '.join(htmllib.unescape(each).split()) for each in VALUE_TITLE.findall(old)} | \
        {' '.join(htmllib.unescape(each).split()) for each in WAS_TITLE.findall(old)} | \
        {' '.join(htmllib.unescape(each).split()) for each in DENSITY.findall(old)} | {everything}


@override_settings(ISLANDS_MANIFEST=MANIFEST)
class ProductionUnitsNextTests(FrozenClock, TestCase):
    NOW = MOMENT

    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser('test.admin', 'test.admin@example.com', 'x')
        world(cls.admin, Client())
        stale_water_world(cls.admin)
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
                    self.assertEqual(was_unsaid(old, props), [])
                    self.assertEqual(unsaid(old, props, new_html=new, ignore=said_another_way(old, language)), [])
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
        self.assertEqual(filters['occupancy']['options'][0]['label'], 'Stocked and empty')
        if 'kind' in filters:
            self.assertEqual(filters['kind']['options'][0]['label'], 'All kinds')

    def test_the_density_cell_draws_the_share_of_capacity_as_a_gauge_with_the_share_in_words(self):
        _old, new = self.pages('en', occupancy='stocked')
        row = next(each for each in props_of(new, 'list-page')['table']['rows']
                   if each['cells']['unit']['text'] == 'TT-01')
        density = row['cells']['density']
        self.assertTrue(density['text'].endswith('kg/m³'))
        self.assertRegex(density['gauge']['text'], r'^\d+ % of capacity$')
        self.assertTrue(0 <= density['gauge']['value'] <= 100)
        self.assertIsNone(density['gauge']['status'])

    def test_the_drawer_is_the_classic_drawer_beside_the_list(self):
        old, new = self.pages('en', unit=str(self.unit.pk))
        self.assertIn('aria-labelledby="drawer-title"', new)
        self.assertIn(reverse('farm:tank_water', args=[self.unit.pk]), new)          # History: Tank › Water
        self.assertEqual(old.count('class="drawer-section"'), new.count('class="drawer-section"'))

    def test_a_stale_value_that_was_critical_says_so_in_words(self):
        """F-244: TM-01's oxygen (5.2 mg/L, under the critical 6, taken 80 hours back) is stale now; its cell keeps the
        stale chip and says it was critical and when it was taken; its age is the origin line's (the classic title's
        every word held by was_unsaid)."""
        old, new = self.pages('en')
        self.assertIn('wq-stale wq-was-critical', old)
        row = next(each for each in props_of(new, 'list-page')['table']['rows']
                   if each['cells']['unit']['text'] == 'TM-01')
        oxygen = row['cells']['oxygen']
        self.assertEqual(oxygen['chip'], {'kind': 'stale', 'text': '5.20'})
        self.assertRegex(oxygen['sub'][0], r'^Stale, was critical · \d{2}\.\d{2}\.\d{4} \d{2}:\d{2}$')
        self.assertRegex(oxygen['sub'][-1], r' · 3\sdays ago$')                    # the age: the origin line's
        self.assertEqual(was_unsaid(old, props_of(new, 'list-page')), [])
        # the check sees a word the new page leaves out
        self.assertEqual(was_unsaid(old.replace('wq-was-critical" title="Stale', 'wq-was-critical" title="Stale · Nowhere'),
                                    props_of(new, 'list-page')), ['Nowhere'])

    def test_a_water_value_is_never_drawn_as_ok_when_it_is_not(self):
        _old, new = self.pages('en')
        for row in props_of(new, 'list-page')['table']['rows']:
            for key in ('temperature', 'oxygen'):
                cell = row['cells'].get(key)
                if cell and cell.get('chip'):
                    self.assertIn(cell['chip']['kind'], ('critical', 'warning', 'stale'))


class GaugeCellTests(SimpleTestCase):
    """core/listprops.py `gauge`: the bar's share clamped to 0-100 (the words say it whole), a status only critical or
    warning; a cell without a gauge has no `gauge` key (the island's props as before)."""

    def test_the_share_is_clamped_and_said_in_words(self):
        self.assertEqual(L.gauge(124.36, '124 % of capacity', 'critical'),
                         {'value': 100.0, 'text': '124 % of capacity', 'status': 'critical'})
        self.assertEqual(L.gauge(None, '— of capacity')['value'], 0.0)
        self.assertEqual(L.gauge(-2, '0 %')['value'], 0.0)
        with self.assertRaises(ValueError):
            L.gauge(5, '5 %', 'ok')
        self.assertNotIn('gauge', L.cell('7.4 kg/m³'))
        self.assertEqual(L.cell('7.4 kg/m³', gauge=L.gauge(12, '12 %'))['gauge']['value'], 12.0)
        self.assertIs(L._pager, L.pager)

"""Operations › Water chemistry's Latest and History in the new look (?ui=next, farm.water.views.water_page, props of
farm/water/page_next.py) on THE test world (core/test_world.py `world`, `stale_water_world` and `water_page_world`, the
clock at its MOMENT). Each tab says everything its classic page says (core.pagesays) in three languages, with and without
filters; what it says another way is named: a value's title (its status, the moment of its sample, its age, how it was
worked out, its provenance and note) is its chip and its lines, and every word of it but the status a chip draws and the
moment (the age, on Latest, and the row's moment, on History, say when) is held in the props (`title_unsaid`), never
ignored. Never a stale or unjudged value drawn as an OK one; the states and the safety line are the server's. The props
are kept for the browser test (frontend/test/prodrest.pages.ts)."""
import html as htmllib
import re
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import translation

from core.island_props import keep, props_of
from core.pagesays import strings, unsaid
from core.test_world import MOMENT, stale_water_world, water_page_world, world
from core.testing import FrozenClock

from ..models import Tank
from ..water.evaluate import Status

MANIFEST = str(Path(__file__).resolve().parents[2] / 'core' / 'testdata' / 'islands-prodrest-manifest.json')
TITLE = re.compile(r'class="(?:num )?wq wq-[^"]*" title="([^"]*)"')
MOMENT_SAID = re.compile(r'\d{2}\.\d{2}\.\d{4}')


def titles(old):
    return [' '.join(htmllib.unescape(each).split()) for each in TITLE.findall(old)]


def title_unsaid(old, props, language):
    """The words of each classic value title (farm/_water_value.html: "Warning · 23.11.2026 11:42 · 1 hour ago · worked
    out from the sample · …") the new page does not carry: each part but a status's name (the chip draws it, or its lines
    say it), the sample's moment and its age in words ("0 minutes ago": the origin line says it as every page with a
    latest value does, "12 s ago"; the row of a sample says its moment) must be in a string of the props, its case aside."""
    with translation.override(language):
        labels = {str(status.label) for status in Status}
        before, _sep, after = translation.gettext('%(age)s ago').partition('%(age)s')
    carried = [each.casefold() for each in strings(props)]
    missing = []
    for title in titles(old):
        for part in title.split(' · '):
            aged = part.startswith(before) and part.endswith(after) and any(char.isdigit() for char in part)
            if part in labels or MOMENT_SAID.search(part) or aged:
                continue
            if not any(part.casefold() in each for each in carried):
                missing.append(part)
    return missing


@override_settings(ISLANDS_MANIFEST=MANIFEST)
class WaterPageNextTests(FrozenClock, TestCase):
    NOW = MOMENT

    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser('test.admin', 'test.admin@example.com', 'x')
        made = world(cls.admin, Client())
        refused = [each for each in made if each.rsplit(': ', 1)[-1].isdigit() and not each.endswith(': 302')]
        if refused:
            raise AssertionError(f'the test world was not built: {refused}')
        stale_water_world(cls.admin)
        cls.voided = water_page_world(cls.admin)
        cls.tank = Tank.objects.get(code='TT-01')

    def setUp(self):
        self.client.force_login(self.admin)

    def pages(self, language='en', **query):
        from core.language import save_account_language
        save_account_language(self.admin, language)
        self.client.cookies['django_language'] = language
        url = reverse('farm:water')
        old = self.client.get(url, {**query, 'ui': 'classic'}).content.decode()
        # a dialog's way back (`next`) is the page asked for: ?ui=classic on the one, ?ui=next on the other
        old = old.replace('ui%3Dclassic', 'ui%3Dnext').replace('ui=classic', 'ui=next')
        new = self.client.get(url, {**query, 'ui': 'next'}).content.decode()
        return old, new

    def held(self, language, query):
        old, new = self.pages(language, **query)
        props = props_of(new, 'list-page')
        self.assertEqual(title_unsaid(old, props, language), [])
        self.assertEqual(unsaid(old, props, new_html=new, ignore=set(titles(old))), [])
        main = new[new.index('<main'):new.index('</main>')]
        self.assertIsNone(re.search(r'\sdata-modal[\s>=]', main), 'nothing opens the classic dialog')
        return old, new, props

    def test_both_tabs_say_everything_their_classic_page_says_in_three_languages(self):
        queries = {'latest': {}, 'history': {'view': 'history'}, 'history-unit': {'unit': str(self.tank.pk)},
                   'history-alerts': {'view': 'history', 'alerts': '1'},
                   'latest-site': {'site': str(self.tank.production_department.site_id)}}
        for language in ('en', 'nb', 'tr'):
            for name, query in queries.items():
                with self.subTest(page=name, language=language):
                    _old, _new, props = self.held(language, query)
                    self.assertTrue(props['table']['rows'], 'the test world has rows on every tab')
                    if name in ('latest', 'history') and (language == 'en' or name == 'latest'):
                        keep(f'production-water-{name}-{language}', {'island': 'list-page', 'props': props})

    def test_the_safety_line_and_the_states_are_the_servers(self):
        old, new, props = self.held('en', {})
        # the alarms' safety line, as the classic page draws it ({% alarm_watch promise=True %}), above the table
        self.assertIn('A warning or a critical value raises an alarm (Company › Alarms).', new)
        self.assertLess(new.index('ui-safety'), new.index('data-island="list-page"'))
        rows = {row['cells']['point']['text']: row for row in props['table']['rows']}
        tm = rows['TM-01']
        # TM-01's oxygen: its latest is the company world's critical 5 mg/L an hour back (the voided sample is not it)
        self.assertEqual(tm['cells']['status']['chip']['kind'], 'critical')
        self.assertEqual(tm['status'], 'critical')
        oxygen = tm['cells']['oxygen_mg_l']
        self.assertEqual(oxygen['chip']['kind'], 'critical')
        self.assertRegex(oxygen['sub'][-1], r'^.+ · .+ ago$')                          # its origin and age

    def test_the_history_strikes_a_voided_sample_and_offers_void_only_on_the_others(self):
        _old, _new, props = self.held('en', {'view': 'history'})
        rows = {row['key']: row for row in props['table']['rows']}
        voided = rows[str(self.voided.pk)]
        self.assertTrue(voided['voided'])
        self.assertIsNone(voided['status'])
        self.assertEqual(voided['actions'], [])
        self.assertEqual(voided['cells']['measured']['sub'], ['voided by test.admin: Test sample of another unit'])
        self.assertEqual(voided['cells']['source']['sub'], ['Test entered on the wrong unit'])
        others = [row for row in props['table']['rows'] if not row['voided']]
        self.assertTrue(any(action['label'] == 'Void' and action['labelled'] for row in others for action in row['actions']))
        filters = {each['name']: each for each in props['toolbar']['filters']}
        self.assertEqual(set(filters), {'site', 'owner', 'from', 'to', 'alerts'})
        self.assertEqual(filters['alerts']['kind'], 'check')
        self.assertFalse(filters['alerts']['checked'])
        self.assertIn({'name': 'view', 'value': 'history'}, props['toolbar']['keep'])
        # one unit's history: its points to choose from, the unit chosen in its group
        _old, new, props = self.held('en', {'unit': str(self.tank.pk)})
        filters = {each['name']: each for each in props['toolbar']['filters']}
        self.assertEqual(filters['owner']['value'], f'unit:{self.tank.pk}')
        self.assertIn('point', filters)
        self.assertIn('History of TT-01', new)


class ValueCellTests(SimpleTestCase):
    """A value the water page cannot judge or could not work out is never drawn as an OK one, nor left without why."""

    def reading(self, **given):
        from types import SimpleNamespace
        said = {'value': None, 'status': 'ok', 'measured': '', 'last_own': None, 'old_alert': None, 'derived': False,
                'sample': SimpleNamespace(live=False), 'provenance': '', 'note': ''}
        return SimpleNamespace(**{**said, **given})

    def test_a_value_that_cannot_be_evaluated_is_a_warning_with_its_words_and_its_reason(self):
        from ..stock.units_next import value_cell
        with translation.override('en'):
            cell = value_cell(self.reading(status='unevaluated', derived=True, note='Test: past the core’s range'),
                              latest=False, whole=True)
        self.assertEqual(cell['chip'], {'kind': 'warning', 'text': '?'})
        self.assertEqual(cell['sub'], ['Cannot be evaluated', 'worked out from the sample', 'Test: past the core’s range'])

    def test_a_stale_value_keeps_its_stale_chip_and_a_sample_with_no_value_is_a_dash(self):
        from ..stock.units_next import value_cell
        cell = value_cell(self.reading(status='stale', note='Test note'), latest=False, whole=True)
        self.assertEqual(cell['chip']['kind'], 'stale')
        self.assertEqual(value_cell(None, latest=False)['text'], '—')

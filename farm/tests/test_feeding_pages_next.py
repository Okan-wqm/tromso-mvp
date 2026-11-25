"""Operations › Feeding in the new look (?ui=next): the Meal board and Records (Feeding records, By unit and day) on the
shared list page (farm/feeding/pages.py). On THE test world (core/test_world.py, world() and feeding_ops_world(), clock at
MOMENT) each page says everything its classic page says in three languages (core.pagesays), with the things it says
another way named (SAID_ANOTHER_WAY): the abbreviation "SFR" is said with its figure ("SFR 1.27 %") and its meaning once
above the table, the classic header titles (an interpolated SFR's columns, the estimate's meaning) are sub-lines and a
line, the unit count of the page head is a line. Never a ration where the protocol gives none: TM-01 (no protocol) says
why on its line; a meal and a voided feeding are drawn as such. The props are kept for the browser test
(frontend/test/prodrest.pages.ts)."""
import re
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import translation
from django.utils.translation import gettext

from core.island_props import keep, props_of
from core.pagesays import unsaid
from core.test_world import MOMENT, feeding_ops_world, world
from core.testing import FrozenClock

MANIFEST = str(Path(__file__).resolve().parents[2] / 'core' / 'testdata' / 'islands-prodrest-manifest.json')
SFR_TITLE = re.compile(r'<span class="ui-sub" title="([^"]*)"><abbr')


def said_another_way(old, language):
    """The words the new page says another way, in `language` (see the module's docstring)."""
    import html
    with translation.override(language):
        words = {gettext('SFR')}
    return words | {' '.join(html.unescape(each).split()) for each in SFR_TITLE.findall(old)}


@override_settings(ISLANDS_MANIFEST=MANIFEST)
class FeedingPagesNextTests(FrozenClock, TestCase):
    NOW = MOMENT

    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser('test.admin', 'test.admin@example.com', 'x')
        world(cls.admin, Client())
        feeding_ops_world(cls.admin)

    def setUp(self):
        self.client.force_login(self.admin)

    def pages(self, name, language='en', **query):
        from core.language import save_account_language
        save_account_language(self.admin, language)
        self.client.cookies['django_language'] = language
        url = reverse(name)
        old = self.client.get(url, {**query, 'ui': 'classic'}).content.decode()
        # a dialog's way back (`next`) is the page asked for: ?ui=classic on the one, ?ui=next on the other
        old = old.replace('ui%3Dclassic', 'ui%3Dnext').replace('ui=classic', 'ui=next')
        new = self.client.get(url, {**query, 'ui': 'next'}).content.decode()
        return old, new

    PAGES = (('meal-board', 'farm:meal_board', {}), ('records', 'farm:feeding_records', {'voided': '1'}),
             ('records-days', 'farm:feeding_records', {'view': 'days'}))

    def test_each_page_says_everything_the_classic_page_says_in_three_languages(self):
        for key, name, query in self.PAGES:
            for language in ('en', 'nb', 'tr'):
                with self.subTest(page=key, language=language):
                    old, new = self.pages(name, language, **query)
                    props = props_of(new, 'list-page')
                    self.assertTrue(props['table']['rows'])
                    self.assertEqual(unsaid(old, props, new_html=new, ignore=said_another_way(old, language)), [])
                    if language == 'en' or key == 'meal-board':
                        keep(f'feeding-{key}-{language}', {'island': 'list-page', 'props': props})

    def test_the_meal_board_gives_a_ration_only_where_the_protocol_gives_one(self):
        _old, new = self.pages('farm:meal_board')
        rows = {row['cells']['unit']['text']: row for row in props_of(new, 'list-page')['table']['rows']
                if row['cells']['unit']['text']}
        tank, cage = rows['TT-01']['cells'], rows['TM-01']['cells']
        self.assertTrue(tank['ration']['text'].endswith('kg'))
        self.assertEqual(tank['today']['pips']['states'][0], 'done')
        self.assertRegex(tank['today']['pips']['label'], r'^1 of 4 meals done$')
        self.assertEqual(tank['protocol']['text'], 'Test hall table')
        self.assertEqual(cage['ration']['text'], 'no data')
        self.assertNotIn('pips', cage['today'])
        self.assertTrue(cage['next']['text'])                       # why there is no ration, where the meal would be
        self.assertEqual([action['label'] for action in rows['TT-01']['actions']], ['Record meal', 'Record water sample'])
        self.assertNotIn('data-modal', new.split('<main', 1)[1].split('</main>', 1)[0])

    def test_a_voided_feeding_is_struck_through_with_who_voided_it_and_why(self):
        _old, new = self.pages('farm:feeding_records', voided='1')
        props = props_of(new, 'list-page')
        voided = [row for row in props['table']['rows'] if row['voided']]
        self.assertEqual(len(voided), 1)
        self.assertEqual(voided[0]['cells']['notes']['sub'], ['voided by test.admin: Entered twice'])
        self.assertEqual(voided[0]['actions'], [])
        live = next(row for row in props['table']['rows'] if not row['voided'])
        self.assertEqual(live['actions'][0]['label'], 'Void')
        self.assertTrue(live['actions'][0]['href'].startswith(reverse('farm:feeding_void', args=[live['key']])))
        _old, hidden = self.pages('farm:feeding_records')
        self.assertFalse(any(row['voided'] for row in props_of(hidden, 'list-page')['table']['rows']))
        filters = {each['name']: each for each in props['toolbar']['filters']}
        self.assertEqual(filters['voided'], {'kind': 'check', 'name': 'voided', 'label': 'Show voided', 'value': '1',
                                             'options': [], 'groups': []})
        self.assertEqual(props['toolbar']['add']['label'], 'Record feeding')

    def test_records_by_unit_and_day_keep_the_view_in_the_filter_form(self):
        _old, new = self.pages('farm:feeding_records', view='days')
        props = props_of(new, 'list-page')
        self.assertIn({'name': 'view', 'value': 'days'}, props['toolbar']['keep'])
        self.assertEqual([tab['current'] for tab in props['tabs']['tabs']], [False, True])

"""Operations › Harvest in the new look (?ui=next): Harvested on the shared list page (farm/harvest/pages.py), with the
design's Per batch and Per site views, and the Harvest plan and Production plans tabs' lists (farm/harvest/lists.py),
each under the server's strip of the group's pages. On THE test world (core/test_world.py: world(), health_ops_world()
and harvest_ops_world(), clock at MOMENT) each page says everything its classic page says in three languages
(core.pagesays); Harvested's totals per batch and per site, under the classic table, are its two other views, so the
classic page is held to the three views together. The column titles of the classic header (Round weight, Book) are lines
above the table. A medicine withdrawal on a plan's day is said in the server's words and marks its row critical. The
props are kept for the browser test (frontend/test/prodrest.pages.ts)."""
import html
import re
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from core.island_props import keep, props_of
from core.pagesays import unsaid
from core.test_world import MOMENT, harvest_ops_world, health_ops_world, world
from core.testing import FrozenClock

MANIFEST = str(Path(__file__).resolve().parents[2] / 'core' / 'testdata' / 'islands-prodrest-manifest.json')
ABBR = re.compile(r'<abbr title="([^"]*)">')


@override_settings(ISLANDS_MANIFEST=MANIFEST)
class HarvestPagesNextTests(FrozenClock, TestCase):
    NOW = MOMENT

    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser('test.admin', 'test.admin@example.com', 'x')
        world(cls.admin, Client())
        health_ops_world(cls.admin)
        harvest_ops_world(cls.admin)

    def setUp(self):
        self.client.force_login(self.admin)

    def pages(self, name, language='en', **query):
        from core.language import save_account_language
        save_account_language(self.admin, language)
        self.client.cookies['django_language'] = language
        url = reverse(name)
        old = self.client.get(url, {**query, 'ui': 'classic'}).content.decode()
        old = old.replace('ui%3Dclassic', 'ui%3Dnext').replace('ui=classic', 'ui=next')
        new = self.client.get(url, {**query, 'ui': 'next'}).content.decode()
        return old, new

    def test_harvested_says_everything_the_classic_page_says_in_its_three_views(self):
        for language in ('en', 'nb', 'tr'):
            with self.subTest(language=language):
                old, new = self.pages('farm:harvests', language)
                views = [props_of(new, 'list-page')] + [props_of(self.pages('farm:harvests', language, view=view)[1],
                                                                 'list-page') for view in ('batch', 'site')]
                self.assertTrue(views[0]['table']['rows'])
                # the abbreviations' titles are lines above the table ("Round weight: The live weight …")
                self.assertEqual(unsaid(old, views, new_html=new), [])
                keep(f'harvest-harvested-{language}', {'island': 'list-page', 'props': views[0]})
                if language == 'en':
                    keep('harvest-harvested-batch-en', {'island': 'list-page', 'props': views[1]})
                titles = {html.unescape(each) for each in ABBR.findall(old)}
                self.assertEqual(len(titles), 2)
                self.assertTrue(all(any(title in line for line in views[0]['lines']) for title in titles))

    def test_the_plan_tabs_say_everything_their_classic_lists_say_in_three_languages(self):
        for key, name in (('plan', 'farm:handlingplanitem_list'), ('targets', 'farm:productionplan_list')):
            for language in ('en', 'nb', 'tr'):
                with self.subTest(page=key, language=language):
                    old, new = self.pages(name, language)
                    props = props_of(new, 'list-page')
                    self.assertTrue(props['table']['rows'])
                    self.assertEqual(unsaid(old, props, new_html=new), [])
                    self.assertIn('aria-label="Harvest"' if language == 'en' else 'class="ui-tabs"', new)
                    if language == 'en':
                        keep(f'harvest-{key}-en', {'island': 'list-page', 'props': props})

    def test_a_withdrawal_on_a_plans_day_is_said_and_marks_the_row_critical(self):
        _old, new = self.pages('farm:handlingplanitem_list')
        rows = props_of(new, 'list-page')['table']['rows']
        harvest = next(row for row in rows if row['cells']['unit']['text'] == 'TM-01')
        self.assertEqual(harvest['status'], 'critical')
        self.assertIn({'kind': 'hold', 'text': 'Withdrawal'}, harvest['cells']['before']['chips'])
        said = [harvest['cells']['before']['text'], *harvest['cells']['before']['sub']]
        self.assertTrue(any(': medicine withdrawal, harvest from ' in line for line in said), said)
        transport = next(row for row in rows if row['cells']['unit']['text'] == 'TT-01')
        self.assertEqual(transport['cells']['status']['chip'], {'kind': 'warning', 'text': 'Overdue'})
        _old, new = self.pages('farm:productionplan_list')
        rows = props_of(new, 'list-page')['table']['rows']
        cage = next(row for row in rows if row['cells']['unit']['text'] == 'TM-01')
        self.assertEqual(cage['status'], 'critical')
        self.assertRegex(cage['cells']['withdrawal']['text'], r'^\S+: harvest from ')
        tank = next(row for row in rows if row['cells']['unit']['text'] == 'TT-01')
        self.assertEqual(tank['cells']['target']['text'], '250 g')

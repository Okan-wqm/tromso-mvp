"""Operations › Health in the new look (?ui=next): Treatments and Sea-lice counts on the shared list page
(farm/health/pages.py) and the Health events tab's list (farm/health/lists.py). On THE test world (core/test_world.py:
world() and health_ops_world(), clock at MOMENT) each page says everything its classic page says in three languages
(core.pagesays). The safety words are the server's: a treatment's withdrawal (until when, and why), a batch held today,
a weekly lice average over the limit, "Notify at once" for a listed disease not notified (and Notify Mattilsynet above
the list). The props are kept for the browser test (frontend/test/prodrest.pages.ts)."""
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from django.utils import translation
from django.utils.translation import gettext

from core.island_props import keep, props_of
from core.pagesays import unsaid
from core.test_world import MOMENT, health_ops_world, world
from core.testing import FrozenClock

def twice(language):
    """The classic row's Edit says its word twice, as the link's title and its hidden text (a layout repeat: the new
    action says it once, as its name)."""
    with translation.override(language):
        return {gettext('Edit')}


MANIFEST = str(Path(__file__).resolve().parents[2] / 'core' / 'testdata' / 'islands-prodrest-manifest.json')


@override_settings(ISLANDS_MANIFEST=MANIFEST)
class HealthPagesNextTests(FrozenClock, TestCase):
    NOW = MOMENT

    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser('test.admin', 'test.admin@example.com', 'x')
        world(cls.admin, Client())
        health_ops_world(cls.admin)

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

    PAGES = (('treatments', 'farm:treatments', {}), ('events', 'farm:healthevent_list', {}),
             ('lice', 'farm:lice_counts', {}))

    def test_each_page_says_everything_the_classic_page_says_in_three_languages(self):
        for key, name, query in self.PAGES:
            for language in ('en', 'nb', 'tr'):
                with self.subTest(page=key, language=language):
                    old, new = self.pages(name, language, **query)
                    props = props_of(new, 'list-page')
                    self.assertTrue(props['table']['rows'])
                    self.assertEqual(unsaid(old, props, new_html=new, once=twice(language)), [])
                    keep(f'health-{key}-{language}', {'island': 'list-page', 'props': props})

    def test_a_treatments_withdrawal_is_the_servers_and_a_batch_held_today_is_in_the_hold_chip(self):
        _old, new = self.pages('farm:treatments')
        rows = props_of(new, 'list-page')['table']['rows']
        bath = next(row for row in rows if row['cells']['treatment']['text'] == 'Test Medicine')
        batches = bath['cells']['batches']
        # the cage has no temperature, so the medicine's degree-days give no end: "end unknown", the server's words
        self.assertRegex(batches['text'], r' \(TM-01\) · (until \d{2}\.\d{2}\.\d{4} \(harvest from \d{2}\.\d{2}\.\d{4}\)|end unknown)$')
        self.assertEqual([chip['kind'] for chip in batches['chips']], ['hold'])
        self.assertEqual(bath['status'], 'warning')
        thermal = next(row for row in rows if row['cells']['treatment']['text'] != 'Test Medicine')
        self.assertEqual(thermal['cells']['batches']['chips'], [])

    def test_a_listed_disease_not_notified_says_notify_at_once(self):
        _old, new = self.pages('farm:healthevent_list')
        props = props_of(new, 'list-page')
        self.assertEqual(props['notices'][0]['tone'], 'critical')
        self.assertTrue(props['notices'][0]['text'].startswith('Notify Mattilsynet: '))
        event = next(row for row in props['table']['rows'] if row['cells']['event']['text'] == 'Vet or fish-health visit')
        self.assertEqual(event['cells']['told']['chip'], {'kind': 'critical', 'text': 'Notify at once'})
        self.assertEqual(event['status'], 'critical')

    def test_a_weekly_lice_average_over_the_limit_is_critical(self):
        _old, new = self.pages('farm:lice_counts')
        props = props_of(new, 'list-page')
        week = props['sections'][0]['rows'][0]
        self.assertEqual(week['status'], 'critical')
        self.assertIn({'kind': 'critical', 'text': 'Over the limit'}, week['cells']['adult']['chips'])
        self.assertEqual(week['cells']['adult']['text'], '0.60')

"""Production › Overview in the new look (?ui=next, config.views.production_home): the island `production`
(frontend/islands/pages/Production.tsx) in the design's layout, its props made by config/production_props.py from the
very context the classic page (templates/_production_overview.html) is drawn from, plus what the design adds from real
sources: the fish's batch count on its card, the units under a medicine withdrawal today in Needs attention, and the
production team today as the HR board's bar (config.views.team_today). The head (status chips, Record water sample) is
the classic page's. On THE test world (core/test_world.py, clock at MOMENT; TM-01's oxygen stale and critical when taken,
core.test_world.stale_water_world) it says everything the classic page says in three languages (core.pagesays); one thing
another way, named: a water value's title is its chip and its origin-and-age line, as on Production units (never for a
value that was critical or a warning: each of its words is held, farm.tests.test_production_units_next.was_unsaid). The
props are kept for the browser test (frontend/test/prodrest.pages.ts)."""
import html as htmllib
import re
from datetime import timedelta
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from core.island_props import keep, props_of
from core.pagesays import unsaid
from core.test_world import MOMENT, stale_water_world, world
from core.testing import FrozenClock

from .test_production_units_next import VALUE_TITLE, WAS_TITLE, was_unsaid

MANIFEST = str(Path(__file__).resolve().parents[2] / 'core' / 'testdata' / 'islands-prodrest-manifest.json')


def as_next(old):
    """The classic page as the new one would say its own address: a dialog's way back (`next`) is the page asked for,
    ?ui=classic on the one and ?ui=next on the other."""
    return old.replace('ui%3Dclassic', 'ui%3Dnext').replace('ui=classic', 'ui=next')


def figures(old):
    """The metric cards' figures, which the classic card says twice (its text and its title): said once at least (the
    island's tile draws its title from the same figure)."""
    return {htmllib.unescape(each) for each in re.findall(r'data-figure title="([^"]*)"', old)}


def said_another_way(old):
    """The classic water values' titles (one of a value that was critical or a warning only as was_unsaid holds it)."""
    squash = lambda each: ' '.join(htmllib.unescape(each).split())          # noqa: E731
    return {squash(each) for each in VALUE_TITLE.findall(old)} | {squash(each) for each in WAS_TITLE.findall(old)}


@override_settings(ISLANDS_MANIFEST=MANIFEST)
class ProductionOverviewNextTests(FrozenClock, TestCase):
    NOW = MOMENT

    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser('test.admin', 'test.admin@example.com', 'x')
        world(cls.admin, Client())
        stale_water_world(cls.admin)

    def setUp(self):
        self.client.force_login(self.admin)

    def page(self, look, language='en'):
        from core.language import save_account_language
        save_account_language(self.admin, language)
        self.client.cookies['django_language'] = language
        response = self.client.get(reverse('production_home'), {'ui': look})
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_the_new_page_says_everything_the_classic_page_says_in_three_languages(self):
        for language in ('en', 'nb', 'tr'):
            with self.subTest(language=language):
                old, new = as_next(self.page('classic', language)), self.page('next', language)
                props = props_of(new, 'production')
                self.assertNotIn('data-metric=', new, 'the body is the island, not the classic cards')
                self.assertEqual(was_unsaid(old, props), [])
                self.assertEqual(unsaid(old, props, new_html=new, ignore=said_another_way(old), once=figures(old)), [])
                keep(f'production-overview-{language}', {'island': 'production', 'props': props})

    def test_the_design_s_layout_and_parts_from_their_real_sources(self):
        props = props_of(self.page('next'), 'production')
        self.assertEqual(props['today']['title'], 'Today on the farm')
        self.assertTrue(props['today']['meta'].startswith('Worked out '))
        tiles = {tile['key']: tile for tile in props['today']['tiles']}
        self.assertRegex(tiles['stock-fish']['sub'], r'^in \d+ batch')                          # the batch count
        self.assertEqual(tiles['water-critical']['status'], None if tiles['water-critical']['figure'] == '0' else 'critical')
        self.assertEqual(props['team']['title'], 'Production team today')
        self.assertEqual(props['team']['link']['label'], 'Today & attendance')
        self.assertTrue(props['team']['stack']['parts'])                                        # the team's bar
        self.assertEqual(props['farm']['title'], 'The farm')
        # Needs attention: a critical water point first, with its values, never a value's chip OK
        rows = props['attention']['rows']
        self.assertEqual((rows[0]['kind'], rows[0]['status']), ('water', 'critical'))
        for row in rows:
            for value in row['values']:
                self.assertIn(value['kind'], ('critical', 'warning', 'stale'))
        old = self.page('classic')
        self.assertNotIn('Production team today', old)
        self.assertNotIn('data-attention="withdrawal"', old)

    def test_a_stale_value_that_was_critical_is_never_only_stale(self):
        rows = props_of(self.page('next'), 'production')['attention']['rows']
        [row] = [row for row in rows if row['title'] == 'TM-01']
        self.assertEqual(row['chip'], {'kind': 'critical', 'text': 'Critical, no recent data'})
        [oxygen] = row['values']
        # in the chip of what its limits said, and said stale in words, with when it was taken
        self.assertEqual((oxygen['kind'], oxygen['figure']), ('critical', '5.20'))
        self.assertRegex(oxygen['sub'][0], r'^Stale, was critical · \d{2}\.\d{2}\.\d{4} \d{2}:\d{2}$')

    def test_a_unit_under_withdrawal_is_in_needs_attention_with_its_drawer(self):
        from farm import withdrawal_gate as gate
        from farm.health import services
        from farm.models import Medicine, MedicineWithdrawal, Tank
        from farm.stock.dates import local_today
        unit = Tank.objects.get(code='TT-01')
        medicine = Medicine.objects.create(name='Test medicine vet.', kind='lice', administration='bath',
                                           active_substance='azamethiphos', lice_report_code='AZAMETHIPHOS')
        with gate.opened('test fixture: a withdrawal row straight in the database'):
            MedicineWithdrawal.objects.create(medicine=medicine, species=None, days=30, safety_margin_pct=0)
        day = local_today(unit) - timedelta(days=2)
        seen = services.handling([unit], day, 'bath', medicine, 'sea_lice').fingerprint
        services.record_treatment(self.admin, units=[unit], method='bath', reason='sea_lice', start_date=day,
                                  end_date=day, medicine=medicine, handling_ack=seen or None)
        new = self.page('next')
        props = props_of(new, 'production')
        [hold] = [row for row in props['attention']['rows'] if row['kind'] == 'withdrawal']
        self.assertEqual((hold['chip']['kind'], hold['title']), ('hold', 'TT-01'))
        self.assertEqual(hold['link']['href'], f'{reverse("farm:production_units")}?unit={unit.pk}')
        old = as_next(self.page('classic'))
        self.assertEqual(unsaid(old, props, new_html=new, ignore=said_another_way(old), once=figures(old)), [])

    def test_a_person_who_may_read_nothing_of_it_is_told_so(self):
        nobody = get_user_model().objects.create_user('test.nobody', 'test.nobody@example.com', 'x')
        self.client.force_login(nobody)
        props = props_of(self.client.get(reverse('production_home'), {'ui': 'next'}).content.decode(), 'production')
        self.assertEqual(props['empty']['title'], 'Your role opens none of the production figures yet.')

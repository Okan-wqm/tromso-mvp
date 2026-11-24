"""The props of the Production and Sensors islands, made in the test run's own database from THE test world
(core/test_world.py: the one builder; every name and address a fixture's) with
the clock at its MOMENT, through the real views in the new look, kept under .build/island-props/ by core/island_props.py
for the browser test (frontend/test/production.pages.ts, `npm run test:pages`). Nothing recorded from a real database is
kept: the repository is public. The pages say the world's facts: a chart per parameter measured or sampled at TT-01,
the gap of the probe's outage, the meter and lab samples, the fish's limits, the window's harvest, treatment, feeding and
alarm, the Deffeyes chart of the window, the window's ends in the date box's shape, the compared chart on the same
window, the pH's "no recent data" and the temperature's fresh newest value (the ingest's channel state).

    water-en, water-nb          Tank › Water of TT-01, 7 days (farm:tank_water)
    sensor-charts-en            Sensors › Charts, TT-01's pH over 7 days compared with its temperature (sensors:charts)"""
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from core.island_props import keep, render_island
from core.testing import FrozenClock
from core.test_world import MOMENT, world
from core.tests_islands import FIXTURE
from farm.models import Tank


@override_settings(ISLANDS_MANIFEST=FIXTURE)
class IslandPagesTests(FrozenClock, TestCase):
    NOW = MOMENT

    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser('test.admin', 'test.admin@example.com', 'x')
        made = world(cls.admin, Client())
        refused = [each for each in made if not each.endswith(': 302') and not each.startswith('hr:')]   # hr_world says its counts
        if refused:
            raise AssertionError(f'the test world was not built: {refused}')
        cls.unit = Tank.objects.get(code='TT-01')

    def setUp(self):
        self.client.force_login(self.admin)

    def test_tank_water_says_the_worlds_facts_and_its_props_are_kept(self):
        url = reverse('farm:tank_water', args=[self.unit.pk])
        for language in ('en', 'nb'):
            props = render_island(self.client, url, 'water', {'range': '7d'}, language)
            charts = {chart['quantity']['code']: chart for chart in props['places'][0]['charts']}
            self.assertLessEqual({'temperature_c', 'oxygen_mg_l', 'ph', 'tan_mg_l', 'alkalinity_mg_l'}, set(charts))
            self.assertTrue(charts['oxygen_mg_l']['gaps'])                              # the outage, shown
            self.assertEqual(charts['oxygen_mg_l']['bands'], {'critical_low': 6.0, 'warning_low': 7.0})
            self.assertEqual(charts['ph']['bands'], {'critical_low': 6.5, 'warning_low': 6.8, 'warning_high': 7.8,
                                                     'critical_high': 8.2})
            self.assertEqual(sorted(sample['source'] for sample in charts['tan_mg_l']['samples']), ['lab', 'manual'])
            self.assertEqual(len(props['places'][0]['worked']['nh3_n_mg_l']['values']), 2)
            self.assertEqual(sorted(event['kind'] for event in props['events']),
                             ['alarm', 'feeding', 'harvest', 'treatment'])
            self.assertTrue(all(event['url'] for event in props['events']))
            # a harvest and a treatment are dated by day: said as the day, never "00:00" (review of batch 1, F5)
            kinds = {event['kind']: event for event in props['events']}
            for kind in ('harvest', 'treatment'):
                self.assertTrue(kinds[kind]['all_day'])
                self.assertRegex(kinds[kind]['when'], r'^\d{2}\.\d{2}\.\d{4}$')
            for kind in ('feeding', 'alarm'):
                self.assertFalse(kinds[kind]['all_day'])
                self.assertRegex(kinds[kind]['when'], r'^\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}$')
            self.assertRegex(props['custom']['start'], r'^\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}$')       # the date box's shape
            self.assertRegex(props['custom']['example'], r'^\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}$')
            ranged = props['range_chart']
            self.assertIsNotNone(ranged['chart'], ranged['reason'])
            self.assertTrue(ranged['path'] and all(ranged['path']))
            self.assertTrue(any(isoline['label'] for isoline in ranged['chart']['isolines']))   # placed by the server
            self.assertTrue(ranged['chart']['regions'])                       # the NH₃-N and CO₂ limits: their regions
            # the window's last day has no diagram (the lab's alkalinity is four days old): said, never a star read as now
            self.assertTrue(ranged['stale'])
            self.assertEqual((ranged['now'], ranged['now_status']), (ranged['stale'], 'warning'))
            keep(f'water-{language}', props)

    def test_tank_water_reads_a_custom_window_in_the_date_boxs_shape(self):
        url = reverse('farm:tank_water', args=[self.unit.pk])
        props = render_island(self.client, url, 'water', {'start': '20.11.2026 06:00', 'end': '21.11.2026 06:00'}, 'en')
        self.assertEqual((props['range'], props['custom']['start'], props['custom']['end']),
                         ('custom', '20.11.2026 06:00', '21.11.2026 06:00'))

    def test_sensor_charts_say_the_chart_and_the_compared_one_and_their_props_are_kept(self):
        props = render_island(self.client, reverse('sensors:charts'), 'sensor-charts', {
            'target': f'unit:{self.unit.pk}', 'quantity': 'ph', 'range': '7d', 'compare': f'unit:{self.unit.pk}',
            'compare_quantity': 'temperature_c'}, 'en')
        self.assertTrue(props['chart']['buckets']['avg'])
        self.assertTrue(props['chart']['gaps'])
        self.assertEqual((props['compare']['chart']['start'], props['compare']['chart']['end']),
                         (props['chart']['start'], props['chart']['end']))
        self.assertIsNotNone(props['now'])                      # a channel is bound: its newest value is said
        self.assertFalse(props['now']['fresh'])                 # the pH is silent: no recent data
        self.assertTrue(props['compare']['now']['fresh'])       # the temperature is fresh
        keep('sensor-charts-en', props)

    def test_sensor_charts_read_from_and_to_in_the_date_boxs_shape(self):
        props = render_island(self.client, reverse('sensors:charts'), 'sensor-charts', {
            'target': f'unit:{self.unit.pk}', 'quantity': 'oxygen_mg_l', 'start': '20.11.2026 06:00',
            'end': '21.11.2026 06:00'}, 'en')
        self.assertEqual(props['errors'], {})
        self.assertTrue(props['chart']['buckets']['avg'])

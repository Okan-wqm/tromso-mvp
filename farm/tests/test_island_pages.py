"""The props of the Production and Sensors islands, made in the test database for the browser test
(frontend/test/production.pages.ts): a small invented farm (every name a fixture's), its water through the real views in
the new look, kept under .build/island-props/ by core/island_props.py. Nothing recorded from a real database is kept
(the repository is public). The pages say the farm's facts: a chart per parameter measured or sampled there, the gap
of the sensors' outage, the meter and lab samples, the fish's limits, the alarm of the window, the compared chart on
the same window.

    water-en, water-nb          Tank › Water of T-01, 7 days (farm:tank_water)
    sensor-charts-en            Sensors › Charts, T-01's pH over 7 days compared with its temperature (sensors:charts)"""
import math
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from alarms.models import Alarm
from core.island_props import keep, render_island
from core.tests_islands import FIXTURE
from farm.models import ProductionDepartment, Site, System, Tank, WaterLimit
from farm.water import services as water_services
from sensors import bindings
from sensors.tests import make_channel, make_connection, make_device, make_format
from sensors.tests.test_read import insert

from .helpers import make_species, point_of, stock_fish
from .test_stock import make_unit

STEP = timedelta(minutes=10)
OUTAGE = (timedelta(days=3, hours=20), timedelta(days=3, hours=8))     # back from now: ten hours without a value


@override_settings(ISLANDS_MANIFEST=FIXTURE)
class IslandPagesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_superuser('reviewer', 'reviewer@example.com', 'x')
        site = Site.objects.create(name='Fjordvik Settefisk', code='FV', timezone='Europe/Oslo')
        hall = ProductionDepartment.objects.create(site=site, name='Hall A', code='HA')
        ras = System.objects.create(name='RAS 1', code='R1', site=site, production_department=hall)
        cls.unit = make_unit('T-01', hall, system=ras)
        Tank.objects.filter(pk=cls.unit.pk).update(name='Smolt tank 1')
        cls.unit.refresh_from_db()
        salmon = make_species()
        stock_fish(cls.user, cls.unit, 5000, '60', 20, species=salmon)
        for parameter, bounds in (('oxygen_mg_l', {'critical_low': 6, 'warning_low': 7}),
                                  ('temperature_c', {'warning_high': 15, 'critical_high': 18}),
                                  ('ph', {'critical_low': '6.5', 'warning_low': '6.8', 'warning_high': '7.8',
                                          'critical_high': '8.2'})):
            WaterLimit.objects.create(species=salmon, parameter=parameter, water_type='any',
                                      **{key: Decimal(str(value)) for key, value in bounds.items()})
        middle = point_of(cls.unit)
        device = make_device(make_connection(), make_format(), site, code='PROBE-T01')
        cls.now = timezone.now().replace(second=0, microsecond=0)
        start = cls.now - timedelta(days=8)
        for quantity, base, swing in (('temperature_c', 12.0, 1.2), ('oxygen_mg_l', 8.4, 0.9), ('ph', 7.3, 0.15)):
            channel = make_channel(device, quantity, code=quantity.upper())
            bindings.move(cls.user, channel, point=middle, at=start)
            rows, moment = [], start + STEP
            while moment < cls.now:
                back = cls.now - moment
                if not OUTAGE[1] <= back <= OUTAGE[0]:
                    hours = (moment - start).total_seconds() / 3600
                    rows.append((moment, round(base + swing * math.sin(hours / 24 * 2 * math.pi), 3)))
                moment += STEP
            insert(channel.channel_no, rows)
        for days, source, values in ((2, 'manual', {'oxygen_mg_l': '7.80', 'temperature_c': '12.4', 'ph': '7.25',
                                                    'tan_mg_l': '0.420'}),
                                     (4, 'lab', {'tan_mg_l': '0.610', 'ph': '7.40', 'temperature_c': '12.1',
                                                 'alkalinity_mg_l': '85'})):
            water_services.record(cls.user, point=middle, measured_at=cls.now - timedelta(days=days), source=source,
                                  values={key: Decimal(value) for key, value in values.items()})
        Alarm.objects.create(source='water_limit', point=middle, parameter='oxygen_mg_l', severity='critical', site=site,
                             opened_at=cls.now - timedelta(days=3), summary='O₂ 5.8 mg/L, below 6.00 (critical)')

    def setUp(self):
        self.client.force_login(self.user)

    def test_tank_water_says_the_farms_facts_and_its_props_are_kept(self):
        url = reverse('farm:tank_water', args=[self.unit.pk])
        for language in ('en', 'nb'):
            props = render_island(self.client, url, 'water', {'range': '7d'}, language)
            charts = {chart['quantity']['code']: chart for chart in props['places'][0]['charts']}
            self.assertLessEqual({'temperature_c', 'oxygen_mg_l', 'ph', 'tan_mg_l', 'alkalinity_mg_l'}, set(charts))
            self.assertTrue(charts['oxygen_mg_l']['gaps'])                              # the outage, shown
            self.assertEqual(charts['ph']['bands'], {'critical_low': 6.5, 'warning_low': 6.8, 'warning_high': 7.8,
                                                     'critical_high': 8.2})
            self.assertEqual(sorted(sample['source'] for sample in charts['tan_mg_l']['samples']), ['lab', 'manual'])
            self.assertEqual(len(props['places'][0]['worked']['nh3_n_mg_l']['values']), 2)
            self.assertEqual([event['kind'] for event in props['events']], ['alarm'])
            keep(f'water-{language}', props)

    def test_sensor_charts_say_the_chart_and_the_compared_one_and_their_props_are_kept(self):
        props = render_island(self.client, reverse('sensors:charts'), 'sensor-charts', {
            'target': f'unit:{self.unit.pk}', 'quantity': 'ph', 'range': '7d', 'compare': f'unit:{self.unit.pk}',
            'compare_quantity': 'temperature_c'}, 'en')
        self.assertTrue(props['chart']['buckets']['avg'])
        self.assertTrue(props['chart']['gaps'])
        self.assertEqual((props['compare']['chart']['start'], props['compare']['chart']['end']),
                         (props['chart']['start'], props['chart']['end']))
        self.assertIsNotNone(props['now'])                      # a channel is bound: its newest value is said
        keep('sensor-charts-en', props)

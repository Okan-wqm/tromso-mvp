"""System › Water (farm:system_water, ?ui=next): the system's points side by side on one time axis, drawn by the island of
Tank › Water from the system's history_data (the JSON of farm:water_system_chart?view=history), the island heading each
point's charts with the point when the system has more than one; the window's props are Tank › Water's
(farm.water.views.window_props); without the new look the address is the system's history on Water chemistry.
On THE test world (core/test_world.py, clock at MOMENT): Test Loop 1 with TT-01's probe and samples; its props are kept
for the browser test (frontend/test/prodrest.pages.ts)."""
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from core.island_props import keep, render_island
from core.test_world import MOMENT, world
from core.testing import FrozenClock

from ..models import System
from ..water.views import history_url

MANIFEST = str(Path(__file__).resolve().parents[2] / 'core' / 'testdata' / 'islands-prodrest-manifest.json')


@override_settings(ISLANDS_MANIFEST=MANIFEST)
class SystemWaterNextTests(FrozenClock, TestCase):
    NOW = MOMENT

    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser('test.admin', 'test.admin@example.com', 'x')
        world(cls.admin, Client())
        cls.system = System.objects.get(code='TL1')
        # the loop's own water (the world samples TT-01's): a meter sample at its point two days back
        from datetime import timedelta
        from decimal import Decimal as D

        from .helpers import point_of
        from ..water import services
        services.record(cls.admin, point=point_of(cls.system), measured_at=MOMENT - timedelta(days=2), source='manual',
                        values={'oxygen_mg_l': D('8.20'), 'temperature_c': D('12.0'), 'ph': D('7.30')}, notes='')

    def setUp(self):
        self.client.force_login(self.admin)
        self.url = reverse('farm:system_water', args=[self.system.pk])

    def test_without_the_new_look_it_is_the_systems_history(self):
        self.assertRedirects(self.client.get(self.url, {'ui': 'classic'}), history_url(self.system),
                             fetch_redirect_response=False)

    def test_the_points_side_by_side_from_the_systems_history_data(self):
        for language in ('en', 'nb', 'tr'):
            props = render_island(self.client, self.url, 'water', {'range': '7d'}, language)
            data = self.client.get(reverse('farm:water_system_chart', args=[self.system.pk]),
                                   {'view': 'history', 'range': '7d'}).json()
            self.assertEqual([place['point'] for place in props['places']], [place['point'] for place in data['places']])
            self.assertEqual((props['start'], props['end']), (data['start'], data['end']))
            self.assertEqual(props['unit']['code'], 'TL1')
            self.assertTrue(any(chart['samples'] or not chart['empty'] for place in props['places']
                                for chart in place['charts']), 'the world\'s values are drawn')
            # a chart's title is its quantity's, as the history's: the island heads each point's charts with the point
            charts = {chart['quantity']['code']: chart['quantity']['label'] for place in data['places']
                      for chart in place['charts']}
            for place in props['places']:
                for chart in place['charts']:
                    self.assertEqual(chart['quantity']['label'], charts[chart['quantity']['code']])
            self.assertRegex(props['custom']['start'], r'^\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}$')
            if language == 'en':
                keep('production-system-water-en', {'island': 'water', 'props': props})

    def test_it_needs_the_right_to_read_the_water(self):
        nobody = get_user_model().objects.create_user('test.nobody', 'test.nobody@example.com', 'x')
        self.client.force_login(nobody)
        self.assertEqual(self.client.get(self.url, {'ui': 'next'}).status_code, 403)

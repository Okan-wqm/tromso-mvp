"""Tank › Water in the new look (farm:tank_water, ?ui=next): the island's root with its props (the water history of the
window, every word finished by the server), the window as the address, the same facts as the unit's history on Water
chemistry (every live sample of the window's middle point, value for value, and the NH₃-N worked out of each), nothing
read as OK when nothing was measured, the right to read the water; without the new look the address is that history."""
import json
import re
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse

from core.tests_islands import FIXTURE

from ..water.views import history_url
from .helpers import role
from .test_water import WaterTestCase


def props_of(html):
    found = re.search(r'<script id="island-water-1" type="application/json">(.*?)</script>', html, re.S)
    return json.loads(found.group(1)) if found else None


@override_settings(ISLANDS_MANIFEST=FIXTURE)
class TankWaterPageTests(WaterTestCase):
    def setUp(self):
        super().setUp()
        self.stock()
        self.limit('oxygen_mg_l', critical_low=6, warning_low=7)
        self.sample(self.t1, hours=3, oxygen_mg_l='6.50', tan_mg_l='0.500', ph='7.20', temperature_c='12.0')
        self.sample(self.t1, hours=30, oxygen_mg_l='8.10')
        self.url = reverse('farm:tank_water', args=[self.t1.pk])

    def page(self, **query):
        response = self.client.get(self.url, {'ui': 'next', **query})
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_without_the_new_look_it_is_the_units_history(self):
        self.assertRedirects(self.client.get(self.url), history_url(self.t1), fetch_redirect_response=False)

    def test_the_island_and_its_props_name_every_part_in_words(self):
        html = self.page()
        self.assertIn('data-island="water"', html)
        props = props_of(html)
        self.assertEqual(props['range'], '24h')
        self.assertEqual([r['key'] for r in props['ranges']], ['24h', '7d', '30d'])
        self.assertTrue(next(r for r in props['ranges'] if r['key'] == '24h')['current'])
        self.assertEqual(props['unit']['code'], 'T-01')
        for word in ('sensor', 'manual', 'lab', 'worked', 'warning', 'critical', 'noValue', 'empty', 'events', 'zoneNote'):
            self.assertTrue(props['words'][word], word)
        self.assertIn('UTC', props['words']['zoneNote'])
        self.assertNotIn('style=', html.split('<main', 1)[1].split('</main>')[0])

    def test_the_same_samples_as_the_units_history_value_for_value(self):
        props = props_of(self.page(range='7d'))
        drawn = {(chart['quantity']['code'], sample['value']) for chart in props['places'][0]['charts']
                 for sample in chart['samples']}
        old = self.client.get(history_url(self.t1)).context['history']
        said = {(code, float(reading.value)) for row in old for code, reading in row.readings.items()
                if not reading.derived and reading.value is not None and code != 'oxygen_saturation_pct'}
        self.assertEqual(drawn, said)
        oxygen = next(c for c in props['places'][0]['charts'] if c['quantity']['code'] == 'oxygen_mg_l')
        self.assertEqual(oxygen['bands'], {'critical_low': 6.0, 'warning_low': 7.0})
        nh3 = props['places'][0]['worked']['nh3_n_mg_l']
        old_nh3 = [float(row.readings['nh3_n_mg_l'].value) for row in old if 'nh3_n_mg_l' in row.readings]
        self.assertEqual([item['value'] for item in nh3['values']], old_nh3)

    def test_a_window_with_nothing_has_no_chart(self):
        start = (self.now - timedelta(days=10)).strftime('%Y-%m-%dT%H:%M')
        end = (self.now - timedelta(days=9)).strftime('%Y-%m-%dT%H:%M')
        props = props_of(self.page(start=start, end=end))
        self.assertEqual((props['range'], props['places'][0]['charts'], props['places'][0]['worked']), ('custom', [], {}))
        self.assertTrue(props['custom']['current'])

    def test_a_window_that_is_not_one_is_refused(self):
        self.assertEqual(self.client.get(self.url, {'ui': 'next', 'start': 'x', 'end': 'y'}).status_code, 400)

    def test_reading_needs_the_water_right(self):
        other = get_user_model().objects.create_user('other', 'other@example.com', 'x')
        other.groups.add(role('Stock reader', 'view_stockoperation'))
        self.client.force_login(other)
        self.assertEqual(self.client.get(self.url, {'ui': 'next'}).status_code, 403)

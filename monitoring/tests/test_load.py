"""The load check of card templates (step 11 of the plan): a wall of 200 cards drawn with a 12-widget template, measured
on the test database (queries, time, bytes) for the page, the fragment and the unchanged poll. It runs only when asked
(MONITOR_LOAD=1; tagged slow), prints what it measured and fails above the bounds below, set from the first measurement
with room for a slower machine: a measured miss decides whether a card cache, a patch protocol or gzip is worth it, never
a guess (README, Monitoring)."""
import os
import time
from unittest import mock, skipUnless

from django.db import connection
from django.test import tag
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .. import read
from ..models import CardTemplate, CardTemplateAssignment
from . import MonitoringCase

WALL = {'schema': 1, 'widgets': [
    {'id': 'w1', 'type': 'value', 'x': 0, 'y': 0, 'w': 3, 'h': 2, 'bind': {'parameter': 'oxygen_mg_l'}, 'opts': {'size': 'large'}},
    {'id': 'w2', 'type': 'value', 'x': 3, 'y': 0, 'w': 3, 'h': 2, 'bind': {'parameter': 'temperature_c'}},
    {'id': 'w3', 'type': 'value', 'x': 6, 'y': 0, 'w': 3, 'h': 2, 'bind': {'parameter': 'ph'}},
    {'id': 'w4', 'type': 'bar', 'x': 9, 'y': 0, 'w': 3, 'h': 2, 'bind': {'parameter': 'oxygen_mg_l'}},
    {'id': 'w5', 'type': 'experiment', 'x': 0, 'y': 2, 'w': 12, 'h': 1},
    {'id': 'w6', 'type': 'fish', 'x': 0, 'y': 3, 'w': 12, 'h': 5, 'opts': {'figures': 'full'}},
    {'id': 'w7', 'type': 'feeding', 'x': 0, 'y': 8, 'w': 12, 'h': 3, 'opts': {'week': True}},
    {'id': 'w8', 'type': 'water_table', 'x': 0, 'y': 11, 'w': 12, 'h': 4, 'opts': {'points': 'all', 'parameters': 'all'}},
    {'id': 'w9', 'type': 'health', 'x': 0, 'y': 15, 'w': 6, 'h': 3},
    {'id': 'w10', 'type': 'tasks', 'x': 6, 'y': 15, 'w': 6, 'h': 2},
    {'id': 'w11', 'type': 'value', 'x': 6, 'y': 17, 'w': 3, 'h': 2, 'bind': {'parameter': 'tan_mg_l'}},
    {'id': 'w12', 'type': 'deffeyes', 'x': 0, 'y': 18, 'w': 4, 'h': 1},
]}
# Bounds from the first measurement (2026-11-05: page 67 queries, 3.4 s, 1,512 KB; fragment 62, 3.1 s, 1,477 KB; the
# unchanged poll 7 queries, 0.03 s), with room for a slower machine.
MAX_QUERIES, MAX_SECONDS, MAX_KB = 80, 30.0, 3000
# A wall of 200 Small cards: about 6 KB a card (monitoring/tests/test_small.py SMALL_CARD_BYTES) and the page around them.
SMALL_MAX_KB = 1400


@tag('slow')
@skipUnless(os.environ.get('MONITOR_LOAD') == '1', 'the load check runs when asked: MONITOR_LOAD=1')
class LoadTests(MonitoringCase):
    def measure(self, url, query):
        with CaptureQueriesContext(connection) as log:
            started = time.perf_counter()
            response = self.client.get(url, query)
            seconds = time.perf_counter() - started
        return response, len(log), seconds, len(response.content) / 1024

    def test_a_wall_of_200_cards_with_a_12_widget_template(self):
        self.farm_of(198)
        mine = CardTemplate.objects.create(name='Wall of 12', layout=WALL)
        CardTemplateAssignment.objects.filter(unit=None, system=None, system_type=None, species=None,
                                              kind=None).update(template=mine)
        self.limit('oxygen_mg_l', critical_low=6, warning_low=7, warning_high=12, critical_high=14)
        found = {}
        with mock.patch.object(read, 'TOKEN_BUCKET', 10 ** 9):
            # (the page drawn with its cards: ?full=1; the page itself is the shell, its cards the fragment's)
            for name, url, own in (('page', reverse('monitoring:monitor'), {'full': '1'}),
                                   ('fragment', reverse('monitoring:cards'), {})):
                self.measure(url, {'wall': '1', **own})                            # warm
                response, queries, seconds, kb = self.measure(url, {'wall': '1', **own})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.content.decode().count('data-key="card:'), 200)
                found[name] = (queries, round(seconds, 2), round(kb))
            after = self.client.get(reverse('monitoring:cards'), {'wall': '1'})['X-Poll-Next']
            response, queries, seconds, kb = self.measure(after, {})
            self.assertEqual(response.status_code, 204)
            found['204'] = (queries, round(seconds, 3), 0)
        print('\nLOAD 200 cards, 12 widgets (queries, seconds, KB):', found)
        for name, (queries, seconds, kb) in found.items():
            with self.subTest(path=name):
                self.assertLessEqual(queries, MAX_QUERIES)
                self.assertLessEqual(seconds, MAX_SECONDS)
                self.assertLessEqual(kb, MAX_KB)

    def test_a_wall_of_200_small_cards(self):
        """The overview of a wide monitor (mode=small): 200 Small cards, each with its four values, the calculated CO₂
        and the pH window from the unit's chart (the chemistry core once per unit, the fish's limits once for all)."""
        for unit in self.farm_of(198, fresh=False):
            self.sample(unit, hours=1, temperature_c='9.5', oxygen_mg_l='9', ph='7.2', alkalinity_mg_l='95',
                        tan_mg_l='0.5')
        self.limit('oxygen_mg_l', critical_low=6, warning_low=7, warning_high=12, critical_high=14)
        self.limit('co2_mg_l', warning_high=15, critical_high=20)
        self.limit('nh3_n_mg_l', warning_high='0.0100', critical_high='0.0200')
        self.limit('alkalinity_mg_l', warning_low=70, warning_high=150)
        found = {}
        small = {'wall': '1', 'mode': 'small'}
        with mock.patch.object(read, 'TOKEN_BUCKET', 10 ** 9):
            for name, url, own in (('page', reverse('monitoring:monitor'), {'full': '1'}),
                                   ('fragment', reverse('monitoring:cards'), {})):
                self.measure(url, {**small, **own})                                # warm
                response, queries, seconds, kb = self.measure(url, {**small, **own})
                self.assertEqual(response.status_code, 200)
                html = response.content.decode()
                self.assertEqual(html.count('data-key="card:'), 200)
                self.assertGreaterEqual(html.count('class="monitor-ph-window'), 198)      # a chart drawn for each
                found[name] = (queries, round(seconds, 2), round(kb))
        print('\nLOAD 200 small cards (queries, seconds, KB):', found)
        for name, (queries, seconds, kb) in found.items():
            with self.subTest(path=name):
                self.assertLessEqual(queries, MAX_QUERIES)
                self.assertLessEqual(seconds, MAX_SECONDS)
                self.assertLessEqual(kb, SMALL_MAX_KB)

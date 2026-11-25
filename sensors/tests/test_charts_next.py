"""Sensors › Charts in the new look (sensors:charts with ?ui=next): the island's root and its props, the same query as the
classic page and the same chart (its buckets, gaps and samples, from the one series reader), the place compared on the
same window, a refused query said with its reasons and no chart, the CSV of what is drawn; the classic page unchanged."""
import json
import re

from django.test import override_settings
from django.urls import reverse

from core.tests_islands import FIXTURE

from .test_chart_data import ChartDataCase

URL = reverse('sensors:charts')


def props_of(html):
    found = re.search(r'<script id="island-sensor-charts-1" type="application/json">(.*?)</script>', html, re.S)
    return json.loads(found.group(1)) if found else None


@override_settings(ISLANDS_MANIFEST=FIXTURE)
class ChartsNextTests(ChartDataCase):
    def next(self, **query):
        response = self.client.get(URL, {'ui': 'next', **query})
        self.assertEqual(response.status_code, 200)
        return response

    def test_the_same_chart_as_the_classic_page(self):
        props = props_of(self.next(**self.query()).content.decode())
        classic = self.client.get(URL, {**self.query(), 'ui': 'classic'}).context['chart']
        self.assertEqual(props['chart']['buckets']['avg'], [bucket.avg for bucket in classic.buckets])
        self.assertEqual(len(props['chart']['gaps']), len(classic.gaps))
        self.assertEqual(props['values']['target'], f'unit:{self.t1.pk}')
        self.assertTrue(props['csv'].startswith(reverse('sensors:chart_csv') + '?'))
        self.assertNotIn('ui=', props['csv'])
        self.assertEqual(props['ranges'], ['6h', '24h', '7d', '30d', '90d', '1y', '2y'])
        self.assertTrue(props['places'] and props['quantities'])

    def test_the_compared_place_is_on_the_same_window(self):
        props = props_of(self.next(**self.query(compare=f'unit:{self.t2.pk}')).content.decode())
        self.assertEqual((props['compare']['chart']['start'], props['compare']['chart']['end']),
                         (props['chart']['start'], props['chart']['end']))

    def test_a_refused_query_is_said_with_its_reasons_and_no_chart(self):
        props = props_of(self.next(**self.query(end='2026-09-01T00:00')).content.decode())
        self.assertIsNone(props['chart'])
        self.assertIn('The end comes after the start.', json.dumps(props['errors']))

    def test_an_empty_query_asks_for_one(self):
        props = props_of(self.next().content.decode())
        self.assertEqual((props['chart'], props['errors']), (None, {}))
        self.assertTrue(props['words']['start'])

    def test_the_classic_page_is_unchanged(self):
        response = self.client.get(URL, self.query())
        self.assertTemplateUsed(response, 'sensors/charts.html')
        self.assertContains(response, '<svg')

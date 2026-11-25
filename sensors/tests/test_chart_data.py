"""The chart as data (sensors/chart.py `data`, sensors:chart_data), what the Charts page and Tank › Water behind `?ui=next`
draw: exactly the SVG chart's buckets, gaps, samples (with their source: meter or lab) and marks, the CSV beside it, the
fish's limit bands only for a person who may read the water, the channel's newest value with its freshness, and a query
the form refuses answered with its reasons, never an empty chart."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from farm.models import WaterLimit
from farm.tests.helpers import make_species, role, stock_fish
from farm.water import services as water_services

from sensors import bindings, chart, demo as sensor_demo, read
from sensors.models import ChannelState, Device

from . import make_channel, make_connection
from .test_read import READER, ReadCase, insert

URL = reverse('sensors:chart_data')


class ChartDataCase(ReadCase):
    def setUp(self):
        insert(self.temp.channel_no, [(self.start + timedelta(minutes=minute), 9 + minute / 100) for minute in range(30)]
               + [(self.start + timedelta(minutes=90 + minute), 9.5) for minute in range(10)])
        self.reader = get_user_model().objects.create_user('reader', 'reader@example.com', 'x')
        self.reader.groups.add(role('Reader', *READER, 'view_tank'))
        self.client.force_login(self.reader)

    def query(self, **extra):
        return {'target': f'unit:{self.t1.pk}', 'quantity': 'temperature_c', 'start': '2026-10-01T00:00',
                'end': '2026-10-01T02:00', **extra}


class ChartDataTests(ChartDataCase):
    def test_the_data_is_what_the_svg_draws(self):
        found = read.series(self.t1, 'temperature_c', self.start, self.start + timedelta(hours=2))
        drawn = chart.data(found, 'T-01')
        self.assertEqual(len(drawn['buckets']['avg']), len(found.buckets))
        self.assertEqual(drawn['buckets']['avg'], [bucket.avg for bucket in found.buckets])
        self.assertEqual(drawn['gaps'], [[int(a.timestamp()), int(b.timestamp())] for a, b in found.gaps])
        self.assertTrue(drawn['gaps'])                                       # the half hour without values
        self.assertEqual(drawn['head'], chart.head_text(found, 'T-01'))
        self.assertEqual((drawn['quantity']['code'], drawn['quantity']['decimals']), ('temperature_c', 1))
        self.assertFalse(drawn['empty'])
        # the chart in words, for whoever cannot see it (review of batch 1, S2): its latest, lowest, highest and gaps
        self.assertEqual([term for term, _words in drawn['said']], ['Latest', 'Lowest', 'Highest', 'No value'])
        self.assertEqual(drawn['said'][1][1], '9.0 °C at 01.10.2026 00:00')            # the site's clock (UTC here)
        self.assertTrue(drawn['gap_text'].startswith('from 01.10.2026 00:'))
        self.assertEqual(drawn['buckets']['other'], [False] * len(found.buckets))         # its own probe only

    def test_an_empty_window_says_so(self):
        found = read.series(self.t1, 'temperature_c', self.start - timedelta(days=3), self.start - timedelta(days=2))
        drawn = chart.data(found, 'T-01')
        self.assertTrue(drawn['empty'])
        self.assertEqual(drawn['empty_text'], 'No sensor values in this time.')

    def test_a_sample_says_whether_it_came_from_a_meter_or_a_lab(self):
        now = timezone.now()
        for hours, source in ((2, 'manual'), (1, 'lab')):
            water_services.record(self.user, point=self.mid1, measured_at=now - timedelta(hours=hours), source=source,
                                  values={'temperature_c': Decimal('8.5')})
        found = read.series(self.t1, 'temperature_c', now - timedelta(hours=6), now)
        self.assertEqual([sample['source'] for sample in chart.data(found, 'T-01')['samples']], ['manual', 'lab'])

    def test_the_endpoint_gives_the_chart_its_csv_and_the_newest_value(self):
        now = timezone.now()
        ChannelState.objects.create(channel_no=self.temp.channel_no, last_value=9.5, last_value_ts=now - timedelta(
            seconds=20), last_good_at=now - timedelta(seconds=20))
        response = self.client.get(URL, self.query())
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(sum(body['chart']['buckets']['n']), 40)
        self.assertTrue(body['csv'].startswith(reverse('sensors:chart_csv') + '?'))
        self.assertEqual((body['now']['value'], body['now']['fresh']), (9.5, True))
        self.assertEqual(body['chart']['bands'], {})                       # no right to read the water: no band

    def test_the_newest_value_is_the_channel_drawn_last_not_the_last_one_bound(self):
        """A tank's own probe (fresh, drawn last) and the loop's probe on its system (filling the own probe's gap, no
        value now): "now" is the own probe's, never the loop's "no recent data"; and the other way round."""
        loop = make_channel(self.device, 'temperature_c', code='TEMP-LOOP')
        bindings.move(self.user, loop, system=self.ras, at=self.start)
        insert(loop.channel_no, [(self.start + timedelta(minutes=40 + minute), 11.0) for minute in range(30)])
        now = timezone.now()
        ChannelState.objects.create(channel_no=self.temp.channel_no, last_value=9.5, last_value_ts=now - timedelta(
            seconds=20), last_good_at=now - timedelta(seconds=20))
        body = self.client.get(URL, self.query()).json()
        self.assertEqual(set(body['chart']['buckets']['channel']), {self.temp.channel_no, loop.channel_no})
        self.assertEqual(body['chart']['buckets']['channel'][-1], self.temp.channel_no)
        # the loop's buckets are marked as the system's, as the SVG chart marks them (review of batch 1, F1)
        self.assertEqual(body['chart']['buckets']['other'], [channel == loop.channel_no for channel in body['chart']['buckets']['channel']])
        self.assertEqual(body['chart']['other_text'], 'From the backup or the system’s channel')
        self.assertEqual((body['now']['channel'], body['now']['value'], body['now']['fresh']),
                         (self.temp.channel_no, 9.5, True))
        # the window ends inside the loop's run: the loop's channel is drawn last, and "now" is its own (no value yet)
        body = self.client.get(URL, self.query(end='2026-10-01T01:00')).json()
        self.assertEqual(body['chart']['buckets']['channel'][-1], loop.channel_no)
        self.assertEqual((body['now']['channel'], body['now']['fresh']), (loop.channel_no, False))

    def test_a_stale_newest_value_says_it_is_not_fresh(self):
        old = timezone.now() - timedelta(days=1)
        ChannelState.objects.create(channel_no=self.temp.channel_no, last_value=9.5, last_value_ts=old, last_good_at=old)
        self.assertFalse(self.client.get(URL, self.query()).json()['now']['fresh'])

    def test_the_bands_for_a_person_who_may_read_the_water(self):
        salmon = make_species()
        stock_fish(self.user, self.t1, 500, species=salmon)
        WaterLimit.objects.create(species=salmon, parameter='temperature_c', water_type='any',
                                  warning_high=Decimal(15), critical_high=Decimal(18))
        self.reader.groups.add(role('Water reader', 'view_watermeasurement'))
        bands = self.client.get(URL, self.query()).json()['chart']['bands']
        self.assertEqual(bands, {'warning_high': 15.0, 'critical_high': 18.0})

    def test_a_refused_query_is_answered_with_its_reasons(self):
        response = self.client.get(URL, self.query(end='2026-09-01T00:00'))
        self.assertEqual(response.status_code, 400)
        self.assertIn('The end comes after the start.', str(response.json()['errors']))
        self.assertEqual(self.client.get(URL).status_code, 400)

    def test_reading_needs_its_right(self):
        self.client.force_login(get_user_model().objects.create_user('other', 'other@example.com', 'x'))
        self.assertEqual(self.client.get(URL, self.query()).status_code, 403)


class SimulatedAndCompareTests(ChartDataCase):
    def test_a_chart_from_the_demos_channels_says_its_values_are_simulated(self):
        found = read.series(self.t1, 'temperature_c', self.start, self.start + timedelta(hours=2))
        self.assertFalse(chart.data(found, 'T-01')['simulated'])
        demo = make_connection('Demo', client_id=sensor_demo.CLIENT_ID)
        Device.objects.filter(pk=self.device.pk).update(connection=demo)
        drawn = chart.data(found, 'T-01')
        self.assertTrue(drawn['simulated'])
        self.assertEqual(drawn['simulated_text'], 'Simulated values')
        self.assertTrue(all(drawn['buckets']['simulated']))

    def test_compare_reads_a_second_place_on_exactly_the_same_window(self):
        body = self.client.get(URL, self.query(compare=f'unit:{self.t2.pk}')).json()
        first, second = body['chart'], body['compare']['chart']
        self.assertEqual((second['start'], second['end'], second['width_s']),
                         (first['start'], first['end'], first['width_s']))
        self.assertTrue(second['empty'])                                 # nothing bound at T-02: said, not hidden
        self.assertIsNone(body['compare']['now'])
        other = self.client.get(URL, self.query(compare=f'unit:{self.t1.pk}', compare_quantity='ph')).json()
        self.assertEqual(other['compare']['chart']['quantity']['code'], 'ph')

    def test_a_compare_that_is_not_one_is_refused(self):
        for extra in ({'compare': 'unit:nothing'}, {'compare': f'unit:{self.t2.pk}', 'compare_quantity': 'colour'}):
            with self.subTest(extra=extra):
                self.assertEqual(self.client.get(URL, self.query(**extra)).status_code, 400)

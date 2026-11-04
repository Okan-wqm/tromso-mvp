"""The sensor reads (sensors/read.py) and their pages: the latest value of a channel from its state, the value at a moment
(never one from after it), the segments of a target (a moved sensor gives two), the series of a target and a quantity
on the bucket ladder (raw rows bucketed below a minute, the minute rollup up to an hour, the hour rollup above, local days
on the site's clock across a change of clocks), exact sums against the stored rows, the primary drawn and the backup
only where the primary has no data, gaps where the spacing is longer than the channel's freshness, manual samples as
points, the chart's SVG, the CSV of what is drawn, the Charts and Live values pages and their right."""
import csv
import io
from datetime import datetime, timedelta, timezone as tz
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.db import connection
from django.urls import reverse
from django.utils import timezone

from farm.models import Site, System
from farm.tests.helpers import point_of, role
from farm.tests.test_stock import make_unit
from farm.water import services as water_services

from sensors import bindings, chart, read
from sensors.models import ChannelState, Device

from . import SensorsCase, make_channel

READER = ('view_reading',)


def insert(channel_no, rows):
    """(ts, value[, n, quality, run_sum, run_min, run_max]) rows."""
    defaults = (None, None, 1, 0, None, None, None)
    full = [(channel_no, *row, *defaults[len(row):]) for row in rows]
    with connection.cursor() as cursor:
        cursor.executemany('INSERT INTO sensors_reading (channel_no, ts, value, n, quality, run_sum, run_min, run_max) '
                           'VALUES (%s, %s, %s, %s, %s, %s, %s, %s)', full)


class ReadCase(SensorsCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.ras = System.objects.create(name='RAS 1', code='R1', site=cls.site, production_department=cls.hall)
        cls.t1 = make_unit('T-01', cls.hall, system=cls.ras)
        cls.t2 = make_unit('T-02', cls.hall, system=cls.ras)
        cls.mid1, cls.mid2 = point_of(cls.t1), point_of(cls.t2)
        cls.start = datetime(2026, 10, 1, tzinfo=tz.utc)
        cls.temp = cls.channel                                   # temperature, heartbeat 60 s, fresh 180 s
        bindings.move(cls.user, cls.temp, point=cls.mid1, at=cls.start)


class LatestTests(ReadCase):
    def test_the_state_gives_the_value_and_its_freshness(self):
        now = timezone.now()
        ChannelState.objects.create(channel_no=self.temp.channel_no, last_value=9.5, last_value_ts=now - timedelta(
            seconds=30), last_good_at=now - timedelta(seconds=30), last_seen_at=now - timedelta(seconds=2))
        state = read.latest([self.temp.channel_no], now)[self.temp.channel_no]
        self.assertEqual((state.value, state.fresh), (9.5, True))
        stale = read.latest([self.temp.channel_no], now + timedelta(seconds=200))[self.temp.channel_no]
        self.assertFalse(stale.fresh)

    def test_a_channel_with_no_value_yet_is_said_so(self):
        state = read.latest([self.temp.channel_no], timezone.now())[self.temp.channel_no]
        self.assertIsNone(state.value)
        self.assertFalse(state.fresh)


class ValueAtTests(ReadCase):
    def test_the_newest_clean_value_at_or_before_the_moment_never_after(self):
        moment = self.start + timedelta(hours=1)
        insert(self.temp.channel_no, [(moment - timedelta(minutes=5), 9.0), (moment, 9.2), (moment + timedelta(seconds=1),
                                                                                               9.9)])
        self.assertEqual(read.value_at(self.temp.channel_no, moment), (moment, 9.2))
        self.assertEqual(read.value_at(self.temp.channel_no, moment - timedelta(seconds=1))[1], 9.0)
        self.assertIsNone(read.value_at(self.temp.channel_no, self.start - timedelta(days=1)))

    def test_a_bad_reading_is_skipped(self):
        moment = self.start + timedelta(hours=1)
        insert(self.temp.channel_no, [(moment - timedelta(minutes=5), 9.0), (moment, 50.0, 1, 16)])
        self.assertEqual(read.value_at(self.temp.channel_no, moment)[1], 9.0)


class SegmentTests(ReadCase):
    def test_a_moved_sensor_gives_each_unit_its_own_time(self):
        moved = self.start + timedelta(days=2)
        bindings.move(self.user, self.temp, point=self.mid2, at=moved)
        end = self.start + timedelta(days=4)
        first = read.segments(self.t1, 'temperature_c', self.start, end)
        second = read.segments(self.t2, 'temperature_c', self.start, end)
        self.assertEqual([(s.channel_no, s.start, s.end) for s in first], [(self.temp.channel_no, self.start, moved)])
        self.assertEqual([(s.channel_no, s.start, s.end) for s in second], [(self.temp.channel_no, moved, end)])

    def test_a_unit_has_its_points_segments_before_its_systems(self):
        system_probe = make_channel(self.device, 'temperature_c', code='T-SYS')
        bindings.move(self.user, system_probe, system=self.ras, at=self.start)
        found = read.segments(self.t1, 'temperature_c', self.start, self.start + timedelta(days=1))
        self.assertEqual([s.origin for s in found], ['sensor', 'system_sensor'])


class SeriesTests(ReadCase):
    def setUp(self):
        # Two hours, one row a minute standing for 60 messages of a second each; one bad row.
        rows = []
        for minute in range(120):
            moment = self.start + timedelta(minutes=minute, seconds=59)
            value = 9 + (minute % 7) * 0.1
            rows.append((moment, value, 60, 0, value * 60 - 0.3, value - 0.2, value + 0.1))
        rows.append((self.start + timedelta(minutes=30, seconds=30), 40.0, 1, 16))
        insert(self.temp.channel_no, rows)
        self.rows = rows[:-1]

    def test_the_tier_follows_the_bucket_width(self):
        for hours, tier in ((1, 'raw'), (24, '1m'), (24 * 30, '1h'), (24 * 400, 'day')):
            with self.subTest(hours=hours):
                found = read.series(self.t1, 'temperature_c', self.start, self.start + timedelta(hours=hours))
                self.assertEqual(found.tier, tier)
                self.assertLessEqual(len(found.buckets), read.MAX_POINTS)

    def test_the_sums_are_exact_against_the_stored_rows(self):
        found = read.series(self.t1, 'temperature_c', self.start, self.start + timedelta(hours=2), max_points=4)
        self.assertEqual(found.width, timedelta(minutes=30))
        total_n = sum(bucket.n for bucket in found.buckets)
        self.assertEqual(total_n, 120 * 60)
        first = found.buckets[0]
        rows = [row for row in self.rows if row[0] < self.start + timedelta(minutes=30)]
        self.assertAlmostEqual(first.avg, sum(row[4] for row in rows) / sum(row[2] for row in rows), places=9)
        self.assertAlmostEqual(first.vmin, min(row[5] for row in rows), places=9)
        self.assertAlmostEqual(first.vmax, max(row[6] for row in rows), places=9)

    def test_an_empty_range_is_said_to_be_empty(self):
        found = read.series(self.t1, 'temperature_c', self.start - timedelta(days=3), self.start - timedelta(days=2))
        self.assertEqual(found.buckets, [])
        self.assertTrue(found.empty)

    def test_a_range_that_ends_before_it_starts_is_refused(self):
        with self.assertRaises(ValueError):
            read.series(self.t1, 'temperature_c', self.start, self.start)

    def test_a_gap_longer_than_the_freshness_is_shown_and_never_filled(self):
        later = self.start + timedelta(hours=3)
        insert(self.temp.channel_no, [(later, 9.0), (later + timedelta(minutes=1), 9.1)])
        found = read.series(self.t1, 'temperature_c', self.start, self.start + timedelta(hours=4), max_points=2000)
        gaps = [(start, end) for start, end in found.gaps if start >= self.start + timedelta(hours=1)]
        self.assertEqual(gaps[0], (self.start + timedelta(minutes=119, seconds=59), later))
        self.assertFalse([b for b in found.buckets if self.start + timedelta(hours=2) <= b.start < later])

    def test_the_backup_fills_only_where_the_primary_has_no_data(self):
        backup = make_channel(self.device, 'temperature_c', code='T-BACKUP')
        bindings.move(self.user, backup, point=self.mid1, at=self.start, role='backup')
        insert(backup.channel_no, [(self.start + timedelta(minutes=10), 1.0), (self.start + timedelta(hours=2, minutes=10),
                                                                              2.0)])
        found = read.series(self.t1, 'temperature_c', self.start, self.start + timedelta(hours=3), max_points=18)
        by_start = {bucket.start: bucket for bucket in found.buckets}
        self.assertEqual(by_start[self.start].channel_no, self.temp.channel_no)
        self.assertEqual(by_start[self.start + timedelta(hours=2)].channel_no, backup.channel_no)
        self.assertEqual(by_start[self.start + timedelta(hours=2)].role, 'backup')

    def test_a_moved_sensor_splits_its_series(self):
        moved = self.start + timedelta(hours=1)
        bindings.move(self.user, self.temp, point=self.mid2, at=moved)
        first = read.series(self.t1, 'temperature_c', self.start, self.start + timedelta(hours=2), max_points=120)
        second = read.series(self.t2, 'temperature_c', self.start, self.start + timedelta(hours=2), max_points=120)
        self.assertTrue(all(bucket.start < moved for bucket in first.buckets))
        self.assertTrue(all(bucket.start >= moved for bucket in second.buckets))
        self.assertEqual(len(first.buckets) + len(second.buckets), 120)
        self.assertIn(moved, [marker.at for marker in second.markers])

    def test_manual_samples_are_drawn_as_points(self):
        water_services.record(self.user, point=self.mid1, measured_at=timezone.now() - timedelta(hours=1),
                              source='manual', values={'temperature_c': Decimal('8.5')})
        now = timezone.now()
        found = read.series(self.t1, 'temperature_c', now - timedelta(hours=6), now)
        self.assertEqual([float(value) for _at, value in found.samples], [8.5])


class LocalDayTests(ReadCase):
    def test_days_are_the_sites_days_across_a_change_of_clocks(self):
        Site.objects.filter(pk=self.site.pk).update(timezone='Europe/Oslo')
        oslo = ZoneInfo('Europe/Oslo')
        # 2026-10-25: the clocks go back in Oslo, a day of 25 hours.
        day = datetime(2026, 10, 25, tzinfo=oslo)
        rows = [(day.astimezone(tz.utc) + timedelta(hours=hour), 9.0) for hour in range(25)]     # absolute hours
        rows += [(datetime(2026, 10, 26, 0, 30, tzinfo=oslo), 9.0)]
        insert(self.temp.channel_no, rows)
        unit = type(self.t1).objects.select_related('production_department__site').get(pk=self.t1.pk)
        found = read.series(unit, 'temperature_c', datetime(2026, 9, 1, tzinfo=tz.utc),
                            datetime(2027, 11, 1, tzinfo=tz.utc))
        self.assertEqual(found.tier, 'day')
        days = {bucket.start.astimezone(oslo).date(): bucket.n for bucket in found.buckets}
        self.assertEqual(days[day.date()], 25)
        self.assertEqual(days[datetime(2026, 10, 26).date()], 1)


class ChartTests(ReadCase):
    def test_the_svg_names_its_tier_shades_gaps_and_escapes_text(self):
        insert(self.temp.channel_no, [(self.start + timedelta(minutes=1), 9.0), (self.start + timedelta(hours=1), 9.5)])
        found = read.series(self.t1, 'temperature_c', self.start, self.start + timedelta(hours=2), max_points=120)
        svg = chart.draw(found, title='<T-01>')
        self.assertIn('&lt;T-01&gt;', svg)
        self.assertIn('class="chart-gap"', svg)
        self.assertIn('class="chart-line"', svg)
        self.assertIn('data-tier="1m"', svg)

    def test_an_empty_chart_says_so(self):
        found = read.series(self.t1, 'temperature_c', self.start - timedelta(days=3), self.start - timedelta(days=2))
        self.assertIn('No sensor values in this time', chart.draw(found, title='T-01'))


class PageTests(ReadCase):
    def setUp(self):
        insert(self.temp.channel_no, [(self.start + timedelta(minutes=minute), 9 + minute / 100) for minute in range(60)])
        self.reader = get_user_model().objects.create_user('reader', 'reader@example.com', 'x')
        self.reader.groups.add(role('Reader', *READER, 'view_tank'))
        self.client.force_login(self.reader)

    def query(self, **extra):
        return {'target': f'unit:{self.t1.pk}', 'quantity': 'temperature_c', 'start': '2026-10-01T00:00',
                'end': '2026-10-01T02:00', **extra}

    def test_the_charts_page_draws_the_chart_and_its_csv_is_what_is_drawn(self):
        page = self.client.get(reverse('sensors:charts'), self.query())
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, '<svg')
        drawn = page.context['chart']
        rows = list(csv.reader(io.StringIO(self.client.get(reverse('sensors:chart_csv'), self.query()).content.decode())))
        self.assertEqual(rows[0], ['start', 'end', 'average', 'lowest', 'highest', 'messages', 'channel', 'role',
                                   'source'])
        self.assertEqual(len(rows) - 1, len(drawn.buckets))
        self.assertEqual(sum(int(row[5]) for row in rows[1:]), 60)

    def test_a_bad_query_is_said_not_drawn(self):
        page = self.client.get(reverse('sensors:charts'), self.query(end='2026-09-01T00:00'))
        self.assertContains(page, 'The end comes after the start.')
        self.assertIsNone(page.context['chart'])

    def test_the_live_values_page_lists_the_channels_with_age_and_state(self):
        now = timezone.now()
        ChannelState.objects.create(channel_no=self.temp.channel_no, last_value=9.5, last_value_ts=now - timedelta(
            seconds=20), last_good_at=now - timedelta(seconds=20))
        page = self.client.get(reverse('sensors:live'))
        self.assertContains(page, 'TEMPERATURE-C')
        self.assertContains(page, '9.5')
        self.assertContains(page, 'Fresh')

    def test_reading_needs_its_right(self):
        other = get_user_model().objects.create_user('other', 'other@example.com', 'x')
        self.client.force_login(other)
        for name in ('sensors:charts', 'sensors:chart_csv', 'sensors:live'):
            self.assertEqual(self.client.get(reverse(name), self.query()).status_code, 403, name)

    def test_the_window_fragment_charts_every_bound_quantity_of_a_unit(self):
        page = self.client.get(reverse('sensors:target_charts'), {'target': f'unit:{self.t1.pk}', 'range': '2y'})
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'Temperature (°C)')
        self.assertContains(page, '<svg')


class DeviceStatusTests(ReadCase):
    def test_a_device_is_offline_after_three_intervals_without_a_message(self):
        from sensors.models import DeviceState
        now = timezone.now()
        DeviceState.objects.create(device_id=self.device.pk, last_message_at=now - timedelta(seconds=2))
        status = read.device_status([self.device], now)[self.device.pk]
        self.assertTrue(status.online)
        Device.objects.filter(pk=self.device.pk).update(expected_interval_s=1)
        self.assertFalse(read.device_status([self.device], now + timedelta(seconds=5))[self.device.pk].online)

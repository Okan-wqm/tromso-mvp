"""Synthetic sensor readings for the plan's storage and read-time figures (docs: README, Sensors, Measured figures): writes
`--channels` channels (numbers from 1,000,000 on, bound to nothing, so no page shows them) for `--days` days, one stored
row every `--interval` seconds (a reduced channel's row stands for its messages), then prints the raw rows, the hour
rollup rows, the time of a chart of one channel over the whole span (local days from the hour rollup), of ten channels
over seven days in 15-minute buckets of the readings themselves, and of the latest values. It refuses a range that already
holds rows (TimescaleDB 2.17.2 loses rows of a multi-row insert that meets a row in a compressed chunk). It writes into
the database it is pointed at: it refuses to run unless `--confirm-database` names that database. Never run it on a
farm's database; use a copy or a test database, and drop the rows after (`--drop`)."""
import json
import time
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.utils import timezone

from farm.water.read import as_parameter
from sensors import read

FIRST = 1_000_000
# A fish's limits for the diagrams: NH₃-N and CO₂ (mg/L), the alkalinity band (mg/L as CaCO₃).
LIMITS = {'nh3_n_limit_mg_l': 0.0125, 'co2_limit_mg_l': 15.0,
          'alkalinity_low_mg_l': 50.0, 'alkalinity_high_mg_l': 150.0}


class Command(BaseCommand):
    help = 'Writes synthetic sensor readings into a confirmed database and prints storage and read figures.'

    def add_arguments(self, parser):
        parser.add_argument('--channels', type=int, default=20)
        parser.add_argument('--days', type=int, default=730)
        parser.add_argument('--interval', type=int, default=60, help='Seconds between two stored rows of a channel.')
        parser.add_argument('--confirm-database', default='', help='The name of the database written to.')
        parser.add_argument('--drop', action='store_true', help='Delete the synthetic rows first.')
        parser.add_argument('--frames', type=int, default=read.PAGE,
                            help='Frames of the replay page timed at one minute (a page at most).')
        parser.add_argument('--measure-only', action='store_true',
                            help='Write nothing: time the rows already there (refreshed and compressed, as in use).')

    def handle(self, *args, **options):
        name = connection.settings_dict['NAME']
        if options['confirm_database'] != name:
            raise CommandError(f'This writes synthetic readings into "{name}": confirm with --confirm-database {name}.')
        channels, days, interval = options['channels'], options['days'], options['interval']
        if channels < 1 or days < 1 or interval < 1 or not 1 <= options['frames'] <= read.PAGE:
            raise CommandError(f'Channels, days and the interval are at least 1; the frames 1 to {read.PAGE}.')
        end = timezone.now().replace(second=0, microsecond=0)
        start = end - timedelta(days=days)
        last = FIRST + channels - 1
        with connection.cursor() as cursor:
            if options['drop']:
                cursor.execute('DELETE FROM sensors_reading WHERE channel_no BETWEEN %s AND %s', [FIRST, last])
            cursor.execute('SELECT count(*) FROM sensors_reading WHERE channel_no BETWEEN %s AND %s', [FIRST, last])
            there = cursor.fetchone()[0]
            if there and not options['measure_only']:
                # Never write over rows: one multi-row insert meeting a row in a compressed chunk loses the rest of its
                # rows silently (TimescaleDB 2.17.2), so the range must be empty (--drop deletes the synthetic rows).
                raise CommandError('The synthetic channels already hold readings: run with --drop to delete them first.')
            written, seconds = 0, 0.0
            if not options['measure_only']:
                began = time.monotonic()
                # A slow wave with noise; each row stands for `interval` one-second messages around it. No ON CONFLICT:
                # the range is empty, and a conflict would stop the command instead of dropping rows unseen.
                cursor.execute(
                    'INSERT INTO sensors_reading (channel_no, ts, value, n, run_sum, run_min, run_max) '
                    'SELECT c, t, v, n, CASE WHEN n > 1 THEN v * n END, CASE WHEN n > 1 THEN v - 0.05 END, '
                    'CASE WHEN n > 1 THEN v + 0.05 END FROM ('
                    '  SELECT c, t, round((10 + sin(extract(epoch FROM t) / 86400.0 * 6.283) + random() * 0.1)'
                    '::numeric, 3)::float8 AS v, %s AS n'
                    '  FROM generate_series(%s::int, %s::int) c, generate_series(%s::timestamptz, %s::timestamptz - '
                    "interval '1 second', make_interval(secs => %s)) t) s",
                    [interval, FIRST, last, start, end, interval])
                written = cursor.rowcount
                seconds = time.monotonic() - began
            cursor.execute('SELECT count(*) FROM sensors_reading WHERE channel_no BETWEEN %s AND %s', [FIRST, last])
            raw = cursor.fetchone()[0]
            cursor.execute('SELECT count(*) FROM sensors_rollup_1h WHERE channel_no BETWEEN %s AND %s', [FIRST, last])
            hours = cursor.fetchone()[0]
        zone = timezone.get_default_timezone()
        span_ms, span_buckets, span_width = self.chart(FIRST, start, end, interval, zone)
        week = max(start, end - timedelta(days=7))
        began = time.monotonic()
        week_buckets = sum(self.chart(number, week, end, interval, zone, width=15 * read.MINUTE)[1]
                           for number in range(FIRST, min(last, FIRST + 9) + 1))
        week_ms = (time.monotonic() - began) * 1000
        replay = [read.Segment(number, week, end, 'primary', read.SENSOR, interval * 3, False, False)
                  for number in range(FIRST, min(last, FIRST + 3) + 1)]
        hourly = int((end - week) / read.HOUR)
        began = time.monotonic()
        values = read.replay_rows(replay, week, read.HOUR, hourly, read.ROLLUP_1H)
        replay_ms = (time.monotonic() - began) * 1000
        # A7: one page of frames at one minute (2000 by default), the readings of four channels in one query.
        frames = options['frames']
        first = end - frames * read.MINUTE
        page = [read.Segment(segment.channel_no, first - read.CARRY, end, 'primary', read.SENSOR, interval * 3, False,
                             False) for segment in replay]
        began = time.monotonic()
        minutes = read.replay_rows(page, first, read.MINUTE, frames, read.RAW)
        page_ms = (time.monotonic() - began) * 1000
        # A8: the whole diagram of every frame of that page, the channels standing for a water whose temperature,
        # salinity, pH and alkalinity all move, with a fish's limits: at the readings' 0.001 resolution (the worst case:
        # every frame a different water) and at the parameters' decimals, as the replay reads a sensor's value.
        waters = []
        for slot in range(frames):
            row = [minutes.get((index % len(page), slot)) for index in range(4)]
            if None in row:
                waters.append(None)
                continue
            temperature, salinity, ph, alkalinity = (value for _ts, value in row)
            waters.append({'temperature_c': temperature, 'salinity_ppt': 25 + 5 * (salinity - 10),
                           'ph': 7 + (ph - 10) / 5, 'alkalinity_mg_l': 100 + 10 * (alkalinity - 10), 'tan_mg_l': 0.5,
                           'oxygen_mg_l': 9.0})
        diagrams = [self.diagrams(waters), self.diagrams(
            [None if water is None else {code: float(as_parameter(code, value)) for code, value in water.items()}
             for water in waters])]
        drawn = sum(water is not None for water in waters)
        began = time.monotonic()
        read.latest(range(FIRST, last + 1))
        latest_ms = (time.monotonic() - began) * 1000
        self.stdout.write(f'written: {written} rows in {seconds:.1f} s')
        self.stdout.write(f'raw rows: {raw}')
        self.stdout.write(f'hour rollup rows: {hours}')
        self.stdout.write(f'chart of one channel over the span: {span_buckets} buckets of {span_width} in {span_ms:.0f} ms')
        self.stdout.write(f'{min(channels, 10)} channels over seven days: {week_buckets} buckets of 15 min from the '
                          f'readings in {week_ms:.0f} ms')
        self.stdout.write(f'replay of seven days hourly: {hourly} frames x {len(replay)} channels, {len(values)} '
                          f'values in one query in {replay_ms:.0f} ms')
        self.stdout.write(f'replay page of {frames} frames at one minute: {len(page)} channels, {len(minutes)} values '
                          f'in one query in {page_ms:.0f} ms')
        (raw_ms, raw_count, raw_size), (shown_ms, shown_count, shown_size) = diagrams
        self.stdout.write(f'diagrams of {frames} frames at one minute: {drawn} frames with a diagram; at the readings\' '
                          f'resolution {raw_count} different in {raw_ms:.0f} ms ({raw_ms / max(drawn, 1):.2f} ms a frame), '
                          f'{raw_size / 1e6:.1f} MB as JSON; at the parameters\' decimals {shown_count} different in '
                          f'{shown_ms:.0f} ms ({shown_ms / max(drawn, 1):.2f} ms a frame), {shown_size / 1e6:.1f} MB as JSON')
        self.stdout.write(f'latest of {channels} channels: {latest_ms:.0f} ms')

    @staticmethod
    def chart(channel_no, start, end, interval, zone, width=None):
        """(ms, buckets, width) of one channel's chart query, as sensors/read.py runs it."""
        width = width or read.width_for(start, end)
        segment = read.Segment(channel_no, start, end, 'primary', read.SENSOR, interval * 3, False, False)
        began = time.monotonic()
        found = read.chart_rows(segment, width, read.tier_of(width), zone)
        return (time.monotonic() - began) * 1000, len(found), width

    @staticmethod
    def diagrams(waters):
        """(ms, different figures, JSON bytes) of a page's diagrams as the replay works them out (None: no diagram)."""
        began = time.monotonic()
        figures, _indexes = read.page_figures(
            [None if water is None else read.frame_analysis(water, LIMITS)[0] for water in waters])
        return (time.monotonic() - began) * 1000, len(figures), len(json.dumps(figures))

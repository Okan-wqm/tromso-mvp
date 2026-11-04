"""Synthetic sensor readings for the plan's storage and read-time figures (docs: README, Sensors, Measured figures): writes
`--channels` channels (numbers from 1,000,000 on, bound to nothing, so no page shows them) for `--days` days, one stored
row every `--interval` seconds (a reduced channel's row stands for its messages), then prints the raw rows, the minute
rollup rows against them, the time of a chart of one channel over the whole span and of the latest values. It writes into
the database it is pointed at: it refuses to run unless `--confirm-database` names that database. Never run it on a
farm's database; use a copy or a test database, and drop the rows after (`--drop`)."""
import time
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.utils import timezone

from sensors import read

FIRST = 1_000_000


class Command(BaseCommand):
    help = 'Writes synthetic sensor readings into a confirmed database and prints storage and read figures.'

    def add_arguments(self, parser):
        parser.add_argument('--channels', type=int, default=20)
        parser.add_argument('--days', type=int, default=730)
        parser.add_argument('--interval', type=int, default=60, help='Seconds between two stored rows of a channel.')
        parser.add_argument('--confirm-database', default='', help='The name of the database written to.')
        parser.add_argument('--drop', action='store_true', help='Delete the synthetic rows first.')

    def handle(self, *args, **options):
        name = connection.settings_dict['NAME']
        if options['confirm_database'] != name:
            raise CommandError(f'This writes synthetic readings into "{name}": confirm with --confirm-database {name}.')
        channels, days, interval = options['channels'], options['days'], options['interval']
        if channels < 1 or days < 1 or interval < 1:
            raise CommandError('Channels, days and the interval are at least 1.')
        end = timezone.now().replace(second=0, microsecond=0)
        start = end - timedelta(days=days)
        last = FIRST + channels - 1
        with connection.cursor() as cursor:
            if options['drop']:
                cursor.execute('DELETE FROM sensors_reading WHERE channel_no BETWEEN %s AND %s', [FIRST, last])
            began = time.monotonic()
            # A slow wave with noise; each row stands for `interval` one-second messages around it.
            cursor.execute(
                'INSERT INTO sensors_reading (channel_no, ts, value, n, run_sum, run_min, run_max) '
                'SELECT c, t, v, n, CASE WHEN n > 1 THEN v * n END, CASE WHEN n > 1 THEN v - 0.05 END, '
                'CASE WHEN n > 1 THEN v + 0.05 END FROM ('
                '  SELECT c, t, round((10 + sin(extract(epoch FROM t) / 86400.0 * 6.283) + random() * 0.1)::numeric, 3)'
                '::float8 AS v, %s AS n'
                '  FROM generate_series(%s::int, %s::int) c, generate_series(%s::timestamptz, %s::timestamptz - '
                "interval '1 second', make_interval(secs => %s)) t) s ON CONFLICT DO NOTHING",
                [interval, FIRST, last, start, end, interval])
            written = cursor.rowcount
            seconds = time.monotonic() - began
            cursor.execute('SELECT count(*) FROM sensors_reading WHERE channel_no BETWEEN %s AND %s', [FIRST, last])
            raw = cursor.fetchone()[0]
            cursor.execute('SELECT count(*) FROM sensors_rollup_1m WHERE channel_no BETWEEN %s AND %s', [FIRST, last])
            minute = cursor.fetchone()[0]
        segment = read.Segment(FIRST, start, end, 'primary', read.SENSOR, interval * 3, False, False)
        width = read.width_for(start, end)
        began = time.monotonic()
        buckets = read._query(segment, width, read.tier_of(width), timezone.get_default_timezone())
        chart_ms = (time.monotonic() - began) * 1000
        began = time.monotonic()
        read.latest(range(FIRST, last + 1))
        latest_ms = (time.monotonic() - began) * 1000
        self.stdout.write(f'written: {written} rows in {seconds:.1f} s')
        self.stdout.write(f'raw rows: {raw}')
        self.stdout.write(f'minute rollup rows: {minute}')
        self.stdout.write(f'rollup / raw: {minute / raw:.2%}' if raw else 'rollup / raw: no rows')
        self.stdout.write(f'chart of one channel: {len(buckets)} buckets of {width} in {chart_ms:.0f} ms')
        self.stdout.write(f'latest of {channels} channels: {latest_ms:.0f} ms')

"""Synthetic sensor readings for the plan's storage and read-time figures (docs: README, Sensors, Measured figures): writes
`--channels` channels (numbers from 1,000,000 on, bound to nothing, so no page shows them) for `--days` days, one stored
row every `--interval` seconds (a reduced channel's row stands for its messages), then prints the raw rows, the hour
rollup rows, the time of a chart of one channel over the whole span (local days from the hour rollup), of ten channels
over seven days in 15-minute buckets of the readings themselves, and of the latest values. It refuses a range that already
holds rows (TimescaleDB 2.17.2 loses rows of a multi-row insert that meets a row in a compressed chunk). It writes into
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
            cursor.execute('SELECT count(*) FROM sensors_reading WHERE channel_no BETWEEN %s AND %s', [FIRST, last])
            if cursor.fetchone()[0]:
                # Never write over rows: one multi-row insert meeting a row in a compressed chunk loses the rest of its
                # rows silently (TimescaleDB 2.17.2), so the range must be empty (--drop deletes the synthetic rows).
                raise CommandError('The synthetic channels already hold readings: run with --drop to delete them first.')
            began = time.monotonic()
            # A slow wave with noise; each row stands for `interval` one-second messages around it. No ON CONFLICT: the
            # range is empty, and a conflict would stop the command instead of dropping rows unseen.
            cursor.execute(
                'INSERT INTO sensors_reading (channel_no, ts, value, n, run_sum, run_min, run_max) '
                'SELECT c, t, v, n, CASE WHEN n > 1 THEN v * n END, CASE WHEN n > 1 THEN v - 0.05 END, '
                'CASE WHEN n > 1 THEN v + 0.05 END FROM ('
                '  SELECT c, t, round((10 + sin(extract(epoch FROM t) / 86400.0 * 6.283) + random() * 0.1)::numeric, 3)'
                '::float8 AS v, %s AS n'
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
        began = time.monotonic()
        read.latest(range(FIRST, last + 1))
        latest_ms = (time.monotonic() - began) * 1000
        self.stdout.write(f'written: {written} rows in {seconds:.1f} s')
        self.stdout.write(f'raw rows: {raw}')
        self.stdout.write(f'hour rollup rows: {hours}')
        self.stdout.write(f'chart of one channel over the span: {span_buckets} buckets of {span_width} in {span_ms:.0f} ms')
        self.stdout.write(f'{min(channels, 10)} channels over seven days: {week_buckets} buckets of 15 min from the '
                          f'readings in {week_ms:.0f} ms')
        self.stdout.write(f'latest of {channels} channels: {latest_ms:.0f} ms')

    @staticmethod
    def chart(channel_no, start, end, interval, zone, width=None):
        """(ms, buckets, width) of one channel's chart query, as sensors/read.py runs it."""
        width = width or read.width_for(start, end)
        segment = read.Segment(channel_no, start, end, 'primary', read.SENSOR, interval * 3, False, False)
        began = time.monotonic()
        found = read.chart_rows(segment, width, read.tier_of(width), zone)
        return (time.monotonic() - began) * 1000, len(found), width

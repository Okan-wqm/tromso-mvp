"""The TimescaleDB objects of the sensors, checked in the catalogue and by behaviour (spikes S0b to S0d, kept as tests):
the readings hypertable with its chunk interval, compression and retention; a managed model with a composite primary
key read and written through the ORM; a late row and a redelivered row into a compressed chunk; the licence of the
pinned image's build; the hour continuous aggregate over the readings (the plan's gate removed the minute tier) with
its policies, exact against a direct computation over the unreduced stream, bad rows left out; and a refresh after raw
chunks are dropped keeps the rollups."""
import json
import random
from datetime import datetime, timedelta, timezone as tz

from django.db import IntegrityError, connection, transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from sensors import quality
from sensors.models import Contract, Reading

from . import one, rows

START = datetime(2026, 10, 1, tzinfo=tz.utc)
# A continuous aggregate's jobs: TimescaleDB 2.32.1 lists them under the aggregate's own view name.
AGGREGATE_JOBS = ("FROM timescaledb_information.jobs j JOIN timescaledb_information.continuous_aggregates c "
                  "ON j.hypertable_name = c.view_name ")
# The one TimescaleDB release everything runs on, pinned by digest in the same image line everywhere a database starts.
PINNED = 'timescale/timescaledb:2.32.1-pg17@sha256:2f5e6969faa5cd7f4b075d65f124e30dc50d456b7b807e5c1acd9d51ba7df51c'


def insert(rows_):
    """(channel_no, ts, value, n, quality, run_sum, run_min, run_max) rows, as the ingest writes them: one row per
    statement (CompressedChunkInsertTests)."""
    with connection.cursor() as cursor:
        for row in rows_:
            cursor.execute(
                'INSERT INTO sensors_reading (channel_no, ts, value, n, quality, run_sum, run_min, run_max) '
                'VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING', row)


def stream(channel_no, start, count, step=timedelta(seconds=1), seed=1):
    """A channel's unreduced messages: (ts, value), one per `step`, with plateaus and noise."""
    generator = random.Random(seed)
    value, found = 10.0, []
    for number in range(count):
        if generator.random() < 0.3:
            value = round(value + generator.uniform(-0.3, 0.3), 2)
        found.append((start + number * step, value))
    return found


def reduce(channel_no, messages, seed=2, bad_every=0):
    """Stored rows of the messages, as the contract describes them: each row closes a run of messages (random length,
    never across a minute border so the test also covers runs inside a bucket) and stands for them; every `bad_every`-th
    row is flagged bad (out of range)."""
    generator = random.Random(seed)
    stored, run = [], []
    for index, (moment, value) in enumerate(messages):
        run.append((moment, value))
        last = index == len(messages) - 1
        crosses = not last and messages[index + 1][0].replace(second=0, microsecond=0) != moment.replace(second=0,
                                                                                                        microsecond=0)
        if last or crosses or generator.random() < 0.4:
            values = [item[1] for item in run]
            bad = bool(bad_every) and len(stored) % bad_every == bad_every - 1
            flags = quality.OUT_OF_RANGE if bad else 0
            if len(run) == 1:
                stored.append((channel_no, moment, value, 1, flags, None, None, None))
            else:
                stored.append((channel_no, moment, value, len(run), flags, sum(values), min(values), max(values)))
            run = []
    return stored


def expected(stored, width):
    """{bucket start: (n, sum, min, max, last)} over the clean rows, worked out directly."""
    found = {}
    for channel_no, moment, value, n, flags, run_sum, run_min, run_max in stored:
        if quality.is_bad(flags):
            continue
        seconds = int(width.total_seconds())
        bucket = datetime.fromtimestamp(int(moment.timestamp()) // seconds * seconds, tz.utc)
        n0, s0, lo, hi, last = found.get(bucket, (0, 0.0, None, None, None))
        lo_v, hi_v = (run_min, run_max) if n > 1 else (value, value)
        found[bucket] = (n0 + n, s0 + (run_sum if n > 1 else value), lo_v if lo is None else min(lo, lo_v),
                         hi_v if hi is None else max(hi, hi_v), (moment, value) if last is None or moment > last[0]
                         else last)
    return {bucket: (n, total, lo, hi, last[1]) for bucket, (n, total, lo, hi, last) in found.items()}


def rollup(view, channel_no):
    return {bucket: (n, total, lo, hi, last) for bucket, n, total, lo, hi, last in rows(
        f'SELECT bucket, n, sum_v, vmin, vmax, vlast FROM {view} WHERE channel_no = %s ORDER BY bucket', [channel_no])}


class HypertableTests(TestCase):
    def test_the_readings_are_a_hypertable_in_7_day_chunks(self):
        self.assertEqual(one("SELECT time_interval FROM timescaledb_information.dimensions "
                             "WHERE hypertable_name = 'sensors_reading' AND column_name = 'ts'"), timedelta(days=7))

    def test_compression_is_per_channel_newest_first(self):
        settings = rows("SELECT attname, segmentby_column_index, orderby_column_index, orderby_asc "
                        "FROM timescaledb_information.compression_settings WHERE hypertable_name = 'sensors_reading' "
                        "ORDER BY attname")
        self.assertEqual(settings, [('channel_no', 1, None, None), ('ts', None, 1, False)])

    def test_the_policies_compress_after_14_days_and_drop_after_the_contracts_retention(self):
        jobs = {name: json.loads(config) for name, config in rows(
            "SELECT proc_name, config FROM timescaledb_information.jobs WHERE hypertable_name = 'sensors_reading'")}
        self.assertEqual(jobs['policy_compression']['compress_after'], '14 days')
        retention_days = Contract.objects.get().retention_days
        self.assertEqual(jobs['policy_retention']['drop_after'], f'{retention_days} days')

    def test_the_licence_of_the_build_is_timescales_community_licence(self):
        # Compression, continuous aggregates and policies are TSL features: the -oss build lacks them.
        self.assertEqual(one('SHOW timescaledb.license'), 'timescale')
        self.assertEqual(one("SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'"), '2.32.1')
        # one image everywhere a database starts: development, the tests, CI, production, the ingest's own scripts
        from pathlib import Path

        from django.conf import settings
        base = Path(settings.BASE_DIR)
        for path in ('docker-compose.yml', 'scripts/test.sh', '.github/workflows/ci.yml', 'deploy/db/Dockerfile',
                     'sensors-ingest/tests/run.sh', 'sensors-ingest/e2e/run.sh', 'sensors-ingest/bench/run.sh',
                     'sensors-ingest/bench/multisource.sh', 'sensors-ingest/simulator/farm-check.sh',
                     'sensors-ingest/simulator/farm-config.sh'):
            with self.subTest(path=path):
                text = (base / path).read_text(encoding='utf-8')
                self.assertIn(PINNED, text)
                self.assertNotRegex(text.replace(PINNED, ''), r'timescale/timescaledb:[0-9]')

    def test_the_orm_writes_and_reads_a_reading_by_its_composite_key(self):
        moment = START + timedelta(minutes=5)
        Reading.objects.create(channel_no=7, ts=moment, value=9.5)
        reading = Reading.objects.get(pk=(7, moment))
        self.assertEqual((reading.value, reading.n, reading.quality, reading.run_sum), (9.5, 1, 0, None))

    def test_a_redelivered_row_is_stored_once(self):
        row = (7, START, 9.5, 1, 0, None, None, None)
        insert([row, row])
        insert([(7, START, 9.9, 1, 0, None, None, None)])
        self.assertEqual(rows('SELECT value FROM sensors_reading WHERE channel_no = 7'), [(9.5,)])

    def test_the_rows_checks_hold_for_any_writer(self):
        for constraint, row in (
                ('chk_sensors_reading_value', (7, START, float('inf'), 1, 0, None, None, None)),
                ('chk_sensors_reading_value', (7, START, float('nan'), 1, 0, None, None, None)),
                ('chk_sensors_reading_quality', (7, START, 1.0, 1, 256, None, None, None)),
                ('chk_sensors_reading_run', (7, START, 1.0, 0, 0, None, None, None)),
                ('chk_sensors_reading_run', (7, START, 1.0, 1, 0, 1.0, 1.0, 1.0)),
                ('chk_sensors_reading_run', (7, START, 1.0, 2, 0, None, None, None)),
                ('chk_sensors_reading_run', (7, START, 1.0, 2, 0, 2.0, 1.0, None)),
                ('chk_sensors_reading_run', (7, START, 5.0, 2, 0, 6.0, 1.0, 4.0)),
                ('chk_sensors_reading_run', (7, START, 1.0, 2, 0, float('inf'), 1.0, 1.0))):
            with self.subTest(row=row):
                with self.assertRaises(IntegrityError) as caught, transaction.atomic():
                    insert([row])
                self.assertEqual(caught.exception.__cause__.diag.constraint_name, constraint)

    def test_late_and_redelivered_rows_reach_a_compressed_chunk(self):
        old = datetime(2026, 9, 1, 12, tzinfo=tz.utc)
        insert([(7, old, 1.0, 1, 0, None, None, None), (7, old + timedelta(hours=1), 2.0, 1, 0, None, None, None)])
        chunk = one("SELECT chunk_schema || '.' || chunk_name FROM timescaledb_information.chunks "
                    "WHERE hypertable_name = 'sensors_reading' AND range_start <= %s AND range_end > %s", [old, old])
        one('SELECT compress_chunk(%s::regclass)', [chunk])
        self.assertTrue(one("SELECT is_compressed FROM timescaledb_information.chunks WHERE chunk_schema || '.' || "
                            "chunk_name = %s", [chunk]))
        insert([(7, old, 99.0, 1, 0, None, None, None),                           # redelivered: stays as it was
                (7, old + timedelta(minutes=30), 1.5, 1, quality.LATE, None, None, None)])   # late: added
        self.assertEqual(rows('SELECT ts, value FROM sensors_reading WHERE channel_no = 7 ORDER BY ts'),
                         [(old, 1.0), (old + timedelta(minutes=30), 1.5), (old + timedelta(hours=1), 2.0)])


class RollupCatalogueTests(TestCase):
    """The plan's gate 2.4 triggered (a minute rollup measured at 100 % of the raw rows, its two-year refresh 58 min): one
    real-time aggregate, the hour, built straight from the readings; no minute tier."""

    def test_one_real_time_aggregate_the_hour_from_the_readings(self):
        found = dict(rows("SELECT view_name, materialized_only FROM timescaledb_information.continuous_aggregates "
                          "WHERE view_name LIKE 'sensors_rollup_%%'"))
        self.assertEqual(found, {'sensors_rollup_1h': False})
        self.assertEqual(one("SELECT hypertable_name FROM timescaledb_information.continuous_aggregates "
                             "WHERE view_name = 'sensors_rollup_1h'"), 'sensors_reading')

    def test_the_definition_takes_clean_rows_only_with_the_bad_mask_of_the_quality_module(self):
        definition = one("SELECT view_definition FROM timescaledb_information.continuous_aggregates "
                         "WHERE view_name = 'sensors_rollup_1h'")
        self.assertIn(f'& {quality.BAD_MASK}) = 0', definition)

    def jobs(self, view):
        found = {name: json.loads(config) for name, config in rows(
            f"SELECT j.proc_name, j.config {AGGREGATE_JOBS}WHERE c.view_name = %s", [view])}
        self.assertIn('policy_refresh_continuous_aggregate', found,
                      rows('SELECT job_id, proc_name, hypertable_schema, hypertable_name, config::text '
                           'FROM timescaledb_information.jobs ORDER BY job_id'))
        return found

    def test_the_policies(self):
        hour = self.jobs('sensors_rollup_1h')
        # The refresh window starts a while back, not at NULL: TimescaleDB refuses a compression policy on an aggregate
        # whose refresh window reaches the compressed region. Older late rows are the daily job's (below).
        refresh = hour['policy_refresh_continuous_aggregate']
        self.assertEqual((refresh['start_offset'], refresh['end_offset']), ('75 days', '01:00:00'))
        self.assertEqual(hour['policy_compression']['compress_after'], '90 days')
        self.assertNotIn('policy_retention', hour)
        self.assertEqual(one(f"SELECT j.schedule_interval {AGGREGATE_JOBS}"
                             "WHERE j.proc_name = 'policy_refresh_continuous_aggregate' "
                             "AND c.view_name = 'sensors_rollup_1h'"), timedelta(hours=1))

    def test_a_daily_job_refreshes_what_lies_before_the_policys_window(self):
        self.assertEqual(rows("SELECT proc_name, schedule_interval FROM timescaledb_information.jobs "
                              "WHERE proc_name = 'sensors_refresh_late'"), [('sensors_refresh_late', timedelta(days=1))])


class RollupValueTests(TestCase):
    """Real-time aggregation (materialized_only = false): what is not refreshed yet is worked out from the readings on
    read, so these tests see the rows they insert without a refresh (which cannot run in a transaction)."""

    def test_the_hour_equals_a_direct_computation_over_the_unreduced_stream(self):
        messages = stream(11, START, 3 * 3600)                   # three hours of one message a second
        stored = reduce(11, messages)
        insert(stored)
        found, wanted = rollup('sensors_rollup_1h', 11), expected(stored, timedelta(hours=1))
        self.assertEqual(found.keys(), wanted.keys())
        for bucket, (n, total, lo, hi, last) in wanted.items():
            self.assertEqual(found[bucket][0], n)
            self.assertAlmostEqual(found[bucket][1], total, places=6)
            self.assertEqual(found[bucket][2:], (lo, hi, last))
        # and the messages themselves: every message counted once, the mean exact
        self.assertEqual(sum(n for n, *_rest in wanted.values()), len(messages))
        self.assertAlmostEqual(sum(total for _n, total, *_rest in wanted.values()), sum(v for _t, v in messages), places=6)

    def test_bad_rows_are_left_out(self):
        stored = reduce(12, stream(12, START, 1800, seed=5), bad_every=4)
        insert(stored)
        wanted = expected(stored, timedelta(hours=1))
        self.assertEqual(sum(found[0] for found in rollup('sensors_rollup_1h', 12).values()),
                         sum(n for n, *_rest in wanted.values()))

    def test_a_shuffled_late_stream_gives_the_same_rollups(self):
        stored = reduce(13, stream(13, START, 3600, seed=9))
        shuffled = stored[:]
        random.Random(3).shuffle(shuffled)
        insert(shuffled)
        for bucket, values in expected(stored, timedelta(hours=1)).items():
            self.assertEqual(rollup('sensors_rollup_1h', 13)[bucket][0], values[0])


class CompressedChunkInsertTests(TestCase):
    """In ONE multi-row INSERT ... ON CONFLICT DO NOTHING, a row conflicting inside a compressed chunk is skipped and the
    rest of the statement is stored (TimescaleDB 2.32.1; 2.17.2 silently dropped the rest, found by the ingest,
    CONTRACT-REQUESTS 13, which is why every writer of sensors_reading writes one row per statement). This test pins the
    behaviour, so a release that changes it shows here."""

    def test_a_conflict_in_a_compressed_chunk_keeps_the_rest_of_the_statement(self):
        old = datetime(2026, 9, 1, 12, tzinfo=tz.utc)
        insert([(31, old, 1.0, 1, 0, None, None, None)])
        chunk = one("SELECT chunk_schema || '.' || chunk_name FROM timescaledb_information.chunks "
                    "WHERE hypertable_name = 'sensors_reading' AND range_start <= %s AND range_end > %s", [old, old])
        one('SELECT compress_chunk(%s::regclass)', [chunk])
        recent = timezone.now().replace(microsecond=0)
        with connection.cursor() as cursor:
            cursor.execute('INSERT INTO sensors_reading (channel_no, ts, value) VALUES (31, %s, 9.0), (31, %s, 2.0) '
                           'ON CONFLICT DO NOTHING', [old, recent])
        self.assertEqual(rows('SELECT value FROM sensors_reading WHERE channel_no = 31 AND ts = %s', [old]), [(1.0,)])
        self.assertEqual(rows('SELECT value FROM sensors_reading WHERE channel_no = 31 AND ts = %s', [recent]), [(2.0,)])


class RollupRefreshTests(TransactionTestCase):
    """What only a committed refresh shows: a late row in a refreshed region is taken in by the job that covers it (the
    hour policy for the last 75 days, the daily job before that), and dropping raw chunks keeps the rollup."""
    serialized_rollback = True

    def refresh(self, view):
        with connection.cursor() as cursor:
            cursor.execute(f"CALL refresh_continuous_aggregate('{view}', NULL, NULL)")

    def run_job(self, name, view=None):
        """Runs a job now, as the scheduler would: a refresh policy of `view`, or the job of procedure `name`."""
        sql = (f"SELECT j.job_id {AGGREGATE_JOBS}WHERE j.proc_name = %s AND c.view_name = %s"
               if view else "SELECT job_id FROM timescaledb_information.jobs WHERE proc_name = %s")
        job = one(sql, [name, view] if view else [name])
        self.assertIsNotNone(job, rows('SELECT job_id, proc_name, hypertable_schema, hypertable_name '
                                       'FROM timescaledb_information.jobs ORDER BY job_id'))
        with connection.cursor() as cursor:
            cursor.execute('CALL run_job(%s)', [job])

    def hour(self, channel_no):
        return rows('SELECT n, sum_v, vmin, vmax, vlast FROM sensors_rollup_1h WHERE channel_no = %s', [channel_no])

    def test_a_recent_late_row_is_taken_in_by_the_hour_policy(self):
        recent = (timezone.now() - timedelta(days=2)).replace(minute=0, second=0, microsecond=0)
        insert([(22, recent, 1.0, 1, 0, None, None, None), (22, recent + timedelta(minutes=30), 3.0, 1, 0, None, None, None)])
        self.refresh('sensors_rollup_1h')
        insert([(22, recent + timedelta(minutes=10), 5.0, 1, quality.LATE, None, None, None)])
        self.assertEqual(self.hour(22), [(2, 4.0, 1.0, 3.0, 3.0)])        # below the watermark: as materialized
        self.run_job('policy_refresh_continuous_aggregate', 'sensors_rollup_1h')
        self.assertEqual(self.hour(22), [(3, 9.0, 1.0, 5.0, 3.0)])

    def test_an_old_late_row_is_taken_in_by_the_daily_job_and_dropped_raw_keeps_its_rollup(self):
        # Before the hour policy's 75 days and inside the late job's reach (the contract's late limit, 728 days, and a
        # day), both counted back from the DATABASE's now(): no test clock moves them. It was 06.01.2025, which the late
        # job stops reaching on 05.01.2027.
        early = one("SELECT date_trunc('hour', now()) - INTERVAL '400 days'")
        insert([(21, early, 1.0, 1, 0, None, None, None), (21, early + timedelta(minutes=30), 3.0, 1, 0, None, None, None)])
        self.refresh('sensors_rollup_1h')
        insert([(21, early + timedelta(minutes=10), 5.0, 1, quality.LATE, None, None, None)])
        self.run_job('policy_refresh_continuous_aggregate', 'sensors_rollup_1h')     # outside its 75 days: no change
        self.assertEqual(self.hour(21), [(2, 4.0, 1.0, 3.0, 3.0)])
        self.run_job('sensors_refresh_late')
        self.assertEqual(self.hour(21), [(3, 9.0, 1.0, 5.0, 3.0)])
        one("SELECT count(*) FROM drop_chunks('sensors_reading', older_than => %s)", [early + timedelta(days=30)])
        self.assertEqual(one('SELECT count(*) FROM sensors_reading WHERE channel_no = 21'), 0)
        # Dropping raw chunks invalidates their region (TimescaleDB 2.17): a refresh over it would empty the rollup. No
        # job reaches it: the policy looks 75 days back, the late job no further than the late limit and a day.
        self.run_job('policy_refresh_continuous_aggregate', 'sensors_rollup_1h')
        with connection.cursor() as cursor:                      # the drop as if it happened two years on
            cursor.execute('UPDATE sensors_contract SET late_limit_days = 1, retention_days = 3')
        self.run_job('sensors_refresh_late')
        self.assertEqual(rows('SELECT n, sum_v FROM sensors_rollup_1h WHERE channel_no = 21'), [(3, 9.0)])

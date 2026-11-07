"""The cold tier of the sensor readings (owner amendments D1, D2; sensors/tiers.py): a whole chunk of `sensors_reading`
is exported to a Parquet file in the archive directory (core.archive), verified row by row against the database and
by the file's checksum, and only then dropped WHOLE (never a row delete); the hourly rollup keeps the chunk's hours;
the archive says which ranges it holds; one chunk is restored into a table of its own.

TransactionTestCase: the rollup is refreshed outside a transaction block, as TimescaleDB requires."""
import shutil
import tempfile
from datetime import datetime, timedelta, timezone as tz
from pathlib import Path

from django.db import connection
from django.test import SimpleTestCase, TransactionTestCase, override_settings

from core import archive

from .. import tiers
from ..models import ArchivedChunk

WEEK = timedelta(days=7)


def chunk_at(day):
    for chunk in tiers.chunks():
        if chunk.start <= day < chunk.end:
            return chunk
    return None


class TierCase(TransactionTestCase):
    channel = 1_500_000
    serialized_rollback = True        # the contract row the migrations seed

    def setUp(self):
        with connection.cursor() as cursor:   # late readings are taken for 30 days here (728 by default)
            cursor.execute('UPDATE sensors_contract SET late_limit_days = 30')
        self.root = Path(tempfile.mkdtemp(prefix='cold-'))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.target = archive.LocalDirectory(self.root)
        # 500 days back: older than the late limit and the rollup's refresh reach, younger than the retention.
        self.day = (datetime.now(tz.utc) - timedelta(days=500)).replace(hour=0, minute=0, second=0, microsecond=0)
        self.write(self.channel, self.day, rows=3 * 24 * 60)

    def write(self, channel, start, rows, every=60):
        with connection.cursor() as cursor:
            # every tenth row stands for a run of 5 messages (run columns set); values with full float precision
            cursor.execute(
                "INSERT INTO sensors_reading (channel_no, ts, value, n, quality, run_sum, run_min, run_max) "
                "SELECT %s, %s::timestamptz + make_interval(secs => i * %s), v, n, 0, "
                "CASE WHEN n > 1 THEN v * n END, CASE WHEN n > 1 THEN v - 0.25 END, CASE WHEN n > 1 THEN v + 0.25 END "
                "FROM (SELECT i, 10 + sin(i / 97.0) / 3.0 AS v, CASE WHEN i %% 10 = 0 THEN 5 ELSE 1 END AS n "
                "FROM generate_series(0, %s - 1) i) s", [channel, start, every, rows])

    def rows(self, table, start, end, channel=None):
        with connection.cursor() as cursor:
            cursor.execute(f'SELECT channel_no, ts, value, n, quality, run_sum, run_min, run_max FROM {table} '
                           'WHERE ts >= %s AND ts < %s AND (%s::int IS NULL OR channel_no = %s) ORDER BY channel_no, ts',
                           [start, end, channel, channel])
            return cursor.fetchall()

    def rollup(self, chunk):
        with connection.cursor() as cursor:
            cursor.execute('SELECT channel_no, bucket, n FROM sensors_rollup_1h WHERE bucket >= %s AND bucket < %s '
                           'ORDER BY 1, 2', [chunk.start, chunk.end])
            return cursor.fetchall()

    def compress(self, chunk):
        with connection.cursor() as cursor:
            cursor.execute('SELECT compress_chunk(%s, if_not_compressed => true)', [chunk.qualified])


class RoundTripTests(TierCase):
    def test_export_verify_drop_and_restore_one_chunk(self):
        chunk = chunk_at(self.day)
        self.compress(chunk)                                   # a warm chunk: compressed in the database
        before = self.rows('sensors_reading', chunk.start, chunk.end)
        tiers.refresh_rollup(chunk)
        hours = self.rollup(chunk)
        self.assertTrue(hours)

        record = tiers.export(chunk, self.target)
        self.assertEqual((record.rows, record.state), (len(before), ArchivedChunk.State.EXPORTED))
        self.assertTrue((self.root / record.path).is_file())
        self.assertEqual(len(record.sha256), 64)
        tiers.verify(record, self.target)
        record.refresh_from_db()
        self.assertEqual(record.state, ArchivedChunk.State.VERIFIED)

        tiers.drop(record, self.target, cold_before=datetime.now(tz.utc) - timedelta(days=100))
        record.refresh_from_db()
        self.assertEqual(record.state, ArchivedChunk.State.DROPPED)
        self.assertIsNone(chunk_at(self.day))                  # the whole chunk is gone, not its rows
        self.assertEqual(self.rows('sensors_reading', chunk.start, chunk.end), [])
        self.assertEqual(self.rollup(chunk), hours)            # the hours stay in the database for ever

        with connection.cursor() as cursor:
            cursor.execute('CREATE TABLE restored (LIKE sensors_reading INCLUDING DEFAULTS)')
        self.assertEqual(tiers.restore(record, self.target, 'restored'), len(before))
        self.assertEqual(self.rows('restored', chunk.start, chunk.end), before)

    def test_the_archive_says_which_part_of_a_range_it_holds(self):
        chunk = chunk_at(self.day)
        tiers.refresh_rollup(chunk)
        record = tiers.export(chunk, self.target)
        tiers.verify(record, self.target)
        tiers.drop(record, self.target, cold_before=datetime.now(tz.utc) - timedelta(days=100))
        found = tiers.archived(self.day - 3 * WEEK, self.day + 3 * WEEK)
        self.assertEqual([(part.start, part.end) for part in found], [(chunk.start, chunk.end)])
        self.assertEqual(tiers.archived(self.day + 3 * WEEK, self.day + 5 * WEEK), [])


class RefusalTests(TierCase):
    def exported(self):
        chunk = chunk_at(self.day)
        tiers.refresh_rollup(chunk)
        record = tiers.export(chunk, self.target)
        tiers.verify(record, self.target)
        return chunk, record

    def assert_refused(self, record, chunk, why, **kwargs):
        with self.assertRaises(tiers.Refused) as caught:
            tiers.drop(record, self.target, cold_before=kwargs.get('cold_before',
                                                                    datetime.now(tz.utc) - timedelta(days=100)))
        self.assertIn(why, str(caught.exception))
        self.assertIsNotNone(chunk_at(self.day))
        record.refresh_from_db()
        self.assertEqual(record.state, ArchivedChunk.State.FAILED)
        self.assertIn(why, record.error)

    def test_a_row_changed_after_the_export_stops_the_drop(self):
        chunk, record = self.exported()
        with connection.cursor() as cursor:
            cursor.execute('UPDATE sensors_reading SET value = value + 1e-9 WHERE channel_no = %s AND ts = %s',
                           [self.channel, self.day + timedelta(hours=5)])
        self.assert_refused(record, chunk, 'differs')

    def test_a_row_added_after_the_export_stops_the_drop(self):
        chunk, record = self.exported()
        self.write(self.channel + 1, self.day, rows=1)
        self.assert_refused(record, chunk, 'differs')

    def test_a_changed_file_stops_the_drop(self):
        chunk, record = self.exported()
        path = self.root / record.path
        data = bytearray(path.read_bytes())
        data[len(data) // 2] ^= 0xFF
        path.write_bytes(bytes(data))
        self.assert_refused(record, chunk, 'checksum')

    def test_a_missing_file_stops_the_drop(self):
        chunk, record = self.exported()
        (self.root / record.path).unlink()
        self.assert_refused(record, chunk, 'missing')

    def test_a_chunk_not_older_than_the_cold_line_is_not_dropped(self):
        chunk, record = self.exported()
        self.assert_refused(record, chunk, 'cold line', cold_before=self.day)

    def test_a_chunk_a_late_reading_may_still_reach_is_not_dropped(self):
        chunk, record = self.exported()
        with connection.cursor() as cursor:
            cursor.execute('UPDATE sensors_contract SET late_limit_days = 600')
        self.assert_refused(record, chunk, 'late limit')

    def test_an_unverified_export_is_not_dropped(self):
        chunk = chunk_at(self.day)
        tiers.refresh_rollup(chunk)
        record = tiers.export(chunk, self.target)
        with self.assertRaises(tiers.Refused):
            tiers.drop(record, self.target, cold_before=datetime.now(tz.utc) - timedelta(days=100))
        self.assertIsNotNone(chunk_at(self.day))

    def test_a_verification_finds_a_row_the_file_lacks(self):
        chunk = chunk_at(self.day)
        tiers.refresh_rollup(chunk)
        record = tiers.export(chunk, self.target)
        self.write(self.channel + 2, self.day + timedelta(hours=1), rows=1)
        with self.assertRaises(tiers.Refused):
            tiers.verify(record, self.target)
        record.refresh_from_db()
        self.assertEqual(record.state, ArchivedChunk.State.FAILED)

    def test_a_chunk_whose_hours_are_not_in_the_rollup_is_not_dropped(self):
        chunk = chunk_at(self.day)
        record = tiers.export(chunk, self.target)              # no refresh: the rollup has not stored its hours
        tiers.verify(record, self.target)
        self.assert_refused(record, chunk, 'rollup')


class ArchiveTargetTests(SimpleTestCase):
    def test_a_file_appears_whole_or_not_at_all(self):
        root = Path(tempfile.mkdtemp(prefix='cold-'))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        target = archive.LocalDirectory(root)

        def broken(path):
            Path(path).write_bytes(b'half')
            raise OSError('disk full')
        with self.assertRaises(OSError):
            target.write('a/b.parquet', broken)
        self.assertFalse(target.exists('a/b.parquet'))
        self.assertEqual([p for p in root.rglob('*') if p.is_file()], [])
        target.write('a/b.parquet', lambda path: Path(path).write_bytes(b'whole'))
        self.assertEqual((root / 'a' / 'b.parquet').read_bytes(), b'whole')
        self.assertEqual(target.sha256('a/b.parquet'), archive.sha256_of(root / 'a' / 'b.parquet'))

    def test_a_path_outside_the_directory_is_refused(self):
        target = archive.LocalDirectory(Path(tempfile.gettempdir()))
        with self.assertRaises(ValueError):
            target.path('../escape.parquet')

    @override_settings(COLD_ARCHIVE_DIR='')
    def test_without_a_directory_the_archive_is_off(self):
        self.assertIsNone(archive.target())

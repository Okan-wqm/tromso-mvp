"""The storage tiers of the sensor readings (owner amendments D1, D2).

- Hot: the newest chunks, raw and uncompressed (writes, late data, live values, replay).
- Warm: older chunks, raw and compressed in the database (the compression policy, sensors migration 0002).
- Cold: chunks older than the cold line, moved out of the database to Parquet files in the archive directory
  (core.archive), WHOLE chunks only: TimescaleDB 2.17 can lose rows of a delete in a compressed chunk, so rows are never
  deleted. The hourly rollup keeps their hours in the database for ever; the raw rows are read from the archive on
  demand (DuckDB) or restored into a table of their own.

A chunk goes cold in three steps, each recorded on its `ArchivedChunk`:
1. export: the chunk's rows, in one consistent snapshot, to a Parquet file written whole; the database works out the
   rows' digest in the same snapshot;
2. verify: every row of the file equals the database's row (all columns, exactly; floats bit for bit), and the
   file's checksum is recorded;
3. drop: under a lock that stops writes to the chunk, the rows' digest equals the export's, the file is there with
   its checksum, the chunk is older than the cold line and than any late reading or rollup refresh can reach, and the
   rollup has stored its hours (no pending invalidation, watermark past the chunk): only then is the chunk dropped.
Any mismatch refuses the drop, marks the record failed with the reason, and leaves the chunk in the database."""
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone as tz

import duckdb
import psycopg
from django.db import connection, transaction
from django.utils import timezone

from .models import ArchivedChunk, Reading

TABLE = 'sensors_reading'
ROLLUP = 'sensors_rollup_1h'
COLUMNS = [field.column for field in Reading._meta.concrete_fields]
# The Parquet type of each column (the database's types, one to one).
TYPES = {'channel_no': 'INTEGER', 'ts': 'TIMESTAMPTZ', 'value': 'DOUBLE', 'n': 'INTEGER', 'quality': 'SMALLINT',
         'run_sum': 'DOUBLE', 'run_min': 'DOUBLE', 'run_max': 'DOUBLE'}
BATCH = 50_000
EPOCH = datetime(1970, 1, 1, tzinfo=tz.utc)
# DuckDB on a shared server: little memory, two threads, spills to the archive's scratch folder.
DUCKDB_MEMORY = '256MB'
US = '(extract(epoch FROM ts) * 1000000)::bigint'


class Refused(Exception):
    """A step that would lose or misplace data was not taken; the reason says why."""


@dataclass(frozen=True)
class Chunk:
    schema: str
    name: str
    start: datetime
    end: datetime
    compressed: bool

    @property
    def qualified(self):
        return f'{self.schema}.{self.name}'


def chunks():
    """The chunks of the readings, oldest first."""
    with connection.cursor() as cursor:
        cursor.execute('SELECT chunk_schema, chunk_name, range_start, range_end, is_compressed '
                       'FROM timescaledb_information.chunks WHERE hypertable_name = %s ORDER BY range_start', [TABLE])
        return [Chunk(*row) for row in cursor.fetchall()]


def _connect():
    """A connection of its own (an export reads in one snapshot, whatever the caller's transaction)."""
    params = connection.get_connection_params()
    keep = {key: params[key] for key in ('dbname', 'user', 'password', 'host', 'port') if params.get(key) is not None}
    return psycopg.connect(**keep)


def _duck(target):
    db = duckdb.connect()
    db.execute(f"SET memory_limit = '{DUCKDB_MEMORY}'")
    db.execute('SET threads = 2')
    db.execute("SET TimeZone = 'UTC'")
    db.execute('SET temp_directory = ?', [str(target.scratch())])
    return db


def _digest_sql():
    """The rows' digest, worked out by the database: their count and the sum of a 64-bit hash of each row's text (in
    UTC, floats in their shortest exact form). A changed, added or removed row changes it."""
    columns = ', '.join(COLUMNS)
    return (f"SELECT count(*), coalesce(sum(hashtextextended(r::text, 0)::numeric), 0) "
            f"FROM (SELECT {columns} FROM {TABLE} WHERE ts >= %s AND ts < %s) r")


def _session(cur):
    cur.execute("SET TimeZone = 'UTC'")
    cur.execute('SET extra_float_digits = 1')
    cur.execute("SET DateStyle = 'ISO, YMD'")


def _name(chunk):
    return f'{TABLE}/{chunk.start:%Y}/{chunk.start:%Y-%m-%dT%H%M}_{chunk.end:%Y-%m-%dT%H%M}.parquet'


def export(chunk, target):
    """Writes the chunk's rows to the archive and records it (state exported). Returns the ArchivedChunk."""
    name = _name(chunk)
    scratch = target.scratch()
    csv_path = scratch / (os.path.basename(name) + '.csv')
    # the time as microseconds since 1970 (UTC): exact, whatever the session's zone and style
    columns = ', '.join(US if column == 'ts' else column for column in COLUMNS)
    with _connect() as pg:
        pg.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
        cur = pg.cursor()
        _session(cur)
        cur.execute(_digest_sql(), [chunk.start, chunk.end])
        rows, total = cur.fetchone()
        try:
            with open(csv_path, 'wb') as out, cur.copy(
                    f'COPY (SELECT {columns} FROM {TABLE} WHERE ts >= %s AND ts < %s ORDER BY channel_no, ts) '
                    'TO STDOUT (FORMAT csv)', [chunk.start, chunk.end]) as copy:
                for data in copy:
                    out.write(data)
            pg.rollback()
            spec = ', '.join(f"'{column}': '{'BIGINT' if column == 'ts' else TYPES[column]}'" for column in COLUMNS)
            shaped = ', '.join('make_timestamp(ts)::TIMESTAMPTZ AS ts' if column == 'ts' else column for column in COLUMNS)

            def produce(path):
                db = _duck(target)
                try:
                    db.execute(f"COPY (SELECT {shaped} FROM read_csv(?, header = false, auto_detect = false, "
                               f"columns = {{{spec}}})) TO '{path}' "
                               f"(FORMAT parquet, COMPRESSION zstd)", [str(csv_path)])
                finally:
                    db.close()
            target.write(name, produce)
        finally:
            if csv_path.exists():
                csv_path.unlink()
    digest = f'{rows}:{total}'
    sha = target.sha256(name)
    now = timezone.now()
    with transaction.atomic():
        ArchivedChunk.objects.filter(table=TABLE, range_start=chunk.start).exclude(
            state=ArchivedChunk.State.FAILED).exclude(state=ArchivedChunk.State.DROPPED).update(
            state=ArchivedChunk.State.FAILED, error='Exported again.')
        record = ArchivedChunk.objects.create(table=TABLE, chunk=chunk.qualified, range_start=chunk.start,
                                              range_end=chunk.end, path=name, rows=rows, sha256=sha, digest=digest,
                                              exported_at=now)
    target.write(name + '.json', lambda path: _manifest(path, record))
    return record


def _manifest(path, record):
    """The file's own description, beside it: the archive reads without the database."""
    with open(path, 'w', encoding='utf-8') as out:
        json.dump({'table': record.table, 'chunk': record.chunk, 'range_start': record.range_start.isoformat(),
                   'range_end': record.range_end.isoformat(), 'rows': record.rows, 'sha256': record.sha256,
                   'digest': record.digest, 'columns': {column: TYPES[column] for column in COLUMNS},
                   'exported_at': record.exported_at.isoformat()}, out, indent=1)


def _fail(record, reason):
    ArchivedChunk.objects.filter(pk=record.pk).update(state=ArchivedChunk.State.FAILED, error=reason)
    raise Refused(reason)


def _file_rows(db, path):
    selected = ', '.join('epoch_us(ts)' if column == 'ts' else column for column in COLUMNS)
    result = db.execute(f"SELECT {selected} FROM read_parquet(?) ORDER BY channel_no, ts", [str(path)])
    while True:
        batch = result.fetchmany(BATCH)
        if not batch:
            return
        yield from batch


def _db_rows(pg, record):
    selected = ', '.join(US if column == 'ts' else column for column in COLUMNS)
    with pg.cursor(name='tier_verify') as cur:
        cur.itersize = BATCH
        cur.execute(f'SELECT {selected} FROM {TABLE} WHERE ts >= %s AND ts < %s ORDER BY channel_no, ts',
                    [record.range_start, record.range_end])
        yield from cur


def verify(record, target):
    """Compares every row of the file with the database's (state verified), or refuses (state failed)."""
    if not target.exists(record.path):
        _fail(record, f'The archive file {record.path} is missing.')
    if target.sha256(record.path) != record.sha256:
        _fail(record, f'The archive file {record.path} does not have its checksum.')
    db = _duck(target)
    count = 0
    try:
        with _connect() as pg:
            pg.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
            file_rows, db_rows = _file_rows(db, target.path(record.path)), _db_rows(pg, record)
            while True:
                left, right = next(file_rows, None), next(db_rows, None)
                if left is None and right is None:
                    break
                if left is None or right is None or tuple(left) != tuple(right):
                    _fail(record, f'Row {count + 1} of the file differs from the database ({left} / {right}).')
                count += 1
            pg.rollback()
    finally:
        db.close()
    if count != record.rows:
        _fail(record, f'The file holds {count} rows, the export counted {record.rows}.')
    ArchivedChunk.objects.filter(pk=record.pk).update(state=ArchivedChunk.State.VERIFIED, verified_at=timezone.now(),
                                                      error='')
    record.refresh_from_db()
    return record


def refresh_rollup(chunk):
    """Stores the rollup's hours of the chunk (outside a transaction block, as TimescaleDB requires)."""
    with connection.cursor() as cursor:
        cursor.execute(f'CALL refresh_continuous_aggregate(%s, %s, %s)', [ROLLUP, chunk.start, chunk.end])


def _rollup_holds(cursor, start, end):
    """Whether the rollup has stored the hours of [start, end): its watermark is past the end and no change of the
    readings in the range waits for a refresh."""
    cursor.execute('SELECT mat_hypertable_id, raw_hypertable_id FROM _timescaledb_catalog.continuous_agg '
                   'WHERE user_view_name = %s', [ROLLUP])
    materialized, raw = cursor.fetchone()
    cursor.execute('SELECT _timescaledb_functions.to_timestamp(_timescaledb_functions.cagg_watermark(%s))',
                   [materialized])
    watermark = cursor.fetchone()[0]
    if watermark is None or watermark < end:
        return False
    low = '_timescaledb_functions.time_to_internal(%s::timestamptz)'
    cursor.execute(
        'SELECT (SELECT count(*) FROM _timescaledb_catalog.continuous_aggs_materialization_invalidation_log '
        f'WHERE materialization_id = %s AND lowest_modified_value < {low} AND greatest_modified_value >= {low}) + '
        '(SELECT count(*) FROM _timescaledb_catalog.continuous_aggs_hypertable_invalidation_log '
        f'WHERE hypertable_id = %s AND lowest_modified_value < {low} AND greatest_modified_value >= {low})',
        [materialized, end, start, raw, end, start])
    return cursor.fetchone()[0] == 0


def refresh_reach():
    """The oldest time a write or a rollup refresh may still touch: a dropped chunk must end before it, since a
    refresh over a dropped region empties the rollup there (TimescaleDB 2.17). The contract's late limit and a day
    (the daily job sensors_refresh_late) and the refresh policy's window, a day more each; no contract row: never."""
    with connection.cursor() as cursor:
        cursor.execute('SELECT late_limit_days FROM sensors_contract WHERE id = 1')
        found = cursor.fetchone()
        cursor.execute("SELECT max((j.config->>'start_offset')::interval) FROM timescaledb_information.jobs j "
                       "JOIN _timescaledb_catalog.continuous_agg c ON (j.config->>'mat_hypertable_id')::int = "
                       "c.mat_hypertable_id WHERE j.proc_name = 'policy_refresh_continuous_aggregate' "
                       "AND c.user_view_name = %s", [ROLLUP])
        window = cursor.fetchone()[0] or timedelta(0)
    if found is None:
        return datetime(1, 1, 1, tzinfo=tz.utc)
    return timezone.now() - max(timedelta(days=found[0] + 2), window + timedelta(days=1))


def drop(record, target, cold_before):
    """Drops the record's chunk from the database after the checks of the module's docstring; refuses otherwise."""
    if record.state != ArchivedChunk.State.VERIFIED:
        raise Refused(f'The chunk is {record.state}, not verified: it is not dropped.')
    if record.range_end > cold_before:
        _fail(record, f'The chunk ends {record.range_end:%Y-%m-%d}, after the cold line {cold_before:%Y-%m-%d}.')
    reach = refresh_reach()
    if record.range_end > reach:
        _fail(record, f'A late reading or the rollup\'s refresh may still reach the chunk (the contract\'s late limit): '
                      f'it ends {record.range_end:%Y-%m-%d}, after {reach:%Y-%m-%d}.')
    if not target.exists(record.path):
        _fail(record, f'The archive file {record.path} is missing.')
    if target.sha256(record.path) != record.sha256:
        _fail(record, f'The archive file {record.path} does not have its checksum.')
    reason = None
    with transaction.atomic():
        with connection.cursor() as cursor:
            current = [chunk for chunk in chunks() if chunk.start == record.range_start and chunk.end == record.range_end]
            if not current:
                reason = 'The chunk is not in the database.'
            else:
                cursor.execute(f'LOCK TABLE {current[0].qualified} IN EXCLUSIVE MODE')
                _session(cursor)
                cursor.execute(_digest_sql(), [record.range_start, record.range_end])
                rows, total = cursor.fetchone()
                if f'{rows}:{total}' != record.digest:
                    reason = f'The chunk\'s rows differ from the export ({rows} rows now, {record.rows} exported).'
                elif not _rollup_holds(cursor, record.range_start, record.range_end):
                    reason = 'The rollup has not stored the chunk\'s hours: refresh it first.'
                else:
                    cursor.execute('SELECT drop_chunks(%s, older_than => %s, newer_than => %s)',
                                   [TABLE, record.range_end, record.range_start])
                    dropped = [name for (name,) in cursor.fetchall()]
                    if dropped != [current[0].qualified]:
                        raise RuntimeError(f'drop_chunks dropped {dropped}, not {current[0].qualified}')
                    ArchivedChunk.objects.filter(pk=record.pk).update(state=ArchivedChunk.State.DROPPED,
                                                                      dropped_at=timezone.now(), error='')
    if reason:
        _fail(record, reason)
    record.refresh_from_db()
    return record


def archived(start, end):
    """The archived (dropped) chunks overlapping [start, end), oldest first: a chart over the range says these
    parts come from the archive."""
    return list(ArchivedChunk.objects.filter(table=TABLE, state=ArchivedChunk.State.DROPPED, range_start__lt=end,
                                             range_end__gt=start).order_by('range_start'))


def restore(record, target, into):
    """Copies the record's rows from the archive into the table `into` (a table shaped like sensors_reading, in this
    database; never the hypertable itself). Returns the number of rows."""
    if not target.exists(record.path) or target.sha256(record.path) != record.sha256:
        raise Refused(f'The archive file {record.path} is missing or does not have its checksum.')
    db = _duck(target)
    count = 0
    try:
        with connection.cursor() as cursor:
            with cursor.cursor.copy(f'COPY {into} ({", ".join(COLUMNS)}) FROM STDIN') as copy:
                for row in _file_rows(db, target.path(record.path)):
                    row = list(row)
                    row[COLUMNS.index('ts')] = EPOCH + timedelta(microseconds=row[COLUMNS.index('ts')])
                    copy.write_row(row)
                    count += 1
    finally:
        db.close()
    if count != record.rows:
        raise Refused(f'The archive gave {count} rows, the record says {record.rows}.')
    return count

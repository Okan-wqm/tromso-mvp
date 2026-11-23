"""Revisions: the proof that a stored figure is still valid (performance plan, section 0; live-data architecture,
stage 3).

`core_rev` holds one counter per (scope, key): ('batch', <id>) moves whenever a stock line, a stock operation's date or
void, or the species of that batch changes. The database moves it, by triggers a migration adds with
`core.operations.TrackRev`; no Python code bumps anything, so raw SQL, `bulk_create`, the admin, a TRUNCATE and a
restore are all covered. A change is noted while the transaction runs and applied at COMMIT, once per key, in sorted key
order (no deadlock between writers; each key's row is locked from the apply to the end of the COMMIT, which on a big
operation is the rest of its commit, a tenth of a second or so); a transaction rolled back moves nothing.

Besides the counter a row holds `dirty_from`, the earliest day changed since the last build, and `dirty_epoch`, the
revision of that build. A figure stored with the revision it was built from (`built_rev`, read BEFORE the data) is
valid iff `built_rev == rev`, or `built_rev >= dirty_epoch` and nothing changed on or before the day it covers
(`dirty_from` is NULL or later). A change without a day (a table-level scope, a water sample) counts for the whole
history (EVERYTHING), so for such a scope only `built_rev == rev` proves anything. A builder ends with `mark_built` (a
compare-and-set: refused when the revision moved while it read). A key with no row is unknown: never valid.

What is tracked (TRACKED) is every input of the water's judgement (farm/water/read.py `latest`, the sensors' provider),
for the stored water the plan's B3 builds:
- the samples, per sampling point (WATER_POINT: a sample written, changed, moved to another point, voided or restored);
- the stock ledger per unit (UNIT_STOCK: the fish in a unit on a day decide the species a value is judged for,
  farm.water.read.SpeciesBook) and per batch (BATCH: the fold's own key), with the earliest day changed;
- the reference data and the places, each table as one key (WATER_TABLES): the sampling points, the limits and the
  species they belong to, the freshness rules, the units, the systems, the sites, the production departments (a unit's
  site and clock), the equipment and the systems it serves (whose units an equipment point is judged for), the platform
  settings (the clock tolerance), the sensors' bindings and channels (which channel counts where, its scale, its
  freshness).
No trigger sits on a table the ingest (sensors-ingest, Rust) writes: NEVER_TRACKED, which a test holds equal to the
tables its database role may write. A live value is proved by its channel's state itself (the reader compares it), never
by a revision.

A key with no row is unknown, never valid: `ensure(pairs)` gives keys a row (above the floor, the whole history dirty),
and the migrations that add the triggers do it for every key that exists then. A reader ensures its keys, then stamps
them, then reads the data. `missing()` names a trigger that is gone or off; `repair()` (manage.py core_rev_repair) makes
the missing ones again and rebuilds.

The audit revision (core.audit.revision) is NOT a proof: admin edits, restores and raw SQL need not log."""
from datetime import date

import importlib

from django.db import connection, transaction

# The day a change that may touch the whole history notes (a batch's species, a line whose operation is gone, any change
# of a scope without days).
EVERYTHING = date(1, 1, 1)
# The row that holds the floor a rebuild sets: a key seen for the first time starts above it.
FLOOR = ('*', '0')

BATCH = 'batch'
UNIT_STOCK = 'unit_stock'
WATER_POINT = 'water_point'
# The table-level scopes (key '0') the water's judgement reads: each is its table's name.
WATER_TABLES = ('platform_settings', 'water_sampling_points', 'water_limits', 'species', 'water_freshness', 'tanks',
                'systems', 'sites', 'production_departments', 'equipment', 'equipment_systems', 'sensors_binding',
                'sensors_channel')
# Every (table, scope) a migration tracks with TrackRev; the presence check compares it with pg_trigger and a test
# compares it with what the migrations made.
TRACKED = (
    ('stock_movements', BATCH),
    ('stock_operations', BATCH),
    ('batches', BATCH),
    ('stock_movements', UNIT_STOCK),
    ('stock_operations', UNIT_STOCK),
    ('batches', UNIT_STOCK),
    ('water_measurements', WATER_POINT),
    *((table, table) for table in WATER_TABLES),
)
# The tables the ingest writes, many times a second: a trigger there would slow every reading and could stop the
# ingest's COMMITs (live-arch CONSENSUS). A test holds that none of them has a revision trigger.
NEVER_TRACKED = ('sensors_reading', 'sensors_channel_state', 'sensors_device_state', 'sensors_ingest_status',
                 'sensors_dead_letter')
# The migrations that make the triggers (core.operations.TrackRev): `operations()` reads them, `repair()` replays them.
MIGRATIONS = ('core.migrations.0014_rev', 'farm.migrations.0050_rev_triggers', 'sensors.migrations.0014_rev_triggers')
# SQL giving the largest revision a stored figure was stamped with, one per table of stored figures (a checkpoint's
# built_rev); a rebuild moves every revision past all of them.
STAMPED = []


def trigger_names(table, scope):
    """The note, apply and truncate triggers of a tracked (table, scope) (core.operations.TrackRev)."""
    function = f'core_rev_{table}_{scope}'
    return f'{function}_note', f'{function}_apply', f'{function}_trunc'


def rev(scope, key='0'):
    """The revision of a key, or None when it has none (unknown: a stored figure stamped for it is never valid)."""
    with connection.cursor() as cursor:
        cursor.execute('SELECT rev FROM core_rev WHERE scope = %s AND key = %s', [scope, str(key)])
        found = cursor.fetchone()
    return found[0] if found else None


def stamp(pairs):
    """One text for the revisions of several keys, read in one query (read it BEFORE the data it stamps):
    'scope:key:rev' sorted, '-' for a key without a revision."""
    pairs = sorted({(scope, str(key)) for scope, key in pairs})
    if not pairs:
        return ''
    with connection.cursor() as cursor:
        cursor.execute('SELECT scope, key, rev FROM core_rev WHERE (scope, key) IN (SELECT * FROM unnest(%s::text[], '
                       '%s::text[]))', [[scope for scope, _key in pairs], [key for _scope, key in pairs]])
        found = {(scope, key): value for scope, key, value in cursor.fetchall()}
    return ' '.join(f'{scope}:{key}:{found.get((scope, key), "-")}' for scope, key in pairs)


def mark_built(scope, key, rev0):
    """After building a figure from revision `rev0`: the row's epoch becomes rev0 and its dirty day is cleared, only
    if the revision is still rev0 (else a write landed while the builder read, and the figure is judged by that
    write's day). It also forgets this transaction's note of the key, so a later change in the same transaction moves
    the revision again. True when it was set."""
    with connection.cursor() as cursor:
        cursor.execute('SELECT core_rev_mark_built(%s, %s, %s)', [scope, str(key), rev0])
        return cursor.fetchone()[0]


def settle():
    """For tests: applies now what COMMIT would apply (a TestCase never commits). The deferred triggers fire at
    once, and so do the rest of the transaction's; notes made without a trigger (by core_rev_note itself) are
    applied too. Then every deferrable constraint is deferred again, as a transaction starts (every one in this schema is
    INITIALLY DEFERRED), so the writes up to the next settle count as one transaction (each key moves once), the
    revision triggers of a hypertable chunk made later included."""
    with connection.cursor() as cursor:
        cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
        cursor.execute('SELECT core_rev_flush()')
        cursor.execute('SET CONSTRAINTS ALL DEFERRED')


def ensure(pairs):
    """Gives each (scope, key) without a row one, above the floor and with the whole history dirty (nothing is known of
    it), in sorted order; a key with a row keeps it. Returns how many were made. A reader ensures the keys it will stamp
    before it stamps them: a key with no row is never valid, so a point nothing ever changed would never be served."""
    pairs = sorted({(scope, str(key)) for scope, key in pairs})
    if not pairs:
        return 0
    with connection.cursor() as cursor:
        cursor.execute('SELECT core_rev_ensure(%s::text[], %s::text[])',
                       [[scope for scope, _key in pairs], [key for _scope, key in pairs]])
        return cursor.fetchone()[0]


def rebuild(stamped=()):
    """After a restore or a load with the triggers off: every revision moves past every revision ever stamped (the
    restored rows may be older than the stored figures), its epoch with it, and the dirty days are cleared; the floor
    for keys seen later is set to the same value. Every stored figure is then invalid and is built again.

    The table is locked first (SHARE ROW EXCLUSIVE: readers go on, writers' commits wait until the rebuild's transaction
    ends) and only then is the largest revision read, so a commit can neither deadlock with the rebuild (it would
    otherwise take every row in the table's physical order while a commit takes its rows in key order) nor land between
    the read and the update and be set back."""
    found = list(stamped)
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute('LOCK TABLE core_rev IN SHARE ROW EXCLUSIVE MODE')
        for sql in STAMPED:
            cursor.execute(sql)
            found.append(cursor.fetchone()[0])
        cursor.execute('SELECT max(rev) FROM core_rev')
        found.append(cursor.fetchone()[0])
        target = max([value for value in found if value is not None] or [0]) + 1
        cursor.execute('UPDATE core_rev SET rev = %s, dirty_epoch = %s, dirty_from = NULL', [target, target])
        cursor.execute('INSERT INTO core_rev (scope, key, rev, dirty_epoch) VALUES (%s, %s, %s, %s) '
                       'ON CONFLICT (scope, key) DO NOTHING', [*FLOOR, target, target])
    return target


def missing():
    """The names of the declared triggers that are not there or do not fire on a normal write (`manage.py check
    --database default` warns, core.W005: without them a stored figure could be judged valid after a change). A trigger
    fires on a normal write when it is enabled ('O') or enabled ALWAYS ('A'); one disabled ('D') or enabled for replica
    sessions only ('R') does not.

    A TimescaleDB hypertable (water_measurements) keeps its rows in chunks, and a row trigger fires on the chunk the row
    is in: each chunk must have the note and apply triggers too, and one that has not is named '<trigger> on <chunk>'."""
    tables, names = [], []
    for table, scope in TRACKED:
        for name in trigger_names(table, scope):
            tables.append(table)
            names.append(name)
    with connection.cursor() as cursor:
        cursor.execute(
            "WITH wanted AS (SELECT * FROM unnest(%s::text[], %s::text[]) AS w(tbl, tg)), "
            "rels AS (SELECT w.tg, to_regclass(w.tbl) AS rel, NULL::text AS child FROM wanted w "
            "  UNION ALL SELECT w.tg, i.inhrelid::regclass, i.inhrelid::regclass::text FROM wanted w "
            "  JOIN pg_inherits i ON i.inhparent = to_regclass(w.tbl) WHERE w.tg NOT LIKE '%%\\_trunc') "
            "SELECT r.tg, r.child FROM rels r WHERE r.rel IS NULL OR NOT EXISTS (SELECT 1 FROM pg_trigger t "
            "  WHERE t.tgrelid = r.rel AND t.tgname = r.tg AND t.tgenabled IN ('O', 'A') AND NOT t.tgisinternal)",
            [tables, names])
        gone = cursor.fetchall()
    root = {name for name, child in gone if child is None}
    found = [name for name in names if name in root]
    found += sorted(f'{name} on {child}' for name, child in gone if child is not None)
    return found


def operations():
    """Every TrackRev of the migrations that make the triggers, as they are written there."""
    from .operations import TrackRev
    found = []
    for module in MIGRATIONS:
        found += [each for each in importlib.import_module(module).Migration.operations if isinstance(each, TrackRev)]
    return found


def repair():
    """Makes again the triggers `missing()` names (dropped, disabled or replica-only, on a table or a hypertable's
    chunk): each broken (table, scope) gets its function and its three triggers made anew, exactly as its migration
    made them (TimescaleDB puts the row triggers on every chunk), then every revision is rebuilt, since changes may have
    passed unseen while they were gone. Returns the (table, scope) pairs made again; nothing is done when none is
    missing."""
    gone = {name.split(' on ')[0] for name in missing()}
    broken = [operation for operation in operations() if gone & set(operation.names())]
    if not broken:
        return []
    with transaction.atomic():
        with connection.schema_editor(atomic=False) as editor:
            for operation in broken:
                operation.database_backwards('core', editor, None, None)
                operation.database_forwards('core', editor, None, None)
        rebuild()
    return [(operation.table, operation.scope) for operation in broken]

"""Revisions: the proof that a stored figure is still valid (performance plan, section 0).

`core_rev` holds one counter per (scope, key): ('batch', 12) moves whenever a stock line, a stock operation's date or
void, or the species of batch 12 changes. The database moves it, by triggers a migration adds with
`core.operations.TrackRev`; no Python code bumps anything, so raw SQL, `bulk_create`, the admin and a restore are all
covered. A change is noted while the transaction runs and applied at COMMIT, once per key, in sorted key order (no
deadlock between writers, a lock held for microseconds).

Besides the counter a row holds `dirty_from`, the earliest day changed since the last build, and `dirty_epoch`, the
revision of that build. A figure stored with the revision it was built from (`built_rev`, read BEFORE the data) is
valid iff `built_rev == rev`, or `built_rev >= dirty_epoch` and nothing changed on or before the day it covers
(`dirty_from` is NULL or later). A builder ends with `mark_built` (a compare-and-set: refused when the revision moved
while it read). A key with no row is unknown: never valid.

The audit revision (core.audit.revision) is NOT a proof: admin edits, restores and raw SQL need not log."""
from datetime import date

from django.db import connection

# The day a change that may touch the whole history notes (a batch's species, a line whose operation is gone).
EVERYTHING = date(1, 1, 1)
# The row that holds the floor a rebuild sets: a key seen for the first time starts above it.
FLOOR = ('*', '0')
# Every (table, scope) a migration tracks with TrackRev; the presence check compares it with pg_trigger and a test
# compares it with what the migrations made.
TRACKED = (
    ('stock_movements', 'batch'),
    ('stock_operations', 'batch'),
    ('batches', 'batch'),
)
# SQL giving the largest revision a stored figure was stamped with, one per table of stored figures (a checkpoint's
# built_rev); a rebuild moves every revision past all of them.
STAMPED = []


def trigger_names(table, scope):
    function = f'core_rev_{table}_{scope}'
    return f'{function}_note', f'{function}_apply'


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
    applied too."""
    with connection.cursor() as cursor:
        cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
        cursor.execute('SELECT core_rev_flush()')


def rebuild(stamped=()):
    """After a restore or a load with the triggers off: every revision moves past every revision ever stamped (the
    restored rows may be older than the stored figures), its epoch with it, and the dirty days are cleared; the floor
    for keys seen later is set to the same value. Every stored figure is then invalid and is built again."""
    found = list(stamped)
    with connection.cursor() as cursor:
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
    """The names of the declared triggers that are not there or are disabled (the integrity checks show them: without
    them a stored figure could be judged valid after a change)."""
    wanted = [name for track in TRACKED for name in trigger_names(*track)]
    with connection.cursor() as cursor:
        cursor.execute("SELECT tgname FROM pg_trigger WHERE tgname = ANY(%s) AND tgenabled <> 'D' AND NOT tgisinternal",
                       [wanted])
        there = {name for (name,) in cursor.fetchall()}
    return [name for name in wanted if name not in there]

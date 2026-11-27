"""The tests' clock. A test whose records are dated on fixed days must not read the day it runs on: the rules that count
from today (a record dated at most the correction window back, nothing in the future, a value's freshness) would fail
it, or pass it, by the calendar. `FrozenClock` holds the clock the code reads at one moment for a test class's whole
life, its class data included. That clock is `django.utils.timezone.now`: the code's days and moments come from it
(core.dates, farm.stock.dates; core/tests_company_clock.py refuses `date.today()` and the like). Not held: the
database's own clock (`now()` in SQL), and a model field's `default=timezone.now`, which keeps the real function it was
given when the model was read (core.AccountMail.alive_at, messaging's created_at): a row made without a value for it
carries the real moment.

Nor must a test read the hour it runs at. The server's day (UTC) and the company's (settings.COMPANY_TIME_ZONE, Oslo)
differ for an hour or two before every UTC midnight, and a site on a third zone differs for longer: a test that says
"today" on one clock while the code reads another passes all day and fails in those hours. `BAD_HOURS` are moments
inside them; core/tests_day_boundary.py runs the tests that count days again at each (`at_bad_hours`), and
`TEST_CLOCK` starts a whole run's clock at any moment (`run_clock`: scripts/test.sh passes it on), to look for more.

Nor must a test time the machine it runs on. A wall-clock bound ("this took under half a second") passes on a quiet
machine and fails on a loaded one, and says nothing of why the code is quick: what keeps a round, a page or a lookup
cheap is what it reads, and that the database counts exactly: `reads` gives the rows a block read of each table, by
PostgreSQL's own counters, and the rows each of its statements handed back: the same on any machine.
core/tests_wall_clock.py refuses a test that asserts on a time it measured."""
import os
import re
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone as dt_timezone
from unittest import mock

from django.db import DEFAULT_DB_ALIAS, connections

CLOCK = 'django.utils.timezone.now'

# Moments at which the UTC day is not the company's (Europe/Oslo unless the environment names another). The first is
# the middle of the CI run that found the class (run 42921917659, 23:17 to 23:57 UTC on 10.11.2026).
BAD_HOURS = {
    'WinterNight': datetime(2026, 11, 10, 23, 30, tzinfo=dt_timezone.utc),      # 00:30 on the 11th in Oslo (UTC+1)
    'SummerNight': datetime(2026, 7, 10, 22, 30, tzinfo=dt_timezone.utc),       # 00:30 on the 11th in Oslo (UTC+2)
    'JustBeforeOslosMidnight': datetime(2026, 11, 10, 22, 59, 59, tzinfo=dt_timezone.utc),   # the same day on both
    'JustAfterOslosMidnight': datetime(2026, 11, 10, 23, 0, 0, tzinfo=dt_timezone.utc),      # Oslo is a day ahead
    'NewYearsEve': datetime(2026, 12, 31, 23, 30, tzinfo=dt_timezone.utc),      # 2027 in Oslo, 2026 on the server
}


class FrozenClock:
    """Mixed in before the TestCase: `timezone.now()` is NOW (an aware datetime) while the class's data is made
    (setUpTestData) and in every test of it, and the real clock again afterwards, also when the set-up fails."""
    NOW = None
    RUNS_ON = False             # StartedClock: the clock starts at NOW and runs on

    @classmethod
    def setUpClass(cls):
        if cls.NOW is None or cls.NOW.tzinfo is None:
            raise TypeError(f'{cls.__name__}.NOW is the moment its clock stands at: an aware datetime.')
        if cls.RUNS_ON:
            began = datetime.now(dt_timezone.utc)
            clock = mock.patch(CLOCK, side_effect=lambda: cls.NOW + (datetime.now(dt_timezone.utc) - began))
        else:
            clock = mock.patch(CLOCK, return_value=cls.NOW)
        clock.start()
        cls.addClassCleanup(clock.stop)
        super().setUpClass()


class StartedClock(FrozenClock):
    """As FrozenClock, but the clock starts at NOW when the class's data is made and runs on from there: for tests
    whose records must be made one after the other (the newest by `created_at`, a history in order), which a clock
    that stands gives the same moment. The day and the year are NOW's all the same (a class runs for seconds)."""
    RUNS_ON = True


def at_bad_hours(namespace, *cases, moments=BAD_HOURS):
    """Puts into `namespace` (a test module's globals()) one class per test class of `cases` and moment of `moments`:
    the same tests with the clock held at that moment (`<Case>At<Moment>`). The cases are given as attributes of their
    modules (`test_pages.WallTests`): a class imported by name would be collected a second time where it is imported."""
    for case in cases:
        for name, moment in moments.items():
            held = type(f'{case.__name__}At{name}', (FrozenClock, case), {
                'NOW': moment, '__module__': namespace['__name__'],
                '__doc__': f'{case.__module__}.{case.__name__} with the clock held at {moment.isoformat()}.'})
            namespace[held.__name__] = held


def run_clock(text=None):
    """The clock of a whole run started at the moment `text` (ISO, with its offset: 2026-11-10T23:30:00+00:00) and
    running on from there, or None without one (TEST_CLOCK in the environment unless given): started by the test runner
    before any test or class data (config/test_runner.py), in every worker. A class's FrozenClock still holds its own.
    The database's clock stays the real one, so a test that compares the two fails in such a run: it is a way to look
    for tests that read the hour, the day or the year they run in, not a way to run the suite. What fails by the run's
    own making, and says nothing of the code: the tests of this module (they compare with the real clock), a test that
    runs makemigrations (the clock is a mock where a migration names `timezone.now`), and the account mails' lease,
    whose rows carry the real moment from their field's default (the module's docstring) while the sweep reads the
    run's."""
    text = os.environ.get('TEST_CLOCK', '') if text is None else text
    if not text:
        return None
    start = datetime.fromisoformat(text)
    if start.tzinfo is None:
        raise ValueError(f'TEST_CLOCK {text!r} is the moment the run\'s clock starts at: give its offset (+00:00).')
    began = datetime.now(dt_timezone.utc)
    clock = mock.patch(CLOCK, side_effect=lambda: start + (datetime.now(dt_timezone.utc) - began))
    clock.start()
    return clock


# ---- What a block reads ----------------------------------------------------------------------------------------------
# The rows read of each table, by this connection in this transaction: PostgreSQL's own counters (the
# pg_stat_xact_user_tables figures, by function): the rows sequential scans read of the table, and the entries its
# indexes handed out (an index scan, an index-only scan, a bitmap). Exact integers, never a plan's rounded average.
COUNTERS = r"""
SELECT c.relname, pg_stat_get_xact_tuples_returned(c.oid)
       + COALESCE((SELECT sum(pg_stat_get_xact_tuples_returned(i.indexrelid)) FROM pg_index i
                   WHERE i.indrelid = c.oid), 0)
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p', 'm') AND n.nspname <> 'information_schema' AND n.nspname NOT LIKE 'pg\_%'
"""

# Transaction control: run as it is, never counted around (after a failed statement only a rollback may run).
CONTROL = re.compile(r'\s*(savepoint|rollback|release|begin|commit|start transaction)\b', re.IGNORECASE)


class Unmeasured(AssertionError):
    """A statement `reads` could not measure touches the table asked about: the answer would be a silent zero."""


@dataclass(frozen=True)
class Statement:
    sql: str
    returned: int | None     # the rows it handed back to Python (None: a server-side cursor's, not known when it runs)
    read: dict               # {table: rows it read}, the tables it read none of left out


def _counters(connection):
    with connection.wrap_database_errors, connection.connection.cursor() as cursor:
        cursor.execute(COUNTERS)
        return {name: int(count) for name, count in cursor.fetchall()}


def _difference(after, before):
    return {name: count - before.get(name, 0) for name, count in after.items() if count != before.get(name, 0)}


def _names(sql, relation):
    return re.search(rf'(?<![\w$]){re.escape(relation)}(?![\w$])', sql) is not None


class Reads(list):
    """The statements a `reads` block ran on its connection (each a Statement, in order), the rows the whole block read
    of each table (`counted`, every statement of the connection included, however it was written: a UNION, an
    executemany, a cursor's later fetches), and the statements it saw run on another thread's connection
    (`elsewhere`), which no counter of this connection sees."""

    def __init__(self):
        super().__init__()
        self.counted = {}
        self.elsewhere = []

    def _measured(self, relation):
        missed = [sql for sql in self.elsewhere if _names(sql, relation)]
        if missed:
            raise Unmeasured(f'{len(missed)} statement(s) naming {relation} ran on another thread, where this block '
                             f'counts nothing: {missed[0][:300]}')

    def read(self, relation):
        """The rows the block read of `relation` (sequentially, or as its indexes' entries)."""
        self._measured(relation)
        return self.counted.get(relation, 0)

    def most_returned(self, relation=None):
        """The most rows one statement handed back (of those that read `relation`, if given); 0 when none did."""
        if relation is not None:
            self._measured(relation)
        found = [statement for statement in self if relation is None or relation in statement.read]
        # A server-side cursor reads its rows when they are fetched, after its statement: asked of its text.
        unknown = [statement.sql for statement in self if statement.returned is None
                   and (relation is None or relation in statement.read or _names(statement.sql, relation))]
        if unknown:
            raise Unmeasured(f'{len(unknown)} statement(s) reading {relation or "anything"} handed their rows back '
                             f'through a server-side cursor, after they ran: {unknown[0][:300]}')
        return max((statement.returned for statement in found), default=0)

    def reads(self):
        """{table: rows read} of the tables the block read at all, for a test's message and its measurement line."""
        return dict(sorted(self.counted.items()))

    def described(self, relation, more_than=100):
        """The statements that read more than `more_than` rows of `relation`, most first, with what they read: for a
        bound's message, so a failure names the statement to look at."""
        heavy = sorted((statement for statement in self if statement.read.get(relation, 0) > more_than),
                       key=lambda statement: -statement.read[relation])
        return '\n'.join(f'{statement.read[relation]:,} rows: {statement.sql[:400]}' for statement in heavy) or (
            f'no single statement read more than {more_than} rows of {relation}: the block\'s own reads, or a cursor')


@contextmanager
def reads(using=DEFAULT_DB_ALIAS):
    """What the block reads of each table, counted by PostgreSQL (COUNTERS) around the block and around each statement
    it runs on the database `using`, and the rows each statement hands back. Nothing is run twice and nothing is left
    out on this connection; a statement on another thread's connection is kept in `elsewhere`, and asking about a
    table one of them names raises Unmeasured. Inside a transaction only (a TestCase's test): the counters are the
    transaction's."""
    from django.db.backends.utils import CursorWrapper

    connection = connections[using]
    if not connection.in_atomic_block:
        raise RuntimeError('reads() counts what the transaction read: run it inside one (a TestCase).')
    found, mine = Reads(), threading.get_ident()

    def count(execute, sql, params, many, context):
        if CONTROL.match(sql):          # a savepoint and its rollback read nothing (and may follow a failed statement)
            return execute(sql, params, many, context)
        before = _counters(connection)
        result = execute(sql, params, many, context)
        raw = context['cursor'].cursor
        returned = None if getattr(raw, 'name', None) else (raw.rowcount if raw.description is not None else 0)
        found.append(Statement(sql, returned, _difference(_counters(connection), before)))
        return result

    def watched(method):
        def run(self, sql, *args, **kwargs):
            if threading.get_ident() != mine:
                found.elsewhere.append(str(sql))
            return method(self, sql, *args, **kwargs)
        return run

    # A parallel plan's workers read in processes of their own, whose counters are not this transaction's: the block
    # runs without them (its own setting, given back after), so every row a statement reads is counted here.
    with connection.wrap_database_errors, connection.connection.cursor() as cursor:
        cursor.execute("SELECT current_setting('max_parallel_workers_per_gather'), "
                       "set_config('max_parallel_workers_per_gather', '0', true)")
        (workers, _set), = cursor.fetchall()
    began = _counters(connection)
    try:
        with connection.execute_wrapper(count), \
                mock.patch.object(CursorWrapper, 'execute', watched(CursorWrapper.execute)), \
                mock.patch.object(CursorWrapper, 'executemany', watched(CursorWrapper.executemany)):
            yield found
        found.counted = _difference(_counters(connection), began)
    finally:
        from psycopg.pq import TransactionStatus
        if connection.connection.info.transaction_status != TransactionStatus.INERROR:   # (a failed one ends anyway)
            with connection.wrap_database_errors, connection.connection.cursor() as cursor:
                cursor.execute("SELECT set_config('max_parallel_workers_per_gather', %s, true)", [workers])


def assert_reads_do_not_grow(test, grow, measure, tables, what, more_than=100):
    """That what `measure()` (a block's Reads) reads of each of `tables` does not grow with the history: `grow()` adds
    to the history, then measure() runs twice and the second counts (the first warms the session: the planner's first
    looks at indexes fresh rows filled, which no vacuum has seen); again after a second grow(). The second count of each
    table must be no more than `more_than` rows above the first, where a scan of the history adds all that grow() added.
    A difference, so what does not depend on the history counts alike on both sides. Writes both counts to stderr."""
    import sys

    found = []
    for _grow in range(2):
        grow()
        measure()
        found.append(measure())
    first, second = found
    sys.stderr.write(f'\n[reads] {what}, beside the history and beside it grown: {first.reads()}, {second.reads()}\n')
    for table in tables:
        with test.subTest(what=what, table=table):
            test.assertLessEqual(second.read(table) - first.read(table), more_than,
                                 f'{what}: {first.read(table):,} rows of {table}, then {second.read(table):,}\n'
                                 f'{second.described(table)}')

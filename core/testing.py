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
cheap is what it reads, and that the database tells exactly. `plans` explains each statement a block runs, as it runs,
and gives the rows it read from each table and the rows it handed back: the same on any machine.
core/tests_wall_clock.py refuses a test that asserts on a time it measured."""
import os
import re
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


# ---- What a statement reads ------------------------------------------------------------------------------------------
EXPLAINED = re.compile(r'\s*(select|with|insert|update|delete)\b', re.IGNORECASE)
# What a rolled-back savepoint does not undo: a session's advisory lock taken or let go, a sequence moved by hand, a
# notification sent, another session ended. A statement that calls one is run, never explained.
NOT_UNDONE = re.compile(r'\b(pg_\w*advisory\w*|nextval|setval|pg_notify|pg_terminate_backend|pg_cancel_backend)\s*\(',
                        re.IGNORECASE)


@dataclass(frozen=True)
class Scan:
    relation: str
    node: str                # the plan's node: 'Seq Scan', 'Index Scan', 'Bitmap Heap Scan', ...
    rows: int                # the rows it read: those it passed on and those its filter or recheck removed, all loops


@dataclass(frozen=True)
class Statement:
    sql: str
    returned: int            # the rows it handed back to Python
    scans: tuple


class Plans(list):
    """The statements a `plans` block ran (each a Statement), in order; `skipped`: those run without being explained."""

    def __init__(self):
        super().__init__()
        self.skipped = []

    def read(self, relation):
        """The rows the block read from `relation`, all its statements together."""
        return sum(scan.rows for statement in self for scan in statement.scans if scan.relation == relation)

    def most_returned(self, relation=None):
        """The most rows one statement handed back (of those that read `relation`, if given); 0 when none did."""
        return max((statement.returned for statement in self
                    if relation is None or any(scan.relation == relation for scan in statement.scans)), default=0)

    def reads(self):
        """{relation: rows read}, for a test's message and its measurement line."""
        found = {}
        for scan in (scan for statement in self for scan in statement.scans):
            found[scan.relation] = found.get(scan.relation, 0) + scan.rows
        return dict(sorted(found.items()))


def _scans(node):
    if 'Relation Name' in node and node['Node Type'] != 'ModifyTable':            # (a write's target is not read by it)
        read = (node.get('Actual Rows', 0) + node.get('Rows Removed by Filter', 0)
                + node.get('Rows Removed by Index Recheck', 0))
        yield Scan(node['Relation Name'], node['Node Type'], round(read * node.get('Actual Loops', 1)))
    for child in node.get('Plans', ()):
        yield from _scans(child)


@contextmanager
def plans(using=DEFAULT_DB_ALIAS):
    """Each statement the block runs on the database `using`, explained as it runs: EXPLAIN ANALYZE of it in a savepoint
    rolled back at once, then the statement itself, so each is measured on the rows it finds then and nothing is done
    twice. Yields the Plans, filled as the block runs. Inside a transaction only (a TestCase's test). A statement that
    fails fails in its explaining, with the same error; one that calls what a rollback does not undo (NOT_UNDONE), and
    one run for many parameter sets, is run without it (`skipped`). An explained insert draws its ids twice."""
    connection = connections[using]
    if not connection.in_atomic_block:
        raise RuntimeError('plans() explains each statement in a savepoint: run it inside a transaction (a TestCase).')
    found = Plans()

    def explain(execute, sql, params, many, context):
        if many or not EXPLAINED.match(sql) or NOT_UNDONE.search(sql):
            found.skipped.append(sql)
            return execute(sql, params, many, context)
        wrapper = context['connection']
        with wrapper.wrap_database_errors, wrapper.connection.cursor() as cursor:
            cursor.execute('SAVEPOINT plans_explain')
            try:
                cursor.execute(f'EXPLAIN (ANALYZE, FORMAT JSON) {sql}', params)
                plan = cursor.fetchone()[0][0]['Plan']
            finally:
                cursor.execute('ROLLBACK TO SAVEPOINT plans_explain')
                cursor.execute('RELEASE SAVEPOINT plans_explain')
        returned = round(plan.get('Actual Rows', 0) * plan.get('Actual Loops', 1))
        found.append(Statement(sql, returned, tuple(_scans(plan))))
        return execute(sql, params, many, context)

    with connection.execute_wrapper(explain):
        yield found

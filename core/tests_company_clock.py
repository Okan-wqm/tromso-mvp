"""No code reads the server's clock (settings.TIME_ZONE, UTC) as a farm's day or time: a place without a site reads the
company's (settings.COMPANY_TIME_ZONE through core.dates.company_zone or farm's zone_of(None)), a site its own. Read from
the code, so a new fallback to the server's zone cannot slip by. Refused outside the tests and the migrations:
- `settings.TIME_ZONE`; `localdate()` and `localtime(x)` without a zone; `make_aware(x)` without a zone;
  `get_default_timezone()`; `get_current_timezone()` other than as the zone a form's own aware value is made naive again
  in (`make_naive(value, get_current_timezone())`: the wall time typed, no clock read);
- `date.today()`, `datetime.today()`, `datetime.now()` without a zone, `timezone.now().date()`: the server's (or UTC's) day
  (`datetime.now(timezone.utc)` is an instant, not a day, and passes);
- `TruncDate`, `TruncDay` and the other `Trunc*` without `tzinfo`: a day of the current zone (UTC) in the database;
- a `__date` lookup on a moment (`created_at__date`, `clock_in__date`): the same, in a filter. A key's part before
  `__date` names a moment when it ends with `_at`, or is one of MOMENT_FIELDS; a field called `date` (`operation__date`)
  is a date already and passes.
The scan is by name: it catches the usual calls, not every spelling (core/tests_date_inputs.py says the same of dates).

The tests are read too, for the day alone: a test that asks the server's clock for today (`localdate()` without a zone,
`date.today()`, `datetime.today()`, `datetime.now()` without a zone, `now().date()`) while the code reads the company's
or a site's passes all day and fails in the hours when the two days differ (README, Tests; core/tests_day_boundary.py
runs the tests that count days there). A wall time of the server's zone (`localtime(x)`, `make_aware(x)`) is left to the
tests: their fixtures' sites read UTC and say so."""
import ast
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from .testing import is_test_module

APPS = ('alarms', 'config', 'core', 'experiments', 'farm', 'hr', 'inventory', 'knowledge', 'messaging', 'monitoring',
        'reports', 'sensors', 'tasks')
# A benchmark that writes made-up readings: no farm's day is read.
ALLOWED = {('sensors/management/commands/bench_sensors.py', 'get_default_timezone')}
# The server's day read in a test, each with why it is the server's that is meant.
TEST_DAY_READS = ('localdate() without a zone', 'date.today()', 'datetime.today()', 'datetime.now()',
                  'now().date(): the UTC day')
ALLOWED_IN_TESTS = {
    # Django's token generator reads its own naive clock (PasswordResetTokenGenerator._now): the test moves that one.
    ('core/tests_account_mail.py', 'datetime.now()'),
    # the day migration farm/0032 itself wrote into the notes: the server's, by the migration's own localdate().
    ('farm/tests/test_migration_altitude.py', 'localdate() without a zone'),
}
MOMENT_FIELDS = {'clock_in', 'clock_out', 'valid_from', 'valid_to', 'ts', 'time', 'moment', 'opened_at', 'closed_at'}
TRUNC = {'TruncDate', 'TruncDay', 'TruncWeek', 'TruncMonth', 'TruncYear', 'TruncQuarter', 'TruncHour', 'Trunc'}


def _name(call):
    func = call.func
    return func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ''


def _owner(call):
    """The name a method is called on: `date` in date.today(), `timezone` in timezone.now()."""
    func = call.func
    if isinstance(func, ast.Attribute):
        value = func.value
        return value.attr if isinstance(value, ast.Attribute) else value.id if isinstance(value, ast.Name) else ''
    return ''


def _zone_given(call, position):
    return len(call.args) > position or any(keyword.arg == 'timezone' for keyword in call.keywords)


def _moment_lookup(key):
    parts = (key or '').split('__')
    return any(part == 'date' and index and (parts[index - 1].endswith('_at') or parts[index - 1] in MOMENT_FIELDS)
               for index, part in enumerate(parts))


def server_clock_reads_in(tree):
    found = []
    naive_zones = {id(call.args[1]) for call in ast.walk(tree) if isinstance(call, ast.Call)
                   and _name(call) == 'make_naive' and len(call.args) > 1}
    for node in ast.walk(tree):
        what = None
        if isinstance(node, ast.Attribute) and node.attr == 'TIME_ZONE' and isinstance(node.ctx, ast.Load):
            what = 'settings.TIME_ZONE'
        elif isinstance(node, ast.Call):
            name, owner = _name(node), _owner(node)
            if name == 'localdate' and not _zone_given(node, 1):
                what = 'localdate() without a zone'
            elif name == 'localtime' and not _zone_given(node, 1):
                what = 'localtime(x) without a zone'
            elif name == 'make_aware' and not _zone_given(node, 1):
                what = 'make_aware(x) without a zone'
            elif name == 'get_default_timezone':
                what = name
            elif name == 'get_current_timezone' and id(node) not in naive_zones:
                what = 'get_current_timezone() outside make_naive'
            elif name == 'today' and owner in ('date', 'datetime'):
                what = f'{owner}.today()'
            elif name == 'now' and owner == 'datetime' and not node.args and not node.keywords:
                what = 'datetime.now()'
            elif (name == 'date' and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Call)
                  and _name(node.func.value) == 'now'):
                what = 'now().date(): the UTC day'
            elif name in TRUNC and not any(keyword.arg == 'tzinfo' for keyword in node.keywords):
                what = f'{name} without tzinfo'
            else:
                keys = [keyword.arg for keyword in node.keywords] + [
                    item.value for arg in node.args if isinstance(arg, ast.Dict) for item in arg.keys
                    if isinstance(item, ast.Constant) and isinstance(item.value, str)]
                if any(_moment_lookup(key) for key in keys):
                    what = '__date lookup on a moment'
        if what:
            found.append((node.lineno, what, _name(node) if isinstance(node, ast.Call) else ''))
    return found


def modules(tests):
    """(relative path, parsed module) of every Python file of APPS: the tests' when `tests`, else the code's (the
    migrations left out), told apart by core.modules.is_test_module. The one walk of the project's files that the guards
    of the clock share."""
    for app in APPS:
        for path in sorted(Path(settings.BASE_DIR, app).rglob('*.py')):
            relative = path.relative_to(settings.BASE_DIR).as_posix()
            if is_test_module(relative) == tests and (tests or '/migrations/' not in relative):
                yield relative, ast.parse(path.read_text(encoding='utf-8'))


def server_clock_reads():
    return [f'{relative}:{line} {what}' for relative, tree in modules(tests=False)
            for line, what, name in server_clock_reads_in(tree) if (relative, name) not in ALLOWED]


def server_day_reads_in_tests():
    return [f'{relative}:{line} {what}' for relative, tree in modules(tests=True)
            for line, what, _name in server_clock_reads_in(tree)
            if what in TEST_DAY_READS and (relative, what) not in ALLOWED_IN_TESTS]


# What the guard must see (the third cross-review's bypass probe, farm/zz_bypass.py): each line one way to read UTC's day.
BYPASS = '''
from datetime import date, datetime
from django.db.models.functions import TruncDate
from django.utils import timezone
date.today()
datetime.now().date()
timezone.now().date()
qs.filter(created_at__date=date(2026, 1, 1))
qs.annotate(day=TruncDate('created_at'))
timezone.localtime().date()
'''


class CompanyClockGuardTests(SimpleTestCase):
    def test_the_guard_sees_every_way_the_probe_reads_utcs_day(self):
        found = server_clock_reads_in(ast.parse(BYPASS))
        self.assertEqual(sorted({line for line, _what, _name in found}), [5, 6, 7, 8, 9, 10])
        fine = "qs.filter(operation__date=day)\nqs.annotate(day=TruncDate('clock_in', tzinfo=zone))\n"
        self.assertEqual(server_clock_reads_in(ast.parse(fine)), [])

    def test_no_code_reads_the_servers_clock_as_a_farms(self):
        self.assertEqual(server_clock_reads(), [])

    def test_no_test_asks_the_servers_clock_for_today(self):
        self.assertEqual(server_day_reads_in_tests(), [])
        for relative, _what in ALLOWED_IN_TESTS:                    # the list names files that are there
            self.assertTrue(Path(settings.BASE_DIR, relative).is_file(), relative)

    def test_every_app_is_read(self):
        from django.apps import apps
        ours = {config.name for config in apps.get_app_configs() if Path(settings.BASE_DIR, config.name).is_dir()}
        self.assertEqual(ours - set(APPS), set())


def fold_checks_outside_core_dates():
    """Each place that works out by itself whether a wall time is skipped or repeated on a clock (`.replace(fold=...)`):
    core.dates.on_clock is the one check."""
    return [f'{relative}:{node.lineno}' for relative, tree in modules(tests=False) if relative != 'core/dates.py'
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and any(keyword.arg == 'fold' for keyword in node.keywords)]


class OneClockCheckTests(SimpleTestCase):
    def test_one_function_says_whether_a_wall_time_exists_once_on_a_clock(self):
        self.assertEqual(fold_checks_outside_core_dates(), [])

    def test_it_refuses_a_skipped_and_a_repeated_time_with_its_reason(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from django.core.exceptions import ValidationError

        from .dates import on_clock
        oslo = ZoneInfo('Europe/Oslo')
        self.assertEqual(on_clock(datetime(2026, 3, 29, 3, 30), oslo).isoformat(), '2026-03-29T03:30:00+02:00')
        for wall, code in ((datetime(2026, 3, 29, 2, 30), 'skipped'), (datetime(2026, 10, 25, 2, 30), 'repeated')):
            with self.subTest(wall=wall), self.assertRaises(ValidationError) as caught:
                on_clock(wall, oslo)
            self.assertEqual(caught.exception.code, code)

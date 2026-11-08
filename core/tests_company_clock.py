"""No code reads the server's clock (settings.TIME_ZONE, UTC) as a farm's day or time: a place without a site reads the
company's (settings.COMPANY_TIME_ZONE through core.dates.company_zone or farm's zone_of(None)), a site its own. Read from
the code, so a new fallback to the server's zone cannot slip by. Refused outside the tests and the migrations:
- `settings.TIME_ZONE`; `localdate()` and `localtime(x)` without a zone; `make_aware(x)` without a zone;
  `get_default_timezone()`; `get_current_timezone()` other than as the zone a form's own aware value is made naive again
  in (`make_naive(value, get_current_timezone())`: the wall time typed, no clock read);
- `date.today()`, `datetime.today()`, `datetime.now()`, `timezone.now().date()`: the server's (or UTC's) day;
- `TruncDate`, `TruncDay` and the other `Trunc*` without `tzinfo`: a day of the current zone (UTC) in the database;
- a `__date` lookup on a moment (`created_at__date`, `clock_in__date`): the same, in a filter. A key's part before
  `__date` names a moment when it ends with `_at`, or is one of MOMENT_FIELDS; a field called `date` (`operation__date`)
  is a date already and passes.
The scan is by name: it catches the usual calls, not every spelling (core/tests_date_inputs.py says the same of dates)."""
import ast
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

APPS = ('config', 'core', 'experiments', 'farm', 'hr', 'inventory', 'knowledge', 'messaging', 'monitoring', 'reports',
        'sensors', 'tasks')
# A benchmark that writes made-up readings: no farm's day is read.
ALLOWED = {('sensors/management/commands/bench_sensors.py', 'get_default_timezone')}
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
            elif name == 'now' and owner == 'datetime':
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


def server_clock_reads():
    found = []
    for app in APPS:
        for path in Path(settings.BASE_DIR, app).rglob('*.py'):
            relative = path.relative_to(settings.BASE_DIR).as_posix()
            if '/migrations/' in relative or '/tests' in relative or path.name.startswith('test'):
                continue
            for line, what, name in server_clock_reads_in(ast.parse(path.read_text(encoding='utf-8'))):
                if (relative, name) not in ALLOWED:
                    found.append(f'{relative}:{line} {what}')
    return found


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

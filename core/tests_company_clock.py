"""No code reads the server's clock (settings.TIME_ZONE, UTC) as a farm's day or time: a place without a site reads the
company's (settings.COMPANY_TIME_ZONE through core.dates.company_zone or farm's zone_of(None)), a site its own. Read from
the code, so a new fallback to the server's zone cannot slip by: `settings.TIME_ZONE`, `localdate()` and `localtime(x)`
without a zone, `make_aware(x)` without a zone and `get_default_timezone()` are refused outside the tests and the
migrations; `get_current_timezone()` only as the zone a form's own aware value is made naive again in
(`make_naive(value, get_current_timezone())`: the wall time typed, no clock read)."""
import ast
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

APPS = ('config', 'core', 'experiments', 'farm', 'hr', 'inventory', 'knowledge', 'messaging', 'monitoring', 'reports',
        'sensors', 'tasks')
# A benchmark that writes made-up readings: no farm's day is read.
ALLOWED = {('sensors/management/commands/bench_sensors.py', 'get_default_timezone')}


def _name(call):
    func = call.func
    return func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ''


def _zone_given(call, position):
    return len(call.args) > position or any(keyword.arg == 'timezone' for keyword in call.keywords)


def server_clock_reads():
    found = []
    for app in APPS:
        for path in Path(settings.BASE_DIR, app).rglob('*.py'):
            relative = path.relative_to(settings.BASE_DIR).as_posix()
            if '/migrations/' in relative or '/tests' in relative or path.name.startswith('test'):
                continue
            tree = ast.parse(path.read_text(encoding='utf-8'))
            naive_zones = {id(call.args[1]) for call in ast.walk(tree) if isinstance(call, ast.Call)
                           and _name(call) == 'make_naive' and len(call.args) > 1}
            for node in ast.walk(tree):
                what = None
                if isinstance(node, ast.Attribute) and node.attr == 'TIME_ZONE' and isinstance(node.ctx, ast.Load):
                    what = 'settings.TIME_ZONE'
                elif isinstance(node, ast.Call):
                    name = _name(node)
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
                if what and (relative, what) not in ALLOWED and (relative, _name(node) if isinstance(node, ast.Call)
                                                                 else '') not in ALLOWED:
                    found.append(f'{relative}:{node.lineno} {what}')
    return found


class CompanyClockGuardTests(SimpleTestCase):
    def test_no_code_reads_the_servers_clock_as_a_farms(self):
        self.assertEqual(server_clock_reads(), [])

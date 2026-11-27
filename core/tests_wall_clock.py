"""No test asserts on a time it measured on the wall clock. "It took under half a second" passes on a quiet machine and
fails on a loaded one (CI run 45865365125: 0.585 s for a bound of 0.5 on a shared runner), and it says nothing of why
the code is quick: what a round, a page or a lookup reads is counted by the database (core.testing.plans), a timeout or
a deadline is driven by a clock the test holds (outbox.send_due's `clock`, the worker's), and that a thing did not wait
is asked of the thing (still hanging, still held). Read from the tests: an assertLess, assertLessEqual, assertGreater,
assertGreaterEqual, assertTrue, assertFalse or `assert` whose arguments hold a reading of time.monotonic,
time.perf_counter, time.time, time.process_time (or their _ns), timeit.default_timer, or a name made from one (in the
same function, or returned by a function of the same module) is refused. A wait with a ceiling (`until`, a deadline
loop) asserts nothing on the clock and passes.

ALLOWED names the timing assertions that must stay, each exactly as written, with why: a real-time requirement of
processes the test cannot hand a clock to, or a benchmark run only when asked."""
import ast
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from .tests_company_clock import APPS, is_test

CLOCKS = {('time', name) for name in ('monotonic', 'perf_counter', 'time', 'process_time', 'monotonic_ns',
                                      'perf_counter_ns', 'time_ns', 'process_time_ns')} | {('timeit', 'default_timer')}
ASSERTS = {'assertLess', 'assertLessEqual', 'assertGreater', 'assertGreaterEqual', 'assertTrue', 'assertFalse'}
GROWS = {'append', 'extend', 'insert', 'add', 'update', 'setdefault'}      # a container a measured value is put in

# (file, Class.test, the assertion as written): why it stays on the wall clock.
ALLOWED = {
    ('alarms/tests/test_reaction.py', 'ReactionTests.test_a_manual_critical_sample_opens_its_alarm_within_10_s',
     'self.assertLess(max(took), TARGET, self.said(process))'):
        "the owner's 10 s from a value's commit to its open alarm, with the real worker in a process of its own: a "
        "requirement on real time, which no clock of the test reaches",
    ('alarms/tests/test_outbox.py', 'SenderThreadTests.test_a_transport_that_hangs_never_delays_an_alarm',
     'self.assertLess(took, TARGET)'):
        "the owner's 10 s while the push service hangs, the worker running as it runs (its loop, its sender thread, "
        "the real clock)",
    ('alarms/tests/test_worker_process.py',
     'ProcessTests.test_a_killed_worker_is_seen_as_not_checking_within_stale_after_and_its_lock_is_let_go',
     'self.assertLess(time.monotonic() - killed, 3 + 2)'):
        "a killed process is said unchecked within stale_after, read on the database's clock: real processes, real "
        "time",
    ('alarms/tests/test_worker_process.py',
     'ProcessTests.test_a_standby_takes_over_within_seconds_of_the_first_being_killed',
     'self.assertLess(took, 5)'):
        "a standby process takes the lock over within seconds of the first being killed: real processes, real time",
    ('monitoring/tests/test_load.py', 'LoadTests.test_a_wall_of_200_cards_with_a_12_widget_template',
     'self.assertLessEqual(seconds, MAX_SECONDS)'):
        "the load check, run only when asked (MONITOR_LOAD=1, never in CI): it measures this machine on purpose",
    ('monitoring/tests/test_load.py', 'LoadTests.test_a_wall_of_200_small_cards',
     'self.assertLessEqual(seconds, MAX_SECONDS)'):
        "the load check of the Small cards, run only when asked (MONITOR_LOAD=1, never in CI)",
}


def _clock_modules(tree):
    """{local name: (module, function)} of the clocks a module can call by a bare name, and the names its modules
    `time` and `timeit` go by."""
    bare, modules = {}, {'time': 'time', 'timeit': 'timeit'}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in ('time', 'timeit'):
            for alias in node.names:
                if (node.module, alias.name) in CLOCKS:
                    bare[alias.asname or alias.name] = (node.module, alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in ('time', 'timeit'):
                    modules[alias.asname or alias.name] = alias.name
    return bare, modules


def _called(call):
    func = call.func
    return func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ''


def _held(node):
    """The name a value is held under: `took`, `self.took` (never `self` alone); '' for anything else."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        owner = _held(node.value)
        return f'{owner}.{node.attr}' if owner else ''
    return ''


def _merge(one, other):
    """Two shapes of one value together (a shape: True, the value is a reading or holds them as a whole; a frozenset,
    the positions of a tuple, or of each tuple a container holds, that are; None, nothing measured)."""
    if one is None or other is None:
        return one if other is None else other
    return True if one is True or other is True else one | other


class _Reader:
    """Which names of a function hold a wall-clock reading (their shape), and which assertions use one."""

    def __init__(self, tree):
        self.bare, self.modules = _clock_modules(tree)
        self.returning = {}               # function name: the shape of what it returns

    def is_clock(self, node):
        if not isinstance(node, ast.Call):
            return False
        func = node.func
        if isinstance(func, ast.Name):
            return func.id in self.bare
        return (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)
                and (self.modules.get(func.value.id), func.attr) in CLOCKS)

    def measured(self, expression, names):
        """Whether `expression` holds a reading as a whole (a tuple's or a container's other parts do not count)."""
        for node in ast.walk(expression):
            if self.is_clock(node) or (isinstance(node, ast.Call) and self.returning.get(_called(node)) is True):
                return True
            if isinstance(node, (ast.Name, ast.Attribute)) and names.get(_held(node)) is True:
                return True
            if (isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant)
                    and isinstance(names.get(_held(node.value)), frozenset)
                    and node.slice.value in names[_held(node.value)]):
                return True
        return False

    def shape(self, value, names):
        if isinstance(value, (ast.Tuple, ast.List)):
            found = frozenset(index for index, part in enumerate(value.elts) if self.measured(part, names))
            if len(found) < len(value.elts):
                return found or None
        if isinstance(value, ast.Call) and isinstance(self.returning.get(_called(value)), frozenset):
            return self.returning[_called(value)]
        if isinstance(value, (ast.Name, ast.Attribute)) and _held(value) in names:
            return names[_held(value)]
        return True if self.measured(value, names) else None

    def _bind(self, target, shape, names):
        if shape is None:
            return
        if isinstance(target, (ast.Tuple, ast.List)):
            for index, part in enumerate(target.elts):
                if shape is True or index in shape:
                    self._bind(part, True, names)
            return
        while isinstance(target, (ast.Subscript, ast.Starred)):   # an item put in a container: the container's shape
            target = target.value
        if _held(target):
            names[_held(target)] = _merge(names.get(_held(target)), shape)

    def _each(self, target, iterable, names):
        """`for target in iterable`: each item's shape, from its container's."""
        if isinstance(iterable, ast.Call) and isinstance(iterable.func, ast.Attribute) and not iterable.args:
            container = names.get(_held(iterable.func.value))
            if iterable.func.attr == 'values':
                return self._bind(target, container, names)
            if iterable.func.attr == 'items' and isinstance(target, ast.Tuple) and len(target.elts) == 2:
                return self._bind(target.elts[1], container, names)
        if isinstance(iterable, (ast.Name, ast.Attribute)) and _held(iterable) in names:
            return self._bind(target, names[_held(iterable)], names)
        self._bind(target, True if self.measured(iterable, names) else None, names)

    def names(self, function):
        """{name: shape} of the names in `function` (its nested functions too) that hold a reading, to a fixed point."""
        names = {}
        while True:
            before = dict(names)
            for node in ast.walk(function):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        self._bind(target, self.shape(node.value, names), names)
                elif isinstance(node, (ast.AugAssign, ast.AnnAssign, ast.NamedExpr)) and node.value is not None:
                    self._bind(node.target, self.shape(node.value, names), names)
                elif isinstance(node, (ast.For, ast.comprehension)):
                    self._each(node.target, node.iter, names)
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in GROWS:
                    for arg in node.args:
                        self._bind(node.func.value, self.shape(arg, names), names)
            if names == before:
                return names

    def returns(self, function, names):
        found = None
        for node in ast.walk(function):
            if isinstance(node, ast.Return) and node.value is not None:
                found = _merge(found, self.shape(node.value, names))
        return found


def _functions(tree):
    """(Class.name or name, the function) of a module's functions and methods."""
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node.name, node
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    yield f'{node.name}.{item.name}', item


def wall_clock_assertions_in(tree):
    """[(line, Class.test, the assertion as written)] of the assertions on a wall-clock reading in a module."""
    reader, functions = _Reader(tree), list(_functions(tree))
    for _round in range(3):                       # a helper's result may come from another helper's
        for name, function in functions:
            got = reader.returns(function, reader.names(function))
            if got is not None:
                reader.returning[name.rsplit('.', 1)[-1]] = got
    found = []
    for name, function in functions:
        names = reader.names(function)
        for node in ast.walk(function):
            if isinstance(node, ast.Assert):
                checked = [node.test]
            elif isinstance(node, ast.Call) and _called(node) in ASSERTS:
                checked = node.args[:2]
            else:
                continue
            if any(reader.measured(part, names) for part in checked):
                found.append((node.lineno, name, ast.unparse(node.test if isinstance(node, ast.Assert) else node)))
    return sorted(found)


def wall_clock_assertions():
    """['file:line Class.test: assertion'] of every test's assertion on a wall-clock reading not in ALLOWED, and the
    ALLOWED entries no test has any more."""
    found, seen = [], set()
    for app in APPS:
        for path in sorted(Path(settings.BASE_DIR, app).rglob('*.py')):
            relative = path.relative_to(settings.BASE_DIR).as_posix()
            if not is_test(relative, path.name):
                continue
            for line, name, source in wall_clock_assertions_in(ast.parse(path.read_text(encoding='utf-8'))):
                if (relative, name, source) in ALLOWED:
                    seen.add((relative, name, source))
                else:
                    found.append(f'{relative}:{line} {name}: {source}')
    return found + [f'allowed but not found: {entry}' for entry in sorted(set(ALLOWED) - seen)]


# Each way the guard must see: one assertion per line from line 13 on, each on a reading of the wall clock.
PROBE = '''
import time
import timeit
from time import perf_counter as pc


class Probe:
    def measure(self):
        started = time.monotonic()
        return 'page', time.monotonic() - started

    def test_probe(self):
        self.assertLess(time.monotonic() - started, 5)
        took = time.perf_counter() - started; self.assertLess(took, 0.5)
        longest = max(longest, time.time() - started); self.assertGreater(1.0, longest)
        seen = []; seen.append(pc() - started); self.assertLessEqual(max(seen), 10)
        rows, seconds = self.measure(); self.assertGreaterEqual(30, seconds)
        [one] = [timeit.default_timer()]; self.assertTrue(one < 3)
        assert time.monotonic_ns() - started < 10
        self.took.append(time.monotonic() - started); self.assertLess(self.took[0], 1)
'''
# What it must let pass: a wait with a ceiling, a measurement written out, a count, the other part of a measurement.
FINE = '''
import sys
import time


def until(found, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if found():
            return True
    raise AssertionError('not within')


class Fine:
    def measure(self):
        started = time.monotonic()
        return 'page', time.monotonic() - started

    def test_fine(self):
        started = time.monotonic()
        sys.stderr.write(f'{time.monotonic() - started:.2f} s')
        rows, seconds = self.measure()
        self.assertEqual(rows, 'page')
        self.assertLess(len(rows), 10)
        self.assertTrue(until(lambda: True, 10))
        self.took.append(time.monotonic() - started)
        self.assertLess(self.count, 3)
'''


class WallClockGuardTests(SimpleTestCase):
    def test_the_guard_sees_every_way_the_probe_asserts_on_the_wall_clock(self):
        found = wall_clock_assertions_in(ast.parse(PROBE))
        self.assertEqual([line for line, _name, _source in found], list(range(13, 21)))
        self.assertEqual({name for _line, name, _source in found}, {'Probe.test_probe'})
        self.assertEqual(wall_clock_assertions_in(ast.parse(FINE)), [])

    def test_no_test_asserts_on_a_time_it_measured(self):
        self.assertEqual(wall_clock_assertions(), [])

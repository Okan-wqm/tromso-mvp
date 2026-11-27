"""No test asserts on a time it measured on the wall clock. "It took under half a second" passes on a quiet machine and
fails on a loaded one (CI run 45865365125: 0.585 s for a bound of 0.5 on a shared runner), and it says nothing of why
the code is quick: what a round, a page or a lookup reads is counted by the database (core.testing.reads), a timeout or
a deadline is driven by a clock the test holds (outbox.send_due's `clock`, the worker's) or read off the call that
waits (a join's timeout), and that a thing did not wait is asked of the thing (still hanging, still held).

Read from every test module (each function and method, in classes nested to any depth, with the functions they
define), a measured value is:
- a reading of time.monotonic, perf_counter, time, process_time, thread_time or clock_gettime (each also as _ns) or
  timeit.default_timer, however imported, and through any name bound to one of those functions (`clock =
  time.monotonic`, `self.clock = ...`);
- the difference of two moments of the real calendar clock: datetime.now(), datetime.utcnow(), timezone.now() (or a
  name holding one) on both sides of a minus;
- anything computed from one of those, in the same function: a name, an item of a list or dict it is put in, a part
  of a tuple, the result of a function of the same module that returns one (or a tuple with one in it).
Refused: a measured value in the arguments (by position or keyword) of any assert... or fail... call, in an `assert`
statement, or in the test of an `if` whose body fails the test (a fail... call or a raise). A wait with a ceiling
(`until`, a deadline loop that raises once it is past) compares a reading in a `while`, never asserts on it, and passes;
so does a measurement written out.

ALLOWED names the timing assertions that must stay, each exactly as written, with why: a real-time requirement of
processes the test cannot hand a clock to, or a benchmark run only when asked."""
import ast

from django.test import SimpleTestCase

from .tests_company_clock import _name, _owner, modules

CLOCK_FUNCTIONS = ('monotonic', 'perf_counter', 'time', 'process_time', 'thread_time', 'clock_gettime')
CLOCKS = ({('time', name) for name in CLOCK_FUNCTIONS} | {('time', f'{name}_ns') for name in CLOCK_FUNCTIONS}
          | {('timeit', 'default_timer')})
NOWS = {('datetime', 'now'), ('datetime', 'utcnow'), ('timezone', 'now')}
GROWS = {'append', 'extend', 'insert', 'add', 'update', 'setdefault'}      # a container a measured value is put in

# (file, Class.test, the assertion as written): why it stays on the wall clock.
ALLOWED = {
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


class _Scope:
    """What one function holds: {name: shape} of the measured names, and the names holding a calendar moment."""

    def __init__(self):
        self.shapes, self.moments = {}, set()

    def state(self):
        return dict(self.shapes), set(self.moments)


class _Reader:
    """Which names of a module's functions hold a wall-clock reading (their shape), and which checks use one."""

    def __init__(self, tree):
        self.modules = {'time': 'time', 'timeit': 'timeit'}
        self.clocks, self.nows = set(), set()       # bare names that are a clock / a calendar clock
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in ('time', 'timeit', 'django.utils.timezone'):
                for alias in node.names:
                    if (node.module, alias.name) in CLOCKS:
                        self.clocks.add(alias.asname or alias.name)
                    elif node.module == 'django.utils.timezone' and alias.name == 'now':
                        self.nows.add(alias.asname or alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in ('time', 'timeit'):
                        self.modules[alias.asname or alias.name] = alias.name
        for node in ast.walk(tree):                 # names bound to a clock function: `clock = time.monotonic`
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None and self.is_clock_function(
                    node.value):
                for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
                    if _held(target):
                        self.clocks.add(_held(target))
        self.returning = {}               # function name: the shape of what it returns

    def is_clock_function(self, node):
        if isinstance(node, (ast.Name, ast.Attribute)) and _held(node) in self.clocks:
            return True
        return (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                and (self.modules.get(node.value.id), node.attr) in CLOCKS)

    def is_clock(self, node):
        return isinstance(node, ast.Call) and self.is_clock_function(node.func)

    def is_moment(self, node, scope):
        if isinstance(node, ast.Call):
            return (_name(node), _owner(node)) in {(name, owner) for owner, name in NOWS} or (
                isinstance(node.func, ast.Name) and node.func.id in self.nows)
        return isinstance(node, (ast.Name, ast.Attribute)) and _held(node) in scope.moments

    def measured(self, expression, scope):
        """Whether `expression` holds a reading as a whole (a tuple's or a container's other parts do not count)."""
        for node in ast.walk(expression):
            if self.is_clock(node) or (isinstance(node, ast.Call) and self.returning.get(_name(node)) is True):
                return True
            if isinstance(node, (ast.Name, ast.Attribute)) and scope.shapes.get(_held(node)) is True:
                return True
            if (isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant)
                    and isinstance(scope.shapes.get(_held(node.value)), frozenset)
                    and node.slice.value in scope.shapes[_held(node.value)]):
                return True
            if (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Sub) and self.is_moment(node.left, scope)
                    and self.is_moment(node.right, scope)):
                return True
        return False

    def shape(self, value, scope):
        if isinstance(value, (ast.Tuple, ast.List)):
            found = frozenset(index for index, part in enumerate(value.elts) if self.measured(part, scope))
            if len(found) < len(value.elts):
                return found or None
        if isinstance(value, ast.Call) and isinstance(self.returning.get(_name(value)), frozenset):
            return self.returning[_name(value)]
        if isinstance(value, (ast.Name, ast.Attribute)) and _held(value) in scope.shapes:
            return scope.shapes[_held(value)]
        return True if self.measured(value, scope) else None

    def _bind(self, target, shape, scope):
        if shape is None:
            return
        if isinstance(target, (ast.Tuple, ast.List)):
            for index, part in enumerate(target.elts):
                if shape is True or index in shape:
                    self._bind(part, True, scope)
            return
        while isinstance(target, (ast.Subscript, ast.Starred)):   # an item put in a container: the container's shape
            target = target.value
        if _held(target):
            scope.shapes[_held(target)] = _merge(scope.shapes.get(_held(target)), shape)

    def _assigned(self, target, value, scope):
        if self.is_moment(value, scope) and _held(target):
            scope.moments.add(_held(target))
        self._bind(target, self.shape(value, scope), scope)

    def _each(self, target, iterable, scope):
        """`for target in iterable`: each item's shape, from its container's."""
        if isinstance(iterable, ast.Call) and isinstance(iterable.func, ast.Attribute) and not iterable.args:
            container = scope.shapes.get(_held(iterable.func.value))
            if iterable.func.attr == 'values':
                return self._bind(target, container, scope)
            if iterable.func.attr == 'items' and isinstance(target, ast.Tuple) and len(target.elts) == 2:
                return self._bind(target.elts[1], container, scope)
        if isinstance(iterable, (ast.Name, ast.Attribute)) and _held(iterable) in scope.shapes:
            return self._bind(target, scope.shapes[_held(iterable)], scope)
        self._bind(target, True if self.measured(iterable, scope) else None, scope)

    def scope(self, function):
        """The measured names and the moments of `function` (its nested functions too), to a fixed point."""
        scope = _Scope()
        while True:
            before = scope.state()
            for node in ast.walk(function):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        self._assigned(target, node.value, scope)
                elif isinstance(node, (ast.AugAssign, ast.AnnAssign, ast.NamedExpr)) and node.value is not None:
                    self._assigned(node.target, node.value, scope)
                elif isinstance(node, (ast.For, ast.comprehension)):
                    self._each(node.target, node.iter, scope)
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in GROWS:
                    for arg in node.args:
                        self._bind(node.func.value, self.shape(arg, scope), scope)
            if scope.state() == before:
                return scope

    def returns(self, function, scope):
        found = None
        for node in ast.walk(function):
            if isinstance(node, ast.Return) and node.value is not None:
                found = _merge(found, self.shape(node.value, scope))
        return found


def _is_check(call):
    return _name(call).startswith(('assert', 'fail'))


def _fails(body):
    """Whether these statements fail the test: a raise, or a fail.../assert... call."""
    return any(isinstance(node, ast.Raise) or (isinstance(node, ast.Call) and _is_check(node))
               for statement in body for node in ast.walk(statement))


def _functions(body, prefix=''):
    """(Class.Inner.name or name, the function) of a module's functions and methods, classes nested to any depth."""
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield f'{prefix}{node.name}', node
        elif isinstance(node, ast.ClassDef):
            yield from _functions(node.body, f'{prefix}{node.name}.')


def wall_clock_assertions_in(tree):
    """[(line, Class.test, the check as written)] of the checks on a wall-clock reading in a module."""
    reader, functions = _Reader(tree), list(_functions(tree.body))
    for _round in range(3):                       # a helper's result may come from another helper's
        for name, function in functions:
            got = reader.returns(function, reader.scope(function))
            if got is not None:
                reader.returning[name.rsplit('.', 1)[-1]] = got
    found = []
    for name, function in functions:
        scope = reader.scope(function)
        for node in ast.walk(function):
            if isinstance(node, ast.Assert):
                checked, source = [node.test], ast.unparse(node.test)
            elif isinstance(node, ast.Call) and _is_check(node):
                checked, source = node.args + [keyword.value for keyword in node.keywords], ast.unparse(node)
            elif isinstance(node, ast.If) and _fails(node.body):
                checked, source = [node.test], f'if {ast.unparse(node.test)}: ...'
            else:
                continue
            if any(reader.measured(part, scope) for part in checked):
                found.append((node.lineno, name, source))
    return sorted(found)


def wall_clock_assertions():
    """['file:line Class.test: check'] of every test's check on a wall-clock reading not in ALLOWED, and the ALLOWED
    entries no test has any more."""
    found, seen = [], set()
    for relative, tree in modules(tests=True):
        for line, name, source in wall_clock_assertions_in(tree):
            if (relative, name, source) in ALLOWED:
                seen.add((relative, name, source))
            else:
                found.append(f'{relative}:{line} {name}: {source}')
    return found + [f'allowed but not found: {entry}' for entry in sorted(set(ALLOWED) - seen)]


# Each way the guard must see: one check per line (lines 17 to 31, and 35), each on a reading of the wall clock.
PROBE = '''
import time
import timeit
from datetime import datetime
from time import perf_counter as pc

from django.utils import timezone


class Probe:
    def measure(self):
        started = time.monotonic()
        return 'page', time.monotonic() - started

    def test_probe(self):
        clock = time.monotonic
        self.assertLess(time.monotonic() - started, 5)
        took = time.perf_counter() - started; self.assertLess(took, 0.5)
        longest = max(longest, time.time() - started); self.assertGreater(1.0, longest)
        seen = []; seen.append(pc() - started); self.assertLessEqual(max(seen), 10)
        rows, seconds = self.measure(); self.assertGreaterEqual(30, seconds)
        [one] = [timeit.default_timer()]; self.assertTrue(one < 3)
        assert time.monotonic_ns() - started < 10
        self.took.append(time.monotonic() - started); self.assertLess(self.took[0], 1)
        if took > 1: self.fail('slow')
        if time.monotonic() - started > 1: raise AssertionError('slow')
        self.assertEqual(time.monotonic() - started < 1, True)
        self.assertIs(time.thread_time() - started < 1, True)
        self.assertLess(first=time.clock_gettime(time.CLOCK_MONOTONIC) - started, second=1)
        self.assertLess(clock() - started, 1)
        begun = timezone.now(); self.assertLess(datetime.now() - begun, 1)

    class Inner:
        def test_inner(self):
            self.assertLess(time.monotonic() - started, 1)
'''
PROBE_LINES = [*range(17, 32), 35]
# What it must let pass: a wait with a ceiling, a measurement written out, a count, the other part of a measurement,
# a moment of the calendar clock compared with a fixed one.
FINE = '''
import sys
import time

from django.utils import timezone


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
        self.assertLess(timezone.now() - THEN, DAY)
        if not rows: self.fail('nothing')
'''


class WallClockGuardTests(SimpleTestCase):
    def test_the_guard_sees_every_way_the_probe_asserts_on_the_wall_clock(self):
        found = wall_clock_assertions_in(ast.parse(PROBE))
        self.assertEqual([line for line, _name, _source in found], PROBE_LINES, found)
        self.assertEqual({name for _line, name, _source in found}, {'Probe.test_probe', 'Probe.Inner.test_inner'})
        self.assertEqual(wall_clock_assertions_in(ast.parse(FINE)), [])

    def test_no_test_asserts_on_a_time_it_measured(self):
        self.assertEqual(wall_clock_assertions(), [])

"""The alarm worker (alarms/worker.py, manage.py run_alarm_worker): the process that keeps the alarms checked. Its loop on a
fake monotonic clock (each wait moves it on), the real database and, where it matters, the real pass: it checks at once
and then every sweep, says on its row what it did, survives a server clock that jumps, a pass that fails whole, the
database lost for a while; exits to be started again when the database stays away, passes keep failing or a pass
hangs; stops cleanly; stands by while another worker holds the lock. The health check reads the same verdict as the
pages (alarms/watch.py)."""
import itertools
import pathlib
import re
import signal
import time
from datetime import timedelta
from io import StringIO
from unittest import mock

import psycopg
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.db import OperationalError, connection
from django.test import TestCase
from django.utils import timezone

from .. import engine, watch, worker
from ..models import Alarm, AlarmWorkerStatus
from . import AlarmsCase

TIMING = dict(tick=1.0, sweep=15.0, stale_after=45, db_down_exit=60.0, backoff_max=10.0, max_failures=5,
              hang_exit=120.0, statement_timeout=20.0, lock_timeout=5.0)


class Clock:
    """A monotonic clock that only the test moves."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class Ticks:
    """The worker's stop event on the fake clock: each wait moves the clock on by what the worker asked and is kept; after
    `count` waits the worker is stopped. `on_wait(n)` runs after the n-th wait (a test's way to change the world)."""

    def __init__(self, clock, count, on_wait=None):
        self.clock, self.count, self.on_wait = clock, count, on_wait
        self.waits, self.stopped = [], False

    def is_set(self):
        return self.stopped

    def set(self):
        self.stopped = True

    def wait(self, seconds):
        self.waits.append(seconds)
        self.clock.now += seconds
        if self.on_wait:
            self.on_wait(len(self.waits))
        if len(self.waits) >= self.count:
            self.stopped = True
        return self.stopped


def unlock_all():
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_advisory_unlock_all()')


def make(count, run_pass=None, cls=worker.Worker, on_wait=None, changes=None, **timing):
    clock = Clock()
    made = cls('alarms', worker.Timing(**{**TIMING, **timing}), run_pass=run_pass or mock.Mock(
        return_value=engine.Summary()), changes=changes, clock=clock, stop=Ticks(clock, count, on_wait),
        reset=mock.Mock(side_effect=unlock_all), exit_now=mock.Mock())
    return made


def other_session():
    """A second session on the test database, as a second worker's."""
    found = connection.settings_dict
    return psycopg.connect(dbname=found['NAME'], user=found['USER'], password=found['PASSWORD'], host=found['HOST'],
                           port=found['PORT'], autocommit=True)


def lock_free():
    """Waits (5 s at most) until the server has ended a closed session and let its lock go."""
    for _ in range(100):
        with other_session() as probe:
            if probe.execute('SELECT pg_try_advisory_lock(%s)', [worker.LOCK]).fetchone()[0]:
                return
        time.sleep(0.05)
    raise AssertionError('the lock was not let go')


class DownWorker(worker.Worker):
    """A worker whose database is unreachable while `down` is true: its first statement of a look fails."""

    down = True

    def _lead(self):
        if self.down:
            raise OperationalError('server closed the connection unexpectedly')
        return super()._lead()


class WorkerCase(TestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(unlock_all)

    def row(self):
        return AlarmWorkerStatus.objects.get(name='alarms')


class PassTests(AlarmsCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(unlock_all)

    def test_it_checks_the_alarms_at_once_and_says_so_on_its_row(self):
        self.sample(5.5)                                    # a critical pH: the real pass opens its alarm
        made = make(1, run_pass=engine.run_once)
        self.assertEqual(made.run(), 0)
        self.assertTrue(Alarm.objects.filter(severity='critical', source='water_limit').exists())
        row = AlarmWorkerStatus.objects.get(name='alarms')
        self.assertEqual((row.state, row.failed_steps, row.consecutive_failures, row.stale_after_seconds),
                         ('stopped', '', 0, 45))
        self.assertIsNotNone(row.last_pass_at)
        self.assertEqual(row.last_ok_pass_at, row.last_pass_at)
        self.assertIsNotNone(row.last_pass_ms)
        self.assertTrue(row.host and row.pid)


class LoopTests(WorkerCase):
    def test_passes_follow_the_sweep_and_a_look_every_tick_keeps_the_row_alive(self):
        made = make(40)
        beats = []
        made.stop.on_wait = lambda n: beats.append(self.row().heartbeat_at)
        self.assertEqual(made.run(), 0)
        self.assertEqual(made.run_pass.call_count, 3)                  # at 0, 15 and 30 s of the 40
        self.assertEqual(set(made.stop.waits), {1.0})
        self.assertEqual(len(beats), 40)

    def test_a_server_clock_that_jumps_neither_stops_nor_hurries_the_passes(self):
        real = timezone.now()
        jumps = itertools.cycle([real - timedelta(hours=1), real + timedelta(days=1)])
        with mock.patch.object(timezone, 'now', side_effect=lambda: next(jumps)):
            made = make(40)
            self.assertEqual(made.run(), 0)
        self.assertEqual(made.run_pass.call_count, 3)
        with connection.cursor() as cursor:
            cursor.execute('SELECT now()')
            database_now = cursor.fetchone()[0]
        self.assertLess(abs(self.row().last_pass_at - database_now), timedelta(minutes=1))   # the database's clock

    def test_a_pass_with_a_failed_step_is_no_good_pass(self):
        made = make(1, run_pass=mock.Mock(return_value=engine.Summary(failed_steps=['water'])))
        made.run()
        row = self.row()
        self.assertEqual((row.failed_steps, row.last_ok_pass_at), ('water', None))
        self.assertIsNotNone(row.last_pass_at)

    def test_passes_that_fail_whole_are_counted_and_the_process_exits_after_max_failures(self):
        made = make(500, run_pass=mock.Mock(side_effect=RuntimeError('the pass broke')))
        with self.assertLogs('alarms.worker', level='ERROR') as logged:
            self.assertEqual(made.run(), 1)
        self.assertEqual(made.run_pass.call_count, 5)
        row = self.row()
        self.assertEqual((row.consecutive_failures, row.last_error), (5, 'RuntimeError: the pass broke'))
        self.assertIn('failed 5 passes in a row', '\n'.join(logged.output))

    def test_a_good_pass_between_failures_starts_the_count_again(self):
        results = [RuntimeError('a'), RuntimeError('b'), engine.Summary()] * 3 + [RuntimeError('c')] * 5
        made = make(1000, run_pass=mock.Mock(side_effect=results))
        with self.assertLogs('alarms.worker', level='ERROR'):
            self.assertEqual(made.run(), 1)
        self.assertEqual(made.run_pass.call_count, 14)

    def test_the_database_lost_is_tried_again_with_a_growing_wait_and_the_process_exits_after_a_minute(self):
        made = make(100, cls=DownWorker)
        with self.assertLogs('alarms.worker', level='ERROR') as logged:
            self.assertEqual(made.run(), 1)
        self.assertEqual(made.stop.waits, [1, 2, 4, 8, 10, 10, 10, 10, 10])
        self.assertEqual(made.reset.call_count, 10)
        self.assertEqual(made.run_pass.call_count, 0)
        self.assertIn('has not reached the database for 65 s', '\n'.join(logged.output))

    def test_the_database_back_the_worker_takes_the_lock_again_and_passes(self):
        def back(n):
            if n == 3:
                made.down = False
        made = make(20, cls=DownWorker, on_wait=back)
        with self.assertLogs('alarms.worker', level='ERROR'):
            self.assertEqual(made.run(), 0)
        self.assertEqual(made.stop.waits[:3], [1, 2, 4])
        self.assertEqual(set(made.stop.waits[3:]), {1.0})             # the tick again once it is back
        self.assertEqual(made.run_pass.call_count, 2)                   # at once, and one sweep later
        self.assertEqual(self.row().state, 'stopped')

    def test_stopped_during_a_pass_the_pass_finishes_its_row_says_stopped_and_the_lock_is_let_go(self):
        def pass_then_signal():
            made.stop.set()                                   # SIGTERM while the pass runs
            return engine.Summary()
        made = make(100, run_pass=mock.Mock(side_effect=pass_then_signal))
        self.assertEqual(made.run(), 0)
        row = self.row()
        self.assertEqual(row.state, 'stopped')
        self.assertIsNotNone(row.last_ok_pass_at)
        with other_session() as other:
            self.assertTrue(other.execute('SELECT pg_try_advisory_lock(%s)', [worker.LOCK]).fetchone()[0])

    def test_a_second_worker_stands_by_while_the_first_holds_the_lock_and_takes_over_when_it_goes(self):
        first = other_session()
        self.addCleanup(first.close)
        first.execute('SELECT pg_advisory_lock(%s)', [worker.LOCK])

        def first_goes(n):
            if n == 5:
                first.close()                                  # the first worker's session ends (stopped, killed)
                lock_free()
        made = make(10, on_wait=first_goes)
        with self.assertLogs('alarms.worker', level='INFO') as logged:
            self.assertEqual(made.run(), 0)
        self.assertEqual(made.run_pass.call_count, 1)                  # only once it held the lock
        self.assertIn("'alarms' stands by", '\n'.join(logged.output))
        self.assertEqual(self.row().state, 'stopped')

    def test_its_session_is_named_bounded_and_finds_a_dead_peer(self):
        made = make(1)
        self.assertTrue(made._lead())
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('application_name'), current_setting('statement_timeout'), "
                           "current_setting('lock_timeout'), current_setting('tcp_keepalives_idle')")
            self.assertEqual(cursor.fetchone(), ('alarm-worker', '20s', '5s', '15'))


class HangTests(WorkerCase):
    def test_a_pass_that_hangs_ends_the_process(self):
        made = make(1)
        self.assertFalse(made.check_hang())                             # no pass under way
        made._pass_started = made.clock() - 119
        self.assertFalse(made.check_hang())
        made._pass_started = made.clock() - 121
        with self.assertLogs('alarms.worker', level='CRITICAL'):
            self.assertTrue(made.check_hang())
        made.exit_now.assert_called_once_with(1)


class TimingTests(TestCase):
    def test_nonsense_is_refused_at_start(self):
        for wrong in ({'tick': 0}, {'sweep': 0.5}, {'stale_after': 15}, {'backoff_max': 0.5}, {'max_failures': 0},
                      {'db_down_exit': 0}, {'hang_exit': 10}, {'lock_timeout': 0}):
            with self.subTest(wrong=wrong), self.assertRaises(ImproperlyConfigured):
                worker.Timing(**{**TIMING, **wrong})

    def test_the_settings_are_the_deployments(self):
        self.assertEqual(worker.Timing.from_settings(), worker.Timing(**settings.ALARM_WORKER))


class HealthTests(WorkerCase):
    def health(self):
        out, err = StringIO(), StringIO()
        try:
            call_command('alarm_worker_health', stdout=out, stderr=err)
        except SystemExit as stop:
            return stop.code, err.getvalue()
        return 0, out.getvalue()

    def status(self, seconds_ago, ok_seconds_ago='same', state='running', steps=''):
        now = timezone.now()
        at = now - timedelta(seconds=seconds_ago) if seconds_ago is not None else None
        ok = at if ok_seconds_ago == 'same' else (now - timedelta(seconds=ok_seconds_ago) if ok_seconds_ago else None)
        AlarmWorkerStatus.objects.update_or_create(name='alarms', defaults=dict(
            state=state, started_at=now - timedelta(hours=1), heartbeat_at=now, last_pass_at=at, last_ok_pass_at=ok,
            failed_steps=steps, stale_after_seconds=45))

    def test_it_says_whether_the_alarms_are_being_checked(self):
        cases = [
            (lambda: None, 1, 'no alarm worker has ever run'),
            (lambda: self.status(5), 0, 'ok: the last alarm pass finished'),
            (lambda: self.status(60), 1, 'no alarm pass has finished for 60 s'),
            (lambda: self.status(None), 1, 'no alarm pass has finished for ever'),
            (lambda: self.status(5, state='stopped'), 1, 'the alarm worker stopped'),
            (lambda: self.status(5, ok_seconds_ago=None, steps='water'), 1, 'these steps fail: water'),
            (lambda: self.status(5, ok_seconds_ago=50, steps='notify'), 1, 'these steps fail: notify'),
            (lambda: self.status(5, ok_seconds_ago=30, steps='notify'), 0, 'ok'),
        ]
        for prepare, code, said in cases:
            with self.subTest(said=said):
                AlarmWorkerStatus.objects.all().delete()
                prepare()
                found = self.health()
                self.assertEqual(found[0], code)
                self.assertIn(said, found[1])

    def test_the_verdict_names_since_when_the_alarms_are_unchecked(self):
        self.status(60, ok_seconds_ago=90)
        found = watch.state()
        self.assertEqual(found.reason, watch.STALE)
        self.assertEqual(found.since, self.row().last_ok_pass_at)
        self.assertFalse(found.checked)


class CommandTests(WorkerCase):
    def test_the_command_runs_the_worker_and_a_signal_stops_it(self):
        handlers = {}
        with mock.patch('signal.signal', side_effect=lambda number, handler: handlers.update({number: handler})), \
                mock.patch.object(worker.Worker, 'run', autospec=True, return_value=0) as run:
            call_command('run_alarm_worker')
        made = run.call_args.args[0]
        self.assertFalse(made.stop.is_set())
        handlers[signal.SIGTERM](signal.SIGTERM, None)
        self.assertTrue(made.stop.is_set())

    def test_a_worker_that_must_be_started_again_exits_1(self):
        with mock.patch('signal.signal'), mock.patch.object(worker.Worker, 'run', return_value=1), \
                self.assertRaises(SystemExit) as stop:
            call_command('run_alarm_worker')
        self.assertEqual(stop.exception.code, 1)

    def test_run_alarms_runs_one_pass_and_no_loop(self):
        out = StringIO()
        with mock.patch.object(engine, 'run_once', return_value=engine.Summary()) as one:
            call_command('run_alarms', stdout=out)
        self.assertEqual(one.call_count, 1)
        with self.assertRaises(TypeError):
            call_command('run_alarms', loop=1)


class ComposeTests(TestCase):
    def test_the_compose_service_runs_the_worker_restarts_it_and_checks_its_health(self):
        text = (pathlib.Path(settings.BASE_DIR) / 'docker-compose.yml').read_text(encoding='utf-8')
        block = re.search(r'^  alarms:\n((?:    .*\n|\s*\n)+)', text, re.MULTILINE).group(1)
        for needed in ('command: ["python", "manage.py", "run_alarm_worker"]', 'restart: unless-stopped',
                       'test: ["CMD", "python", "manage.py", "alarm_worker_health"]', 'depends_on: [db]',
                       'stop_grace_period: 30s'):
            self.assertIn(needed, block)

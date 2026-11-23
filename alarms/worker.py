"""The alarm worker (manage.py run_alarm_worker; the compose service `alarms`): the one process that keeps the alarms
checked, a pass of alarms/engine.py at a time, for as long as it runs.

- **One active worker.** It holds a session-level advisory lock (`LOCK`); a second worker started beside it waits as a
  hot standby and takes over within a tick of the first one's session ending (stopped, killed, its connection lost).
  The database ends a dead client's session by TCP keepalives the worker sets on its own session (`_session`), so a
  worker cut off from the network does not keep the lock for the kernel's two hours.
- **When it passes.** At once when it starts, then at least every `sweep` seconds (what time alone moves: a value going
  stale, the delays, escalation).
- **Its own row** (alarms.AlarmWorkerStatus, `alarm_worker_status`): running or stopped, when it last finished a pass and
  a pass with no failed step, how long the pass took, what failed, and after how long without a pass the alarms count as
  unchecked (`stale_after`). The pages and the health check read it (alarms/watch.py), on the database's clock.
- **What stops it, and what it survives.** The database unreachable: the connection is closed and tried again after
  the tick, doubled each time up to `backoff_max`; unreachable for `db_down_exit` seconds: the process exits with 1 and
  Docker starts it again (`restart: unless-stopped`). A pass that fails whole (a step's failure is the engine's: logged,
  alarmed, the other steps go on): logged and counted; `max_failures` in a row: exit 1. A pass still running after
  `hang_exit` seconds (a hang the statement timeout did not end): the watchdog thread ends the process with 1. SIGTERM
  or SIGINT: the pass under way finishes, the row says stopped, the lock is let go, exit 0. The intervals are counted on
  the monotonic clock, so a server clock that jumps neither stops nor hurries the passes.
The timings are the deployment's (settings.ALARM_WORKER), refused at start when they make no sense (`Timing`)."""
import logging
import os
import socket
import threading
import time
from dataclasses import dataclass

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import InterfaceError, OperationalError, connection
from django.db.models import F
from django.db.models.functions import Now

from . import engine
from .models import AlarmWorkerStatus, WorkerState

logger = logging.getLogger(__name__)
LOCK = 4_261_607_202          # the worker's session-level advisory lock (one active worker); engine.LOCK is the steps'
DEFAULT_NAME = 'alarms'
MS = 1000                     # milliseconds in a second: the database's settings are in ms
# The TCP keepalives of the worker's session, as shares of its stale_after: the first probe after a third of it idle, then
# one every ninth, three of them; so the database ends a dead worker's session, and lets its lock go to a standby,
# within two thirds of stale_after: before the pages call the alarms unchecked.
KEEPALIVE = {'idle': 3, 'interval': 9, 'count': 3}
DATABASE_DOWN = (OperationalError, InterfaceError)


def _fit(field, text):
    return str(text)[:AlarmWorkerStatus._meta.get_field(field).max_length]


@dataclass(frozen=True)
class Timing:
    """settings.ALARM_WORKER, checked: a worker never starts on nonsense (a sweep shorter than the tick, a staleness the
    passes cannot keep up with)."""

    tick: float
    sweep: float
    stale_after: int
    db_down_exit: float
    backoff_max: float
    max_failures: int
    hang_exit: float
    statement_timeout: float
    lock_timeout: float

    def __post_init__(self):
        problems = []
        if not self.tick > 0:
            problems.append('tick must be above 0')
        if not self.sweep >= self.tick:
            problems.append('sweep must be at least the tick')
        if not self.stale_after > self.sweep:
            problems.append('stale_after must be longer than the sweep')
        if not self.backoff_max >= self.tick:
            problems.append('backoff_max must be at least the tick')
        if not self.db_down_exit > 0 or not self.max_failures >= 1:
            problems.append('db_down_exit must be above 0 and max_failures at least 1')
        if not self.hang_exit > self.statement_timeout > 0 or not self.lock_timeout > 0:
            problems.append('hang_exit must be longer than statement_timeout, both and lock_timeout above 0')
        if problems:
            raise ImproperlyConfigured(f'settings.ALARM_WORKER: {"; ".join(problems)}.')

    @classmethod
    def from_settings(cls, **overrides):
        return cls(**{**settings.ALARM_WORKER, **overrides})


def _reset():
    """Closes the default connection after a database error: the next statement opens a new one."""
    try:
        connection.close()
    except Exception:
        logger.warning('Closing the alarm worker\'s broken connection failed; a new one is opened all the same.',
                       exc_info=True)
        connection.connection = None


class Worker:
    """One alarm worker: `run()` until `stop` is set (0) or until it must be started again (1). The pass, the clock, the
    reset of a broken connection and the process's end are given in for the tests; by default the engine's pass, the
    monotonic clock, connection.close and os._exit."""

    def __init__(self, name=DEFAULT_NAME, timing=None, *, run_pass=None, clock=time.monotonic, stop=None, reset=_reset,
                 exit_now=os._exit):
        self.name = name
        self.timing = timing or Timing.from_settings()
        self.run_pass = run_pass or engine.run_once
        self.clock = clock
        self.stop = stop or threading.Event()
        self.reset = reset
        self.exit_now = exit_now
        self.leading = False
        self._standby_said = False
        self._pass_started = None
        self._done = threading.Event()         # the watchdog's own: set when run() ends

    # ---- the loop -------------------------------------------------------------------------------------------------------
    def run(self):
        watchdog = threading.Thread(target=self._watch, name=f'alarm-worker-watchdog-{self.name}', daemon=True)
        watchdog.start()
        try:
            return self._loop()
        finally:
            self._finish()
            self._done.set()
            watchdog.join()

    def _loop(self):
        last_pass, down_since, tries, failures = None, None, 0, 0
        while not self.stop.is_set():
            try:
                if not self._lead():
                    self.stop.wait(self.timing.tick)
                    continue
                if last_pass is None or self.clock() - last_pass >= self.timing.sweep:
                    last_pass = self.clock()
                    self._pass()
                    failures = 0
                else:
                    self._status(heartbeat_at=Now())
                down_since, tries = None, 0
            except DATABASE_DOWN as error:
                self._lost(error)
                now = self.clock()
                down_since = now if down_since is None else down_since
                if now - down_since >= self.timing.db_down_exit:
                    logger.critical('The alarm worker %r has not reached the database for %.0f s; it exits to be started '
                                    'again.', self.name, now - down_since)
                    return 1
                self.stop.wait(min(self.timing.backoff_max, self.timing.tick * 2 ** tries))
                tries += 1
                continue
            except Exception as error:
                failures += 1
                logger.exception('An alarm pass of the worker %r failed whole (%d in a row).', self.name, failures)
                self._failed(error)
                if failures >= self.timing.max_failures:
                    logger.critical('The alarm worker %r failed %d passes in a row; it exits to be started again.',
                                    self.name, failures)
                    return 1
            self.stop.wait(self.timing.tick)
        return 0

    def _pass(self):
        self._pass_started = self.clock()
        try:
            summary = self.run_pass()
        finally:
            took = self.clock() - self._pass_started
            self._pass_started = None
        fields = {'heartbeat_at': Now(), 'last_pass_at': Now(), 'last_pass_ms': round(took * MS),
                  'failed_steps': _fit('failed_steps', ', '.join(summary.failed_steps)), 'consecutive_failures': 0}
        if not summary.failed_steps:
            fields['last_ok_pass_at'] = Now()
        self._status(**fields)
        if summary.opened or summary.cleared or summary.failed_steps:
            logger.info('Alarm pass: %s', summary)
        return summary

    # ---- the lock, the session and the row -----------------------------------------------------------------------------
    def _lead(self):
        """Whether this worker is the active one: it holds the lock (taken now if free; its session set up and its row
        written as running), or another worker does and this one stands by."""
        if self.leading:
            return True
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_try_advisory_lock(%s)', [LOCK])
            got = cursor.fetchone()[0]
        if not got:
            if not self._standby_said:
                logger.info('Another alarm worker holds the lock; %r stands by.', self.name)
                self._standby_said = True
            return False
        self._session()
        AlarmWorkerStatus.objects.update_or_create(name=self.name, defaults={
            'state': WorkerState.RUNNING, 'host': _fit('host', socket.gethostname()), 'pid': os.getpid(),
            'started_at': Now(), 'heartbeat_at': Now(), 'consecutive_failures': 0, 'last_error': '',
            'stale_after_seconds': self.timing.stale_after})
        self.leading, self._standby_said = True, False
        logger.info('The alarm worker %r checks the alarms (pid %d).', self.name, os.getpid())
        return True

    def _session(self):
        """The worker's own session: named, its statements and lock waits bounded, an idle transaction ended, and a dead
        peer found within about half a minute either way (TCP keepalives), so a lost worker's lock is let go."""
        timing = self.timing
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config('application_name', 'alarm-worker', false), "
                           "set_config('statement_timeout', %s, false), set_config('lock_timeout', %s, false), "
                           "set_config('idle_in_transaction_session_timeout', %s, false), "
                           "set_config('tcp_keepalives_idle', %s, false), "
                           "set_config('tcp_keepalives_interval', %s, false), "
                           "set_config('tcp_keepalives_count', %s, false)",
                           [str(round(timing.statement_timeout * MS)), str(round(timing.lock_timeout * MS)),
                            str(round(timing.hang_exit * MS)), str(round(timing.stale_after / KEEPALIVE['idle'])),
                            str(max(1, round(timing.stale_after / KEEPALIVE['interval']))), str(KEEPALIVE['count'])])

    def _status(self, **fields):
        AlarmWorkerStatus.objects.filter(name=self.name).update(**fields)

    def _failed(self, error):
        try:
            self._status(heartbeat_at=Now(), consecutive_failures=F('consecutive_failures') + 1,
                         last_error=_fit('last_error', f'{type(error).__name__}: {error}'))
        except Exception:
            logger.warning('The alarm worker %r could not write its failure on its row.', self.name, exc_info=True)

    def _lost(self, error):
        logger.error('The alarm worker %r lost the database (%s: %s); it tries again.', self.name,
                     type(error).__name__, str(error)[:200])
        self.leading = False                 # the session and its lock are gone with the connection
        self.reset()

    def _finish(self):
        """Stopped: the row says so and the lock is let go (best effort: a database that is gone has let it go)."""
        if not self.leading:
            return
        try:
            self._status(state=WorkerState.STOPPED, heartbeat_at=Now())
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_advisory_unlock(%s)', [LOCK])
        except Exception:
            logger.warning('The alarm worker %r could not say it stopped.', self.name, exc_info=True)
        self.leading = False
        logger.info('The alarm worker %r stopped.', self.name)

    # ---- the watchdog ---------------------------------------------------------------------------------------------------
    def _watch(self):
        while not self._done.wait(self.timing.tick):
            self.check_hang()

    def check_hang(self):
        """Ends the process (1) when a pass has run longer than `hang_exit`: whatever it waits for, Docker's restart is a
        surer way out. Returns whether it did."""
        started = self._pass_started
        if started is None or self.clock() - started < self.timing.hang_exit:
            return False
        logger.critical('An alarm pass of the worker %r has run for %.0f s; the process exits to be started again.',
                        self.name, self.clock() - started)
        logging.shutdown()
        self.exit_now(1)
        return True

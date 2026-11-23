"""The alarm worker as it runs on a server: the real command (manage.py run_alarm_worker) in a process of its own on the
test database, stopped by SIGTERM, killed by SIGKILL, its database session cut, and two of them side by side. What the
pages and the health check say is read from the database the way they read it (alarms/watch.py)."""
import os
import signal
import subprocess
import sys
import tempfile
import time
from io import StringIO

from django.conf import settings
from django.core.management import call_command
from django.db import connection
from django.test import TransactionTestCase

from .. import watch, worker
from ..models import AlarmWorkerStatus

FAST = {'ALARM_WORKER_TICK': '0.2', 'ALARM_WORKER_SWEEP': '1', 'ALARM_WORKER_STALE_AFTER': '3'}
START = 90                     # seconds a process may take to start (Django's checks on a loaded runner) and pass once


def until(found, seconds, what):
    """found()'s first true value within `seconds`, else the test fails naming `what`."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        value = found()
        if value:
            return value
        time.sleep(0.1)
    raise AssertionError(f'not within {seconds} s: {what}')


def lock_free():
    """Whether the worker's lock is free (taken and let go at once from this session)."""
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_try_advisory_lock(%s)', [worker.LOCK])
        got = cursor.fetchone()[0]
        cursor.execute('SELECT pg_advisory_unlock_all()')
    return got


class ProcessTests(TransactionTestCase):
    def start(self):
        log = tempfile.TemporaryFile()
        self.addCleanup(log.close)
        process = subprocess.Popen(
            [sys.executable, 'manage.py', 'run_alarm_worker'], cwd=settings.BASE_DIR, stdout=log,
            stderr=subprocess.STDOUT, env={**os.environ, 'DB_NAME': connection.settings_dict['NAME'], **FAST,
                                           'PYTHONUNBUFFERED': '1'})
        process.log = log
        self.addCleanup(self.end, process)
        return process

    def end(self, process):
        if process.poll() is None:
            process.kill()
            process.wait(30)

    def said(self, process):
        process.log.seek(0)
        return process.log.read().decode('utf-8', 'replace')

    def checked(self, pid=None):
        found = watch.state()
        return found.checked and (pid is None or found.row.pid == pid)

    def test_sigterm_finishes_the_pass_says_stopped_and_exits_0(self):
        process = self.start()
        until(lambda: self.checked(process.pid), START, 'the worker checking the alarms')
        process.send_signal(signal.SIGTERM)
        self.assertEqual(process.wait(30), 0, self.said(process))
        self.assertEqual(watch.state().reason, watch.STOPPED)
        self.assertEqual(AlarmWorkerStatus.objects.get().state, 'stopped')

    def test_a_killed_worker_is_seen_as_not_checking_within_stale_after_and_its_lock_is_let_go(self):
        process = self.start()
        until(lambda: self.checked(process.pid), START, 'the worker checking the alarms')
        process.kill()
        process.wait(30)
        killed = time.monotonic()
        until(lambda: watch.state().reason == watch.STALE, 10, 'the alarms said unchecked')
        self.assertLess(time.monotonic() - killed, 3 + 2)           # stale_after 3 s, read on the database's clock
        with self.assertRaises(SystemExit) as stop:
            call_command('alarm_worker_health', stderr=StringIO())
        self.assertEqual(stop.exception.code, 1)
        with connection.cursor() as cursor:
            until(lambda: cursor.execute('SELECT pg_try_advisory_lock(%s)', [worker.LOCK]) or cursor.fetchone()[0],
                  10, 'the dead worker\'s lock let go')
            cursor.execute('SELECT pg_advisory_unlock_all()')

    def test_a_standby_takes_over_within_seconds_of_the_first_being_killed(self):
        first = self.start()
        until(lambda: self.checked(first.pid), START, 'the first worker checking the alarms')
        second = self.start()
        until(lambda: 'stands by' in self.said(second), START, 'the second worker standing by')
        self.assertEqual(AlarmWorkerStatus.objects.get().pid, first.pid)
        first.kill()
        first.wait(30)
        killed = time.monotonic()
        until(lambda: self.checked(second.pid), 10, 'the standby checking the alarms')
        took = time.monotonic() - killed
        sys.stderr.write(f'\n[alarm worker] standby took over {took:.2f} s after the first was killed\n')
        self.assertLess(took, 5)

    def test_a_cut_database_session_is_opened_again_and_the_passes_go_on(self):
        process = self.start()
        until(lambda: self.checked(process.pid), START, 'the worker checking the alarms')
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE application_name = "
                           "'alarm-worker' AND datname = current_database()")
            self.assertEqual(cursor.rowcount, 1)
        cut = AlarmWorkerStatus.objects.get().last_pass_at
        until(lambda: AlarmWorkerStatus.objects.get().last_pass_at > cut and self.checked(process.pid), 20,
              'a pass after the session was cut')
        self.assertIsNone(process.poll(), self.said(process))
        self.assertIn('lost the database', self.said(process))

import os
import subprocess
import sys
import unittest
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase, TestCase, TransactionTestCase


def database_setting(key, **env):
    """The default database's `key` as config/settings.py computes it in a fresh interpreter with `env` set."""
    code = ('import json, config.settings as s; '
            f'print(json.dumps(s.DATABASES["default"][{key!r}]))')
    run = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, check=True,
                         cwd=settings.BASE_DIR, env={**os.environ, **env})
    return run.stdout.strip()


class PersistentConnectionsTests(SimpleTestCase):
    """DB_CONN_MAX_AGE keeps a database connection open between requests for that many seconds; without it each
    request opens its own (Django's default, 0). A kept connection is checked before reuse."""

    def test_default_is_one_connection_per_request(self):
        env = {k: v for k, v in os.environ.items() if k != 'DB_CONN_MAX_AGE'}
        self.assertEqual(subprocess.run(
            [sys.executable, '-c', 'import config.settings as s; print(s.DATABASES["default"]["CONN_MAX_AGE"])'],
            capture_output=True, text=True, check=True, cwd=settings.BASE_DIR, env=env).stdout.strip(), '0')

    def test_environment_sets_the_age(self):
        self.assertEqual(database_setting('CONN_MAX_AGE', DB_CONN_MAX_AGE='60'), '60')

    def test_kept_connections_are_health_checked(self):
        self.assertEqual(database_setting('CONN_HEALTH_CHECKS', DB_CONN_MAX_AGE='60'), 'true')


def setting(name, **env):
    """config/settings.py's `name` as a fresh interpreter computes it with `env` (and no inherited value of those keys)."""
    base = {k: v for k, v in os.environ.items() if k not in env and k != 'COMPANY_TIME_ZONE'}
    run = subprocess.run([sys.executable, '-c', f'import config.settings as s; print(s.{name})'], capture_output=True,
                         text=True, check=True, cwd=settings.BASE_DIR, env={**base, **env})
    return run.stdout.strip()


class CompanyTimeZoneTests(SimpleTestCase):
    """The company's time zone (COMPANY_TIME_ZONE): a new site's and the one migration 0028 gives a site without one.
    Europe/Oslo unless the environment names another; the server's own clock (TIME_ZONE) stays UTC."""

    def test_default_is_oslo_and_the_environment_names_another(self):
        self.assertEqual((setting('COMPANY_TIME_ZONE'), setting('TIME_ZONE')), ('Europe/Oslo', 'UTC'))
        self.assertEqual(setting('COMPANY_TIME_ZONE', COMPANY_TIME_ZONE='Europe/Istanbul'), 'Europe/Istanbul')


class ParallelRunnerTests(SimpleTestCase):
    """`manage.py test --parallel` copies the test database for each worker, which PostgreSQL does only while nobody is
    connected to it, and TimescaleDB's job scheduler stays connected to every database with the extension: on a server
    that runs the scheduler (the development server) the copy fails half-way, so the runner says what to run instead
    before it creates anything."""

    def runner(self, parallel):
        from config.test_runner import FastPasswordRunner
        runner = FastPasswordRunner(parallel=parallel, verbosity=0)
        runner.parallel = parallel
        return runner

    def test_parallel_on_a_server_with_the_scheduler_is_refused_before_any_database_is_made(self):
        from django.core.exceptions import ImproperlyConfigured
        from django.test.runner import DiscoverRunner
        with mock.patch('config.test_runner.runs_the_scheduler', return_value=True), \
                mock.patch.object(DiscoverRunner, 'setup_databases') as made:
            with self.assertRaisesMessage(ImproperlyConfigured, 'scripts/test.sh'):
                self.runner(4).setup_databases()
        made.assert_not_called()

    def test_parallel_on_a_server_without_the_scheduler_and_one_process_anywhere_go_ahead(self):
        from django.test.runner import DiscoverRunner
        for parallel, scheduler in ((4, False), (1, True)):
            with self.subTest(parallel=parallel, scheduler=scheduler), \
                    mock.patch('config.test_runner.runs_the_scheduler', return_value=scheduler), \
                    mock.patch.object(DiscoverRunner, 'setup_databases', return_value='made') as made:
                self.assertEqual(self.runner(parallel).setup_databases(), 'made')
                made.assert_called_once()

    def test_the_scheduler_is_read_from_the_servers_setting(self):
        from config.test_runner import runs_the_scheduler
        for value, runs in (('16', True), ('0', False), (None, False)):
            cursor = mock.MagicMock()
            cursor.__enter__.return_value.fetchone.return_value = (value,)
            connection = mock.Mock(vendor='postgresql', _nodb_cursor=mock.Mock(return_value=cursor))
            with self.subTest(value=value):
                self.assertIs(runs_the_scheduler(connection), runs)
        self.assertIs(runs_the_scheduler(mock.Mock(vendor='sqlite')), False)


class ParallelScheduleTests(SimpleTestCase):
    """The parallel run hands its workers a class at a time, but a TransactionTestCase's tests share nothing (each starts
    from a database emptied, or emptied and restored, after the one before), so they are handed out one by one: a class
    of migration tests of three minutes each no longer keeps one worker busy long after the others are done."""

    def test_a_transaction_test_case_is_handed_out_test_by_test_and_a_test_case_whole(self):
        from config.test_runner import FastPasswordRunner

        class _Flushed(TransactionTestCase):     # in here, so the run does not find them as tests of their own
            def test_one(self): pass

            def test_two(self): pass

            def test_three(self): pass

        class _Rolledback(TestCase):
            def test_one(self): pass

            def test_two(self): pass

        flushed = unittest.TestSuite(_Flushed(name) for name in ('test_one', 'test_two', 'test_three'))
        rolledback = unittest.TestSuite(_Rolledback(name) for name in ('test_one', 'test_two'))
        suite = FastPasswordRunner.parallel_test_suite([rolledback, flushed], processes=2)
        self.assertEqual([[test.id().rsplit('.', 2)[1:] for test in subsuite] for subsuite in suite.subsuites], [
            [['_Rolledback', 'test_one'], ['_Rolledback', 'test_two']],
            [['_Flushed', 'test_one']], [['_Flushed', 'test_two']], [['_Flushed', 'test_three']],
        ])

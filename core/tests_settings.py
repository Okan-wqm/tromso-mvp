import os
import subprocess
import sys

from django.conf import settings
from django.test import SimpleTestCase


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
    """The company's time zone (COMPANY_TIME_ZONE): a new site's and the one migration 0030 gives a site without one.
    Europe/Oslo unless the environment names another; the server's own clock (TIME_ZONE) stays UTC."""

    def test_default_is_oslo_and_the_environment_names_another(self):
        self.assertEqual((setting('COMPANY_TIME_ZONE'), setting('TIME_ZONE')), ('Europe/Oslo', 'UTC'))
        self.assertEqual(setting('COMPANY_TIME_ZONE', COMPANY_TIME_ZONE='Europe/Istanbul'), 'Europe/Istanbul')

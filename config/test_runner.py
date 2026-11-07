from django.core.exceptions import ImproperlyConfigured
from django.db import connections
from django.test.runner import DiscoverRunner
from django.test.utils import override_settings


def runs_the_scheduler(connection):
    """Whether the database server runs TimescaleDB's job scheduler, which keeps a connection open to every database
    with the extension (it does unless timescaledb.max_background_workers is 0)."""
    if connection.vendor != 'postgresql':
        return False
    with connection._nodb_cursor() as cursor:
        cursor.execute("SELECT current_setting('timescaledb.max_background_workers', true)")
        value = cursor.fetchone()[0]
    return value not in (None, '0')


class FastPasswordRunner(DiscoverRunner):
    """Password hashing is made deliberately slow; tests create many users and do not need that."""

    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        self._fast_hasher = override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
        self._fast_hasher.enable()

    def teardown_test_environment(self, **kwargs):
        self._fast_hasher.disable()
        super().teardown_test_environment(**kwargs)

    def setup_databases(self, **kwargs):
        # The parallel workers each get a copy of the test database, and PostgreSQL copies a database only while
        # nobody is connected to it: on a server running TimescaleDB's scheduler the copy would fail half-way.
        if self.parallel > 1 and any(runs_the_scheduler(connections[alias]) for alias in connections):
            raise ImproperlyConfigured(
                'manage.py test --parallel needs a database server without TimescaleDB\'s job scheduler '
                '(timescaledb.max_background_workers=0), since it copies the test database for each worker: run '
                'scripts/test.sh, which starts one, or leave out --parallel (README, Tests).')
        return super().setup_databases(**kwargs)

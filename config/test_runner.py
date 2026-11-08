import warnings

from django.core.exceptions import ImproperlyConfigured
from django.db import connections
from django.test import TestCase, TransactionTestCase
from django.test.runner import DiscoverRunner, ParallelTestSuite
from django.test.utils import override_settings

# Third-party code's own warnings that the strict filters below would otherwise turn into errors: reported (once per
# place) but not failing the run. Each is (category, module regex, message regex, reason). Only a warning raised inside
# the library for its own use belongs here; one our call causes is fixed in our code (README, CI and dependency
# updates). Empty: the whole suite runs without one.
THIRD_PARTY_WARNINGS = []


def strict_warnings():
    """Deprecations become errors: DeprecationWarning and PendingDeprecationWarning, so also every Django
    RemovedInDjango*Warning (RemovedInNextVersionWarning is a DeprecationWarning, RemovedInDjango2028Warning a
    PendingDeprecationWarning), wherever they are raised, so a warning a library attributes to its own frame while our
    call caused it fails too. So does Django's "received a naive datetime" RuntimeWarning: a naive datetime stored with
    time zone support on is read as the default time zone's, a silent shift. The listed third-party ones stay warnings.
    """
    warnings.simplefilter('error', DeprecationWarning)
    warnings.simplefilter('error', PendingDeprecationWarning)
    warnings.filterwarnings('error', r'.*received a naive datetime', RuntimeWarning)
    for category, module, message, _reason in THIRD_PARTY_WARNINGS:
        warnings.filterwarnings('default', message, category, module)


def strict_warnings_in_worker(*args):
    """A parallel worker started by spawn or forkserver gets the filters too (a forked one inherits them)."""
    strict_warnings()


def runs_the_scheduler(connection):
    """Whether the database server runs TimescaleDB's job scheduler, which keeps a connection open to every database
    with the extension (it does unless timescaledb.max_background_workers is 0)."""
    if connection.vendor != 'postgresql':
        return False
    with connection._nodb_cursor() as cursor:
        cursor.execute("SELECT current_setting('timescaledb.max_background_workers', true)")
        value = cursor.fetchone()[0]
    return value not in (None, '0')


class TestByTestParallelSuite(ParallelTestSuite):
    """The parallel run hands its workers a class at a time (a TestCase's tests share its class's data). A
    TransactionTestCase's tests share nothing: each starts from the database emptied (and, with serialized_rollback,
    restored) after the one before. So they are handed out one by one, and a class of migration tests of minutes each no
    longer keeps one worker busy long after the others are done. They still come after every TestCase, as Django orders
    them, so no TestCase meets a database one of them has emptied."""
    process_setup = strict_warnings_in_worker

    def __init__(self, subsuites, *args, **kwargs):
        super().__init__(self.split(subsuites), *args, **kwargs)

    @staticmethod
    def split(subsuites):
        handed_out = []
        for subsuite in subsuites:
            tests = list(subsuite)
            if len(tests) > 1 and isinstance(tests[0], TransactionTestCase) and not isinstance(tests[0], TestCase):
                handed_out += [type(subsuite)([test]) for test in tests]
            else:
                handed_out.append(subsuite)
        return handed_out


class FastPasswordRunner(DiscoverRunner):
    """Password hashing is made deliberately slow; tests create many users and do not need that."""
    parallel_test_suite = TestByTestParallelSuite

    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        strict_warnings()
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

import warnings
from unittest import mock

from django.test import SimpleTestCase
from django.utils.deprecation import RemovedAfterNextVersionWarning, RemovedInNextVersionWarning

from config import test_runner

NAIVE = ('DateTimeField AttendanceRecord.clock_in received a naive datetime (2026-03-02 06:00:00) while time zone '
         'support is active.')


class StrictWarningsTests(SimpleTestCase):
    """Deprecations and naive datetimes fail the tests (config.test_runner.strict_warnings; README, CI and dependency
    updates)."""

    def test_the_running_suite_turns_a_deprecation_into_an_error(self):
        # the runner's filters, in whichever worker runs this test
        with self.assertRaises(DeprecationWarning):
            warnings.warn('old', DeprecationWarning)
        with self.assertRaises(RuntimeWarning):
            warnings.warn(NAIVE, RuntimeWarning)

    def test_deprecations_of_every_kind_are_errors_wherever_they_are_raised(self):
        with warnings.catch_warnings():
            warnings.resetwarnings()
            test_runner.strict_warnings()
            for category in (DeprecationWarning, PendingDeprecationWarning, RemovedInNextVersionWarning,
                             RemovedAfterNextVersionWarning):
                for module in ('farm.models', 'django.db.models.query', 'pypdf._reader'):
                    with self.subTest(category=category.__name__, module=module), self.assertRaises(category):
                        warnings.warn_explicit('old', category, 'x.py', 1, module=module)

    def test_a_naive_datetime_is_an_error_and_another_runtime_warning_is_not(self):
        with warnings.catch_warnings(record=True) as shown:
            warnings.resetwarnings()
            test_runner.strict_warnings()
            with self.assertRaises(RuntimeWarning):
                warnings.warn_explicit(NAIVE, RuntimeWarning, 'fields.py', 1, module='django.db.models.fields')
            warnings.warn_explicit('overflow', RuntimeWarning, 'x.py', 1, module='farm.water.chemistry')
        self.assertEqual([str(w.message) for w in shown], ['overflow'])

    def test_a_listed_third_party_warning_is_reported_not_raised(self):
        listed = [(DeprecationWarning, r'somelib\.', r'old api', 'its own use, fixed in the next release')]
        with mock.patch.object(test_runner, 'THIRD_PARTY_WARNINGS', listed), \
                warnings.catch_warnings(record=True) as shown:
            warnings.resetwarnings()
            test_runner.strict_warnings()
            warnings.warn_explicit('old api is going', DeprecationWarning, 'lib.py', 1, module='somelib.core')
            with self.assertRaises(DeprecationWarning):            # the same text from our code still fails
                warnings.warn_explicit('old api is going', DeprecationWarning, 'x.py', 1, module='farm.views')
        self.assertEqual([str(w.message) for w in shown], ['old api is going'])

    def test_every_listed_third_party_warning_names_a_library_and_a_reason(self):
        ours = ('config', 'core', 'farm', 'hr', 'sensors', 'monitoring', 'reports', 'tasks', 'inventory',
                'experiments', 'knowledge', 'messaging')
        for category, module, message, reason in test_runner.THIRD_PARTY_WARNINGS:
            with self.subTest(module=module):
                self.assertTrue(issubclass(category, Warning))
                self.assertTrue(module and not module.lstrip('^').startswith(ours), 'a library, never our code')
                self.assertTrue(reason.strip())

    def test_a_spawned_worker_installs_them_too(self):
        self.assertIs(test_runner.TestByTestParallelSuite.process_setup, test_runner.strict_warnings_in_worker)
        with warnings.catch_warnings():
            warnings.resetwarnings()
            test_runner.strict_warnings_in_worker()
            with self.assertRaises(PendingDeprecationWarning):
                warnings.warn('old', PendingDeprecationWarning)


class TestRunnerImageNameTests(SimpleTestCase):
    """The test runner's image has one name, scripts/testrunner/image.sh's (a tag hashed from what it is built from):
    scripts/test.sh, CI and every script of sensors-ingest/ that migrates a database ask that script. A script that
    wrote a name of its own (`balik-testrunner:latest`, built by nothing) failed at its migrate step."""

    def test_no_script_or_workflow_names_the_image_itself(self):
        from pathlib import Path

        from django.conf import settings
        root = Path(settings.BASE_DIR)
        named = []
        for pattern in ('scripts/**/*.sh', 'sensors-ingest/**/*.sh', 'chemcore/scripts/*.sh', '.github/**/*.yml',
                        'docker-compose.yml'):
            for path in root.glob(pattern):
                relative = path.relative_to(root).as_posix()
                if relative != 'scripts/testrunner/image.sh' and 'node_modules' not in relative \
                        and '/target/' not in relative and 'balik-testrunner' in path.read_text(encoding='utf-8'):
                    named.append(relative)
        self.assertEqual(named, [])
        self.assertIn('tag=balik-testrunner-chemcore:req-$hash',
                      (root / 'scripts' / 'testrunner' / 'image.sh').read_text(encoding='utf-8'))

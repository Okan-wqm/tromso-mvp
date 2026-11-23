"""The production settings (config/settings.py, the production block; README, Starting a production server). With DEBUG
off the server is HTTPS-only behind its proxy, takes its secrets from files, serves hashed static files, keeps the same
Content-Security-Policy, and refuses to start on an unsafe value: the deploy check, which the release step and the
production server itself run before anything is served (deploy/web/release.sh, deploy/web/gunicorn.conf.py)."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

# A safe production configuration, as deploy/farm.env.example and the secret files give it (values made up here).
PRODUCTION = {
    'DJANGO_DEBUG': '0', 'DJANGO_ALLOWED_HOSTS': 'farm.invalid',
    'DJANGO_SECRET_KEY': 'not-a-secret-' + 'abcdefghij' * 5, 'DJANGO_AUDIT_DIGEST_KEY': 'digest-' + 'klmnopqrst' * 4,
    'EMAIL_HOST': 'smtp.farm.invalid', 'DEFAULT_FROM_EMAIL': 'console@farm.invalid', 'PUBLIC_BASE_URL': 'https://farm.invalid',
}
OWN = ('DJANGO_', 'EMAIL_', 'GUNICORN_')
NAMED = ('PUBLIC_BASE_URL', 'DEFAULT_FROM_EMAIL', 'ACCOUNT_LINK_HOURS', 'PASSWORD_RESET_MAILS_PER_HOUR', 'DB_PASSWORD_FILE')


def run(arguments, **env):
    """`arguments` in a fresh interpreter that sees only the settings a test names (and the database's address)."""
    base = {k: v for k, v in os.environ.items() if not k.startswith(OWN) and k not in NAMED}
    return subprocess.run([sys.executable, *arguments], capture_output=True, text=True, cwd=settings.BASE_DIR,
                          env={**base, **env})


def computed(expression, **env):
    done = run(['-c', f'import json, config.settings as s; print(json.dumps({expression}))'], **env)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def deploy_check(**env):
    """`check --deploy --fail-level WARNING`, as the release step and the production server run it: the checks ask the
    database server only for its version, through its maintenance database."""
    done = run(['manage.py', 'check', '--deploy', '--fail-level', 'WARNING'], DB_NAME='postgres', **env)
    return done.returncode, done.stdout + done.stderr


class ProductionSettingsTests(SimpleTestCase):
    SECURITY = ('[s.SECURE_PROXY_SSL_HEADER, s.SECURE_SSL_REDIRECT, s.SESSION_COOKIE_SECURE, s.CSRF_COOKIE_SECURE, '
                's.SECURE_HSTS_SECONDS, s.SECURE_HSTS_INCLUDE_SUBDOMAINS, s.SECURE_HSTS_PRELOAD, '
                's.SILENCED_SYSTEM_CHECKS, s.CSRF_TRUSTED_ORIGINS]')

    def test_with_debug_off_every_request_is_https_behind_the_proxy(self):
        self.assertEqual(computed(self.SECURITY, **PRODUCTION), [
            ['HTTP_X_FORWARDED_PROTO', 'https'], True, True, True, 31536000, True, False, ['security.W021'],
            ['https://farm.invalid']])

    def test_a_development_server_stays_on_plain_http(self):
        self.assertEqual(computed(self.SECURITY), [None, False, False, False, 0, True, False, ['security.W021'], []])

    def test_hsts_and_the_trusted_origins_come_from_the_environment(self):
        found = computed(self.SECURITY, **PRODUCTION, DJANGO_HSTS_SECONDS='300', DJANGO_HSTS_INCLUDE_SUBDOMAINS='0',
                         DJANGO_HSTS_PRELOAD='1',
                         DJANGO_CSRF_TRUSTED_ORIGINS=' https://a.farm.invalid, https://b.farm.invalid/ ,')
        self.assertEqual(found[4:], [300, False, True, [], ['https://a.farm.invalid', 'https://b.farm.invalid']])

    def test_the_content_security_policy_is_the_same_in_production(self):
        development, production = computed('s.SECURE_CSP'), computed('s.SECURE_CSP', **PRODUCTION)
        self.assertEqual(production, development)
        self.assertEqual(production['style-src'], ["'self'"])

    def test_static_files_carry_their_hash_in_production_only(self):
        backend = "s.STORAGES['staticfiles']['BACKEND']"
        self.assertEqual(computed(backend, **PRODUCTION),
                         'django.contrib.staticfiles.storage.ManifestStaticFilesStorage')
        self.assertEqual(computed(backend), 'django.contrib.staticfiles.storage.StaticFilesStorage')

    def test_a_production_server_logs_its_errors(self):
        # Django's own handler prints only with DEBUG on: a 500 must leave a line on stderr
        self.assertEqual(computed("s.LOGGING['loggers']['django']", **PRODUCTION),
                         {'handlers': ['stderr'], 'level': 'WARNING', 'propagate': False})
        self.assertNotIn('django', computed("s.LOGGING['loggers']"))


class SecretFileTests(SimpleTestCase):
    """A secret from a file (a Docker secret), so that no secret stands in a container's environment."""

    def file(self, text):
        handle, path = tempfile.mkstemp()
        with os.fdopen(handle, 'w', encoding='utf-8') as out:
            out.write(text)
        self.addCleanup(os.unlink, path)
        return path

    def test_each_secret_is_the_first_line_of_its_file(self):
        found = computed("[s.SECRET_KEY, s.AUDIT_DIGEST_KEY, s.DATABASES['default']['PASSWORD'], "
                         "s.MAILERS['default']['OPTIONS']['password']]",
                         DJANGO_SECRET_KEY_FILE=self.file('key-from-a-file\nsecond line\n'),
                         DJANGO_AUDIT_DIGEST_KEY_FILE=self.file('digest-from-a-file\r\n'),
                         DB_PASSWORD='', DB_PASSWORD_FILE=self.file('db-from-a-file\n'),
                         EMAIL_HOST='smtp.farm.invalid',
                         EMAIL_HOST_USER='farm', EMAIL_HOST_PASSWORD_FILE=self.file('mail-from-a-file'))
        self.assertEqual(found, ['key-from-a-file', 'digest-from-a-file', 'db-from-a-file', 'mail-from-a-file'])

    def test_a_secret_given_twice_empty_or_unreadable_stops_the_server(self):
        for env, words in (
                ({'DJANGO_SECRET_KEY': 'a', 'DJANGO_SECRET_KEY_FILE': self.file('b')},
                 'Both DJANGO_SECRET_KEY and DJANGO_SECRET_KEY_FILE are set'),
                # (the test runner's own DB_PASSWORD is blanked: an empty variable counts as not set)
                ({'DB_PASSWORD': '', 'DB_PASSWORD_FILE': self.file('\nsecond line')}, 'holds nothing on its first line'),
                ({'DJANGO_AUDIT_DIGEST_KEY_FILE': str(Path(tempfile.gettempdir()) / 'no-such-secret')},
                 'cannot be read')):
            with self.subTest(env=sorted(env)):
                done = run(['-c', 'import config.settings'], **env)
                self.assertNotEqual(done.returncode, 0)
                self.assertIn('ImproperlyConfigured', done.stderr)
                self.assertIn(words, done.stderr)


class RefusalTests(SimpleTestCase):
    """An unsafe production value stops the deploy check, which nothing serves before (README, Starting a production
    server): each one by its own id."""

    def test_a_safe_production_configuration_passes_without_a_warning(self):
        code, output = deploy_check(**PRODUCTION)
        self.assertEqual(code, 0, output)
        self.assertIn('check identified no issues', output)

    def test_each_unsafe_value_is_refused(self):
        for change, issue in (
                ({'DJANGO_SECRET_KEY': ''}, 'security.W009'),              # the development key of the repository
                ({'DJANGO_SECRET_KEY': 'short-key'}, 'security.W009'),
                ({'DJANGO_ALLOWED_HOSTS': ''}, 'security.W020'),
                ({'DJANGO_ALLOWED_HOSTS': '*'}, 'core.E007'),
                ({'DJANGO_CSRF_TRUSTED_ORIGINS': 'http://farm.invalid'}, 'core.E008'),
                ({'DJANGO_AUDIT_DIGEST_KEY': ''}, 'core.E009'),
                ({'DJANGO_AUDIT_DIGEST_KEY': PRODUCTION['DJANGO_SECRET_KEY']}, 'core.E009'),
                ({'DJANGO_AUDIT_DIGEST_KEY': 'too-short'}, 'core.E009'),
                ({'DJANGO_HSTS_SECONDS': '0'}, 'security.W004'),
                ({'PUBLIC_BASE_URL': 'http://farm.invalid'}, 'core.E004'),
                ({'EMAIL_HOST': ''}, 'core.E002')):
            with self.subTest(change=change):
                code, output = deploy_check(**{**PRODUCTION, **change})
                self.assertNotEqual(code, 0, output)
                self.assertIn(f'({issue})', output)

    def test_the_production_server_runs_the_check_before_its_first_worker(self):
        start = ['-c', "import runpy; runpy.run_path('deploy/web/gunicorn.conf.py')['on_starting'](None)"]
        unsafe = run(start, DB_NAME='postgres', **{**PRODUCTION, 'DJANGO_ALLOWED_HOSTS': '*'})
        self.assertNotEqual(unsafe.returncode, 0)
        self.assertIn('The deploy check refused to start the server', unsafe.stderr)
        self.assertIn('core.E007', unsafe.stderr)
        safe = run(start, DB_NAME='postgres', **PRODUCTION)
        self.assertEqual(safe.returncode, 0, safe.stdout + safe.stderr)

    def test_the_server_settings_are_whole_numbers_of_one_or_more(self):
        read = ['-c', "import runpy; c = runpy.run_path('deploy/web/gunicorn.conf.py'); "
                      "print(c['workers'], c['threads'], c['timeout'], c['worker_class'])"]
        self.assertEqual(run(read).stdout.split(), ['3', '4', '120', 'gthread'])
        self.assertEqual(run(read, GUNICORN_WORKERS='5').stdout.split()[0], '5')
        for value in ('0', 'many'):
            done = run(read, GUNICORN_WORKERS=value)
            self.assertNotEqual(done.returncode, 0)
            self.assertIn('GUNICORN_WORKERS', done.stderr)

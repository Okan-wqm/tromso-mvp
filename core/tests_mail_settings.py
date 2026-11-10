"""Where the account e-mails go, and what their links say, is settled by the environment alone (README, Email): a
development server prints them in its terminal, a server with DEBUG off sends them by SMTP or does not start. No address,
user or password is in the repository."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, override_settings

from . import checks

CONSOLE = 'django.core.mail.backends.console.EmailBackend'
SMTP = 'django.core.mail.backends.smtp.EmailBackend'

# Everything the mail settings read: a fresh interpreter gets only what a test names, never what the machine has set.
MAIL_ENV = ('EMAIL_HOST', 'EMAIL_PORT', 'EMAIL_HOST_USER', 'EMAIL_HOST_PASSWORD', 'EMAIL_TLS', 'EMAIL_TIMEOUT',
            'DEFAULT_FROM_EMAIL', 'PUBLIC_BASE_URL', 'ACCOUNT_LINK_HOURS', 'PASSWORD_RESET_MAILS_PER_HOUR',
            'DJANGO_DEBUG', 'DJANGO_ALLOWED_HOSTS', 'DJANGO_SECRET_KEY')

# Production-like settings as the deploy check runs with them (scripts/testrunner/in-container.sh), and the mail part.
PRODUCTION = {'DJANGO_DEBUG': '0', 'DJANGO_ALLOWED_HOSTS': 'farm.invalid', 'DJANGO_SECRET_KEY': 'not-a-secret-' + 'abcdefghij' * 5}
MAIL = {'EMAIL_HOST': 'smtp.farm.invalid', 'DEFAULT_FROM_EMAIL': 'console@farm.invalid',
        'PUBLIC_BASE_URL': 'https://farm.invalid'}


def run(arguments, **env):
    base = {k: v for k, v in os.environ.items() if k not in MAIL_ENV}
    return subprocess.run([sys.executable, *arguments], capture_output=True, text=True, cwd=settings.BASE_DIR,
                          env={**base, **env})


def computed(expression, **env):
    """`expression` over config/settings.py (as `s`) in a fresh interpreter with `env`."""
    done = run(['-c', f'import json, config.settings as s; print(json.dumps({expression}))'], **env)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def check(*arguments, **env):
    """`manage.py check` in a fresh interpreter: the checks ask the database server only for its version, through its
    maintenance database (as scripts/testrunner/in-container.sh runs them)."""
    done = run(['manage.py', 'check', *arguments], DB_NAME='postgres', **env)
    return done.returncode, done.stdout + done.stderr


class MailSettingsTests(SimpleTestCase):
    def test_a_development_server_prints_its_mail_and_links_to_itself(self):
        self.assertEqual(computed('[s.MAILERS, s.MAIL_MUST_SEND, s.PUBLIC_BASE_URL]'),
                         [{'default': {'BACKEND': CONSOLE}}, False, 'http://127.0.0.1:8047'])

    def test_the_environment_names_the_smtp_server_and_the_sender(self):
        found = computed('[s.MAILERS, s.DEFAULT_FROM_EMAIL, s.PUBLIC_BASE_URL]', EMAIL_HOST='smtp.example.net',
                         EMAIL_HOST_USER='farm', EMAIL_HOST_PASSWORD='s3cret', DEFAULT_FROM_EMAIL='farm@example.net',
                         PUBLIC_BASE_URL='https://farm.example.net/')
        self.assertEqual(found, [
            {'default': {'BACKEND': SMTP, 'OPTIONS': {
                'host': 'smtp.example.net', 'port': None, 'username': 'farm', 'password': 's3cret',
                'use_tls': True, 'use_ssl': False, 'timeout': 10}}},
            'farm@example.net', 'https://farm.example.net'])

    def test_the_port_the_encryption_and_the_timeout_are_the_environments(self):
        options = "s.MAILERS['default']['OPTIONS']"
        found = computed(options, EMAIL_HOST='smtp.example.net', EMAIL_TLS='ssl', EMAIL_PORT='2465', EMAIL_TIMEOUT='3')
        self.assertEqual((found['use_tls'], found['use_ssl'], found['port'], found['timeout']), (False, True, 2465, 3))
        found = computed(options, EMAIL_HOST='smtp.example.net', EMAIL_TLS='off')
        self.assertEqual((found['use_tls'], found['use_ssl'], found['username'], found['password']),
                         (False, False, None, None))

    def test_an_encryption_it_does_not_know_stops_the_settings_with_its_name(self):
        done = run(['-c', 'import config.settings'], EMAIL_HOST='smtp.example.net', EMAIL_TLS='yes')
        self.assertNotEqual(done.returncode, 0)
        self.assertIn('EMAIL_TLS must be starttls, ssl or off', done.stderr)

    def test_with_debug_off_there_is_no_console_to_fall_back_on(self):
        found = computed('[s.MAILERS["default"]["BACKEND"], s.MAILERS["default"]["OPTIONS"]["host"], s.MAIL_MUST_SEND, '
                         's.PUBLIC_BASE_URL]', DJANGO_DEBUG='0')
        self.assertEqual(found, [SMTP, None, True, ''])

    def test_a_link_lives_a_day_unless_the_environment_says_otherwise(self):
        self.assertEqual(computed('s.PASSWORD_RESET_TIMEOUT'), 24 * 3600)
        self.assertEqual(computed('s.PASSWORD_RESET_TIMEOUT', ACCOUNT_LINK_HOURS='2'), 2 * 3600)

    def test_reset_mails_are_limited_to_three_an_hour_unless_the_environment_says_otherwise(self):
        self.assertEqual(computed('s.PASSWORD_RESET_MAILS_PER_HOUR'), 3)
        self.assertEqual(computed('s.PASSWORD_RESET_MAILS_PER_HOUR', PASSWORD_RESET_MAILS_PER_HOUR='1'), 1)

    def test_a_lifetime_or_a_limit_under_one_stops_the_settings(self):
        # no link would ever work, no reset mail ever be sent: said when the server starts, not found out by a person
        for name in ('ACCOUNT_LINK_HOURS', 'PASSWORD_RESET_MAILS_PER_HOUR'):
            for value in ('0', '-1'):
                with self.subTest(name=name, value=value):
                    done = run(['-c', 'import config.settings'], **{name: value})
                    self.assertNotEqual(done.returncode, 0)
                    self.assertIn(f'{name} must be 1 or more', done.stderr)


def smtp(**options):
    return {'default': {'BACKEND': SMTP, 'OPTIONS': {
        'host': 'smtp.farm.invalid', 'port': None, 'username': None, 'password': None, 'use_tls': True,
        'use_ssl': False, 'timeout': 10, **options}}}


GOOD = dict(MAIL_MUST_SEND=True, MAILERS=smtp(), DEFAULT_FROM_EMAIL='console@farm.invalid',
            PUBLIC_BASE_URL='https://farm.invalid', ALLOWED_HOSTS=['farm.invalid'])


def found(**changed):
    with override_settings(**{**GOOD, **changed}):
        return [(problem.id, problem.msg) for problem in checks.mail_is_configured(None)]


def ids(**changed):
    return [problem_id for problem_id, _text in found(**changed)]


class MailCheckTests(SimpleTestCase):
    """core.checks.mail_is_configured: an Error, so `runserver`, `migrate` and `check` stop on it."""

    def test_a_complete_configuration_passes(self):
        self.assertEqual(found(), [])
        self.assertEqual(found(MAILERS=smtp(username='farm', password='s3cret')), [])
        self.assertEqual(found(MAILERS=smtp(username='farm', password='s3cret', use_tls=False, use_ssl=True)), [])

    def test_the_tests_and_a_development_server_are_left_alone(self):
        # as this run is: DEBUG was on when the settings were read, the mail goes to the test outbox
        self.assertEqual(checks.mail_is_configured(None), [])
        self.assertEqual(found(MAIL_MUST_SEND=False, MAILERS={'default': {'BACKEND': CONSOLE}},
                               DEFAULT_FROM_EMAIL='webmaster@localhost', PUBLIC_BASE_URL='http://127.0.0.1:8047'), [])

    def test_no_smtp_server_with_debug_off_is_an_error(self):
        self.assertEqual(ids(MAILERS=smtp(host=None)), ['core.E002'])
        self.assertEqual(ids(MAILERS={'default': {'BACKEND': CONSOLE}}), ['core.E002'])
        self.assertEqual(ids(MAILERS={}), ['core.E002'])
        text = found(MAILERS=smtp(host=None))[0][1]
        self.assertIn('EMAIL_HOST', text)
        self.assertIn('invitations and password resets', text)

    def test_a_server_that_sends_needs_a_sender_address(self):
        for sender in ('webmaster@localhost', '', 'not an address'):
            with self.subTest(sender=sender):
                self.assertEqual(ids(DEFAULT_FROM_EMAIL=sender), ['core.E003'])
        self.assertEqual(ids(DEFAULT_FROM_EMAIL='Farm console <console@farm.invalid>'), [])
        # a development server trying a real SMTP server is held to it too
        self.assertEqual(ids(MAIL_MUST_SEND=False, DEFAULT_FROM_EMAIL='webmaster@localhost',
                             PUBLIC_BASE_URL='http://127.0.0.1:8047'), ['core.E003'])

    def test_the_links_need_a_public_address_this_server_answers_to(self):
        for address in ('', 'farm.invalid', 'http://farm.invalid', 'https://farm.invalid/console',
                        'https://farm.invalid?x=1', 'https://elsewhere.invalid', 'ftp://farm.invalid'):
            with self.subTest(address=address):
                self.assertEqual(ids(PUBLIC_BASE_URL=address), ['core.E004'])
        self.assertEqual(ids(PUBLIC_BASE_URL='https://farm.invalid:8443'), [])
        self.assertIn('PUBLIC_BASE_URL', found(PUBLIC_BASE_URL='')[0][1])

    def test_a_password_is_never_sent_to_the_mail_server_in_the_clear(self):
        self.assertEqual(ids(MAILERS=smtp(username='farm', password='s3cret', use_tls=False)), ['core.E005'])
        self.assertEqual(ids(MAILERS=smtp(username='farm')), ['core.E005'])
        self.assertEqual(ids(MAILERS=smtp(password='s3cret')), ['core.E005'])
        self.assertNotIn('s3cret', found(MAILERS=smtp(username='farm', password='s3cret', use_tls=False))[0][1])


class StartTests(SimpleTestCase):
    """The server itself: with production-like settings it does not start without its SMTP server."""

    def test_with_debug_off_and_no_smtp_server_the_check_refuses(self):
        code, output = check(**PRODUCTION)
        self.assertNotEqual(code, 0, output)
        self.assertIn('core.E002', output)
        self.assertIn('core.E004', output)

    def test_with_the_mail_environment_it_passes(self):
        code, output = check(**PRODUCTION, **MAIL)
        self.assertEqual(code, 0, output)

    def test_the_deploy_check_has_no_open_mail_issue(self):
        # with what the deploy check gives it (in-container.sh), Django's own "development-only email backend" is closed
        code, output = check('--deploy', '--fail-level', 'CRITICAL', **PRODUCTION, **MAIL)
        self.assertEqual(code, 0, output)
        self.assertEqual(re.findall(r'\((?:mail|core)\.[EW]\d+\)', output), [], output)
        script = (Path(settings.BASE_DIR) / 'scripts' / 'testrunner' / 'in-container.sh').read_text(encoding='utf-8')
        still_open = script.split('DEPLOY_OPEN="')[1].split('"')[0]
        self.assertNotIn('mail.', still_open)
        for name, value in MAIL.items():
            self.assertIn(f'{name}={value}', script)

    def test_without_it_the_deploy_check_names_the_mail_errors(self):
        code, output = check('--deploy', '--fail-level', 'CRITICAL', **PRODUCTION)
        self.assertEqual(code, 0, output)                    # the script reads the list, it is not stopped by an Error
        self.assertIn('(core.E002)', output)

"""“Forgot your password?” takes the same time whoever the address belongs to (review R1): a request for an address with
an account is answered as one for an address nobody has. Asked of the work, never of the clock (two kinds of answer
"a few milliseconds apart" were the machine's time as much as the code's). Through the pages against the real worker,
so it commits for real: the request runs the same statements for both, every answer is in while the mail server is
still shut (none waited for it), and the address is looked at on the worker's thread only, after the answer."""
import re
import sys
import threading
import time
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.mail.backends.base import BaseEmailBackend
from django.db import connection
from django.test import TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from . import accountmail
from .models import AccountMail

WAIT = 30                 # seconds a wait for the worker may take on a loaded machine (a ceiling, never a measure)


class GatedBackend(BaseEmailBackend):
    """A mail server that takes no mail until the test opens its `gate`; `asked`: the threads that talked to it."""
    gate = threading.Event()
    sent, asked = [], []

    def send_messages(self, messages):
        type(self).asked.append(threading.current_thread().name)
        if not type(self).gate.wait(timeout=WAIT):
            raise RuntimeError('the test never opened the mail server')
        type(self).sent.extend(messages)
        return len(messages)


GATED = {'default': {'BACKEND': 'core.tests_account_mail_timing.GatedBackend'}}


def shape(sql):
    """A statement without its values: the work it stands for, whatever the address."""
    return re.sub(r"'(?:[^']|'')*'|\b\d+\b", '?', sql)


@override_settings(MAIL_IN_BACKGROUND=True, MAILERS=GATED, PASSWORD_RESET_MAILS_PER_HOUR=10,
                   PUBLIC_BASE_URL='https://farm.example')
class ForgotPasswordTimingTests(TransactionTestCase):
    serialized_rollback = True            # the next test finds the rows the migrations made

    def ask(self, address):
        """The statements the request ran, without their values (its time is kept for the measurement line only)."""
        with CaptureQueriesContext(connection) as ran:
            start = time.perf_counter()
            response = self.client.post(reverse('password_reset'), {'email': address})
            self.took.append(round((time.perf_counter() - start) * 1000))
        self.assertEqual((response.status_code, response['Location']), (302, reverse('password_reset_done')))
        return [shape(query['sql']) for query in ran.captured_queries]

    def test_a_known_address_is_answered_as_an_unknown_one(self):
        GatedBackend.gate.clear()
        GatedBackend.sent.clear(), GatedBackend.asked.clear()
        self.addCleanup(GatedBackend.gate.set)
        self.took, looked_at, real = [], [], accountmail.reset_now

        def reset_now(address, language):
            looked_at.append(threading.current_thread().name)
            return real(address, language)

        get_user_model().objects.create_user('ali', 'ali@example.com', 'eski-sifre-123')
        with mock.patch.object(accountmail, 'reset_now', reset_now):
            self.ask('warm@example.com')
            unknown = [self.ask(f'nobody{n}@example.com') for n in range(5)]
            known = [self.ask('ali@example.com') for _ in range(5)]
            self.assertEqual(GatedBackend.sent, [])         # every answer is in, the mail server still shut
            GatedBackend.gate.set()
            self.assertTrue(accountmail.worker.drain(WAIT), f'the mail worker did not finish its jobs within {WAIT} s')
        sys.stderr.write(f'\n[forgot password] answered in ms: unknown {self.took[1:6]}, known {self.took[6:]}\n')
        self.assertEqual(known, unknown)                      # the same statements whoever the address belongs to
        self.assertEqual(looked_at, ['account-mail'] * 11)    # the address looked at on the worker's thread only
        self.assertEqual(set(GatedBackend.asked), {'account-mail'})   # and the mail server talked to there only
        # and the five mails do go out, afterwards
        self.assertEqual([sent.to for sent in GatedBackend.sent], [['ali@example.com']] * 5)
        self.assertEqual(AccountMail.objects.filter(sent_at=None).count(), 0)

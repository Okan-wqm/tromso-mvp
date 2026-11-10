"""“Forgot your password?” takes the same time whoever the address belongs to (review R1): with a mail server that
needs 0.6 s for a mail, a request for an address with an account is answered as quickly as one for an address nobody
has. Measured through the pages against the real worker, so it commits for real."""
import statistics
import time

from django.contrib.auth import get_user_model
from django.core.mail.backends.base import BaseEmailBackend
from django.test import TransactionTestCase, override_settings
from django.urls import reverse

from .models import AccountMail

SECONDS_A_MAIL = 0.6


class SlowBackend(BaseEmailBackend):
    """A mail server that takes its time over every mail (a quick one, in real life)."""
    sent = []

    def send_messages(self, messages):
        time.sleep(SECONDS_A_MAIL)
        type(self).sent.extend(messages)
        return len(messages)


SLOW = {'default': {'BACKEND': 'core.tests_account_mail_timing.SlowBackend'}}


@override_settings(MAIL_IN_BACKGROUND=True, MAILERS=SLOW, PASSWORD_RESET_MAILS_PER_HOUR=10,
                   PUBLIC_BASE_URL='https://farm.example')
class ForgotPasswordTimingTests(TransactionTestCase):
    serialized_rollback = True            # the next test finds the rows the migrations made

    def ask(self, address):
        start = time.perf_counter()
        response = self.client.post(reverse('password_reset'), {'email': address})
        took = time.perf_counter() - start
        self.assertEqual((response.status_code, response['Location']), (302, reverse('password_reset_done')))
        return took

    def test_a_known_address_is_answered_as_quickly_as_an_unknown_one(self):
        SlowBackend.sent.clear()
        get_user_model().objects.create_user('ali', 'ali@example.com', 'eski-sifre-123')
        self.ask('warm@example.com')
        unknown = [self.ask(f'nobody{n}@example.com') for n in range(5)]
        known = [self.ask('ali@example.com') for _ in range(5)]
        measured = 'ms unknown %s known %s' % ([round(t * 1000) for t in unknown], [round(t * 1000) for t in known])
        # no single answer waited for the mail server, and the two kinds are a few milliseconds apart
        self.assertLess(max(known), SECONDS_A_MAIL / 2, measured)
        self.assertLess(abs(statistics.median(known) - statistics.median(unknown)), 0.1, measured)
        # and the five mails do go out, afterwards
        waited = time.monotonic()
        while len(SlowBackend.sent) < 5 and time.monotonic() - waited < 30:
            time.sleep(0.1)
        self.assertEqual([sent.to for sent in SlowBackend.sent], [['ali@example.com']] * 5, measured)
        while AccountMail.objects.filter(sent_at=None).exists() and time.monotonic() - waited < 30:
            time.sleep(0.1)                 # the worker has written the last one down before the database is emptied
        self.assertEqual(AccountMail.objects.filter(sent_at=None).count(), 0)

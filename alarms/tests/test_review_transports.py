"""The addendum to REVIEW4 (5260557a), each held by a test that fails without its fix:

- a transport that declares no limit is never handed a notification: each attempt fails, saying why (the surviving
  mutant: the guard removed);
- `manage.py check --deploy` refuses a configured transport that cannot be imported, is not a Transport, or declares no
  whole `max_bytes` of at least 1 (alarms.E001-E003); an ordinary check does not, so one wrong setting never stops
  `run_alarm_worker`;
- the limit is in UTF-8 bytes, as a push payload's is: a Norwegian or Turkish text whose characters fit but whose bytes
  do not is built to the bytes, cut between two words."""
from django.core import checks
from django.test import SimpleTestCase, override_settings

from core.models import Profile

from .. import outbox, services
from ..models import DeliveryAttempt, Notification, OutboxEntry
from .doubles import RecordingTransport, UndeclaredTransport
from .test_review_fixes import Case

DOUBLES = 'alarms.tests.doubles'


class UndeclaredLimitTests(Case):
    def setUp(self):
        super().setUp()
        UndeclaredTransport.calls.clear()
        self.addCleanup(UndeclaredTransport.calls.clear)

    @override_settings(ALARM_TRANSPORTS={'push': f'{DOUBLES}.UndeclaredTransport'})
    def test_a_transport_that_declares_no_limit_is_handed_nothing_and_each_attempt_says_why(self):
        (notification,) = self.system(1, 'critical')
        with self.assertLogs('alarms.outbox', level='ERROR'):
            outbox.send_due(self.at(0))
        self.assertEqual(UndeclaredTransport.calls, [])
        attempt = DeliveryAttempt.objects.get(notification=notification)
        self.assertEqual(attempt.outcome, 'failed')
        self.assertIn('declares no max_bytes', attempt.detail)
        self.assertTrue(OutboxEntry.objects.filter(notification=notification).exists())


def transports_declare_limits(app_configs):
    """The deployment check (imported here, so the other tests of this module run without it)."""
    from ..checks import transports_declare_limits as check
    return check(app_configs)


class DeployCheckTests(SimpleTestCase):
    def found(self, setting):
        with override_settings(ALARM_TRANSPORTS=setting):
            return sorted(error.id for error in transports_declare_limits(None))

    def test_each_configured_transport_must_be_a_transport_with_a_byte_limit(self):
        self.assertEqual(self.found({}), [])
        self.assertEqual(self.found({'push': f'{DOUBLES}.RecordingTransport'}), [])
        self.assertEqual(self.found({'push': f'{DOUBLES}.NoSuchTransport'}), ['alarms.E001'])
        self.assertEqual(self.found({'push': f'{DOUBLES}.NotATransport'}), ['alarms.E002'])
        self.assertEqual(self.found({'push': f'{DOUBLES}.UndeclaredTransport'}), ['alarms.E003'])
        for bad in ('4000', 0, True, 4000.0):
            with self.subTest(bad=bad), override_settings(ALARM_TRANSPORTS={'push': f'{DOUBLES}.RecordingTransport'}):
                original = RecordingTransport.max_bytes
                RecordingTransport.max_bytes = bad
                try:
                    self.assertEqual(sorted(error.id for error in transports_declare_limits(None)), ['alarms.E003'])
                finally:
                    RecordingTransport.max_bytes = original

    def test_it_is_a_deployment_check_at_error_level_never_an_ordinary_one(self):
        from ..checks import transports_declare_limits as check
        self.assertIn(check, checks.registry.registry.deployment_checks)
        self.assertNotIn(check, checks.registry.registry.registered_checks)
        with override_settings(ALARM_TRANSPORTS={'push': f'{DOUBLES}.UndeclaredTransport'}):
            self.assertEqual([error.level for error in transports_declare_limits(None)], [checks.ERROR])


class ByteLimitTests(Case):
    def setUp(self):
        super().setUp()
        RecordingTransport.floods.clear()
        self.addCleanup(RecordingTransport.floods.clear)

    def queued(self, summary, language, seconds=0):
        Profile.objects.update_or_create(user=self.operator, defaults={'language': language})
        at = self.at(seconds=seconds)
        alarm = services.open_alarm(source='system', parameter='sensors_failed', severity='critical', at=at,
                                    site=self.bergen, summary=summary)
        (made,) = services.queue_many([Notification(alarm=alarm, recipient=self.operator, channel='push', level=0,
                                                    queued_at=at)])
        return made

    def assert_within_bytes(self, limit):
        self.assertTrue(RecordingTransport.sent)
        for sent in RecordingTransport.sent:
            self.assertLessEqual(len(sent.text.encode('utf-8')), limit, sent.text)

    @override_settings(ALARM_TRANSPORTS={'push': f'{DOUBLES}.SmsTransport'})
    def test_a_turkish_text_whose_characters_fit_an_sms_but_whose_bytes_do_not_is_cut_between_words(self):
        summary = ' '.join(['Havuz çıkışında çözünmüş oksijen düşük, şişeler değiştirilmeli'] * 2)
        row = self.queued(summary, 'tr')
        full = outbox.text(row)
        self.assertLessEqual(len(full), 160)                         # it fits in characters ...
        self.assertGreater(len(full.encode('utf-8')), 160)           # ... not in bytes
        outbox.send_due(self.at(1))
        self.assert_within_bytes(160)
        (sent,) = RecordingTransport.sent
        self.assertTrue(sent.text.endswith('…'), sent.text)
        kept = sent.text[:-1]
        self.assertTrue(full.startswith(kept))
        self.assertIn(full[len(kept)], ' ;,:')
        self.assertTrue(DeliveryAttempt.objects.filter(notification=row, outcome='sent').exists())

    @override_settings(ALARM_TRANSPORTS={'push': f'{DOUBLES}.RecordingTransport'})
    def test_a_norwegian_follow_up_near_the_push_limit_is_built_to_its_bytes(self):
        made = [self.queued(f'K-{number:03d} · Midtre: løst oksygen 3,1 mg/L, kritisk; ærlig målt, øvre kår, åpen ventil, '
                            f'sjekk pumpe og lufteslange før påfylling av ferskvann på kar', 'nb') for number in range(60)]
        for second in range(0, 11):
            outbox.send_due(self.at(seconds=second))
        self.assert_within_bytes(4000)
        follow_up = RecordingTransport.sent[-1].text
        self.assertGreater(len(follow_up.encode('utf-8')), len(follow_up))                    # multi-byte letters
        for row in made:
            self.assertTrue(DeliveryAttempt.objects.filter(notification=row, outcome='sent').exists(), row.pk)
        self.assertFalse(OutboxEntry.objects.exists())

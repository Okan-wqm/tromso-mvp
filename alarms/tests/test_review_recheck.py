"""The recheck of the alarm worker (fc254413, REVIEW2.md: N1-N6, two mutants) and the coordinator's two decisions on it,
each held by a test that fails without its fix:

- N1 (probe T17): a flood message about cleared alarms opens no coverage window: a new open critical of the kind 35 s
  later is sent, never covered by a message that said "cleared";
- N2 (T1): a message about cleared criticals counts only its own alarms (now the follow-up names each: test_review_final);
- N3 (T4): open, unacknowledged criticals go before cleared criticals, then the rest;
- N4 (T2): a word about a snooze of an alarm that cleared since is given up, never "still open";
- N5 (T3): an error in a notification's own handling before the transport is a failed attempt, counted as any;
- N6: a chunk that dies leaves no attempt (give_up_said's transaction); a standing unsent critical never holds the
  warnings back;
- sensors_failed is never snoozed (the farm is blind); unit_unevaluated and value_unevaluated are;
- at a transport's first connection, criticals that cleared more than 24 h before go out as one summary, their own
  notifications covered by it, said why; open ones and those cleared within 24 h go normally."""
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import override_settings

from .. import outbox, services
from ..models import Alarm, DeliveryAttempt, OutboxEntry
from .doubles import RecordingTransport
from .test_review_fixes import Case
from farm.tests.helpers import may_record

RECORDING = {'push': 'alarms.tests.doubles.RecordingTransport'}
FAILING = {'push': 'alarms.tests.doubles.FailingTransport'}


class RecheckCase(Case):
    def setUp(self):
        super().setUp()
        RecordingTransport.floods.clear()
        self.addCleanup(RecordingTransport.floods.clear)

    def cleared(self, count, minutes=1, parameter='sensors_failed', seconds=0):
        made = self.system(count, 'critical', seconds=seconds, parameter=parameter)
        for row in made:
            services.clear(row.alarm, self.at(minutes), 'restored')
        return made


@override_settings(ALARM_TRANSPORTS=RECORDING)
class FloodCoverageTests(RecheckCase):
    def test_a_cleared_flood_message_never_covers_the_next_open_critical(self):            # probe T17
        self.cleared(3, minutes=1)
        outbox.send_due(self.at(2))
        self.assertEqual(len(RecordingTransport.floods), 1)
        (fresh,) = self.system(1, 'critical', seconds=155)                                # 35 s after the message
        found = outbox.send_due(self.at(2, seconds=35))
        self.assertEqual((found.sent, found.grouped), (1, 0))
        self.assertEqual(RecordingTransport.sent[-1].pk, fresh.pk)

    def test_a_message_about_cleared_criticals_counts_only_its_own(self):                      # probe T1
        self.system(2, 'critical')                                                      # two open, sent one by one
        outbox.send_due(self.at(0, seconds=1))
        self.cleared(3, minutes=1, seconds=10)
        outbox.send_due(self.at(2))
        ((first, flood),) = RecordingTransport.floods
        self.assertEqual(flood.size, 3)
        self.assertTrue(first.text.startswith('3 more critical alarms'), first.text)
        self.assertIn('0 open now', first.text)


@override_settings(ALARM_TRANSPORTS=RECORDING)
class OrderTests(RecheckCase):
    def test_an_open_critical_goes_before_cleared_criticals(self):                            # probe T4
        for number in range(30):
            self.cleared(1, minutes=1, parameter=f'old{number}')
        (fresh,) = self.system(1, 'critical', seconds=120, parameter='fresh')
        outbox.send_due(self.at(3))
        self.assertEqual(RecordingTransport.sent[0].pk, fresh.pk)


@override_settings(ALARM_TRANSPORTS=RECORDING)
class StaleWordTests(RecheckCase):
    def test_a_word_about_a_snooze_of_an_alarm_that_cleared_since_is_given_up(self):          # probe T2
        self.rule()
        self.sample(5.5)
        self.loop()
        alarm = self.critical()
        snoozer = may_record(get_user_model().objects.create_user('snoozer', 'snoozer@example.com', 'x'),
                             'add_alarmshelve')
        row = services.shelve(alarm, snoozer, 10, 'probe cleaned', at=self.at(1))
        with override_settings(ALARM_TRANSPORTS={}):
            self.loop(minutes=12)                                       # the snooze ended, the alarm open: told again
        resumed = row.notifications.get(kind='resumed')
        services.clear(alarm, self.at(13), 'restored')
        outbox.send_due(self.at(14))
        self.assertNotIn(resumed.pk, [sent.pk for sent in RecordingTransport.sent])
        self.assertFalse(OutboxEntry.objects.filter(notification=resumed).exists())
        self.assertIn('cleared', DeliveryAttempt.objects.get(notification=resumed).detail)


@override_settings(ALARM_TRANSPORTS=RECORDING)
class HandlingErrorTests(RecheckCase):
    def test_an_error_before_the_transport_is_a_failed_attempt_counted_as_any(self):         # probe T3
        (notification,) = self.system(1, 'critical')
        with mock.patch.object(outbox, 'text', side_effect=RuntimeError('the text broke')), \
                self.assertLogs('alarms.outbox', level='ERROR'):
            for minute in range(0, 14):
                outbox.send_due(self.at(minute))
        attempts = DeliveryAttempt.objects.filter(notification=notification)
        self.assertGreater(attempts.count(), 1)
        self.assertIn('the text broke', attempts.first().detail)
        self.assertEqual(len(outbox.stuck(outbox.alarm_rules.current(), self.at(14))), 1)


class MutantTests(RecheckCase):
    def test_a_chunk_that_dies_leaves_no_attempt(self):
        made = self.system(3, 'warning')
        for row in made:
            services.clear(row.alarm, self.at(1), 'restored')
        with mock.patch.object(services, '_log', side_effect=RuntimeError('the log is gone')), \
                self.assertRaises(RuntimeError):
            services.give_up_said(made, 'not sent', self.at(2))
        self.assertFalse(DeliveryAttempt.objects.exists())
        self.assertEqual(OutboxEntry.objects.count(), 3)

    @override_settings(ALARM_TRANSPORTS=FAILING)
    def test_a_standing_unsent_critical_never_holds_the_warnings_back(self):
        self.system(1, 'critical', parameter='standing')
        outbox.send_due(self.now)                                        # it fails and waits for its retry
        (warning,) = self.system(1, 'warning', seconds=5, parameter='later')
        with override_settings(ALARM_TRANSPORTS=RECORDING):
            outbox.send_due(self.at(0, seconds=6))                          # the critical not due: the warning goes
        self.assertIn(warning.pk, [sent.pk for sent in RecordingTransport.sent])


class SnoozeKindTests(RecheckCase):
    def test_sensors_failed_is_never_snoozed_an_unevaluated_unit_is(self):
        snoozer = may_record(get_user_model().objects.create_user('snoozer', 'snoozer@example.com', 'x'),
                             'add_alarmshelve')
        blind = services.open_alarm(source='system', farm_wide=True, parameter='sensors_failed', severity='critical', at=self.now,
                                    summary='The sensors cannot be read')
        with self.assertRaisesMessage(ValidationError, 'never snoozed'):
            services.shelve(blind, snoozer, 30, 'busy', at=self.at(1))
        for parameter in ('unit_unevaluated', 'value_unevaluated'):
            alarm = services.open_alarm(source='system', farm_wide=True, parameter=parameter, severity='critical', at=self.now,
                                        summary=parameter)
            self.assertEqual(services.shelve(alarm, snoozer, 30, 'calibrating', at=self.at(1)).alarm, alarm)


class FirstConnectionTests(RecheckCase):
    def test_criticals_cleared_more_than_a_day_before_go_as_one_summary(self):
        days = 24 * 60
        old = []
        for number in range(3):
            old += self.cleared(1, minutes=-(3 * days) + number, parameter=f'old{number}', seconds=-(4 * days * 60))
        (recent,) = self.cleared(1, minutes=-60, parameter='recent', seconds=-2 * 3600)
        (still_open,) = self.system(1, 'critical', parameter='open')
        with override_settings(ALARM_TRANSPORTS=RECORDING):
            outbox.send_due(self.at(1))
        texts = [sent.text for sent in RecordingTransport.sent]
        summaries = [text for text in texts if 'happened and cleared while no message could be sent' in text]
        self.assertEqual(len(summaries), 1)
        self.assertTrue(summaries[0].startswith('3 critical alarms'))
        self.assertIn('see the alarm log', summaries[0])
        sent = [notification.pk for notification in RecordingTransport.sent]
        self.assertIn(recent.pk, sent)
        self.assertIn(still_open.pk, sent)
        for row in old:
            attempt = DeliveryAttempt.objects.get(notification=row)
            self.assertEqual(attempt.outcome, 'grouped')
            self.assertIn('summary', attempt.detail)
            self.assertFalse(OutboxEntry.objects.filter(notification=row).exists())
        self.assertEqual(Alarm.objects.count(), 5)

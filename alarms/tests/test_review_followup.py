"""The follow-up review of the alarm worker (head 81007c2a, R1-R6), each finding held by a test that fails without its fix:

- R1: a critical's retry wait never overflows, however many failures (retry 5 s, escalation 30 min, 60 and 200
  failures); one notification that cannot be handled never stops the round: the others still go;
- R2: the attempt and the queue's entry are written together or not at all (a death between them); a round drops an
  entry that already has a sent or covered attempt, and never counts it undeliverable;
- R3: a critical that joins the queue during a round of warnings ends it, whatever time it is stamped with;
- R4: a notification whose alarm cleared before its first attempt is given up, said why, on any channel; a channel
  without a transport is left out of a round in the database; a round and the supervision stay cheap with 20,000
  waiting;
- R5: a snoozed critical is never counted undeliverable;
- R6: a failed step's flood key is never cut; the alarm system's alarms about the farm (an oxygen with no fresh value,
  the sensors unreadable) are snoozed like any; only those about its own health are not."""
import sys
import time
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import OperationalError, connection
from django.test import override_settings

from .. import floods, outbox, read, services
from ..models import Alarm, DeliveryAttempt, OutboxEntry, SeverityPolicy
from .doubles import RecordingTransport
from . import NOTHING_CONNECTED
from .test_review_fixes import Case
from core.testing import reads
from farm.tests.helpers import may_record

FAILING = {'push': 'alarms.tests.doubles.FailingTransport'}
RECORDING = {'push': 'alarms.tests.doubles.RecordingTransport'}


class RetryOverflowTests(Case):
    def test_no_count_of_failures_overflows_the_wait(self):
        SeverityPolicy.objects.filter(severity='critical').update(retry_seconds=5, escalation_minutes=30)
        rules = outbox.alarm_rules.current()
        row = self.system(1, 'critical')[0]
        row.acknowledged = False
        for failures in (60, 200, 10_000):
            row.failures = failures
            self.assertEqual(outbox.retry_wait(row, rules), timedelta(minutes=30))

    @override_settings(ALARM_TRANSPORTS=RECORDING)
    def test_one_notification_that_cannot_be_handled_never_stops_the_round(self):
        bad, good = self.system(1, 'critical', parameter='bad')[0], self.system(1, 'critical', parameter='good')[0]
        real = floods.key

        def key(alarm):
            if alarm.pk == bad.alarm_id:
                raise OverflowError('a broken entry')
            return real(alarm)
        with mock.patch.object(floods, 'key', key), self.assertLogs('alarms.outbox', level='ERROR'):
            found = outbox.send_due(self.now)
        self.assertEqual(found.sent, 1)
        self.assertEqual([sent.pk for sent in RecordingTransport.sent], [good.pk])
        self.assertTrue(OutboxEntry.objects.filter(notification=bad).exists())     # left for the next round


class TogetherTests(Case):
    @override_settings(ALARM_TRANSPORTS=RECORDING)
    def test_a_death_between_the_attempt_and_the_queue_leaves_neither(self):
        (notification,) = self.system(1, 'critical')
        with mock.patch('core.audit.record', side_effect=OperationalError('the server went away')), \
                self.assertLogs('alarms.outbox', level='ERROR'):
            outbox.send_due(self.now)
        self.assertFalse(DeliveryAttempt.objects.exists())
        self.assertTrue(OutboxEntry.objects.filter(notification=notification).exists())
        self.assertEqual(outbox.send_due(self.now + timedelta(seconds=1)).sent, 1)
        self.assertFalse(OutboxEntry.objects.filter(notification=notification).exists())

    @override_settings(ALARM_TRANSPORTS=FAILING)
    def test_an_entry_that_already_went_is_dropped_and_never_undeliverable(self):
        (notification,) = self.system(1, 'critical', seconds=-3600)
        DeliveryAttempt.objects.create(notification=notification, attempted_at=self.now - timedelta(minutes=50),
                                       outcome='failed', detail='')
        DeliveryAttempt.objects.create(notification=notification, attempted_at=self.now - timedelta(minutes=40),
                                       outcome='sent', detail='')            # the queue's delete lost (an old death)
        self.assertEqual(outbox.stuck(outbox.alarm_rules.current(), self.now), [])
        found = outbox.send_due(self.now)
        self.assertEqual((found.undeliverable, found.backlog, found.failed), (0, 0, 0))
        self.assertFalse(OutboxEntry.objects.filter(notification=notification).exists())


class SlowRecording(RecordingTransport):
    def send(self, notification, flood=None):
        time.sleep(0.05)
        return super().send(notification, flood)


@override_settings(ALARM_TRANSPORTS={'push': 'alarms.tests.test_review_followup.SlowRecording'})
class InsertionOrderTests(Case):
    def test_a_critical_stamped_before_the_round_and_committed_during_it_ends_the_round(self):
        for number in range(3):
            self.system(1, 'warning', parameter=f'w{number}')
        made = []
        real = SlowRecording.send

        def send(transport, notification, flood=None):
            if not made:                                  # a pass that began before the round commits now
                made.extend(self.system(1, 'critical', seconds=-30, parameter='urgent'))
            return real(transport, notification, flood)
        with mock.patch.object(SlowRecording, 'send', send):
            found = outbox.send_due(self.now)
        self.assertEqual((found.sent, found.deferred), (1, 2))
        outbox.send_due(self.now + timedelta(seconds=1))
        self.assertEqual(RecordingTransport.sent[1].pk, made[0].pk)


class ClearedFirstTests(Case):
    def test_a_notification_whose_alarm_cleared_before_its_first_attempt_is_given_up_and_said(self):
        (notification,) = self.system(1, 'warning')               # (a critical is still delivered: test_cleared_criticals)
        services.clear(notification.alarm, self.at(1), 'restored')
        found = outbox.send_due(self.at(2))                       # no transport connected: given up all the same
        self.assertEqual(found.given_up, 1)
        attempt = DeliveryAttempt.objects.get(notification=notification)
        self.assertIn('cleared before the first attempt', attempt.detail)
        self.assertEqual(read.status(notification), 'failed')
        self.assertFalse(OutboxEntry.objects.filter(notification=notification).exists())
        with override_settings(ALARM_TRANSPORTS=RECORDING):
            self.assertEqual(outbox.send_due(self.at(3)).sent, 0)                 # never at the first connection
        self.assertEqual(RecordingTransport.sent, [])


class LoadTests(Case):
    def fill(self, count, severity='critical'):
        with connection.cursor() as cursor:
            cursor.execute("INSERT INTO alarms (source, parameter, severity, opened_at, summary) SELECT 'system', 'many', "
                           "%s, %s, 'many ' || n FROM generate_series(1, %s) n", [severity, self.now, count])
            cursor.execute('INSERT INTO alarm_notifications (alarm_id, recipient_id, channel, level, queued_at, kind) '
                           "SELECT id, %s, 'push', 0, opened_at, 'alarm' FROM alarms WHERE parameter = 'many'",
                           [self.operator.pk])
            cursor.execute("INSERT INTO alarm_outbox (notification_id) SELECT n.id FROM alarm_notifications n JOIN alarms "
                           "a ON a.id = n.alarm_id WHERE a.parameter = 'many'")
            cursor.execute('ANALYZE alarms; ANALYZE alarm_notifications; ANALYZE alarm_outbox')

    @NOTHING_CONNECTED
    def test_twenty_thousand_waiting_without_a_transport_cost_a_round_and_the_supervision_little(self):
        self.fill(20_000)
        with reads() as round_:
            found = outbox.send_due(self.now + timedelta(minutes=1))
        with reads() as supervision:
            stuck = outbox.stuck(outbox.alarm_rules.current(), self.now + timedelta(hours=1))
        sys.stderr.write(f'\n[alarm outbox] 20,000 waiting, no transport: the most rows one statement handed back, a '
                         f'round {round_.most_returned()}, the supervision {supervision.most_returned()}\n')
        self.assertEqual((found.waiting, found.backlog, stuck), (20_000, 20_000, []))
        # The waiting are counted in the database, never handed to Python: of the statements that read the
        # notifications, the round's hand back their count (one row), the supervision's nothing (none has failed).
        self.assertLessEqual(round_.most_returned('alarm_notifications'), 1)
        self.assertEqual(supervision.most_returned('alarm_notifications'), 0)


@override_settings(ALARM_TRANSPORTS=FAILING)
class SnoozedNotUndeliverableTests(Case):
    def test_a_snoozed_critical_is_never_counted_undeliverable(self):
        self.rule()
        self.sample(5.5)
        for minute in range(4):
            self.loop(minutes=minute)
        alarm = self.critical()
        snoozer = may_record(get_user_model().objects.create_user('snoozer', 'snoozer@example.com', 'x'),
                             'add_alarmshelve')
        services.shelve(alarm, snoozer, 60, 'probe cleaned', at=self.at(4))
        for minute in range(4, 20):
            self.loop(minutes=minute)
        self.assertEqual(outbox.stuck(outbox.alarm_rules.current(), self.at(20)), [])
        self.assertFalse(Alarm.objects.filter(parameter='notifications_undeliverable').exists())


class KindTests(Case):
    def test_a_failed_steps_flood_key_is_never_cut(self):
        long = Alarm(source='system', parameter='step_failed', severity='critical', summary='x' * 290)
        other = Alarm(source='system', parameter='step_failed', severity='critical', summary='x' * 289 + 'y')
        self.assertLessEqual(len(floods.key(long)), DeliveryAttempt._meta.get_field('flood_key').max_length)
        self.assertNotEqual(floods.key(long), floods.key(other))

    def test_alarms_about_the_farm_are_snoozed_those_about_the_alarm_systems_own_health_never(self):
        snoozer = may_record(get_user_model().objects.create_user('snoozer', 'snoozer@example.com', 'x'),
                             'add_alarmshelve')
        for parameter in ('no_fresh_oxygen', 'unit_unevaluated', 'value_unevaluated'):
            with self.subTest(parameter=parameter):
                alarm = services.open_alarm(source='system', farm_wide=True, parameter=parameter, severity='critical', at=self.now,
                                            summary=parameter)
                self.assertEqual(services.shelve(alarm, snoozer, 30, 'probe cleaned', at=self.at(1)).alarm, alarm)
        for parameter in ('alarms_unchecked', 'step_failed', 'notifications_undeliverable', 'alarm_rules',
                          'sensors_failed'):
            with self.subTest(parameter=parameter):
                alarm = services.open_alarm(source='system', farm_wide=True, parameter=parameter, severity='critical', at=self.now,
                                            summary=parameter)
                with self.assertRaisesMessage(ValidationError, 'own health is never snoozed'):
                    services.shelve(alarm, snoozer, 30, 'busy', at=self.at(1))

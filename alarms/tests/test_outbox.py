"""The outbox's delivery (alarms/outbox.py): a pass only queues; the sender hands each due notification to its transport,
critical first and oldest first, tries a failed one again only after its severity's retry time, sends a whole backlog
once the transport is back, never loses one (a sender that dies after the transport took it sends it again: at least
once, written sent once), never sends one two senders hold at once, and fails an attempt whose transport hangs or
raises. With the worker: its sender thread writes the outbox's figures on the worker's row, and a transport that hangs
never delays an alarm."""
import threading
import time
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import OperationalError, connection
from django.test import TransactionTestCase, override_settings

from farm.tests.helpers import role

from .. import engine, outbox, read, services, watch, worker
from ..models import Alarm, AlarmWorkerStatus, DeliveryAttempt, Notification, RecipientRule, SeverityPolicy
from ..transports import Sent, Transport
from . import NOTHING_CONNECTED, AlarmsCase
from .doubles import RecordingTransport
from .test_reaction import TARGET, Farm, critical_units
from .test_worker import TIMING, other_session, unlock_all
from .test_worker_process import START, until

DOUBLES = 'alarms.tests.doubles'
RECORDING = {'push': f'{DOUBLES}.RecordingTransport'}
FAILING = {'push': f'{DOUBLES}.FailingTransport'}
HANGING = {'push': 'alarms.tests.test_outbox.HangingTransport'}
RAISING = {'push': 'alarms.tests.test_outbox.RaisingTransport'}


class HangingTransport(Transport):
    """A push service that does not answer until the test lets it."""

    channel = 'push'
    max_bytes = 4000
    release = threading.Event()
    entered = threading.Event()

    def send(self, notification):
        type(self).entered.set()
        type(self).release.wait(60)
        return Sent('late')


class RaisingTransport(Transport):
    channel = 'push'
    max_bytes = 4000

    def send(self, notification):
        raise RuntimeError('the push library broke')


class OutboxCase(AlarmsCase):
    def setUp(self):
        super().setUp()
        RecordingTransport.sent.clear()
        self.addCleanup(RecordingTransport.sent.clear)

    def queued(self, severity='critical', minutes_ago=0, count=1):
        """`count` alarms of the alarm system of `severity`, each with a level-0 notification to the operator queued
        `minutes_ago`."""
        at = self.now - timedelta(minutes=minutes_ago)
        made = []
        for number in range(count):
            alarm = services.open_alarm(source='system', farm_wide=True, parameter=f'test_{severity}_{minutes_ago}_{number}',
                                        severity=severity, at=at, summary=f'{severity} {number}', site=self.bergen)
            made += services.queue_many([Notification(alarm=alarm, recipient=self.operator, channel='push', level=0,
                                                      queued_at=at)])
        return made

    def send(self, seconds=0, **options):
        return outbox.send_due(self.now + timedelta(seconds=seconds), **options)


class RetryTests(OutboxCase):
    def test_the_retry_times_are_seeded_per_severity(self):
        self.assertEqual(dict(SeverityPolicy.objects.values_list('severity', 'retry_seconds')),
                         {'critical': 30, 'warning': 120})

    @override_settings(ALARM_TRANSPORTS=FAILING)
    def test_a_failed_notification_is_tried_again_only_after_its_retry_time(self):
        (notification,) = self.queued()
        self.assertEqual((self.send().failed, self.send(10).retrying, self.send(29).failed), (1, 1, 0))
        self.assertEqual(self.send(30).failed, 1)
        attempts = list(DeliveryAttempt.objects.values_list('attempted_at', flat=True))
        self.assertEqual(attempts, [self.now, self.now + timedelta(seconds=30)])
        self.assertEqual(read.status(notification), 'queued')

    @override_settings(ALARM_TRANSPORTS=FAILING)
    def test_after_its_attempts_a_warning_is_failed_and_left(self):
        SeverityPolicy.objects.filter(severity='warning').update(delivery_attempts=2, retry_seconds=5)
        (notification,) = self.queued('warning')
        for second in range(0, 60, 5):
            self.send(second)
        self.assertEqual(DeliveryAttempt.objects.count(), 2)
        self.assertEqual(read.status(notification), 'failed')
        self.assertEqual(outbox.send_due(self.now + timedelta(hours=1)).backlog, 0)


class OrderTests(OutboxCase):
    @override_settings(ALARM_TRANSPORTS=RECORDING)
    def test_a_backlog_goes_out_critical_first_then_oldest(self):
        old_warning = self.queued('warning', minutes_ago=30)[0]
        new_critical = self.queued('critical', minutes_ago=1)[0]
        old_critical = self.queued('critical', minutes_ago=20)[0]
        new_warning = self.queued('warning', minutes_ago=2)[0]
        self.assertEqual(self.send().sent, 4)
        self.assertEqual([sent.pk for sent in RecordingTransport.sent],
                         [old_critical.pk, new_critical.pk, old_warning.pk, new_warning.pk])

    def test_a_backlog_waits_for_a_transport_and_goes_out_whole_once_it_answers(self):
        made = self.queued(count=40)
        with override_settings(ALARM_TRANSPORTS={}):
            nothing = self.send()
        self.assertEqual((nothing.waiting, nothing.backlog, nothing.oldest, DeliveryAttempt.objects.count()),
                         (40, 40, self.now, 0))
        with override_settings(ALARM_TRANSPORTS=FAILING):
            self.assertEqual(self.send(1).failed, 40)
        with override_settings(ALARM_TRANSPORTS=RECORDING):
            self.assertEqual(self.send(31).sent, 40)
            self.assertEqual(self.send(90).backlog, 0)
        self.assertEqual(sorted(sent.pk for sent in RecordingTransport.sent), sorted(row.pk for row in made))
        self.assertEqual(DeliveryAttempt.objects.filter(outcome='sent').count(), 40)


class NeverLostTests(OutboxCase):
    @override_settings(ALARM_TRANSPORTS=RECORDING)
    def test_a_sender_that_dies_after_the_transport_took_it_sends_it_again_never_loses_it(self):
        (notification,) = self.queued()
        real = services.attempt
        with mock.patch.object(services, 'attempt', side_effect=OperationalError('the server went away')), \
                self.assertLogs('alarms.outbox', level='ERROR'):           # logged, the round goes on
            self.send()
        self.assertEqual(read.status(notification), 'queued')               # nothing written: still to be sent
        with mock.patch.object(services, 'attempt', side_effect=real):
            self.assertEqual(self.send(1).sent, 1)
        self.assertEqual([sent.pk for sent in RecordingTransport.sent], [notification.pk, notification.pk])
        self.assertEqual(DeliveryAttempt.objects.filter(outcome='sent').count(), 1)
        self.assertEqual(read.status(notification), 'sent')
        self.assertEqual(self.send(2).sent, 0)

    @override_settings(ALARM_TRANSPORTS=RECORDING)
    def test_a_notification_another_sender_is_sending_is_left_to_it(self):
        (notification,) = self.queued()
        other = other_session()
        self.addCleanup(other.close)
        other.execute('SELECT pg_advisory_lock(%s, hashtext(%s))', [outbox.CLAIM, str(notification.pk)])
        found = self.send()
        self.assertEqual((found.busy, found.sent, RecordingTransport.sent), (1, 0, []))
        other.execute('SELECT pg_advisory_unlock_all()')
        self.assertEqual(self.send(1).sent, 1)

    @override_settings(ALARM_TRANSPORTS=RECORDING)
    def test_one_another_sender_sent_since_this_round_read_the_outbox_is_not_sent_again(self):
        (notification,) = self.queued()
        real = outbox._claim

        def claimed_after_the_other_sent_it(row):
            services.attempt(row, Sent('by the other sender'), self.now)
            return real(row)
        with mock.patch.object(outbox, '_claim', side_effect=claimed_after_the_other_sent_it):
            self.assertEqual(self.send().sent, 0)
        self.assertEqual(RecordingTransport.sent, [])
        self.assertEqual(DeliveryAttempt.objects.filter(outcome='sent').count(), 1)

    @override_settings(ALARM_TRANSPORTS=RECORDING)
    def test_a_pass_only_queues_the_sender_sends(self):
        self.rule()
        self.sample(5.5)
        engine.run_once(self.now)
        self.assertTrue(Notification.objects.exists())
        self.assertFalse(DeliveryAttempt.objects.exists())
        self.assertEqual(self.send().sent, Notification.objects.count())


class BadTransportTests(OutboxCase):
    @override_settings(ALARM_TRANSPORTS=HANGING)
    def test_a_transport_that_hangs_is_a_failed_attempt_after_the_timeout(self):
        HangingTransport.release.clear()
        self.addCleanup(HangingTransport.release.set)
        (notification,) = self.queued()
        started = time.monotonic()
        with self.assertLogs('alarms.outbox', level='ERROR'):
            found = self.send(timeout=0.3)
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(found.failed, 1)
        self.assertEqual(DeliveryAttempt.objects.get().detail, 'no answer in 0.3 s')

    @override_settings(ALARM_TRANSPORTS=RAISING)
    def test_a_transport_that_raises_is_a_failed_attempt(self):
        self.queued()
        with self.assertLogs('alarms.outbox', level='ERROR'):
            self.assertEqual(self.send(timeout=5).failed, 1)
        self.assertEqual(DeliveryAttempt.objects.get().detail, 'RuntimeError: the push library broke')

    @override_settings(ALARM_TRANSPORTS=RECORDING)
    def test_a_stopping_worker_ends_its_round_before_the_next_notification(self):
        self.queued(count=3)
        self.assertEqual(self.send(stop=lambda: len(RecordingTransport.sent) >= 1).sent, 1)


class WorkerRoundTests(OutboxCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(unlock_all)

    @NOTHING_CONNECTED                                         # the two wait: the row shows them
    def test_the_sender_writes_the_outbox_figures_on_the_workers_row(self):
        self.queued(minutes_ago=7, count=2)
        made = worker.Worker('alarms', worker.Timing(**TIMING), send=None)
        self.assertTrue(made._lead())
        found = made.send_round()
        row = AlarmWorkerStatus.objects.get()
        self.assertEqual((found.waiting, row.outbox_waiting, row.outbox_oldest_at), (2, 2, self.now - timedelta(minutes=7)))
        self.assertIsNotNone(row.last_send_at)


class SenderThreadTests(TransactionTestCase):
    """The worker as it runs (its loop, its sender thread, the real clock) on a thread of the test, the push service
    hanging: the alarm still opens within the 10 s, and passes go on while a send waits."""

    serialized_rollback = True

    @override_settings(ALARM_TRANSPORTS=HANGING)
    def test_a_transport_that_hangs_never_delays_an_alarm(self):
        HangingTransport.release.clear()
        HangingTransport.entered.clear()
        self.addCleanup(HangingTransport.release.set)
        farm = Farm(2)
        operators = role('Operators')
        get_user_model().objects.create_user('operator', 'operator@example.com', 'x').groups.add(operators)
        RecipientRule.objects.create(site=farm.site, min_severity='warning', level=0, channel='push', role=operators)
        made = worker.Worker('alarms', worker.Timing(**{**TIMING, 'tick': 0.2, 'sweep': 600, 'stale_after': 900,
                                                         'send_timeout': 30}))

        def run():
            try:
                made.run()
            finally:
                connection.close()
        thread = threading.Thread(target=run)
        thread.start()
        self.addCleanup(thread.join, 60)
        self.addCleanup(made.stop.set)
        until(lambda: watch.state().checked, START, 'the worker checking the alarms')
        farm.sample(farm.points[0], 5.5)
        until(lambda: Notification.objects.exists(), TARGET, 'the first alarm queued')
        until(HangingTransport.entered.is_set, TARGET, 'the sender stuck in a send')
        farm.sample(farm.points[1], 5.5)                    # the push service still hangs
        committed = time.monotonic()
        until(lambda: farm.units[1].pk in critical_units(), TARGET, 'the second alarm while the sender hangs')
        took = time.monotonic() - committed
        self.assertFalse(DeliveryAttempt.objects.exists())             # the first send has not come back
        HangingTransport.release.set()
        until(lambda: DeliveryAttempt.objects.filter(outcome='sent').count() == Notification.objects.count(), TARGET,
              'every notification sent once the push service answers')
        made.stop.set()
        thread.join(60)
        self.assertFalse(thread.is_alive())
        self.assertEqual(AlarmWorkerStatus.objects.get().state, 'stopped')
        self.assertLess(took, TARGET)
        self.assertEqual(Alarm.objects.filter(severity='critical', source='water_limit').count(), 2)


class SendSupervisionTests(OutboxCase):
    """A round of the sender that fails (the outbox itself unreadable: not a transport's refusal) is the alarm system's
    step 'send': a critical alarm of its own from the next pass until a round passes again."""

    def setUp(self):
        super().setUp()
        self.addCleanup(unlock_all)

    def test_a_failed_round_is_said_to_the_next_pass_and_a_good_one_ends_it(self):
        made = worker.Worker('alarms', worker.Timing(**{**TIMING, 'tick': 0.05}), run_pass=mock.Mock(
            return_value=engine.Summary()), send=mock.Mock(side_effect=RuntimeError('the outbox cannot be read')))
        self.assertTrue(made._lead())
        with mock.patch.object(worker, '_reset'), self.assertLogs('alarms.worker', level='ERROR'):
            thread = threading.Thread(target=made._sender)
            thread.start()
            until(lambda: made.send.call_count >= 1, 10, 'a round of the sender')
            made._done.set()
            thread.join(10)
        self.assertTrue(made._send_failing)
        made._pass()
        made.run_pass.assert_called_once_with(outside={'send': True})

    def test_the_pass_raises_the_step_alarm_and_ends_it(self):
        summary = engine.run_once(self.now, outside={'send': True})
        self.assertIn('send', summary.failed_steps)
        alarm = Alarm.objects.get(source='system', parameter='step_failed')
        self.assertEqual(alarm.severity, 'critical')
        self.assertIn('"send"', alarm.summary)
        for minute in (1, 2, 3):
            self.assertNotIn('send', engine.run_once(self.now + timedelta(minutes=minute),
                                                     outside={'send': False}).failed_steps)
        self.assertFalse(read.is_open(alarm))

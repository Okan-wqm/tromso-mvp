"""The independent review of the alarm worker (2026-11-23, F1-F11 and three surviving mutants), each finding held by a
test that fails without its fix:

- F1: a critical notification is never given up silently: it is tried again, the wait doubling up to the escalation
  time, until its alarm is acknowledged (N7: clearing does not end it); one that cannot be delivered past the escalation
  time is a critical alarm of the alarm system and is said on the pages; warnings keep their attempts.
- F2, F3: the notice is live on the monitoring wall, on every alarm page, says when nothing is sent, when the sender is
  silent and when criticals cannot be delivered; the worker's figures and timings are shown read-only.
- F4: a worker on a new database session takes the lock again with its session's settings; a lost database clears its
  leadership.
- F5: a critical is never behind a round of warnings; a round has a deadline.
- F6: a round reads the outbox's queue, never the whole history.
- F7: the gap marker stays until a pass whose supervision passed.
- F8: the watchdog ends a hung process (a pass or the loop), without shutting the log down; the sender's join is
  bounded; the database settings bound a connect and find a dead peer.
- F9: the alarm system's own criticals are never snoozed; one alarm's snoozes together at most the longest; the people
  notified are told of a snooze, and told again when it ends with the alarm still open.
- F10: a critical's retry time and flood window are bounded tighter; each failed step is its own flood kind.
- F11: the dead man is not asked while something it vouches for does not hold (the ingest dead, notifications
  undeliverable), nor after a failed pass outside its throttle."""
import threading
import time
from datetime import timedelta
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import DatabaseError, OperationalError, connection, transaction
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.testing import assert_reads_do_not_grow, reads
from farm.tests.helpers import may_record, role
from sensors.models import Connection, IngestStatus
from sensors.tests import make_connection

from .. import engine, floods, models, outbox, read, services, watch, worker
from ..models import Alarm, AlarmWorkerStatus, DeliveryAttempt, Notification, SeverityPolicy
from . import NOTHING_CONNECTED, AlarmsCase
from .doubles import RecordingTransport
from .test_worker import TIMING, make, unlock_all

FAILING = {'push': 'alarms.tests.doubles.FailingTransport'}
RECORDING = {'push': 'alarms.tests.doubles.RecordingTransport'}


class Case(AlarmsCase):
    def setUp(self):
        super().setUp()
        RecordingTransport.sent.clear()
        self.addCleanup(RecordingTransport.sent.clear)
        self.addCleanup(unlock_all)

    def at(self, minutes=0, seconds=0):
        return self.now + timedelta(minutes=minutes, seconds=seconds)

    def system(self, count, severity, seconds=0, parameter='sensors_failed', to=None):
        at = self.at(seconds=seconds)
        made = []
        for number in range(count):
            alarm = services.open_alarm(source='system', farm_wide=True, parameter=parameter, severity=severity, at=at,
                                        summary=f'{parameter} {severity} {seconds}/{number}', site=self.bergen)
            made += services.queue_many([Notification(alarm=alarm, recipient=to or self.operator, channel='push',
                                                      level=0, queued_at=at)])
        return made


# ---- F1 --------------------------------------------------------------------------------------------------------------
@override_settings(ALARM_TRANSPORTS=FAILING)
class CriticalNeverGivenUpTests(Case):
    def test_a_critical_failing_for_an_hour_is_tried_all_along_and_said_undeliverable(self):
        self.rule()
        self.sample(5.5)
        for minute in range(61):
            self.loop(minutes=minute)
        alarm = self.critical()
        (notification,) = Notification.objects.filter(alarm=alarm)
        times = list(DeliveryAttempt.objects.filter(notification=notification).values_list('attempted_at', flat=True))
        self.assertGreater(len(times), 10)                                   # past its 5 attempts
        gaps = [later - earlier for earlier, later in zip(times, times[1:])]
        self.assertLessEqual(max(gaps), timedelta(minutes=6))                # never more than the escalation time apart
        self.assertGreater(times[-1], self.at(54))                          # still tried in the last minutes
        self.assertEqual(read.status(notification), 'queued')
        self.assertTrue(models.OutboxEntry.objects.filter(notification=notification).exists())
        found = Alarm.objects.get(source='system', parameter='notifications_undeliverable')
        self.assertEqual(found.severity, 'critical')
        self.assertFalse(hasattr(found, 'clearance'))
        self.assertEqual(outbox.send_due(self.at(61)).undeliverable, 2)       # its own notification too

    def test_once_acknowledged_it_has_its_attempts_then_it_is_given_up(self):
        self.rule()
        self.sample(5.5)
        self.loop()
        alarm = self.critical()
        may_record(self.manager, 'change_alarm')         # Alarms: Edit: the service asks who may (L-5)
        services.acknowledge(alarm, self.manager, at=self.at(1))
        for minute in range(2, 40):
            self.loop(minutes=minute)
        (notification,) = Notification.objects.filter(alarm=alarm)
        self.assertEqual(DeliveryAttempt.objects.filter(notification=notification).count(), 5)
        self.assertEqual(read.status(notification), 'failed')
        self.assertFalse(models.OutboxEntry.objects.filter(notification=notification).exists())

    def test_a_warning_keeps_its_attempts(self):
        self.rule()
        self.sample(6.2)
        for minute in range(0, 30):
            self.loop(minutes=minute)
        (notification,) = Notification.objects.all()
        self.assertEqual(DeliveryAttempt.objects.filter(notification=notification).count(), 5)
        self.assertEqual(read.status(notification), 'failed')
        self.assertFalse(Alarm.objects.filter(parameter='notifications_undeliverable').exists())

    def test_the_wait_doubles_up_to_the_escalation_time(self):
        rules = outbox.alarm_rules.current()
        row = self.system(1, 'critical')[0]
        row.acknowledged = False
        waits = []
        for failures in range(1, 9):
            row.failures = failures
            waits.append(outbox.retry_wait(row, rules).total_seconds())
        self.assertEqual(waits, [30, 60, 120, 240, 300, 300, 300, 300])
        row.acknowledged = True
        self.assertEqual(outbox.retry_wait(row, rules).total_seconds(), 30)


# ---- F5, F6 ------------------------------------------------------------------------------------------------------------
class SlowTransport(RecordingTransport):
    """A push service that takes 0.2 s for every send, of the round's clock: `clock` is the one the tests give the round
    (outbox.send_due's `clock`), so where a round's deadline falls is the same on any machine."""
    elapsed = 0.0

    @classmethod
    def clock(cls):
        return cls.elapsed

    def send(self, notification, flood=None):
        type(self).elapsed += 0.2
        return super().send(notification, flood)


@override_settings(ALARM_TRANSPORTS={'push': 'alarms.tests.test_review_fixes.SlowTransport'})
class RoundTests(Case):
    def setUp(self):
        super().setUp()
        SlowTransport.elapsed = 0.0

    def test_a_round_ends_at_its_deadline_and_the_rest_goes_next(self):
        for number in range(12):                                  # each its own kind: no flood message
            self.system(1, 'warning', parameter=f'p{number}')
        found = outbox.send_due(self.now, round_seconds=0.3, clock=SlowTransport.clock)
        self.assertEqual((found.sent, found.deferred), (2, 10))  # sent at 0 s and 0.2 s; at 0.4 s its deadline is past
        self.assertEqual(outbox.send_due(self.now).sent + found.sent, 12)

    def test_a_critical_queued_during_a_round_of_warnings_ends_it_and_goes_first(self):
        for number in range(3):
            self.system(1, 'warning', parameter=f'w{number}')
        real = SlowTransport.send
        made = []

        def send(transport, notification, flood=None):
            if not made:
                made.extend(self.system(1, 'critical', seconds=1, parameter='urgent'))
            return real(transport, notification, flood)
        with mock.patch.object(SlowTransport, 'send', send):
            found = outbox.send_due(self.now)
        self.assertEqual((found.sent, found.deferred), (1, 2))
        outbox.send_due(self.now + timedelta(seconds=2))
        self.assertEqual(RecordingTransport.sent[1].pk, made[0].pk)


class QueueTests(Case):
    """F6: what a round reads of each history table does not grow with the history. Measured beside 50,000 and again
    beside 100,000 notifications of history (each sent 30 days before the test's moment), counted by PostgreSQL
    (core.testing.reads): the 50,000 more must add fewer than a hundred rows read, where a scan of the history adds
    them all. A difference, so what does not depend on the history counts alike on both sides: the queue's own rows,
    and the planner's look at an index's ends (at most a hundred heap pages of rows this transaction wrote and no
    vacuum has seen)."""
    STEP = 50_000
    HISTORY_TABLES = ('alarms', 'alarm_notifications', 'alarm_delivery_attempts')

    def grow(self):
        """STEP more alarms, each notified to the operator and sent 30 days before the test's moment. Returns STEP."""
        with connection.cursor() as cursor:
            cursor.execute("INSERT INTO alarms (source, parameter, severity, opened_at, summary) SELECT 'system', 'old', "
                           "'warning', %s::timestamptz - interval '30 days', 'old ' || n FROM generate_series(1, %s) n",
                           [self.now, self.STEP])
            cursor.execute('INSERT INTO alarm_notifications (alarm_id, recipient_id, channel, level, queued_at, kind) '
                           "SELECT a.id, %s, 'push', 0, a.opened_at, 'alarm' FROM alarms a WHERE a.parameter = 'old' "
                           'AND NOT EXISTS (SELECT 1 FROM alarm_notifications n WHERE n.alarm_id = a.id)',
                           [self.operator.pk])
            cursor.execute("INSERT INTO alarm_delivery_attempts (notification_id, attempted_at, outcome, detail, "
                           "flood_key) SELECT n.id, n.queued_at, 'sent', '', '' FROM alarm_notifications n JOIN alarms a "
                           "ON a.id = n.alarm_id WHERE a.parameter = 'old' AND NOT EXISTS (SELECT 1 FROM "
                           'alarm_delivery_attempts d WHERE d.notification_id = n.id)')
            cursor.execute('ANALYZE alarms; ANALYZE alarm_notifications; ANALYZE alarm_delivery_attempts; '
                           'ANALYZE alarm_outbox')
        return self.STEP

    def test_a_round_reads_the_queue_never_the_whole_history(self):
        queued = sorted(row.pk for row in self.system(3, 'critical'))

        def backlog():
            with reads() as found:
                rows = outbox.backlog()
            self.assertEqual(sorted(row.pk for row in rows), queued)
            return found
        assert_reads_do_not_grow(self, self.grow, backlog, self.HISTORY_TABLES, 'backlog()')

    @override_settings(ALARM_TRANSPORTS=RECORDING)
    def test_a_sending_round_reads_the_recent_attempts_never_the_whole_history(self):
        """The whole round as the worker's sender runs it, sending three criticals (each its own kind, so each goes on
        its own): its flood check reads the attempts of the flood window by their time (alarms 0024), never all."""
        rounds = []

        def round_():
            queued = [row for number in range(3)
                      for row in self.system(1, 'critical', parameter=f'queued{len(rounds)}{number}')]
            RecordingTransport.sent.clear()
            with reads() as found:
                delivery = outbox.send_due(self.now)
            self.assertEqual((delivery.sent, sorted(row.pk for row in RecordingTransport.sent)),
                             (3, sorted(row.pk for row in queued)))
            rounds.append(found)
            return found
        assert_reads_do_not_grow(self, self.grow, round_, self.HISTORY_TABLES, 'a sending round')


# ---- F9 ----------------------------------------------------------------------------------------------------------------
class SnoozeRuleTests(Case):
    def setUp(self):
        super().setUp()
        self.snoozer = may_record(get_user_model().objects.create_user('snoozer', 'snoozer@example.com', 'x'),
                                  'add_alarmshelve')
        self.rule()
        self.sample(5.5)
        self.loop()
        self.alarm = self.critical()

    def test_the_alarm_systems_own_critical_alarm_is_never_snoozed(self):
        own = services.open_alarm(source='system', farm_wide=True, parameter='alarms_unchecked', severity='critical', at=self.now,
                                  summary='not checked')
        with self.assertRaisesMessage(ValidationError, 'never snoozed'):
            services.shelve(own, self.snoozer, 10, 'busy', at=self.at(1))

    def test_one_alarms_snoozes_together_are_at_most_the_longest(self):
        services.shelve(self.alarm, self.snoozer, 200, 'cleaning', at=self.at(1))
        services.unshelve(self.alarm, self.snoozer, at=self.at(11))           # 10 minutes used
        with self.assertRaisesMessage(ValidationError, 'at most 230 more'):
            services.shelve(self.alarm, self.snoozer, 235, 'again', at=self.at(12))
        services.shelve(self.alarm, self.snoozer, 230, 'again', at=self.at(12))

    def test_the_people_notified_are_told_of_a_snooze_and_told_again_when_it_ends(self):
        row = services.shelve(self.alarm, self.snoozer, 30, 'probe cleaned', at=self.at(1))
        told = Notification.objects.get(kind='snoozed')
        self.assertEqual((told.recipient, told.shelve, told.alarm), (self.operator, row, self.alarm))
        self.loop(minutes=20)
        self.assertFalse(Notification.objects.filter(kind='resumed').exists())
        self.loop(minutes=32)                                                 # it ran out at 31, the alarm open
        again = Notification.objects.get(kind='resumed')
        self.assertEqual((again.recipient, again.shelve, again.queued_at), (self.operator, row, self.at(32)))
        self.loop(minutes=33)
        self.assertEqual(Notification.objects.filter(kind='resumed').count(), 1)        # once per snooze

    def test_an_acknowledged_alarm_is_not_told_again(self):
        services.shelve(self.alarm, self.snoozer, 30, 'probe cleaned', at=self.at(1))
        services.acknowledge(self.alarm, self.operator, at=self.at(5))
        self.loop(minutes=40)
        self.assertFalse(Notification.objects.filter(kind='resumed').exists())


# ---- F10 ---------------------------------------------------------------------------------------------------------------
class BoundTests(Case):
    def test_a_criticals_retry_and_flood_window_are_bounded_tighter(self):
        for values in ({'retry_seconds': 301}, {'flood_window_seconds': 301}):
            with self.subTest(values=values), self.assertRaises(DatabaseError), transaction.atomic():
                SeverityPolicy.objects.filter(severity='critical').update(**values)
        SeverityPolicy.objects.filter(severity='warning').update(retry_seconds=3600, flood_window_seconds=3600)

    def test_each_failed_step_is_its_own_flood_kind(self):
        one = Alarm(source='system', parameter='step_failed', severity='critical', summary='The alarm step "water" '
                    'failed', site=None)
        two = Alarm(source='system', parameter='step_failed', severity='critical', summary='The alarm step "notify" '
                    'failed', site=None)
        self.assertNotEqual(floods.key(one), floods.key(two))


# ---- F3: the notice and the health check say the sender and the undeliverable ones ------------------------------------
class WatchTests(Case):
    def row(self, **fields):
        now = timezone.now()
        values = dict(state='running', started_at=now - timedelta(hours=1), heartbeat_at=now, last_pass_at=now,
                      last_ok_pass_at=now, stale_after_seconds=45, last_send_at=now)
        AlarmWorkerStatus.objects.update_or_create(name='alarms', defaults={**values, **fields})

    def test_a_silent_sender_and_undeliverable_criticals_are_said(self):
        self.client.force_login(get_user_model().objects.create_superuser('admin', 'admin@example.com', 'x'))
        cases = [({'last_send_at': timezone.now() - timedelta(minutes=5)}, watch.SENDER,
                  'The alarm notifications are NOT being sent'),
                 ({'undeliverable': 2, 'undeliverable_since': timezone.now() - timedelta(minutes=9)},
                  watch.UNDELIVERABLE, '2 critical notifications cannot be delivered')]
        for fields, reason, words in cases:
            with self.subTest(reason=reason):
                self.row(**fields)
                self.assertEqual(watch.state().reason, reason)
                self.assertContains(self.client.get(reverse('alarms:alarm_list')), words)
                from io import StringIO
                from django.core.management import call_command
                with self.assertRaises(SystemExit):
                    call_command('alarm_worker_health', stderr=StringIO())
                AlarmWorkerStatus.objects.all().delete()


# ---- F2: every alarm page, the live notice on the wall, "nothing is sent" ----------------------------------------------
class PageTests(Case):
    def setUp(self):
        super().setUp()
        self.client.force_login(get_user_model().objects.create_superuser('admin', 'admin@example.com', 'x'))

    def test_every_alarm_page_says_when_none_is_checked(self):
        for name in ('alarms:recipientrule_list', 'alarms:severitypolicy_list', 'alarms:parameterdeadband_list',
                     'sensors:alarmrule_list', 'sensors:alarm_events'):
            with self.subTest(page=name):
                self.assertContains(self.client.get(reverse(name)), 'The alarms are NOT being checked')

    @NOTHING_CONNECTED
    def test_the_wall_asks_for_the_notice_again_and_it_follows_the_worker(self):
        wall = self.client.get(reverse('monitoring:monitor'))
        self.assertContains(wall, f'data-poll="{reverse("alarms:alarm_watch_notice")}?sent_note=1"')
        notice = reverse('alarms:alarm_watch_notice') + '?sent_note=1'
        self.assertContains(self.client.get(notice), 'no alarm worker has run here')
        now = timezone.now()
        AlarmWorkerStatus.objects.create(name='alarms', state='running', started_at=now, heartbeat_at=now,
                                         last_pass_at=now, last_ok_pass_at=now, last_send_at=now, stale_after_seconds=45)
        page = self.client.get(notice).content.decode()
        self.assertNotIn('NOT being checked', page)
        self.assertIn('Nothing is sent yet: the push transport is not connected', page)
        AlarmWorkerStatus.objects.update(state='stopped')
        self.assertContains(self.client.get(notice), 'the alarm worker stopped')

    def test_the_notice_is_the_walls_readers(self):
        reader = get_user_model().objects.create_user('reader', 'reader@example.com', 'x')
        self.client.force_login(reader)
        self.assertEqual(self.client.get(reverse('alarms:alarm_watch_notice')).status_code, 403)
        reader.groups.add(role('Wall', 'view_stockoperation'))
        self.assertEqual(self.client.get(reverse('alarms:alarm_watch_notice')).status_code, 200)

    @NOTHING_CONNECTED
    def test_the_sensors_overview_says_nothing_is_sent(self):
        self.assertContains(self.client.get(reverse('sensors:home')), 'Nothing is sent yet')

    def test_the_workers_figures_and_timings_are_shown(self):
        now = timezone.now()
        AlarmWorkerStatus.objects.create(name='alarms', state='running', host='alarms-1', started_at=now,
                                         heartbeat_at=now, last_pass_at=now, last_ok_pass_at=now, last_send_at=now,
                                         stale_after_seconds=45, outbox_waiting=7, outbox_oldest_at=now)
        page = self.client.get(reverse('alarms:alarm_list')).content.decode()
        for words in ('The alarm worker', 'alarms-1', 'Notifications waiting', '7',
                      f'looks every {settings.ALARM_WORKER["tick"]} s'):
            self.assertIn(words, page)


# ---- F4, F7, F8, F11 and the mutants: the worker ------------------------------------------------------------------------
class WorkerTests(Case):
    def test_a_new_database_session_is_found_and_the_lock_taken_again_with_its_settings(self):
        made = make(5)
        sessions = mock.Mock(wraps=made._session)
        made._session = sessions
        holds = iter([False] + [True] * 10)
        made._holds = lambda: next(holds)
        with self.assertLogs('alarms.worker', level='WARNING') as logged:
            made.run()
        self.assertEqual(sessions.call_count, 2)
        self.assertIn('takes the lock again', '\n'.join(logged.output))

    def test_a_lost_database_clears_the_leadership(self):
        results = [OperationalError('the session was cut'), engine.Summary()]
        made = make(20, run_pass=mock.Mock(side_effect=lambda **kw: _next(results)))
        sessions = mock.Mock(wraps=made._session)
        made._session = sessions
        with self.assertLogs('alarms.worker', level='ERROR'):
            made.run()
        self.assertEqual(sessions.call_count, 2)                           # the lock taken again on the new session

    def test_the_gap_stays_until_a_pass_whose_supervision_passed(self):
        made = make(40, run_pass=mock.Mock(side_effect=[engine.Summary(failed_steps=['supervision']),
                                                        engine.Summary(), engine.Summary()]))
        made._unchecked = ('from', 'to')
        made.leading, made._pid = True, None
        made._holds = lambda: True
        made.run()
        calls = made.run_pass.call_args_list
        self.assertEqual([call.kwargs.get('unchecked') for call in calls], [('from', 'to'), ('from', 'to'), None])

    def test_the_watchdog_thread_ends_a_hung_pass(self):
        # The watchdog thread on the worker's clock, which the test holds: the pass starts at 0 and hangs; the clock
        # is moved to 10 ms short of hang_exit (0.5 s) for two of the watchdog's looks, then to hang_exit. It must end
        # the process at the first look at hang_exit and at no look before: its bound, exactly, on any machine.
        release, ended, moment, looks = threading.Event(), [], [0.0], []
        self.addCleanup(release.set)

        def hung_pass():
            ended.append(release.wait(20))         # True: the process's end let it go (20 s: a ceiling, never a measure)
            return engine.Summary()
        made = worker.Worker('alarms', worker.Timing(**{**TIMING, 'tick': 0.05, 'hang_exit': 0.5,
                                                        'statement_timeout': 0.2}),
                             run_pass=hung_pass, send=False, clock=lambda: moment[0],
                             exit_now=mock.Mock(side_effect=lambda code: (release.set(), made.stop.set())))
        made._session = lambda: None              # (its idle-transaction limit would end the test's own session)
        look = made.check_hang

        def watched():
            fired = look()
            looks.append((moment[0], fired))
            started = made._pass_started
            if started is not None and not fired:
                short = sum(at == started + 0.49 for at, _fired in looks)
                moment[0] = started + 0.5 if short >= 2 else started + 0.49
            return fired
        made.check_hang = watched
        with mock.patch('logging.shutdown') as shutdown, self.assertLogs('alarms.worker', level='CRITICAL'):
            made.run()
        self.assertEqual(ended, [True])           # one pass, ended by the watchdog while it hung
        self.assertEqual([fired for at, fired in looks if at < 0.5], [False] * len([at for at, _ in looks if at < 0.5]))
        self.assertEqual(sum(at == 0.49 for at, _fired in looks), 2)
        self.assertEqual(next(at for at, fired in looks if fired), 0.5)
        made.exit_now.assert_called_with(1)
        shutdown.assert_not_called()

    def test_the_watchdog_ends_a_loop_that_does_not_come_round(self):
        made = make(1)
        made._looped_at = made.clock() - 121
        with self.assertLogs('alarms.worker', level='CRITICAL'):
            self.assertTrue(made.check_hang())

    def test_a_sender_that_hangs_does_not_hold_the_stop(self):
        release, senders = threading.Event(), []
        self.addCleanup(release.set)

        def hanging(stop):
            senders.append(threading.current_thread())
            return release.wait(30) and outbox.Delivery()   # (30 s: a ceiling, never a measure)
        made = worker.Worker('alarms', worker.Timing(**{**TIMING, 'tick': 0.05, 'send_timeout': 0.3}),
                             run_pass=mock.Mock(return_value=engine.Summary()), send=hanging, exit_now=mock.Mock())
        threading.Timer(0.5, made.stop.set).start()
        with self.assertLogs('alarms.worker', level='ERROR') as logged, \
                mock.patch.object(threading.Thread, 'join', autospec=True, side_effect=threading.Thread.join) as join:
            made.run()
        self.assertTrue(senders)
        self.assertTrue(senders[0].is_alive())    # the worker stopped while its sender still hung in the send
        # and waited for it no longer than its bound: one join of the sender, of send_timeout and a tick
        self.assertEqual([call.args[1:] for call in join.call_args_list if call.args[0] is senders[0]],
                         [(made.timing.send_timeout + made.timing.tick,)])
        self.assertIn('leaves its thread', '\n'.join(logged.output))

    def test_the_database_settings_bound_a_connect_and_find_a_dead_peer(self):
        options = settings.DATABASES['default']['OPTIONS']
        self.assertGreater(options['connect_timeout'], 0)
        self.assertEqual(options['keepalives'], 1)


class PingTests(Case):
    URL = 'https://dead-man.invalid/ping'

    def worker(self, summaries, count=45):
        asked = []
        made = make(count, run_pass=mock.Mock(side_effect=summaries), deadman_url=self.URL, deadman_every=30.0,
                    deadman_timeout=5.0, sweep=10.0)
        made.ping = lambda url, timeout: asked.append(made.clock() - 1000)
        made.spawn = lambda target, args: target(*args)
        return made, asked

    def test_not_after_a_failed_pass_outside_the_throttle(self):
        good, bad = engine.Summary(), engine.Summary(failed_steps=['water'])
        made, asked = self.worker([good, good, good, bad, good])
        made.run()
        self.assertEqual(asked, [0, 40])                          # 30 failed: not then, though the throttle had passed

    def test_not_while_the_ingest_is_dead_or_criticals_cannot_be_delivered(self):
        made, asked = self.worker([engine.Summary()] * 5)
        IngestStatus.objects.create(connection_id=make_connection().pk,
                                    heartbeat_at=timezone.now() - timedelta(minutes=10), connected=True)
        with self.assertLogs('alarms.worker', level='WARNING'):
            made.run()
        self.assertEqual(asked, [])
        Connection.objects.update(is_active=False)
        made, asked = self.worker([engine.Summary()] * 5)
        AlarmWorkerStatus.objects.all().delete()
        real_lead = made._lead

        def lead():
            got = real_lead()
            AlarmWorkerStatus.objects.update(undeliverable=1, undeliverable_since=timezone.now())
            return got
        made._lead = lead
        with self.assertLogs('alarms.worker', level='WARNING'):
            made.run()
        self.assertEqual(asked, [])


def _next(results):
    found = results.pop(0)
    if isinstance(found, Exception):
        raise found
    return found


class CutSessionTests(TransactionTestCase):
    """A connection opened again inside a pass (Django's after an error) is a new session: the worker finds it at its
    next look and takes the lock on it, with its settings."""

    serialized_rollback = True

    def test_a_session_cut_inside_a_pass_is_taken_again(self):
        def a_pass_whose_session_is_replaced(**kwargs):
            connection.close()                        # the next statement opens a new session, without the lock
            return engine.Summary()
        made = worker.Worker('alarms', worker.Timing(**{**TIMING, 'tick': 0.05, 'sweep': 0.05}),
                             run_pass=a_pass_whose_session_is_replaced, send=False)
        pids = []

        def run():
            try:
                made.run()
            finally:
                connection.close()
        real = made._lead

        def lead():
            got = real()
            if got and made._pid not in pids:
                pids.append(made._pid)
            return got
        made._lead = lead
        thread = threading.Thread(target=run)
        thread.start()
        deadline = time.monotonic() + 20
        while len(pids) < 3 and time.monotonic() < deadline:
            time.sleep(0.05)
        made.stop.set()
        thread.join(20)
        self.assertGreaterEqual(len(pids), 3)          # each pass's new session found and the lock taken on it
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM pg_stat_activity WHERE application_name = 'alarm-worker' "
                           "AND datname = current_database()")
            self.assertEqual(cursor.fetchone()[0], 0)

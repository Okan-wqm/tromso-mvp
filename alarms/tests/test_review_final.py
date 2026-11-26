"""The last recheck of the alarm worker (9dc3cafe, REVIEW3.md) and the coordinator's bar on it: no known way to drop or
delay an open or newly cleared critical on a connected transport. Each held by a test that fails without its fix:

- N7 (probe T18): a critical that clears while the transport is connected but failing is never given up: only an
  acknowledgement ends a critical's retries; when it is delivered it says "Critical, now cleared";
- batch, never drop (probes M1, M2): the first critical of a kind goes at once; the next open criticals of that kind for
  that person are never covered: they are collected for the critical rule's follow-up time (5 s, at most 8 s; 0: at
  once) and go as one follow-up message naming every unit and how many are open now, each within 30 s; a different tank
  of the same quantity is named too;
- D8c: the summaries of old cleared criticals go after the criticals' messages in a round;
- the follow-up after a cleared flood counts only the alarms it tells;
- an error inside `is_due` follows the retry wait (no attempt a tick), and the critical it hides still raises the
  supervision alarm; an error while a group is judged or sent is a failed attempt of its notifications (never of one
  that went already)."""
import re
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import DatabaseError, transaction
from django.test import override_settings

from farm.tests.helpers import may_record, point_of
from farm.tests.test_stock import make_unit

from .. import floods, outbox, read, services
from ..models import Alarm, DeliveryAttempt, Notification, OutboxEntry, SeverityPolicy
from .doubles import RecordingTransport
from .test_review_fixes import Case

RECORDING = {'push': 'alarms.tests.doubles.RecordingTransport'}
FAILING = {'push': 'alarms.tests.doubles.FailingTransport'}


class FinalCase(Case):
    def setUp(self):
        super().setUp()
        RecordingTransport.floods.clear()
        self.addCleanup(RecordingTransport.floods.clear)

    def rounds(self, start, end, step=1):
        """A round through the outbox every `step` seconds from `start` to `end` (seconds after self.now), both in."""
        for second in range(start, end + 1, step):
            outbox.send_due(self.at(seconds=second))

    def told(self, notification):
        """Whether the person was told of it: its attempt says sent, and a message handed to the transport names it."""
        return (DeliveryAttempt.objects.filter(notification=notification, outcome='sent').exists()
                and any(notification.alarm.summary in sent.text for sent in RecordingTransport.sent))

    def reaches(self, notification, start, within=30):
        """The seconds after `start` until the person is told of it (a round every second), None if not within."""
        for second in range(0, within + 1):
            outbox.send_due(self.at(seconds=start + second))
            if self.told(notification):
                return second
        return None

    def tank(self, code):
        return point_of(make_unit(code, self.hall, system=self.ras))

    def oxygen(self, point, seconds):
        """A critical dissolved-oxygen alarm of `point`, opened `seconds` after self.now, its notification to the
        operator queued then."""
        at = self.at(seconds=seconds)
        alarm = services.open_alarm(source='water_limit', point=point, parameter='oxygen_mg_l', severity='critical',
                                    at=at, summary=f'{point.owner.code} · {point.name}: Dissolved oxygen 3.1 (critical)',
                                    site=self.bergen, production_department=self.hall)
        (made,) = services.queue_many([Notification(alarm=alarm, recipient=self.operator, channel='push', level=0,
                                                    queued_at=at)])
        return made


# ---- N7 -----------------------------------------------------------------------------------------------------------------
class ClearedWhileFailingTests(FinalCase):
    def test_a_critical_that_clears_while_the_transport_fails_is_delivered_once_saying_so(self):       # probe T18
        (notification,) = self.system(1, 'critical')
        with override_settings(ALARM_TRANSPORTS=FAILING):
            self.rounds(0, 50, step=10)
            services.clear(notification.alarm, self.at(1), 'restored')                 # it clears at +60 s
            self.rounds(60, 300, step=10)                                              # the push service fails 5 min
        self.assertTrue(OutboxEntry.objects.filter(notification=notification).exists())       # never given up
        with override_settings(ALARM_TRANSPORTS=RECORDING):
            self.rounds(310, 660, step=10)                                             # it recovers
        self.assertEqual([sent.pk for sent in RecordingTransport.sent], [notification.pk])
        self.assertIn('Critical, now cleared', RecordingTransport.sent[0].text)
        self.assertEqual(DeliveryAttempt.objects.filter(notification=notification, outcome='sent').count(), 1)
        self.assertEqual(read.status(notification), 'sent')
        self.assertFalse(OutboxEntry.objects.filter(notification=notification).exists())

    def test_an_acknowledgement_still_ends_its_retries(self):
        (notification,) = self.system(1, 'critical')
        services.clear(notification.alarm, self.at(1), 'restored')
        may_record(self.manager, 'change_alarm')         # Alarms: Edit: the service asks who may (L-5)
        services.acknowledge(notification.alarm, self.manager, at=self.at(1))
        with override_settings(ALARM_TRANSPORTS=FAILING):
            self.rounds(60, 1200, step=30)
        self.assertEqual(DeliveryAttempt.objects.filter(notification=notification).count(), 5)
        self.assertFalse(OutboxEntry.objects.filter(notification=notification).exists())


# ---- batch, never drop ------------------------------------------------------------------------------------------------
@override_settings(ALARM_TRANSPORTS=RECORDING)
class OpenCriticalsAreNeverCoveredTests(FinalCase):
    def test_m1_an_open_critical_after_a_mixed_flood_reaches_the_person_by_name(self):                # probe M1
        first, second, third = self.system(3, 'critical')
        for row in (first, third):
            services.clear(row.alarm, self.at(seconds=10), 'restored')
        self.rounds(20, 54)                                                    # the flood is told, whatever its form
        for row in (first, second, third):
            self.assertTrue(self.told(row), row.alarm.summary)
        (fresh,) = self.system(1, 'critical', seconds=55)                       # 35 s after the flood's first message
        self.assertIsNotNone(self.reaches(fresh, 55))
        self.assertFalse(DeliveryAttempt.objects.filter(outcome='grouped').exists())

    def test_m2_an_open_critical_after_a_flood_that_cleared_reaches_the_person_by_name(self):         # probe M2
        made = self.system(3, 'critical')
        self.rounds(1, 19)
        for row in made:
            services.clear(row.alarm, self.at(seconds=20), 'restored')
        self.rounds(20, 39)
        (fresh,) = self.system(1, 'critical', seconds=40)
        self.assertIsNotNone(self.reaches(fresh, 40))
        self.assertFalse(DeliveryAttempt.objects.filter(outcome='grouped').exists())

    def test_every_tank_of_one_quantity_is_named_and_a_later_tank_reaches_the_person(self):
        points = [self.mid1] + [self.tank(f'T-0{number}') for number in (2, 3, 4)]
        made = [self.oxygen(point, 0) for point in points[:3]]
        self.assertEqual(len({floods.key(row.alarm) for row in made}), 1)                 # one kind
        self.rounds(1, 40)
        for row in made:                                                        # each tank by name, none covered
            self.assertTrue(self.told(row), row.alarm.summary)
        fourth = self.oxygen(points[3], 45)
        self.assertIsNotNone(self.reaches(fourth, 45))
        self.assertFalse(DeliveryAttempt.objects.filter(outcome='grouped').exists())

    def test_the_first_goes_at_once_the_next_ones_as_one_message_naming_each_and_how_many_are_open(self):
        (first,) = self.system(1, 'critical')
        outbox.send_due(self.at(seconds=1))
        self.assertEqual([sent.pk for sent in RecordingTransport.sent], [first.pk])     # at once, on its own
        followers = self.system(3, 'critical', seconds=3)
        services.clear(followers[2].alarm, self.at(seconds=5), 'restored')
        for second in range(3, 34):
            outbox.send_due(self.at(seconds=second))
            if all(self.told(row) for row in followers):
                break
        self.assertLessEqual(second - 3, 30)                                    # within 30 s of the first of them
        self.assertEqual(len(RecordingTransport.sent), 2)                       # one follow-up message for the three
        text = RecordingTransport.sent[1].text
        for row in followers:
            self.assertIn(row.alarm.summary, text)
        self.assertIn('2 open now', text)
        self.assertEqual(DeliveryAttempt.objects.filter(outcome='sent').count(), 4)
        self.assertFalse(OutboxEntry.objects.exists())

    def test_the_follow_up_after_a_cleared_flood_counts_only_what_it_tells(self):                      # probe T17
        for row in self.system(3, 'critical'):
            services.clear(row.alarm, self.at(1), 'restored')
        self.rounds(120, 150)
        told = len(RecordingTransport.sent)
        (fresh,) = self.system(1, 'critical', seconds=155)
        self.assertIsNotNone(self.reaches(fresh, 155))
        (text,) = [sent.text for sent in RecordingTransport.sent[told:]]
        counted = re.match(r'^(\d+) ', text)
        self.assertTrue(counted is None or counted.group(1) == '1', text)

    def test_the_follow_up_time_is_the_critical_rules_and_none_sends_each_at_once(self):
        self.assertEqual(outbox.alarm_rules.current().follow_up('critical'), timedelta(seconds=5))
        for severity, seconds in (('critical', 9), ('warning', 1)):
            with self.subTest(severity=severity), self.assertRaises(DatabaseError), transaction.atomic():
                SeverityPolicy.objects.filter(severity=severity).update(follow_up_seconds=seconds)
        SeverityPolicy.objects.filter(severity='critical').update(follow_up_seconds=0)
        (first,) = self.system(1, 'critical')
        outbox.send_due(self.at(seconds=1))
        (second,) = self.system(1, 'critical', seconds=2)
        outbox.send_due(self.at(seconds=2))
        self.assertEqual([sent.pk for sent in RecordingTransport.sent], [first.pk, second.pk])

    def test_warnings_keep_their_coverage(self):
        self.system(5, 'warning')
        outbox.send_due(self.at(0))
        self.system(2, 'warning', seconds=30)
        found = outbox.send_due(self.at(seconds=30))
        self.assertEqual((found.grouped, found.sent), (2, 0))


# ---- D8c --------------------------------------------------------------------------------------------------------------
@override_settings(ALARM_TRANSPORTS=RECORDING)
class SummariesAfterCriticalsTests(FinalCase):
    def test_a_fresh_open_critical_goes_ahead_of_six_summaries(self):
        days = 24 * 60
        for number in range(6):
            person = get_user_model().objects.create_user(f'person{number}', f'p{number}@example.com', 'x')
            (old,) = self.system(1, 'critical', seconds=-4 * days * 60, parameter=f'old{number}', to=person)
            services.clear(old.alarm, self.at(-3 * days), 'restored')
        (fresh,) = self.system(1, 'critical', parameter='fresh')
        outbox.send_due(self.at(1))
        self.assertEqual(len(RecordingTransport.sent), 7)
        self.assertEqual(RecordingTransport.sent[0].pk, fresh.pk)


# ---- errors while judging --------------------------------------------------------------------------------------------
class JudgingErrorTests(FinalCase):
    @override_settings(ALARM_TRANSPORTS=RECORDING)
    def test_an_error_inside_is_due_follows_the_retry_wait_and_still_raises_the_supervision_alarm(self):  # T3c
        (notification,) = self.system(1, 'critical')
        with mock.patch.object(outbox, 'is_due', side_effect=RuntimeError('the due check broke')), \
                self.assertLogs('alarms.outbox', level='ERROR'):
            self.rounds(0, 300)
            attempts = DeliveryAttempt.objects.filter(notification=notification)
            self.assertLessEqual(attempts.count(), 11)                    # its 30 s retry wait, not one a second
            self.assertGreaterEqual(attempts.count(), 9)
            self.assertIn('the due check broke', attempts.first().detail)
            self.assertEqual([row.pk for row in outbox.stuck(outbox.alarm_rules.current(), self.at(seconds=360))],
                             [notification.pk])
            self.loop(seconds=360)
        found = Alarm.objects.get(source='system', parameter='notifications_undeliverable')
        self.assertEqual(found.severity, 'critical')

    @override_settings(ALARM_TRANSPORTS=RECORDING)
    def test_an_error_while_a_group_is_judged_is_a_failed_attempt_of_its_notifications(self):
        made = self.system(2, 'critical')
        with mock.patch.object(floods, 'plan', side_effect=ValueError('the plan broke')), \
                self.assertLogs('alarms.outbox', level='ERROR'):
            outbox.send_due(self.at(0))
        for row in made:
            attempt = DeliveryAttempt.objects.get(notification=row)
            self.assertEqual(attempt.outcome, 'failed')
            self.assertIn('the plan broke', attempt.detail)
            self.assertTrue(OutboxEntry.objects.filter(notification=row).exists())

    @override_settings(ALARM_TRANSPORTS=RECORDING)
    def test_a_notification_that_went_before_its_group_failed_gets_no_failed_attempt(self):
        went, broke = self.system(2, 'warning')
        real, calls = services.attempt, []

        def attempt(*args, **kwargs):
            calls.append(args[0].pk)
            if len(calls) == 2:
                raise RuntimeError('the write broke')
            return real(*args, **kwargs)
        with mock.patch.object(services, 'attempt', side_effect=attempt), \
                self.assertLogs('alarms.outbox', level='ERROR'):
            outbox.send_due()                                            # each attempt stamped with its own moment
        self.assertEqual(list(DeliveryAttempt.objects.filter(notification=went).values_list('outcome', flat=True)),
                         ['sent'])
        self.assertEqual(list(DeliveryAttempt.objects.filter(notification=broke).values_list('outcome', flat=True)),
                         ['failed'])
        self.assertTrue(timedelta(0) <= DeliveryAttempt.objects.get(notification=went).attempted_at - self.now
                        < timedelta(minutes=5))

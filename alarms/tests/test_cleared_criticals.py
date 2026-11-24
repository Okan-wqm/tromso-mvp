"""A critical alarm that opened and cleared before its first delivery attempt is still delivered, never dropped (the
coordinator's decision of 2026-11-24): on a fish farm a critical that came and went while the transport was down (an
oxygen crash, a power cut) is exactly what the people on call must hear afterwards. It goes out as one message saying it
was critical and has cleared, when it opened and when it cleared, in the person's language, through the same outbox,
grouping and flood rules as any notification. A warning (or another notification) that cleared before its first attempt
is still given up, its attempt saying why, after the due criticals and in bounded chunks, so 20,000 of them never delay a critical;
a flood of cleared criticals says so."""
import sys
import time

from django.db import connection
from django.test import override_settings

from core.models import Profile
from core.templatetags.dates import on, zone_for

from .. import outbox, read, services
from ..models import DeliveryAttempt, OutboxEntry
from .doubles import RecordingTransport
from .test_review_fixes import Case

RECORDING = {'push': 'alarms.tests.doubles.RecordingTransport'}


class ClearedCriticalTests(Case):
    def test_a_critical_that_came_and_went_while_the_transport_was_down_is_sent_once_saying_so(self):
        (notification,) = self.system(1, 'critical')
        services.clear(notification.alarm, self.at(1), 'restored')
        down = outbox.send_due(self.at(2))                        # no transport connected
        self.assertEqual((down.given_up, down.waiting), (0, 1))
        self.assertTrue(OutboxEntry.objects.filter(notification=notification).exists())
        with override_settings(ALARM_TRANSPORTS=RECORDING):
            found = outbox.send_due(self.at(3))
            self.assertEqual(outbox.send_due(self.at(4)).sent, 0)
        self.assertEqual(found.sent, 1)
        (sent,) = RecordingTransport.sent
        self.assertEqual(sent.pk, notification.pk)
        self.assertIn('Critical, now cleared', sent.text)
        clock = (lambda at: on(at, zone_for(self.bergen)).strftime('%d.%m.%Y %H:%M'))
        self.assertIn(f'Opened {clock(self.now)}, cleared {clock(self.at(1))}', sent.text)
        self.assertEqual(read.status(notification), 'sent')

    def test_it_is_said_in_the_persons_language(self):
        Profile.objects.update_or_create(user=self.operator, defaults={'language': 'nb'})
        (notification,) = self.system(1, 'critical')
        services.clear(notification.alarm, self.at(1), 'restored')
        with override_settings(ALARM_TRANSPORTS=RECORDING):
            outbox.send_due(self.at(2))
        (sent,) = RecordingTransport.sent
        self.assertNotIn('Critical, now cleared', sent.text)
        self.assertIn('avsluttet', sent.text)

    def test_cleared_criticals_of_one_kind_go_out_as_one_flood_message(self):
        made = self.system(4, 'critical')
        for row in made:
            services.clear(row.alarm, self.at(1), 'restored')
        with override_settings(ALARM_TRANSPORTS=RECORDING):
            found = outbox.send_due(self.at(2))
        self.assertEqual((found.floods, found.sent, len(RecordingTransport.sent)), (1, 4, 1))

    def test_a_warning_that_came_and_went_is_given_up_and_said(self):
        (notification,) = self.system(1, 'warning')
        services.clear(notification.alarm, self.at(1), 'restored')
        found = outbox.send_due(self.at(2))
        self.assertEqual(found.given_up, 1)
        self.assertIn('cleared before the first attempt', DeliveryAttempt.objects.get(notification=notification).detail)
        self.assertEqual(read.status(notification), 'failed')


@override_settings(ALARM_TRANSPORTS=RECORDING)
class FloodTextTests(Case):
    def test_a_flood_of_cleared_criticals_says_so_with_the_count_and_the_first_and_last_times(self):
        made = self.system(4, 'critical')
        for minute, row in enumerate(made, start=1):
            services.clear(row.alarm, self.at(minute), 'restored')
        outbox.send_due(self.at(10))
        ((first, flood),) = RecordingTransport.floods
        clock = (lambda at: on(at, zone_for(self.bergen)).strftime('%d.%m.%Y %H:%M'))
        self.assertIn('4 critical alarms, all now cleared', first.text)
        self.assertIn(f'first opened {clock(self.now)}, last cleared {clock(self.at(4))}', first.text)

    def test_it_is_said_in_the_persons_language(self):
        Profile.objects.update_or_create(user=self.operator, defaults={'language': 'tr'})
        for row in self.system(3, 'critical'):
            services.clear(row.alarm, self.at(1), 'restored')
        outbox.send_due(self.at(2))
        ((first, _flood),) = RecordingTransport.floods
        self.assertNotIn('all now cleared', first.text)
        self.assertIn('kapandı', first.text)


class BoundedGiveUpTests(Case):
    """Giving up a large backlog of cleared warnings never delays a critical: due criticals go first, the give-up comes
    after them in bounded chunks, each its own transaction, what a round leaves the next one takes."""

    def fill(self, count):
        with connection.cursor() as cursor:
            cursor.execute("INSERT INTO alarms (source, parameter, severity, opened_at, summary) SELECT 'system', 'many', "
                           "'warning', %s, 'many ' || n FROM generate_series(1, %s) n", [self.now, count])
            cursor.execute("INSERT INTO alarm_clearances (alarm_id, cleared_at, cause) SELECT id, %s, 'restored' FROM "
                           "alarms WHERE parameter = 'many'", [self.at(1)])
            cursor.execute('INSERT INTO alarm_notifications (alarm_id, recipient_id, channel, level, queued_at, kind) '
                           "SELECT id, %s, 'push', 0, opened_at, 'alarm' FROM alarms WHERE parameter = 'many'",
                           [self.operator.pk])
            cursor.execute("INSERT INTO alarm_outbox (notification_id) SELECT n.id FROM alarm_notifications n JOIN alarms "
                           "a ON a.id = n.alarm_id WHERE a.parameter = 'many'")
            cursor.execute('ANALYZE alarms; ANALYZE alarm_clearances; ANALYZE alarm_notifications; ANALYZE alarm_outbox')

    @override_settings(ALARM_TRANSPORTS=RECORDING)
    def test_a_critical_queued_with_twenty_thousand_cleared_warnings_goes_out_in_the_first_round(self):
        self.fill(20_000)
        (critical,) = self.system(1, 'critical', parameter='urgent')
        started = time.monotonic()
        found = outbox.send_due(self.at(2))
        took = time.monotonic() - started
        sys.stderr.write(f'\n[alarm outbox] a critical beside 20,000 cleared warnings: out in the first round, '
                         f'{took * 1000:.0f} ms\n')
        self.assertEqual([sent.pk for sent in RecordingTransport.sent], [critical.pk])
        self.assertEqual(found.sent, 1)
        self.assertLess(found.given_up, 20_000)
        self.assertLess(took, 1.0)

    def test_the_backlog_drains_over_rounds_each_bounded(self):
        self.fill(20_000)
        rounds, longest = 0, 0.0
        while OutboxEntry.objects.exists():
            rounds += 1
            started = time.monotonic()
            outbox.send_due(self.at(2, seconds=rounds))
            longest = max(longest, time.monotonic() - started)
            self.assertLess(rounds, 100)
        sys.stderr.write(f'\n[alarm outbox] 20,000 cleared warnings given up over {rounds} rounds, the longest '
                         f'{longest * 1000:.0f} ms\n')
        self.assertGreater(rounds, 1)
        self.assertLess(longest, 1.0)
        self.assertEqual(DeliveryAttempt.objects.filter(detail__contains='cleared before the first attempt').count(),
                         20_000)

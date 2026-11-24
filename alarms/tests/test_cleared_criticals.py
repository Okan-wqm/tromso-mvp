"""A critical alarm that opened and cleared before its first delivery attempt is still delivered, never dropped (the
coordinator's decision of 2026-11-24): on a fish farm a critical that came and went while the transport was down (an
oxygen crash, a power cut) is exactly what the people on call must hear afterwards. It goes out as one message saying it
was critical and has cleared, when it opened and when it cleared, in the person's language, through the same outbox,
grouping and flood rules as any notification. A warning (or another notification) that cleared before its first attempt
is still given up, its attempt saying why; 20,000 of them cost a round little."""
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


class ClearedLoadTests(Case):
    def test_twenty_thousand_cleared_warnings_cost_a_round_little(self):
        with connection.cursor() as cursor:
            cursor.execute("INSERT INTO alarms (source, parameter, severity, opened_at, summary) SELECT 'system', 'many', "
                           "'warning', %s, 'many ' || n FROM generate_series(1, 20000) n", [self.now])
            cursor.execute("INSERT INTO alarm_clearances (alarm_id, cleared_at, cause) SELECT id, %s, 'restored' FROM "
                           "alarms WHERE parameter = 'many'", [self.at(1)])
            cursor.execute('INSERT INTO alarm_notifications (alarm_id, recipient_id, channel, level, queued_at, kind) '
                           "SELECT id, %s, 'push', 0, opened_at, 'alarm' FROM alarms WHERE parameter = 'many'",
                           [self.operator.pk])
            cursor.execute("INSERT INTO alarm_outbox (notification_id) SELECT n.id FROM alarm_notifications n JOIN alarms "
                           "a ON a.id = n.alarm_id WHERE a.parameter = 'many'")
            cursor.execute('ANALYZE alarms; ANALYZE alarm_clearances; ANALYZE alarm_notifications; ANALYZE alarm_outbox')
        started = time.monotonic()
        found = outbox.send_due(self.at(2))
        took = time.monotonic() - started
        started = time.monotonic()
        again = outbox.send_due(self.at(3))
        next_took = time.monotonic() - started
        sys.stderr.write(f'\n[alarm outbox] 20,000 cleared warnings: the round that gives them up {took * 1000:.0f} ms, '
                         f'the next round {next_took * 1000:.0f} ms\n')
        self.assertEqual((found.given_up, again.backlog), (20_000, 0))
        self.assertEqual(OutboxEntry.objects.count(), 0)
        self.assertLess(took, 10)
        self.assertLess(next_took, 0.5)

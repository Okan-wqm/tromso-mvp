"""The alarms (F-091, owner answer 2026-11-06): what holds an alarm (the water limits, the sensor rules), who is notified
(the recipient rules), the outbox per recipient and channel, the escalation when nobody acknowledges, the delivery through
a pluggable transport (none is connected: nothing is sent), and the acknowledgement. Every row is append-only and every
step is in the activity log."""
from datetime import timedelta
from unittest import mock

from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.test import override_settings
from django.utils import timezone

from core.models import AuditLog
from farm.tests.helpers import may_record
from sensors import alarms as sensor_alarms
from sensors.models import AlarmEvent, AlarmRule
from sensors.tests import make_channel, make_connection, make_device, make_format

from .. import read, routing, services
from ..models import (APPEND_ONLY, Acknowledgement, Alarm, AlarmClearance, DeliveryAttempt, Escalation, Notification,
                      RecipientRule, SeverityPolicy)
from . import AlarmsCase
from .doubles import FailingTransport, RecordingTransport

PUSH_DOUBLE = {'push': 'alarms.tests.doubles.RecordingTransport'}
PUSH_FAILING = {'push': 'alarms.tests.doubles.FailingTransport'}


class TableTests(AlarmsCase):
    def test_every_alarm_row_is_append_only(self):
        self.rule()
        self.sample(5.5)
        self.loop()
        alarm = self.critical()
        services.acknowledge(alarm, self.operator, device='phone-1', app='Suderra 1.0', at=self.now)
        for table in ('alarms', 'alarm_notifications', 'alarm_acknowledgements'):   # the database itself, past PROTECT
            with self.subTest(table=table), connection.cursor() as cursor:
                with self.assertRaisesMessage(DatabaseError, 'append-only'), transaction.atomic():
                    cursor.execute(f'UPDATE {table} SET id = id')
                with self.assertRaisesMessage(DatabaseError, 'append-only'), transaction.atomic():
                    cursor.execute(f'DELETE FROM {table}')
        with connection.cursor() as cursor:                                  # and the same trigger on all six
            cursor.execute("SELECT tgrelid::regclass::text FROM pg_trigger WHERE tgname LIKE 'trg_%%_append_only' "
                           "AND tgrelid::regclass::text = ANY(%s)", [list(APPEND_ONLY)])
            self.assertEqual(sorted(row[0] for row in cursor.fetchall()), sorted(APPEND_ONLY))

    def test_a_rule_names_a_role_or_a_person_never_both_and_its_department_is_on_its_site(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            RecipientRule.objects.create(site=self.bergen, level=0, min_severity='warning', channel='push')
        with self.assertRaises(IntegrityError), transaction.atomic():
            RecipientRule.objects.create(site=self.bergen, level=0, min_severity='warning', channel='push',
                                         role=self.operators, user=self.manager)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.rule(channel='email')
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.rule(level=10)
        with self.assertRaisesMessage(ValidationError, 'not on the site'):
            RecipientRule(site=self.oslo, production_department=self.hall, level=0, min_severity='warning',
                          channel='push', role=self.operators).full_clean()


class WaterTests(AlarmsCase):
    def test_a_value_past_the_critical_limit_holds_one_alarm_where_it_is(self):
        self.sample(5.5)
        self.loop()
        self.loop(minutes=1)
        alarm = self.critical()
        self.assertEqual((alarm.source, alarm.point, alarm.parameter, alarm.severity, alarm.site, alarm.production_department),
                         ('water_limit', self.mid1, 'ph', 'critical', self.bergen, self.hall))
        self.assertIn('T-01', alarm.summary)
        self.assertIn('5.50', alarm.summary)
        self.assertTrue(read.is_open(alarm))
        entry = AuditLog.objects.get(entity_type='alarm', action='create', entity_id=str(alarm.pk))
        self.assertEqual(entry.severity, AuditLog.Severity.CRITICAL)

    def test_a_fresh_value_back_inside_the_limits_clears_it(self):
        self.sample(5.5, hours=2)
        self.loop()
        self.sample(7.2)
        self.loop(minutes=1)                                  # back inside: the clear waits for the off-delay
        self.loop(minutes=2)
        alarm = self.critical()
        self.assertFalse(read.is_open(alarm))
        self.assertEqual(AlarmClearance.objects.get(alarm=alarm).cause, 'returned')
        self.assertTrue(AuditLog.objects.filter(entity_type='alarm', action='update').exists())
        self.loop(minutes=3)
        self.assertEqual(Alarm.objects.filter(severity='critical').count(), 1)

    def test_a_value_that_goes_stale_never_clears_it(self):
        self.sample(5.5)
        self.loop()
        self.loop(minutes=60 * 80)                  # pH is fresh for 72 hours: the value is stale now
        self.assertTrue(read.is_open(self.critical()))

    def test_a_warning_that_turns_critical_stays_open_beside_the_critical_alarm(self):
        self.sample(6.2, hours=2)
        self.loop()
        warning = Alarm.objects.get()
        self.assertEqual(warning.severity, 'warning')
        self.sample(5.5)
        self.loop(minutes=1)
        self.assertTrue(read.is_open(warning))                  # never cleared and reopened (alarm plan, defect 2)
        self.assertEqual((self.critical().severity, read.is_open(self.critical())), ('critical', True))

    def test_values_inside_the_limits_and_parameters_without_one_hold_nothing(self):
        self.sample(7.0)
        self.loop()
        self.assertFalse(Alarm.objects.exists())


class SensorTests(AlarmsCase):
    def setUp(self):
        super().setUp()
        device = make_device(make_connection(), make_format(), self.bergen)
        self.flow = make_channel(device, 'flow_m3_h')
        self.sensor_rule = AlarmRule.objects.create(kind='low', severity='warning', channel=self.flow, threshold=10)

    def test_a_sensor_rules_event_is_mirrored_and_cleared_with_it(self):
        self.sample(7.2)                        # T-01's water fine, its oxygen fresh: the sensor rule's is the one alarm
        event = AlarmEvent.objects.create(rule=self.sensor_rule, channel_no=self.flow.channel_no,
                                          opened_at=self.now, peak=4)
        with mock.patch.object(sensor_alarms, 'evaluate', return_value=(0, 0)):
            self.loop()
            alarm = Alarm.objects.get()
            self.assertEqual((alarm.source, alarm.sensor_event, alarm.severity, alarm.site, alarm.opened_at),
                             ('sensor_rule', event, 'warning', self.bergen, self.now))
            AlarmEvent.objects.filter(pk=event.pk).update(closed_at=self.now + timedelta(minutes=3))
            self.loop(minutes=4)
        self.assertEqual(AlarmClearance.objects.get().cleared_at, self.now + timedelta(minutes=3))
        self.assertEqual(Alarm.objects.count(), 1)

    def test_the_loop_checks_the_sensor_rules_itself(self):
        with mock.patch.object(sensor_alarms, 'evaluate', return_value=(0, 0)) as evaluate:
            self.loop()
        evaluate.assert_called_once()
        self.assertEqual(evaluate.call_args.args[0], self.now)          # (and the pass's OxygenPass)


class RoutingTests(AlarmsCase):
    def open_alarm(self, ph=5.5):
        self.sample(ph)
        self.loop()
        # the water's alarm (a critical told to nobody also raises the alarm system's own: alarms_unreached)
        return Alarm.objects.get(source='water_limit', severity='critical' if ph < 6 else 'warning')

    def test_a_rule_reaches_the_active_members_of_its_role_on_its_site(self):
        self.rule()
        self.rule(site=self.oslo, user=self.manager)                         # another site
        inactive = type(self.operator).objects.create_user('gone', 'gone@example.com', 'x', is_active=False)
        inactive.groups.add(self.operators)
        alarm = self.open_alarm()
        self.assertEqual([user for user, _rule in routing.recipients(alarm, 0, self.now)], [self.operator])

    def test_a_department_rule_and_a_rule_for_every_site(self):
        self.rule(site=None, production_department=None, user=self.manager)
        alarm = self.open_alarm()
        self.assertEqual({user for user, _rule in routing.recipients(alarm, 0, self.now)}, {self.manager})
        other = type(self.hall).objects.create(site=self.bergen, name='Hall B', code='HB')
        self.rule(production_department=other, user=self.operator)
        self.assertEqual({user for user, _rule in routing.recipients(alarm, 0, self.now)}, {self.manager})

    def test_a_critical_only_rule_skips_a_warning(self):
        self.rule(min_severity='critical')
        alarm = self.open_alarm(ph=6.2)
        self.assertEqual(routing.recipients(alarm, 0, self.now), [])

    def test_an_on_shift_rule_reaches_only_the_people_on_shift_now(self):
        self.rule(on_shift_only=True)
        alarm = self.open_alarm()
        with mock.patch('hr.read.on_shift', return_value=set()):
            self.assertEqual(routing.recipients(alarm, 0, self.now), [])
        with mock.patch('hr.read.on_shift', return_value={self.operator.pk}) as on_shift:
            self.assertEqual([user for user, _rule in routing.recipients(alarm, 0, self.now)], [self.operator])
        on_shift.assert_called_once_with(self.now)

    def test_a_deleted_or_inactive_rule_reaches_nobody(self):
        self.rule(is_active=False)
        self.rule(user=self.manager).soft_delete(None)
        self.assertEqual(routing.recipients(self.open_alarm(), 0, self.now), [])


class OutboxTests(AlarmsCase):
    def test_an_alarm_queues_one_push_per_recipient_and_logs_it(self):
        self.rule()
        self.rule(user=self.operator)                                         # the same person twice: one notification
        self.sample(5.5)
        self.loop()
        notification = Notification.objects.get()
        self.assertEqual((notification.recipient, notification.channel, notification.level), (self.operator, 'push', 0))
        self.assertEqual(read.status(notification), 'queued')
        self.assertTrue(AuditLog.objects.filter(entity_type='alarm notification', action='create').exists())
        self.loop(minutes=1)
        self.assertEqual(Notification.objects.count(), 1)

    def test_a_rule_added_later_still_reaches_an_open_alarm_never_a_cleared_one(self):
        self.sample(5.5, hours=2)
        self.loop()
        self.rule()
        self.loop(minutes=1)
        self.assertEqual(Notification.objects.count(), 1)
        self.sample(7.0)
        self.loop(minutes=2)
        self.loop(minutes=3)                                       # cleared after the off-delay
        self.rule(user=self.manager, level=0)
        self.loop(minutes=4)
        self.assertEqual(Notification.objects.count(), 1)

    def test_nothing_is_sent_without_a_transport(self):
        self.rule()
        self.sample(5.5)
        self.loop()
        self.assertFalse(DeliveryAttempt.objects.exists())
        self.assertFalse(read.transport_connected('push'))

    @override_settings(ALARM_TRANSPORTS=PUSH_DOUBLE)
    def test_a_transport_sends_each_notification_once(self):
        RecordingTransport.sent.clear()
        self.rule()
        self.sample(5.5)
        self.loop()
        self.loop(minutes=1)
        attempt = DeliveryAttempt.objects.get()
        self.assertEqual((attempt.outcome, attempt.notification.recipient), ('sent', self.operator))
        self.assertEqual(read.status(attempt.notification), 'sent')
        self.assertEqual([notification.pk for notification in RecordingTransport.sent], [attempt.notification.pk])
        self.assertTrue(read.transport_connected('push'))

    @override_settings(ALARM_TRANSPORTS=PUSH_FAILING)
    def test_a_failing_transport_is_tried_again_up_to_the_severitys_attempts(self):
        SeverityPolicy.objects.filter(severity='warning').update(delivery_attempts=3)
        self.rule()
        self.sample(6.2)                                       # a warning (a critical is tried until it is answered)
        for minute in range(8):
            self.loop(minutes=minute)
        self.assertEqual(DeliveryAttempt.objects.filter(outcome='failed').count(), 3)
        self.assertEqual(read.status(Notification.objects.get()), 'failed')
        self.assertEqual(DeliveryAttempt.objects.first().detail, FailingTransport.reason)


class EscalationTests(AlarmsCase):
    def setUp(self):
        super().setUp()
        SeverityPolicy.objects.filter(severity='critical').update(escalation_minutes=10)
        self.rule()
        self.rule(level=1, user=self.manager)
        self.sample(5.5)
        self.loop()
        self.alarm = self.critical()

    def test_an_unacknowledged_alarm_goes_to_the_next_level_after_the_owners_minutes(self):
        self.loop(minutes=9)
        self.assertFalse(Escalation.objects.exists())
        self.loop(minutes=10)
        escalation = Escalation.objects.get()
        self.assertEqual((escalation.level, escalation.escalated_at), (1, self.now + timedelta(minutes=10)))
        self.assertEqual(Notification.objects.get(level=1).recipient, self.manager)
        self.assertEqual(read.level(self.alarm), 1)
        self.assertTrue(AuditLog.objects.filter(entity_type='alarm escalation').exists())
        self.loop(minutes=30)                                            # no level 2: it stays at 1
        self.assertEqual(Escalation.objects.count(), 1)

    def test_an_acknowledgement_stops_it(self):
        services.acknowledge(self.alarm, self.operator, at=self.now + timedelta(minutes=5))
        self.loop(minutes=20)
        self.assertFalse(Escalation.objects.exists())

    def test_a_cleared_alarm_is_not_escalated(self):
        self.sample(7.0, hours=0.5)
        self.loop(minutes=1)
        self.loop(minutes=20)
        self.assertFalse(Escalation.objects.exists())

    def test_a_level_with_nobody_to_notify_goes_on_at_once(self):
        RecipientRule.objects.filter(level=0).update(is_active=False)
        self.sample(7.0, hours=0.5)
        self.loop(minutes=1)
        self.loop(minutes=2)                                             # the first alarm cleared (off-delay)
        self.sample(5.5, hours=0.25)
        self.loop(minutes=3)
        second = Alarm.objects.filter(severity='critical').exclude(pk=self.alarm.pk).get()
        self.assertEqual(read.level(second), 1)
        self.assertEqual(Notification.objects.get(alarm=second).recipient, self.manager)

    def test_an_alarm_nobody_can_be_notified_of_is_said(self):
        RecipientRule.objects.update(is_active=False)
        self.sample(7.0, hours=0.5)
        self.loop(minutes=1)
        self.loop(minutes=2)
        self.sample(5.5, hours=0.25)
        self.loop(minutes=3)
        second = Alarm.objects.filter(severity='critical').exclude(pk=self.alarm.pk).get()
        self.assertTrue(read.nobody_notified(second))
        self.assertFalse(read.nobody_notified(self.alarm))


class AcknowledgementTests(AlarmsCase):
    def setUp(self):
        super().setUp()
        self.rule()
        self.sample(5.5)
        self.loop()
        self.alarm = self.critical()

    def test_who_when_from_which_device_and_app_and_how_late(self):
        notification = Notification.objects.get()
        ack = services.acknowledge(self.alarm, self.operator, at=self.alarm.opened_at + timedelta(minutes=4),
                                   device='phone-7', app='Suderra Alarms 1.0', notification=notification)
        self.assertEqual((ack.user, ack.device, ack.app, ack.notification, ack.delay),
                         (self.operator, 'phone-7', 'Suderra Alarms 1.0', notification, timedelta(minutes=4)))
        self.assertTrue(read.acknowledged(self.alarm))
        entry = AuditLog.objects.get(entity_type='alarm acknowledgement')
        self.assertEqual(entry.user, self.operator)

    def test_once_per_person(self):
        may_record(self.manager, 'change_alarm')         # Alarms: Edit: the service asks who may (L-5)
        services.acknowledge(self.alarm, self.operator)
        with self.assertRaisesMessage(ValidationError, 'already acknowledged'):
            services.acknowledge(self.alarm, self.operator)
        services.acknowledge(self.alarm, self.manager)
        self.assertEqual(Acknowledgement.objects.count(), 2)

    def test_a_notification_answered_is_the_persons_own(self):
        may_record(self.manager, 'change_alarm')         # may acknowledge, but not with another person's notification
        with self.assertRaisesMessage(ValidationError, 'not yours'):
            services.acknowledge(self.alarm, self.manager, notification=Notification.objects.get())

    def test_who_may_acknowledge(self):
        self.assertTrue(read.may_acknowledge(self.operator, self.alarm))          # notified of it
        self.assertFalse(read.may_acknowledge(self.manager, self.alarm))
        self.manager.groups.add(type(self.operators).objects.create(name='Alarm desk'))
        from django.contrib.auth.models import Permission
        self.manager.groups.get(name='Alarm desk').permissions.add(Permission.objects.get(codename='change_alarm'))
        manager = type(self.manager).objects.get(pk=self.manager.pk)
        self.assertTrue(read.may_acknowledge(manager, self.alarm))


class CommandTests(AlarmsCase):
    def test_run_alarms_runs_one_pass(self):
        from io import StringIO
        from django.core.management import call_command
        self.rule()
        self.sample(5.5)
        out = StringIO()
        with mock.patch.object(timezone, 'now', return_value=self.now):
            call_command('run_alarms', stdout=out)
        self.assertIn('2 opened', out.getvalue())                    # the critical level and the warning level
        self.assertIn('1 queued', out.getvalue())
        self.assertIn('nothing sent: no transport', out.getvalue())

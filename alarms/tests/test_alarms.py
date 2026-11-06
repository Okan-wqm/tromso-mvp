"""The alarms (F-091, owner answer 2026-11-06): what holds an alarm (the water limits, the sensor rules), who is notified
(the recipient rules), the outbox per recipient and channel, the escalation when nobody acknowledges, the delivery through
a pluggable transport (none is connected: nothing is sent), and the acknowledgement. Every row is append-only and every
step is in the activity log."""
from datetime import timedelta
from unittest import mock

from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, transaction
from django.test import override_settings
from django.utils import timezone

from core.models import AuditLog, PlatformSettings
from sensors import alarms as sensor_alarms
from sensors.models import AlarmEvent, AlarmRule
from sensors.tests import make_channel, make_connection, make_device, make_format

from .. import engine, read, routing, services
from ..models import (Acknowledgement, Alarm, AlarmClearance, DeliveryAttempt, Escalation, Notification,
                      RecipientRule)
from ..transports import MAX_ATTEMPTS
from . import AlarmsCase
from .doubles import FailingTransport, RecordingTransport

PUSH_DOUBLE = {'push': 'alarms.tests.doubles.RecordingTransport'}
PUSH_FAILING = {'push': 'alarms.tests.doubles.FailingTransport'}


class TableTests(AlarmsCase):
    def test_every_alarm_row_is_append_only(self):
        self.rule()
        self.sample(5.5)
        self.loop()
        alarm = Alarm.objects.get()
        services.acknowledge(alarm, self.operator, device='phone-1', app='Suderra 1.0', at=self.now)
        for model in (Alarm, Notification, Acknowledgement):
            with self.subTest(model=model.__name__):
                with self.assertRaisesMessage(DatabaseError, 'append-only'), transaction.atomic():
                    model.objects.update(id=model.objects.first().id)
                with self.assertRaisesMessage(DatabaseError, 'append-only'), transaction.atomic():
                    model.objects.all().delete()

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
        alarm = Alarm.objects.get()
        self.assertEqual((alarm.source, alarm.point, alarm.parameter, alarm.severity, alarm.site, alarm.production_department),
                         ('water_limit', self.mid1, 'ph', 'critical', self.bergen, self.hall))
        self.assertIn('T-01', alarm.summary)
        self.assertIn('5.50', alarm.summary)
        self.assertTrue(read.is_open(alarm))
        entry = AuditLog.objects.get(entity_type='alarm', action='create')
        self.assertEqual(entry.severity, AuditLog.Severity.CRITICAL)

    def test_a_fresh_value_back_inside_the_limits_clears_it(self):
        self.sample(5.5, hours=2)
        self.loop()
        self.sample(7.2)
        self.loop(minutes=1)
        alarm = Alarm.objects.get()
        self.assertFalse(read.is_open(alarm))
        self.assertEqual(AlarmClearance.objects.get().alarm, alarm)
        self.assertTrue(AuditLog.objects.filter(entity_type='alarm', action='update').exists())
        self.loop(minutes=2)
        self.assertEqual(Alarm.objects.count(), 1)

    def test_a_value_that_goes_stale_never_clears_it(self):
        self.sample(5.5)
        self.loop()
        self.loop(minutes=60 * 80)                  # pH is fresh for 72 hours: the value is stale now
        self.assertTrue(read.is_open(Alarm.objects.get()))

    def test_a_warning_that_turns_critical_is_cleared_and_a_critical_alarm_opens(self):
        self.sample(6.2, hours=2)
        self.loop()
        warning = Alarm.objects.get()
        self.assertEqual(warning.severity, 'warning')
        self.sample(5.5)
        self.loop(minutes=1)
        self.assertFalse(read.is_open(warning))
        critical = Alarm.objects.exclude(pk=warning.pk).get()
        self.assertEqual((critical.severity, read.is_open(critical)), ('critical', True))

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
        evaluate.assert_called_once_with(self.now)


class RoutingTests(AlarmsCase):
    def open_alarm(self, ph=5.5):
        self.sample(ph)
        self.loop()
        return Alarm.objects.get()

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
        self.rule(user=self.manager, level=0)
        self.loop(minutes=3)
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
    def test_a_failing_transport_is_tried_again_up_to_the_cap(self):
        self.rule()
        self.sample(5.5)
        for minute in range(MAX_ATTEMPTS + 3):
            self.loop(minutes=minute)
        self.assertEqual(DeliveryAttempt.objects.filter(outcome='failed').count(), MAX_ATTEMPTS)
        self.assertEqual(read.status(Notification.objects.get()), 'failed')
        self.assertEqual(DeliveryAttempt.objects.first().detail, FailingTransport.reason)


class EscalationTests(AlarmsCase):
    def setUp(self):
        super().setUp()
        PlatformSettings.objects.update(alarm_escalation_minutes=10)
        self.rule()
        self.rule(level=1, user=self.manager)
        self.sample(5.5)
        self.loop()
        self.alarm = Alarm.objects.get()

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
        self.loop(minutes=1)                                             # the first alarm cleared
        self.sample(5.5, hours=0.25)
        self.loop(minutes=2)
        second = Alarm.objects.exclude(pk=self.alarm.pk).get()
        self.assertEqual(read.level(second), 1)
        self.assertEqual(Notification.objects.get(alarm=second).recipient, self.manager)

    def test_an_alarm_nobody_can_be_notified_of_is_said(self):
        RecipientRule.objects.update(is_active=False)
        self.sample(7.0, hours=0.5)
        self.loop(minutes=1)
        self.sample(5.5, hours=0.25)
        self.loop(minutes=2)
        second = Alarm.objects.exclude(pk=self.alarm.pk).get()
        self.assertTrue(read.nobody_notified(second))
        self.assertFalse(read.nobody_notified(self.alarm))


class AcknowledgementTests(AlarmsCase):
    def setUp(self):
        super().setUp()
        self.rule()
        self.sample(5.5)
        self.loop()
        self.alarm = Alarm.objects.get()

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
        services.acknowledge(self.alarm, self.operator)
        with self.assertRaisesMessage(ValidationError, 'already acknowledged'):
            services.acknowledge(self.alarm, self.operator)
        services.acknowledge(self.alarm, self.manager)
        self.assertEqual(Acknowledgement.objects.count(), 2)

    def test_a_notification_answered_is_the_persons_own(self):
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
        self.assertIn('1 opened', out.getvalue())
        self.assertIn('1 queued', out.getvalue())
        self.assertIn('nothing sent: no transport', out.getvalue())

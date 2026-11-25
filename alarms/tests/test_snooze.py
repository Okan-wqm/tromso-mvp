"""Snoozing an alarm (ISA-18.2 shelving; owner decision Q5 of 2026-11-08: a right of its own, a reason, at most 4 h for a
critical alarm and 12 h for a warning by default, events always recorded). While a snooze is in force the alarm is still
raised, kept and shown; nobody is notified of it, what was queued for it waits, and it is not escalated. Once it ends
(it runs out, even while the worker was down, or someone ends it early) notification and escalation go on, the
escalation time counted again from the end. Written once, logged, never changed."""
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import DatabaseError, connection, transaction
from django.test import override_settings
from django.urls import reverse

from core import access, navigation
from core.models import AuditLog
from farm.tests.helpers import role

from .. import outbox, read, services
from ..models import Alarm, AlarmShelve, AlarmShelveEnd, Escalation, Notification, RecipientRule, SeverityPolicy
from . import AlarmsCase
from .doubles import RecordingTransport
from farm.tests.helpers import may_record

SNOOZER = ('view_alarm', 'view_alarmshelve', 'add_alarmshelve')


class SnoozeCase(AlarmsCase):
    def setUp(self):
        super().setUp()
        SeverityPolicy.objects.filter(severity='critical').update(escalation_minutes=10)
        self.rule()
        self.rule(level=1, user=self.manager)
        self.sample(5.5)
        self.loop()
        self.alarm = self.critical()
        self.snoozer = may_record(get_user_model().objects.create_user('snoozer', 'snoozer@example.com', 'x', first_name='Siri'),
                                  'add_alarmshelve')
        self.snoozer.groups.add(role('Alarm snoozer', *SNOOZER))

    def at(self, minutes):
        return self.now + timedelta(minutes=minutes)

    def snooze(self, minutes=60, reason='Probe being cleaned', at=1, alarm=None):
        return services.shelve(alarm or self.alarm, self.snoozer, minutes, reason, at=self.at(at))


class RuleTests(SnoozeCase):
    def test_the_longest_snoozes_are_seeded_per_severity(self):
        self.assertEqual(dict(SeverityPolicy.objects.values_list('severity', 'shelve_max_minutes')),
                         {'critical': 240, 'warning': 720})

    def test_a_snooze_needs_a_reason_and_at_most_its_severitys_longest(self):
        warning = Alarm.objects.get(severity='warning', source='water_limit')
        for minutes, reason, said in ((60, '  ', 'Say why'), (241, 'x', '1 to 240 minutes'), (0, 'x', '1 to 240'),
                                      (None, 'x', '1 to 240'), ('30', 'x', '1 to 240')):
            with self.subTest(minutes=minutes, reason=reason), self.assertRaisesMessage(ValidationError, said):
                self.snooze(minutes, reason)
        self.assertEqual(self.snooze(720, 'Calibration', alarm=warning).until - self.at(1), timedelta(minutes=720))
        with self.assertRaisesMessage(ValidationError, '1 to 720'):
            self.snooze(721, 'x', at=800, alarm=warning)
        self.assertEqual(self.snooze(240).until, self.at(241))

    def test_one_at_a_time_and_only_an_open_alarm(self):
        self.snooze(60)
        with self.assertRaisesMessage(ValidationError, 'snoozed already'):
            self.snooze(30, at=10)
        self.snooze(30, at=61)                                         # once it has run out, again
        self.sample(7.0, hours=0.5)
        self.loop(minutes=200)
        self.loop(minutes=202)
        self.assertFalse(read.is_open(self.alarm))
        with self.assertRaisesMessage(ValidationError, 'has cleared'):
            self.snooze(30, at=203)

    def test_the_longest_is_the_users_row(self):
        SeverityPolicy.objects.filter(severity='critical').update(shelve_max_minutes=15)
        with self.assertRaisesMessage(ValidationError, '1 to 15 minutes'):
            self.snooze(16)
        with self.assertRaises(DatabaseError), transaction.atomic():
            SeverityPolicy.objects.filter(severity='critical').update(shelve_max_minutes=481)

    def test_it_is_logged_critical_and_never_changed(self):
        row = self.snooze()
        entry = AuditLog.objects.get(entity_type='alarm snooze')
        self.assertEqual((entry.user, entry.severity, entry.changes['Why']),
                         (self.snoozer, 'critical', [None, 'Probe being cleaned']))
        services.unshelve(self.alarm, self.snoozer, at=self.at(5))
        self.assertEqual(AlarmShelveEnd.objects.get().shelve, row)
        for table in ('alarm_shelves', 'alarm_shelve_ends'):
            with self.subTest(table=table), connection.cursor() as cursor:
                with self.assertRaisesMessage(DatabaseError, 'append-only'), transaction.atomic():
                    cursor.execute(f'DELETE FROM {table}')


class BehaviourTests(SnoozeCase):
    def test_while_snoozed_it_is_kept_but_neither_notified_nor_escalated_and_after_it_goes_on(self):
        third = get_user_model().objects.create_user('third', 'third@example.com', 'x')
        self.snooze(60)
        self.loop(minutes=20)                                          # past the 10 min escalation
        RecipientRule.objects.create(site=self.bergen, min_severity='warning', level=0, channel='push', user=third)
        self.loop(minutes=59)
        self.assertFalse(Escalation.objects.exists())
        self.assertFalse(Notification.objects.filter(recipient=third).exists())
        self.assertTrue(read.is_open(self.alarm))
        self.loop(minutes=61)                                          # it ran out at 61
        self.assertEqual(Notification.objects.get(recipient=third, kind='alarm').queued_at, self.at(61))
        self.loop(minutes=70)
        self.assertFalse(Escalation.objects.exists())                  # the escalation time counts from the end
        self.loop(minutes=71)
        self.assertEqual(Escalation.objects.get().escalated_at, self.at(71))

    def test_ended_early_it_goes_on_from_the_end(self):
        self.snooze(120)
        services.unshelve(self.alarm, self.snoozer, at=self.at(5))
        self.loop(minutes=14)
        self.assertFalse(Escalation.objects.exists())
        self.loop(minutes=15)
        self.assertTrue(Escalation.objects.exists())
        with self.assertRaisesMessage(ValidationError, 'not snoozed'):
            services.unshelve(self.alarm, self.snoozer, at=self.at(16))

    def test_a_snooze_that_ran_out_while_the_worker_was_down_ends_at_its_first_pass(self):
        self.snooze(30)
        self.loop(minutes=90)                                          # nothing ran from 1 to 90
        self.assertEqual(Escalation.objects.get().escalated_at, self.at(90))

    @override_settings(ALARM_TRANSPORTS={'push': 'alarms.tests.doubles.RecordingTransport'})
    def test_a_notification_queued_before_waits_and_goes_out_when_it_ends(self):
        RecordingTransport.sent.clear()
        self.addCleanup(RecordingTransport.sent.clear)
        self.snooze(60)
        found = outbox.send_due(self.at(2))
        self.assertEqual((found.snoozed, found.sent, [(sent.recipient, sent.kind) for sent in RecordingTransport.sent]),
                         (1, 1, [(self.operator, 'snoozed')]))      # the word that it was snoozed goes at once
        self.assertEqual(outbox.send_due(self.at(62)).sent, 1)

    def test_its_raises_and_clears_go_on_while_snoozed(self):
        self.snooze(240)
        self.sample(7.0, hours=0.5)
        self.loop(minutes=2)
        self.loop(minutes=4)
        self.assertFalse(read.is_open(self.alarm))                     # cleared while snoozed
        self.sample(5.4, hours=0.25)
        self.loop(minutes=10)
        self.assertEqual(Alarm.objects.filter(severity='critical', source='water_limit').count(), 2)


class PageTests(SnoozeCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.snoozer)

    def test_it_sits_in_company_alarms_and_in_the_matrix(self):
        place = navigation.place('alarms.view_alarmshelve')
        self.assertEqual((place.workspace.key, str(place.group.label)), ('company', 'Alarms'))
        self.assertEqual(next(area for area in access.areas() if area.model == 'alarms.AlarmShelve').actions,
                         ('view', 'add'))

    def test_snoozed_and_ended_through_the_pages(self):
        detail = reverse('alarms:alarm_detail', args=[self.alarm.pk])
        self.assertContains(self.client.get(detail), 'max="240"')
        with mock.patch('django.utils.timezone.now', return_value=self.at(1)):
            response = self.client.post(reverse('alarms:alarm_snooze', args=[self.alarm.pk]),
                                        {'minutes': '30', 'reason': 'Probe being cleaned'})
            self.assertRedirects(response, detail, fetch_redirect_response=False)
            row = AlarmShelve.objects.get()
            self.assertEqual((row.user, row.until, row.reason), (self.snoozer, self.at(31), 'Probe being cleaned'))
            page = self.client.get(detail)
            self.assertContains(page, 'Snoozed by Siri until')
            self.assertContains(page, 'End snooze')
            self.assertContains(self.client.get(reverse('alarms:alarm_list')), 'Snoozed until')
            self.assertContains(self.client.get(reverse('alarms:alarm_snoozes')), 'In force')
            self.client.post(reverse('alarms:alarm_snooze_end', args=[self.alarm.pk]))
            self.assertEqual(AlarmShelveEnd.objects.get().user, self.snoozer)
            self.assertContains(self.client.get(reverse('alarms:alarm_snoozes')), 'Ended early by Siri')
            self.assertContains(self.client.get(detail), 'Snooze ended by Siri')

    def test_a_refused_snooze_says_why(self):
        response = self.client.post(reverse('alarms:alarm_snooze', args=[self.alarm.pk]),
                                    {'minutes': '500', 'reason': 'x'}, follow=True)
        self.assertContains(response, '1 to 240 minutes')
        self.assertFalse(AlarmShelve.objects.exists())

    def test_nobody_without_the_right_snoozes(self):
        reader = get_user_model().objects.create_user('reader', 'reader@example.com', 'x')
        reader.groups.add(role('Alarm reader', 'view_alarm'))
        self.client.force_login(reader)
        self.assertNotContains(self.client.get(reverse('alarms:alarm_detail', args=[self.alarm.pk])), 'Snooze for')
        for name in ('alarm_snooze', 'alarm_snooze_end'):
            self.assertEqual(self.client.post(reverse(f'alarms:{name}', args=[self.alarm.pk]),
                                              {'minutes': '30', 'reason': 'x'}).status_code, 403)
        self.assertEqual(self.client.get(reverse('alarms:alarm_snoozes')).status_code, 403)
        self.assertFalse(AlarmShelve.objects.exists())

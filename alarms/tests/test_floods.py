"""Alarm floods (alarms/floods.py; the owner's burst requirement): many warnings of one kind for one person become one flood
message, and the ones within the flood window after it are covered by it; a burst of criticals is the first on its own
and one follow-up message naming the rest, none ever covered (test_review_final); every alarm is still raised, kept,
listed and escalated on its own. The kind of an alarm is its site, its severity and what it is about; different people, kinds and
windows are never mixed. The pages show a flood of open alarms."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import DatabaseError, transaction
from django.test import override_settings
from django.urls import reverse

from farm.tests.helpers import role
from sensors.models import AlarmEvent, AlarmRule
from sensors.tests import make_channel, make_connection, make_device, make_format

from .. import floods, outbox, read, rules as alarm_rules, services
from ..models import Alarm, DeliveryAttempt, Notification, SeverityPolicy
from . import AlarmsCase
from .doubles import RecordingTransport
from farm.tests.helpers import may_record

RECORDING = {'push': 'alarms.tests.doubles.RecordingTransport'}
FAILING = {'push': 'alarms.tests.doubles.FailingTransport'}


class FloodCase(AlarmsCase):
    def setUp(self):
        super().setUp()
        RecordingTransport.sent.clear()
        RecordingTransport.floods.clear()
        self.addCleanup(RecordingTransport.sent.clear)
        self.addCleanup(RecordingTransport.floods.clear)

    def alarms(self, count, seconds=0, kind='sensors_failed', severity='critical', site=None, to=None):
        """`count` alarms of the alarm system of one kind, opened `seconds` after self.now, each with a level-0
        notification queued for `to` (the operator) then."""
        at = self.now + timedelta(seconds=seconds)
        made = []
        for number in range(count):
            alarm = services.open_alarm(source='system', parameter=kind, severity=severity, at=at,
                                        summary=f'{kind} {seconds}/{number}', site=site or self.bergen)
            made += services.queue_many([Notification(alarm=alarm, recipient=to or self.operator, channel='push',
                                                      level=0, queued_at=at)])
        return made

    def send(self, seconds=0):
        return outbox.send_due(self.now + timedelta(seconds=seconds))


class KindTests(FloodCase):
    def test_the_kind_is_site_severity_and_what_it_is_about(self):
        rules = alarm_rules.current()
        self.assertEqual(dict(SeverityPolicy.objects.values_list('severity', 'flood_count')), {'critical': 3,
                                                                                                 'warning': 3})
        self.assertEqual(rules.flood_window('critical'), timedelta(seconds=120))
        point = self.mid1
        mg = Alarm(source='water_limit', point=point, parameter='oxygen_mg_l', severity='critical', site=self.bergen)
        pct = Alarm(source='water_limit', point=point, parameter='oxygen_saturation_pct', severity='critical',
                    site=self.bergen)
        ph = Alarm(source='water_limit', point=point, parameter='ph', severity='critical', site=self.bergen)
        oslo = Alarm(source='water_limit', point=point, parameter='oxygen_mg_l', severity='critical', site=self.oslo)
        warning = Alarm(source='water_limit', point=point, parameter='oxygen_mg_l', severity='warning', site=self.bergen)
        self.assertEqual(floods.key(mg), floods.key(pct))                     # one quantity, in mg/L or in %
        self.assertEqual(len({floods.key(alarm) for alarm in (mg, ph, oslo, warning)}), 4)
        device = make_device(make_connection(), make_format(), self.bergen)
        rule = AlarmRule.objects.create(kind='low', severity='warning', channel=make_channel(device, 'flow_m3_h'),
                                        threshold=10)
        event = AlarmEvent.objects.create(rule=rule, channel_no=rule.channel.channel_no, opened_at=self.now, peak=4)
        self.assertTrue(floods.key(Alarm(source='sensor_rule', sensor_event=event, severity='warning',
                                         site=self.bergen)).endswith(f'rule:{rule.pk}'))

    def test_the_rows_bound_a_flood(self):
        for values in ({'flood_count': 1}, {'flood_count': 1001}, {'flood_window_seconds': 9},
                       {'flood_window_seconds': 3601}):
            with self.subTest(values=values), self.assertRaises(DatabaseError), transaction.atomic():
                SeverityPolicy.objects.filter(severity='critical').update(**values)


@override_settings(ALARM_TRANSPORTS=RECORDING)
class BurstTests(FloodCase):
    def test_a_burst_is_one_message_per_person_and_every_notification_is_written_with_it(self):
        made = self.alarms(24, severity='warning')
        found = self.send()
        self.assertEqual((found.floods, found.sent, found.grouped), (1, 24, 0))
        ((first, flood),) = RecordingTransport.floods
        self.assertEqual((first.pk, flood.size, flood.since), (made[0].pk, 24, self.now))
        self.assertEqual(len(RecordingTransport.sent), 1)                      # one message, not 24
        self.assertEqual(set(DeliveryAttempt.objects.values_list('outcome', 'flood_size')), {('sent', 24)})
        self.assertEqual({read.status(notification) for notification in made}, {'sent'})
        self.assertEqual(Alarm.objects.count(), 24)                            # every alarm kept on its own
        self.assertEqual(self.send(1).backlog, 0)

    def test_a_burst_of_criticals_is_the_first_on_its_own_and_one_follow_up_naming_the_rest(self):
        made = self.alarms(24)
        found = self.send()
        self.assertEqual((found.floods, found.sent, found.grouped), (1, 24, 0))
        first, follow_up = RecordingTransport.sent
        self.assertEqual(first.pk, made[0].pk)
        self.assertEqual(RecordingTransport.floods[0][1].size, 23)
        for row in made[1:]:
            self.assertIn(row.alarm.summary, follow_up.text)
        self.assertIn('23 open now', follow_up.text)
        self.assertEqual(self.send(1).backlog, 0)

    def test_the_ones_after_a_flood_message_are_covered_within_the_window_and_counted_again_after_it(self):
        self.alarms(5, severity='warning')
        self.send()
        self.alarms(2, seconds=30, severity='warning')
        found = self.send(30)
        self.assertEqual((found.grouped, found.sent, len(RecordingTransport.sent)), (2, 0, 1))
        covered = DeliveryAttempt.objects.filter(outcome='grouped')
        self.assertEqual(covered.count(), 2)
        self.assertIn('covered by the flood message', covered.first().detail)
        later = self.alarms(1, seconds=200, severity='warning')                # past the 120 s window
        found = self.send(200)
        self.assertEqual((found.sent, found.grouped, found.floods), (1, 0, 0))
        self.assertEqual(RecordingTransport.sent[-1].pk, later[0].pk)

    def test_a_trickle_becomes_a_flood_once_the_window_holds_enough(self):
        self.alarms(1, severity='warning')
        self.send()
        self.alarms(1, seconds=10, severity='warning')
        self.send(10)
        self.assertEqual(len(RecordingTransport.floods), 0)                    # two sent on their own
        self.alarms(1, seconds=20, severity='warning')
        found = self.send(20)
        self.assertEqual((found.floods, RecordingTransport.floods[0][1].size), (1, 3))
        self.alarms(1, seconds=25, severity='warning')
        self.assertEqual(self.send(25).grouped, 1)

    def test_people_and_kinds_are_never_mixed(self):
        self.alarms(3, severity='warning')
        self.alarms(3, severity='warning', to=self.manager)
        self.alarms(1, kind='step_failed', severity='warning')
        self.alarms(1, site=self.oslo, severity='warning')
        self.alarms(1)
        found = self.send()
        self.assertEqual((found.floods, found.sent), (2, 9))
        self.assertEqual(sorted(flood.size for _first, flood in RecordingTransport.floods), [3, 3])
        self.assertEqual({first.recipient for first, _flood in RecordingTransport.floods}, {self.operator, self.manager})

    def test_a_snoozed_alarm_waits_outside_its_flood(self):
        made = self.alarms(3, severity='warning', kind='unit_unevaluated')   # (sensors_failed is never snoozed)
        snoozer = may_record(get_user_model().objects.create_user('snoozer', 'snoozer@example.com', 'x'),
                             'add_alarmshelve')
        services.shelve(made[0].alarm, snoozer, 30, 'probe cleaned', at=self.now)
        found = self.send(1)
        self.assertEqual((found.snoozed, found.sent, found.floods), (1, 3, 0))        # two: not a flood of three
        self.assertEqual(sorted(sent.kind for sent in RecordingTransport.sent), ['alarm', 'alarm', 'snoozed'])


class FailingFloodTests(FloodCase):
    def test_a_flood_message_that_fails_is_tried_again_as_one(self):
        self.alarms(4, severity='warning')
        with override_settings(ALARM_TRANSPORTS=FAILING):
            found = self.send()
        self.assertEqual((found.floods, found.failed), (1, 4))
        self.assertEqual(set(DeliveryAttempt.objects.values_list('outcome', 'flood_size')), {('failed', 4)})
        with override_settings(ALARM_TRANSPORTS=RECORDING):
            self.assertEqual(self.send(10).retrying, 4)                        # its retry time (120 s) first
            found = self.send(120)
        self.assertEqual((found.floods, found.sent, len(RecordingTransport.sent)), (1, 4, 1))

    def test_a_grouped_attempt_is_written_once(self):
        (notification,) = self.alarms(1)
        services.attempt(notification, RecordingTransport().send(notification), self.now, grouped=True)
        with self.assertRaises(DatabaseError), transaction.atomic():
            services.attempt(notification, RecordingTransport().send(notification), self.now)


class PageTests(FloodCase):
    def test_the_alarms_page_shows_a_flood_of_open_alarms_and_the_history_the_flood_message(self):
        desk = get_user_model().objects.create_user('desk', 'desk@example.com', 'x')
        desk.groups.add(role('Alarm desk', 'view_alarm'))
        self.client.force_login(desk)
        made = self.alarms(4)
        with override_settings(ALARM_TRANSPORTS=RECORDING):
            self.send()
        self.alarms(2, seconds=600)                                            # far apart: not the same flood
        self.assertContains(self.client.get(reverse('alarms:alarm_list')), 'Alarm flood: 4 open Critical alarms')
        self.assertContains(self.client.get(reverse('alarms:alarm_detail', args=[made[1].alarm_id])),
                            'in a flood message of 3 alarms')                 # the follow-up after the first
        self.assertEqual([flood.size for flood in floods.open_floods(alarm_rules.current())], [4])

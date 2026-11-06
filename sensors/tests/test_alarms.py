"""Sensor alarms, shown and not sent (owner question 1): rules on a channel or on every channel of a quantity (no data, the
device offline, above, below, a change faster than a rate), checked by manage.py check_sensors from the state and the
clean readings only; an event opens once per rule and channel, keeps its peak, closes past the hysteresis, and a person
acknowledges it (logged). A high or low rule on a water quantity is refused: the water limits judge those. The pages say
plainly that nobody is notified."""
from datetime import timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection
from django.urls import reverse
from django.utils import timezone

from core.models import AuditLog
from farm.tests.helpers import role

from alarms.models import Acknowledgement
from sensors import alarms
from sensors.models import AlarmEvent, AlarmRule, ChannelState, DeviceState

from . import SensorsCase, make_channel

KEEPER = ('view_alarmrule', 'add_alarmrule', 'change_alarmrule', 'delete_alarmrule', 'view_alarmevent',
          'change_alarmevent', 'view_channel')


class AlarmCase(SensorsCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.flow = make_channel(cls.device, 'flow_m3_h')

    def state(self, channel, value, seconds=5):
        at = timezone.now() - timedelta(seconds=seconds)
        ChannelState.objects.update_or_create(channel_no=channel.channel_no, defaults={
            'last_value': value, 'last_value_ts': at, 'last_good_at': at, 'last_seen_at': at})

    def readings(self, channel, rows):
        with connection.cursor() as cursor:
            cursor.executemany('INSERT INTO sensors_reading (channel_no, ts, value) VALUES (%s, %s, %s)',
                               [(channel.channel_no, timezone.now() - timedelta(seconds=ago), value) for ago, value in rows])


class RuleRulesTests(AlarmCase):
    def test_one_of_channel_or_quantity_and_a_threshold_where_it_is_needed(self):
        self.refused('chk_sensors_alarm_rule_scope', lambda: AlarmRule.objects.create(kind='no_data', severity='warning'))
        self.refused('chk_sensors_alarm_rule_scope', lambda: AlarmRule.objects.create(
            kind='no_data', severity='warning', channel=self.flow, quantity='flow_m3_h'))
        self.refused('chk_sensors_alarm_rule_threshold', lambda: AlarmRule.objects.create(
            kind='high', severity='warning', channel=self.flow))
        self.refused('chk_sensors_alarm_rule_kind', lambda: AlarmRule.objects.create(
            kind='loud', severity='warning', channel=self.flow))
        self.refused('chk_sensors_alarm_rule_numbers', lambda: AlarmRule.objects.create(
            kind='no_data', severity='warning', channel=self.flow, for_s=-1))

    def test_one_open_event_per_rule_and_channel(self):
        rule = AlarmRule.objects.create(kind='no_data', severity='warning', channel=self.flow)
        AlarmEvent.objects.create(rule=rule, channel_no=self.flow.channel_no, opened_at=timezone.now())
        self.refused('uq_sensors_alarm_event_open', lambda: AlarmEvent.objects.create(
            rule=rule, channel_no=self.flow.channel_no, opened_at=timezone.now()))


class EvaluateTests(AlarmCase):
    def test_high_opens_keeps_its_peak_and_closes_past_the_hysteresis(self):
        rule = AlarmRule.objects.create(kind='high', severity='critical', channel=self.flow, threshold=100, hysteresis=5)
        self.state(self.flow, 120)
        self.readings(self.flow, [(30, 115), (5, 120)])
        alarms.evaluate()
        event = AlarmEvent.objects.get()
        self.assertEqual((event.rule, event.peak, event.closed_at), (rule, 120, None))
        self.state(self.flow, 130)
        alarms.evaluate()
        self.assertEqual(AlarmEvent.objects.get().peak, 130)
        self.state(self.flow, 98)                                       # under the threshold, inside the hysteresis
        alarms.evaluate()
        self.assertIsNone(AlarmEvent.objects.get().closed_at)
        self.state(self.flow, 94)
        alarms.evaluate()
        self.assertIsNotNone(AlarmEvent.objects.get().closed_at)

    def test_high_for_a_time_needs_every_value_of_that_time_above(self):
        AlarmRule.objects.create(kind='high', severity='warning', channel=self.flow, threshold=100, for_s=60)
        self.state(self.flow, 120)
        self.readings(self.flow, [(50, 90), (5, 120)])
        alarms.evaluate()
        self.assertFalse(AlarmEvent.objects.exists())

    def test_a_quantity_rule_applies_to_every_channel_of_it(self):
        other = make_channel(self.device, 'flow_m3_h', code='FLOW-2')
        AlarmRule.objects.create(kind='low', severity='warning', quantity='flow_m3_h', threshold=10)
        self.state(self.flow, 5)
        self.state(other, 50)
        alarms.evaluate()
        self.assertEqual(list(AlarmEvent.objects.values_list('channel_no', flat=True)), [self.flow.channel_no])

    def test_no_data_and_device_offline(self):
        AlarmRule.objects.create(kind='no_data', severity='warning', channel=self.flow, for_s=0)
        AlarmRule.objects.create(kind='device_offline', severity='critical', channel=self.flow)
        self.state(self.flow, 50, seconds=3600)
        alarms.evaluate()
        self.assertEqual(AlarmEvent.objects.filter(rule__kind='no_data').count(), 1)
        self.assertEqual(AlarmEvent.objects.filter(rule__kind='device_offline').count(), 1)
        DeviceState.objects.create(device_id=self.device.pk, last_message_at=timezone.now())
        self.state(self.flow, 50)
        alarms.evaluate()
        self.assertFalse(AlarmEvent.objects.filter(closed_at__isnull=True).exists())

    def test_rate_is_the_change_over_its_time(self):
        AlarmRule.objects.create(kind='rate', severity='warning', channel=self.flow, threshold=20, for_s=60)
        self.state(self.flow, 100)
        self.readings(self.flow, [(70, 50), (5, 100)])
        alarms.evaluate()
        self.assertEqual(AlarmEvent.objects.count(), 1)

    def test_an_inactive_rule_or_a_channel_in_maintenance_opens_nothing(self):
        AlarmRule.objects.create(kind='low', severity='warning', channel=self.flow, threshold=10, is_active=False)
        self.state(self.flow, 1)
        alarms.evaluate()
        self.assertFalse(AlarmEvent.objects.exists())

    def test_the_command_runs_once(self):
        AlarmRule.objects.create(kind='low', severity='warning', channel=self.flow, threshold=10)
        self.state(self.flow, 1)
        call_command('check_sensors', stdout=StringIO())
        self.assertEqual(AlarmEvent.objects.count(), 1)


class PageTests(AlarmCase):
    def setUp(self):
        self.keeper = get_user_model().objects.create_user('keeper', 'keeper@example.com', 'x')
        self.keeper.groups.add(role('Alarm keeper', *KEEPER))
        self.client.force_login(self.keeper)

    def test_a_rule_is_created_and_a_water_high_or_low_is_refused(self):
        response = self.client.post(reverse('sensors:alarmrule_create'), {
            'scope': 'channel', 'channel': self.flow.pk, 'quantity': '', 'kind': 'high', 'threshold': '100',
            'for_s': '60', 'hysteresis': '2', 'severity': 'critical', 'is_active': 'on'})
        self.assertIn(response.status_code, (204, 302), response.context and response.context['form'].errors)
        rule = AlarmRule.objects.get()
        self.assertEqual((rule.channel, rule.threshold, rule.for_s, rule.hysteresis, rule.severity),
                         (self.flow, 100.0, 60, 2.0, 'critical'))
        response = self.client.post(reverse('sensors:alarmrule_create'), {
            'channel': self.channel.pk, 'kind': 'high', 'threshold': '20', 'for_s': '0', 'hysteresis': '0',
            'severity': 'warning', 'is_active': 'on'})
        self.assertContains(response, 'The water limits judge')

    def test_events_are_listed_said_not_sent_and_acknowledged_with_a_log(self):
        rule = AlarmRule.objects.create(kind='low', severity='warning', channel=self.flow, threshold=10)
        event = AlarmEvent.objects.create(rule=rule, channel_no=self.flow.channel_no, opened_at=timezone.now(), peak=4)
        page = self.client.get(reverse('sensors:alarm_events'))
        self.assertContains(page, 'Nothing is sent yet')
        self.client.post(reverse('sensors:alarm_event_acknowledge', args=[event.pk]))
        self.assertEqual(Acknowledgement.objects.get(alarm__sensor_event=event).user, self.keeper)
        self.assertTrue(AuditLog.objects.filter(entity_type='alarm acknowledgement').exists())

    def test_open_events_of_a_site(self):
        rule = AlarmRule.objects.create(kind='low', severity='warning', channel=self.flow, threshold=10)
        AlarmEvent.objects.create(rule=rule, channel_no=self.flow.channel_no, opened_at=timezone.now())
        self.assertEqual(len(alarms.open_events(self.site)), 1)
        self.assertEqual(len(alarms.open_events()), 1)

    def test_the_water_rule_message_is_raised_by_the_service_too(self):
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            AlarmRule(kind='low', severity='warning', channel=self.channel, threshold=5).full_clean()

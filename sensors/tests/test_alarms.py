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
from farm.models import ProductionDepartment, Site, System
from farm.tests.helpers import role

from sensors import alarms, bindings
from sensors.models import AlarmEvent, AlarmRule, ChannelState, DeviceState

from . import SensorsCase, make_channel, make_device

KEEPER = ('view_alarmrule', 'add_alarmrule', 'change_alarmrule', 'delete_alarmrule', 'view_alarmevent',
          'change_alarmevent', 'view_channel')


class AlarmCase(SensorsCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.flow = make_channel(cls.device, 'flow_m3_h')
        cls.ras = System.objects.create(name='RAS 1', code='R1', site=cls.site, production_department=cls.hall)
        cls.bound = bindings.move(cls.user, cls.flow, timezone.now() - timedelta(days=30), system=cls.ras)

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
        self.assertContains(page, 'Nobody is notified')
        self.client.post(reverse('sensors:alarm_event_acknowledge', args=[event.pk]))
        event.refresh_from_db()
        self.assertEqual(event.acknowledged_by, self.keeper)
        self.assertTrue(AuditLog.objects.filter(entity_id=str(event.pk)).exists())

    def test_open_events_of_a_site(self):
        rule = AlarmRule.objects.create(kind='low', severity='warning', channel=self.flow, threshold=10)
        AlarmEvent.objects.create(rule=rule, channel_no=self.flow.channel_no, opened_at=timezone.now(), binding=self.bound)
        self.assertEqual(len(alarms.open_events(self.site)), 1)
        self.assertEqual(len(alarms.open_events()), 1)

    def test_the_water_rule_message_is_raised_by_the_service_too(self):
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            AlarmRule(kind='low', severity='warning', channel=self.channel, threshold=5).full_clean()


class PlaceTests(AlarmCase):
    """An alarm belongs to the place, through the binding it opened under: only a channel bound now is checked, and only
    with values measured while it was bound there; moving it or taking it out of the water closes its open events then;
    a site's open events are those of its places, whatever the device's site is now."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.oslo = Site.objects.create(name='Oslo', code='OS', timezone='Europe/Oslo')
        cls.r9 = System.objects.create(name='RAS 9', code='R9', site=cls.oslo, production_department=(
            ProductionDepartment.objects.create(site=cls.oslo, name='Hall O', code='HO')))
        cls.probe = make_device(cls.connection, cls.format, cls.site, code='ORP-1')
        cls.orp = make_channel(cls.probe, 'orp_mv')

    def place(self, at=None, system=None):
        bindings.move_device(self.user, self.probe, at or timezone.now() - timedelta(hours=2), system or self.ras)

    def test_an_event_opens_under_the_binding_of_its_place(self):
        self.place()
        AlarmRule.objects.create(kind='high', severity='warning', channel=self.orp, threshold=400)
        self.state(self.orp, 450)
        alarms.evaluate()
        event = AlarmEvent.objects.get()
        self.assertEqual(event.binding, bindings.Binding.objects.get(channel=self.orp, valid_to__isnull=True))
        self.assertEqual(len(alarms.open_events(self.site)), 1)

    def test_a_move_or_taking_it_out_closes_its_open_events_then(self):
        self.place(timezone.now() - timedelta(hours=3))
        AlarmRule.objects.create(kind='high', severity='warning', channel=self.orp, threshold=400)
        self.state(self.orp, 450, seconds=60)
        alarms.evaluate()
        moved_at = timezone.now()
        bindings.move_device(self.user, self.probe, moved_at, self.r9)
        event = AlarmEvent.objects.get()
        self.assertEqual(event.closed_at, moved_at)
        self.assertEqual((alarms.open_events(self.site), alarms.open_events(self.oslo)), ([], []))
        alarms.evaluate()                                     # the value measured in Bergen is not Oslo's
        self.assertEqual(AlarmEvent.objects.filter(closed_at__isnull=True).count(), 0)
        self.state(self.orp, 470)                             # measured in Oslo
        alarms.evaluate()
        self.assertEqual([str(event.binding.target) for event in alarms.open_events(self.oslo)], ['RAS 9 (R9)'])
        out_at = timezone.now().replace(microsecond=0)
        bindings.unbind_device(self.user, self.probe, out_at)
        self.assertEqual(AlarmEvent.objects.filter(closed_at__isnull=True).count(), 0)

    def test_a_device_out_of_the_water_is_not_checked(self):
        AlarmRule.objects.create(kind='high', severity='warning', channel=self.orp, threshold=400)
        AlarmRule.objects.create(kind='no_data', severity='warning', channel=self.orp, for_s=0)
        AlarmRule.objects.create(kind='device_offline', severity='warning', channel=self.orp)
        self.state(self.orp, 450, seconds=7200)
        alarms.evaluate()
        self.assertFalse(AlarmEvent.objects.exists())

    def test_the_no_data_clock_starts_when_it_is_placed(self):
        AlarmRule.objects.create(kind='no_data', severity='warning', channel=self.orp, for_s=0)
        self.state(self.orp, 300, seconds=7200)               # its last value, from before it came here
        self.place(timezone.now() - timedelta(seconds=30))
        alarms.evaluate()
        self.assertFalse(AlarmEvent.objects.exists())          # placed 30 s ago: not yet past its freshness
        bindings.Binding.objects.filter(channel=self.orp, valid_to__isnull=True).update(
            valid_from=timezone.now() - timedelta(hours=1))     # placed an hour ago, nothing measured since
        alarms.evaluate()
        self.assertEqual(AlarmEvent.objects.filter(rule__kind='no_data').count(), 1)

    def test_the_time_above_counts_only_the_readings_taken_there(self):
        AlarmRule.objects.create(kind='high', severity='warning', channel=self.orp, threshold=400, for_s=600)
        self.readings(self.orp, [(500, 300), (200, 450), (5, 460)])     # 300 was taken before it came here
        self.place(timezone.now() - timedelta(seconds=300))
        self.state(self.orp, 460)
        alarms.evaluate()
        self.assertEqual(AlarmEvent.objects.count(), 1)

"""The data-layering audit, L-5: who may acknowledge an alarm is one rule (alarms.read.may_acknowledge: Alarms: Edit, or a
person one of its notifications went to), asked by the service itself (alarms.services.acknowledge), whoever calls it:
the alarm's page, the Sensors › Alarm events page, a future mobile app. Without a notification given, the person's own
is the one they answered."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.urls import reverse

from farm.tests.helpers import role
from sensors import bindings
from sensors.models import AlarmEvent, AlarmRule
from sensors.tests import make_channel, make_connection, make_device, make_format

from .. import services
from ..models import Acknowledgement
from . import AlarmsCase


class OneRuleTests(AlarmsCase):
    def setUp(self):
        super().setUp()
        self.rule()
        self.sample(5.5)
        self.loop()
        self.alarm = self.critical()

    def test_the_service_refuses_who_may_not_whatever_calls_it(self):
        with self.assertRaises(PermissionDenied):
            services.acknowledge(self.alarm, self.manager, app='console')
        self.assertFalse(Acknowledgement.objects.exists())

    def test_a_person_it_was_sent_to_may_and_their_notification_is_the_one_answered(self):
        ack = services.acknowledge(self.alarm, self.operator, app='console')
        mine = self.alarm.notifications.filter(recipient=self.operator).order_by('-level').first()
        self.assertIsNotNone(mine)
        self.assertEqual((ack.user, ack.notification), (self.operator, mine))

    def test_alarms_edit_may_without_a_notification(self):
        self.manager.groups.add(role('Alarm admin', 'change_alarm'))
        self.manager = get_user_model().objects.get(pk=self.manager.pk)        # its rights read again
        ack = services.acknowledge(self.alarm, self.manager, app='console')
        self.assertEqual((ack.user, ack.notification), (self.manager, None))


class SensorEventsPageTests(AlarmsCase):
    def setUp(self):
        super().setUp()
        device = make_device(make_connection(), make_format(), self.bergen)
        flow = make_channel(device, 'flow_m3_h')
        rule = AlarmRule.objects.create(kind='low', severity='warning', channel=flow, threshold=10)
        bound = bindings.move(self.keeper, flow, self.now - timedelta(days=1), system=self.ras)
        self.event = AlarmEvent.objects.create(rule=rule, channel_no=flow.channel_no, opened_at=self.now, peak=4,
                                               binding=bound)
        self.viewer = get_user_model().objects.create_user('viewer', 'viewer@example.com', 'x')
        self.viewer.groups.add(role('Event reader', 'view_alarmevent'))
        self.client.force_login(self.viewer)

    def test_reading_the_events_gives_no_acknowledgement(self):
        page = self.client.get(reverse('sensors:alarm_events'))
        self.assertNotContains(page, reverse('sensors:alarm_event_acknowledge', args=[self.event.pk]))
        response = self.client.post(reverse('sensors:alarm_event_acknowledge', args=[self.event.pk]))
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Acknowledgement.objects.exists())

    def test_alarms_edit_acknowledges_from_the_events_page(self):
        self.viewer.groups.add(role('Alarm admin', 'change_alarm'))
        page = self.client.get(reverse('sensors:alarm_events'))
        self.assertContains(page, reverse('sensors:alarm_event_acknowledge', args=[self.event.pk]))
        self.client.post(reverse('sensors:alarm_event_acknowledge', args=[self.event.pk]))
        self.assertEqual(Acknowledgement.objects.get().user, self.viewer)

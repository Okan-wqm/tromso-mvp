"""Company › Alarms: the alarms with their history (opened, notified, delivered or waiting, escalated, acknowledged,
cleared), the page saying plainly that nothing is sent while no transport is connected, the acknowledgement from the
console, and the recipient rules as a tab."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.urls import reverse

from core import access, navigation
from core.models import AuditLog
from farm.tests.helpers import role
from sensors import bindings
from sensors.models import AlarmEvent, AlarmRule
from sensors.tests import make_channel, make_connection, make_device, make_format

from ..models import Acknowledgement, RecipientRule
from . import NOTHING_CONNECTED, AlarmsCase

READER = ('view_alarm',)
DESK = ('view_alarm', 'change_alarm', 'view_recipientrule', 'add_recipientrule', 'change_recipientrule',
        'delete_recipientrule')


class PageTests(AlarmsCase):
    def setUp(self):
        super().setUp()
        self.desk = get_user_model().objects.create_user('desk', 'desk@example.com', 'x')
        self.desk.groups.add(role('Alarm desk', *DESK))
        self.rule()
        self.sample(5.5)
        self.loop()
        self.alarm = self.critical()

    def test_they_sit_in_company_and_in_the_matrix(self):
        for perm, actions in (('alarms.view_alarm', ('view', 'change')),
                              ('alarms.view_recipientrule', ('view', 'add', 'change', 'delete'))):
            place = navigation.place(perm)
            self.assertEqual((place.workspace.key, str(place.group.label)), ('company', 'Alarms'))
            model = perm.replace('view_', '').replace('alarms.', '')
            area = next(area for area in access.areas() if area.model.lower() == f'alarms.{model}')
            self.assertEqual(area.actions, actions)

    @NOTHING_CONNECTED
    def test_reading_needs_the_right_and_the_page_says_nothing_is_sent(self):
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(reverse('alarms:alarm_list')).status_code, 403)
        self.client.force_login(self.desk)
        page = self.client.get(reverse('alarms:alarm_list'))
        self.assertContains(page, 'Nothing is sent yet')
        self.assertContains(page, 'T-01')
        self.assertContains(page, reverse('alarms:alarm_detail', args=[self.alarm.pk]))

    def test_an_alarms_page_shows_its_history(self):
        self.client.force_login(self.desk)
        self.loop(minutes=1)
        page = self.client.get(reverse('alarms:alarm_detail', args=[self.alarm.pk]))
        for text in ('Opened', 'Ola', 'Queued', 'Push'):
            self.assertContains(page, text)

    def test_the_operator_notified_may_acknowledge_without_the_desks_right(self):
        reader = self.operator
        reader.groups.add(role('Alarm reader', *READER))
        self.client.force_login(reader)
        response = self.client.post(reverse('alarms:alarm_acknowledge', args=[self.alarm.pk]))
        self.assertEqual(response.status_code, 302)
        ack = Acknowledgement.objects.get()
        self.assertEqual((ack.user, ack.app, ack.device), (self.operator, 'console', ''))
        page = self.client.get(reverse('alarms:alarm_detail', args=[self.alarm.pk]))
        self.assertContains(page, 'Acknowledged')

    def test_a_reader_not_notified_may_not_acknowledge(self):
        self.manager.groups.add(role('Alarm reader', *READER))
        self.client.force_login(self.manager)
        self.assertEqual(self.client.post(reverse('alarms:alarm_acknowledge', args=[self.alarm.pk])).status_code, 403)
        self.assertFalse(Acknowledgement.objects.exists())

    def test_the_open_filter(self):
        self.client.force_login(self.desk)
        self.sample(7.0, hours=0.5)
        self.loop(minutes=1)
        self.loop(minutes=2)                                   # cleared after the off-delay
        self.assertNotContains(self.client.get(reverse('alarms:alarm_list'), {'state': 'open'}),
                               reverse('alarms:alarm_detail', args=[self.alarm.pk]))
        self.assertContains(self.client.get(reverse('alarms:alarm_list'), {'state': 'all'}),
                            reverse('alarms:alarm_detail', args=[self.alarm.pk]))

    def test_recipient_rules_are_a_tab_with_its_log(self):
        self.client.force_login(self.desk)
        response = self.client.post(reverse('alarms:recipientrule_create'), {
            'site': str(self.bergen.pk), 'production_department': '', 'min_severity': 'critical', 'level': '1',
            'role': '', 'user': str(self.manager.pk), 'on_shift_only': '', 'channel': 'push', 'is_active': 'on'})
        self.assertEqual(response.status_code, 302, response.context and response.context['form'].errors)
        rule = RecipientRule.objects.get(user=self.manager)
        self.assertEqual((rule.level, rule.min_severity), (1, 'critical'))
        self.assertTrue(AuditLog.objects.filter(entity_type='alarm recipient rule', action='create').exists())
        self.assertContains(self.client.get(reverse('alarms:recipientrule_list')), 'Mona')


class SensorsPageTests(AlarmsCase):
    """The Sensors › Alarm events page acknowledges through the alarms: one record of who saw it."""

    @NOTHING_CONNECTED
    def test_its_acknowledge_writes_the_alarms_acknowledgement(self):
        device = make_device(make_connection(), make_format(), self.bergen)
        flow = make_channel(device, 'flow_m3_h')
        rule = AlarmRule.objects.create(kind='low', severity='warning', channel=flow, threshold=10)
        bound = bindings.move(self.keeper, flow, self.now - timedelta(days=1), system=self.ras)
        event = AlarmEvent.objects.create(rule=rule, channel_no=flow.channel_no, opened_at=self.now, peak=4, binding=bound)
        keeper = get_user_model().objects.create_user('tech', 'tech@example.com', 'x')
        keeper.groups.add(role('Sensor keeper', 'view_alarmevent', 'change_alarm'))      # Alarms: Edit (L-5)
        self.client.force_login(keeper)
        page = self.client.get(reverse('sensors:alarm_events'))
        self.assertContains(page, 'Nothing is sent yet')
        self.client.post(reverse('sensors:alarm_event_acknowledge', args=[event.pk]))
        ack = Acknowledgement.objects.get()
        self.assertEqual((ack.alarm.sensor_event, ack.user, ack.app), (event, keeper, 'console'))
        self.assertContains(self.client.get(reverse('sensors:alarm_events')), 'tech')
        self.client.post(reverse('sensors:alarm_event_acknowledge', args=[event.pk]))       # twice: once
        self.assertEqual(Acknowledgement.objects.count(), 1)


class RoleDeleteTests(AlarmsCase):
    """A role an alarm recipient rule names is not deleted from under it: the rule would reach nobody without a word."""

    def test_deleting_a_role_a_rule_names_is_refused_and_said(self):
        self.rule()
        admin = get_user_model().objects.create_superuser('root', 'root@example.com', 'x')
        self.client.force_login(admin)
        response = self.client.post(reverse('core:group_delete', args=[self.operators.pk]), follow=True)
        self.assertContains(response, 'cannot be deleted')
        self.assertTrue(type(self.operators).objects.filter(pk=self.operators.pk).exists())
        self.assertEqual(RecipientRule.objects.count(), 1)

"""The alarm rules are the user's reference data, never the code's (owner, alarm plan §7c): the delays, the escalation time
and the delivery attempts per severity, and the deadband per water parameter, are rows a person with the right edits on
Company › Alarms, seeded with the owner's defaults (§7a), bounded by the database, logged; the code holds no threshold."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.urls import reverse

from core import access, navigation
from core.models import AuditLog, PlatformSettings
from farm.tests.helpers import role

from .. import rules
from ..models import ParameterDeadband, SeverityPolicy
from . import AlarmsCase

SEEDED_POLICIES = {'critical': (0, 30, 5, 5), 'warning': (30, 30, 30, 5)}
SEEDED_DEADBANDS = {'oxygen_mg_l': '0.2', 'oxygen_saturation_pct': '2', 'temperature_c': '0.3', 'ph': '0.05',
                    'co2_mg_l': '1', 'tan_mg_l': '0.05', 'nh3_n_mg_l': '0.002', 'nitrite_n_mg_l': '0.05',
                    'salinity_ppt': '0.5'}
ADMIN = ('view_severitypolicy', 'change_severitypolicy', 'view_parameterdeadband', 'add_parameterdeadband',
         'change_parameterdeadband', 'delete_parameterdeadband')


class SeedTests(AlarmsCase):
    def test_the_owners_defaults_are_seeded_as_rows(self):
        self.assertEqual({policy.severity: (policy.on_delay_seconds, policy.off_delay_seconds, policy.escalation_minutes,
                                            policy.delivery_attempts) for policy in SeverityPolicy.objects.all()},
                         SEEDED_POLICIES)
        self.assertEqual({row.parameter: row.deadband for row in ParameterDeadband.objects.all()},
                         {code: Decimal(value) for code, value in SEEDED_DEADBANDS.items()})

    def test_the_escalation_time_is_the_severitys_not_a_platform_setting(self):
        self.assertFalse(hasattr(PlatformSettings, 'alarm_escalation_minutes'))
        SeverityPolicy.objects.filter(severity='critical').update(escalation_minutes=7)
        self.assertEqual(rules.current().escalation_after('critical'), timedelta(minutes=7))
        self.assertEqual(rules.current().escalation_after('warning'), timedelta(minutes=30))

    def test_a_changed_row_is_read_on_the_next_pass(self):
        before = rules.current()
        ParameterDeadband.objects.filter(parameter='ph').update(deadband=Decimal('0.1'))
        self.assertEqual(before.deadband('ph'), Decimal('0.05'))
        self.assertEqual(rules.current().deadband('ph'), Decimal('0.1'))
        self.assertEqual(rules.current().deadband('turbidity_ntu'), Decimal(0))    # no row: no deadband


class BoundsTests(AlarmsCase):
    def test_the_database_refuses_nonsense(self):
        cases = [(ParameterDeadband, {'deadband': Decimal('-0.1')}, {'parameter': 'ph'}),
                 (SeverityPolicy, {'on_delay_seconds': 3601}, {'severity': 'warning'}),
                 (SeverityPolicy, {'off_delay_seconds': -1}, {'severity': 'warning'}),
                 (SeverityPolicy, {'escalation_minutes': 0}, {'severity': 'warning'}),
                 (SeverityPolicy, {'escalation_minutes': 1441}, {'severity': 'warning'}),
                 (SeverityPolicy, {'delivery_attempts': 0}, {'severity': 'warning'}),
                 (SeverityPolicy, {'delivery_attempts': 21}, {'severity': 'warning'}),
                 (SeverityPolicy, {'retry_seconds': 0}, {'severity': 'warning'}),
                 (SeverityPolicy, {'retry_seconds': 3601}, {'severity': 'critical'})]
        for model, values, where in cases:
            with self.subTest(values=values), self.assertRaises(IntegrityError), transaction.atomic():
                model.objects.filter(**where).update(**values)
        with self.assertRaises(IntegrityError), transaction.atomic():
            SeverityPolicy.objects.create(severity='critical', on_delay_seconds=0, off_delay_seconds=0,
                                          escalation_minutes=5, delivery_attempts=5)    # one row per severity
        with self.assertRaises(IntegrityError), transaction.atomic():
            ParameterDeadband.objects.create(parameter='ph', deadband=Decimal('0.1'))    # one live row per parameter

    def test_a_deadband_wider_than_the_parameters_range_is_refused_by_the_form(self):
        admin = get_user_model().objects.create_user('alarmadmin', 'alarmadmin@example.com', 'x')
        admin.groups.add(role('Alarm admin', *ADMIN))
        self.client.force_login(admin)
        row = ParameterDeadband.objects.get(parameter='ph')
        response = self.client.post(reverse('alarms:parameterdeadband_edit', args=[row.pk]),
                                    {'parameter': 'ph', 'deadband': '50', 'version': row.version})
        self.assertIn('deadband', response.context['form'].errors)


class PageTests(AlarmsCase):
    def setUp(self):
        super().setUp()
        self.admin = get_user_model().objects.create_user('alarmadmin', 'alarmadmin@example.com', 'x')
        self.admin.groups.add(role('Alarm admin', *ADMIN))
        self.client.force_login(self.admin)

    def test_they_sit_under_company_alarms_and_in_the_matrix(self):
        for perm, model, actions in (('alarms.view_severitypolicy', 'alarms.SeverityPolicy', ('view', 'change')),
                                     ('alarms.view_parameterdeadband', 'alarms.ParameterDeadband',
                                      ('view', 'add', 'change', 'delete'))):
            place = navigation.place(perm)
            self.assertEqual((place.workspace.key, str(place.group.label)), ('company', 'Alarms'))
            self.assertEqual(next(area for area in access.areas() if area.model == model).actions, actions)

    def test_a_policy_is_edited_and_logged(self):
        policy = SeverityPolicy.objects.get(severity='warning')
        self.client.post(reverse('alarms:severitypolicy_edit', args=[policy.pk]), {
            'on_delay_seconds': '60', 'off_delay_seconds': '45', 'escalation_minutes': '20', 'delivery_attempts': '3',
            'retry_seconds': '90', 'shelve_max_minutes': '120', 'flood_count': '4', 'flood_window_seconds': '60',
            'clock_skew_seconds': '90', 'clock_skew_deadband_seconds': '15', 'clock_behind_window_seconds': '600',
            'version': policy.version})
        policy.refresh_from_db()
        self.assertEqual((policy.on_delay_seconds, policy.off_delay_seconds, policy.escalation_minutes,
                          policy.delivery_attempts, policy.retry_seconds), (60, 45, 20, 3, 90))
        entry = AuditLog.objects.get(entity_type='alarm severity rule', action='update')
        self.assertEqual(entry.changes['Raise after (seconds)'], ['30', '60'])
        self.assertContains(self.client.get(reverse('alarms:severitypolicy_list')), '60')

    def test_a_deadband_is_edited_and_logged(self):
        row = ParameterDeadband.objects.get(parameter='ph')
        self.client.post(reverse('alarms:parameterdeadband_edit', args=[row.pk]),
                         {'parameter': 'ph', 'deadband': '0.1', 'version': row.version})
        row.refresh_from_db()
        self.assertEqual(row.deadband, Decimal('0.1'))
        self.assertTrue(AuditLog.objects.filter(entity_type='alarm deadband', action='update').exists())

    def test_nobody_without_the_right_reads_them(self):
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(reverse('alarms:severitypolicy_list')).status_code, 403)
        self.assertEqual(self.client.get(reverse('alarms:parameterdeadband_list')).status_code, 403)

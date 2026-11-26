"""The independent cross review of the owner-settings alarms (docs/reviews/2026-11-owner-settings.md): each finding pinned
by the safe behaviour it asked for. A missed critical alarm can kill fish: every test here is a way one was missed."""
from datetime import timedelta

from farm.water import read as water_read, sources as water_sources

from . import AlarmsCase, farm_alarms


class Live:
    """A live provider of farm/water/sources.py whose values the test gives: {target: {code: [SensorValue]}}."""

    def __init__(self, values):
        self.values = values

    def latest(self, targets, now):
        return {target: found for target, found in self.values.items() if target in targets}

    def value_at(self, targets, code, moment):
        return {}

    def bound(self, targets, code, since, until):
        return set()


def sensor_value(code, number, at, fresh_for=60, channel_no=77):
    return water_sources.SensorValue(code, number, at, fresh_for, water_sources.PRIMARY, channel_no)


def open_levels(**filters):
    return sorted(alarm.severity for alarm in farm_alarms().filter(clearance__isnull=True, source='water_limit',
                                                                    **filters))


class CrossReviewCase(AlarmsCase):
    def live(self, values):
        provider = Live(values)
        water_sources.register(provider)
        self.addCleanup(water_sources.unregister, provider)
        return provider

    def live_ph(self, number, at, point=None):
        return self.live({(water_sources.POINT, (point or self.mid1).pk): {'ph': [sensor_value('ph', number, at)]}})


class ClockAheadTests(CrossReviewCase):
    """F1 (blocker): a value stamped ahead of the server's clock decides the card's status (the read layer counts it up to
    the ingest contract's hour, evaluate.MAX_AHEAD), so its alarm is raised as soon as the card shows it: the on-delay is
    counted from the value's time or the pass's, whichever is earlier, never from a moment still to come."""

    def test_a_value_four_minutes_fast_raises_its_critical_at_once(self):
        self.live_ph(5.5, self.now + timedelta(minutes=4))         # inside the read layer's clock tolerance: fresh
        card = water_read.unit_water([self.t1], self.now)[self.t1.pk]
        self.assertEqual(card.status, 'critical')
        self.loop()
        self.assertIn('critical', open_levels())

    def test_a_probe_twenty_minutes_fast_beside_a_good_value_raises_its_critical_at_once(self):
        self.sample(7.0, hours=0.1)                                 # a correct clock, fine
        self.live_ph(5.5, self.now + timedelta(minutes=20))         # beyond the tolerance, inside the contract's hour
        card = water_read.unit_water([self.t1], self.now)[self.t1.pk]
        self.assertEqual(card.status, 'critical')
        self.loop()
        self.assertIn('critical', open_levels())

    def test_the_warning_on_delay_runs_from_the_pass_not_from_the_future_stamp(self):
        self.live_ph(6.2, self.now + timedelta(minutes=20))         # a warning, 20 min fast; warning on-delay 30 s
        self.loop()
        self.assertEqual(open_levels(), [])
        self.loop(seconds=31)
        self.assertEqual(open_levels(), ['warning'])

    def test_a_fast_value_that_comes_back_clears_after_the_off_delay_counted_from_the_pass(self):
        probe = self.live_ph(5.5, self.now + timedelta(minutes=4))
        self.loop()
        self.assertEqual(open_levels(), ['critical'])               # the warning waits for its own on-delay
        probe.values = {(water_sources.POINT, self.mid1.pk): {'ph': [sensor_value(
            'ph', 7.0, self.now + timedelta(minutes=4, seconds=1))]}}    # back, the same probe 4 min fast
        self.loop(seconds=1)
        self.assertEqual(open_levels(), ['critical'])
        self.loop(seconds=32)                                       # the off-delay (30 s) from the pass that saw it
        self.assertEqual(open_levels(), [])


class DeadbandAcrossCandidatesTests(CrossReviewCase):
    """F2: a level clears only when EVERY fresh value of the unit's water is back inside its limit by the deadband (alarm
    plan §2.1), not only the value that decided it: a depth point 0.02 over the critical pH limit, inside pH's deadband
    (0.05), keeps the critical open beside a newer warning value of the middle point, so the next 5.98 never re-raises
    it (no chatter)."""

    def test_another_points_value_inside_the_deadband_keeps_the_level(self):
        from farm.models import SamplingPoint
        depth = SamplingPoint.objects.create(unit=self.t1, kind='depth', name='Bottom', depth_m=1)
        self.sample(5.5, hours=1, point=depth)
        self.loop()
        self.loop(seconds=31)
        self.assertEqual(open_levels(), ['critical', 'warning'])
        self.sample(6.02, hours=0.6, point=depth)          # back over 6 by less than the deadband
        self.sample(6.4, hours=0.5)                         # the middle point: a warning, newer
        self.loop(seconds=32)
        self.loop(seconds=80)
        self.assertEqual(open_levels(), ['critical', 'warning'])

    def test_every_value_clear_by_the_deadband_clears(self):
        from farm.models import SamplingPoint
        depth = SamplingPoint.objects.create(unit=self.t1, kind='depth', name='Bottom', depth_m=1)
        self.sample(5.5, hours=1, point=depth)
        self.loop()
        self.sample(6.2, hours=0.6, point=depth)           # clear of the critical limit by more than the deadband
        self.sample(6.4, hours=0.5)
        self.loop(seconds=1)
        self.loop(seconds=40)
        self.assertEqual(open_levels(), ['warning'])


def without_triggers(sql, params=()):
    """Runs `sql` as a restore or a hand edit would, past the tables' triggers (the test database's owner may)."""
    from django.db import connection
    with connection.cursor() as cursor:
        cursor.execute('SET session_replication_role = replica')
        try:
            cursor.execute(sql, params)
        finally:
            cursor.execute('SET session_replication_role = DEFAULT')


class MissingRuleTests(CrossReviewCase):
    """F6: a severity's rule row that is missing (a restore, a hand edit) never stops the evaluation: the pass uses the
    safest value of each field (no on-delay; the longest off-delay, shortest escalation and most delivery attempts of the
    rows there are, else their bounds), says so with a critical configuration alarm of the alarm system, and clears it
    once the row is back. The last live row of a severity cannot be deleted, by the model or the database."""

    def system_alarms(self):
        from ..read import is_open
        return {alarm.parameter: is_open(alarm) for alarm in farm_alarms().filter(source='system')}

    def test_a_missing_warning_rule_never_stops_the_critical(self):
        without_triggers("DELETE FROM alarm_severity_policies WHERE severity = 'warning'")
        self.sample(5.5, hours=0)
        summary = self.loop()
        self.assertEqual(summary.failed_steps, [])
        self.assertIn('critical', open_levels())
        self.assertEqual(self.system_alarms(), {'alarm_rules': True})
        self.assertEqual(farm_alarms().get(source='system').severity, 'critical')

    def test_a_missing_critical_rule_raises_the_critical_at_once(self):
        from ..models import SeverityPolicy
        SeverityPolicy.objects.filter(severity='warning').update(on_delay_seconds=600)
        without_triggers("DELETE FROM alarm_severity_policies WHERE severity = 'critical'")
        self.sample(5.5, hours=0)
        self.loop()
        self.assertIn('critical', open_levels())                   # no on-delay: never the warning's 600 s

    def test_the_configuration_alarm_clears_when_the_row_is_back(self):
        from ..models import SeverityPolicy
        row = SeverityPolicy.objects.get(severity='warning')
        self.sample(7.2)                        # T-01's water fine, its oxygen fresh: no other system alarm
        without_triggers("DELETE FROM alarm_severity_policies WHERE severity = 'warning'")
        self.loop()
        without_triggers('INSERT INTO alarm_severity_policies (id, severity, on_delay_seconds, off_delay_seconds, '
                         'escalation_minutes, delivery_attempts, clock_skew_seconds, clock_skew_deadband_seconds, '
                         'clock_behind_window_seconds, retry_seconds, shelve_max_minutes, flood_count, '
                         'flood_window_seconds, created_at, updated_at, version, is_deleted) VALUES (%s, %s, 30, 30, 30, '
                         '5, 60, 10, 600, 120, 720, 3, 120, now(), now(), 1, false)', [row.pk, 'warning'])
        self.loop(seconds=1)
        self.loop(minutes=2)
        self.assertEqual(self.system_alarms(), {'alarm_rules': False})

    def test_the_last_rule_of_a_severity_cannot_be_deleted(self):
        from django.core.exceptions import ValidationError
        from django.db import DatabaseError, transaction
        from ..models import SeverityPolicy
        row = SeverityPolicy.objects.get(severity='critical')
        with self.assertRaises(ValidationError):
            row.soft_delete(self.keeper)
        with self.assertRaises(DatabaseError), transaction.atomic():
            SeverityPolicy.all_objects.filter(pk=row.pk).update(is_deleted=True)
        with self.assertRaises(DatabaseError), transaction.atomic():
            SeverityPolicy.all_objects.filter(pk=row.pk).delete()
        self.assertTrue(SeverityPolicy.objects.filter(severity='critical').exists())


class FailedStepTests(CrossReviewCase):
    """F3: the alarm system supervises itself (EEMUA 191). A step of the pass that fails is a critical system alarm from
    the pass it fails in until it passes again; and the water step is isolated per unit, so one unit that cannot be
    evaluated raises that unit's own "could not be evaluated" alarm (on its site) and never silences the others."""

    def setUp(self):
        super().setUp()
        from farm.tests.helpers import point_of, stock_fish
        from farm.tests.test_stock import make_unit
        self.t2 = make_unit('T-02', self.hall, system=self.ras)
        stock_fish(self.keeper, self.t2, 1000, '50', 10, species=self.salmon)
        self.mid2 = point_of(self.t2)

    def system(self, **filters):
        return farm_alarms().filter(source='system', **filters)

    def test_a_step_that_fails_every_pass_is_a_critical_system_alarm_until_it_passes(self):
        from unittest import mock
        from .. import read, sources
        self.sample(5.5, hours=0)
        with mock.patch.object(sources, 'water', side_effect=RuntimeError('a bug')), \
                self.assertLogs('alarms.engine', level='ERROR'):
            self.loop()
            self.loop(minutes=1)
        alarm = self.system().get()
        self.assertEqual((alarm.severity, alarm.parameter), ('critical', 'step_failed'))
        self.assertIn('water', alarm.summary)
        self.loop(minutes=2)
        self.loop(minutes=3)
        self.assertFalse(read.is_open(alarm))
        self.assertIn('critical', open_levels())                   # the water's own alarm, once the step runs

    def test_one_unit_that_cannot_be_read_never_silences_the_others(self):
        from unittest import mock
        real = water_read.unit_water

        def unit_water(units, now=None):
            if any(unit.pk == self.t2.pk for unit in units):
                raise ValueError('a bad row of T-02')
            return real(units, now)
        self.sample(5.5, hours=0)
        self.sample(5.5, hours=0, point=self.mid2)
        with mock.patch.object(water_read, 'unit_water', side_effect=unit_water), \
                self.assertLogs('alarms.sources', level='ERROR'):
            summary = self.loop()
        self.assertEqual(summary.failed_steps, [])
        self.assertEqual(open_levels(point__unit=self.t1), ['critical'])
        alarm = self.system().get()
        self.assertEqual((alarm.severity, alarm.parameter, alarm.site, alarm.production_department),
                         ('critical', 'unit_unevaluated', self.bergen, self.hall))
        self.assertIn('T-02', alarm.summary)

    def test_one_unit_whose_evaluation_fails_never_silences_the_others(self):
        from unittest import mock
        from .. import read, sources
        real = sources._slots

        def slots(found):
            if found.point is not None and found.point.unit_id == self.t2.pk:
                raise ArithmeticError('a value nobody expected')
            return real(found)
        self.sample(5.5, hours=0)
        self.sample(5.5, hours=0, point=self.mid2)
        with mock.patch.object(sources, '_slots', side_effect=slots), self.assertLogs('alarms.sources', level='ERROR'):
            self.loop()
        self.assertEqual(open_levels(point__unit=self.t1), ['critical'])
        alarm = self.system().get()
        self.assertEqual(alarm.parameter, 'unit_unevaluated')
        self.loop(minutes=1)                                       # evaluated again: restored, its alarms raised
        self.loop(minutes=2)
        self.assertFalse(read.is_open(alarm))
        self.assertEqual(open_levels(point__unit=self.t2), ['critical', 'warning'])


class UnitKeyTests(CrossReviewCase):
    """F7: a water alarm's subject is the unit's parameter at a level (`water:unit:<unit>:<slot>:<severity>`), never the
    point that stood for the unit: replacing the middle point keeps the one alarm per level (no orphan, no duplicate); a
    unit removed ends its alarms (cause "unit removed")."""

    def replace_middle_point(self):
        from farm.health.withdrawal import guarded_units
        from farm.models import SamplingPoint
        guarded_units(self.keeper, [self.t1.pk], None,
                      lambda: SamplingPoint.objects.filter(pk=self.mid1.pk).update(is_active=False))
        return guarded_units(self.keeper, [self.t1.pk], None, lambda: SamplingPoint.objects.create(
            unit=self.t1, kind='middle', name='Middle 2'))

    def test_a_replaced_middle_point_keeps_one_alarm_per_level(self):
        from ..models import AlarmSubjectState
        self.sample(5.5, hours=1)
        self.loop()
        self.loop(seconds=31)
        new = self.replace_middle_point()
        self.sample(5.4, hours=0.5, point=new)
        self.loop(minutes=1)
        self.assertEqual(open_levels(), ['critical', 'warning'])
        self.assertEqual(sorted(AlarmSubjectState.objects.filter(key__startswith='water:', open_alarm__isnull=False)
                                .values_list('key', flat=True)),
                         [f'water:unit:{self.t1.pk}:ph:critical', f'water:unit:{self.t1.pk}:ph:warning'])

    def test_the_new_point_clears_what_the_old_one_raised(self):
        self.sample(5.5, hours=1)
        self.loop()
        new = self.replace_middle_point()
        self.sample(7.0, hours=0.5, point=new)
        self.loop(minutes=1)
        self.loop(minutes=2)
        self.assertEqual(open_levels(), [])

    def test_a_unit_removed_ends_its_alarms(self):
        from farm.models import Tank
        from ..models import AlarmClearance
        self.sample(5.5, hours=1)
        self.loop()
        Tank.objects.filter(pk=self.t1.pk).update(is_deleted=True)     # as a restore or a hand edit would leave it
        self.loop(minutes=1)
        self.assertEqual(open_levels(), [])
        self.assertEqual(set(AlarmClearance.objects.values_list('cause', flat=True)), {'unit_removed'})


class SystemRoutingTests(CrossReviewCase):
    """F8: a system alarm carries its site where one applies (a unit's), so that site's recipient rules reach it; a
    farm-wide one (the sensors cannot be read, a failed step, the rules) goes to the company-wide rules, and, where there
    is none, to every rule that reaches its severity: the alarm system's own alarm never reaches nobody."""

    def system_alarm(self, site=None):
        from .. import services
        return services.open_alarm(at=self.now, severity='critical', summary='The sensors cannot be read',
                                   source='system', parameter='sensors_failed', site=site, farm_wide=True)

    def people(self, alarm):
        from .. import routing
        return sorted(user.username for user, _rule in routing.recipients(alarm, 0, self.now))

    def test_a_farm_wide_system_alarm_reaches_the_site_rules_when_there_is_no_company_wide_one(self):
        self.rule(site=self.bergen)
        self.rule(site=self.oslo, role=None, user=self.manager)
        self.assertEqual(self.people(self.system_alarm()), ['manager', 'operator'])

    def test_a_farm_wide_system_alarm_goes_to_the_company_wide_rule_where_there_is_one(self):
        self.rule(site=self.bergen)
        self.rule(site=None, role=None, user=self.manager)
        self.assertEqual(self.people(self.system_alarm()), ['manager'])

    def test_a_system_alarm_of_a_site_reaches_that_sites_rules(self):
        self.rule(site=self.bergen)
        self.rule(site=self.oslo, role=None, user=self.manager)
        self.assertEqual(self.people(self.system_alarm(site=self.bergen)), ['operator'])

    def test_the_loop_notifies_the_sensors_failure_with_site_rules_only(self):
        from ..models import Notification
        from .test_defects import Unreadable
        self.rule(site=self.bergen)
        unreadable = Unreadable()
        water_sources.register(unreadable)
        self.addCleanup(water_sources.unregister, unreadable)
        with self.assertLogs('farm.water.sources', level='ERROR'):
            self.loop()
            self.loop(minutes=1)
        self.assertTrue(Notification.objects.filter(alarm__source='system', recipient=self.operator).exists())


class RuleBoundsTests(CrossReviewCase):
    """F9: the rules' bounds are the model's and the database's, per severity, not only the form's: a critical alarm is
    raised within the owner's 10 s target (alarm plan §2.4, §7a Q3: critical on-delay 0, "the 10 s rule wins over spike
    filtering"), so its on-delay is at most 10 s; a critical alarm unacknowledged goes up within 30 min; a deadband is at
    most its parameter's whole range. A value inside the bounds but unusual is shown with a warning, never refused."""
    ADMIN = ('view_severitypolicy', 'change_severitypolicy', 'view_parameterdeadband', 'add_parameterdeadband',
             'change_parameterdeadband', 'delete_parameterdeadband')

    def login(self):
        from django.contrib.auth import get_user_model
        from farm.tests.helpers import role
        admin = get_user_model().objects.create_user('alarmadmin', 'alarmadmin@example.com', 'x')
        admin.groups.add(role('Alarm admin', *self.ADMIN))
        self.client.force_login(admin)

    def test_the_database_refuses_unsafe_values_per_severity(self):
        from decimal import Decimal
        from django.db import IntegrityError, transaction
        from ..models import ParameterDeadband, SeverityPolicy
        for severity, values in (('critical', {'on_delay_seconds': 11}), ('critical', {'escalation_minutes': 31}),
                                 ('warning', {'on_delay_seconds': 901})):
            with self.subTest(severity=severity, values=values), self.assertRaises(IntegrityError), \
                    transaction.atomic():
                SeverityPolicy.objects.filter(severity=severity).update(**values)
        SeverityPolicy.objects.filter(severity='critical').update(on_delay_seconds=10, escalation_minutes=30)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ParameterDeadband.objects.filter(parameter='ph').update(deadband=Decimal('50'))

    def test_the_model_refuses_them_with_a_reason(self):
        from django.core.exceptions import ValidationError
        from ..models import SeverityPolicy
        policy = SeverityPolicy.objects.get(severity='critical')
        policy.on_delay_seconds, policy.escalation_minutes = 3600, 1440
        with self.assertRaises(ValidationError) as refused:
            policy.full_clean()
        self.assertEqual(set(refused.exception.message_dict), {'on_delay_seconds', 'escalation_minutes'})

    def test_the_form_refuses_a_critical_raised_after_an_hour(self):
        from ..forms import SeverityPolicyForm
        from ..models import SeverityPolicy
        form = SeverityPolicyForm({'on_delay_seconds': 3600, 'off_delay_seconds': 3600, 'escalation_minutes': 1440,
                                   'delivery_attempts': 1}, instance=SeverityPolicy.objects.get(severity='critical'))
        self.assertFalse(form.is_valid())
        self.assertIn('on_delay_seconds', form.errors)

    def test_an_unusual_value_is_shown_with_a_warning(self):
        from decimal import Decimal
        from django.urls import reverse
        from ..models import ParameterDeadband, SeverityPolicy
        self.login()
        SeverityPolicy.objects.filter(severity='critical').update(on_delay_seconds=5)
        page = self.client.get(reverse('alarms:severitypolicy_list'))
        self.assertContains(page, 'notice-warning')
        self.assertContains(page, 'Critical: raised 5 s after the value')
        ParameterDeadband.objects.filter(parameter='ph').update(deadband=Decimal('0.4'))   # the warning band is 0.5 wide
        page = self.client.get(reverse('alarms:parameterdeadband_list'))
        self.assertContains(page, 'notice-warning')

    def test_the_seeded_values_are_not_unusual(self):
        from django.urls import reverse
        self.login()
        self.assertNotContains(self.client.get(reverse('alarms:severitypolicy_list')), 'notice-warning')
        self.assertNotContains(self.client.get(reverse('alarms:parameterdeadband_list')), 'notice-warning')


class StructuralClearTests(CrossReviewCase):
    """F12: a limit deleted while its alarm is open is the easiest way to silence it, so the clearance says so: the cause
    "limit removed" (not "no fish"), and its log entry names the limit row deleted, who deleted it and when."""

    def test_a_deleted_limit_clears_with_its_cause_and_names_the_row_and_the_person(self):
        from core.models import AuditLog
        from farm.models import WaterLimit
        from ..models import AlarmClearance
        self.sample(5.5, hours=1)
        self.loop()
        limit = WaterLimit.objects.get(parameter='ph')
        limit.soft_delete(self.keeper)
        self.loop(seconds=1)
        self.assertEqual(open_levels(), [])
        self.assertEqual(set(AlarmClearance.objects.values_list('cause', flat=True)), {'limit_removed'})
        entry = AuditLog.objects.filter(entity_type='alarm', action='update').latest('id')
        said = ' '.join(str(value) for value in entry.changes.values())
        self.assertIn(str(limit.pk), said)
        self.assertIn('keeper', said)

    def test_an_emptied_unit_clears_with_no_fish(self):
        from farm.stock import services as stock_services
        from farm.tests.helpers import may_record
        from ..models import AlarmClearance
        self.sample(5.5, hours=1)
        self.loop()
        may_record(self.keeper, 'delete_stockoperation')     # the stock service asks (L-6)
        stock_services.void(self.keeper, stock_services.StockOperation.objects.get(), 'Wrong unit')
        self.loop(seconds=1)
        self.assertEqual(set(AlarmClearance.objects.values_list('cause', flat=True)), {'structural'})


class TextTests(CrossReviewCase):
    """F15: the escalation time moved from the Platform settings to each severity's rule: no text says otherwise."""

    def test_no_text_sends_the_escalation_time_to_the_platform_settings(self):
        import pathlib
        from django.conf import settings
        from ..forms import RecipientRuleForm
        self.assertNotIn('Platform settings', str(RecipientRuleForm._meta.help_texts['level']))
        access = (pathlib.Path(settings.BASE_DIR) / 'config' / 'access.py').read_text(encoding='utf-8')
        self.assertNotIn("the alarms' escalation time", access)


class UnwatchedUnitTests(CrossReviewCase):
    """F16, and review 2 of fresh-rule (R2, 2026-11-23): a unit with fish and no point to read its own water at (no middle
    point, no other own-water point) has no water alarm at all, and its oxygen has no fresh value: the alarm system's
    critical, on its site (it was a configuration warning, which no longer holds beside it), until a point gives a fresh
    oxygen."""

    def test_a_stocked_unit_without_a_point_is_critical_its_oxygen_unknown(self):
        from farm.health.withdrawal import guarded_units
        from farm.models import SamplingPoint
        from .. import read
        guarded_units(self.keeper, [self.t1.pk], None,             # every point of the unit (the outlet too)
                      lambda: SamplingPoint.objects.filter(unit=self.t1).update(is_active=False))
        self.loop()
        self.loop(seconds=31)
        alarm = farm_alarms().get(source='system', parameter='oxygen_mg_l')
        self.assertEqual((alarm.severity, alarm.site), ('critical', self.bergen))
        self.assertIn('T-01', alarm.summary)
        self.assertFalse(farm_alarms().filter(parameter='no_water_point').exists())
        guarded_units(self.keeper, [self.t1.pk], None,
                      lambda: SamplingPoint.objects.filter(pk=self.mid1.pk).update(is_active=True))
        self.sample(7.2)                                            # its pH and its oxygen, fresh
        self.loop(minutes=1)
        self.loop(minutes=2)
        self.assertFalse(read.is_open(alarm))

    def test_an_empty_unit_without_a_point_is_nothing(self):
        from farm.tests.test_stock import make_unit
        unit = make_unit('T-09', self.hall)
        from farm.health.withdrawal import guarded_units
        from farm.models import SamplingPoint
        guarded_units(self.keeper, [unit.pk], None,
                      lambda: SamplingPoint.objects.filter(unit=unit).update(is_active=False))
        self.loop()
        self.loop(seconds=31)
        self.assertFalse(farm_alarms().filter(parameter='no_water_point').exists())

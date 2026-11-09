"""The seven defects the alarm plan (scratchpad plan/alarms/PLAN.md §2.3) found in this app, each pinned by its tests."""
from farm.models import SamplingPoint
from farm.tests.helpers import point_of

from ..models import Alarm, AlarmClearance, Escalation, Notification, ParameterDeadband, SeverityPolicy
from . import AlarmsCase


class UnitSubjectTests(AlarmsCase):
    """Defect 1: the water's alarms are the units' (their middle point stands for them, A9.1), never every active point's:
    an inlet's value is the stream coming in, and a depth point's critical value already decides its unit (worst fresh
    value), so an alarm of its own would be the same danger twice."""

    def test_an_inlet_holds_no_alarm(self):
        self.sample(5.5, point=point_of(self.t1, 'inlet'))
        self.sample(7.0, hours=0.5)                          # the unit's own water is fine
        self.loop()
        self.assertFalse(Alarm.objects.exists())

    def test_a_depth_points_critical_value_is_its_units_one_alarm(self):
        depth = SamplingPoint.objects.create(unit=self.t1, kind='depth', name='Bottom', depth_m=1)
        self.sample(5.5, point=depth)
        self.sample(5.4, hours=0.5)                          # the middle point critical too: still one alarm
        self.loop()
        alarm = self.critical()                              # one critical alarm, at the unit's middle point
        self.assertEqual((alarm.point, alarm.parameter, alarm.severity), (self.mid1, 'ph', 'critical'))

    def test_a_loops_value_is_judged_for_the_units_fish_and_raises_the_units_alarm_only(self):
        self.sample(5.5, point=point_of(self.ras))
        self.loop()
        self.assertEqual(sorted((alarm.point.pk, alarm.severity) for alarm in Alarm.objects.all()),
                         [(self.mid1.pk, 'critical'), (self.mid1.pk, 'warning')])      # the unit's two levels, no loop's


class LevelTests(AlarmsCase):
    """Defect 2: a water alarm is a level of a unit's parameter, warning (L) and critical (LL) each with its own alarm, raised
    after the severity's on-delay counted in data time, cleared only past the parameter's deadband and after the
    off-delay: a severity change never clears and reopens, and a value at the limit does not chatter."""

    def open_levels(self):
        return sorted(alarm.severity for alarm in Alarm.objects.filter(clearance__isnull=True))

    def test_a_warning_waits_for_its_on_delay_counted_from_the_value(self):
        self.sample(6.2, hours=0)
        self.loop()
        self.assertEqual(self.open_levels(), [])
        self.loop(seconds=31)
        self.assertEqual(self.open_levels(), ['warning'])

    def test_a_critical_raises_at_once_beside_the_warning_and_nothing_clears(self):
        self.sample(6.2, hours=1)
        self.loop()
        self.sample(5.5, hours=0)
        self.loop(seconds=1)
        self.assertEqual(self.open_levels(), ['critical', 'warning'])
        self.assertFalse(AlarmClearance.objects.exists())

    def test_a_value_inside_the_deadband_never_clears(self):
        self.sample(5.5, hours=1)
        self.loop()
        self.sample(6.03, hours=0.5)                 # past the critical limit (6) by less than pH's deadband (0.05)
        self.loop(seconds=1)
        self.loop(minutes=5)
        self.assertEqual(self.open_levels(), ['critical', 'warning'])

    def test_a_clear_waits_for_the_off_delay(self):
        self.sample(5.5, hours=1)
        self.loop()
        self.sample(7.0, hours=0.5)
        self.loop(seconds=1)
        self.assertEqual(self.open_levels(), ['critical', 'warning'])
        self.loop(seconds=40)
        self.assertEqual(self.open_levels(), [])
        self.assertEqual({clearance.cause for clearance in AlarmClearance.objects.all()}, {'returned'})

    def test_the_users_rules_are_read_on_the_next_pass(self):
        SeverityPolicy.objects.filter(severity='warning').update(on_delay_seconds=0)
        ParameterDeadband.objects.filter(parameter='ph').update(deadband=0)
        self.sample(6.2, hours=0)
        self.loop()
        self.assertEqual(self.open_levels(), ['warning'])

    def test_a_warning_is_not_notified_while_its_critical_is_open(self):
        self.rule()
        self.sample(5.5)
        self.loop()
        self.assertEqual([notification.alarm.severity for notification in Notification.objects.all()], ['critical'])
        self.assertFalse(Escalation.objects.exists())

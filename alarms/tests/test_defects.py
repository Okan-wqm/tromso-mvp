"""The seven defects the alarm plan (scratchpad plan/alarms/PLAN.md §2.3) found in this app, each pinned by its tests."""
from farm.tests.helpers import point_of

from ..models import Alarm
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
        self.sample(5.5, point=point_of(self.t1, 'depth'))
        self.sample(5.4, hours=0.5)                          # the middle point critical too: still one alarm
        self.loop()
        alarm = Alarm.objects.get()
        self.assertEqual((alarm.point, alarm.parameter, alarm.severity), (self.mid1, 'ph', 'critical'))

    def test_a_loops_value_is_judged_for_the_units_fish_and_raises_the_units_alarm_only(self):
        self.sample(5.5, point=point_of(self.ras))
        self.loop()
        self.assertEqual([(alarm.point, alarm.severity) for alarm in Alarm.objects.all()], [(self.mid1, 'critical')])

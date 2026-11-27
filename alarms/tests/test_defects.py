"""The seven defects the alarm plan (scratchpad plan/alarms/PLAN.md §2.3) found in this app, each pinned by its tests."""
from datetime import timedelta
from unittest import mock

from django.db import IntegrityError, connection, transaction
from django.test.utils import CaptureQueriesContext

from farm.models import SamplingPoint
from farm.tests.helpers import point_of, stock_fish
from farm.tests.test_stock import make_unit
from farm.water import services as water, sources as water_sources
from sensors import alarms as sensor_alarms, bindings
from sensors.models import AlarmEvent, AlarmRule
from sensors.tests import make_channel, make_connection, make_device, make_format

from .. import engine, outbox, read, services, sources
from ..models import (AlarmClearance, AlarmSubjectState, Escalation, Notification, ParameterDeadband,
                      SeverityPolicy)
from . import AlarmsCase, farm_alarms


class UnitSubjectTests(AlarmsCase):
    """Defect 1: the water's alarms are the units' (their middle point stands for them, A9.1), never every active point's:
    an inlet's value is the stream coming in, and a depth point's critical value already decides its unit (worst fresh
    value), so an alarm of its own would be the same danger twice."""

    def test_an_inlet_holds_no_alarm(self):
        self.sample(5.5, point=point_of(self.t1, 'inlet'))
        self.sample(7.0, hours=0.5)                          # the unit's own water is fine
        self.loop()
        self.assertFalse(farm_alarms().exists())

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
        self.assertEqual(sorted((alarm.point.pk, alarm.severity) for alarm in farm_alarms().all()),
                         [(self.mid1.pk, 'critical'), (self.mid1.pk, 'warning')])      # the unit's two levels, no loop's


class LevelTests(AlarmsCase):
    """Defect 2: a water alarm is a level of a unit's parameter, warning (L) and critical (LL) each with its own alarm, raised
    after the severity's on-delay counted in data time, cleared only past the parameter's deadband and after the
    off-delay: a severity change never clears and reopens, and a value at the limit does not chatter."""

    def open_levels(self):
        return sorted(alarm.severity for alarm in farm_alarms().filter(clearance__isnull=True))

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


class Unreadable:
    """A live water source that cannot be read (a provider of farm/water/sources.py that raises)."""

    def latest(self, targets, now):
        raise ConnectionError('the sensors cannot be read')

    def value_at(self, targets, code, moment):
        raise ConnectionError('the sensors cannot be read')

    def bound(self, targets, code, since, until):
        raise ConnectionError('the sensors cannot be read')


class FailedSourceTests(AlarmsCase):
    """Defect 3: while the live sources cannot be read, nothing clears (a sample alone must not end an alarm a sensor
    raised), and the failure is an alarm of its own."""

    def setUp(self):
        super().setUp()
        self.sample(5.5, hours=1)
        self.loop()
        self.unreadable = Unreadable()

    def test_nothing_clears_and_the_failure_is_an_alarm_until_the_sensors_answer_again(self):
        self.sample(7.0, hours=0.5)
        water_sources.register(self.unreadable)
        try:
            with self.assertLogs('farm.water.sources', level='ERROR'):    # said, and kept out of the run's output
                self.loop(minutes=1)
                self.loop(minutes=5)
        finally:
            water_sources.unregister(self.unreadable)
        self.assertTrue(read.is_open(self.critical()))
        system = farm_alarms().get(source='system')
        self.assertEqual((system.parameter, system.severity, read.is_open(system)), ('sensors_failed', 'critical', True))
        self.loop(minutes=6)
        self.loop(minutes=7)
        self.assertFalse(read.is_open(self.critical()))
        self.assertEqual(AlarmClearance.objects.get(alarm=system).cause, 'restored')


class OlderEvidenceTests(AlarmsCase):
    """Defect 4: only a value taken after the last bad one clears an alarm: when the bad value goes (a sample voided, a
    probe taken out), an older value that is still fresh must not end it."""

    def test_a_value_older_than_the_last_bad_one_never_clears(self):
        self.sample(7.0, hours=6)
        bad = self.sample(5.5, hours=1)
        self.loop()
        water.void(self.keeper, bad, 'Taken in the wrong tank')        # the six-hour-old value is the newest again
        self.loop(minutes=1)
        self.loop(minutes=5)
        self.assertTrue(read.is_open(self.critical()))
        self.sample(7.0, hours=0)
        self.loop(minutes=6)
        self.loop(minutes=7)
        self.assertFalse(read.is_open(self.critical()))


class FailureIsolationTests(AlarmsCase):
    """Defect 5: one failing step never takes the others with it (each step is its own transaction, its failure logged and
    counted); the worker goes on after a pass that failed whole (alarms/tests/test_worker.py)."""

    def setUp(self):
        super().setUp()
        device = make_device(make_connection(), make_format(), self.bergen)
        flow = make_channel(device, 'flow_m3_h')
        rule = AlarmRule.objects.create(kind='low', severity='warning', channel=flow, threshold=10)
        bound = bindings.move(self.keeper, flow, self.now - timedelta(days=1), system=self.ras)
        AlarmEvent.objects.create(rule=rule, channel_no=flow.channel_no, opened_at=self.now, peak=4, binding=bound)

    def test_a_failing_water_step_leaves_the_sensor_alarms_done_and_is_said(self):
        with mock.patch.object(sensor_alarms, 'evaluate', return_value=(0, 0)), \
                mock.patch.object(sources, 'water', side_effect=RuntimeError('the water read failed')), \
                self.assertLogs('alarms.engine', level='ERROR') as logged:
            summary = self.loop()
        self.assertEqual(summary.failed_steps, ['water'])
        self.assertTrue(farm_alarms().filter(source='sensor_rule').exists())
        self.assertIn('the water read failed', '\n'.join(logged.output))
        self.assertIn('1 step failed: water', str(summary))



class OneOpenAlarmTests(AlarmsCase):
    """Defect 6: one open alarm per subject is the database's to hold, not only the code's: an alarm is the open alarm of
    one subject at most (a unique column), and a raise is a compare-and-set on the subject's row, so a second raise for a
    subject whose alarm is open (a second worker, a bug) writes nothing."""

    def setUp(self):
        super().setUp()
        self.sample(5.5)
        self.loop()
        self.alarm = self.critical()
        self.key = AlarmSubjectState.objects.get(open_alarm=self.alarm).key

    def test_an_alarm_is_open_for_one_subject_at_most(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            AlarmSubjectState.objects.create(key='water:another', open_alarm=self.alarm)

    def test_a_second_raise_for_an_open_subject_writes_nothing(self):
        with self.assertRaises(services.AlreadyOpen):
            services.raise_for(self.key, lambda: services.open_alarm(
                at=self.now, severity='critical', summary='twice', source='water_limit', point=self.mid1,
                parameter='ph', site=self.bergen, production_department=self.hall))
        self.assertEqual(farm_alarms().filter(severity='critical', source='water_limit').count(), 1)
        self.assertEqual(AlarmSubjectState.objects.get(key=self.key).open_alarm, self.alarm)


class BulkTests(AlarmsCase):
    """Defect 7: a pass's writes are set-based and its routing is resolved once per pass: its queries do not grow with the
    alarms it raises, the notifications it queues or the rules and people it reads (a burst of alarms at once costs what
    one costs)."""

    def setUp(self):
        super().setUp()
        for name in ('ann', 'bob', 'cy'):
            type(self.operator).objects.create_user(name, f'{name}@example.com', 'x').groups.add(self.operators)
        self.rule()
        self.rule(user=self.manager, on_shift_only=True)
        self.sample(7.2)                        # T-01's water, its oxygen fresh: it raises nothing in the burst

    def queries_of_a_burst(self, units):
        for number in range(units):
            unit = make_unit(f'B{units}-{number}', self.hall, system=self.ras)
            stock_fish(self.keeper, unit, 100, '50', 10, species=self.salmon)
            self.sample(5.5, point=point_of(unit))
        at = self.now + timedelta(minutes=units)
        with CaptureQueriesContext(connection) as queries:              # the pass; the sender's round after it sends one
            summary = engine.run_once(at)                               # message per notification, a call each
        outbox.send_due(at)
        self.assertEqual(summary.failed_steps, [])
        return len(queries), summary.opened

    def test_a_pass_costs_the_same_for_two_alarming_units_and_for_six(self):
        few, opened_few = self.queries_of_a_burst(2)
        many, opened_many = self.queries_of_a_burst(6)
        self.assertEqual((opened_few, opened_many), (4, 12))          # each unit's warning and critical levels
        self.assertEqual(few, many)

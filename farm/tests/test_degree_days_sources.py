"""Where a day's water temperature comes from when degree-days are added up, and the one way they are added up
(farm/water/degree_days.py; the architecture audit of 2026-11-26, H-2 and M-3, and the independent review of the first
round, REVIEW-1: never an earlier withdrawal end without a question).

- B-1: the lowest of everything measured in a tier (the unit's own probe days and samples together, only then its
  system's); a probe and samples that disagree are said; a probe day needs a channel with a range and a plausible mean.
- B-2: a probe day is a CLOSED day stored as a fact by the daily job; the readers never read the sensors' tables; a
  day a probe is still expected for is not closed yet (projected, "about", frees nobody); history only by a guarded
  backfill; a correction is void + new through the guard; an end the job would move earlier is floored.
- B-3: a reading holds until the channel's next stored row, good or not, at most an hour; 20 hours of the day must
  hold a good reading; late readings after a day is closed change nothing.
- B-4: the landing command dumps and compares the ends, and floors every end that would move earlier.
- M-1: the cap does not run out inside a gap and also takes the first day measured after it; an unread day is an
  error. M-2: the rules are the platform owner's settings, changed through the guard. M-3: the fast is bounded by the
  batch's presence, one search for the day it is complete. M-4: another clock and a 23-hour day.

Real sensor channels and readings (the sensors app's provider, asked through farm/water/sources.py by the closing
service), real water samples, the real withdrawal and fasting readers."""
import io
import os
import tempfile
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, transaction
from django.test.utils import CaptureQueriesContext

from core import platform
from core.models import PlatformSettings
from core.testing import FrozenClock
from farm import withdrawal_gate as gate
from sensors import bindings
from sensors.models import Binding
from sensors.provider import PROVIDER
from sensors.quality import DEVICE_BAD
from sensors.tests import make_channel, make_connection, make_device, make_format

from ..handling import fasting
from ..health import services as health_services, withdrawal
from ..models import (HandlingRule, ProbeDay, ProbeDayClosing, ProductionDepartment, Site, Species, System, Tank,
                      WaterMeasurement, WithdrawalFloor)
from ..models.handling import MAX_FASTING_HOURS
from ..models.site import zone_of
from ..stock.dates import start_of
from ..water import degree_days, services
from ..water.degree_days import BatchWater, Temperatures
from .helpers import going_on, may_record, point_of
from .test_health import HealthTestCase
from .test_stock import make_unit

D = Decimal
DAY = timedelta(days=1)


class SourcesCase(HealthTestCase):
    """T-01 of the fixtures (Bergen, UTC) with the 2,000 salmon stocked 10 days ago, and a temperature probe on its
    middle point: a heartbeat of 20 minutes, so a value is fresh for an hour and one reading an hour covers the day."""

    def setUp(self):
        super().setUp()
        may_record(self.user, 'add_binding', 'add_watermeasurement', 'delete_watermeasurement')
        self.connection, self.format = make_connection(), make_format()
        self.device = make_device(self.connection, self.format, self.bergen, code='PROBE-T1')
        self.probe = self.channel('TEMP')
        self.bind(self.probe, point_of(self.t1))

    def channel(self, code, device=None, **fields):
        return make_channel(device or self.device, 'temperature_c', code=code, **{'heartbeat_s': 1200, **fields})

    def zone(self):
        return zone_of(self.bergen)

    def bind(self, channel, place, days_ago=9):
        """The channel at a sampling point (or a system) from the start of that day."""
        at = datetime.combine(self.day(days_ago), time.min, tzinfo=self.zone())
        target = {'system': place} if isinstance(place, System) else {'point': place}
        return bindings.move(self.user, channel, at=at, **target)

    def readings(self, days_ago, value, hours=range(24), quality=0, channel=None, minute=0):
        """The probe's readings of that day, one in each hour given (stored as the ingest stores them)."""
        rows = [((channel or self.probe).channel_no,
                 datetime.combine(self.day(days_ago), time(hour, minute), tzinfo=self.zone()), float(value), quality)
                for hour in hours]
        with connection.cursor() as cursor:
            cursor.executemany('INSERT INTO sensors_reading (channel_no, ts, value, quality) VALUES (%s, %s, %s, %s)',
                               rows)

    def job(self, days_ago):
        """The daily job as it runs half an hour into the day after that one: it closes every day over by then."""
        now = datetime.combine(self.day(days_ago - 1), time(0, 30), tzinfo=self.zone())
        return services.close_probe_days(now=now)

    def probed(self, value, *days_ago):
        """The probe read `value` all day on each of those days."""
        for each in days_ago:
            self.readings(each, value)

    @gate.opened('test fixture: the species’ assumed temperature straight in the database')
    def assume(self, value):
        Species.objects.filter(pk=self.salmon.pk).update(withdrawal_temperature_c=None if value is None else D(value))

    def water(self, first=None):
        return BatchWater({self.batch.pk}, self.today, first)

    def measured(self, days_ago, batch=None):
        return self.water(self.day(days_ago)).measured((batch or self.batch).pk, self.day(days_ago))

    def row(self, days_ago, channel=None):
        return ProbeDay.objects.get(day=self.day(days_ago), channel_no=(channel or self.probe).channel_no,
                                    voided_at__isnull=True)


# ---- B-1: the lowest of a tier; a probe is not believed over lower evidence ---------------------------------------
class LowestOfTheTierTests(SourcesCase):
    def test_a_probe_above_the_days_sample_does_not_replace_it_and_the_disagreement_is_said(self):
        # 40 degree-days after a last day 6 days ago. The probe read 9 °C on each of the five days since (drifted, or
        # in air), the hand samples say 4 °C: the samples count, 20 by yesterday, 20 to go at 4 °C a day: 5 days.
        # (The probe alone would give 45 by yesterday and free the fish today.)
        self.probed('9', 5, 4, 3, 2, 1)
        for days_ago in range(1, 6):
            self.temperature(self.t1, days_ago, '4')
        self.job(5)
        self.job(1)
        self.treat(self.medicine(degree_days=40), 6, 6)
        [held] = self.held()
        self.assertEqual((held.until, held.estimated, held.remaining_degree_days), (self.day(-5), True, D(20)))
        self.assertEqual((held.accrual.days[degree_days.SAMPLES], held.accrual.days[degree_days.SENSOR]), (5, 0))
        self.assertEqual(len(held.accrual.differed), 5)
        self.assertIn('On 5 days', withdrawal.describe(held))
        self.assertIn('the probe’s daily mean and the water samples differed by more than 1.0 °C: the lower was '
                      'counted. Check the probe.', withdrawal.describe(held))

    def test_a_probe_below_the_sample_counts(self):
        self.probed('4', 2)
        self.temperature(self.t1, 2, '4.5')              # within the tolerance: not said
        self.job(2)
        found = self.measured(2)
        self.assertEqual((found.value, found.source, found.differs), (D('4.00'), degree_days.SENSOR, None))

    def test_the_systems_probe_never_beats_the_units_own_sample(self):
        # T-01 and T-02 in one system whose own probe (a warm sump) reads 9 °C; T-01 has a hand sample of 4 °C, T-02
        # nothing of its own: T-01 counts its own 4 °C, T-02 the system's 9 °C.
        system = System.objects.create(name='RAS 1', code='R1', site=self.bergen, production_department=self.hall)
        with gate.opened('test fixture: the units in their system'):
            Tank.all_objects.filter(pk__in=[self.t1.pk, self.t2.pk]).update(system=system)
        other = self.stock(self.t2, count=500)
        sump = self.channel('SUMP')
        self.bind(sump, system)
        self.readings(2, '9', channel=sump)
        self.temperature(self.t1, 2, '4')
        self.job(2)
        water = BatchWater({self.batch.pk, other.pk}, self.today, self.day(2))
        own, shared = water.measured(self.batch.pk, self.day(2)), water.measured(other.pk, self.day(2))
        self.assertEqual((own.value, own.source), (D(4), degree_days.SAMPLES))
        self.assertEqual((shared.value, shared.source), (D('9.00'), degree_days.SENSOR))

    def test_of_two_probes_the_lower_counts(self):
        drain = self.channel('DRAIN')
        self.bind(drain, point_of(self.t1, 'bottom_drain'))
        self.probed('5', 2)
        self.readings(2, '3', channel=drain)
        self.job(2)
        self.assertEqual(self.measured(2).value, D('3.00'))

    def test_a_channel_without_a_range_or_with_an_implausible_mean_is_not_a_probe_day(self):
        loose = self.channel('LOOSE', range_min=None, range_max=None)
        self.bind(loose, point_of(self.t1, 'bottom_drain'))
        self.readings(2, '3', channel=loose)
        self.probed('45', 2)                           # a good reading as stored, outside the water's -3 to 40 °C
        self.job(2)
        self.assertEqual({row.channel_no: (row.ranged, row.counts) for row in ProbeDay.objects.all()},
                         {self.probe.channel_no: (True, False), loose.channel_no: (False, False)})
        self.assertIsNone(self.measured(2))


# ---- B-2: a closed day is a stored fact --------------------------------------------------------------------------
class ClosedDayTests(SourcesCase):
    def test_nothing_counts_before_a_day_is_closed_and_the_tables_start_empty(self):
        self.probed('4', 5, 4, 3, 2, 1)
        self.assertEqual((ProbeDay.objects.count(), ProbeDayClosing.objects.count()), (0, 0))
        self.assertIsNone(self.measured(2))             # history is not read from the readings: only a backfill

    def test_the_job_closes_each_day_once_oldest_first_and_the_first_run_only_yesterday(self):
        self.probed('4', 5, 4, 3, 2, 1)
        rows, closings, floors = self.job(3)
        self.assertEqual(([row.day for row in rows], [each.day for each in closings], floors),
                         ([self.day(3)], [self.day(3)], []))
        rows, closings, _floors = self.job(1)
        self.assertEqual([each.day for each in closings], [self.day(2), self.day(1)])
        self.assertEqual(self.job(1), ([], [], []))
        row = self.row(2)
        self.assertEqual((row.mean_c, row.covered_seconds, row.hours, row.readings, row.counts, row.how,
                          row.hours_needed, row.hold_seconds), (D('4.00'), 86400, 24, 24, True, 'closed', 20, 3600))

    def test_a_binding_deleted_after_the_day_was_closed_changes_nothing(self):
        # Assumed 10 °C; the probe measured 4 °C on five closed days. Deleting the binding and the readings must not
        # turn them into assumed days (50 by yesterday, free): they stay 20, 20 to go at 4 °C.
        self.assume('10.0')
        self.probed('4', 5, 4, 3, 2, 1)
        self.job(5)
        self.job(1)
        self.treat(self.medicine(degree_days=40), 6, 6)
        [before] = self.held()
        Binding.objects.filter(channel=self.probe).update(is_deleted=True)
        with connection.cursor() as cursor:
            cursor.execute('DELETE FROM sensors_reading WHERE channel_no = %s', [self.probe.channel_no])
        [after] = self.held()
        self.assertEqual((after.until, after.accrual.days[degree_days.SENSOR]), (before.until, 5))
        self.assertEqual(after.until, self.day(-5))

    def test_a_day_a_probe_is_still_expected_for_is_not_closed_yet_and_frees_nobody(self):
        # 18 degree-days; 4 °C on the four closed days (16); yesterday's readings are there but the day is not closed:
        # projected at 4 °C it reaches 18, but a projection frees nobody: not before tomorrow, "about".
        self.probed('4', 5, 4, 3, 2, 1)
        self.job(5)
        self.job(2)
        self.treat(self.medicine(degree_days=18), 6, 6)
        [held] = self.held()
        self.assertEqual((held.until, held.estimated, held.unclosed, held.worked_out, held.settled),
                         (self.day(-1), True, 1, self.today, self.today))
        self.assertEqual(held.accrual.days[degree_days.UNCLOSED], 1)
        text = withdrawal.describe(held)
        self.assertIn('Not before tomorrow: 1 sensor day is not closed yet, and the fish are held until it is.', text)
        self.assertIn('1 sensor day not closed yet', text)
        # The job closes it on the end that was shown: no floor, and the fish are free today.
        _rows, _closings, floors = self.job(1)
        self.assertEqual((floors, self.held()), ([], []))

    def test_a_sample_on_a_day_not_closed_yet_does_not_stand_in_for_the_probe(self):
        self.probed('4', 2)
        self.job(2)
        self.temperature(self.t1, 1, '12')
        counted = self.water(self.day(1)).day(self.batch.pk, self.day(1))
        self.assertEqual((counted.value, counted.how), (None, degree_days.UNCLOSED))

    def test_today_is_never_a_probe_day(self):
        self.probed('4', 1)
        self.job(1)
        self.readings(0, '4')
        counted = self.water(self.day(1)).day(self.batch.pk, self.today)
        self.assertEqual((counted.value, counted.how), (None, degree_days.PENDING))

    def test_a_reader_reads_no_table_of_the_sensors(self):
        self.probed('4', 3, 2, 1)
        self.job(3)
        self.job(1)
        self.treat(self.medicine(degree_days=40), 6, 6)
        with CaptureQueriesContext(connection) as queries:
            self.held()
        self.assertEqual([query['sql'] for query in queries if 'sensors_' in query['sql']], [])

    def test_the_probe_days_the_closings_and_the_floors_are_written_inside_the_guard_only(self):
        treatment = self.treat(self.medicine(degree_days=40), 6, 6)
        for write in (
                lambda: ProbeDay.objects.create(point=point_of(self.t1), day=self.day(2), channel_no=1, mean_c=D(4),
                                                covered_seconds=86400, hours=24, readings=24, ranged=True,
                                                hours_needed=20, hold_seconds=3600, counts=True, how='closed'),
                lambda: ProbeDayClosing.objects.create(timezone='UTC', day=self.day(2), hours_needed=20,
                                                       hold_seconds=3600, probe_days=0),
                lambda: WithdrawalFloor.objects.create(treatment=treatment, batch=self.batch, not_before=self.day(-9),
                                                       origin='landing', reason='x')):
            with self.assertRaises(gate.UnguardedWithdrawalWrite), transaction.atomic():
                write()

    def test_history_is_backfilled_only_through_the_guard_which_asks(self):
        # No assumed temperature, nothing measured: the 40 degree-days cannot be counted and the end is unknown. The
        # readings say 10 °C a day: backfilled they end the withdrawal yesterday. That frees fish held today: asked.
        self.probed('10', 5, 4, 3, 2, 1)
        self.treat(self.medicine(degree_days=40), 6, 6)
        self.assertIsNone(self.held()[0].until)
        ask = dict(units=[self.t1], first=self.day(5), last=self.day(1), reason='the probe was there all along')
        with self.assertRaises(withdrawal.WithdrawalChanged) as asked:
            services.backfill_probe_days(self.user, **ask)
        self.assertEqual([warning.warning for warning in asked.exception.change.warnings], ['released'])
        self.assertEqual(ProbeDay.objects.count(), 0)
        rows = going_on(services.backfill_probe_days, self.user, **ask)
        self.assertEqual([(row.how, row.counts, row.created_by, row.note) for row in rows],
                         [('backfilled', True, self.user, 'the probe was there all along')] * 5)
        self.assertEqual(self.held(), [])
        self.assertEqual(ProbeDayClosing.objects.count(), 0)          # a backfill closes no day
        with self.assertRaises(ValidationError):                       # today is not over
            services.backfill_probe_days(self.user, units=[self.t1], first=self.day(1), last=self.today, reason='x')

    def test_late_readings_change_nothing_and_a_correction_is_void_and_new_through_the_guard(self):
        self.readings(3, '4', hours=range(22))
        self.job(3)
        row = self.row(3)
        self.assertEqual((row.mean_c, row.hours, row.counts), (D('4.00'), 22, True))
        self.readings(3, '28', hours=[22, 23])                         # a logger empties its buffer days later
        self.assertEqual(self.measured(3).value, D('4.00'))
        self.assertEqual(self.job(1)[0], [])                           # the day is closed: not written again
        made = going_on(services.correct_probe_day, self.user, row, 'the late readings belong to the day')
        row.refresh_from_db()
        self.assertEqual((row.voided_by, row.void_reason, made.how, made.mean_c, made.created_by),
                         (self.user, 'the late readings belong to the day', 'corrected', D('6.00'), self.user))
        self.assertEqual(self.measured(3).value, D('6.00'))            # (22 x 4 + 2 x 28) / 24

    def test_a_closed_day_that_would_move_an_end_earlier_is_floored_and_the_floor_is_lifted_through_the_guard(self):
        # 30 degree-days; 4 °C on four closed days (16); yesterday not closed, projected at 4 °C with today and the two
        # days after: about 3 days from now. Yesterday really was 10 °C: closed, the end would be tomorrow. Nobody is
        # there to be asked, so the end that was shown stays as a floor.
        self.probed('4', 5, 4, 3, 2)
        self.probed('10', 1)
        self.job(5)
        self.job(2)
        treatment = self.treat(self.medicine(degree_days=30), 6, 6)
        self.assertEqual(self.held()[0].settled, self.day(-3))
        _rows, _closings, [floor] = self.job(1)
        self.assertEqual((floor.treatment, floor.batch, floor.not_before, floor.origin, floor.created_by),
                         (treatment, self.batch, self.day(-3), 'closing', None))
        [held] = self.held()
        self.assertEqual((held.until, held.worked_out, held.floor), (self.day(-3), self.day(-1), floor))
        self.assertIn('by a floor', withdrawal.describe(held))
        with self.assertRaises(withdrawal.WithdrawalChanged) as asked:
            health_services.lift_floor(self.user, floor, 'the vet read the probe')
        self.assertEqual([warning.warning for warning in asked.exception.change.warnings], ['released'])
        going_on(health_services.lift_floor, self.user, floor, 'the vet read the probe')
        floor.refresh_from_db()
        self.assertEqual((floor.lifted_by, floor.lift_reason), (self.user, 'the vet read the probe'))
        self.assertEqual(self.held()[0].until, self.day(-1))

    def test_the_job_writes_nothing_when_the_sensors_cannot_be_read(self):
        self.probed('4', 1)
        with mock.patch.object(PROVIDER, 'covered', side_effect=RuntimeError('down')), \
                self.assertRaises(services.SensorsUnread):
            self.job(1)
        self.assertEqual((ProbeDay.objects.count(), ProbeDayClosing.objects.count()), (0, 0))


# ---- B-3: what a reading covers -----------------------------------------------------------------------------------
class CoverageTests(SourcesCase):
    def test_a_dead_probe_does_not_keep_measuring(self):
        # A heartbeat of 8 hours: the value shows as fresh for a day. One reading at midnight, then nothing: it stands
        # for an hour, not for the day, and not for the day after.
        slow = self.channel('SLOW', heartbeat_s=28800)
        self.bind(slow, point_of(self.t1, 'bottom_drain'))
        self.readings(3, '12', hours=[0], channel=slow)
        self.job(3)
        self.job(2)
        row = self.row(3, slow)
        self.assertEqual((row.covered_seconds, row.hours, row.counts), (3600, 1, False))
        self.assertFalse(ProbeDay.objects.filter(day=self.day(2)).exists())
        self.assertIsNone(self.measured(3))

    def test_a_bad_row_ends_the_hold_of_the_good_one_before_it(self):
        self.readings(3, '12', hours=[0])
        self.readings(3, '12', hours=[0], minute=10, quality=DEVICE_BAD)
        self.job(3)
        self.assertEqual(self.row(3).covered_seconds, 600)

    def test_twenty_hours_of_the_day_must_hold_a_good_reading(self):
        self.readings(3, '4', hours=range(19))
        self.readings(2, '4', hours=range(20))
        self.job(3)
        self.job(2)
        self.assertEqual([(row.day, row.hours, row.counts) for row in ProbeDay.objects.order_by('day')],
                         [(self.day(3), 19, False), (self.day(2), 20, True)])

    def test_the_mean_is_weighted_by_time(self):
        self.readings(3, '2', hours=range(18))
        self.readings(3, '10', hours=[18, 19])
        self.readings(3, '99', hours=[19], minute=30, quality=DEVICE_BAD)      # ends the last hold after half an hour
        self.job(3)
        row = self.row(3)                                # (18 x 2 + 1.5 x 10) / 19.5
        self.assertEqual((row.mean_c, row.covered_seconds, row.hours), (D('2.61'), 70200, 20))

    def test_readings_before_the_binding_began_are_not_the_places(self):
        other = self.channel('MOVED')
        self.readings(3, '4', channel=other)             # the probe hung elsewhere until noon
        bindings.move(self.user, other, point=point_of(self.t1, 'bottom_drain'),
                      at=datetime.combine(self.day(3), time(12), tzinfo=self.zone()))
        self.job(3)
        row = self.row(3, other)
        self.assertEqual((row.covered_seconds, row.hours, row.counts), (43200, 12, False))


# ---- M-4: another clock, and a day of 23 hours ---------------------------------------------------------------------
class OsloClockTests(FrozenClock, SourcesCase):
    """A unit in Oslo around the night the clocks go forward (29 March 2026: the day has 23 hours, from 23:00 UTC on
    the 28th to 22:00 UTC on the 29th)."""
    NOW = datetime(2026, 4, 2, 10, 0, tzinfo=UTC)

    def setUp(self):
        super().setUp()
        oslo = Site.objects.create(name='Oslo', code='OS', timezone='Europe/Oslo')
        self.o1 = make_unit('O-01', ProductionDepartment.objects.create(site=oslo, name='Hall O', code='HO'))
        self.fish = self.stock(self.o1, count=500)
        self.oslo_probe = self.channel('OSLO', device=make_device(self.connection, self.format, oslo, code='PROBE-O1'))
        bindings.move(self.user, self.oslo_probe, point=point_of(self.o1),
                      at=datetime(2026, 3, 25, 0, 0, tzinfo=UTC))

    def test_a_probe_day_is_the_places_local_day(self):
        first = datetime(2026, 3, 28, 23, 0, tzinfo=UTC)                 # 00:00 in Oslo on the 29th
        rows = [(self.oslo_probe.channel_no, first + timedelta(hours=hour), 4.0 if 0 <= hour < 23 else 30.0, 0)
                for hour in range(-2, 25)]                              # two hours of the 28th, two of the 30th
        with connection.cursor() as cursor:
            cursor.executemany('INSERT INTO sensors_reading (channel_no, ts, value, quality) VALUES (%s, %s, %s, %s)',
                               rows)
        services.close_probe_days(now=datetime(2026, 3, 30, 3, 0, tzinfo=UTC))
        day = date(2026, 3, 29)
        row = ProbeDay.objects.get(day=day, channel_no=self.oslo_probe.channel_no)
        self.assertEqual((row.mean_c, row.covered_seconds, row.hours, row.counts), (D('4.00'), 23 * 3600, 23, True))
        self.assertEqual(ProbeDayClosing.objects.get(timezone='Europe/Oslo').day, day)
        found = BatchWater({self.fish.pk}, date(2026, 4, 2), day).temperatures.of(self.o1.pk, day)
        self.assertEqual((found.value, found.source), (D('4.00'), degree_days.SENSOR))


# ---- M-1: the cap ---------------------------------------------------------------------------------------------------
class CapTests(SourcesCase):
    def test_an_assumption_above_the_water_is_capped_and_the_cap_does_not_run_out_inside_the_gap(self):
        # Assumed 10 °C; 3 °C measured the day the fish came, 10 days ago, and nothing since: nine days without a
        # measurement, all nine at 3 °C (27), not seven at 3 °C and two at 10 °C (41).
        self.assume('10.0')
        self.temperature(self.t1, 10, '3')
        self.treat(self.medicine(degree_days=27), 10, 10)
        self.assertEqual(self.held(), [])
        [held] = self.held(day=self.day(1))
        self.assertEqual((held.until, held.accrual.days[degree_days.CAPPED], held.accrual.days[degree_days.ASSUMED]),
                         (self.today, 9, 0))
        self.assertIn('9 days without a measured water temperature are counted below the species’ assumed '
                      'temperature: at the coldest daily mean measured in the 7 days before their gap began, or the '
                      'first day measured after it when that is colder.', withdrawal.describe(held))

    def test_the_first_day_measured_after_the_gap_caps_it_too(self):
        self.assume('8.0')
        self.temperature(self.t1, 1, '2')
        counted = self.water(self.day(5)).day(self.batch.pk, self.day(3))
        self.assertEqual((counted.value, counted.how), (D(2), degree_days.CAPPED))

    def test_the_cap_is_the_coldest_of_the_days_before_the_gap_began(self):
        self.assume('8.0')
        self.temperature(self.t1, 9, '5')
        self.temperature(self.t1, 8, '7')
        counted = self.water(self.day(5)).day(self.batch.pk, self.day(3))
        self.assertEqual((counted.value, counted.how), (D(5), degree_days.CAPPED))
        with gate.opened('test fixture: the cap reads one day'):
            PlatformSettings.objects.update(assumption_cap_days=1)
        platform.forget()
        counted = self.water(self.day(5)).day(self.batch.pk, self.day(3))
        self.assertEqual((counted.value, counted.how), (D(7), degree_days.CAPPED))

    def test_a_day_that_was_not_read_is_an_error_not_an_unmeasured_day(self):
        temperatures = Temperatures([self.t1], self.day(5), self.today, D(1))
        self.assertIsNone(temperatures.of(self.t1.pk, self.day(5)))
        for day in (self.day(6), self.day(-1)):
            with self.assertRaises(LookupError):
                temperatures.of(self.t1.pk, day)


class FreezingTests(SourcesCase):
    def test_a_daily_mean_of_zero_or_below_adds_nothing(self):
        self.temperature(self.t1, 5, '10')
        self.temperature(self.t1, 4, '-2')
        self.temperature(self.t1, 3, '10')
        self.treat(self.medicine(degree_days=20), 6, 6)
        self.assertEqual(self.held(), [])
        [held] = self.held(day=self.day(3))
        self.assertEqual((held.until, held.estimated), (self.day(2), False))

    def test_a_projection_at_or_below_zero_adds_nothing(self):
        for days_ago in (3, 2, 1):
            self.temperature(self.t1, days_ago, '-1')
        accrual = self.water(self.day(3)).accrue(self.batch.pk, self.day(3), self.day(-2))
        self.assertEqual((accrual.total, accrual.days[degree_days.SAMPLES], accrual.projected), (D(0), 3, 3))


# ---- M-2: the rules are settings, changed through the guard --------------------------------------------------------
class SettingsTests(SourcesCase):
    def test_a_probe_day_is_closed_with_the_hours_and_the_hold_of_the_settings_and_keeps_them(self):
        with gate.opened('test fixture: the settings straight in the database'):
            PlatformSettings.objects.update(sensor_day_hours=12, sensor_hold_seconds=600)
        platform.forget()
        for minute in (0, 10, 20, 30, 40, 50):
            self.readings(2, '4', hours=range(12), minute=minute)
        self.job(2)
        row = self.row(2)
        self.assertEqual((row.hours, row.covered_seconds, row.hours_needed, row.hold_seconds, row.counts),
                         (12, 43200, 12, 600, True))
        with gate.opened('test fixture: the settings straight in the database'):
            PlatformSettings.objects.update(sensor_day_hours=20)
        platform.forget()
        self.assertEqual(self.measured(2).value, D('4.00'))            # a closed day keeps what it was closed with

    def test_the_rules_are_changed_only_through_the_guard_which_asks_when_fish_would_be_freed(self):
        # Assumed 8 °C; 3 °C ten days ago, 9 °C nine days ago, nothing since. With the cap's 7 days the eight days
        # without a measurement count 3 °C (24); with 1 day they would count the assumed 8 °C (64): 40 degree-days
        # would be over.
        self.assume('8.0')
        self.temperature(self.t1, 10, '3')
        self.temperature(self.t1, 9, '9')
        self.treat(self.medicine(degree_days=40), 9, 9)
        self.assertEqual(len(self.held()), 1)
        for field, value in (('sensor_day_hours', 12), ('sensor_hold_seconds', 60), ('assumption_cap_days', 1)):
            with self.subTest(field=field), self.assertRaises(gate.UnguardedWithdrawalWrite), transaction.atomic():
                PlatformSettings.objects.update(**{field: value})

        def write():
            PlatformSettings.objects.update(assumption_cap_days=1)
            platform.forget()

        with self.assertRaises(withdrawal.WithdrawalChanged) as asked:
            withdrawal.guarded_ceiling(self.user, write)
        platform.forget()
        self.assertEqual([warning.warning for warning in asked.exception.change.warnings], ['released'])
        self.assertEqual(PlatformSettings.get().assumption_cap_days, 7)


# ---- B-4: the landing ------------------------------------------------------------------------------------------------
class LandingTests(SourcesCase):
    def run_command(self, *args):
        out = io.StringIO()
        call_command('withdrawal_ends', *args, stdout=out)
        return out.getvalue()

    def test_an_end_that_would_move_earlier_stops_the_landing_or_is_floored(self):
        for days_ago in range(1, 6):
            self.temperature(self.t1, days_ago, '4')
        treatment = self.treat(self.medicine(degree_days=40), 6, 6)
        [before] = self.held()
        self.assertEqual(before.until, self.day(-5))
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'before.json')
            self.assertIn('1 withdrawals and 0 fasts written', self.run_command('dump', '--out', path))
            self.assertIn('1 withdrawals compared: 0 would end earlier', self.run_command('compare', path))
            # The rule changes (here: the same days read twice as warm, behind the guard, as a change of code is).
            with gate.opened('test fixture: what a change of the rule does to the days'):
                WaterMeasurement.objects.update(temperature_c=D(8))
            self.assertEqual(self.held(), [])                            # 40 by yesterday: free, and nobody was asked
            with self.assertRaises(CommandError):
                self.run_command('compare', path)
            self.assertEqual(WithdrawalFloor.objects.count(), 0)
            said = self.run_command('compare', path, '--floor', '--reason', 'The rule of 26.11.2026.')
        self.assertIn('EARLIER\tT-01', said)
        self.assertIn('1 floors set', said)
        [floor] = WithdrawalFloor.objects.all()
        self.assertEqual((floor.treatment, floor.batch, floor.not_before, floor.origin, floor.reason),
                         (treatment, self.batch, self.day(-5), 'landing', 'The rule of 26.11.2026.'))
        [held] = self.held()
        self.assertEqual((held.until, held.worked_out), (self.day(-5), self.today))
        out = io.StringIO()
        call_command('withdrawal_floors', 'list', stdout=out)
        self.assertIn(f'not before {self.day(-5).isoformat()}', out.getvalue())


# ---- M-3: the fast is bounded by the batch's presence; one search ---------------------------------------------------
class FastTests(SourcesCase):
    def requirement(self, degrees, hours=None):
        return fasting.Requirement.of(HandlingRule(kind='harvest', min_fasting_degree_days=D(degrees),
                                                   min_fasting_hours=hours))

    def fed(self, days_ago, at=time(18)):
        moment = datetime.combine(self.day(days_ago), at, tzinfo=self.zone())
        return SimpleNamespace(moment=moment, record=SimpleNamespace(date=self.day(days_ago)))

    def test_a_purge_the_water_has_not_reached_since_the_fish_came_starts_the_day_they_came(self):
        # 1 °C on each of the nine days since the fish came 10 days ago: 60 degree-days are not reached; the fast is
        # looked for back to the day they came, not 60 days back.
        for days_ago in range(1, 10):
            self.temperature(self.t1, days_ago, '1')
        start = fasting.start_of_fast(self.t1, self.today, self.requirement(60), self.water(), self.batch.pk)
        self.assertEqual((start.starts_at, start.unreached, sum(start.accrual.days.values())),
                         (start_of(self.day(10), self.t1), True, 10))

    def test_the_day_a_fast_is_complete_is_the_first_day_fasted_says_ok(self):
        for days_ago in range(1, 8):
            self.temperature(self.t1, days_ago, '3')
        water, fed = self.water(), self.fed(5)
        for degrees, hours in ((9, None), (12, None), (13, 72), (20, 200), (300, None)):
            requirement = self.requirement(degrees, hours)
            day = self.day(5)
            while not fasting.fasted(self.t1, day, fed, requirement, water, [self.batch.pk]).ok:
                day += DAY                                              # the search the walk replaces
            with self.subTest(degrees=degrees, hours=hours):
                self.assertEqual(fasting.complete_on(self.t1, fed, requirement, water, [self.batch.pk]), day)
        # 300 degree-days at 3 °C is far beyond the 60 days the old search gave up after: found all the same.
        self.assertGreater(day, self.today + 60 * DAY)

    def test_a_rule_in_degree_days_looks_for_the_last_feeding_without_a_bound(self):
        self.assertIsNone(fasting.fed_since(self.requirement(60), self.today))
        hours = fasting.Requirement.of(HandlingRule(kind='transport', min_fasting_hours=24))
        self.assertEqual(fasting.fed_since(hours, self.today), self.today - fasting.LOOKBACK_DAYS * DAY)
        self.assertEqual(fasting.LOOKBACK_DAYS, MAX_FASTING_HOURS // 24 + 1)
        self.assertFalse(hasattr(fasting, 'MAX_FAST_DAYS'))


class OneAccrualTests(SourcesCase):
    """The same water, every source in it: 6 days ago a probe day at 5 °C, 5 days ago a sample of 6 °C, 4 days ago
    nothing (assumed 8 °C, capped by the first day measured after it, which was below zero: it adds 0), 3 days ago a
    sample of −2 °C (adds 0), 2 days ago and yesterday probe days at 4 °C: 19 degree-days. The days are closed by the
    job; the three without a reading have no row: closed without a probe."""

    def setUp(self):
        super().setUp()
        self.assume('8.0')
        self.probed('5', 6)
        self.probed('4', 2, 1)
        self.job(6)
        self.job(1)
        self.temperature(self.t1, 5, '6')
        self.temperature(self.t1, 3, '-2')
        self.first = self.day(6)
        self.counted = {degree_days.SENSOR: 3, degree_days.SAMPLES: 2, degree_days.CAPPED: 1}

    def days(self, accrual):
        return {how: count for how, count in accrual.days.items() if count}

    def test_the_reader_adds_the_days_up(self):
        accrual = self.water(self.first).accrue(self.batch.pk, self.first, self.day(1))
        self.assertEqual((accrual.total, self.days(accrual), accrual.missing), (D(19), self.counted, 1))

    def test_the_withdrawal_ends_where_the_reader_reaches_it(self):
        self.treat(self.medicine(degree_days=19), 7, 7)
        self.assertEqual(self.held(), [])                       # 19 reached yesterday: free today
        [held] = self.held(day=self.day(1))
        self.assertEqual((held.until, held.estimated), (self.today, False))
        self.assertEqual(self.days(held.accrual), self.counted)

    def test_the_fast_counts_the_same_days(self):
        water = self.water()
        fed = SimpleNamespace(moment=start_of(self.day(7), self.t1), record=SimpleNamespace(date=self.day(7)))
        requirement = fasting.Requirement.of(HandlingRule(kind='harvest', min_fasting_degree_days=D(19)))
        done = fasting.fasted(self.t1, self.today, fed, requirement, water, [self.batch.pk])
        self.assertEqual((done.degree_days, done.ok, self.days(done.accrual)), (D('19.0'), True, self.counted))
        start = fasting.start_of_fast(self.t1, self.today, requirement, water, self.batch.pk)
        self.assertEqual((start.starts_at, start.unreached, self.days(start.accrual)),
                         (start_of(self.first, self.t1), False, self.counted))
        self.assertEqual(fasting.complete_on(self.t1, fed, requirement, water, [self.batch.pk]), self.today)
        self.assertIn('Days counted: 3 days measured by the sensors, 2 days from water samples, 1 day without a '
                      'measurement.', degree_days.accrual_text(start.accrual))

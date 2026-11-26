"""Where a day's water temperature comes from when degree-days are added up, and the one way they are added up
(farm/water/degree_days.py, the architecture audit of 2026-11-26, H-2 and M-3; the coordinator's decision, safe side):

1. a day with at least 20 h of fresh, good readings of a temperature probe at the unit (else its system's) counts at
   their time-weighted mean;
2. else at the mean of that day's water samples;
3. else at the species' assumed temperature, but never above the coldest daily mean measured in the 7 days before it.

A daily mean of 0 °C or below adds nothing, never subtracts. The medicine withdrawal, the purging fast and the
degree-day reader itself add the same days up to the same sum, and each says how many days came from which source.

Real sensor channels and readings (the sensors app's provider, read through farm/water/sources.py), real water
samples, the real withdrawal and fasting readers."""
from datetime import datetime, time
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.db import connection

from farm import withdrawal_gate
from sensors import bindings
from sensors.provider import PROVIDER
from sensors.quality import OUT_OF_RANGE
from sensors.tests import make_channel, make_connection, make_device, make_format

from ..handling import fasting
from ..health import withdrawal
from ..models import HandlingRule, Species
from ..models.handling import MAX_FASTING_HOURS
from ..models.site import zone_of
from ..stock.dates import start_of
from ..water import degree_days
from ..water.degree_days import BatchWater
from .helpers import may_record, point_of
from .test_health import HealthTestCase

D = Decimal


class SourcesCase(HealthTestCase):
    """T-01 of the fixtures (Bergen, UTC) with the 2,000 salmon stocked 10 days ago, and a temperature probe that can be
    bound to its middle point: a heartbeat of an hour, so a value stays fresh for 3 h."""

    def setUp(self):
        super().setUp()
        may_record(self.user, 'add_binding')
        device = make_device(make_connection(), make_format(), self.bergen, code='PROBE-T1')
        self.probe = make_channel(device, 'temperature_c', code='TEMP', heartbeat_s=3600)

    def zone(self):
        return zone_of(self.bergen)

    def bind(self, days_ago):
        """The probe on T-01's middle point from the start of that day."""
        at = datetime.combine(self.day(days_ago), time.min, tzinfo=self.zone())
        bindings.move(self.user, self.probe, point=point_of(self.t1), at=at)

    def readings(self, days_ago, value, hours=range(24), quality=0):
        """The probe's readings of that day, one at the start of each hour given (stored as the ingest stores them)."""
        rows = [(self.probe.channel_no, datetime.combine(self.day(days_ago), time(hour), tzinfo=self.zone()),
                 float(value), quality) for hour in hours]
        with connection.cursor() as cursor:
            cursor.executemany('INSERT INTO sensors_reading (channel_no, ts, value, quality) VALUES (%s, %s, %s, %s)',
                               rows)

    @withdrawal_gate.opened('test fixture: withdrawal inputs written straight in the database')
    def assume(self, value):
        Species.objects.filter(pk=self.salmon.pk).update(withdrawal_temperature_c=None if value is None else D(value))

    def water(self, first):
        return BatchWater({self.batch.pk}, self.today, first)


class SensorDayTests(SourcesCase):
    def test_a_unit_with_a_probe_and_few_hand_samples_counts_the_probes_daily_mean(self):
        # 40 degree-days after a last day 6 days ago. The probe read 4 °C all day on each of the five days since; one
        # hand sample of 10 °C three days ago. The probe's days count: 20 by yesterday, 20 to go at 4 °C a day is 5
        # days, today to 4 days ahead, so about 5 days from now. (The samples alone gave 10 by yesterday and 3 days.)
        self.bind(7)
        for days_ago in range(1, 6):
            self.readings(days_ago, '4')
        self.temperature(self.t1, 3, '10')
        self.treat(self.medicine(degree_days=40), 6, 6)
        [held] = self.held()
        self.assertEqual((held.until, held.estimated, held.remaining_degree_days, held.days_without_temperature),
                         (self.day(-5), True, D(20), 0))
        self.assertEqual(held.accrual.days[degree_days.SENSOR], 5)
        self.assertEqual(held.accrual.days[degree_days.SAMPLES], 0)
        self.assertIn('Days counted: 5 days measured by the sensors, 5 days projected.', withdrawal.describe(held))

    def test_the_daily_mean_is_weighted_by_time(self):
        # 2 °C every hour from midnight to 17:00 (18 readings, each held to the next), then one reading of 10 °C at
        # 18:00, held for its fresh 3 h to 21:00: 21 h covered, (18 × 2 + 3 × 10) / 21 = 3.14 °C by time (the plain
        # mean of the 19 rows would be 2.42).
        self.bind(3)
        self.readings(2, '2', hours=range(18))
        self.readings(2, '10', hours=[18])
        found = self.water(self.day(2)).measured(self.batch.pk, self.day(2))
        self.assertEqual((found.value, found.source), (D('3.14'), degree_days.SENSOR))     # 66 / 21, rounded down

    def test_a_day_with_less_than_20_hours_of_readings_falls_back_to_the_samples(self):
        self.bind(3)
        self.readings(2, '4', hours=range(16))          # 16 readings, the last fresh to 18:00: 18 h
        self.temperature(self.t1, 2, '9')
        found = self.water(self.day(2)).measured(self.batch.pk, self.day(2))
        self.assertEqual((found.value, found.source), (D(9), degree_days.SAMPLES))
        self.readings(2, '4', hours=[17, 18, 19])      # now to 22:00: 22 h
        found = self.water(self.day(2)).measured(self.batch.pk, self.day(2))
        self.assertEqual((found.value, found.source), (D(4), degree_days.SENSOR))

    def test_bad_readings_do_not_count(self):
        self.bind(3)
        self.readings(2, '30', quality=OUT_OF_RANGE)
        self.assertIsNone(self.water(self.day(2)).measured(self.batch.pk, self.day(2)))

    def test_a_probe_that_cannot_be_read_is_said_and_the_samples_count(self):
        self.bind(7)
        for days_ago in range(1, 6):
            self.readings(days_ago, '4')
            self.temperature(self.t1, days_ago, '6')
        self.treat(self.medicine(degree_days=40), 6, 6)
        with mock.patch.object(PROVIDER, 'covered', side_effect=RuntimeError('down'), create=True):
            [held] = self.held()
        self.assertEqual(held.accrual.days[degree_days.SAMPLES], 5)
        self.assertTrue(held.accrual.sensors_failed)
        self.assertIn('The sensors could not be read', withdrawal.describe(held))


class AssumedTests(SourcesCase):
    def test_an_assumption_above_the_water_is_capped_at_the_coldest_day_measured_in_the_7_days_before(self):
        # 30 degree-days after a last day 6 days ago; 3 °C measured 5 and 4 days ago, nothing since; the species is
        # assumed at 8 °C. Uncapped: 3 + 3 + 8 + 8 + 8 = 30 by yesterday, free today. Capped at 3 °C: 15 by yesterday,
        # 15 to go at 3 °C a day (the last days measured) is 5 days: about 5 days from now.
        self.assume('8.0')
        self.temperature(self.t1, 5, '3')
        self.temperature(self.t1, 4, '3')
        self.treat(self.medicine(degree_days=30), 6, 6)
        [held] = self.held()
        self.assertEqual((held.until, held.estimated, held.remaining_degree_days, held.days_without_temperature),
                         (self.day(-5), True, D(15), 3))
        self.assertEqual((held.accrual.days[degree_days.CAPPED], held.accrual.days[degree_days.ASSUMED]), (3, 0))
        text = withdrawal.describe(held)
        self.assertIn('3 days without a measured water temperature are counted at the coldest daily mean measured in '
                      'the 7 days before each, below the species’ assumed temperature.', text)
        self.assertNotIn('counted at the assumed 8.0 °C', text)

    def test_the_cap_reads_only_the_7_days_before(self):
        # The day 2 days ago, not measured: the 7 days before it are 9 to 3 days ago.
        self.assume('8.0')
        self.temperature(self.t1, 10, '3')              # 8 days before it: too old to cap it
        self.temperature(self.t1, 1, '1')               # after it: never caps it
        counted = self.water(self.day(2)).day(self.batch.pk, self.day(2))
        self.assertEqual((counted.value, counted.how), (D('8.0'), degree_days.ASSUMED))
        self.temperature(self.t1, 9, '5')
        counted = self.water(self.day(2)).day(self.batch.pk, self.day(2))
        self.assertEqual((counted.value, counted.how), (D(5), degree_days.CAPPED))


class FreezingTests(SourcesCase):
    def test_a_daily_mean_of_zero_or_below_adds_nothing(self):
        # 20 degree-days after a last day 6 days ago: 10 °C, −2 °C, 10 °C: 20 by three days ago (the −2 °C day adds
        # 0, never −2), so the fish may go two days ago.
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


class OneAccrualTests(SourcesCase):
    """The same water, every source in it: 6 days ago a probe day at 5 °C, 5 days ago a sample of 6 °C, 4 days ago
    nothing (assumed 8 °C, capped at 5 °C), 3 days ago a sample of −2 °C (adds 0), 2 days ago and yesterday probe days
    at 4 °C: 24 degree-days."""

    def setUp(self):
        super().setUp()
        self.assume('8.0')
        self.bind(7)
        for days_ago, value in ((6, '5'), (2, '4'), (1, '4')):
            self.readings(days_ago, value)
        self.temperature(self.t1, 5, '6')
        self.temperature(self.t1, 3, '-2')
        self.first = self.day(6)
        self.counted = {degree_days.SENSOR: 3, degree_days.SAMPLES: 2, degree_days.CAPPED: 1}

    def days(self, accrual):
        return {how: count for how, count in accrual.days.items() if count}

    def test_the_reader_adds_the_days_up(self):
        accrual = self.water(self.first).accrue(self.batch.pk, self.first, self.day(1))
        self.assertEqual((accrual.total, self.days(accrual), accrual.missing), (D(24), self.counted, 1))

    def test_the_withdrawal_ends_where_the_reader_reaches_it(self):
        self.treat(self.medicine(degree_days=24), 7, 7)
        self.assertEqual(self.held(), [])                       # 24 reached yesterday: free today
        [held] = self.held(day=self.day(1))
        self.assertEqual((held.until, held.estimated), (self.today, False))
        self.assertEqual(self.days(held.accrual), self.counted)
        self.treat(self.medicine('Slice vet.', degree_days=25), 7, 7)
        [held] = self.held()
        self.assertEqual((held.until, held.remaining_degree_days, self.days(held.accrual)),
                         (self.day(-1), D(1), {**self.counted, degree_days.PROJECTED: 1}))

    def test_the_fast_counts_the_same_days(self):
        water = self.water(self.first)
        fed = SimpleNamespace(moment=start_of(self.day(7), self.t1), record=SimpleNamespace(date=self.day(7)))
        rule = HandlingRule(kind='harvest', min_fasting_degree_days=D(24))
        requirement = fasting.Requirement.of(rule)
        done = fasting.fasted(self.t1, self.today, fed, requirement, water, [self.batch.pk])
        self.assertEqual((done.degree_days, done.ok, self.days(done.accrual)), (D('24.0'), True, self.counted))
        start = fasting.start_of_fast(self.t1, self.today, requirement, water, self.batch.pk)
        self.assertEqual((start.starts_at, start.unreached, self.days(start.accrual)),
                         (start_of(self.first, self.t1), False, self.counted))
        self.assertIn('Days counted: 3 days measured by the sensors, 2 days from water samples, 1 day without a '
                      'measurement.', degree_days.accrual_text(start.accrual))


class CoupledConstantsTests(SourcesCase):
    def test_the_last_feeding_is_looked_for_longer_than_the_longest_rule(self):
        self.assertEqual(fasting.LOOKBACK_DAYS, MAX_FASTING_HOURS // 24 + 1)
        self.assertGreaterEqual(fasting.MAX_FAST_DAYS * 24, MAX_FASTING_HOURS)

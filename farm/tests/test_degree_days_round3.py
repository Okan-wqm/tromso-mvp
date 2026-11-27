"""The degree-days, round 3 (the independent review REVIEW-2 of 6fec0790): what can still end a withdrawal earlier after
the deploy without a question, what a page costs, and what the records and the words say.

- N-1: the cap of an assumed temperature is the coldest of the days before its GAP began, however long before the walk,
  within a horizon of the walk (never of today): the same past days count the same however many days go by.
- N-2: a probe is still expected at a place that had a row on any of the last EXPECTED_DAYS closed days of its clock,
  not only on the last one: a silent day does not let the next day count from the samples before it is closed.
- N-4: the cap is worked out once per gap.
- N-6: a floor is never set at a day already past.
- N-7: a deadband channel's held value is the lower bound of the messages up to the next row.
- N-8: the water page and the closing of probe days take their places from the one resolver.
- N-9: a projection at the species' assumed temperature is capped as a past day is.
- N-10: the daily job takes an advisory lock.
- N-11: a probe day keeps the hold it was made with; the closing is in the activity log.
- N-12: the words say the calendar days the code counts.
- N-13: no dead choice, no unused field.
- N-14: a day of 25 hours counts, one of 23 hours with 19 of them measured does not."""
import inspect
import os
import subprocess
from dataclasses import fields
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from unittest import mock

from django.db import connection
from django.test.utils import CaptureQueriesContext

from core.forms import PlatformSettingsForm
from core.models import AuditLog
from core.testing import FrozenClock
from farm import withdrawal_gate as gate
from sensors import bindings

from ..health import services as health_services, withdrawal
from ..models import ProbeDay, ProbeDayClosing, ProductionDepartment, Site, System, Tank, WaterMeasurement
from ..models.health import FloorOrigin
from ..models.site import zone_of
from ..stock.dates import shown_date
from ..water import degree_days, read, services, sources
from ..water.degree_days import BatchWater
from .helpers import correction_window, point_of
from .test_degree_days_sources import SourcesCase
from .test_stock import make_unit

D = Decimal
DAY = timedelta(days=1)
CLOCK = 'django.utils.timezone.now'


class CapAnchoredTests(FrozenClock, SourcesCase):
    """T-02's own batch, stocked 61 days before 20.11.2026; the species assumed at 10 °C; one sample of 3 °C on
    21.09.2026 (M), nothing since; a course of 200 degree-days ended on 10.11.2026 (E = M + 50)."""
    NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)

    def setUp(self):
        super().setUp()
        with correction_window(400):
            self.fish = self.stock(self.t2, count=500, days_ago=61)
        self.assume('10.0')
        self.temperature(self.t2, 60, '3')
        self.treat(self.medicine(degree_days=200), 10, 10, units=[self.t2])

    def test_the_cap_of_a_gap_begun_before_the_course_holds_and_the_end_does_not_move(self):
        # The gap began the day after the sample, 50 days before the course: the cap is that sample's 3 °C (the coldest
        # of the days before the GAP began), now and as the days go by. Today the 9 past days count 27; the rest is
        # projected at the assumption capped at 3 °C: 173 to go is 58 days, the end 17.01.2027. In 3, 8 and 20 days the
        # past days are counted, still at 3 °C, and the end does not move.
        ends = [self.held(unit=self.t2)[0]]
        for later in (3, 8, 20):
            with mock.patch(CLOCK, return_value=self.NOW + later * DAY):
                ends += withdrawal.of_units([self.t2]).get(self.t2.pk)
        self.assertEqual([held.until for held in ends], [date(2027, 1, 17)] * 4)
        self.assertEqual([held.accrual.days[degree_days.CAPPED] for held in ends], [9, 12, 17, 29])
        self.assertEqual(ends[0].accrual.projected_at, D(3))


class HorizonTests(SourcesCase):
    """T-02's own batch, stocked 400 days ago; the species assumed at 10 °C; a walk from 10 days ago: its gap is followed
    back CAP_HORIZON_DAYS (365) before it, to 375 days ago, and no further."""

    def setUp(self):
        super().setUp()
        with correction_window(500):
            self.fish = self.stock(self.t2, count=500, days_ago=400)
        self.assume('10.0')

    def counted(self):
        water = BatchWater({self.fish.pk}, self.today, self.day(10))
        accrual = water.walk(self.fish.pk, self.day(10), days=1)
        return accrual

    def test_a_sample_inside_the_horizon_caps_the_gap(self):
        self.temperature(self.t2, 374, '3')
        accrual = self.counted()
        self.assertEqual((accrual.days[degree_days.CAPPED], accrual.total, accrual.uncapped), (1, D(3), 0))

    def test_a_sample_just_outside_the_horizon_does_not_and_the_text_says_so(self):
        self.temperature(self.t2, 376, '3')
        accrual = self.counted()
        self.assertEqual((accrual.days[degree_days.ASSUMED], accrual.total, accrual.uncapped), (1, D('10.0'), 1))
        self.assertIn(f'Nothing measured for these fish caps 1 day counted at the assumed temperature: nothing was '
                      f'measured for them from {shown_date(self.day(375))}, 365 days before the first day counted, to '
                      'the start of its gap.', degree_days.accrual_text(accrual))
        self.assertEqual(degree_days.CAP_HORIZON_DAYS, 365)


class ProjectionCapTests(SourcesCase):
    def test_a_projection_at_the_assumed_temperature_is_capped_too(self):
        # T-02's batch stocked 50 days ago; assumed 10 °C; 3 °C measured 42 days ago, nothing since; a course of 150
        # degree-days ended 40 days ago. The 39 past days count 3 °C (117); no day measured within 30 days, so the rest
        # is projected at the assumption, capped at 3 °C as the past days are: 33 to go is 11 days.
        with correction_window(400):
            self.stock(self.t2, count=500, days_ago=50)
        self.assume('10.0')
        self.temperature(self.t2, 42, '3')
        with correction_window(400):
            self.treat(self.medicine(degree_days=150), 40, 40, units=[self.t2])
        [held] = self.held(unit=self.t2)
        self.assertEqual((held.accrual.projected_at, held.until), (D(3), self.day(-11)))


class ExpectedTests(SourcesCase):
    def test_a_probe_silent_on_the_last_closed_day_is_still_expected_the_day_after(self):
        # The probe read 4 °C on the days 5, 4 and 3 days ago, nothing 2 days ago (closed without a row), 4 °C yesterday,
        # which is not closed yet; a hand sample of 10 °C yesterday. 16 degree-days asked: with yesterday counted from
        # the sample (4 + 4 + 4 + 0 + 10) the fish would be free today; the probe is still expected for yesterday, so
        # yesterday is projected (at 4 °C: 16, reached yesterday) and the fish wait to tomorrow.
        self.probed('4', 5, 4, 3, 1)
        self.job(5)
        self.job(2)
        self.temperature(self.t1, 1, '10')
        self.treat(self.medicine(degree_days=16), 6, 6)
        [held] = self.held()
        self.assertEqual((held.until, held.waits, held.unclosed), (self.day(-1), True, 1))

    def test_a_probe_gone_for_good_is_no_longer_expected_after_the_expected_days(self):
        self.probed('4', 12)
        self.job(12)
        self.job(2)
        self.temperature(self.t1, 1, '9')
        found = self.measured(1)
        self.assertEqual((found.value, found.source), (D(9), degree_days.SAMPLES))
        self.assertEqual(degree_days.EXPECTED_DAYS, 7)


class GapMemoTests(SourcesCase):
    def test_the_cap_is_worked_out_once_a_gap(self):
        with correction_window(400):
            fish = self.stock(self.t2, count=500, days_ago=45)
        self.assume('10.0')
        self.temperature(self.t2, 44, '3')
        water = BatchWater({fish.pk}, self.today, self.day(43))
        batch_id = fish.pk
        with mock.patch.object(BatchWater, '_value', autospec=True, side_effect=BatchWater._value) as looked:
            accrual = water.accrue(batch_id, self.day(43), self.day(1))
        self.assertEqual(accrual.days[degree_days.CAPPED], 43)
        self.assertLess(looked.call_count, 400)


class FloorTests(SourcesCase):
    def test_a_floor_is_never_set_at_a_day_already_past(self):
        treatment = self.treat(self.medicine(degree_days=40), 6, 6)
        moved = [withdrawal.Moved(treatment, self.batch.pk, self.day(1), None),
                 withdrawal.Moved(treatment, self.batch.pk, self.today, None)]
        self.assertEqual(health_services.set_floors(moved, FloorOrigin.CLOSING, 'test'), [])


class DeadbandTests(SourcesCase):
    def test_a_rows_hold_is_the_lower_bound_of_the_messages_up_to_the_next_row(self):
        # Every hour one row of 5 °C standing for 60 messages from 3 °C to 5 °C since the row before: the water between
        # two rows was as low as 3 °C, so the held value is 3 °C, never the row's own 5 °C.
        start = datetime.combine(self.day(2), time.min, tzinfo=self.zone())
        rows = [(self.probe.channel_no, start + timedelta(hours=hour), 5.0, 60, 270.0, 3.0, 5.0) for hour in range(25)]
        with connection.cursor() as cursor:
            cursor.executemany('INSERT INTO sensors_reading (channel_no, ts, value, n, run_sum, run_min, run_max) '
                               'VALUES (%s, %s, %s, %s, %s, %s, %s)', rows)
        self.job(2)
        self.assertEqual(self.row(2).mean_c, D('3.00'))


class JobTests(SourcesCase):
    def test_the_job_takes_an_advisory_lock(self):
        with CaptureQueriesContext(connection) as queries:
            self.job(1)
        self.assertTrue(any('pg_advisory_xact_lock' in query['sql'] for query in queries))

    def test_a_probe_day_keeps_the_hold_it_was_made_with_and_the_closing_is_logged(self):
        quick = self.channel('QUICK', heartbeat_s=600)           # fresh for 30 minutes: a reading stands 30 minutes
        self.bind(quick, point_of(self.t1, 'bottom_drain'))
        self.readings(1, '4', channel=quick)
        _rows, [closing], _floors = self.job(1)
        self.assertEqual(self.row(1, quick).hold_seconds, 1800)
        self.assertTrue(AuditLog.objects.filter(entity_id=str(closing.pk)).exists())


class OneResolverTests(SourcesCase):
    def test_the_water_page_and_the_closing_take_their_places_from_the_one_resolver(self):
        self.assertIn('tiers(', inspect.getsource(read._places))
        self.assertIn('_places_of(', inspect.getsource(services.probe_places))
        self.assertFalse(hasattr(read, 'water_sources'))


class WordsTests(SourcesCase):
    def test_the_cap_setting_says_calendar_days(self):
        help_text = str(PlatformSettingsForm.Meta.help_texts['assumption_cap_days'])
        self.assertIn('calendar days before its gap', help_text)
        self.assertNotIn('measured days', help_text)

    def test_no_dead_choice_and_no_unused_field(self):
        self.assertNotIn('write', FloorOrigin.values)
        self.assertNotIn('role', {field.name for field in fields(sources.Covered)})


class LongDayTests(FrozenClock, SourcesCase):
    """Oslo around the night the clocks go back (25 October 2026: 25 hours, 22:00 UTC on the 24th to 23:00 UTC on the
    25th), and the night they go forward (29 March 2026: 23 hours)."""
    NOW = datetime(2026, 10, 28, 10, 0, tzinfo=UTC)

    def setUp(self):
        super().setUp()
        self.oslo = Site.objects.create(name='Oslo', code='OS', timezone='Europe/Oslo')
        self.o1 = make_unit('O-01', ProductionDepartment.objects.create(site=self.oslo, name='Hall O', code='HO'))
        self.oslo_probe = self.channel('OSLO', device=self.oslo_device())
        bindings.move(self.user, self.oslo_probe, point=point_of(self.o1), at=datetime(2026, 3, 20, tzinfo=UTC))

    def oslo_device(self):
        from sensors.tests import make_device
        return make_device(self.connection, self.format, self.oslo, code='PROBE-O1')

    def hours_of(self, first, count):
        with connection.cursor() as cursor:
            cursor.executemany('INSERT INTO sensors_reading (channel_no, ts, value) VALUES (%s, %s, %s)',
                               [(self.oslo_probe.channel_no, first + timedelta(hours=hour), 4.0) for hour in range(count)])

    def test_a_day_of_25_hours_counts_whole(self):
        self.hours_of(datetime(2026, 10, 24, 22, 0, tzinfo=UTC), 25)
        services.close_probe_days(now=datetime(2026, 10, 26, 3, 0, tzinfo=UTC))
        row = ProbeDay.objects.get(day=date(2026, 10, 25), channel_no=self.oslo_probe.channel_no)
        self.assertEqual((row.hours, row.covered_seconds, row.counts), (25, 25 * 3600, True))

    def test_a_day_of_23_hours_with_19_measured_does_not_count(self):
        self.hours_of(datetime(2026, 3, 28, 23, 0, tzinfo=UTC), 19)
        services.close_probe_days(now=datetime(2026, 3, 30, 3, 0, tzinfo=UTC))
        row = ProbeDay.objects.get(day=date(2026, 3, 29), channel_no=self.oslo_probe.channel_no)
        self.assertEqual((row.hours, row.counts), (19, False))
        self.assertEqual(ProbeDayClosing.objects.get(timezone='Europe/Oslo').day, date(2026, 3, 29))



# ---- REVIEW-3 -------------------------------------------------------------------------------------------------------
class TwoChannelsTests(SourcesCase):
    """Two temperature channels at T-01's middle point on one day (an oxygen probe's thermistor beside a temperature
    probe): the lowest counting row counts, whatever order the rows were written or are read in (R3-1)."""

    @gate.opened('test fixture: closed probe days straight in the database')
    def rows(self, *rows):
        for channel_no, mean, counts in rows:
            ProbeDay.objects.create(point=point_of(self.t1), day=self.day(2), channel_no=channel_no, mean_c=D(mean),
                                    covered_seconds=86400 if counts else 3600, hours=24 if counts else 1,
                                    readings=24, ranged=True, hours_needed=20, hold_seconds=3600, counts=counts,
                                    how='closed')

    def test_the_lower_of_two_counts_written_first(self):
        self.rows((101, '6', True), (102, '8', True))
        self.assertEqual(self.measured(2).value, D(6))

    def test_the_lower_of_two_counts_written_second(self):
        self.rows((102, '8', True), (101, '6', True))
        self.assertEqual(self.measured(2).value, D(6))

    def test_a_row_that_does_not_count_never_hides_one_that_does(self):
        self.rows((101, '2', False), (102, '7', True))
        found = self.measured(2)
        self.assertEqual((found.value, found.source), (D(7), degree_days.SENSOR))


class SearchOnceTests(SourcesCase):
    def test_the_gap_search_runs_once_a_read_however_many_batches(self):
        # Every unit with its points and its own batch, the species assumed at 10 °C, one course in degree-days over
        # all of them, nothing measured: the gap before the walks is searched once for the read, not once per batch
        # (R3-2). Measured at 3, 9 and 27 batches.
        self.assume('10.0')
        units, counts = [], []
        for size in (3, 9, 27):
            made = []
            while len(units) < size:
                unit = make_unit(f'S-{len(units):02d}', self.hall)
                point_of(unit)
                self.stock(unit, count=100, days_ago=20)
                units.append(unit)
                made.append(unit)
            self.treat(self.medicine(f'Med {size}', degree_days=200), 5, 5, units=made)
            with CaptureQueriesContext(connection) as queries:
                withdrawal.of_units(units)
            counts.append(len(queries))
        self.assertEqual(counts[1:], counts[:1] * 2)


class AssumedClosingTests(SourcesCase):
    def test_a_day_closed_without_a_counting_row_counted_above_the_projection_is_floored(self):
        # T-02's own fish, stocked 20 days ago; the species assumed at 10 °C. A probe counted 4 °C on the days 12 to 9
        # ago and 8 °C two days ago; nothing in between. Yesterday it read only 17 hours: its row does not count. Before
        # the job closes yesterday it is projected at the mean of the measured days, 4.8 °C; closed, it counts at the
        # assumption capped at 8 °C (the coldest of the 7 days before its gap). That is an assumption, not the water:
        # the earlier end it gives is floored, and the floor says so (R3-3).
        with correction_window(400):
            self.stock(self.t2, count=500, days_ago=20)
        self.assume('10.0')
        probe = self.channel('T2')
        self.bind(probe, point_of(self.t2), days_ago=16)
        for days_ago in (12, 11, 10, 9):
            self.readings(days_ago, '4', channel=probe)
        self.readings(2, '8', channel=probe)
        self.readings(1, '8', hours=range(17), channel=probe)
        self.job(12)
        self.job(2)
        self.treat(self.medicine(degree_days=56), 13, 13, units=[self.t2])
        [before] = self.held(unit=self.t2)
        self.assertEqual((before.settled, before.accrual.projected_at), (self.day(-1), D('4.8')))
        _rows, _closings, [floor] = self.job(1)
        self.assertEqual(floor.not_before, self.day(-1))
        self.assertIn('assumption', floor.reason)


class FloorRequiredTests(SourcesCase):
    def test_a_day_and_a_projection_need_the_walks_floor_and_a_walk_back_its_days(self):
        water = self.water(self.day(5))
        with self.assertRaises(TypeError):
            water.day(self.batch.pk, self.day(3))
        with self.assertRaises(TypeError):
            water.projection(self.batch.pk)
        with self.assertRaises(ValueError):
            water.walk(self.batch.pk, self.day(1), backward=True, needed=D(10))


class DeadbandBadRowTests(SourcesCase):
    def test_a_runs_lower_bound_reaches_back_over_a_stored_bad_row(self):
        # Every hour a row of 5 °C standing for 60 messages from 3 °C to 5 °C; a bad row stored at half past each hour
        # ends the hold before it. The run of the messages after the bad row is carried by the next GOOD row: the held
        # value of each row is still that run's lowest, 3 °C (R3-9).
        start = datetime.combine(self.day(2), time.min, tzinfo=self.zone())
        rows = [(self.probe.channel_no, start + timedelta(hours=hour), 5.0, 60, 270.0, 3.0, 5.0, 0)
                for hour in range(25)]
        rows += [(self.probe.channel_no, start + timedelta(hours=hour, minutes=30), 99.0, 1, None, None, None, 32)
                 for hour in range(24)]
        with connection.cursor() as cursor:
            cursor.executemany('INSERT INTO sensors_reading (channel_no, ts, value, n, run_sum, run_min, run_max, '
                               'quality) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)', rows)
        self.job(2)
        self.assertEqual((self.row(2).mean_c, self.row(2).covered_seconds), (D('3.00'), 12 * 3600))


class OtherClockSearchTests(SourcesCase):
    def test_the_search_reads_each_place_on_its_own_clock(self):
        # T-01 (UTC) in a system on Tokyo's clock: a loop sample at 00:30 on Tokyo's day 20 days ago is that day's,
        # though it is still the day before in UTC (R3-12).
        tokyo = Site.objects.create(name='Tokyo', code='TK', timezone='Asia/Tokyo')
        system = System.objects.create(site=tokyo, name='Tokyo loop', code='TL', production_department=(
            ProductionDepartment.objects.create(site=tokyo, name='Hall T', code='HT')))
        with gate.opened('test fixture: the unit in a loop of another clock'):
            Tank.objects.filter(pk=self.t1.pk).update(system=system)
        self.t1.refresh_from_db()
        loop = point_of(system)
        day = self.day(20)
        with gate.opened('test fixture: a sample straight in the database'):
            WaterMeasurement.objects.create(point=loop, source='manual', temperature_c=D(3), created_by=self.user,
                                            measured_at=datetime.combine(day, time(0, 30), tzinfo=zone_of(tokyo)))
        temperatures = degree_days.Temperatures([self.t1], self.day(5), self.today, D(1))
        self.assertEqual(temperatures.last_measured(day, day + DAY), day)


class ScriptTests(SourcesCase):
    def run_script(self, out, **env):
        script = Path(__file__).resolve().parents[2] / 'scripts' / 'withdrawal_ends_old.sh'
        return subprocess.run(['bash', str(script), out], capture_output=True, text=True, env={**os.environ, **env})

    def test_the_script_refuses_unsafe_paths_and_a_migration_on_the_compose_network(self):
        for out in ('F:\\dev\\balik-notes\\ends.json', '/tmp/two words/ends.json'):
            with self.subTest(out=out):
                done = self.run_script(out)
                self.assertEqual(done.returncode, 2, done.stderr)
                self.assertIn('refused', done.stderr)
        done = self.run_script('/tmp/ends.json', WITHDRAWAL_ENDS_MIGRATE='1',
                               WITHDRAWAL_ENDS_DB='-e DB_HOST=balik-ciftligi-db-1')
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn('compose', done.stderr)


class OneTierRuleTests(SourcesCase):
    def test_the_sensors_trail_takes_a_units_tiers_from_the_one_resolver(self):
        from sensors import read as sensors_read
        self.assertIn('water_read.tiers(', inspect.getsource(sensors_read.tiers))

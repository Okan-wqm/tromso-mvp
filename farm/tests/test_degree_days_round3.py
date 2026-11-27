"""The degree-days, round 3 (the independent review REVIEW-2 of 6fec0790): what can still end a withdrawal earlier after
the deploy without a question, what a page costs, and what the records and the words say.

- N-1: the cap of an assumed temperature looks back from the walk's first day (less the cap's days), never from today:
  the same past days count the same however many days go by.
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
from dataclasses import fields
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from unittest import mock

from django.db import connection
from django.test.utils import CaptureQueriesContext

from core.forms import PlatformSettingsForm
from core.models import AuditLog
from core.testing import FrozenClock
from sensors import bindings

from ..health import services as health_services, withdrawal
from ..models import ProbeDay, ProbeDayClosing, ProductionDepartment, Site
from ..models.health import FloorOrigin
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

    def test_the_end_does_not_move_with_the_days_that_go_by(self):
        # The sample is 50 days before the course: outside the cap's look-back of the walk (its first day less 7). Every
        # day counts 10 °C now and in 8 days, when the old read range would have dropped it: the end stays 01.12.2026.
        [now] = self.held(unit=self.t2)
        later = self.NOW + 8 * DAY
        with mock.patch(CLOCK, return_value=later):
            [then] = withdrawal.of_units([self.t2]).get(self.t2.pk)
        self.assertEqual((now.until, then.until), (date(2026, 12, 1), date(2026, 12, 1)))


class ProjectionCapTests(SourcesCase):
    def test_a_projection_at_the_assumed_temperature_is_capped_too(self):
        # T-02's batch stocked 50 days ago; assumed 10 °C; 3 °C measured 42 days ago, nothing since; a course of 150
        # degree-days ended 40 days ago. The 39 past days count 3 °C (117); no day measured within 30 days, so the rest
        # is projected at the assumption, capped at 3 °C as the past days are: 33 to go is 11 days.
        with correction_window(400):
            self.stock(self.t2, count=500, days_ago=50)
        self.assume('10.0')
        self.temperature(self.t2, 42, '3')
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
        self.assertIn('days before the gap', help_text)
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


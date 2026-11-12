"""The medicine withdrawal on a farm whose sites read several clocks (second review, S1).

A withdrawal follows the fish, and the fish, the course and the company can each be on another day for some hours. Two
questions are asked of the clocks, and one day cannot answer both:

- WHICH courses and fish count: read as LATE as any clock involved has it. A course that has begun where it was given
  has begun, and a batch that is in a treated unit there is in it, though an earlier clock elsewhere has not reached
  that day.
- HOW FAR the withdrawal has run (the days counted, the day it ends): read as EARLY as any clock involved has it.

So fish are held if they are held on any day from the earliest relevant today to the latest: the strict answer. The
rule lives once, in farm.health.withdrawal.Reader (`there`, `holds`); the Treatments list, "Under withdrawal today",
the write guards and what blocks a deletion read it, so none of them is laxer than a unit's own line, and the list is
never laxer than reading everything on the company's day (what it did before this branch).

The clocks: Bergen (the fixtures' site, UTC), Oslo (the company's, and the site Oslofjord), Tokyo."""
from datetime import date, datetime, timedelta, timezone as dt_timezone

from django.urls import reverse

from core.testing import BAD_HOURS, FrozenClock

from ..handling import check as handling_check
from ..health import services, withdrawal
from ..models import ProductionDepartment, Site
from ..stock import services as stock_services
from ..stock.dates import local_today
from ..stock.read import Presence
from .helpers import rows_data
from .test_health import TokyoCase
from .test_stock import make_unit

DAY = timedelta(days=1)


class ClocksCase(TokyoCase):
    """Bergen's T-01 and T-02 (UTC), Tokyo's K-01, and Oslofjord's OS-01 and OS-02 (Oslo's clock)."""

    def setUp(self):
        super().setUp()
        oslofjord = Site.objects.create(name='Oslofjord', code='OS', timezone='Europe/Oslo')
        hall = ProductionDepartment.objects.create(site=oslofjord, name='Hall O', code='HO')
        self.os1, self.os2 = make_unit('OS-01', hall), make_unit('OS-02', hall)

    def course(self, unit, first, last, days=None, degree_days=None):
        medicine = self.medicine(name=f'Bath {unit.code} {days} {degree_days}', days=days, degree_days=degree_days)
        return services.record_treatment(self.user, units=[unit], method='bath', reason='sea_lice', start_date=first,
                                         end_date=last, medicine=medicine)

    def move(self, batch, source, target, day, count=1000):
        self.going_on(stock_services.record_transfer, self.user, source=source, batch=batch, day=day,
                      legs=[(target, count)], reason='density')

    # ---- what each reader says ------------------------------------------------------------------------------------
    def row(self, treatment, **query):
        rows = self.client.get(reverse('farm:treatments'), query).context['rows']
        return next((row for row in rows if row['treatment'] == treatment), None)

    def list_holds(self, treatment):
        """The batches the Treatments list shows as held by the treatment."""
        row = self.row(treatment)
        if 'held' not in row:                # before the rule was settled: a batch was held when it held on the row's day
            return {batch.code for batch, found in row['batches'] if found is not None and found.holds_on(row['today'])}
        return {batch.code for batch, found in row['batches'] if found is not None and batch.pk in row['held']}

    def line_holds(self, unit):
        """The batches the unit's own withdrawal line holds on the unit's own today."""
        return {self.codes[found.batch_id] for found in withdrawal.of_units([unit]).get(unit.pk, [])}

    def harvest_warned(self, unit):
        return [warning.warning for warning in handling_check.check('harvest', unit, local_today(unit))]

    def main_held(self, treatment):
        """What the list held before this branch (f249304): everything read on the company's day alone."""
        company = local_today()
        unit_ids = [unit.pk for unit in treatment.units.all()]
        presence = Presence.of_units(unit_ids)
        there = {batch_id for unit_id in unit_ids for batch_id in presence.batches.get(unit_id, ())
                 if presence.present_between(unit_id, batch_id, treatment.start_date, min(treatment.end_date, company))}
        reader = withdrawal.Reader(there, company)
        return {self.codes[batch_id] for batch_id in there
                if reader.of_treatment(treatment, batch_id).holds_on(company)}

    @property
    def codes(self):
        from ..models import Batch
        return dict(Batch.all_objects.values_list('pk', 'code'))

    def assert_the_list_is_the_strict_side(self, treatment, units):
        """The list holds whatever a unit's own line holds and whatever the company's day alone held, and lists the
        treatment under "Under withdrawal today" exactly when it holds something."""
        held = self.list_holds(treatment)
        for unit in units:
            self.assertLessEqual(self.line_holds(unit), held, f'the list is laxer than the line of {unit.code}')
        self.assertLessEqual(self.main_held(treatment), held, 'the list is laxer than it was on the company’s day')
        self.assertEqual(self.row(treatment, show='withdrawal') is not None, bool(held))
        return held


class AfternoonTests(FrozenClock, ClocksCase):
    """16:00 UTC on the 10th: the 10th in Bergen and Oslo, the 11th in Tokyo."""
    NOW = datetime(2026, 11, 10, 16, 0, tzinfo=dt_timezone.utc)

    def setUp(self):
        super().setUp()
        self.here, self.there = local_today(self.t2), local_today(self.k1)
        self.assertEqual((self.here, self.there, local_today()), (date(2026, 11, 10), date(2026, 11, 11), self.here))

    def test_a_course_given_today_on_a_site_ahead_is_held_though_the_companys_day_has_not_come(self):
        """The review's case D. The list read the 10th, found no fish in the course (it begins on the 11th) and showed
        nothing under withdrawal, while the unit's own line held them to the 17th."""
        batch = self.stock(self.k1, count=1000, weight='100', days_ago=10)
        treatment = self.course(self.k1, self.there, self.there, days=5)
        self.assertEqual(self.line_holds(self.k1), {batch.code})
        self.assertEqual(self.harvest_warned(self.k1), ['withdrawal'])
        self.assertEqual(self.assert_the_list_is_the_strict_side(treatment, [self.k1]), {batch.code})
        [(found, held)] = self.row(treatment)['batches']
        self.assertEqual((found, held.until), (batch, self.there + 6 * DAY))
        self.assertContains(self.client.get(reverse('farm:treatments')), '<span class="over-text" title="')

    def test_treated_ahead_and_moved_behind(self):
        batch, treatment, until = self.treated_there(2, 1)                 # last day the 9th, 1 day: free from the 11th
        self.moved_here(batch)
        self.assertEqual(self.line_holds(self.t2), {batch.code})           # the 10th where they are: held
        self.assertEqual(self.assert_the_list_is_the_strict_side(treatment, [self.t2]), {batch.code})

    def test_treated_behind_and_moved_ahead_the_list_is_the_strict_side(self):
        batch = self.stock(self.t2, count=1000, weight='100', days_ago=10)
        treatment = self.course(self.t2, self.here - DAY, self.here - DAY, days=1)     # free from the 11th
        self.move(batch, self.t2, self.k1, self.here)
        self.assertEqual(self.line_holds(self.k1), set())                  # the 11th where they are now: free there
        self.assertEqual(self.harvest_warned(self.k1), [])
        self.assertEqual(self.assert_the_list_is_the_strict_side(treatment, [self.k1]), {batch.code})

    def test_a_batch_split_over_two_clocks_is_held_as_long_as_its_part_on_the_earlier_one(self):
        batch = self.stock(self.k1, count=1000, weight='100', days_ago=10)
        self.move(batch, self.k1, self.t2, self.here - 5 * DAY, count=400)             # split before the course
        treatment = self.course(self.k1, self.there - 2 * DAY, self.there - 2 * DAY, days=1)   # free from the 11th
        self.assertEqual((self.line_holds(self.k1), self.line_holds(self.t2)), (set(), {batch.code}))
        self.assertEqual(self.assert_the_list_is_the_strict_side(treatment, [self.k1, self.t2]), {batch.code})


class NightTests(FrozenClock, ClocksCase):
    """23:30 UTC on the 10th: the 10th in Bergen, the 11th in Oslo (the company and Oslofjord) and in Tokyo."""
    NOW = BAD_HOURS['WinterNight']

    def setUp(self):
        super().setUp()
        self.here, self.there = local_today(self.t2), local_today(self.os1)
        self.assertEqual((self.here, self.there, local_today()), (date(2026, 11, 10), date(2026, 11, 11), self.there))

    def from_bergen(self, target, days_ago=3):
        """A batch stocked in Bergen and moved to `target` `days_ago` days back on Bergen's clock."""
        batch = self.stock(self.t2, count=1000, weight='100', days_ago=10)
        self.move(batch, self.t2, target, self.here - days_ago * DAY)
        return batch

    def test_fish_from_an_earlier_clock_given_a_course_today_are_held(self):
        """The review's case E, a regression against the company's day: the list read the 10th (Bergen's, where the
        fish once were), on which the course of the 11th had not begun, and showed no fish and nothing under
        withdrawal."""
        batch = self.from_bergen(self.os1)
        treatment = self.course(self.os1, self.there, self.there, days=5)              # held to the 16th
        self.assertEqual(self.line_holds(self.os1), {batch.code})
        self.assertEqual(self.harvest_warned(self.os1), ['withdrawal'])
        self.assertEqual(self.main_held(treatment), {batch.code})                        # the company's day held them
        self.assertEqual(self.assert_the_list_is_the_strict_side(treatment, [self.os1]), {batch.code})
        row = self.row(treatment)
        [(found, held)] = row['batches']
        self.assertEqual((row['today'], found, held.until), (self.here, batch, self.there + 6 * DAY))

    def test_a_batch_that_arrived_today_in_a_unit_under_a_running_course_is_in_it(self):
        resident = self.stock(self.os1, count=1000, weight='100', days_ago=10)
        treatment = self.course(self.os1, self.there - 2 * DAY, self.there + 2 * DAY, days=1)     # running
        arrived = self.from_bergen(self.os2)
        self.move(arrived, self.os2, self.os1, self.there)                 # today on Oslofjord's clock: the 11th
        self.assertEqual(self.line_holds(self.os1), {resident.code, arrived.code})
        self.assertEqual(self.assert_the_list_is_the_strict_side(treatment, [self.os1]), {resident.code, arrived.code})

    def test_degree_days_reached_yesterday_on_the_later_clock_still_hold_on_the_earlier_one(self):
        batch = self.from_bergen(self.os1, days_ago=8)
        treatment = self.course(self.os1, self.there - 6 * DAY, self.there - 6 * DAY, degree_days=40)
        self.today = self.there                                             # samples dated on Oslofjord's clock
        for days_ago in range(1, 6):
            self.temperature(self.os1, days_ago, '8')                      # 8 degrees a day, the 6th to the 10th: 40
        self.today = self.here
        self.assertEqual(self.line_holds(self.os1), set())                 # reached on the 10th: free on the 11th there
        self.assertEqual(self.assert_the_list_is_the_strict_side(treatment, [self.os1]), {batch.code})
        [(_found, held)] = self.row(treatment)['batches']
        self.assertEqual((held.until, held.estimated), (self.there, False))


class GuardsOnTwoClocksTests(FrozenClock, ClocksCase):
    """The write guards and what blocks a deletion, for fish under a course begun today on the later clock (the
    review's inference from case E: their day is the earliest among the units, the 10th, and the course begins on the
    11th). 23:30 UTC on the 10th."""
    NOW = BAD_HOURS['WinterNight']

    def setUp(self):
        super().setUp()
        self.here, self.there = local_today(self.t2), local_today(self.os1)
        self.fish = self.stock(self.t2, count=1000, weight='100', days_ago=10)
        self.move(self.fish, self.t2, self.os1, self.here - 3 * DAY)
        self.bath = self.medicine(name='Bath', days=5)
        self.given_today = services.record_treatment(self.user, units=[self.os1], method='bath', reason='sea_lice',
                                                 start_date=self.there, end_date=self.there, medicine=self.bath)

    def test_the_guards_day_is_the_earlier_one_and_the_course_is_of_the_later(self):
        self.assertEqual(withdrawal._reached([self.os1.pk]), ({self.fish.pk}, self.here))
        self.assertEqual(self.given_today.start_date, self.there)

    def test_what_blocks_a_deletion_sees_the_fish_as_held(self):
        [why] = withdrawal.held_reached([self.os1.pk])
        self.assertIn(f'A medicine withdrawal holds batch {self.fish.code}', why)

    def test_a_medicine_row_made_shorter_asks_for_the_fish_of_the_course_begun_today(self):
        """The medicine was also given on a Bergen unit long ago, so the guard's day is Bergen's, the 10th."""
        services.record_treatment(self.user, units=[self.t1], method='bath', reason='sea_lice',
                                  start_date=self.here - 9 * DAY, end_date=self.here - 9 * DAY, medicine=self.bath)
        data = rows_data('withdrawals', [{'species': '', 'degree_days': '', 'days': '1', 'safety_margin_pct': '',
                                          'note': ''}], 0, record=self.bath)
        refused = self.client.post(reverse('farm:medicine_withdrawals', args=[self.bath.pk]), data)
        self.assertEqual(refused.status_code, 422)
        self.assertContains(refused, f'{self.fish.code} is held', status_code=422)
        self.assertEqual(list(self.bath.withdrawals.values_list('days', flat=True)), [5])

    def test_voiding_the_course_begun_today_asks(self):
        with self.assertRaises(withdrawal.WithdrawalChanged) as asked:
            services.void_treatment(self.user, self.given_today, 'Wrong cage')
        self.assertEqual([freed.batch for freed in asked.exception.change.released], [self.fish])

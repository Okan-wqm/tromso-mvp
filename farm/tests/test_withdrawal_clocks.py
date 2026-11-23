"""The medicine withdrawal on a farm whose sites read several clocks.

**The rule (the owner's decision of 12.11.2026): everything is read on the site's own day.** Fish are read on today of
the site they are on NOW. The Treatments list, "Under withdrawal today" and its day counts read each batch on that
day, through the same reader the unit's own withdrawal line and the harvest check use (farm.health.withdrawal
`of_units`, `of_treatments`, one reader per site's day), so they are one answer: for a site ahead of the company or
behind it, a batch moved between clocks, a batch split over two, a course begun today on its site, a batch that arrived
today. The company's day plays no part in whether fish are held. Every test here asserts that the list says what the
unit's own line says.

The write guards are another matter and keep their day, the earliest today among every unit the fish were in; but a
course that has begun where it was given has begun (Reader.there), so a guard on an earlier day sees it.

The clocks: Bergen (the fixtures' site, UTC), Oslo (the company's, and the site Oslofjord), Tokyo."""
from datetime import date, datetime, timedelta, timezone as dt_timezone

from django.urls import reverse

from core.testing import BAD_HOURS, FrozenClock

from ..handling import check as handling_check
from ..health import services, withdrawal
from ..models import Batch, ProductionDepartment, Site
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
    def parts(self, treatment, **query):
        """The treatment's row on the list: its parts (withdrawal.Reached), or None when the list leaves it out."""
        rows = self.client.get(reverse('farm:treatments'), query).context['rows']
        return next((row['batches'] for row in rows if row['treatment'] == treatment), None)

    def line(self, unit, treatment):
        """{batch code: the withdrawal} the unit's own line holds today for this treatment, on the unit's own today."""
        codes = dict(Batch.all_objects.values_list('pk', 'code'))
        return {codes[found.batch_id]: found for found in withdrawal.of_units([unit]).get(unit.pk, [])
                if found.treatment == treatment}

    def harvest_warned(self, unit):
        return [warning.warning for warning in handling_check.check('harvest', unit, local_today(unit))]

    def assert_the_list_says_what_the_units_own_line_says(self, treatment, units):
        """For each unit: the batches of the treatment that are in it today are on the list read on that unit's own
        today, held exactly when the unit's own line holds them, with the same end and the same day counts; and "Under
        withdrawal today" lists the treatment exactly when a part is held. Returns {(batch code, the part's units):
        held}."""
        parts = self.parts(treatment)
        for unit in units:
            today = local_today(unit)
            here = Presence.of_units([unit.pk]).batches_in(unit.pk, today)
            listed = {part.batch.code: part for part in parts if part.batch.pk in here and part.today == today
                      and (not part.units or unit.code in part.units)}
            line = self.line(unit, treatment)
            self.assertEqual({code for code, part in listed.items() if part.held}, set(line), unit.code)
            for code, found in line.items():
                self.assertEqual((listed[code].withdrawal.until, listed[code].withdrawal.days_without_temperature),
                                 (found.until, found.days_without_temperature), (unit.code, code))
        self.assertEqual(self.parts(treatment, show='withdrawal') is not None, any(part.held for part in parts))
        return {(part.batch.code, part.units): part.held for part in parts}


class AfternoonTests(FrozenClock, ClocksCase):
    """16:00 UTC on the 10th: the 10th in Bergen and Oslo, the 11th in Tokyo."""
    NOW = datetime(2026, 11, 10, 16, 0, tzinfo=dt_timezone.utc)

    def setUp(self):
        super().setUp()
        self.here, self.there = local_today(self.t2), local_today(self.k1)
        self.assertEqual((self.here, self.there, local_today()), (date(2026, 11, 10), date(2026, 11, 11), self.here))

    def test_a_course_given_today_on_a_site_ahead_of_the_company_has_begun(self):
        """The review's case D. Read on the company's 10th, or on any day before the course's first, the list found no
        fish in a course that began on the 11th where it was given, while the unit's own line held them to the 17th."""
        batch = self.stock(self.k1, count=1000, weight='100', days_ago=10)
        treatment = self.course(self.k1, self.there, self.there, days=5)
        self.assertEqual(self.harvest_warned(self.k1), ['withdrawal'])
        self.assertEqual(self.assert_the_list_says_what_the_units_own_line_says(treatment, [self.k1]),
                         {(batch.code, ()): True})
        [part] = self.parts(treatment)
        self.assertEqual((part.today, part.withdrawal.until), (self.there, self.there + 6 * DAY))
        self.assertContains(self.client.get(reverse('farm:treatments')), '<span class="over-text" title="')

    def test_fish_free_on_their_own_sites_day_are_free_though_the_companys_day_has_not_come(self):
        """A site ahead of the company whose fish never left it: free on the site's 11th, and so on the list. The
        company's 10th plays no part."""
        batch, treatment, until = self.treated_there(1, 0)                 # given yesterday there, no days: free today
        self.assertEqual((until, self.harvest_warned(self.k1)), (self.there, []))
        self.assertEqual(self.assert_the_list_says_what_the_units_own_line_says(treatment, [self.k1]),
                         {(batch.code, ()): False})
        self.assertIsNone(self.parts(treatment, show='withdrawal'))

    def test_treated_ahead_and_moved_behind_they_are_read_where_they_are_now(self):
        """Fish treated in Tokyo (free from the 11th) and moved to Bergen, where it is the 10th: held, as their unit
        says. Read on the day of the unit the course was given in they were shown as free."""
        batch, treatment, until = self.treated_there(2, 1)
        self.moved_here(batch)
        self.assertEqual(self.harvest_warned(self.t2), ['withdrawal'])
        # one part: K-01, which they left on the 10th, has no fish of theirs on its 11th
        self.assertEqual(self.assert_the_list_says_what_the_units_own_line_says(treatment, [self.t2, self.k1]),
                         {(batch.code, ()): True})
        [part] = self.parts(treatment)
        self.assertEqual((part.today, part.withdrawal.until), (self.here, until))
        self.assertContains(self.client.get(reverse('farm:treatments')), '<span class="over-text" title="')

    def test_treated_behind_and_moved_ahead_they_are_free_where_they_are_now(self):
        batch = self.stock(self.t2, count=1000, weight='100', days_ago=10)
        treatment = self.course(self.t2, self.here - DAY, self.here - DAY, days=1)     # free from the 11th
        self.move(batch, self.t2, self.k1, self.here)
        self.assertEqual(self.harvest_warned(self.k1), [])                # the 11th where they are now: free
        # T-02, which they left today, still names them on its own 10th, as its own line does: two parts
        self.assertEqual(self.assert_the_list_says_what_the_units_own_line_says(treatment, [self.k1, self.t2]),
                         {(batch.code, ('K-01',)): False, (batch.code, ('T-02',)): True})

    def test_a_batch_split_over_two_clocks_is_shown_once_for_each_day_with_its_units(self):
        batch = self.stock(self.k1, count=1000, weight='100', days_ago=10)
        # Split AFTER the course's day (S-03, rule B: the hold follows the fish that were in K-01 on it; a part split
        # off before the course is not held at all, rule D: the test after this one).
        self.move(batch, self.k1, self.t2, self.here - DAY, count=400)
        treatment = self.course(self.k1, self.there - 2 * DAY, self.there - 2 * DAY, days=1)   # free from the 11th
        held = self.assert_the_list_says_what_the_units_own_line_says(treatment, [self.k1, self.t2])
        self.assertEqual(held, {(batch.code, ('K-01',)): False, (batch.code, ('T-02',)): True})
        self.assertIsNotNone(self.parts(treatment, show='withdrawal'))    # a part of it is held today
        page = self.client.get(reverse('farm:treatments'))
        self.assertContains(page, f'<strong>{batch.code}</strong> (K-01) · ')
        self.assertContains(page, f'<strong>{batch.code}</strong> (T-02) · <span class="over-text"')

    def test_a_course_given_today_on_the_later_clock_does_not_hold_the_part_split_off_before_it(self):
        """S-03, rule D (before: "the whole batch is held by a course given to a part of it, each part by its own
        site's calendar"): the part in Bergen left K-01 five days before the course, was never in it, and is not held:
        not on the list, not on its unit's line, not at its harvest, and its unit is not blocked (a day-based
        withdrawal). The guard's day is still the earlier one."""
        batch = self.stock(self.k1, count=1000, weight='100', days_ago=10)
        self.move(batch, self.k1, self.t2, self.here - 5 * DAY, count=400)
        treatment = self.course(self.k1, self.there, self.there, days=5)
        self.assertEqual(self.assert_the_list_says_what_the_units_own_line_says(treatment, [self.k1, self.t2]),
                         {(batch.code, ()): True})
        self.assertEqual([(part.where, part.withdrawal.until) for part in self.parts(treatment)],
                         [(('K-01',), self.there + 6 * DAY)])
        self.assertEqual((self.harvest_warned(self.k1), self.harvest_warned(self.t2)), (['withdrawal'], []))
        self.assertEqual(withdrawal._reached([self.t2.pk])[1], self.here)             # the guard's day, the 10th
        self.assertEqual(withdrawal.held_reached([self.t2.pk]), [])
        self.assertIn(batch.code, withdrawal.held_reached([self.k1.pk])[0])


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
        """The review's case E: read on Bergen's 10th, where the fish once were, the course of the 11th had not begun,
        and the list showed no fish and nothing under withdrawal."""
        batch = self.from_bergen(self.os1)
        treatment = self.course(self.os1, self.there, self.there, days=5)              # held to the 16th
        self.assertEqual(self.harvest_warned(self.os1), ['withdrawal'])
        self.assertEqual(self.assert_the_list_says_what_the_units_own_line_says(treatment, [self.os1]),
                         {(batch.code, ()): True})
        [part] = self.parts(treatment)
        self.assertEqual((part.today, part.withdrawal.until), (self.there, self.there + 6 * DAY))

    def test_a_batch_that_arrived_today_in_a_unit_under_a_running_course_is_in_it(self):
        resident = self.stock(self.os1, count=1000, weight='100', days_ago=10)
        treatment = self.course(self.os1, self.there - 2 * DAY, self.there + 2 * DAY, days=1)     # running
        arrived = self.from_bergen(self.os2)
        self.move(arrived, self.os2, self.os1, self.there)                 # today on Oslofjord's clock: the 11th
        self.assertEqual(self.assert_the_list_says_what_the_units_own_line_says(treatment, [self.os1]),
                         {(resident.code, ()): True, (arrived.code, ()): True})

    def test_treated_ahead_and_moved_behind_at_night(self):
        """The company's day has turned too; only Bergen, where the fish are, is still on the 10th."""
        batch, treatment, until = self.treated_there(2, 1)                 # in Tokyo: free from the 11th
        self.moved_here(batch)
        self.assertEqual((local_today(self.k1), local_today()), (self.there, self.there))
        self.assertEqual(self.assert_the_list_says_what_the_units_own_line_says(treatment, [self.t2, self.k1]),
                         {(batch.code, ()): True})
        [part] = self.parts(treatment)
        self.assertEqual((part.today, part.withdrawal.until), (self.here, until))

    def test_degree_days_reached_yesterday_where_the_fish_are_now_free_them_there(self):
        batch = self.from_bergen(self.os1, days_ago=8)
        treatment = self.course(self.os1, self.there - 6 * DAY, self.there - 6 * DAY, degree_days=40)
        self.today = self.there                                             # samples dated on Oslofjord's clock
        for days_ago in range(1, 6):
            self.temperature(self.os1, days_ago, '8')                      # 8 degrees a day, the 6th to the 10th: 40
        self.today = self.here
        self.assertEqual(self.harvest_warned(self.os1), [])                # reached on the 10th: free on the 11th there
        self.assertEqual(self.assert_the_list_says_what_the_units_own_line_says(treatment, [self.os1]),
                         {(batch.code, ()): False})
        [part] = self.parts(treatment)
        self.assertEqual((part.withdrawal.until, part.withdrawal.estimated), (self.there, False))

    def test_a_site_behind_the_company_counts_its_own_running_day(self):
        """The failure of CI's bad hour: on the company's 11th the list counted Bergen's running 10th as a past day
        without a temperature."""
        treatment = self.treat(self.medicine(degree_days=50), 6, 6)        # in T-01: five past days, none measured
        self.assert_the_list_says_what_the_units_own_line_says(treatment, [self.t1])
        [part] = self.parts(treatment)
        self.assertEqual((part.today, part.withdrawal.days_without_temperature), (self.here, 5))


class GuardsOnTwoClocksTests(FrozenClock, ClocksCase):
    """The write guards and what blocks a deletion, for fish under a course begun today on the later clock (the
    review's inference from case E, which a run confirmed: their day is the earliest among the units, the 10th, and
    the course begins on the 11th, so they did not see it). 23:30 UTC on the 10th. The guards' day is unchanged; a
    course that has begun where it was given has begun."""
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
        self.assertContains(refused, f'{self.fish.code} in OS-01 is held', status_code=422)   # the lot: batch, unit
        self.assertEqual(list(self.bath.withdrawals.values_list('days', flat=True)), [5])

    def test_voiding_the_course_begun_today_asks(self):
        with self.assertRaises(withdrawal.WithdrawalChanged) as asked:
            services.void_treatment(self.user, self.given_today, 'Wrong cage')
        self.assertEqual([freed.batch for freed in asked.exception.change.released], [self.fish])

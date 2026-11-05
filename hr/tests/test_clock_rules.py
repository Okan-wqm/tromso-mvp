from datetime import date, time, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from .. import clock, rules
from ..rules import Planned

OSLO, AUCKLAND, PACIFIC = ZoneInfo('Europe/Oslo'), ZoneInfo('Pacific/Auckland'), ZoneInfo('America/Los_Angeles')
NIGHT = SimpleNamespace(starts_at=time(22), ends_at=time(6), break_minutes=0)
DAY = SimpleNamespace(starts_at=time(14), ends_at=time(22), break_minutes=30)
EARLY = SimpleNamespace(starts_at=time(6), ends_at=time(14), break_minutes=30)
SETTINGS = SimpleNamespace(min_rest_minutes=660, standard_week_minutes=2400, max_consecutive_days=6, rest_rule='warn')


def planned(day, shift, zone=OSLO):
    start, end = clock.span(day, shift, zone)
    return Planned(day, start, end, clock.net_minutes(start, end, shift.break_minutes))


class SpanTests(SimpleTestCase):
    def test_a_night_is_as_long_as_the_clocks_make_it(self):
        self.assertEqual(clock.minutes(*clock.span(date(2026, 3, 27), NIGHT, OSLO)), 480)    # an ordinary night
        self.assertEqual(clock.minutes(*clock.span(date(2026, 3, 28), NIGHT, OSLO)), 420)    # clocks forward: 7 h
        self.assertEqual(clock.minutes(*clock.span(date(2026, 10, 24), NIGHT, OSLO)), 540)   # clocks back: 9 h
        self.assertEqual(clock.minutes(*clock.span(date(2026, 10, 25), NIGHT, OSLO)), 480)

    def test_the_instants_are_utc_and_follow_the_sites_zone(self):
        start, end = clock.span(date(2026, 1, 15), EARLY, AUCKLAND)       # UTC+13 in January
        self.assertEqual((start.isoformat(), end.isoformat()), ('2026-01-14T17:00:00+00:00', '2026-01-15T01:00:00+00:00'))
        start, _ = clock.span(date(2026, 1, 15), EARLY, PACIFIC)          # UTC-8
        self.assertEqual(start.isoformat(), '2026-01-15T14:00:00+00:00')

    def test_net_minutes_take_the_break_off(self):
        start, end = clock.span(date(2026, 3, 2), EARLY, OSLO)
        self.assertEqual(clock.net_minutes(start, end, 30), 450)


class RuleTests(SimpleTestCase):
    def found(self, plan, leave=(), holidays=(), weeks=(date(2026, 3, 2),), settings=SETTINGS):
        return [(f.code, f.severity, f.day, f.detail) for f in
                rules.findings(plan, set(leave), set(holidays), settings, weeks)]

    def test_a_night_then_the_afternoon_leaves_eight_hours_not_thirty_two(self):
        # 22:00-06:00 on the 2nd, then 14:00-22:00 on the 3rd: 8 hours of rest (the source computed 1920 minutes)
        plan = [planned(date(2026, 3, 2), NIGHT), planned(date(2026, 3, 3), DAY)]
        self.assertEqual(self.found(plan), [('rest_short', 'warn', date(2026, 3, 3), 480)])

    def test_the_rest_across_the_border_of_the_week_counts(self):
        # Sunday 22:00 to Monday 06:00, then Monday 14:00: the Sunday shift is in the week before the one asked for
        plan = [planned(date(2026, 3, 1), NIGHT), planned(date(2026, 3, 2), DAY)]
        self.assertEqual(self.found(plan), [('rest_short', 'warn', date(2026, 3, 2), 480)])
        self.assertEqual(self.found(plan, weeks=(date(2026, 2, 23),)), [('rest_short', 'warn', date(2026, 3, 2), 480)])
        self.assertEqual(self.found(plan, weeks=(date(2026, 3, 16),)), [])     # far away: not asked for

    def test_the_rest_rule_decides_between_warning_and_blocking(self):
        plan = [planned(date(2026, 3, 2), NIGHT), planned(date(2026, 3, 3), DAY)]
        strict = SimpleNamespace(**{**SETTINGS.__dict__, 'rest_rule': 'block'})
        self.assertEqual(self.found(plan, settings=strict), [('rest_short', 'block', date(2026, 3, 3), 480)])
        self.assertTrue(rules.findings(plan, set(), set(), strict, [date(2026, 3, 2)])[0].blocks)
        lax = SimpleNamespace(**{**SETTINGS.__dict__, 'min_rest_minutes': 480})
        self.assertEqual(self.found(plan, settings=lax), [])                      # exactly the minimum is enough

    def test_the_rest_on_the_night_the_clocks_change_is_read_in_real_time(self):
        # 22:00-06:00 from the 28th (7 h of night), then 17:00 the same day it ends: the gap is 11 h of real time
        plan = [planned(date(2026, 3, 28), NIGHT), planned(date(2026, 3, 29), SimpleNamespace(
            starts_at=time(17), ends_at=time(23), break_minutes=0))]
        self.assertEqual(self.found(plan, weeks=(date(2026, 3, 23),)), [])

    def test_overlapping_shifts_and_a_shift_on_leave_block(self):
        small_hours = SimpleNamespace(starts_at=time(2), ends_at=time(10), break_minutes=0)
        plan = [planned(date(2026, 3, 2), NIGHT), planned(date(2026, 3, 3), small_hours)]    # 02:00 is inside the night
        self.assertEqual(self.found(plan), [('span_overlap', 'block', date(2026, 3, 3), 0)])
        back_to_back = [planned(date(2026, 3, 2), NIGHT), planned(date(2026, 3, 3), EARLY)]   # 06:00 ends, 06:00 starts
        self.assertEqual(self.found(back_to_back), [('rest_short', 'warn', date(2026, 3, 3), 0)])
        self.assertEqual(self.found([planned(date(2026, 3, 4), EARLY)], leave=[date(2026, 3, 4)]),
                         [('leave_overlap', 'block', date(2026, 3, 4), 0)])

    def test_a_long_week_a_long_run_and_a_holiday_warn(self):
        week = [planned(date(2026, 3, 2) + timedelta(days=n), EARLY) for n in range(6)]        # 6 x 7.5 h = 45 h
        self.assertEqual(self.found(week), [('week_hours', 'warn', date(2026, 3, 2), 2700)])
        seven = week + [planned(date(2026, 3, 8), EARLY)]
        got = self.found(seven)
        self.assertIn(('consecutive_days', 'warn', date(2026, 3, 8), 7), got)
        self.assertEqual(self.found([planned(date(2026, 3, 5), EARLY)], holidays=[date(2026, 3, 5)]),
                         [('holiday_work', 'warn', date(2026, 3, 5), 0)])

    def test_a_day_off_breaks_the_run_and_the_standard_week_is_not_a_limit_at_exactly_that(self):
        days = [0, 1, 2, 3, 4, 6]        # Mon-Fri, then Sunday
        plan = [planned(date(2026, 3, 2) + timedelta(days=n), EARLY) for n in days]
        codes = [code for code, *_ in self.found(plan)]
        self.assertNotIn('consecutive_days', codes)
        exact = SimpleNamespace(**{**SETTINGS.__dict__, 'standard_week_minutes': 450 * 6})
        self.assertNotIn('week_hours', [code for code, *_ in self.found(plan, settings=exact)])

    def test_findings_are_for_the_weeks_asked_for_only(self):
        plan = [planned(date(2026, 3, 9), NIGHT), planned(date(2026, 3, 10), DAY)]
        self.assertEqual(self.found(plan), [])                                    # the 9th is in the next week

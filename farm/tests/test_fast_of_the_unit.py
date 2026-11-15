"""The fast before a handling is the fast of the fish in the unit handled (flow fault S-01; the owner's decision 1 of
14.11.2026: fish of two batches in one unit are one group). The check asked "when was this BATCH last fed, in any unit it
was ever in": a tank fasted 87 h was told "15.0 h" because its sibling tank was fed, a sea cage fasted 39 h was stored as
"21.0 h" at a time nobody fed it (the land tanks' feeding on the sea site's clock), and the false sentence went into the
acknowledgement and the critical log. One reader now says it for every page (farm.feeding.read.last_fed_of): this unit's
feedings since the fish came in, the unit they came from up to the day of the move, and so on back along their own
path; nothing else. The cases are those of ops2/RULES.md §1.2 (1 to 9 and 11 to 13; of 9 the read: the question at the
back-dated feeding's own save, and case 10, are another change), the two real ones of Round 1, and the review's: a path
follows the order the transfers happened in WITHIN a day (a unit emptied and refilled on one day, a move there and back,
a grading day)."""
from datetime import time as clock, timedelta
from decimal import Decimal

from django.urls import reverse

from core.models import AuditLog

from ..feeding import read as feeding_read, services as feeding_services
from ..handling import check
from ..handling import fasting
from ..models import Feed, HandlingAcknowledgement, HandlingPlanItem, Site, Tank
from ..stock import read as stock_read, services
from ..stock.dates import local_today, shown_date
from .helpers import going_on
from .test_harvest import HarvestTestCase
from .test_stock import make_unit


class FastTestCase(HarvestTestCase):
    """T-01: 10,000 salmon (batch A) since 20 days. The rules: harvest 72 h, transport 24 h."""

    def setUp(self):
        super().setUp()
        self.t3 = make_unit('T-03', self.hall)

    def move(self, count, days_ago, source=None, to=None, batch=None):
        """`count` fish out of `source` (T-01) into `to` (T-02), going on past the transport's own fast warning."""
        source, day = source or self.t1, self.day(days_ago)
        seen = check.assess('transport', source, day, batch or self.batch).fingerprint
        return services.record_transfer(self.user, source=source, batch=batch or self.batch, day=day,
                                        legs=[(to or self.t2, count)], reason='density', handling_ack=seen)

    def fasted(self, unit, kind='harvest', batch=None):
        """(the unit of the feeding counted from, its day, the hours fasted) of a handling of `unit` today, from the
        warning or, when the fast is long enough, from the reader."""
        fed = feeding_read.last_fed_at(unit, self.today)
        warnings = [each for each in check.assess(kind, unit, self.today, batch).warnings if each.warning == 'fasting']
        hours = warnings[0].fasted_hours if warnings else None
        return (fed.record.unit.code, fed.record.date, hours) if fed else None


class SplitTests(FastTestCase):
    def test_case_1_a_unit_never_split_counts_its_own_latest_feeding(self):
        self.fed(3, at=clock(9, 0))
        self.fed(1, at=clock(18, 0))
        self.assertEqual(self.fasted(self.t1), ('T-01', self.day(1), Decimal('6.0')))

    def test_case_2_a_sibling_fed_after_the_split_does_not_break_the_fast_of_the_fish_moved(self):
        self.fed(6, at=clock(9, 0))                          # the whole batch, in T-01
        self.move(4000, 5)                                   # 4,000 to T-02, which is not fed since
        self.fed(1, at=clock(9, 0))                          # the fish that stayed in T-01, yesterday
        self.assertEqual(self.fasted(self.t1), ('T-01', self.day(1), Decimal('15.0')))
        result = check.assess('harvest', self.t2, self.today, self.batch)
        self.assertEqual([each for each in result.warnings if each.warning == 'fasting'], [])   # 135 h against 72 h
        self.assertIn(f'Last fed {shown_date(self.day(6))} 09:00 in T-01: 135.0 h before {shown_date(self.today)}.',
                      result.notes)
        self.fed(2, at=clock(12, 0), unit=self.t2)           # T-02's own feeding counts from the day they came in
        self.assertEqual(self.fasted(self.t2), ('T-02', self.day(2), Decimal('36.0')))

    def test_case_3_and_the_tank_of_round_1_fasted_87_hours_not_15(self):
        self.fed(4, at=clock(9, 0))                          # the last common feeding, in T-01
        self.move(4000, 3)
        self.move(3000, 3, to=self.t3)
        for unit in (self.t1, self.t2, self.t3):             # split after the last feeding: all three count from it
            with self.subTest(unit=unit.code):
                self.assertEqual(feeding_read.last_fed_at(unit, self.today).record.unit, self.t1)
                self.assertEqual(check.assess('harvest', unit, self.today).warnings, [])      # 87 h against 72 h
        self.fed(1, at=clock(9, 0), unit=self.t2)            # only T-02 is fed again
        self.fed(1, at=clock(9, 0), unit=self.t3)
        self.assertEqual(self.fasted(self.t2), ('T-02', self.day(1), Decimal('15.0')))
        self.assertEqual(self.fasted(self.t1), ('T-01', self.day(4), None))                   # T-01 still fasts: 87 h
        self.assertIn(f'Last fed {shown_date(self.day(4))} 09:00 in T-01: 87.0 h before {shown_date(self.today)}.',
                      check.assess('harvest', self.t1, self.today).notes)

    def test_the_old_units_feedings_after_the_fish_left_do_not_count_and_the_move_day_does(self):
        self.fed(5, at=clock(9, 0))
        self.move(4000, 4)
        self.fed(4, at=clock(9, 0))                          # T-01 on the day of the move: it counts (the move has no time)
        self.fed(3, at=clock(9, 0))                          # T-01 the day after: the fish in T-02 were not there
        self.assertEqual(feeding_read.last_fed_at(self.t2, self.today).record.date, self.day(4))

    def test_a_unit_fed_before_these_fish_came_into_it_does_not_count_for_them(self):
        other = self.stock(self.t2, count=1000, days_ago=15)
        self.fed(9, at=clock(9, 0), unit=self.t2)            # the fish that were in T-02 then
        services.record_harvest(self.user, unit=self.t2, batch=other, day=self.day(8), count=1000,
                                measured_weight_kg=Decimal('55'), facility=self.facility, everything=True,
                                handling_ack=check.assess('harvest', self.t2, self.day(8), other).fingerprint)
        self.fed(6, at=clock(9, 0))                          # batch A, still in T-01
        self.move(4000, 5)                                   # into T-02, empty since the harvest
        fed = feeding_read.last_fed_at(self.t2, self.today)
        self.assertEqual((fed.record.unit, fed.record.date), (self.t1, self.day(6)))


class MixedUnitTests(FastTestCase):
    """Case 4 and 5: T-02 holds batch B, fed 2 days ago 09:00 (39 h); 500 fish of A, fed in T-01 yesterday 18:00 (6 h),
    come into it today."""

    def setUp(self):
        super().setUp()
        self.b = self.stock(self.t2, count=3000, weight='50', days_ago=12)
        self.fed(2, at=clock(9, 0), unit=self.t2)
        self.fed(1, at=clock(18, 0))
        self.move(500, 0)

    def test_one_fast_for_the_unit_whichever_batch_is_named_and_the_least_fasted_fish_decide(self):
        found = {}
        for name, batch in (('B', self.b), ('A', self.batch), ('none', None)):
            result = check.assess('harvest', self.t2, self.today, batch)
            [warning] = [each for each in result.warnings if each.warning == 'fasting']
            self.assertEqual((warning.fed.record.unit, warning.fasted_hours), (self.t1, Decimal('6.0')), name)
            self.assertIn(f'Last fed {shown_date(self.day(1))} 18:00 in T-01, 6.0 h before', warning.message())
            found[name] = result.fingerprint
        self.assertEqual(len(set(found.values())), 1)        # one box value: the answer does not follow the batch

    def test_before_the_fish_arrived_the_unit_counted_its_own_feeding(self):
        [warning] = [each for each in check.assess('harvest', self.t2, self.day(1), self.b).warnings]
        self.assertEqual((warning.fed.record.unit, warning.fasted_hours), (self.t2, Decimal('15.0')))

    def test_the_dialog_of_either_batch_shows_the_same_fast(self):
        url = reverse('farm:stock_harvest', args=[self.t2.pk])
        for batch in (self.b, self.batch):
            page = self.client.get(url, {'batch': str(batch.pk)})
            self.assertContains(page, f'Last fed {shown_date(self.day(1))} 18:00 in T-01, 6.0 h before')


class WhatCountsTests(FastTestCase):
    def test_case_7_medicated_feed_is_feed(self):
        medicated = Feed.objects.create(name='Medisinfor', code='MED-1', feed_type='medicated', pellet_size_mm=Decimal(4))
        self.fed(3, at=clock(9, 0))
        going_on(feeding_services.record_feeding, self.user, unit=self.t1, day=self.day(1), feed=medicated,
                 amount_kg=Decimal('5'), time=clock(18, 0))
        [warning] = [each for each in check.assess('harvest', self.t1, self.today).warnings if each.warning == 'fasting']
        self.assertEqual((warning.fed.record.feed, warning.fasted_hours), (medicated, Decimal('6.0')))

    def test_case_8_a_feeding_without_a_time_counts_from_the_end_of_its_day_and_names_its_unit(self):
        self.fed(3)
        [warning] = check.assess('harvest', self.t1, self.today).warnings
        self.assertEqual(warning.fasted_hours, Decimal('48.0'))
        self.assertEqual(warning.message(),
                         f'Last fed {shown_date(self.day(3))} (no time recorded: counted from the end of the day) in '
                         f'T-01, 48.0 h before {shown_date(self.today)}: the harvest rule asks for 72 h.')

    def test_the_acknowledgement_and_the_critical_log_line_name_the_feeding_and_its_unit(self):
        counted = self.fed(4, at=clock(9, 0))                # in T-01, before the move
        self.move(4000, 3)
        self.rule('harvest', 120)                            # 87 h is too short for this farm's rule
        url = reverse('farm:stock_harvest', args=[self.t2.pk])
        form = self.client.get(url).context['form']
        data = {'token': form['token'].value(), 'batch': str(self.batch.pk), 'date': self.today.isoformat(),
                'count': '100', 'measured_weight_kg': '5.5', 'facility': str(self.facility.pk), 'notes': '',
                'handling_ack': form.handling.fingerprint}
        self.assertEqual(self.client.post(url, data).status_code, 302)
        row = HandlingAcknowledgement.objects.get(warning='fasting', operation__kind='harvest')
        self.assertEqual((row.feeding, row.feeding.unit, row.fasted_hours, row.required_hours),
                         (counted, self.t1, Decimal('87.0'), 120))
        entry = AuditLog.objects.get(entity_type='stock operation', action='create', entity_id=str(row.operation_id))
        self.assertEqual(entry.severity, 'critical')
        self.assertIn(f'Last fed {shown_date(self.day(4))} 09:00 in T-01, 87.0 h before {shown_date(self.today)}: the '
                      'harvest rule asks for 120 h.', entry.changes['Handling warnings acknowledged'][1])

    def test_the_units_list_and_the_drawer_read_the_same_feeding(self):
        self.fed(4, at=clock(9, 0))
        self.move(4000, 3)
        self.fed(1, at=clock(9, 0))                          # the fish that stayed
        figures = feeding_read.figures(stock_read.stock_of([self.t1, self.t2]))
        self.assertEqual((figures[self.t1.pk].last_fed, figures[self.t1.pk].last_fed_in), (self.day(1), None))
        self.assertEqual((figures[self.t2.pk].last_fed, figures[self.t2.pk].last_fed_in), (self.day(4), self.t1))

    def test_the_earliest_harvest_date_is_the_units_too(self):
        self.fed(4, at=clock(9, 0))
        self.move(4000, 3)
        self.fed(1, at=clock(9, 0))                          # T-01 is fed again: its purge starts over
        self.assertEqual(check.earliest(self.t2, self.batch).decides, '')            # 87 h: nothing holds T-02
        self.assertEqual(check.earliest(self.t1, self.batch).decides, 'purging')


class OtherClockTests(FastTestCase):
    """Case 11 and the sea cage of Round 1: the land site on UTC, the sea site on New York's clock."""

    def setUp(self):
        super().setUp()
        Site.objects.filter(pk=self.tromso.pk).update(timezone='America/New_York')
        self.m1 = make_unit('M-01', self.sea, 'pond', status=Tank.Status.ACTIVE)
        self.m1 = Tank.objects.select_related('production_department__site').get(pk=self.m1.pk)
        self.there = local_today(self.m1)                    # the cage's own today

    def to_sea(self, days_before):
        day = self.there - timedelta(days=days_before)
        seen = check.assess('transport', self.t1, day, self.batch).fingerprint
        services.record_transfer(self.user, source=self.t1, batch=self.batch, day=day, legs=[(self.m1, 3000)],
                                 reason='density', handling_ack=seen)

    def give(self, unit, day, at):
        return feeding_services.record_feeding(self.user, unit=unit, day=day, feed=self.feed, amount_kg=Decimal('5'),
                                               time=at)

    def test_the_cage_fasted_39_hours_whatever_the_land_tanks_were_fed(self):
        self.to_sea(5)
        own = self.give(self.m1, self.there - timedelta(days=2), clock(9, 0))         # 09:00 on the cage's clock
        self.give(self.t1, self.there - timedelta(days=1), clock(9, 0))               # the land tank, the day after
        [warning] = [each for each in check.assess('harvest', self.m1, self.there).warnings
                     if each.warning == 'fasting']
        self.assertEqual((warning.fed.record, warning.fasted_hours), (own, Decimal('39.0')))
        self.assertIn(f'Last fed {shown_date(self.there - timedelta(days=2))} 09:00 in M-01, 39.0 h before',
                      warning.message())
        self.assertNotIn('on the clock of', warning.message())                         # its own unit, its own clock

    def test_a_feeding_in_the_unit_they_came_from_is_said_on_its_own_clock_and_on_the_cages(self):
        fed = self.give(self.t1, self.there - timedelta(days=4), clock(9, 0))         # 09:00 UTC, in the land tank
        self.to_sea(3)                                                                 # never fed in the cage
        found = feeding_read.last_fed_at(self.m1, self.there)
        self.assertEqual(found.record, fed)
        text = check.fed_when(found, self.m1)
        self.assertIn('09:00 in T-01 (', text)                                         # when and where it was given
        self.assertIn(' on the clock of M-01)', text)                                  # and what that is at the cage
        self.assertNotIn('09:00 on the clock', text)                                   # nobody fed the cage at 09:00


class SameDayTests(FastTestCase):
    """Transfers have a day and no time: within a day they happened in the order they were entered, the ledger's own
    order, and a path follows it (review F-02). Read by day, the lines entered after the fish left a unit were taken
    for their stay there: a tank fed 39 h before its harvest was told nothing, or "the fast is not checked"."""

    def fasting(self, unit, kind='harvest'):
        result = check.assess(kind, unit, self.today)
        return result, [each for each in result.warnings if each.warning == 'fasting']

    def test_a_unit_emptied_and_refilled_with_the_same_fish_on_one_day_keeps_its_last_feeding(self):
        self.fed(2, at=clock(9, 0))                                   # T-01, 39 h before today
        self.move(10000, 1)                                           # every fish to T-02 ...
        self.move(10000, 1, source=self.t2, to=self.t1)               # ... and back the same day
        result, warnings = self.fasting(self.t1)
        self.assertEqual([(each.fed.record.unit, each.fed.record.date, each.fasted_hours) for each in warnings],
                         [(self.t1, self.day(2), Decimal('39.0'))])
        self.assertIn(f'Last fed {shown_date(self.day(2))} 09:00 in T-01, 39.0 h before', warnings[0].message())
        self.assertFalse([note for note in result.notes if 'the fast is not checked' in note], result.notes)
        figures = feeding_read.figures(stock_read.stock_of([self.t1]))[self.t1.pk]
        self.assertEqual((figures.last_fed, figures.last_fed_in), (self.day(2), None))

    def test_the_unit_the_fish_passed_through_that_day_is_on_their_path(self):
        """(A feeding of a unit that holds no fish at the start or the end of its day is refused by the feeding service,
        so none can be recorded there; the path still names the unit, for the day.)"""
        self.move(10000, 1)
        self.move(10000, 1, source=self.t2, to=self.t1)
        where = feeding_read.fed_where(stock_read.ledger([self.batch.pk]), self.t1.pk, [self.batch.pk], self.today)
        self.assertEqual(sorted((place.unit_id == self.t1.pk, place.first, place.last) for place in where),
                         [(False, self.day(1), self.day(1)),                 # T-02, that day
                          (True, self.day(20), self.day(1)),                 # T-01 up to the move out
                          (True, self.day(1), self.today)])                  # T-01 since they came back

    def test_a_grading_day_the_fish_moved_out_before_others_came_in_keep_their_own_feeding(self):
        self.fed(12, at=clock(9, 0))                                  # the whole batch, in T-01
        self.move(3000, 10, to=self.t3)                               # 3,000 to T-03, not fed since
        self.fed(2, at=clock(9, 0))                                   # the 7,000 that stayed in T-01
        self.move(7000, 1)                                            # T-01's 7,000 into T-02 ...
        self.move(3000, 1, source=self.t3, to=self.t1)                # ... then T-03's 3,000 into T-01, the same day
        result, warnings = self.fasting(self.t2)
        self.assertEqual([(each.fed.record.unit, each.fed.record.date, each.fasted_hours) for each in warnings],
                         [(self.t1, self.day(2), Decimal('39.0'))])
        self.assertFalse([note for note in result.notes if 'Last fed' in note], result.notes)
        # The fish now in T-01 came from T-03 after the 7,000 had left: the feeding of the 7,000 is not theirs.
        self.assertEqual(self.fasted(self.t1), ('T-01', self.day(12), None))
        figures = feeding_read.figures(stock_read.stock_of([self.t1, self.t2]))
        self.assertEqual((figures[self.t2.pk].last_fed, figures[self.t2.pk].last_fed_in), (self.day(2), self.t1))
        self.assertEqual((figures[self.t1.pk].last_fed, figures[self.t1.pk].last_fed_in), (self.day(12), None))

    def test_the_other_order_on_a_grading_day_is_read_as_entered(self):
        self.fed(12, at=clock(9, 0))
        self.move(3000, 10, to=self.t3)
        self.fed(2, at=clock(9, 0))
        self.move(3000, 1, source=self.t3, to=self.t1)                # T-03's 3,000 join the 7,000 first ...
        self.move(10000, 1)                                           # ... then all of T-01 goes to T-02
        self.assertEqual(self.fasted(self.t2), ('T-01', self.day(2), Decimal('39.0')))

    def test_fish_moved_out_and_back_on_other_days_bring_what_they_were_fed_there(self):
        self.fed(6, at=clock(9, 0))
        self.move(4000, 5)                                            # 4,000 to T-02
        self.fed(4, at=clock(9, 0))                                   # the 6,000 in T-01
        self.fed(3, at=clock(9, 0), unit=self.t2)                     # the 4,000 in T-02
        self.move(4000, 2, source=self.t2, to=self.t1)                # and back beside the others
        self.assertEqual(self.fasted(self.t1), ('T-02', self.day(3), Decimal('63.0')))


class LaterRecordsTests(FastTestCase):
    def test_case_9_a_feeding_back_dated_after_the_harvest_changes_the_answer_at_once(self):
        """Nothing is stored on read: the check of the harvest's day says the back-dated feeding the moment it is
        entered. (The question at that feeding's own save is not built: another change.)"""
        self.fed(5, at=clock(9, 0))
        self.assertEqual(check.assess('harvest', self.t1, self.day(1)).warnings, [])      # 87 h against 72 h
        self.harvest(count=100, kilos='5.5', days_ago=1)                                  # no tick was needed
        self.fed(2, at=clock(9, 0))                                                       # entered afterwards
        [warning] = check.assess('harvest', self.t1, self.day(1)).warnings
        self.assertEqual((warning.warning, warning.fasted_hours, warning.fed.record.date),
                         ('fasting', Decimal('15.0'), self.day(2)))


class PlannedFastTests(FastTestCase):
    """Cases 12 and 13: the days the meal board shows "Fasting" for a planned harvest and the days on which a feeding
    makes the harvest's check warn are the same days, of the same unit."""

    def plan(self, unit, batch=None):
        return HandlingPlanItem.objects.create(kind='harvest', date=self.today, unit=unit, batch=batch or self.batch,
                                               facility=self.facility)

    def test_case_12_the_board_fasts_on_the_days_a_feeding_would_make_the_check_warn(self):
        self.plan(self.t1)
        board = fasting.fasts([self.t1], self.day(5), self.today)
        for days_ago in (5, 4, 3, 2, 1, 0):                           # one more feeding each round: the latest decides
            self.fed(days_ago, at=clock(12, 0))
            warned = bool(check.assess('harvest', self.t1, self.today).warnings)
            with self.subTest(days_ago=days_ago):
                self.assertEqual((self.t1.pk, self.day(days_ago)) in board, warned)
        self.assertEqual(sorted(day for _unit, day in board), [self.day(3), self.day(2), self.day(1), self.today])

    def test_case_12_a_unit_not_fed_inside_the_window_passes_whatever_its_sibling_was_fed(self):
        self.fed(6, at=clock(9, 0))
        self.move(4000, 5)                                            # 4,000 to T-02, planned for harvest today
        self.plan(self.t2)
        self.fed(1, at=clock(9, 0))                                   # the sibling tank, inside T-02's window
        self.assertEqual(check.assess('harvest', self.t2, self.today).warnings, [])
        board = fasting.fasts([self.t1, self.t2], self.day(1), self.day(1))
        self.assertEqual(list(board), [(self.t2.pk, self.day(1))])    # the planned unit fasts, its sibling does not

    def test_case_13_fish_moved_in_during_the_window_decide_by_their_own_path(self):
        other = self.stock(self.t2, count=3000, weight='50', days_ago=12)
        self.fed(6, at=clock(9, 0), unit=self.t2)                     # T-02's own fish: 135 h
        self.plan(self.t2, other)
        self.fed(2, at=clock(9, 0))                                   # T-01, inside T-02's window
        self.assertEqual(check.assess('harvest', self.t2, self.today).warnings, [])
        self.move(500, 1)                                             # 500 of them come into T-02 during the window
        [warning] = check.assess('harvest', self.t2, self.today, other).warnings
        self.assertEqual((warning.fed.record.unit, warning.fasted_hours), (self.t1, Decimal('39.0')))


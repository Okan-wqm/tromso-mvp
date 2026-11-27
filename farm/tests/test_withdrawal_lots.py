"""Which fish a medicine withdrawal holds (flow fault S-03; the owner, 14.11.2026; RULES 2.2 A to E): the fish that were
EXPOSED, not their batch.

A. The fish of a batch that were in a treated unit on a course day are held.
B. The hold follows them wherever they are moved.
C. A unit that holds any held fish is held as a whole, for every batch in it; fish that shared a unit with held fish
   stay held to the same end after they are moved on (the owner's example: tank C held to 23.11).
D. Fish of the same batch that left the treated unit before the first course day, or were never in it, are not held.
E. A medicine with no withdrawal row and a medicated feeding with no treatment hold the same fish, end unknown.

Every reader says the same fact: the unit's line (the units list, the card, `check_withdrawal`'s "held now"), the
harvest check and its stored acknowledgement, the Treatments list, the harvests inside a withdrawal, the withdrawal
guard (a harvest brought inside, fish released) and what blocks a deletion. RULES 2.2's ten cases are the classes
below, by number."""
import io
from decimal import Decimal

from django.core.management import call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from core.models import AuditLog

from .. import withdrawal_gate
from ..feeding import services as feeding_services
from ..handling import check
from ..health import services, withdrawal
from ..health.withdrawal import WithdrawalChanged
from ..models import (Batch, Feed, HandlingAcknowledgement, Medicine, MedicineWithdrawal, Treatment,
                      WithdrawalAcknowledgement)
from ..stock import services as stock_services
from ..stock.dates import shown_date
from .helpers import going_on, may_record, point_of
from .test_harvest_inside_withdrawal import HarvestInsideTestCase
from .test_stock import make_unit
from .test_withdrawal_cleaner_fish import CleanerWithdrawalTestCase


class LotsTestCase(HarvestInsideTestCase):
    """T-01: batch A, 2,000 fish since 10 days. T-02, T-03, T-04: empty. `bath`: 7 days."""

    def setUp(self):
        super().setUp()
        self.a = self.batch
        self.t3, self.t4 = make_unit('T-03', self.hall), make_unit('T-04', self.hall)
        self.bath = self.medicine(days=7)

    def move(self, batch, source, target, days_ago, count=500, combines=(), **fields):
        """A transfer. `combines`: the lots [(batch, unit code)] the move must be ASKED about, because it combines
        them with held fish (the owner's decision 8, farm/tests/test_withdrawal_combined.py); the question is then
        ticked. A question the test does not expect fails it, and so does an expected one that is not asked: nothing
        is ticked silently (verification V-10). A harvest brought inside or fish released are never expected here."""
        def record(**more):
            return stock_services.record_transfer(self.user, source=source, batch=batch, day=self.day(days_ago),
                                                  legs=[(target, count)], reason='density', **fields, **more)
        if 'withdrawal_ack' in fields:
            return record()
        expected = sorted((each.code, unit) for each, unit in combines)
        try:
            operation = record()
        except WithdrawalChanged as asked:
            found = asked.change
            self.assertEqual((sorted((each.batch.code, each.unit.code) for each in found.combined),
                              found.harvested, found.released), (expected, [], []), found.messages())
            return record(withdrawal_ack=found.fingerprint)
        self.assertEqual(expected, [], 'the move was expected to ask about the fish it combines, and did not')
        return operation

    def ends(self, unit, day=None):
        """[(the batch held, the first day it may be harvested)] of the unit's own withdrawal line."""
        return [(self.code(held.batch_id), held.until) for held in self.held(unit, day)]

    def code(self, batch_id):
        return Batch.all_objects.get(pk=batch_id).code

    def warned(self, unit, batch=None, day=None):
        """[(the batch named, the end)] of the withdrawal warnings of a harvest of the unit, and the notes."""
        result = check.assess('harvest', unit, day or self.today, batch)
        return ([(each.block.batch.code, each.block.until) for each in result.warnings if each.warning == 'withdrawal'],
                result.notes)

    def command(self):
        out = io.StringIO()
        call_command('check_withdrawal', stdout=out)
        return out.getvalue()

    def listed(self, treatment):
        """[(batch, units, held)] of a treatment's row of the Treatments list."""
        return [(part.batch.code, part.where, part.held)
                for part in withdrawal.of_treatments([Treatment.all_objects.prefetch_related('units').get(
                    pk=treatment.pk)])[treatment.pk]]

    def harvest_of(self, unit, batch, days_ago=0, count=100, **fields):
        seen = check.assess('harvest', unit, self.day(days_ago), batch).fingerprint
        return stock_services.record_harvest(self.user, unit=unit, batch=batch, day=self.day(days_ago), count=count,
                                             measured_weight_kg=Decimal(count) / 8, facility=self.facility,
                                             handling_ack=seen or None, **fields)


class Case1SplitBeforeTheCourseTests(LotsTestCase):
    """800 of A go to T-02 six days ago; T-01 is bathed five days ago: harvest from 3 days ahead."""

    def setUp(self):
        super().setUp()
        self.move(self.a, self.t1, self.t2, 6, 800)
        self.treatment = self.treat(self.bath, 5, 5)
        self.until = self.day(-3)

    def test_the_tank_split_off_before_the_course_is_not_held_on_any_page(self):
        self.assertEqual(self.ends(self.t1), [(self.a.code, self.until)])
        self.assertEqual(self.ends(self.t2), [])                                    # the unit's line, the card
        self.assertEqual(self.warned(self.t1)[0], [(self.a.code, self.until)])
        warnings, notes = self.warned(self.t2)
        self.assertEqual(warnings, [])
        self.assertIn('No medicine withdrawal in force.', notes)
        self.assertEqual(check.earliest(self.t2, self.a).decides, '')
        self.assertEqual(check.earliest(self.t1, self.a).day, self.until)
        self.assertEqual(self.listed(self.treatment), [(self.a.code, ('T-01',), True)])
        self.assertIn('1 of 2 units with fish are under a medicine withdrawal.', self.command())

    def test_its_harvest_needs_no_tick_and_is_not_inside_the_withdrawal(self):
        self.harvest_of(self.t2, self.a)                                            # no box, nothing asked
        self.assertFalse(HandlingAcknowledgement.objects.exists())
        self.assertEqual(withdrawal.harvests_inside(), [])
        self.assertIn('No harvest lies inside a medicine withdrawal.', self.command())
        # The treated tank's harvest is asked and listed, as before.
        operation = self.harvest_of(self.t1, self.a)
        self.assertEqual([found.operation_id for found in withdrawal.harvests_inside()], [operation.pk])

    def test_only_the_treated_tank_blocks_a_delete(self):
        self.assertEqual(self.t2.withdrawal_blockers(), [])
        [reason] = self.t1.withdrawal_blockers()
        self.assertIn(self.a.code, reason)
        # T-04 holds nothing and never did: nothing of a hold elsewhere blocks it (RULES case 9, data F4).
        self.assertEqual(self.t4.withdrawal_blockers(), [])


class Case2SplitDuringOrAfterTheCourseTests(LotsTestCase):
    """T-01 is bathed from 5 to 3 days ago (harvest from 5 days ahead)."""

    def setUp(self):
        super().setUp()
        self.treatment = self.treat(self.bath, 5, 3)
        self.until = self.day(-5)

    def test_fish_moved_out_during_the_course_are_held_where_they_are_to_the_same_end(self):
        self.move(self.a, self.t1, self.t2, 4)                                      # day 2 of 3
        self.assertEqual(self.ends(self.t1), [(self.a.code, self.until)])
        self.assertEqual(self.ends(self.t2), [(self.a.code, self.until)])
        self.assertEqual(self.warned(self.t2)[0], [(self.a.code, self.until)])
        self.assertEqual(self.listed(self.treatment), [(self.a.code, ('T-01', 'T-02'), True)])
        self.assertIn('2 of 2 units with fish are under a medicine withdrawal.', self.command())
        self.assertIn('These fish were treated in T-01.', withdrawal.describe(self.held(self.t2)[0]))
        self.assertTrue(self.t2.withdrawal_blockers())

    def test_fish_moved_out_after_the_course_and_moved_on_again_are_held(self):
        self.move(self.a, self.t1, self.t2, 2)
        self.move(self.a, self.t2, self.t3, 1, 200)
        for unit in (self.t1, self.t2, self.t3):
            self.assertEqual(self.ends(unit), [(self.a.code, self.until)], unit.code)
        self.assertEqual(self.ends(self.t3, self.until), [])                        # free on the first free day
        self.assertEqual(self.ends(self.t3, self.day(-4)), [(self.a.code, self.until)])     # held on the last day

    def test_fish_moved_out_on_the_first_course_day_are_held_and_the_day_before_it_are_not(self):
        self.move(self.a, self.t1, self.t2, 5, 300)                                 # the first course day: no time
        # The day before: these fish are out of the course's reach, which the guard asks about (they were held).
        change = self.change_of(self.move, self.a, self.t1, self.t3, 6, 300, withdrawal_ack=None)
        self.assertEqual([(each.batch.code, each.unit.code, each.freed) for each in change.released],
                         [(self.a.code, 'T-03', True)])
        self.move(self.a, self.t1, self.t3, 6, 300, withdrawal_ack=change.fingerprint)
        self.assertEqual(self.ends(self.t2), [(self.a.code, self.until)])
        self.assertEqual(self.ends(self.t3), [])


class Case3And4SharedUnitTests(LotsTestCase):
    """T-01 (A) is bathed 6 days ago: harvest from 2 days ahead. T-02: batch B, 3,000 fish, never treated."""

    def setUp(self):
        super().setUp()
        self.b = self.stock(self.t2, count=3000, days_ago=9)
        self.treatment = self.treat(self.bath, 6, 6)
        self.until = self.day(-2)

    def test_case_3_treated_fish_moved_in_beside_an_untreated_batch_hold_the_unit_and_the_cause_is_named(self):
        self.move(self.a, self.t1, self.t2, 4, combines=[(self.b, 'T-02')])
        self.assertEqual(self.ends(self.t2), [(self.a.code, self.until)])
        self.assertIn('These fish were treated in T-01.', withdrawal.describe(self.held(self.t2)[0]))
        for batch in (self.a, self.b):
            self.assertEqual(self.warned(self.t2, batch)[0], [(self.a.code, self.until)])
        self.assertEqual(self.listed(self.treatment),
                         [(self.a.code, ('T-01', 'T-02'), True), (self.b.code, ('T-02',), True)])

    def test_case_4_the_owners_example_untreated_fish_that_shared_the_held_unit_stay_held_after_they_move_on(self):
        """Tank A treated and held; 500 untreated fish of tank B moved into A; those 500 moved on to tank C before
        the end: tank C is held to the same end (the owner, 14.11.2026)."""
        self.move(self.b, self.t2, self.t1, 4, combines=[(self.b, 'T-01')])   # 500 of B into the held T-01
        self.move(self.b, self.t1, self.t3, 2)                                      # and on to the empty T-03
        self.assertEqual(self.ends(self.t3), [(self.b.code, self.until)])
        self.assertEqual(self.ends(self.t3, self.day(-1)), [(self.b.code, self.until)])     # to the same end
        self.assertEqual(self.ends(self.t3, self.until), [])
        self.assertEqual(self.ends(self.t2), [])                # B's fish that never left T-02 met no held fish
        [held] = self.held(self.t3)
        said = f'These fish shared T-01 with {self.a.code} (treated in T-01).'
        self.assertIn(said, withdrawal.describe(held))
        # The pages, the stored acknowledgement and the critical log line say the same fact.
        warnings, _notes = self.warned(self.t3, self.b)
        self.assertEqual(warnings, [(self.b.code, self.until)])
        operation = self.harvest_of(self.t3, self.b)
        row = HandlingAcknowledgement.objects.get(operation=operation)
        self.assertEqual((row.operation, row.batch, row.withdrawal_until, row.withdrawal_source),
                         (operation, self.b, self.until, f'treatment:{self.treatment.pk}'))
        self.assertIn(said, row.withdrawal_reason)
        entry = AuditLog.objects.get(entity_type='stock operation', action='create', entity_id=str(operation.pk))
        self.assertEqual(entry.severity, 'critical')
        self.assertIn(said, entry.changes['Handling warnings acknowledged'][1])
        out = self.command()
        self.assertIn(f'T-03 · {self.b.code}: harvest from {self.until.isoformat()}. {said}', out)
        self.assertIn(f'lies inside a withdrawal of {self.a.code}, through T-01 shared with {self.a.code}', out)
        self.assertIn('Acknowledged when the harvest was recorded.', out)
        self.assertEqual(self.listed(self.treatment),
                         [(self.a.code, ('T-01',), True), (self.b.code, ('T-03',), True)])
        self.assertTrue(self.t3.withdrawal_blockers())
        self.assertEqual(self.t2.withdrawal_blockers(), [])

    def test_the_dialog_of_the_unit_they_moved_on_to_warns_and_takes_its_box(self):
        self.move(self.b, self.t2, self.t1, 4, combines=[(self.b, 'T-01')])
        self.move(self.b, self.t1, self.t3, 2)
        shown = self.client.get(reverse('farm:stock_harvest', args=[self.t3.pk]))
        self.assertContains(shown, f'medicine withdrawal of {self.b.code}')
        self.assertContains(shown, f'These fish shared T-01 with {self.a.code} (treated in T-01).')
        self.assertContains(shown, 'name="handling_ack"')
        self.assertNotContains(shown, 'No medicine withdrawal in force.')

    def test_v02_held_fish_that_pass_through_a_unit_hold_its_fish_after_the_day_too(self):
        self.move(self.a, self.t1, self.t2, 4, combines=[(self.b, 'T-02')])   # into T-02 beside B
        self.move(self.a, self.t2, self.t3, 4)                                      # and out again the same day
        self.assertEqual(self.ends(self.t2, self.day(4)), [(self.a.code, self.until)])
        self.assertEqual(self.ends(self.t2), [(self.b.code, self.until)])           # the day after, and today
        self.assertIn(f'These fish shared T-02 with {self.a.code} (treated in T-01).',
                      withdrawal.describe(self.held(self.t2)[0]))
        self.assertEqual(self.ends(self.t3), [(self.a.code, self.until)])

    def test_v01_fish_that_pass_through_the_bathed_unit_on_the_bath_day_are_held_and_not_their_batch(self):
        self.move(self.b, self.t2, self.t1, 6, combines=[(self.b, 'T-01')])   # 500 of B into T-01 on the bath day
        self.move(self.b, self.t1, self.t3, 6)                                      # and on to T-03 the same day
        self.assertEqual(self.ends(self.t3), [(self.b.code, self.until)])           # they were bathed
        self.assertEqual(self.ends(self.t2), [])                                    # the 2,500 that never moved
        self.assertEqual(self.warned(self.t2)[0], [])
        self.assertIn('2 of 3 units with fish are under a medicine withdrawal.', self.command())

    def test_a_harvest_on_the_last_day_of_the_lot_is_inside(self):
        self.move(self.b, self.t2, self.t1, 4, combines=[(self.b, 'T-01')])
        self.move(self.b, self.t1, self.t3, 2)
        operation = self.harvest_of(self.t3, self.b, count=500, everything=True)    # T-03 is empty after it
        [found] = withdrawal.harvests_inside()
        self.assertEqual((found.operation_id, found.batch, found.line.batch, found.until),
                         (operation.pk, self.a, self.b, self.until))
        self.assertEqual(self.ends(self.t3), [(self.b.code, self.until)])           # the day they left still counts
        self.assertEqual(self.ends(self.t3, self.day(-1)), [])                      # no fish: no line

    def test_a_transfer_there_and_back_leaves_the_unit_passed_through_free_for_other_fish(self):
        self.move(self.a, self.t1, self.t3, 5)                                      # 500 of A to T-03
        self.move(self.a, self.t3, self.t1, 4)                                      # and back the next day
        self.assertEqual(self.ends(self.t1), [(self.a.code, self.until)])
        self.assertEqual(self.ends(self.t3, self.day(4)), [(self.a.code, self.until)])
        self.assertEqual(self.ends(self.t3), [])
        self.move(self.b, self.t2, self.t3, 2)                  # B comes into the empty T-03 two days after A left it
        self.assertEqual(self.ends(self.t3), [])
        self.assertEqual(self.t3.withdrawal_blockers(), [])


class TwoTreatmentsMeetTests(LotsTestCase):
    """A (T-01) bathed 6 days ago, 7 days: harvest from 2 days ahead. B (T-02) bathed 5 days ago with a 14-day
    medicine: harvest from 10 days ahead. 500 of each meet in T-03."""

    def setUp(self):
        super().setUp()
        self.b = self.stock(self.t2, count=3000, days_ago=9)
        self.treat(self.bath, 6, 6)
        self.treat(self.medicine(name='Alpha Max', days=14), 5, 5, units=[self.t2])
        self.short, self.long = self.day(-2), self.day(-10)
        self.move(self.a, self.t1, self.t3, 3)
        self.move(self.b, self.t2, self.t3, 3, combines=[(self.a, 'T-03')])    # A now waits for B's longer end

    def test_the_later_end_decides_for_the_unit_and_both_causes_are_said(self):
        self.assertCountEqual(self.ends(self.t3), [(self.a.code, self.short), (self.b.code, self.long)])
        found = check.earliest(self.t3, self.a)
        self.assertEqual((found.decides, found.day), ('withdrawal', self.long))
        self.assertEqual(self.ends(self.t3, self.short), [(self.b.code, self.long)])

    def test_fish_of_the_short_withdrawal_carry_the_long_one_on(self):
        self.move(self.a, self.t3, self.t4, 1, 100)             # A's fish, which shared T-03 with B's, into T-04
        self.assertEqual(sorted(self.ends(self.t4), key=lambda each: each[1]),
                         [(self.a.code, self.short), (self.a.code, self.long)])
        self.assertEqual(check.earliest(self.t4, self.a).day, self.long)
        self.assertEqual(self.ends(self.t1), [(self.a.code, self.short)])           # T-01 met nobody


class Case5And6UnknownEndTests(LotsTestCase):
    def test_case_5_a_medicine_with_no_withdrawal_row_holds_the_same_fish_end_unknown(self):
        b = self.stock(self.t2, count=3000, days_ago=9)
        self.move(self.a, self.t1, self.t3, 7, 300)                                 # split off before the course
        self.treat(self.medicine(name='No row'), 5, 5)
        self.move(self.a, self.t1, self.t2, 3, combines=[(b, 'T-02')])   # after it, beside B
        self.move(b, self.t2, self.t4, 2)                                           # B's fish move on
        self.assertEqual(self.ends(self.t1), [(self.a.code, None)])
        self.assertEqual(self.ends(self.t2), [(self.a.code, None)])
        self.assertEqual(self.ends(self.t4), [(b.code, None)])
        self.assertEqual(self.ends(self.t3), [])
        self.assertEqual(self.warned(self.t4)[0], [(b.code, None)])
        self.assertEqual(self.warned(self.t3)[0], [])
        self.assertTrue(self.t4.withdrawal_blockers())
        self.assertEqual(self.t3.withdrawal_blockers(), [])

    def test_case_6_medicated_feed_with_no_treatment_holds_the_fed_unit_and_where_its_fish_went(self):
        b = self.stock(self.t2, count=3000, days_ago=9)
        self.move(self.a, self.t1, self.t3, 7, 300)                                 # split off before the feeding
        feed = Feed.objects.create(name='Medisinfôr', code='MED-1', feed_type='medicated')
        may_record(self.user, 'add_feedingrecord')  # the feeding service asks (L-6)
        feeding_services.record_feeding(self.user, unit=self.t1, day=self.day(5), feed=feed, amount_kg=Decimal('2'))
        self.move(self.a, self.t1, self.t2, 3, combines=[(b, 'T-02')])
        self.move(b, self.t2, self.t4, 2)
        self.assertEqual(self.ends(self.t1), [(self.a.code, None)])
        self.assertEqual(self.ends(self.t2), [(self.a.code, None)])
        self.assertEqual(self.ends(self.t4), [(b.code, None)])
        self.assertEqual(self.ends(self.t3), [])
        self.assertIn(f'These fish shared T-02 with {self.a.code} (given medicated feed in T-01).',
                      withdrawal.describe(self.held(self.t4)[0]))
        self.assertIn('These fish were given the medicated feed in T-01.', withdrawal.describe(self.held(self.t2)[0]))
        self.assertEqual(self.warned(self.t3)[0], [])
        self.assertIn('3 of 4 units with fish are under a medicine withdrawal.', self.command())


class Case7And8TheGuardTests(LotsTestCase):
    """T-01 (A) bathed 6 days ago (harvest from 2 days ahead); 500 of B joined T-01 4 days ago and moved on to T-03 2
    days ago, where they are held because they shared T-01."""

    def setUp(self):
        super().setUp()
        self.b = self.stock(self.t2, count=3000, days_ago=9)
        self.treatment = self.treat(self.bath, 6, 6)
        self.until = self.day(-2)
        self.move_in = self.move(self.b, self.t2, self.t1, 4, combines=[(self.b, 'T-01')])
        self.move_on = self.move(self.b, self.t1, self.t3, 2)

    def test_case_7_voiding_the_course_asks_about_every_lot_it_frees_by_batch_and_unit(self):
        change = self.change_of(services.void_treatment, self.user, self.treatment, 'entered twice')
        self.assertCountEqual([(each.batch.code, each.unit.code, each.freed) for each in change.released],
                              [(self.a.code, 'T-01', True), (self.b.code, 'T-03', True)])
        self.assertTrue(any(f'{self.b.code} in T-03 is held today' in message
                            and f'These fish shared T-01 with {self.a.code}' in message
                            for message in change.messages()), change.messages())
        services.void_treatment(self.user, self.treatment, 'entered twice', withdrawal_ack=change.fingerprint)
        for unit in (self.t1, self.t2, self.t3):
            self.assertEqual(self.ends(unit), [], unit.code)
        self.assertCountEqual(WithdrawalAcknowledgement.objects.values_list('batch__code', 'warning'),
                              [(self.a.code, 'released'), (self.b.code, 'released')])
        self.assertEqual(self.listed(self.treatment), [(self.a.code, (), False)])       # shown under "voided"

    def test_case_8_a_later_last_day_moves_the_end_everywhere_and_an_earlier_one_asks(self):
        longer = self.treat(self.bath, 5, 4)                    # a second course of T-01: harvest from 4 days ahead
        self.assertEqual(max(until for _batch, until in self.ends(self.t3)), self.day(-4))
        self.assertEqual(check.earliest(self.t3, self.b).day, self.day(-4))
        services.change_last_day(self.user, longer, self.day(3))                    # later: harvest from 5 days ahead
        self.assertEqual(check.earliest(self.t3, self.b).day, self.day(-5))         # everywhere at once
        self.assertEqual(check.earliest(self.t1, self.a).day, self.day(-5))
        change = self.change_of(services.change_last_day, self.user, longer, self.day(5))
        self.assertIn((self.b.code, 'T-03', self.day(-3)),
                      [(each.batch.code, each.unit.code, each.until_after) for each in change.released])

    def test_a_backdated_course_asks_about_a_harvest_of_fish_that_only_shared_the_unit(self):
        self.going_on(services.void_treatment, self.user, self.treatment, 'entered twice')
        harvest = self.harvest_of(self.t3, self.b, days_ago=1)                      # nothing in force: no tick
        self.assertFalse(HandlingAcknowledgement.objects.filter(operation=harvest).exists())
        change = self.change_of(self.treat, self.bath, 6, 6)                        # T-01, never B's own tank
        [found] = change.harvested
        self.assertEqual((found.operation_id, found.line.batch, found.batch), (harvest.pk, self.b, self.a))
        self.assertIn(f'the fish harvested shared T-01 with {self.a.code} before', change.messages()[0])

    def test_voiding_the_move_that_brought_the_fish_beside_held_fish_asks_about_them(self):
        """The void of the move out of T-01 puts B's 500 back in T-01 (held there); the void of the move INTO T-01
        would mean they never met A: asked."""
        stock_services.void(self.user, self.move_on, 'wrong tank')                  # back in the held T-01: not asked
        self.assertEqual(self.ends(self.t3), [])
        change = self.change_of(stock_services.void, self.user, self.move_in, 'never happened')
        self.assertEqual([(each.batch.code, each.unit.code, each.freed) for each in change.released],
                         [(self.b.code, 'T-02', True)])

    def test_a_move_dated_before_the_course_that_takes_fish_out_of_its_reach_is_asked_about(self):
        change = self.change_of(self.move, self.a, self.t1, self.t4, 7, 300, withdrawal_ack=None)   # before the bath
        self.assertEqual([(each.batch.code, each.unit.code, each.freed) for each in change.released],
                         [(self.a.code, 'T-04', True)])
        self.move(self.a, self.t1, self.t4, 7, 300, withdrawal_ack=change.fingerprint)
        self.assertEqual(self.ends(self.t4), [])
        self.assertEqual(self.ends(self.t1), [(self.a.code, self.until)])

    def test_a_move_of_fish_that_were_never_held_asks_nothing(self):
        asked = HandlingAcknowledgement.objects.count()         # the move of B in beside A, in the class's setUp
        self.move(self.b, self.t2, self.t4, 0, 200, withdrawal_ack=None)   # B's untreated fish to an empty tank
        self.assertFalse(WithdrawalAcknowledgement.objects.exists())
        self.assertEqual(HandlingAcknowledgement.objects.count(), asked)
        self.assertEqual(self.ends(self.t4), [])
        # Held fish in beside them: nobody is released; that B now waits with them is said at the move (the owner's
        # decision 8, farm/tests/test_withdrawal_combined.py) and ticked by `move`.
        self.move(self.a, self.t1, self.t4, 0, 200, combines=[(self.b, 'T-04')])
        self.assertFalse(WithdrawalAcknowledgement.objects.exists())
        self.assertEqual(HandlingAcknowledgement.objects.count(), asked + 1)
        self.assertEqual(HandlingAcknowledgement.objects.order_by('pk').last().batch, self.b)
        self.assertEqual(self.ends(self.t4), [(self.a.code, self.until)])


class Case9DeleteBlockerTests(LotsTestCase):
    def test_an_empty_unit_the_fish_passed_through_before_the_course_is_not_blocked(self):
        self.move(self.a, self.t1, self.t2, 8, 2000)                                # everything to T-02
        self.move(self.a, self.t2, self.t3, 7, 2000)                                # and on to T-03: T-02 is empty
        self.treat(self.bath, 5, 5, units=[self.t3])
        self.assertEqual(self.t1.withdrawal_blockers(), [])
        self.assertEqual(self.t2.withdrawal_blockers(), [])
        self.assertTrue(self.t3.withdrawal_blockers())

    def test_the_treated_unit_stays_blocked_after_its_fish_moved_on_while_they_are_held(self):
        self.treat(self.bath, 5, 5)
        self.move(self.a, self.t1, self.t2, 3, 2000)                                # T-01 is empty; A held in T-02
        self.assertEqual(self.ends(self.t1), [])
        [reason] = self.t1.withdrawal_blockers()                # without T-01 the course reached nobody
        self.assertIn(self.a.code, reason)

    def test_for_degree_days_an_untreated_sibling_unit_still_blocks_its_water_counts_for_the_end(self):
        """Decided for now (the vet's open question): a degree-day end is worked out on the exposed batch's water, the
        lowest among EVERY unit the batch is in, so the sibling's samples move it."""
        self.move(self.a, self.t1, self.t2, 6, 800)                                 # split off before the course
        self.treat(self.medicine(name='Slice vet.', degree_days=500), 5, 5)
        self.assertEqual(self.ends(self.t2), [])                                    # not held
        [reason] = self.t2.withdrawal_blockers()                                    # but its water counts
        self.assertIn(self.a.code, reason)
        self.assertEqual(self.t4.withdrawal_blockers(), [])


class Case10CleanerFishTests(CleanerWithdrawalTestCase):
    """C-02 (500 lumpfish and 300 salmon of other batches) was bathed 3 days ago; C-01 holds 2,000 salmon and 10,000
    lumpfish that were never treated; C-03 holds 1,000 salmon of another batch, never treated. The owner's decision 6
    (16.11.2026), both directions."""

    def setUp(self):
        super().setUp()
        self.cage3 = make_unit('C-03', self.cage.production_department)
        self.other_salmon = self.stock(self.cage3, count=1000, weight='125', days_ago=8)

    def ends(self, unit, day=None):
        return sorted((held.batch_id, held.until) for held in withdrawal.of_units([unit], day).get(unit.pk, []))

    def test_held_cleaner_fish_hold_nobody_beside_them_and_carry_no_hold_onward(self):
        """The owner, 16.11.2026 (decision 6): a cleaner-fish lot never makes another lot held."""
        self.join(self.bathed_lump)
        result = check.assess('harvest', self.cage, self.today, self.salmon_batch)
        self.assertEqual(self.withdrawals(result), [])
        self.assertEqual(result.fingerprint, '')
        self.assertEqual(check.earliest(self.cage, self.salmon_batch).decides, '')
        # The cage's own line: the bathed lumpfish and the lumpfish that are beside them now.
        self.assertEqual(self.ends(self.cage), [(self.bathed_lump.pk, self.until)])
        self.assertIn(self.note(self.bathed_lump), result.notes)
        # The cage's own lumpfish and salmon, which were beside them, carry nothing on to C-03.
        for batch in (self.lump_batch, self.salmon_batch):
            stock_services.record_transfer(self.user, source=self.cage, batch=batch, day=self.day(1),
                                           legs=[(self.cage3, 500)], reason='density')
        self.assertEqual(self.ends(self.cage3), [])
        result = check.assess('harvest', self.cage3, self.today, self.other_salmon)
        self.assertEqual((self.withdrawals(result), result.fingerprint), ([], ''))
        self.assertIn('No medicine withdrawal in force.', result.notes)
        self.assertEqual(withdrawal.harvests_inside(), [])

    def test_v03_one_note_per_cleaner_batch_with_its_latest_end(self):
        self.join(self.bathed_lump)
        other = health_bath(self, days=14)                      # C-01 itself bathed today, a 14-day medicine
        later = self.day(-15)
        self.assertIsNotNone(other)
        result = check.assess('harvest', self.cage, self.today, self.salmon_batch)
        notes = [note for note in result.notes if note.startswith('Cleaner fish in C-01')]
        self.assertEqual(sorted(notes), sorted([
            f'Cleaner fish in C-01 are in a medicine withdrawal ({batch.code}, harvest from {shown_date(later)}): keep '
            'them out of the harvest.' for batch in (self.bathed_lump, self.lump_batch)]))
        self.assertEqual([each.block.until for each in self.withdrawals(result)], [later])     # the salmon's own

    def test_bathed_salmon_hold_the_cage_and_its_cleaner_fish_wherever_they_go(self):
        self.join(self.bathed_salmon, 100)
        [warning] = self.withdrawals(check.assess('harvest', self.cage, self.today, self.salmon_batch))
        self.assertEqual((warning.block.batch, warning.block.until), (self.bathed_salmon, self.until))
        self.assertEqual(self.ends(self.cage), [(self.bathed_salmon.pk, self.until)])     # one line holds them all
        # The cage's lumpfish, held with it, are held where they are moved on to: a note for the salmon there, never a
        # warning, and those salmon are not held by them.
        stock_services.record_transfer(self.user, source=self.cage, batch=self.lump_batch, day=self.day(1),
                                       legs=[(self.cage3, 1000)], reason='density')
        self.assertEqual(self.ends(self.cage3), [(self.lump_batch.pk, self.until)])
        self.assertIn(f'These fish shared C-01 with {self.bathed_salmon.code} (treated in C-02).',
                      withdrawal.describe(withdrawal.of_units([self.cage3])[self.cage3.pk][0]))
        result = check.assess('harvest', self.cage3, self.today, self.other_salmon)
        self.assertEqual((self.withdrawals(result), result.fingerprint), ([], ''))
        self.assertIn(f'Cleaner fish in C-03 are in a medicine withdrawal ({self.lump_batch.code}, harvest from '
                      f'{shown_date(self.until)}): keep them out of the harvest.', result.notes)
        self.assertEqual(check.earliest(self.cage3, self.other_salmon).decides, '')
        # ... while C-01's own salmon, moved on, hold the unit they come into.
        going_on(stock_services.record_transfer, self.user, source=self.cage, batch=self.salmon_batch,
                 day=self.day(1), legs=[(self.cage3, 100)], reason='density')
        warnings = self.withdrawals(check.assess('harvest', self.cage3, self.today, self.other_salmon))
        self.assertCountEqual([(each.block.batch, each.block.until) for each in warnings],
                              [(self.salmon_batch, self.until), (self.other_salmon, self.until)])


def health_bath(case, days):
    bath = Medicine.objects.create(name='Alpha Max', kind='lice', administration='bath',
                                   active_substance='deltamethrin', lice_report_code='DELTAMETHRIN')
    with withdrawal_gate.opened('test fixture: a withdrawal row straight in the database'):
        MedicineWithdrawal.objects.create(medicine=bath, species=None, days=days, safety_margin_pct=0, note='')
    return services.record_treatment(case.user, units=[case.cage], method='bath', reason='sea_lice',
                                     start_date=case.today, end_date=case.today, medicine=bath)


class BudgetTests(LotsTestCase):
    """The readers stay bulk: the closure of the batches a hold can travel between is one grouped query, and the walk
    makes none, so the units list, a drawer, the plans and the cards cost the same for 6 units as for 24."""

    def farm(self, count):
        """`count` units in a chain: each holds its own batch, and 100 fish of the unit before it (so a hold of the
        first travels through all of them); the first is bathed."""
        units = [self.t1, *(make_unit(f'U-{number:02d}', self.hall) for number in range(1, count))]
        if getattr(self, 'with_points', False):
            for unit in units:
                point_of(unit)
        batches = [self.a, *(self.stock(unit, count=1000, days_ago=9) for unit in units[1:])]
        self.treat(self.bath, 6, 6)
        for index in range(1, count):
            going_on(stock_services.record_transfer, self.user, source=units[index - 1], batch=batches[index - 1],
                     day=self.day(5), legs=[(units[index], 100)], reason='density')
        return units

    def counted(self, call):
        with CaptureQueriesContext(connection) as queries:
            found = call()
        return len(queries), found

    def measure(self, count):
        units = self.farm(count)
        treatments = list(Treatment.objects.prefetch_related('units'))
        lines, held = self.counted(lambda: withdrawal.of_units(units))
        self.assertEqual(len(held), count)                                          # every unit of the chain is held
        blocks, _found = self.counted(lambda: check.in_force_of(units))
        listed, rows = self.counted(lambda: withdrawal.of_treatments(treatments))
        self.assertEqual(len(rows[treatments[0].pk]), count)
        blockers, _found = self.counted(lambda: units[-1].withdrawal_blockers())
        guard, _found = self.counted(lambda: withdrawal.snapshot({self.a.pk}, self.today))
        inside, _found = self.counted(withdrawal.harvests_inside)
        return {'of_units': lines, 'in_force_of': blocks, 'of_treatments': listed, 'blockers': blockers,
                'snapshot': guard, 'harvests_inside': inside}

    def test_six_units_cost_what_twenty_four_do(self):
        self.assertEqual(self.measure(6), RECORDED)

    def test_twenty_four_units_cost_what_six_do(self):
        self.assertEqual(self.measure(24), RECORDED)

    def test_with_sampling_points_six_units_cost_what_twenty_four_do(self):
        # Every unit with its points (review N-14): the closed probe days and the last closings are read too, two
        # queries whatever the number of units.
        self.with_points = True
        self.assertEqual(self.measure(6), RECORDED_WITH_POINTS)

    def test_with_sampling_points_twenty_four_units_cost_what_six_do(self):
        self.with_points = True
        self.assertEqual(self.measure(24), RECORDED_WITH_POINTS)


# The queries of each reader, whatever the number of units or batches (measured at 6 and at 24 units). One more each
# since 2026-11-26: the degree-days' rules, the platform's settings read once per water read (outside a request, where
# the row is not memoised); these units have no sampling point, so no probe day is read.
RECORDED = {'of_units': 11, 'in_force_of': 12, 'of_treatments': 15, 'blockers': 19, 'snapshot': 17,
            'harvests_inside': 1}
# The same with every unit's sampling points: the closings of the clocks and the closed probe days, two more.
RECORDED_WITH_POINTS = {name: count + 2 for name, count in RECORDED.items() if name != 'harvests_inside'} | {
    'harvests_inside': RECORDED['harvests_inside']}

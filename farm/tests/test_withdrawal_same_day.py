"""Fish that come into a unit and leave it on the same day still held that unit for that day (review F-03 of the flow
faults). The stock's presence asks the ends of the days (in the unit at the end of the day or of the day before), so
held fish that were put into a unit and taken out of it again on one day were never "in" it: the batch beside them was
harvested from that unit the same day with "No medicine withdrawal in force.", without a tick, and check_withdrawal
did not list it. The withdrawal asks "had fish in the unit at ANY moment of the day" (farm.stock.read.Presence.during):
for the unit's blocks, for a harvest inside a withdrawal, and for the fish a course reached. Which fish stay held after
they are moved on (the day after, here) is S-03, not this."""
import io
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.management import call_command

from ..handling import check
from ..health import withdrawal
from ..models import HandlingAcknowledgement
from ..stock import read as stock_read, services as stock_services
from .test_stock import make_unit
from .test_withdrawal_shared_unit import SharedUnitTestCase


class PassingThroughTests(SharedUnitTestCase):
    """A is bathed in T-01 2 days ago (7 days: harvest from 6 days ahead). Today 500 of A come into T-02, beside B."""

    def setUp(self):
        super().setUp()
        self.treatment = self.treat(self.medicine(days=7), 2, 2)
        self.until = self.day(-6)
        self.move(0)

    def withdrawals(self, batch=None):
        result = check.assess('harvest', self.t2, self.today, batch or self.b)
        return result, [each for each in result.warnings if each.warning == 'withdrawal']

    def test_the_held_fish_harvested_out_the_same_day_still_hold_the_unit_that_day(self):
        """The review's probe B1."""
        seen = check.assess('harvest', self.t2, self.today, self.a).fingerprint
        stock_services.record_harvest(self.user, unit=self.t2, batch=self.a, day=self.today, count=500,
                                      measured_weight_kg=Decimal('65'), facility=self.facility, everything=True,
                                      handling_ack=seen)
        self.assertEqual(stock_read.fish_of_batch(self.a.pk).get(self.t2.pk), None)       # A is out of T-02 again
        result, warnings = self.withdrawals()
        self.assertEqual([(each.block.batch, each.block.until) for each in warnings], [(self.a, self.until)])
        self.assertNotIn('No medicine withdrawal in force.', result.notes)
        with self.assertRaises(ValidationError) as caught:                                # the harvest of B needs the tick
            self.harvest_b(0)
        self.assertEqual(caught.exception.message_dict,
                         {'handling_ack': ['Tick the box to go on despite these warnings.']})
        operation = self.harvest_b(0, handling_ack=result.fingerprint)
        row = HandlingAcknowledgement.objects.get(operation=operation)
        self.assertEqual((row.warning, row.batch, row.withdrawal_until), ('withdrawal', self.a, self.until))
        out = io.StringIO()
        call_command('check_withdrawal', stdout=out)
        self.assertIn(f'Harvest of {self.today.isoformat()} from T-02 · {self.b.code} (100 fish to '
                      f'{self.facility.name}) lies inside a withdrawal of {self.a.code}, in the same unit (harvest '
                      f'from {self.until.isoformat()}):', out.getvalue())
        self.assertIn('2 harvests lie inside a medicine withdrawal.', out.getvalue())     # A's own, and B's beside it

    def test_the_held_fish_moved_on_the_same_day_still_hold_the_unit_that_day(self):
        """The review's probe B2."""
        t3 = make_unit('T-03', self.hall)
        stock_services.record_transfer(self.user, source=self.t2, batch=self.a, day=self.today, legs=[(t3, 500)],
                                       reason='density')
        result, warnings = self.withdrawals()
        self.assertEqual([(each.block.batch, each.block.until) for each in warnings], [(self.a, self.until)])
        self.assertNotIn('No medicine withdrawal in force.', result.notes)
        self.assertEqual([held.batch_id for held in withdrawal.of_units([self.t2]).get(self.t2.pk, [])], [self.a.pk])
        self.assertEqual(check.earliest(self.t2, self.b).decides, 'withdrawal')

    def test_the_day_before_the_held_fish_came_the_unit_was_not_held(self):
        self.assertEqual(self.withdrawals()[1][0].block.batch, self.a)                    # today: beside B
        result = check.assess('harvest', self.t2, self.day(1), self.b)
        self.assertEqual([each for each in result.warnings if each.warning == 'withdrawal'], [])
        self.assertIn('No medicine withdrawal in force.', result.notes)


class AnyMomentOfTheDayTests(SharedUnitTestCase):
    def pass_through(self, days_ago, source, batch, to, count=300):
        """`count` fish of `batch` out of `source` into `to` and back again, both on one day."""
        for one, other in ((source, to), (to, source)):
            stock_services.record_transfer(self.user, source=one, batch=batch, day=self.day(days_ago),
                                           legs=[(other, count)], reason='density')

    def test_presence_during_a_day_counts_fish_that_came_and_left_and_present_keeps_its_meaning(self):
        self.assertTrue(hasattr(stock_read.Presence, 'during'), 'the presence asks only the ends of the days')
        self.pass_through(3, self.t2, self.b, self.t1)
        presence = stock_read.Presence.of_units([self.t1.pk])
        self.assertFalse(presence.present(self.t1.pk, self.b.pk, self.day(3)))            # the ends of the days: unchanged
        self.assertEqual(presence.batches_in(self.t1.pk, self.day(3)), {self.a.pk})
        self.assertTrue(presence.during(self.t1.pk, self.b.pk, self.day(3)))              # at some moment of that day
        self.assertEqual(presence.batches_during(self.t1.pk, self.day(3)), {self.a.pk, self.b.pk})
        for days_ago in (4, 2):
            self.assertFalse(presence.during(self.t1.pk, self.b.pk, self.day(days_ago)), days_ago)
        self.assertTrue(presence.during_between(self.t1.pk, self.b.pk, self.day(5), self.day(3)))
        self.assertFalse(presence.during_between(self.t1.pk, self.b.pk, self.day(2), self.today))
        self.assertFalse(presence.during_between(self.t1.pk, self.b.pk, self.day(6), self.day(4)))
        # Where the ends of the days say a batch was there, so does the day: fish that stay, arrive or leave.
        for day in (self.day(11), self.day(10), self.day(1), self.today):
            self.assertEqual(presence.during(self.t1.pk, self.a.pk, day), presence.present(self.t1.pk, self.a.pk, day))

    def test_fish_that_pass_through_a_unit_on_the_day_it_is_bathed_are_reached_by_the_course(self):
        self.pass_through(3, self.t2, self.b, self.t1)
        self.treat(self.medicine(days=7), 3, 3)                                           # T-01, that day
        self.assertEqual(sorted(held.batch_id for held in self.held(self.t2)), [self.b.pk])
        [warning] = check.assess('harvest', self.t2, self.today, self.b).warnings
        self.assertEqual((warning.warning, warning.block.batch, warning.block.until), ('withdrawal', self.b, self.day(-5)))

    def test_a_treatment_entered_afterwards_is_asked_about_the_harvest_beside_the_fish_that_passed_through(self):
        self.move(4)                                                                      # 500 of A beside B, 4 days ago
        stock_services.record_harvest(self.user, unit=self.t2, batch=self.a, day=self.day(4), count=500,
                                      measured_weight_kg=Decimal('65'), facility=self.facility, everything=True)
        self.harvest_b(4)                                                                 # B from T-02, the same day
        change = self.change_of(self.treat, self.medicine(days=7), 5, 5)                  # A was bathed the day before
        self.assertEqual(sorted((found.line.batch.code, found.batch.code) for found in change.harvested),
                         sorted([(self.a.code, self.a.code), (self.b.code, self.a.code)]))

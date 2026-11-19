"""The spread is said at EVERY move that makes it, whatever the batch (the owner's decision 8 of 16.11.2026; the
verification of 27e554e, W-1).

A lot is a batch in a unit. When held fish join fish that are not held of THEIR OWN batch (a split before the course
merged back, held fish moved into the tank split off before the course, decision 7's sibling tank moved into its held
part), the lot after the move is held by a cause the lot already "knew" from the arriving fish, and nothing was said:
0 rows, no question, the fish held all the same. The fish already in a lot and the fish a move brings into it are two
groups; each is asked about on its own, exactly as two batches are.

The matrix: (the same batch / another batch) x (the held side moves in / the side that is not held moves in) x
(transfer, split, grading, stocking, void). Each cell asks, names the lot that now waits, stores the acknowledgement on
the operation and logs it critical, with the same sentence as every combination. Two cells cannot exist: a stocking
always makes a new batch (no "same batch"), and fish stocked are never held before they arrive (no "held side moves
in"). The verifier's three schedules are kept by name (H3a, H3b, H4)."""
from decimal import Decimal

from core.models import AuditLog

from ..handling import check
from ..models import Batch, HandlingAcknowledgement, StockOperation
from ..stock import services as stock_services
from .test_stock import make_unit
from .test_withdrawal_combined import CombinedTestCase


class MatrixTestCase(CombinedTestCase):
    """CombinedTestCase (T-01: A, bathed 6 days ago, harvest from 2 days ahead; T-02: B, never treated) and: 800 of A
    went to T-03 eight days ago, before the course, so they are not held (rule D); T-04, T-05 empty."""

    def setUp(self):
        super().setUp()
        self.t5 = make_unit('T-05', self.hall)
        self.split = self.going_on(self.transfer, self.a, self.t1, [(self.t3, 800)], days_ago=8)
        self.assertEqual(self.held(self.t3), [])

    def nothing_asked_since_the_split(self):
        """No acknowledgement but the split's own (it took fish out of the course's reach: asked and ticked)."""
        self.assertFalse(HandlingAcknowledgement.objects.exclude(operation=self.split).exists())

    def grade(self, batch, source, target, days_ago=0, **fields):
        return stock_services.record_grading(self.user, source=source, batch=batch, day=self.day(days_ago),
                                             outputs=[(target, 300, Decimal(140), 'Large')],
                                             remainder_avg_weight_g=Decimal(120), **fields)

    def stock_into(self, unit, **fields):
        return stock_services.record_input(self.user, species=self.salmon, input_stage='smolt', origin='purchased',
                                           day=self.today, lines=[(unit, 200, Decimal(125))], supplier=self.supplier,
                                           **fields)

    def said(self, expected, call, *args, **kwargs):
        """Asks the write, checks the lots it names as now waiting ([(batch code, unit code)], each to the course's
        end), then goes on with the tick and checks what is kept: one acknowledgement row per lot on the operation
        (warning `withdrawal`, the batch, the end, the sentence asked) and the critical line with the same sentence.
        Returns the operation."""
        change = self.change_of(call, *args, **kwargs)
        self.assertEqual(sorted((each.batch.code, each.unit.code, each.until) for each in change.combined),
                         sorted((code, unit, self.until) for code, unit in expected), change.messages())
        self.assertEqual(change.harvested, [])
        messages = {each.batch.code: each.message() for each in change.combined}
        for code, unit in expected:
            self.assertIn(f'{code} in {unit} will wait for the harvest with ', messages[code])
        before = set(StockOperation.all_objects.values_list('pk', flat=True))
        done = call(*args, withdrawal_ack=change.fingerprint, **kwargs)
        operation = done if isinstance(done, StockOperation) else StockOperation.all_objects.exclude(
            pk__in=before).first() or StockOperation.all_objects.get(pk=args[1].pk)
        rows = HandlingAcknowledgement.objects.filter(operation=operation)
        self.assertEqual(sorted((row.batch.code, row.warning, row.withdrawal_until) for row in rows),
                         sorted((code, 'withdrawal', self.until) for code, _unit in expected))
        for row in rows:
            self.assertEqual(row.withdrawal_reason, messages[row.batch.code])
        logged = ' '.join(entry.changes['Withdrawal warnings acknowledged'][1] for entry in AuditLog.objects.filter(
            entity_type='stock operation', entity_id=str(operation.pk), severity='critical')
            if 'Withdrawal warnings acknowledged' in entry.changes)
        for message in messages.values():
            self.assertIn(message, logged)
        for code, unit in expected:             # and the harvest of those fish waits for that end, as it was said
            batch = Batch.all_objects.get(code=code)
            unit = next(each for each in (self.t1, self.t2, self.t3, self.t4, self.t5) if each.code == unit)
            self.assertEqual(check.earliest(unit, batch).day, self.until)
        return operation


class TransferTests(MatrixTestCase):
    def test_other_batch_held_side_moves_in(self):
        self.said([(self.b.code, 'T-02')], self.transfer, self.a, self.t1, [(self.t2, 500)])

    def test_other_batch_not_held_side_moves_in(self):
        self.said([(self.b.code, 'T-01')], self.transfer, self.b, self.t2, [(self.t1, 500)])

    def test_same_batch_held_side_moves_in(self):
        self.said([(self.a.code, 'T-03')], self.transfer, self.a, self.t1, [(self.t3, 300)])

    def test_same_batch_not_held_side_moves_in(self):
        self.said([(self.a.code, 'T-01')], self.transfer, self.a, self.t3, [(self.t1, 300)])


class SplitTests(MatrixTestCase):
    """A split is a transfer into several units: the empty one asks nothing."""

    def test_other_batch_held_side_moves_in(self):
        self.said([(self.b.code, 'T-02')], self.transfer, self.a, self.t1, [(self.t2, 300), (self.t4, 300)])

    def test_other_batch_not_held_side_moves_in(self):
        self.said([(self.b.code, 'T-01')], self.transfer, self.b, self.t2, [(self.t1, 300), (self.t4, 300)])

    def test_same_batch_held_side_moves_in(self):
        self.said([(self.a.code, 'T-03')], self.transfer, self.a, self.t1, [(self.t3, 300), (self.t4, 300)])

    def test_same_batch_not_held_side_moves_in(self):
        self.said([(self.a.code, 'T-01')], self.transfer, self.a, self.t3, [(self.t1, 300), (self.t4, 300)])


class GradingTests(MatrixTestCase):
    def test_other_batch_held_side_moves_in(self):
        self.said([(self.b.code, 'T-02')], self.grade, self.a, self.t1, self.t2)

    def test_other_batch_not_held_side_moves_in(self):
        self.said([(self.b.code, 'T-01')], self.grade, self.b, self.t2, self.t1)

    def test_same_batch_held_side_moves_in(self):
        self.said([(self.a.code, 'T-03')], self.grade, self.a, self.t1, self.t3)

    def test_same_batch_not_held_side_moves_in(self):
        self.said([(self.a.code, 'T-01')], self.grade, self.a, self.t3, self.t1)


class StockingTests(MatrixTestCase):
    """The one cell a stocking has: fish that are not held (new, of a new batch) stocked beside held fish."""

    def test_other_batch_not_held_side_moves_in(self):
        change = self.change_of(self.stock_into, self.t1)
        self.assertEqual([(each.unit.code, each.until) for each in change.combined], [('T-01', self.until)])
        self.stock_into(self.t1, withdrawal_ack=change.fingerprint)
        new = Batch.objects.exclude(pk__in=[self.a.pk, self.b.pk]).get()
        row = HandlingAcknowledgement.objects.get(operation__kind='input')
        self.assertEqual((row.operation.kind, row.batch, row.warning, row.withdrawal_until),
                         ('input', new, 'withdrawal', self.until))
        self.assertIn(f'{new.code} in T-01 will wait for the harvest with ', row.withdrawal_reason)
        self.assertEqual(check.earliest(self.t1, new).day, self.until)


class VoidTests(MatrixTestCase):
    """A void moves fish back in the ledger: the fish of the voided move were where they came from all along."""

    def void(self, operation):
        return stock_services.void(self.user, operation, 'never happened')

    def test_other_batch_held_side_moves_in(self):
        out = self.transfer(self.a, self.t1, [(self.t5, 1200)], days_ago=4)      # all held A leave T-01
        self.transfer(self.b, self.t2, [(self.t1, 500)], days_ago=3)             # B into the emptied T-01: free
        self.nothing_asked_since_the_split()
        self.said([(self.b.code, 'T-01')], stock_services.void, self.user, out, 'never happened')

    def test_other_batch_not_held_side_moves_in(self):
        out = self.transfer(self.b, self.t2, [(self.t5, 3000)], days_ago=4)      # all B leave T-02
        self.transfer(self.a, self.t1, [(self.t2, 500)], days_ago=3)             # held A into the emptied T-02
        self.nothing_asked_since_the_split()
        self.said([(self.b.code, 'T-02')], stock_services.void, self.user, out, 'never happened')

    def test_same_batch_held_side_moves_in(self):
        out = self.transfer(self.a, self.t1, [(self.t5, 1200)], days_ago=4)      # all held A leave T-01
        self.transfer(self.a, self.t3, [(self.t1, 300)], days_ago=3)             # not-held A into the emptied T-01
        self.nothing_asked_since_the_split()
        self.said([(self.a.code, 'T-01')], stock_services.void, self.user, out, 'never happened')

    def test_same_batch_not_held_side_moves_in(self):
        """The split before the course voided: its 800 fish were in T-01 on the course day after all."""
        self.said([(self.a.code, 'T-01')], stock_services.void, self.user, self.split, 'never happened')


class VerifierScheduleTests(MatrixTestCase):
    """The verifier's schedules (REVIEW-S03, verification of 27e554e, W-1), each asked and, past the tick, held."""

    def refused_without_a_tick(self, unit, batch):
        seen = check.assess('harvest', unit, self.today, batch)
        self.assertTrue(seen.fingerprint)                                       # a harvest there needs the box

    def test_h3a_the_split_before_the_course_merged_back_into_the_held_tank(self):
        self.said([(self.a.code, 'T-01')], self.transfer, self.a, self.t3, [(self.t1, 800)], days_ago=2)
        self.refused_without_a_tick(self.t1, self.a)

    def test_h3b_held_fish_moved_into_the_tank_split_off_before_the_course(self):
        self.said([(self.a.code, 'T-03')], self.transfer, self.a, self.t1, [(self.t3, 300)], days_ago=2)
        self.refused_without_a_tick(self.t3, self.a)

    def test_h4_the_sibling_tank_of_decision_7_moved_into_its_held_part_and_back(self):
        self.transfer(self.b, self.t2, [(self.t5, 1000)], days_ago=8)          # B's sibling tank, before anything
        self.said([(self.b.code, 'T-02')], self.grade, self.a, self.t1, self.t2, days_ago=3)
        self.assertEqual(check.earliest(self.t5, self.b).decides, '')                 # decision 7: T-05 is free
        self.said([(self.b.code, 'T-02')], self.transfer, self.b, self.t5, [(self.t2, 300)], days_ago=2)
        self.said([(self.b.code, 'T-05')], self.transfer, self.b, self.t2, [(self.t5, 100)], days_ago=1)
        self.refused_without_a_tick(self.t5, self.b)

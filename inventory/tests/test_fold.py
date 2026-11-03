"""The store's book without a database (inventory/fold.py), with worked numbers: first expired first out over
two lots, expired lots last, feeding beyond the book and what fixes it, departures before the feeding's
estimate, a count at the end of its day, a whole-location count, a transfer between sites."""
from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase

from ..fold import Folded, Line, Lot, Op, Place, physical

D = Decimal


def nov(day):
    return date(2026, 11, day)


class Ledger:
    """Builds the fold's rows: operations in the order written, lines, lots and two sites' places."""

    def __init__(self):
        self.lines, self.counts, self.seq = [], [], 0
        self.places = {'WH': Place('WH', 'S1', 'WH-1'), 'SILO': Place('SILO', 'S1', 'SI-1'),
                       'FAR': Place('FAR', 'S2', 'FA-1')}
        self.lots = {'A': Lot('A', 'A-100', nov(20)), 'B': Lot('B', 'B-200', nov(10)), 'N': Lot('N', '', None)}

    def op(self, kind, day, location=None):
        self.seq += 1
        return Op(f'op{self.seq}', kind, day, self.seq, location)

    def line(self, op, kind, quantity, lot='A', location='WH'):
        self.lines.append(Line(len(self.lines) + 1, op, lot, location, kind, D(quantity)))

    def receive(self, day, quantity, lot='A', location='WH'):
        self.line(self.op('receipt', day), 'in', quantity, lot, location)

    def out(self, day, quantity, lot='A', location='WH', kind='write_off'):
        self.line(self.op(kind, day), 'out', -D(quantity), lot, location)

    def transfer(self, day, quantity, lot='A', source='WH', destination='SILO'):
        op = self.op('transfer', day)
        self.line(op, 'transfer_out', -D(quantity), lot, source)
        self.line(op, 'transfer_in', quantity, lot, destination)

    def count(self, day, location, found):
        op = self.op('count', day, location)
        self.counts.append(op)
        for lot, quantity in found.items():
            self.line(op, 'count', quantity, lot, location)
        return op

    def fold(self, feeding=None):
        return Folded(self.lines, self.counts, {key: D(value) for key, value in (feeding or {}).items()}, self.lots,
                      self.places)


class FoldTests(SimpleTestCase):
    def test_feeding_draws_first_expired_first_out_across_two_lots(self):
        ledger = Ledger()
        ledger.receive(nov(1), 500, 'A')          # expires 20 Nov
        ledger.receive(nov(1), 300, 'B')          # expires 10 Nov: drawn first
        fold = ledger.fold({('S1', nov(3)): 400})
        self.assertEqual([(draw.bucket, draw.kg) for draw in fold.draws], [(('WH', 'B'), 300), (('WH', 'A'), 100)])
        self.assertEqual(fold.on_hand(nov(3)), {('WH', 'A'): 400})
        self.assertEqual(fold.balance(('WH', 'A'), nov(2)), 500)     # the day before the feeding
        self.assertEqual(fold.uncovered, [])

    def test_expired_lots_come_last_and_are_reported(self):
        ledger = Ledger()
        ledger.receive(nov(1), 300, 'B')          # expires 10 Nov
        ledger.receive(nov(1), 100, 'A')          # expires 20 Nov
        fold = ledger.fold({('S1', nov(12)): 250})
        self.assertEqual([(draw.bucket[1], draw.kg, draw.expired) for draw in fold.draws],
                         [('A', 100, False), ('B', 150, True)])
        self.assertEqual(fold.on_hand(nov(12)), {('WH', 'B'): 150})

    def test_a_lot_without_an_expiry_is_drawn_after_those_with_one(self):
        ledger = Ledger()
        ledger.receive(nov(1), 100, 'N')
        ledger.receive(nov(2), 100, 'A')
        fold = ledger.fold({('S1', nov(3)): 150})
        self.assertEqual([(draw.bucket[1], draw.kg) for draw in fold.draws], [('A', 100), ('N', 50)])

    def test_feeding_beyond_the_book_is_uncovered_and_no_later_delivery_fills_it(self):
        ledger = Ledger()
        ledger.receive(nov(1), 1000)
        ledger.receive(nov(5), 500, 'B')          # after the shortfall: it does not cover it (owner decision Q-S1)
        fold = ledger.fold({('S1', nov(2)): 700, ('S1', nov(3)): 500})
        self.assertEqual(fold.uncovered, [('S1', nov(3), D(200))])
        self.assertEqual(fold.on_hand(nov(5)), {('WH', 'B'): 500})

    def test_the_missing_delivery_recorded_on_its_day_covers_the_feeding(self):
        ledger = Ledger()
        ledger.receive(nov(1), 1000)
        ledger.receive(nov(3), 400, 'B')          # the delivery that was missing, backdated to its day
        fold = ledger.fold({('S1', nov(2)): 700, ('S1', nov(3)): 500})
        self.assertEqual(fold.uncovered, [])
        # 2 Nov: 700 of A (B not there yet); 3 Nov: all 400 of B (10 Nov) first, then 100 of A.
        self.assertEqual(fold.on_hand(nov(3)), {('WH', 'A'): 200})

    def test_a_departure_keeps_what_it_needs_and_the_feeding_takes_only_the_rest(self):
        ledger = Ledger()
        ledger.receive(nov(1), 1000)
        ledger.transfer(nov(3), 500, destination='FAR')      # to the other site, recorded after the feeding's day
        self.assertIsNone(physical(ledger.lines))
        fold = ledger.fold({('S1', nov(2)): 800})
        self.assertEqual([draw.kg for draw in fold.draws], [500])
        self.assertEqual(fold.uncovered, [('S1', nov(2), D(300))])
        self.assertEqual(fold.balance(('WH', 'A'), nov(2)), 500)
        self.assertEqual(fold.balance(('WH', 'A'), nov(3)), 0)
        self.assertEqual(fold.balance(('FAR', 'A'), nov(3)), 500)

    def test_a_count_sets_the_end_of_its_day_and_its_variance_is_against_the_book_with_that_days_feeding(self):
        ledger = Ledger()
        ledger.receive(nov(1), 1000)
        count = ledger.count(nov(3), 'WH', {'A': 750})
        fold = ledger.fold({('S1', nov(2)): 200, ('S1', nov(3)): 30, ('S1', nov(4)): 50})
        variance = next(item for item in fold.variances if item.op == count)
        self.assertEqual((variance.book, variance.counted, variance.difference), (770, 750, -20))
        self.assertEqual(fold.balance(('WH', 'A'), nov(3)), 750)
        self.assertEqual(fold.balance(('WH', 'A'), nov(4)), 700)

    def test_a_count_counts_the_whole_location(self):
        ledger = Ledger()
        ledger.receive(nov(1), 300, 'A')
        ledger.receive(nov(1), 200, 'B')
        ledger.receive(nov(1), 100, 'B', location='SILO')
        ledger.count(nov(4), 'WH', {'A': 280})               # B was not found in WH: 0
        fold = ledger.fold()
        self.assertEqual(fold.on_hand(nov(4)), {('WH', 'A'): 280, ('SILO', 'B'): 100})
        self.assertEqual(sorted((item.bucket[1], item.difference) for item in fold.variances), [('A', -20), ('B', -200)])

    def test_a_departure_below_the_physical_book_is_found_also_later(self):
        ledger = Ledger()
        ledger.receive(nov(1), 100)
        ledger.out(nov(5), 80)
        ledger.out(nov(3), 30)       # entered later, dated before: 100 − 30 − 80 < 0 on 5 Nov
        shortfall = physical(ledger.lines)
        self.assertEqual((shortfall.line.op.day, shortfall.available), (nov(5), 70))

    def test_feeding_never_counts_in_the_physical_check(self):
        ledger = Ledger()
        ledger.receive(nov(1), 100)
        ledger.out(nov(3), 100)
        self.assertIsNone(physical(ledger.lines))
        fold = ledger.fold({('S1', nov(2)): 60})
        self.assertEqual(fold.uncovered, [('S1', nov(2), D(60))])    # the write-off needs all of it
        self.assertEqual(fold.on_hand(nov(3)), {})

    def test_a_site_draws_only_its_own_locations(self):
        ledger = Ledger()
        ledger.receive(nov(1), 400, location='FAR')
        ledger.transfer(nov(4), 100, source='FAR', destination='WH')
        fold = ledger.fold({('S1', nov(3)): 50, ('S1', nov(5)): 50})
        self.assertEqual(fold.uncovered, [('S1', nov(3), D(50))])
        self.assertEqual(fold.on_hand(nov(5)), {('FAR', 'A'): 300, ('WH', 'A'): 50})

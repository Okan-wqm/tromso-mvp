"""The one assignment resolver (farm/feeding/resolve.py, owner decision 16) on its own, for protocol rows and profile rows
alike, over every combination of the three kinds of row; a temperature profile's reading (growth.between) by hand; and
the policy's planned temperature of a day ahead (ration.Policy.planned_temperature)."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from itertools import product
from types import SimpleNamespace

from django.test import SimpleTestCase

from ..feeding import growth
from ..feeding.ration import PlannedTemperature, Policy, Profile
from ..feeding.resolve import Resolver

D = Decimal
DAY = date(2026, 11, 26)


@dataclass
class Row:
    """An assignment row as the resolver reads it: its table (`profile_id`), unit, batch and period."""
    profile_id: object
    unit_id: object = None
    batch_id: object = None
    valid_from: date = date(2026, 11, 1)
    valid_until: date = None

    def covers(self, day):
        return self.valid_from <= day and (self.valid_until is None or day <= self.valid_until)


SPECIES = {'pair': 'S', 'unit': 'S', 'batch': 'S', 'trout': 'T'}


class ResolverTests(SimpleTestCase):
    def resolve(self, rows, unit='U1', batch='B1', day=DAY):
        return Resolver(rows, 'profile', SPECIES, {'B1': 'S', 'B2': 'S'}).resolve(unit, batch, day)

    def test_the_most_specific_row_wins_for_every_combination(self):
        made = {'pair': Row('pair', 'U1', 'B1'), 'unit': Row('unit', 'U1'), 'batch': Row('batch', None, 'B1')}
        for present in product((False, True), repeat=3):
            rows = [row for kind, row in zip(('pair', 'unit', 'batch'), made.values()) if present[
                ('pair', 'unit', 'batch').index(kind)]]
            expected = next((row for row in rows), None)          # in the order pair, unit, batch
            found, skipped = self.resolve(rows)
            self.assertIs(found, expected, present)
            self.assertIsNone(skipped)

    def test_a_row_out_of_its_days_is_not_read(self):
        ended = Row('unit', 'U1', valid_until=date(2026, 11, 25))
        later = Row('pair', 'U1', 'B1', valid_from=date(2026, 11, 27))
        batch = Row('batch', None, 'B1')
        self.assertIs(self.resolve([ended, later, batch])[0], batch)
        self.assertIs(self.resolve([ended, later, batch], day=date(2026, 11, 25))[0], ended)

    def test_a_units_row_of_another_species_is_read_past_and_said(self):
        trout, batch = Row('trout', 'U1'), Row('batch', None, 'B1')
        self.assertEqual(self.resolve([trout, batch]), (batch, trout))
        self.assertEqual(self.resolve([trout]), (None, trout))

    def test_after_a_grading_each_part_reads_its_own_place(self):
        # the batch in U1 and its part graded into U2: a unit row on U1, the whole batch's row everywhere
        unit, batch = Row('unit', 'U1'), Row('batch', None, 'B1')
        self.assertIs(self.resolve([unit, batch], unit='U1')[0], unit)
        self.assertIs(self.resolve([unit, batch], unit='U2')[0], batch)
        self.assertIs(self.resolve([unit, batch], unit='U2', batch='B2')[0], None)

    def test_protocol_rows_resolve_the_same_way(self):
        rows = [SimpleNamespace(protocol_id='unit', unit_id='U1', batch_id=None, covers=lambda day: True)]
        self.assertIs(Resolver(rows, 'protocol', {'unit': 'S'}, {'B1': 'S'}).resolve('U1', 'B1', DAY)[0], rows[0])


class BetweenTests(SimpleTestCase):
    POINTS = ((D(0), D(10)), (D(100), D(12)), (D(400), D(14)))

    def test_smooth_by_hand(self):
        # 10 °C at 0 g, 12 °C at 100 g, 14 °C at 400 g: 50 g → 11 °C, 250 g → 13 °C, outside → the end's
        self.assertEqual([growth.between(self.POINTS, D(weight)) for weight in (0, 50, 100, 250, 400, 900)],
                         [D(10), D(11), D(12), D(13), D(14), D(14)])

    def test_step_by_hand(self):
        # a step at each point: from its weight on, its temperature; before the first, the first's
        self.assertEqual([growth.between(self.POINTS, D(weight), step=True)
                          for weight in ('-1', 0, '99.99', 100, 399, 400, 900)],
                         [D(10), D(10), D(10), D(12), D(12), D(14), D(14)])

    def test_smooth_never_jumps_and_step_is_a_point_value_everywhere(self):
        values = {value for _weight, value in self.POINTS}
        weights = [D(n) / 4 for n in range(0, 2001)]
        smooth = [growth.between(self.POINTS, weight) for weight in weights]
        for before, after in zip(smooth, smooth[1:]):
            self.assertLessEqual(abs(after - before), D(2) / 100 / 4)
        self.assertTrue(all(growth.between(self.POINTS, weight, step=True) in values for weight in weights))


class PlannedTemperatureTests(SimpleTestCase):
    def test_the_policy_reads_the_profile_in_force_at_the_weight(self):
        hall = SimpleNamespace(name='Hall A', species_id='S')
        policy = Policy([], {}, {'B1': 'S'}, lambda unit_id, day: None,
                        profile_rows=[Row('hall', 'U1')],
                        profiles={'hall': Profile(hall, ((D(0), D(10)), (D(100), D(12))))})
        self.assertEqual(policy.planned_temperature('U1', 'B1', DAY, D(40)), PlannedTemperature(D('10.8'), hall))
        self.assertIsNone(policy.planned_temperature('U2', 'B1', DAY, D(40)))

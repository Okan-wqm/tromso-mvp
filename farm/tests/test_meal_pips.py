"""The meal board's pips (docs/design/system, MealBoard): one per planned meal of a batch line, filled for the meals
recorded, ringed for the next, dashed for the later ones; they only draw the line's own counts."""
from types import SimpleNamespace

from django.test import SimpleTestCase

from farm.templatetags.feeding import meal_pips


def line(planned, meals):
    return SimpleNamespace(planned_meals=planned, meals=meals)


class MealPipsTests(SimpleTestCase):
    def test_done_then_next_then_the_later_ones(self):
        self.assertEqual(meal_pips(line(4, 1)), ['done', 'next', '', ''])

    def test_none_done_rings_the_first(self):
        self.assertEqual(meal_pips(line(3, 0)), ['next', '', ''])

    def test_all_done_has_no_next(self):
        self.assertEqual(meal_pips(line(2, 2)), ['done', 'done'])

    def test_more_recorded_than_planned_fills_them_all_and_no_more(self):
        self.assertEqual(meal_pips(line(2, 5)), ['done', 'done'])

    def test_no_meals_planned_draws_nothing(self):
        self.assertEqual(meal_pips(line(0, 1)), [])
        self.assertEqual(meal_pips(line(None, 0)), [])

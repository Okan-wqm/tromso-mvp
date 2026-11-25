"""A worked-out water value is never fresher than its oldest input (the coordinator's decision of 2026-11-26): its
freshness is the earliest moment any of the values it was worked out with stops being fresh (farm/water/freshness.py
`derived_until`, the inputs each parameter declares in farm/water/parameters.py), never later than its own row's hours.
An NH₃ worked out from a 5-day-old pH was fresh for its own 168 h while the pH it came from was fresh for 72 h. Every
reader asks `read.Reading.fresh` / `fresh_until`, so the pages, the cards and the alarms say it the same way."""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from monitoring.cards import render

from ..water import evaluate, freshness, parameters, read
from ..water.evaluate import Status
from .test_water import WaterTestCase

D = Decimal
NH3, NH4 = 'nh3_n_mg_l', 'nh4_n_mg_l'
TAN, PH, TEMPERATURE, SALINITY = parameters.TAN, parameters.PH, parameters.TEMPERATURE, parameters.SALINITY
FULL = {'tan_mg_l': '1.000', 'ph': '7.50', 'temperature_c': '12.0', 'salinity_ppt': '0.0'}


class DeclaredInputsGuardTests(TestCase):
    """The guard: a worked-out parameter (one not measured) cannot exist without the inputs its freshness is taken from,
    so a value to come (the CO₂ worked out from the carbonate system) cannot skip the rule."""

    def derived(self):
        return [parameter for parameter in parameters.BY_CODE.values() if not parameter.measured]

    def test_every_worked_out_parameter_declares_its_inputs(self):
        self.assertTrue(self.derived())
        for parameter in self.derived():
            with self.subTest(parameter=parameter.code):
                self.assertTrue(parameter.inputs, f'{parameter.code} is worked out and declares no inputs')
                for code in parameter.inputs:
                    self.assertIn(code, parameters.BY_CODE)
                    self.assertTrue(parameters.get(code).measured, f'{code} is not a measured input')
                    self.assertIn(code, freshness.SEEDS)
                self.assertIn(parameter.code, freshness.SEEDS)
        for parameter in parameters.BY_CODE.values():
            if parameter.measured:
                self.assertEqual(parameter.inputs, (), parameter.code)

    def test_the_ammonia_is_worked_out_from_the_tan_the_ph_the_temperature_and_the_salinity(self):
        for code in (NH3, NH4):
            self.assertEqual(set(parameters.get(code).inputs), {TAN, PH, TEMPERATURE, SALINITY})

    def test_the_derived_codes_are_the_declared_ones(self):
        self.assertEqual(set(read.DERIVED), {parameter.code for parameter in self.derived()})
        self.assertEqual(set(parameters.DERIVED), set(read.DERIVED))

    def test_a_worked_out_parameter_without_inputs_is_refused_where_it_is_made(self):
        with self.assertRaises(ValueError):
            parameters._parameter('co2_worked_mg_l', 'CO₂', 'CO₂', 1, 0, 200, measured=False)

    def test_each_input_running_out_ends_it(self):
        """For every worked-out parameter and every one of its inputs: that input alone stale makes it stale."""
        now = at = timezone.now()
        for parameter in self.derived():
            for code in parameter.inputs:
                with self.subTest(parameter=parameter.code, input=code):
                    ends = {each: now + timedelta(days=1) for each in parameter.inputs}
                    ends[code] = now - timedelta(seconds=1)
                    until = freshness.derived_until(parameter.code, at, ends)
                    self.assertFalse(evaluate.is_fresh(parameter, at, now, until=until))
                    ends[code] = now + timedelta(seconds=1)
                    self.assertTrue(evaluate.is_fresh(parameter, at, now,
                                                      until=freshness.derived_until(parameter.code, at, ends)))

    def test_an_input_left_out_or_one_not_declared_is_refused(self):
        now = timezone.now()
        inputs = parameters.get(NH3).inputs
        with self.assertRaises(ValueError):
            freshness.derived_until(NH3, now, {code: now for code in inputs[1:]})
        with self.assertRaises(ValueError):
            freshness.derived_until(NH3, now, {**{code: now for code in inputs}, 'nitrite_n_mg_l': now})
        with self.assertRaises(ValueError):
            freshness.derived_until(TAN, now, {})

    def test_a_worked_out_value_is_never_judged_fresh_by_its_own_hours_alone(self):
        """The one rule refuses a worked-out parameter without the end its inputs give (`until`): no reader can fall
        back on the NH₃ row's 168 h."""
        now = timezone.now()
        with self.assertRaises(ValueError):
            evaluate.is_fresh(parameters.get(NH3), now - timedelta(hours=1), now)

    def test_its_own_row_still_caps_it(self):
        now = timezone.now()
        far = {code: now + timedelta(days=60) for code in parameters.get(NH3).inputs}
        self.assertEqual(freshness.derived_until(NH3, now, far), now + freshness.fresh_for(NH3))


class DerivedFreshnessTests(WaterTestCase):
    def context(self):
        return read.Context([self.mid1], self.now - read.WINDOW)

    def observation(self, hours, **values):
        return read.Observation(self.mid1, self.ago(hours=hours), read.Origin.MANUAL,
                                {code: D(value) for code, value in values.items()})

    def test_an_nh3_from_a_young_tan_and_an_old_ph_is_not_fresh(self):
        """The TAN 2 h old (fresh for 168 h), the pH 80 h old (fresh for 72 h): the NH₃ is not fresh."""
        ph = self.observation(80, ph='7.50')
        together = read.Observation.combined([self.observation(2, tan_mg_l='1.000'), ph,
                                              self.observation(1, temperature_c='12.0', salinity_ppt='0.0')])
        found = self.context().readings(together)
        for code in (NH3, NH4):
            with self.subTest(code=code):
                self.assertIsNotNone(found[code].value)
                self.assertEqual(found[code].fresh_until, ph.at + timedelta(hours=72))
                self.assertFalse(found[code].fresh(self.now))
        self.assertTrue(found[TAN].fresh(self.now))

    def test_young_inputs_give_a_fresh_nh3_that_ends_with_the_first_input(self):
        """One sample 1 h old: the NH₃ is fresh, and stale once its temperature (24 h) is, though its TAN (168 h) and its
        own row (168 h) are not."""
        self.sample(hours=1, **FULL)
        nh3 = self.unit_water().get(NH3)
        self.assertIsNotNone(nh3.value)
        self.assertTrue(nh3.fresh(self.now))
        self.assertEqual(nh3.status, Status.NO_LIMIT)
        ends = nh3.at + timedelta(hours=24)
        self.assertEqual(nh3.fresh_until, ends)
        self.assertTrue(nh3.fresh(ends))
        self.assertFalse(nh3.fresh(ends + timedelta(seconds=1)))
        tan = self.unit_water().get(TAN)
        self.assertTrue(tan.fresh(ends + timedelta(seconds=1)))

    def test_a_salinity_looked_up_from_an_earlier_sample_ends_it_first(self):
        """The salinity is not in the TAN sample: the point's salinity 160 h old stands in (fresh for 168 h, so 8 h
        more), and the NH₃ ends with it."""
        salinity = self.sample(hours=160, salinity_ppt='0.0')
        self.sample(hours=1, tan_mg_l='1.000', ph='7.50', temperature_c='12.0')
        nh3 = self.unit_water().get(NH3)
        self.assertIsNotNone(nh3.value)
        self.assertEqual(nh3.fresh_until, salinity.measured_at + timedelta(hours=168))
        self.assertTrue(nh3.fresh(self.now))
        self.assertFalse(nh3.fresh(self.now + timedelta(hours=8, seconds=1)))

    def test_a_changed_input_row_moves_it(self):
        """The inputs' freshness is the user's rows, read as every value's is."""
        from ..models import WaterFreshness
        self.sample(hours=30, **FULL)
        self.assertFalse(self.unit_water().get(NH3).fresh(self.now))
        WaterFreshness.objects.filter(parameter=TEMPERATURE).update(fresh_hours=48)
        freshness.forget()
        self.addCleanup(freshness.forget)
        self.assertTrue(self.unit_water().get(NH3).fresh(self.now))

    def test_the_page_and_the_card_show_it_stale(self):
        """A sample 30 h old: its TAN is fresh, its temperature is not, so its NH₃ is stale on the water's read API (the
        water page, the drawer, the overview) and on the monitoring card."""
        self.stock()
        self.limit(NH3, critical_high='0.025', warning_high='0.0125')
        self.sample(hours=30, **FULL)
        water = self.unit_water()
        nh3 = water.get(NH3)
        self.assertIsNotNone(nh3.value)
        self.assertEqual(nh3.status, Status.STALE)
        self.assertEqual(water.get(TAN).status, Status.NO_LIMIT)
        face = render.face(nh3, self.now)
        self.assertTrue(face.stale)
        self.assertEqual(face.status, Status.STALE)
        self.assertEqual(water.get(NH4).fresh(self.now), False)

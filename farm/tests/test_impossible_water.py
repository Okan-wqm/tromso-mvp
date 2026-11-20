"""A water that cannot be is refused by the core itself (owner-approved correction, 2026-11-10; the independent check of
2026-11-09, claim 9): at a high pH the hydroxide and the borate alone are alkalinity, so a pH has a floor of alkalinity;
at or below it the DIC, the CO2 and the carbonate would be 0 or negative. The application's two entry points have always
refused such a pair with its reason (the calculator's form, a unit's chart: deffeyes.why_impossible), but the core worked
it out (40 °C, S 40, alkalinity 0.5 meq/L, pH 9: DIC -0.0167 mmol/L, CO2 -0.0002 mg/L by formula 3). Now every door of
formula 3 answers native.ImpossibleWaterError (a ValueError), never a negative concentration, by the one rule
why_impossible asks too (Equilibria.possible), so the reason on the page and the core's refusal cannot disagree. Formula
1 refuses nothing, by name: golden v1 holds what it returns below the floor."""
import math
import random

from django.test import SimpleTestCase

from ..water import chemistry, deffeyes, native

MEQ = native.MG_CACO3_PER_MEQ
# The independent check's water, 40 °C, S 40, 0.5 meq/L at pH 9.0 (ODD_V1): impossible by formula 1 and 3. Formula 4's
# NBS step (Millero 1986, extrapolated to 40 °C) puts its pH 9.0 floor at 0.497 meq/L, just below it, so the application's
# refusal is held at pH 9.1, where the floor is 0.557 meq/L.
ODD_V1 = (40.0, 40.0, 9.0, 0.5 * MEQ)
ODD = (40.0, 40.0, 9.1, 0.5 * MEQ)
ODD_WATER = {'temperature_c': 40.0, 'salinity_ppt': 40.0, 'ph': 9.1, 'alkalinity_mg_l': 0.5 * MEQ, 'tan_mg_l': 0.5}
LIMITS = {'nh3_n_mg_l': 0.0103, 'co2_mg_l': 15.0, 'alkalinity_low_mg_l': 50.0, 'alkalinity_high_mg_l': 150.0}
CONCENTRATIONS = ('dic', 'co2_mg_l', 'co2_corrected_mg_l')


class CoreRefusalTests(SimpleTestCase):
    def test_the_refusal_is_a_typed_error(self):
        self.assertTrue(issubclass(native.ImpossibleWaterError, ValueError))
        self.assertFalse(issubclass(native.ImpossibleWaterError, native.NonFiniteError))

    def test_the_analysis_refuses_the_water_and_the_target(self):
        with self.assertRaises(native.ImpossibleWaterError):
            native.analyse(*ODD)
        with self.assertRaises(native.ImpossibleWaterError):
            deffeyes.analyse(deffeyes.Water(*ODD), deffeyes.Limits(co2_mg_l=15.0))
        with self.assertRaises(native.ImpossibleWaterError):
            native.analyse(12.0, 1.0, 7.0, 80.0, target_ph=11.5, target_alkalinity_mg_l=20.0)
        found = native.analyse(40.0, 40.0, 9.0, 200.0, co2_mg_l=15.0, target_ph=8.0, target_alkalinity_mg_l=150.0)
        for name in (*CONCENTRATIONS, 'target_dic', 'target_co2_mg_l'):
            self.assertGreater(found[name], 0.0, name)

    def test_the_equilibria_refuse_it(self):
        eq = chemistry.water_equilibria(40.0, 40.0, 0.5 * MEQ)
        for call in (lambda: eq.dic(0.5, 9.1), lambda: eq.co2_judged(0.5, 9.1), lambda: eq.co2(-0.0167, 9.1),
                     lambda: eq.carbonate(-0.0167, 9.1)):
            with self.assertRaises(native.ImpossibleWaterError):
                call()
        self.assertIsNone(eq.ph_at(-0.0167, 0.5))                   # as before: no pH gives such a water
        self.assertGreater(eq.dic(2.3, 8.1), 0.0)
        self.assertGreater(eq.co2_judged(2.3, 8.1)[0], 0.0)
        self.assertEqual(eq.co2(0.0, 8.1), 0.0)

    def test_the_chart_the_small_charts_and_the_simulator_refuse_it(self):
        eq = chemistry.water_equilibria(40.0, 40.0, 0.5 * MEQ)
        for call in (lambda: native.geometry(ODD_WATER, LIMITS), lambda: native.plots(ODD_WATER, LIMITS),
                     lambda: native.safe_zone(ODD_WATER, LIMITS, (6.0, 6.0, 1.0, 1.0)),
                     lambda: native.safe_zone_gaps(ODD_WATER, LIMITS),
                     lambda: native.judge_step(ODD_WATER, LIMITS, 8.0, 2.0),
                     lambda: native.simulate(eq, (-0.0167, 0.5), 9.1, [('naoh', 10.0)], 1.0)):
            with self.assertRaises(native.ImpossibleWaterError):
                call()

    def test_a_dose_that_takes_more_than_there_is_is_a_step_without_a_water_as_before(self):
        eq = chemistry.water_equilibria(12.0, 1.0, 80.0)
        alkalinity = 80.0 / MEQ
        steps = native.simulate(eq, (eq.dic(alkalinity, 7.0), alkalinity), 7.0, [('degas', 500.0)], 1.0)
        self.assertEqual(len(steps), 2)
        self.assertGreater(steps[0][5], 0.0)
        self.assertEqual(steps[1][4:6], (None, None))

    def test_formula_1_still_returns_what_golden_v1_holds(self):
        found = native.analyse(*ODD_V1, formula=1)
        self.assertAlmostEqual(found['dic'], -0.023300501402556982, delta=1e-13)       # the core before this change
        self.assertLess(found['co2_mg_l'], 0.0)
        self.assertIsNotNone(native.why_impossible(*ODD_V1, formula=1))
        self.assertLess(native.equilibria(40.0, 40.0).dic(0.5, 9.0), 0.0)


class OneRuleTests(SimpleTestCase):
    """The reason the pages say (why_impossible) and the core's refusal are one decision."""

    def agree(self, temp_c, salinity, ph, alkalinity_mg_l, **ions):
        reason = native.why_impossible(temp_c, salinity, ph, alkalinity_mg_l, **ions)
        eq = chemistry.water_equilibria(temp_c, salinity, alkalinity_mg_l, **ions)
        try:
            found = native.analyse(temp_c, salinity, ph, alkalinity_mg_l, co2_mg_l=15.0, **ions)
        except native.ImpossibleWaterError:
            found = None
        try:
            dic = eq.dic(alkalinity_mg_l / MEQ, ph)                 # as sensors/trail.py and the recorders ask
        except native.ImpossibleWaterError:
            dic = None
        self.assertEqual(reason is None, found is not None, (temp_c, salinity, ph, alkalinity_mg_l, ions))
        self.assertEqual(reason is None, dic is not None, (temp_c, salinity, ph, alkalinity_mg_l, ions))
        if found is not None:
            self.assertEqual(found['dic'], dic)
            for name in CONCENTRATIONS:
                self.assertGreater(found[name], 0.0, (name, temp_c, salinity, ph, alkalinity_mg_l))
        return reason is None

    def test_over_random_waters_on_both_sides_of_the_floor(self):
        rng = random.Random(20261110)
        possible = 0
        for _case in range(3000):
            temp_c, salinity = rng.uniform(0, 40), rng.choice([0.0, 0.3, rng.uniform(0, 5), rng.uniform(5, 40)])
            ph = rng.uniform(6.0, 12.0)
            ions = rng.choice([{}, {'conductivity_25_us_cm': rng.uniform(50, 3000)}, {'hardness_mg_l': 150.0},
                               {'water_origin': 'salt_added'}])
            floor = native.alkalinity_floor(temp_c, salinity, ph, 100.0, **ions)
            alkalinity = rng.choice([rng.uniform(0.1, 400), max(0.01, floor * rng.uniform(0.9, 1.1))])
            possible += self.agree(temp_c, salinity, ph, alkalinity, **ions)
        self.assertGreater(possible, 1500)                          # both sides of the floor are met
        self.assertGreater(3000 - possible, 200)

    def test_on_the_floor_and_a_last_digit_beside_it(self):
        for temp_c, salinity, ph in ((25.0, 35.0, 9.0), (10.0, 5.0, 10.0), (40.0, 40.0, 9.0), (30.0, 15.0, 11.5)):
            floor = native.alkalinity_floor(temp_c, salinity, ph)              # sea water: the same at any alkalinity
            decided = [self.agree(temp_c, salinity, ph, alkalinity) for alkalinity in (
                floor - 1e-9, math.nextafter(floor, 0), floor, math.nextafter(floor, math.inf), floor + 1e-9)]
            with self.subTest(temp_c=temp_c, salinity=salinity, ph=ph):
                self.assertEqual((decided[0], decided[-1]), (False, True))
                self.assertEqual(decided, sorted(decided))                  # once possible, possible above

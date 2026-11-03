"""The calculator around the Water Quality Management Chart (farm/water/calculation.py): the dosing recipes and
the simulator (farm/water/dosing.py), the four small charts (farm/water/charts.py), the CO₂ the air leaves in a
water (farm/water/chemistry.py), and the page with its live parts, its report and the values a unit gives it.
Every number is checked against an independent calculation or a published value, and against the source's own
code (deffeyes_reference/reference.json, made by deffeyes_reference/driver.ts) where the source got it right;
where it did not, the test says which bug document entry it is."""
import json
import math
import re
from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone, translation

from core.models import Profile

from ..models import ProductionDepartment, Site, System, WaterLimit, WaterMeasurement
from ..water import calculation, charts, chemistry, deffeyes, dosing, services
from ..water.deffeyes import Limits, Target, Water, analyse
from ..water.evaluate import Status
from .helpers import make_species, role, stock_fish
from .test_deffeyes import plummer_busenberg
from .test_stock import make_unit

REFERENCE = json.loads((Path(__file__).parent / 'deffeyes_reference' / 'reference.json').read_text(encoding='utf-8'))
# The source's reagent names (reagents.ts REAGENTS) and ours.
SOURCE_NAMES = {'Sodium Bicarbonate': 'nahco3', 'Sodium Carbonate': 'na2co3', 'Sodium Hydroxide': 'naoh',
                'Calcium Carbonate': 'caco3', 'Calcium Hydroxide': 'caoh2', 'Calcium Oxide': 'cao', 'Add CO₂': 'co2',
                'De-gas CO₂': 'degas', 'Muriatic Acid': 'hcl'}
PARTS = ['source', 'actions', 'errors', 'simulator', 'plot-nh3', 'plot-h2s', 'deffeyes', 'plot-carbonate',
         'plot-saturation', 'results']


def setUpModule():
    call_command('compile_catalogs', verbosity=0)    # the language tests read the built catalogs


def water_point(temp_c, salinity, ph, alkalinity_mg_l):
    """(equilibria, (DIC, alkalinity meq/L)) of a water."""
    eq = chemistry.equilibria(temp_c, salinity)
    alkalinity = alkalinity_mg_l / chemistry.MG_CACO3_PER_MEQ
    return eq, (eq.dic(alkalinity, ph), alkalinity)


def fresh_ph(dic, alkalinity, temp_c=25):
    """An independent fresh-water carbonate system (no salinity, no boron, no pH scales): K1 and K2 of Plummer &
    Busenberg (1982), Kw of Harned & Owen (1958) at 25 °C (pKw 13.995). The pH (mol/L ≈ mol/kg) at which
    alkalinity = DIC (α1 + 2 α2) + Kw/[H⁺] − [H⁺], by bisection; DIC in mmol/L, alkalinity in meq/L."""
    pk1, pk2 = plummer_busenberg(temp_c)
    k1, k2, kw = 10 ** -pk1, 10 ** -pk2, 10 ** -13.995

    def excess(ph):
        h = 10 ** -ph
        whole = h * h + h * k1 + k1 * k2
        return dic / 1000 * (h * k1 + 2 * k1 * k2) / whole + kw / h - h - alkalinity / 1000

    low, high = 0.0, 14.0
    for _step in range(100):
        middle = (low + high) / 2
        if excess(middle) < 0:
            low = middle
        else:
            high = middle
    return (low + high) / 2


# ---- the reagents and the recipes --------------------------------------------------------------------------------
class ReagentTests(SimpleTestCase):
    def test_the_molar_masses_are_the_formulas(self):
        # IUPAC standard atomic weights; the chemistry's own constants are the same sums.
        self.assertAlmostEqual(dosing.BY_KEY['co2'].molar_mass, chemistry.MG_CO2_PER_MMOL, places=9)
        self.assertAlmostEqual(dosing.BY_KEY['caco3'].molar_mass / 2, chemistry.MG_CACO3_PER_MEQ, places=9)
        # The source's (reagents.ts REAGENTS): the same within 2e-5 (its CO₂ is 44.010, WQ-35).
        for name, mass in (('nahco3', 84.007), ('na2co3', 105.988), ('naoh', 39.997), ('caco3', 100.087),
                           ('caoh2', 74.093), ('cao', 56.077), ('co2', 44.010), ('hcl', 36.461)):
            with self.subTest(name=name):
                self.assertAlmostEqual(dosing.BY_KEY[name].molar_mass / mass, 1, delta=2e-5)

    def test_each_reagent_moves_the_water_its_way(self):
        # Deffeyes (1965); Stumm & Morgan (1996) 4.5: per mmol, DIC and alkalinity.
        moves = {'nahco3': (1, 1), 'na2co3': (1, 2), 'naoh': (0, 1), 'caco3': (1, 2), 'caoh2': (0, 2), 'cao': (0, 2),
                 'co2': (1, 0), 'degas': (-1, 0), 'hcl': (0, -1)}
        self.assertEqual({reagent.key: (reagent.dic, reagent.alkalinity) for reagent in dosing.REAGENTS}, moves)
        # The source's angles (`radians`) follow from them.
        for key, angle in (('nahco3', math.pi / 4), ('na2co3', math.atan(2)), ('naoh', math.pi / 2), ('co2', 0),
                           ('degas', math.pi), ('hcl', 3 * math.pi / 2)):
            self.assertAlmostEqual(dosing.BY_KEY[key].angle, angle, places=12)

    def test_the_alkalinity_a_gram_gives_is_the_stoichiometry(self):
        # One equivalent of alkalinity is 50.04 g as CaCO₃ (Standard Methods 2320 B), so a kg of alkalinity as
        # CaCO₃ takes 1.68 kg NaHCO₃, 1.06 kg Na₂CO₃, 0.80 kg NaOH, 0.74 kg Ca(OH)₂, 0.56 kg CaO: the factors every
        # RAS text gives (e.g. Timmons & Ebeling, Recirculating Aquaculture). The simulator adds them to a water.
        eq, start = water_point(12, 1, 7.0, 80)
        for key, kilograms in (('nahco3', 1.679), ('na2co3', 1.059), ('naoh', 0.799), ('caoh2', 0.740),
                               ('cao', 0.560)):
            with self.subTest(key=key):
                steps = dosing.simulate(eq, start, 7.0, {key: kilograms * 1000}, 1000)    # in 1000 m³: 1 g/m³ each
                gained = (steps[-1].alkalinity - start[1]) * chemistry.MG_CACO3_PER_MEQ
                self.assertAlmostEqual(gained, 1, delta=0.002)

    def test_the_recipes_are_the_sources(self):
        # 798 cases of the source's calculateDosingRecipes (every pair of the nine reagents, the default four and all
        # nine, three waters, seven targets, two volumes): the same recipes in the same order, the same grams within
        # 2e-5 (the molar masses), the same moves. Except where the source finds none for a base and stripping,
        # which reach a target up and to the left (WQ-40).
        missed = []
        for case in REFERENCE['dosing']:
            eq, start = water_point(case['temperature_c'], case['salinity_ppt'], case['ph'], case['alkalinity_mg_l'])
            _eq, end = water_point(case['temperature_c'], case['salinity_ppt'], case['target_ph'],
                                   case['target_alkalinity_mg_l'])
            self.assertAlmostEqual(start[0], case['dic'], delta=1e-7)
            ours = dosing.recipes(start, end, {SOURCE_NAMES[name] for name in case['reagents']}, case['volume_m3'])
            theirs = [[(SOURCE_NAMES[step[0]], *step[1:]) for step in recipe] for recipe in case['recipes']]
            keys = [[dose.reagent.key for dose in recipe.doses] for recipe in ours]
            if keys != [[step[0] for step in recipe] for recipe in theirs]:
                missed.append((case, keys))
                continue
            for recipe, source in zip(ours, theirs):
                for dose, (_key, grams, delta_alkalinity, delta_dic) in zip(recipe.doses, source):
                    self.assertAlmostEqual(dose.grams / grams, 1, delta=2e-5)
                    self.assertAlmostEqual(dose.delta_alkalinity, delta_alkalinity, delta=1e-6)
                    self.assertAlmostEqual(dose.delta_dic, delta_dic, delta=1e-6)
        self.assertEqual(len(missed), 3)
        for case, keys in missed:
            self.assertEqual(case['recipes'], [])
            self.assertIn('De-gas CO₂', case['reagents'])
            self.assertIn(case['reagents'][0], ('Sodium Hydroxide', 'Calcium Hydroxide', 'Calcium Oxide'))
            self.assertEqual(keys, [['degas']])          # straight left: stripping alone

    def test_a_base_and_stripping_reach_up_and_to_the_left(self):
        # WQ-40: the source's intersection divides by an infinite slope and returns nothing; the move is the sum
        # of the two directions, NaOH up (alkalinity) and stripping left (DIC).
        eq, start = water_point(12, 1, 7.0, 80)
        end = (start[0] - 0.3, start[1] + 0.2)
        (made,) = dosing.recipes(start, end, ['naoh', 'degas'], 2.0)
        naoh, degas = made.doses
        self.assertEqual((naoh.reagent.key, degas.reagent.key), ('naoh', 'degas'))
        self.assertAlmostEqual(naoh.grams, 0.2 * dosing.BY_KEY['naoh'].molar_mass * 2.0, places=9)
        self.assertAlmostEqual(degas.grams, 0.3 * chemistry.MG_CO2_PER_MMOL * 2.0, places=9)
        self.assertEqual(made.waypoint, (start[0], start[1] + 0.2))

    def test_every_recipe_takes_the_water_to_its_target(self):
        # Independent of the source: the doses, added by the simulator, end at the target's DIC, alkalinity and
        # pH; every amount is positive.
        for temp_c, salinity, ph, alkalinity, target_ph, target_alkalinity in (
                (12, 1, 7.0, 80, 7.5, 100), (25, 35, 8.1, 115, 7.8, 140), (8, 0, 6.6, 30, 7.2, 60),
                (12, 1, 7.0, 80, 6.8, 70), (20, 5, 7.6, 150, 8.2, 120)):
            eq, start = water_point(temp_c, salinity, ph, alkalinity)
            _eq, end = water_point(temp_c, salinity, target_ph, target_alkalinity)
            found = dosing.recipes(start, end, [reagent.key for reagent in dosing.REAGENTS], 3.0)
            self.assertTrue(found)
            for recipe in found:
                with self.subTest(water=(temp_c, salinity, ph, alkalinity), recipe=recipe.doses):
                    self.assertTrue(all(dose.grams > 0 for dose in recipe.doses))
                    steps = dosing.simulate(eq, start, ph, {dose.reagent.key: dose.grams for dose in recipe.doses}, 3.0)
                    self.assertAlmostEqual(steps[-1].dic, end[0], delta=1e-6)
                    self.assertAlmostEqual(steps[-1].alkalinity, end[1], delta=1e-6)
                    self.assertAlmostEqual(steps[-1].ph, target_ph, delta=1e-5)

    def test_practical_recipes_first_and_an_overshoot_only_when_nothing_else_reaches(self):
        eq, start = water_point(12, 1, 7.0, 80)
        _eq, end = water_point(12, 1, 7.5, 100)
        found = dosing.recipes(start, end, [reagent.key for reagent in dosing.REAGENTS], 1.0)
        self.assertLessEqual(len(found), dosing.MAX_RECIPES)
        self.assertEqual([dose.reagent.key for dose in found[0].doses], ['nahco3', 'naoh'])
        self.assertFalse(any(recipe.counter_productive for recipe in found))
        self.assertEqual([recipe.priority for recipe in found], sorted(recipe.priority for recipe in found))
        # Down and to the right with sodium bicarbonate and acid only: the overshoot is the one way, so it is given.
        _eq, down = water_point(12, 1, 6.5, 70)
        (only,) = dosing.recipes(start, down, ['nahco3', 'hcl'], 1.0)
        self.assertTrue(only.counter_productive)
        self.assertEqual(dosing.recipes(start, start, ['nahco3', 'naoh'], 1.0), [])

    def test_without_a_volume_the_doses_are_per_cubic_metre(self):
        eq, start = water_point(12, 1, 7.0, 80)
        _eq, end = water_point(12, 1, 7.5, 100)
        (per_m3,) = dosing.recipes(start, end, ['nahco3', 'naoh'])
        (in_two,) = dosing.recipes(start, end, ['nahco3', 'naoh'], 2.0)
        for dose, doubled in zip(per_m3.doses, in_two.doses):
            self.assertIsNone(dose.grams)
            self.assertAlmostEqual(doubled.grams, 2 * dose.mg_l, places=9)


# ---- the simulator --------------------------------------------------------------------------------------------
class SimulatorTests(SimpleTestCase):
    def test_the_steps_are_the_sources_where_the_water_exists(self):
        # 36 cases of the source's calcForwardDosing: the same DIC, alkalinity, pH and CO₂ at every step, the
        # moves within 2e-5 of their size (the molar masses), but where the source clamps a negative DIC or
        # alkalinity to 0 (WQ-41): there ours goes on (acid) or stops (no carbon left).
        clamped = 0
        for case in REFERENCE['forward']:
            eq, start = water_point(case['temperature_c'], case['salinity_ppt'], case['ph'], case['alkalinity_mg_l'])
            amounts = {SOURCE_NAMES[name]: grams for name, grams in case['amounts'].items()}
            steps = dosing.simulate(eq, start, case['ph'], amounts, case['volume_m3'])
            self.assertEqual(len(steps), len(case['steps']))
            moved = 0.0
            for step, (label, dic, alkalinity, ph, co2) in zip(steps, case['steps']):
                with self.subTest(case=case['amounts'], volume=case['volume_m3'], step=label):
                    if step.dic <= 0 or step.alkalinity < 0:
                        clamped += 1
                        self.assertEqual(0, dic if step.dic <= 0 else alkalinity)
                        continue
                    moved += abs(step.dic - start[0]) + abs(step.alkalinity - start[1])
                    self.assertAlmostEqual(step.dic, dic, delta=2e-5 * moved + 1e-8)
                    self.assertAlmostEqual(step.alkalinity, alkalinity, delta=2e-5 * moved + 1e-8)
                    self.assertAlmostEqual(step.ph, ph, delta=1e-4)     # steep where little carbon is left
                    self.assertAlmostEqual(step.co2_mg_l / co2, 1, delta=3e-4)     # ln 10 × the pH's
        self.assertEqual(clamped, 13)     # 500 g stripped and 4 kg HCl in each water, 40 g HCl in 1 m³ of the softest

    def test_more_stripping_than_there_is_carbon_is_no_water(self):
        # WQ-41: the source clamps the DIC at 0 and shows a pH and CO₂ of NaN; there is no such water.
        eq, start = water_point(12, 1, 7.0, 80)
        steps = dosing.simulate(eq, start, 7.0, {'degas': 500, 'naoh': 10}, 1.0)
        self.assertEqual([step.reagent.key for step in steps[1:]], ['naoh', 'degas'])   # REAGENTS' order
        self.assertLess(steps[-1].dic, 0)
        self.assertIsNone(steps[-1].ph)

    def test_acid_past_the_alkalinity_is_shown_as_acid(self):
        # WQ-41: the source clamps the alkalinity at 0 and shows pH 4.57 after 4 kg HCl in 1 m³. The acid left over
        # is 4000 / 36.461 mmol/L − 1.6 meq/L, 108 mmol/L of H⁺: −log [H⁺] = 0.97, and as a meter reads it (NBS,
        # the activity: γH 0.88 at the water's salinity, 0.78 by Davies at 0.11 mol/L) 1.0 to 1.1.
        eq, start = water_point(12, 1, 7.0, 80)
        steps = dosing.simulate(eq, start, 7.0, {'hcl': 4000}, 1.0)
        excess = 4000 / dosing.BY_KEY['hcl'].molar_mass - start[1]
        self.assertAlmostEqual(steps[-1].alkalinity, -excess, places=9)
        self.assertAlmostEqual(steps[-1].ph, -math.log10(excess / 1000), delta=0.11)
        self.assertLess(steps[-1].ph, 1.1)

    def test_sodium_bicarbonate_by_an_independent_carbonate_system(self):
        # 100 g NaHCO₃ in 1 m³ of fresh water at 25 °C, pH 7.0, 50 mg/L: the new pH by Plummer & Busenberg's
        # constants, solved here on their own, within 0.005 pH (the constants differ by less than 0.002 pK).
        eq, start = water_point(25, 0, 7.0, 50)
        self.assertAlmostEqual(fresh_ph(*start), 7.0, delta=0.003)
        steps = dosing.simulate(eq, start, 7.0, {'nahco3': 100}, 1.0)
        added = 100 / dosing.BY_KEY['nahco3'].molar_mass
        self.assertAlmostEqual(steps[-1].ph, fresh_ph(start[0] + added, start[1] + added), delta=0.005)
        # Then 20 g NaOH: alkalinity only.
        steps = dosing.simulate(eq, start, 7.0, {'nahco3': 100, 'naoh': 20}, 1.0)
        base = 20 / dosing.BY_KEY['naoh'].molar_mass
        self.assertAlmostEqual(steps[-1].ph, fresh_ph(start[0] + added, start[1] + added + base), delta=0.005)

    def test_stripping_below_the_air_is_flagged(self):
        eq, start = water_point(12, 1, 7.0, 80)
        air = chemistry.co2_from_air(12, 1)
        steps = dosing.simulate(eq, start, 7.0, {'degas': 10}, 1.0, air)
        self.assertGreater(steps[-1].co2_mg_l, air)
        self.assertFalse(steps[-1].below_air)
        steps = dosing.simulate(eq, start, 7.0, {'degas': 17.4}, 1.0, air)
        self.assertLess(steps[-1].co2_mg_l, air)
        self.assertTrue(steps[-1].below_air)
        # A base can take the CO₂ below the air's: that is chemistry, not stripping, and is not flagged.
        steps = dosing.simulate(eq, start, 7.0, {'naoh': 20}, 1.0, air)
        self.assertLess(steps[-1].co2_mg_l, air)
        self.assertFalse(steps[-1].below_air)

    def test_each_step_is_judged_as_the_water_is(self):
        result = calculation.calculate(
            Water(12, 1, 7.0, 80, tan_mg_l=0.5, total_sulfide_ug_l=2), Limits(0.0103, 15, 2, 50, 100), Target(7.5, 100),
            1.0, deffeyes.ALL_LAYERS, ['nahco3'], 1.0, {'naoh': 25, 'hcl': 60})
        water, base, acid = result.steps
        eq = result.analysis.equilibria
        self.assertEqual(water.co2.status, Status.CRITICAL)                       # 16.9 mg/L, the limit 15
        for judged in result.steps:
            step = judged.step
            with self.subTest(step=step.reagent):
                border = eq.ph_where_co2(step.alkalinity, 15 / chemistry.MG_CO2_PER_MMOL)
                self.assertEqual(judged.co2, deffeyes.judge(step.ph, border, False))
                self.assertEqual(judged.nh3, deffeyes.judge(step.ph, result.analysis.nh3.ph, True))
                self.assertAlmostEqual(judged.nh3_n_mg_l, 0.5 * eq.nh3_share(step.ph), places=12)
                self.assertAlmostEqual(judged.h2s_ug_l, 2 * chemistry.H2S_PER_S * eq.h2s_share(step.ph), places=12)
        self.assertGreater(base.step.ph, 8.04)                                  # past the NH₃ border
        self.assertEqual(base.nh3.status, Status.CRITICAL)
        self.assertEqual(result.change['ph'], acid.step.ph - water.step.ph)


# ---- carbon dioxide from the air --------------------------------------------------------------------------------
class AirTests(SimpleTestCase):
    @staticmethod
    def weiss_per_kg(temp_c, salinity):
        """Weiss (1974) in mol/(kg atm), as Dickson, Sabine & Christian (2007) give it."""
        t = (temp_c + 273.15) / 100
        return math.exp(-60.2409 + 93.4517 / t + 23.3585 * math.log(t)
                        + salinity * (0.023517 - 0.023656 * t + 0.0047036 * t * t))

    def test_the_solubility_is_weisss(self):
        # The check value of Dickson et al. (2007), SOP: ln K0 = −3.5617 at 25 °C and S 35, per kg.
        self.assertAlmostEqual(math.log(self.weiss_per_kg(25, 35)), -3.5617, delta=0.0001)
        # The per-litre form is the per-kg one times the water's density: 1.02334 kg/L at 25 °C and 35 (UNESCO 1981).
        self.assertAlmostEqual(chemistry.k0_co2(25, 35) / self.weiss_per_kg(25, 35), 1.02334, delta=0.001)
        # In fresh water, Plummer & Busenberg (1982) log KH = 108.3865 + 0.01985076 T − 6919.53/T
        # − 40.45154 log T + 669365/T²: within 0.003 (0.7 %).
        for temp_c in (5, 12, 25):
            t = temp_c + 273.15
            log_kh = 108.3865 + 0.01985076 * t - 6919.53 / t - 40.45154 * math.log10(t) + 669365 / t ** 2
            self.assertAlmostEqual(math.log10(chemistry.k0_co2(temp_c, 0)), log_kh, delta=0.003)

    def test_the_vapour_pressure_and_the_co2_of_air_saturated_water(self):
        # Water's vapour pressure at 25 °C: 3.1690 kPa (IAPWS), 0.031276 atm.
        self.assertAlmostEqual(chemistry.vapour_pressure_atm(25) / 0.031276, 1, delta=0.002)
        # 420 µmol/mol in the dry air over fresh water at 12 °C, sea level: K0 xCO₂ (1 − Pwv) × 44.0095 g/mol.
        expected = chemistry.k0_co2(12, 0) * 420e-6 * (1 - chemistry.vapour_pressure_atm(12)) * 44009.5
        self.assertAlmostEqual(chemistry.co2_from_air(12, 0), expected, places=12)
        self.assertAlmostEqual(chemistry.co2_from_air(12, 0), 0.91, delta=0.01)
        self.assertLess(chemistry.co2_from_air(12, 0, chemistry.pressure_atm(1000)), chemistry.co2_from_air(12, 0))


# ---- the four small charts ----------------------------------------------------------------------------------------
class SmallChartTests(SimpleTestCase):
    def test_their_data_are_the_sources(self):
        # The source's generateUIAvsPHData, generateH2SvsPHData, generateCarbonateVsPHData and
        # generateSaturationVsPHData (rounded there to 6, 4, 6 and 3 decimals) at the same pH.
        for case in REFERENCE['ph_charts']:
            eq = chemistry.equilibria(case['temperature_c'], case['salinity_ppt'])
            with self.subTest(case=(case['temperature_c'], case['salinity_ppt'])):
                for ph, nh3 in case['uia']:
                    self.assertAlmostEqual(case['tan_mg_l'] * eq.nh3_share(ph), nh3, delta=1e-6)
                for ph, h2s, hs, _ug_l in case['h2s']:
                    self.assertAlmostEqual(100 * eq.h2s_share(ph), h2s, delta=1e-4)
                    self.assertAlmostEqual(100 - 100 * eq.h2s_share(ph), hs, delta=1e-4)
                for ph, *shares in case['carbonate']:
                    for ours, theirs in zip(eq.fractions(ph), shares):
                        self.assertAlmostEqual(ours, theirs, delta=1e-6)
                _eq, (dic, _alkalinity) = water_point(case['temperature_c'], case['salinity_ppt'], case['ph'],
                                                      case['alkalinity_mg_l'])
                for ph, calcite, aragonite in case['saturation']:
                    for ksp, theirs in ((eq.ksp_calcite, calcite), (eq.ksp_aragonite, aragonite)):
                        ours = charts.saturation_index(eq, dic, ph, case['calcium_mg_l'], ksp)
                        self.assertAlmostEqual(ours, theirs, delta=0.0006)

    def test_their_values_by_published_constants(self):
        # Emerson et al. (1975): NH₃ share = 1 / (1 + 10^(pK − pH)), pK = 0.09018 + 2729.92/T, fresh water.
        eq = chemistry.equilibria(12, 0)
        for ph in (6.5, 7.5, 8.5):
            emerson = 1 / (1 + 10 ** (0.09018 + 2729.92 / 285.15 - ph))
            self.assertAlmostEqual(eq.nh3_share(ph) / emerson, 1, delta=0.005)
        # Half the sulfide is H₂S at pH = pK1 (6.98 in fresh water at 25 °C, Millero 1986); half the DIC is CO₂ at
        # pK1 and half HCO₃⁻ at pK2 (6.352 and 10.329, Plummer & Busenberg 1982).
        eq = chemistry.equilibria(25, 0)
        self.assertAlmostEqual(eq.h2s_share(6.98), 0.5, delta=0.003)
        co2, hco3, co3 = eq.fractions(6.352)
        self.assertAlmostEqual(co2 / hco3, 1, delta=0.005)
        co2, hco3, co3 = eq.fractions(10.329)
        self.assertAlmostEqual(co3 / hco3, 1, delta=0.005)

    def test_the_saturation_index_is_zero_on_the_big_charts_line(self):
        # The same Ω two ways: a point of the chart's calcite line (Ω = 1) has a saturation index of 0.
        result = analyse(Water(25, 35, 8.1, 115, calcium_mg_l=412))
        eq = result.equilibria
        line = deffeyes.geometry(result).omega['calcite'][0]
        for dic, alkalinity in line[::20]:
            ph = eq.ph_at(dic, alkalinity)
            self.assertAlmostEqual(charts.saturation_index(eq, dic, ph, 412, eq.ksp_calcite), 0, delta=1e-6)

    def test_the_bands_follow_the_border(self):
        result = analyse(Water(12, 1, 7.0, 80, tan_mg_l=0.5, total_sulfide_ug_l=2), Limits(0.0103, 15, 2))
        border = result.nh3.ph
        self.assertEqual(charts.bands(result.nh3, 6.0, 9.5),
                         [('safe', 6.0, border - 0.2), ('alert', border - 0.2, border), ('danger', border, 9.5)])
        border = result.h2s.ph
        self.assertEqual(charts.bands(result.h2s, 4.0, 12.5),
                         [('danger', 4.0, border), ('alert', border, border + 0.2), ('safe', border + 0.2, 12.5)])
        # A missing value or limit is never drawn as safe; a limit that cannot be reached is safe everywhere.
        self.assertEqual(charts.bands(analyse(Water(12, 1, 7.0, 80)).nh3, 6.0, 9.5), [])
        self.assertEqual(charts.bands(analyse(Water(12, 1, 7.0, 80, tan_mg_l=0.5)).nh3, 6.0, 9.5), [])
        low_tan = analyse(Water(12, 1, 7.0, 80, tan_mg_l=0.005), Limits(0.0103))
        self.assertEqual(charts.bands(low_tan.nh3, 6.0, 9.5), [('safe', 6.0, 9.5)])
        past = analyse(Water(12, 1, 7.0, 80, tan_mg_l=500), Limits(0.0103))
        self.assertLess(past.nh3.ph, 6.0)
        self.assertEqual(charts.bands(past.nh3, 6.0, 9.5), [('danger', 6.0, 9.5)])

    def test_the_water_stays_on_its_chart(self):
        # WQ-42: the source's NH₃ chart runs from pH 6 to 9.5 and up to 2.5 times the limit, and its points are
        # dropped outside: a water at pH 9.8, or with more NH₃ than that, had no point.
        result = analyse(Water(12, 1, 9.8, 200, tan_mg_l=2), Limits(0.0103, 15))
        plot = charts.nh3_plot(result)
        self.assertEqual(plot.x, (6.0, 10.5))
        self.assertGreaterEqual(plot.y[1], result.nh3_n_mg_l)
        drawing = charts.draw(plot)
        self.assertIn('water', [dot['key'] for dot in drawing.dots])
        self.assertIn('water', [line['key'] for line in drawing.verticals])
        self.assertIsNone(charts.nh3_plot(analyse(Water(12, 1, 7.0, 80))))         # without the TAN

    def test_saturation_only_where_its_constants_hold(self):
        self.assertIsNone(charts.saturation_plot(analyse(Water(12, 1, 7.0, 80, calcium_mg_l=400))))   # WQ-32
        self.assertIsNone(charts.saturation_plot(analyse(Water(25, 35, 8.1, 115))))
        plot = charts.saturation_plot(analyse(Water(25, 35, 8.1, 115, calcium_mg_l=412)))
        self.assertEqual([key for key, _name, _curve in plot.series], ['calcite', 'aragonite'])
        self.assertLessEqual(plot.y[0], 0)
        self.assertGreaterEqual(plot.y[1], 0)
        # Its ticks are whole steps (the curves run from −2.27 to 1.40 here), never a half rounded to −0.
        drawing = charts.draw(charts.saturation_plot(analyse(Water(12, 35, 7.0, 80, calcium_mg_l=400))))
        self.assertEqual([tick['label'] for tick in drawing.y_ticks], ['-3', '-2', '-1', '0', '1', '2'])

    def test_the_svg_has_plain_coordinates_and_the_languages_labels(self):
        result = analyse(Water(12, 1, 7.0, 80, tan_mg_l=0.5, total_sulfide_ug_l=2), Limits(0.0103, 15, 2))
        for language in ('en', 'tr', 'nb'):
            with translation.override(language):
                drawings = [charts.draw(plot) for plot in charts.plots(result).values() if plot]
            for drawing in drawings:
                for series in drawing.series:
                    self.assertRegex(series['points'], r'^-?[\d.]+,-?[\d.]+( -?[\d.]+,-?[\d.]+)*$')
                for value in [band['x'] for band in drawing.bands] + [dot['y'] for dot in drawing.dots]:
                    self.assertRegex(value, r'^-?\d+\.\d\d$')
            labels = [tick['label'] for tick in drawings[1].y_ticks]
            self.assertEqual(labels[-1], {'en': '100 %', 'tr': '%100', 'nb': '100 %'}[language])
            self.assertEqual(drawings[0].x_ticks[1]['label'], {'en': '6.5', 'tr': '6,5', 'nb': '6,5'}[language])


# ---- the page --------------------------------------------------------------------------------------------------
class CalculatorPageTests(TestCase):
    url = reverse('farm:water_calculator')
    results_url = reverse('farm:water_calculator_results')
    report_url = reverse('farm:water_calculator_report')
    values = {'temperature_c': '12', 'ph': '7', 'salinity_ppt': '1', 'alkalinity_mg_l': '80', 'tan_mg_l': '0.5',
              'total_sulfide_ug_l': '2', 'volume_m3': '1', 'target_ph': '7.5', 'target_alkalinity_mg_l': '100',
              'alkalinity_low_mg_l': '50', 'alkalinity_high_mg_l': '100', 'nh3_n_limit_mg_l': '0.0103',
              'co2_limit_mg_l': '15', 'h2s_limit_ug_l': '2', 'drawn': '1',
              'reagents': ['nahco3', 'naoh', 'co2', 'degas'], 'layers': [key for key, _label in deffeyes.LAYERS]}

    def setUp(self):
        self.user = get_user_model().objects.create_user('ali', 'ali@example.com', 'eski-sifre-123')
        self.user.groups.add(role('Water reader', 'view_watermeasurement'))
        self.client.force_login(self.user)

    def query(self, **changes):
        return {**self.values, **changes}

    def test_the_page_is_laid_out_as_the_sources(self):
        html = self.client.get(self.url).content.decode()
        # Where the values come from, the input bar's tabs, then the parts in the source's order.
        tabs = re.findall(r'data-tab="(\w+)"', html)
        self.assertEqual(tabs, ['water', 'system', 'target', 'limits', 'reagents', 'simulator'])
        self.assertEqual(re.findall(r'data-live-part="([\w-]+)"', html), PARTS)
        self.assertLess(html.index('name="point"'), html.index('data-tabs'))
        self.assertLess(html.index('data-live-part="plot-h2s"'), html.index('data-live-part="deffeyes"'))
        for text in ('Un-ionised ammonia against pH', 'H₂S and HS⁻ against pH', 'CO₂, HCO₃⁻ and CO₃²⁻ against pH',
                     'Calcite and aragonite saturation against pH', 'Dosing recipes (3)', 'Print report',
                     'class="ph-chart"', '<svg class="deffeyes-chart"'):
            self.assertIn(text, html)

    def test_the_interactive_contract(self):
        # What frontend/poll.ts and components.ts read: the live form and its fragment's address, its parts, the
        # fields never inside a part, the layer boxes in the form, the choice of a unit that sends the form, the
        # Calculate button for a browser without the script.
        html = self.client.get(self.url).content.decode()
        self.assertIn(f'<form method="get" action="{self.url}" class="calc" data-live="{self.results_url}" novalidate>',
                      html)
        self.assertRegex(html, r'<select name="point" data-autosubmit="" id="id_point">')
        self.assertIn('<noscript><button type="submit" class="button button-inline">Calculate</button></noscript>', html)
        self.assertEqual(html.count('name="layers"'), len(deffeyes.LAYERS))
        fragment = self.client.get(self.results_url, self.query()).content.decode()
        self.assertEqual(re.findall(r'data-live-part="([\w-]+)"', fragment), PARTS)
        self.assertNotRegex(fragment, r'<(input|select|textarea)\b')            # no field is ever replaced
        poll = (Path(__file__).resolve().parents[2] / 'frontend' / 'poll.ts').read_text(encoding='utf-8')
        components = (Path(__file__).resolve().parents[2] / 'frontend' / 'components.ts').read_text(encoding='utf-8')
        for selector in ("'form[data-live]'", "'[data-live-part]'", "'[data-error-for]'", "'[data-autosubmit]'",
                         'history.replaceState', 'AbortController'):
            self.assertIn(selector, poll)
        for selector in ("'select[data-autosubmit]'", "'button[data-print]'", "'[data-panel]'"):
            self.assertIn(selector, components)

    def test_the_fragment_draws_what_the_page_draws(self):
        query = self.query(dose_nahco3='50', ph='7.2')
        page = self.client.get(self.url, query).content.decode()
        fragment = self.client.get(self.results_url, query).content.decode()
        for name in ('results', 'simulator', 'plot-nh3', 'deffeyes'):
            with self.subTest(part=name):
                pattern = rf'<(\w+) [^>]*data-live-part="{name}".*?</\1>\n?'
                self.assertEqual(re.search(pattern, page, re.S).group(0)[:4000],
                                 re.search(pattern, fragment, re.S).group(0)[:4000])

    def test_unticking_a_layer_takes_it_off_the_chart(self):
        everything = self.client.get(self.results_url, self.query()).content.decode()
        self.assertIn('deffeyes-zone-nh3', everything)
        layers = [key for key, _label in deffeyes.LAYERS if key != 'nh3']
        fewer = self.client.get(self.results_url, self.query(layers=layers)).content.decode()
        self.assertNotIn('deffeyes-zone-nh3', fewer)
        self.assertIn('deffeyes-zone-co2', fewer)
        none = self.client.get(self.results_url, self.query(layers=[])).content.decode()
        self.assertNotIn('deffeyes-zone', none)
        self.assertNotRegex(none, r'class="deffeyes-isoline[ "]')

    def test_a_wrong_value_comes_back_on_its_field(self):
        fragment = self.client.get(self.results_url, self.query(ph='25')).content.decode()
        self.assertIn('<a href="#id_ph">pH (NBS scale)</a>', fragment)
        self.assertRegex(fragment, r'<ul class="errorlist" data-error-for="ph"><li>Ensure this value is less than or '
                                   r'equal to 12')
        self.assertNotIn('class="ph-chart"', fragment)
        self.assertIn('show again once every value is right', fragment)
        # Without the script the page draws the error on the field itself.
        page = self.client.get(self.url, self.query(ph='25'))
        self.assertIn('ph', page.context['form'].errors)
        self.assertIsNone(page.context['chart'])

    def test_the_recipes_and_the_dosing_layer(self):
        response = self.client.get(self.results_url, self.query())
        recipes = response.context['result'].recipes
        self.assertEqual([[dose.reagent.key for dose in recipe.doses] for recipe in recipes],
                         [['nahco3', 'naoh'], ['nahco3', 'degas'], ['co2', 'naoh']])
        html = response.content.decode()
        self.assertIn('13.6 g', html)               # NaHCO₃ for 1 m³ (the source: 13.646 g)
        self.assertIn('Dosing path: tick one reagent', html)
        two = self.client.get(self.results_url, self.query(reagents=['nahco3', 'naoh'])).content.decode()
        self.assertIn('class="deffeyes-wedge"', two)
        self.assertIn('class="deffeyes-dosing-path"', two)
        self.assertEqual(two.count('class="deffeyes-reagent '), 2)
        one = self.client.get(self.results_url, self.query(reagents=['hcl'])).content.decode()
        self.assertIn('data-reagent="hcl"', one)
        self.assertIn('A recipe takes two reagents', one)
        no_volume = self.client.get(self.results_url, self.query(volume_m3='')).content.decode()
        self.assertIn('13.6 g/m³', no_volume)
        no_target = self.client.get(self.results_url, self.query(target_ph='', target_alkalinity_mg_l=''))
        self.assertContains(no_target, 'Give a target pH and alkalinity for the recipes.')

    def test_the_simulator(self):
        response = self.client.get(self.results_url, self.query(dose_nahco3='50', dose_degas='10'))
        steps = response.context['result'].steps
        self.assertEqual([judged.step.reagent and judged.step.reagent.key for judged in steps], [None, 'nahco3', 'degas'])
        html = response.content.decode()
        self.assertIn('Dosing simulator', html)
        self.assertIn('class="deffeyes-simulator"', html)
        self.assertIn('ΔpH +0.51', html)
        self.assertNotIn('Dosing simulator', self.client.get(self.results_url, self.query()).content.decode())
        no_volume = self.client.get(self.results_url, self.query(dose_nahco3='50', volume_m3=''))
        self.assertContains(no_volume, 'Give the volume to follow the amounts.')
        gone = self.client.get(self.results_url, self.query(dose_degas='500'))
        self.assertContains(gone, 'more CO₂ is stripped than the water holds')

    def test_the_report_draws_every_layer(self):
        response = self.client.get(self.report_url, self.query(layers=[], dose_nahco3='50'))
        html = response.content.decode()
        for text in ('Water chemistry report', 'deffeyes-zone-nh3', 'deffeyes-isoline', 'class="ph-chart"',
                     'Dosing recipes', 'Dosing simulator', 'data-print hidden', 'Temperature (°C)'):
            self.assertIn(text, html)
        self.assertNotIn('class="rail"', html)
        page = self.client.get(self.url, self.query(ph='7.2')).content.decode()
        self.assertIn(f'href="{self.report_url}?', page)

    def test_nothing_is_stored_and_reading_is_needed(self):
        self.client.get(self.results_url, self.query(dose_nahco3='50'))
        self.client.get(self.report_url, self.query())
        self.assertFalse(WaterMeasurement.all_objects.exists())
        stranger = get_user_model().objects.create_user('veli', 'veli@example.com')
        stranger.groups.add(role('Tanks', 'view_tank'))
        self.client.force_login(stranger)
        for url in (self.url, self.results_url, self.report_url):
            self.assertEqual(self.client.get(url).status_code, 403)

    def test_it_speaks_each_language(self):
        for language, words in {
            'tr': ('%100', '1,982 mmol/L', 'pH 7,0'),
            'nb': ('100 %', '1,982 mmol/L', 'pH 7,0'),
        }.items():
            Profile.objects.update_or_create(user=self.user, defaults={'language': language})
            for url in (self.url, self.results_url, self.report_url):
                response = self.client.get(url)
                with self.subTest(language=language, url=url):
                    self.assertEqual(response.status_code, 200)
                    self.assertNotIn('%(', response.content.decode())
                    for word in words:
                        self.assertContains(response, word)
            # A value typed in the language is read in it.
            response = self.client.get(self.results_url, self.query(ph='7,2', tan_mg_l='0,5', nh3_n_limit_mg_l='0,0103'))
            self.assertEqual(response.context['analysis'].water.ph, 7.2)


# ---- the values of a unit or a loop -----------------------------------------------------------------------------
class ValuesFromAUnitTests(TestCase):
    url = reverse('farm:water_calculator')

    def setUp(self):
        self.user = get_user_model().objects.create_user('ali', 'ali@example.com', 'eski-sifre-123')
        self.user.groups.add(role('Water keeper', 'view_watermeasurement', 'add_watermeasurement', 'view_tank'))
        self.client.force_login(self.user)
        site = Site.objects.create(name='Bergen', code='BG', altitude=D('120.4'))
        hall = ProductionDepartment.objects.create(site=site, name='Hall A', code='HA')
        self.loop = System.objects.create(name='RAS 1', code='R1', site=site, production_department=hall)
        self.unit = make_unit('T-01', hall, system=self.loop)
        self.salmon = make_species()
        stock_fish(self.user, self.unit, 1000, '50', 10, species=self.salmon)
        now = timezone.now()
        services.record(self.user, point=self.unit, measured_at=now - timedelta(hours=3), source='manual',
                        values={'temperature_c': D('9.5'), 'ph': D('7.12'), 'tan_mg_l': D('0.8')})
        services.record(self.user, point=self.unit, measured_at=now - timedelta(days=5), source='lab',
                        values={'alkalinity_mg_l': D('95'), 'salinity_ppt': D('0.3')})
        WaterLimit.objects.create(species=self.salmon, parameter='nh3_n_mg_l', warning_high=D('0.0100'),
                                  critical_high=D('0.0200'))
        WaterLimit.objects.create(species=self.salmon, parameter='co2_mg_l', critical_high=D('15.0'))
        WaterLimit.objects.create(species=self.salmon, parameter='alkalinity_mg_l', warning_low=D('70'),
                                  warning_high=D('150'))
        self.samples = WaterMeasurement.all_objects.count()

    def test_choosing_a_unit_puts_its_values_in_and_the_address_keeps_them(self):
        response = self.client.get(self.url, {'point': f'tank:{self.unit.pk}'})
        self.assertEqual(response.status_code, 302)
        address = response['Location']
        for part_ in ('temperature_c=9.5', 'ph=7.12', 'tan_mg_l=0.800', 'alkalinity_mg_l=95', 'salinity_ppt=0.3',
                      'altitude_m=120', 'nh3_n_limit_mg_l=0.0200', 'co2_limit_mg_l=15.0', 'alkalinity_low_mg_l=70',
                      'alkalinity_high_mg_l=150', f'loaded=tank%3A{self.unit.pk}', 'drawn=1', 'reagents=nahco3'):
            self.assertIn(part_, address)
        response = self.client.get(address)
        self.assertEqual(response.status_code, 200)
        source = response.context['source']
        self.assertEqual(source['point'], self.unit)
        self.assertEqual({row['offer'].field for row in source['rows'] if not row['changed']},
                         {'temperature_c', 'ph', 'tan_mg_l', 'alkalinity_mg_l', 'salinity_ppt', 'altitude_m',
                          'nh3_n_limit_mg_l', 'co2_limit_mg_l', 'alkalinity_low_mg_l', 'alkalinity_high_mg_l'})
        self.assertEqual(source['missing'], ['Dissolved oxygen (mg/L O₂)'])
        self.assertContains(response, 'The latest values of T-01')
        self.assertContains(response, 'Atlantic salmon: warning above 0.0100, critical above 0.0200')
        self.assertEqual(response.context['analysis'].water.ph, 7.12)
        self.assertEqual(WaterMeasurement.all_objects.count(), self.samples)      # nothing written back

    def test_a_value_changed_here_is_marked_and_kept(self):
        address = self.client.get(self.url, {'point': f'tank:{self.unit.pk}'})['Location']
        changed = address.replace('ph=7.12', 'ph=7.40')
        fragment = self.client.get(reverse('farm:water_calculator_results') + changed[changed.index('?'):])
        rows = {row['offer'].field: row for row in fragment.context['source']['rows']}
        self.assertTrue(rows['ph']['changed'])
        self.assertFalse(rows['temperature_c']['changed'])
        self.assertContains(fragment, 'changed here', count=1)
        self.assertEqual(fragment.context['analysis'].water.ph, 7.4)
        self.assertEqual(WaterMeasurement.objects.get(ph__isnull=False).ph, D('7.12'))

    def test_a_loop_and_manual_entry(self):
        response = self.client.get(self.url, {'point': f'system:{self.loop.pk}', 'drawn': '1', 'temperature_c': '14',
                                              'ph': '7', 'salinity_ppt': '1', 'alkalinity_mg_l': '80'})
        self.assertEqual(response.status_code, 302)
        address = response['Location']
        self.assertIn('temperature_c=14', address)       # the loop has no sample: the values stay as entered
        self.assertIn('altitude_m=120', address)
        page = self.client.get(address)
        self.assertEqual(page.context['source']['missing'][0], 'Temperature (°C)')
        manual = self.client.get(self.url, {'point': '', 'drawn': '1', 'temperature_c': '14', 'ph': '7',
                                            'salinity_ppt': '1', 'alkalinity_mg_l': '80'})
        self.assertEqual(manual.status_code, 200)
        self.assertIsNone(manual.context['source'])

    def test_a_unit_no_longer_there(self):
        response = self.client.get(self.url, {'point': 'tank:00000000-0000-0000-0000-000000000000'}, follow=True)
        self.assertContains(response, 'That unit or system is no longer there')
        self.assertIsNotNone(response.context['chart'])                          # the defaults are drawn

"""The basis NH3 and CO2 are judged on (cross review F1; owner decision 2026-11-09, safety with live fish).

The published NH3 limits (Piper et al. 1982; US EPA 1985) were set on Emerson et al. (1975)'s ideal fraction, every
activity 1; the CO2 guidelines on the free CO2 worked out the same way (Standard Methods 4500-CO2 D) or measured. Formula
3's activity-corrected values are lower in an ion-rich water (12 to 17 % for NH3 at 1000 to 3000 µS/cm), so judged
against limits of the ideal basis they would understate. Every judgement, alarm, status, border and safe TAN therefore
takes the LARGER of the limits' basis (formula 1: the ideal water in fresh water, formula 1's seawater constants from 5
permil) and the activity-corrected value; the corrected value is shown beside it, and the provenance says which judged."""
from decimal import Decimal as D

from django.test import SimpleTestCase

from ..water import calculation, charts, chemistry, deffeyes, dosing, messages, native, read
from ..water.evaluate import Status
from .test_water import WaterTestCase

LIMITS = deffeyes.Limits(nh3_n_mg_l=0.0103, co2_mg_l=15.0, h2s_ug_l=2.0, alkalinity_low_mg_l=50.0,
                         alkalinity_high_mg_l=150.0)
CONDUCTIVITIES = (500.0, 1000.0, 3000.0)
PHS = (6.8, 7.0, 7.5, 8.0)


def ideal(temp_c, ph, alkalinity, tan=0.5, limits=LIMITS):
    """The analysis on the limits' basis in fresh water: formula 1 at a salinity of 0, every activity 1."""
    return deffeyes.analyse(deffeyes.Water(temp_c, 0.0, ph, alkalinity, tan_mg_l=tan, formula=1), limits)


class FreshWaterTests(SimpleTestCase):
    def test_the_judged_nh3_is_at_least_the_ideal_at_500_1000_and_3000_us_cm_and_12_degrees(self):
        for conductivity in CONDUCTIVITIES:
            for ph in PHS:
                water = deffeyes.Water(12.0, 0.0, ph, 80.0, tan_mg_l=0.5, conductivity_25_us_cm=conductivity)
                found, basis = deffeyes.analyse(water, LIMITS), ideal(12.0, ph, 80.0)
                eq = found.equilibria
                with self.subTest(conductivity=conductivity, ph=ph):
                    self.assertGreaterEqual(eq.nh3_share(ph), native.equilibria(12.0, 0.0).nh3_share(ph))
                    self.assertGreaterEqual(found.nh3_n_mg_l, basis.nh3_n_mg_l)
                    self.assertGreaterEqual(found.nh3_share_pct, basis.nh3_share_pct)
                    self.assertLessEqual(found.safe_tan_mg_l, basis.safe_tan_mg_l)
                    self.assertLessEqual(found.nh3.ph, basis.nh3.ph)                 # toxic above: lower is stricter
                    # The corrected value is lower and only said beside it.
                    self.assertLess(found.nh3_corrected_n_mg_l, found.nh3_n_mg_l)
                    self.assertEqual(found.nh3_corrected_n_mg_l, 0.5 * eq.nh3_share_corrected(ph))
                    self.assertEqual((found.nh3_basis, eq.nh3_basis), ('limits', 'limits'))

    def test_the_judged_co2_is_at_least_the_ideal_at_500_1000_and_3000_us_cm_and_12_degrees(self):
        for conductivity in CONDUCTIVITIES:
            for ph in PHS:
                water = deffeyes.Water(12.0, 0.0, ph, 80.0, tan_mg_l=0.5, conductivity_25_us_cm=conductivity)
                found, basis = deffeyes.analyse(water, LIMITS), ideal(12.0, ph, 80.0)
                with self.subTest(conductivity=conductivity, ph=ph):
                    self.assertGreaterEqual(found.co2_mg_l, basis.co2_mg_l)
                    self.assertLess(found.co2_corrected_mg_l, found.co2_mg_l)
                    self.assertEqual(found.co2_basis, 'limits')
                    if basis.co2.ph is not None:
                        self.assertGreaterEqual(found.co2.ph, basis.co2.ph)          # toxic below: higher is stricter

    def test_a_water_under_the_limit_only_by_its_activities_is_critical(self):
        """TAN chosen so that the corrected NH3-N is below the limit and the ideal above it: critical."""
        eq = native.water_equilibria(12.0, 0.0, 80.0, conductivity_25_us_cm=3000.0)
        between = (eq.nh3_share_corrected(7.5) * native.equilibria(12.0, 0.0).nh3_share(7.5)) ** 0.5
        tan = 0.0103 / between
        found = deffeyes.analyse(deffeyes.Water(12.0, 0.0, 7.5, 80.0, tan_mg_l=tan, conductivity_25_us_cm=3000.0),
                                 LIMITS)
        self.assertLess(found.nh3_corrected_n_mg_l, 0.0103)
        self.assertGreater(found.nh3_n_mg_l, 0.0103)
        self.assertEqual(found.nh3.status, Status.CRITICAL)
        # CO2 likewise: a limit between the corrected and the judged CO2 is passed.
        water = deffeyes.Water(12.0, 0.0, 7.0, 80.0, conductivity_25_us_cm=3000.0)
        first = deffeyes.analyse(water, LIMITS)
        limit = (first.co2_mg_l + first.co2_corrected_mg_l) / 2
        found = deffeyes.analyse(water, deffeyes.Limits(co2_mg_l=limit))
        self.assertEqual(found.co2.status, Status.CRITICAL)

    def test_the_small_chart_the_simulator_and_the_target_judge_alike(self):
        water = deffeyes.Water(12.0, 0.0, 7.2, 80.0, tan_mg_l=0.5, conductivity_25_us_cm=1000.0)
        target = deffeyes.Target(7.6, 120.0)
        found = deffeyes.analyse(water, LIMITS, target)
        eq = found.equilibria
        curve = dict(charts.plots(found)['nh3'].series[0][2])
        nearest = min(curve, key=lambda ph: abs(ph - 7.2))
        self.assertAlmostEqual(curve[nearest], 0.5 * eq.nh3_share(nearest), delta=1e-15)
        (first, _after) = dosing.simulate(eq, (found.dic, found.alkalinity_meq), 7.2, {'nahco3': 50.0}, 1.0)
        self.assertAlmostEqual(first.co2_mg_l, found.co2_mg_l, delta=1e-12)
        step = calculation.judge_step(found, first)
        self.assertAlmostEqual(step.nh3_n_mg_l, found.nh3_n_mg_l, delta=1e-15)
        meq = 120.0 / chemistry.MG_CACO3_PER_MEQ
        self.assertAlmostEqual(found.target_co2_mg_l, eq.co2_judged(meq, 7.6)[0] * chemistry.MG_CO2_PER_MMOL,
                               delta=1e-12)
        self.assertGreater(found.target_co2_mg_l, eq.co2(eq.dic(meq, 7.6), 7.6) * chemistry.MG_CO2_PER_MMOL)

    def test_the_provenance_says_which_judged_and_the_corrected_value(self):
        water = deffeyes.Water(12.0, 0.0, 7.5, 80.0, tan_mg_l=0.5, conductivity_25_us_cm=1000.0)
        found = deffeyes.analyse(water, LIMITS)
        self.assertIn('NH₃ judged on the basis its limits were set on', found.nh3_judged)
        self.assertIn('activity-corrected', found.nh3_judged)
        self.assertIn('CO₂ judged on the basis its limits were set on', found.co2_judged)
        # Formula 1 is the limits' basis itself: nothing more to say.
        one = deffeyes.analyse(deffeyes.Water(12.0, 0.0, 7.5, 80.0, tan_mg_l=0.5, formula=1), LIMITS)
        self.assertEqual((one.nh3_judged, one.co2_judged), ('', ''))
        # Golden v1 holds none of the four (golden_parity ADDED): for formula 1 they follow from what it holds.
        self.assertEqual((one.co2_corrected_mg_l, one.nh3_corrected_n_mg_l), (one.co2_mg_l, one.nh3_n_mg_l))
        self.assertEqual((one.co2_basis, one.nh3_basis), ('limits', 'limits'))
        self.assertEqual(messages.judged('nh3', 'corrected', 0.001, found.equilibria),
                         'NH₃ judged on its activity-corrected value, the larger here.')


class SeaWaterTests(SimpleTestCase):
    def test_in_sea_water_the_limits_basis_is_formula_1s_and_the_larger_judges(self):
        """From 5 permil the limits' basis is formula 1's seawater constants; formula 3's NBS conversion gives more NH3
        in cold sea water (cross review F2) and less at 25 °C, so each temperature takes its larger."""
        for temp_c, basis in ((2.0, 'corrected'), (25.0, 'limits')):
            eq = native.water_equilibria(temp_c, 35.0, 2300.0 * 0.05004345)
            one = native.equilibria(temp_c, 35.0)
            with self.subTest(temp_c=temp_c):
                self.assertEqual(eq.nh3_basis, basis)
                for ph in (7.6, 8.0):
                    self.assertEqual(eq.nh3_share(ph), max(eq.nh3_share_corrected(ph), one.nh3_share(ph)))
                    self.assertGreaterEqual(eq.nh3_share(ph), one.nh3_share(ph))

    def test_formula_1_stays_golden_v1s(self):
        one = native.equilibria(12.0, 35.0)
        self.assertIsNone(one.limits_equilibria())
        self.assertEqual(one.nh3_share(8.0), one.nh3_share_corrected(8.0))
        self.assertEqual(one.nh3_basis, 'limits')


class ReadTests(WaterTestCase):
    def reading(self, code):
        return read.latest([self.mid1])[self.mid1.pk].get(code)

    def test_a_samples_nh3_is_judged_on_the_larger_and_says_the_corrected(self):
        self.stock()
        eq = chemistry.water_equilibria(12.0, 0.0, 80.0, conductivity_25_us_cm=1000.0)
        judged = (D(2) * D(eq.nh3_share(7.5))).quantize(D('0.0001'))
        corrected = (D(2) * D(eq.nh3_share_corrected(7.5))).quantize(D('0.0001'))
        ideal_nh3 = (D(2) * D(native.equilibria(12.0, 0.0).nh3_share(7.5))).quantize(D('0.0001'))
        self.assertGreaterEqual(judged, ideal_nh3)
        self.assertLess(corrected, judged)
        # A critical limit between the two: the reading is critical.
        self.limit('nh3_n_mg_l', critical_high=str((corrected + judged) / 2))
        self.sample(hours=2, tan_mg_l='2', ph='7.5', temperature_c='12', alkalinity_mg_l='80',
                    conductivity_25_us_cm='1000')
        nh3 = self.reading('nh3_n_mg_l')
        self.assertEqual(nh3.value, judged)
        self.assertEqual(nh3.status, Status.CRITICAL)
        self.assertIn('NH₃ judged on the basis its limits were set on', nh3.provenance)
        self.assertIn(f'activity-corrected {corrected}', nh3.provenance.replace(',', '.'))
        self.assertEqual(self.reading('nh4_n_mg_l').value, (D(2) - judged).quantize(D('0.001')))

"""The Water Quality Management Chart (farm/water/deffeyes.py) and the carbonate and sulfide chemistry under
it (farm/water/chemistry.py): the constants against the papers and tables they come from, the derived values
against a published formula and against their own definitions, the whole calculation point by point against
the source's own code (deffeyes_reference/reference.json, made by deffeyes_reference/driver.ts from the
source's engine), the chart's geometry against the formulas, the SVG, and the page in each language."""
import json
import math
import re
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import translation

from core.models import Profile

from ..models import WaterMeasurement
from ..water import chemistry, deffeyes, native
from ..water.deffeyes import Limits, Target, Water, analyse
from ..water.evaluate import Status
from .helpers import role

REFERENCE = json.loads((Path(__file__).parent / 'deffeyes_reference' / 'reference.json').read_text(encoding='utf-8'))
H2S_PER_S = chemistry.H2S_PER_S
# The isolines the source draws: every quarter pH from 4.25 to 12.5 (the core draws them, chemcore/core/src/geometry.rs).
ISOLINE_PHS = [round(4.25 + 0.25 * step, 2) for step in range(34)]


def setUpModule():
    call_command('compile_catalogs', verbosity=0)    # the language tests read the built catalogs


def table(name):
    """The rows of one of the reference's tables, as dicts."""
    header = REFERENCE[name]['header']
    return [dict(zip(header, row)) for row in REFERENCE[name]['rows']]


def plummer_busenberg(temp_c):
    """Plummer & Busenberg (1982), Geochim. Cosmochim. Acta 46: 1011, eqs. 7 and 8: pK1 and pK2 of carbonic
    acid in pure water (thermodynamic, infinite dilution)."""
    t = temp_c + 273.15
    log_k1 = -356.3094 - 0.06091964 * t + 21834.37 / t + 126.8339 * math.log10(t) - 1684915 / t ** 2
    log_k2 = -107.8871 - 0.03252849 * t + 5151.79 / t + 38.92561 * math.log10(t) - 563713.9 / t ** 2
    return -log_k1, -log_k2


# ---- the constants against the published values ---------------------------------------------------------------
class ConstantTests(SimpleTestCase):
    def test_carbonic_acid_in_fresh_water_is_plummer_and_busenbergs(self):
        # The pure-water terms of Millero, Graham, Huang, Bustos-Serrano & Pierrot (2006), Mar. Chem. 100: 80,
        # against Plummer & Busenberg (1982), 0 to 40 °C: both are fits of Harned's measurements; they agree
        # within 0.002 pK.
        for temp_c in range(0, 41, 5):
            pk1, pk2 = plummer_busenberg(temp_c)
            with self.subTest(temp_c=temp_c):
                self.assertAlmostEqual(-math.log10(chemistry.k1_sws(temp_c, 0)), pk1, delta=0.002)
                self.assertAlmostEqual(-math.log10(chemistry.k2_sws(temp_c, 0)), pk2, delta=0.002)
        # Plummer & Busenberg's own values at 25 °C: pK1 6.352, pK2 10.329.
        self.assertAlmostEqual(-math.log10(chemistry.k1_sws(25, 0)), 6.352, delta=0.001)
        self.assertAlmostEqual(-math.log10(chemistry.k2_sws(25, 0)), 10.329, delta=0.001)

    def test_carbonic_acid_in_sea_water_agrees_with_lueker(self):
        # Lueker, Dickson & Keeling (2000), Mar. Chem. 70: 105, the check values of Dickson, Sabine & Christian
        # (2007), Guide to Best Practices for Ocean CO2 Measurements, ch. 5, at S 35 and 25 °C, total scale:
        # pK1 5.8472, pK2 8.9660. Millero et al. (2006) is another fit (seawater scale, converted here): within
        # 0.01.
        to_total = chemistry._free_to_total(25, 35) / chemistry._free_to_sws(25, 35)
        self.assertAlmostEqual(-math.log10(chemistry.k1_sws(25, 35) * to_total), 5.8472, delta=0.01)
        self.assertAlmostEqual(-math.log10(chemistry.k2_sws(25, 35) * to_total), 8.9660, delta=0.01)

    def test_water_and_boric_acid_are_the_handbooks_check_values(self):
        # Dickson, Sabine & Christian (2007), Guide to Best Practices, ch. 5, at S 35 and 25 °C, total scale: ln Kw =
        # −30.434 (eq. 62: Millero's 1995 expression with 0.015 taken from its constant, footnote 5; formula 1's
        # `kw_total`), ln KB = −19.7964 (Dickson 1990). Millero's own, on his seawater scale (formula 3's `kw_sws`), is
        # therefore −30.434 + 0.015.
        self.assertAlmostEqual(math.log(chemistry.kw_total(25, 35)), -30.434, delta=0.001)
        self.assertAlmostEqual(math.log(native.kw_sws(25, 35)), -30.419, delta=0.001)
        self.assertAlmostEqual(math.log(chemistry.kb_total(25, 35)), -19.7964, delta=0.0001)
        # In pure water at 25 °C: pKw 13.995 (the value this test has always held; Harned & Owen 1958 print 13.9965),
        # which Millero's expression gives at S 0 (13.9946) and the Guide's shifted constant misses by 0.006 (14.0012);
        # pKB 9.237 (Manov et al. 1944).
        self.assertAlmostEqual(-math.log10(native.kw_sws(25, 0)), 13.995, delta=0.001)
        self.assertAlmostEqual(-math.log10(chemistry.kw_total(25, 0)), 14.0012, delta=0.0001)
        self.assertAlmostEqual(-math.log10(chemistry.kb_total(25, 0)), 9.237, delta=0.002)

    def test_hydrogen_sulfide_is_milleros(self):
        # Millero (1986), Mar. Chem. 18: 121: pK1 6.98 in pure water at 25 °C; Millero, Plese & Fernandez
        # (1988), Limnol. Oceanogr. 33: 269: 6.51 in sea water (S 35) at 25 °C.
        self.assertAlmostEqual(-math.log10(chemistry.k_h2s_total(25, 0)), 6.98, delta=0.005)
        self.assertAlmostEqual(-math.log10(chemistry.k_h2s_total(25, 35)), 6.51, delta=0.005)
        # It rises as the water cools (Millero 1986: about 0.017 pK per °C): H₂S is a larger share in cold water.
        self.assertGreater(-math.log10(chemistry.k_h2s_total(10, 0)), -math.log10(chemistry.k_h2s_total(25, 0)) + 0.2)

    def test_calcite_and_aragonite_are_muccis(self):
        # Mucci (1983), Am. J. Sci. 283: 780, at S 35 and 25 °C: Ksp* calcite 4.27e−7, aragonite 6.48e−7 (mol/kg)²
        # (the values Zeebe & Wolf-Gladrow 2001 tabulate). At S 0 the equation is the thermodynamic constant of
        # calcite, log K = −8.48 (Plummer & Busenberg 1982).
        self.assertAlmostEqual(chemistry.ksp_calcite(25, 35) / 4.27e-7, 1, delta=0.005)
        self.assertAlmostEqual(chemistry.ksp_aragonite(25, 35) / 6.48e-7, 1, delta=0.005)
        self.assertAlmostEqual(math.log10(chemistry.ksp_calcite(25, 0)), -8.48, delta=0.01)

    def test_in_fresh_water_every_scale_is_one(self):
        eq = chemistry.equilibria(12, 0)
        self.assertEqual(eq.ph_offset, 0)
        self.assertEqual(eq.k1, chemistry.k1_sws(12, 0))
        self.assertEqual(eq.k_h2s, chemistry.k_h2s_total(12, 0))
        self.assertEqual(eq.boron, 0)


# ---- the derived values ------------------------------------------------------------------------------------
class DerivedTests(SimpleTestCase):
    def test_free_co2_follows_standard_methods(self):
        # Standard Methods 4500-CO₂ D (APHA): in fresh water at 25 °C, free CO₂ (mg/L) = 2.0 B 10^(6.0 − pH), with
        # B the bicarbonate alkalinity in mg/L as CaCO₃ (all of it below pH 8.3); the 2.0 is rounded: within 3 %. The
        # equation takes every activity as 1 (no ionic strength): formula 1's convention, the basis CO₂ limits are judged
        # on. Formula 3 gives the water its own ionic strength (here the alkalinity's, I 0.002) and less CO₂ by the
        # activities, said beside the judged one, the larger (cross review F1).
        for ph in (6.5, 7.0, 7.5, 8.0):
            with self.subTest(ph=ph):
                result = analyse(Water(25, 0, ph, 100, formula=1))
                self.assertAlmostEqual(result.co2_mg_l / (2.0 * 100 * 10 ** (6.0 - ph)), 1, delta=0.03)
                self.assertLess(analyse(Water(25, 0, ph, 100)).co2_corrected_mg_l, result.co2_mg_l)
                self.assertEqual(analyse(Water(25, 0, ph, 100)).co2_mg_l, result.co2_mg_l)    # judged on it (F1)

    def test_co2_rises_as_the_ph_falls_at_a_fixed_alkalinity(self):
        for temp_c in (0, 12, 30):
            for salinity in (0, 5, 35):
                for alkalinity in (20, 100, 400):
                    co2 = [analyse(Water(temp_c, salinity, ph / 10, alkalinity)).co2_mg_l for ph in range(90, 59, -2)]
                    dic = [analyse(Water(temp_c, salinity, ph / 10, alkalinity)).dic for ph in range(90, 59, -2)]
                    with self.subTest(temp_c=temp_c, salinity=salinity, alkalinity=alkalinity):
                        self.assertEqual(co2, sorted(co2))
                        self.assertEqual(len(set(co2)), len(co2))
                        self.assertEqual(dic, sorted(dic))

    def test_the_pieces_agree_with_each_other(self):
        for temp_c, salinity in ((0, 0), (12, 1), (25, 35), (40, 50)):
            eq = chemistry.equilibria(temp_c, salinity)
            for ph in (5.0, 6.5, 7.3, 8.1, 9.6):
                with self.subTest(temp_c=temp_c, salinity=salinity, ph=ph):
                    self.assertAlmostEqual(sum(eq.fractions(ph)), 1, places=12)
                    dic = eq.dic(2.0, ph)
                    self.assertAlmostEqual(eq.alkalinity(dic, ph), 2.0, places=12)
                    self.assertAlmostEqual(eq.ph_at(dic, 2.0), ph, places=8)
                    self.assertAlmostEqual(eq.ph_of(eq.hydrogen(ph)), ph, places=12)
                    # The closed forms give back the share they were solved for.
                    self.assertAlmostEqual(eq.ph_where_co2_at_dic(dic, eq.co2(dic, ph)), ph, places=8)
                    self.assertAlmostEqual(eq.ph_where_carbonate(dic, eq.carbonate(dic, ph)), ph, places=6)

    def test_at_each_border_the_value_is_the_limit(self):
        for temp_c, salinity in ((4, 0), (12, 1), (20, 35)):
            eq = chemistry.equilibria(temp_c, salinity)
            with self.subTest(temp_c=temp_c, salinity=salinity):
                ph = eq.ph_where_nh3(2.0, 0.0103)
                self.assertAlmostEqual(2.0 * eq.nh3_share(ph), 0.0103, places=12)
                ph = eq.ph_where_h2s(50.0, 2.0)
                self.assertAlmostEqual(50.0 * eq.h2s_share(ph), 2.0, places=10)
                ph = eq.ph_where_co2(2.0, 15 / chemistry.MG_CO2_PER_MMOL)
                self.assertAlmostEqual(eq.co2(eq.dic(2.0, ph), ph) * chemistry.MG_CO2_PER_MMOL, 15, places=6)
        eq = chemistry.equilibria(12, 0)
        self.assertIsNone(eq.ph_where_nh3(0.01, 0.0103))      # TAN below the limit: never reached
        self.assertIsNone(eq.ph_where_h2s(1.0, 2.0))
        self.assertIsNone(eq.ph_where_co2_at_dic(0.2, 0.3))

    def test_the_status_follows_the_border_and_the_alert_band(self):
        # Past the border critical, within 0.2 pH a warning (the source's uiaStatus and h2sStatus).
        base = analyse(Water(12, 0, 7.0, 80, tan_mg_l=0.5), Limits(nh3_n_mg_l=0.0103))
        border = base.nh3.ph
        for ph, status in ((border - 0.3, Status.OK), (border - 0.1, Status.WARNING), (border + 0.01, Status.CRITICAL)):
            with self.subTest(ph=ph):
                self.assertEqual(analyse(Water(12, 0, ph, 80, tan_mg_l=0.5), Limits(nh3_n_mg_l=0.0103)).nh3.status,
                                 status)
        self.assertEqual(analyse(Water(12, 0, 7, 80)).nh3.status, Status.NOT_MEASURED)
        self.assertEqual(analyse(Water(12, 0, 7, 80, tan_mg_l=0.5)).nh3.status, Status.NO_LIMIT)
        self.assertEqual(analyse(Water(12, 0, 7, 80, tan_mg_l=0.005), Limits(nh3_n_mg_l=0.0103)).nh3.status, Status.OK)
        critical_co2 = analyse(Water(12, 0, 6.8, 80), Limits(co2_mg_l=15))
        self.assertGreater(critical_co2.co2_mg_l, 15)
        self.assertEqual(critical_co2.co2.status, Status.CRITICAL)

    def test_sulfide_goes_in_as_s_and_h2s_comes_out_as_h2s(self):
        result = analyse(Water(20, 0, 7.0, 80, total_sulfide_ug_l=10), Limits(h2s_ug_l=2))
        share = result.equilibria.h2s_share(7.0)
        self.assertAlmostEqual(result.h2s_ug_l, 10 * 34.08088 / 32.065 * share, places=12)
        self.assertAlmostEqual(result.safe_total_sulfide_ug_l * H2S_PER_S * share, 2, places=12)

    def test_oxygen_saturation_from_the_dissolved_oxygen(self):
        result = analyse(Water(10, 0, 7, 80, oxygen_mg_l=11.288))      # air saturation at 10 °C (APHA 4500-O)
        self.assertAlmostEqual(result.oxygen_saturation_pct, 100, delta=0.01)
        self.assertIsNone(analyse(Water(10, 0, 7, 80)).oxygen_saturation_pct)


# ---- against the source's own code, point by point ---------------------------------------------------------
class SourceReferenceTests(SimpleTestCase):
    """The source's calculator, run by its own TypeScript (deffeyes_reference/driver.ts), over 672 waters (0 to
    40 °C, fresh to 50 ‰, pH 6 to 9, alkalinity 20 to 800 mg/L, the limits and sulfide varied) and 17 edges.
    Tolerances: the table keeps 9 significant digits; CO₂ differs by the molar mass (the source's 44.0096
    against IUPAC's 44.0095, 2.3e−6). Where the source was wrong (WQ-30 on) the test says what differs."""

    @staticmethod
    def run_row(row):
        water = Water(row['temperature_c'], row['salinity_ppt'], row['ph'], row['alkalinity_mg_l'], row['tan_mg_l'],
                      row['total_sulfide_ug_l'], formula=1)       # the source's engine is formula 1's convention
        limits = Limits(row['nh3_n_limit'], row['co2_limit'], row['h2s_limit'], row['alkalinity_low'],
                        row['alkalinity_high'])
        return analyse(water, limits, Target(row['target_ph'], row['target_alkalinity_mg_l']))

    def assertClose(self, ours, theirs, relative=0.0, absolute=0.0):
        self.assertIsNotNone(ours)
        self.assertLessEqual(abs(ours - theirs), max(absolute, relative * abs(theirs)), (ours, theirs))

    def test_the_constants_on_the_free_scale(self):
        rows = table('constants')
        self.assertEqual(len(rows), 24)
        for row in rows:
            eq = chemistry.equilibria(row['temperature_c'], row['salinity_ppt'])
            with self.subTest(temperature=row['temperature_c'], salinity=row['salinity_ppt']):
                for name, value in (('pk1_free', eq.k1), ('pk2_free', eq.k2), ('pkw_free', eq.kw), ('pkb_free', eq.kb),
                                    ('pk_nh4_free', eq.k_nh4), ('pk_h2s_free', eq.k_h2s)):
                    self.assertClose(-math.log10(value), row[name], absolute=2e-7)
                self.assertClose(eq.ph_offset, row['ph_offset'], absolute=2e-8)

    def test_every_value_of_every_water(self):
        rows = table('outputs') + table('edges')
        self.assertEqual(len(rows), 689)
        statuses = {0: Status.OK, 1: Status.WARNING, 2: Status.CRITICAL}
        for row in rows:
            result = self.run_row(row)
            with self.subTest(row=row):
                if 'isoline_slope' in row:
                    slope, intercept = result.equilibria.isoline(row['ph'])
                    self.assertClose(slope, row['isoline_slope'], relative=1e-8)
                    self.assertClose(intercept, row['isoline_intercept'], relative=1e-8, absolute=1e-12)
                self.assertClose(result.dic, row['dic'], relative=1e-8)
                self.assertClose(result.co2_mg_l, row['co2'], relative=3e-6)
                self.assertClose(result.co2.ph, row['co2_border'], absolute=3e-6)
                self.assertClose(result.target_dic, row['target_dic'], relative=1e-8)
                self.assertClose(result.target_co2_mg_l, row['target_co2'], relative=3e-6)
                self.assertClose(result.nh3_n_mg_l, row['nh3_n'], relative=1e-8, absolute=1e-15)
                self.assertClose(result.safe_tan_mg_l, row['safe_tan'], relative=1e-8)
                # The NH₃ border: the source bisects between pH 4 and 12 and gives 12 for a border above it.
                if row['nh3_border'] is None:
                    self.assertIsNone(result.nh3.ph)
                elif row['nh3_border'] < 12 - 1e-6:
                    self.assertClose(result.nh3.ph, row['nh3_border'], absolute=1e-6)
                else:
                    self.assertGreaterEqual(result.nh3.ph, 12 - 1e-6)
                self.assertEqual(result.nh3.status, statuses[row['nh3_status']])
                # The H₂S border: the source gives 3 and 13.5 for "below 4" and "above 12.5", shown as pHs (WQ-34).
                if row['h2s_border'] is None:
                    self.assertIsNone(result.h2s.ph)
                elif 4 <= row['h2s_border'] <= 12.5:
                    self.assertClose(result.h2s.ph, row['h2s_border'], absolute=1e-6)
                else:
                    self.assertTrue(result.h2s.ph < 4 or result.h2s.ph > 12.5, result.h2s.ph)
                self.assertEqual(result.h2s.status, statuses[row['h2s_status']])
                self.assertClose(result.h2s_ug_l, row['h2s'], relative=1e-8, absolute=1e-12)
                self.assertClose(result.safe_total_sulfide_ug_l, row['safe_total_sulfide_h2s_basis'] / H2S_PER_S,
                                 relative=1e-8)
                if 'nh3_share_at_border_pct' in row and row['nh3_border'] is not None:
                    self.assertClose(result.nh3_share_at_border_pct, row['nh3_share_at_border_pct'], relative=1e-8)

    def test_the_chart_draws_what_the_source_draws(self):
        for case in REFERENCE['geometry']:
            water = Water(case['temperature_c'], case['salinity_ppt'], case['ph'], case['alkalinity_mg_l'],
                          case['tan_mg_l'], case['total_sulfide_ug_l'], case['calcium_mg_l'], formula=1)
            limits = Limits(case['nh3_n_limit'], case['co2_limit'], case['h2s_limit'], case['alkalinity_low'],
                            case['alkalinity_high'])
            result = analyse(water, limits, Target(case['target_ph'], case['target_alkalinity_mg_l']))
            eq = result.equilibria
            with self.subTest(temperature=case['temperature_c'], salinity=case['salinity_ppt'], ph=case['ph']):
                # The isolines (the source rounds its points to 4 decimals): their ends at DIC 0 and 8.
                self.assertEqual([isoline[0] for isoline in case['isolines']], ISOLINE_PHS)
                for ph, at_zero, end, at_end in case['isolines']:
                    slope, intercept = eq.isoline(ph)
                    self.assertClose(intercept, at_zero, absolute=1e-4)
                    self.assertClose(slope * end + intercept, at_end, absolute=1e-4)
                self.assertClose(result.dic, case['current'][0], relative=1e-8)
                self.assertClose(result.alkalinity_meq, case['current'][1], relative=1e-8)
                self.assertClose(result.target_dic, case['target'][0], relative=1e-8)
                # The CO₂ boundary: at each of the source's DICs our curve has the source's alkalinity.
                co2 = case['co2_limit'] / chemistry.MG_CO2_PER_MMOL
                for dic, alkalinity in case['co2_zone']:
                    self.assertClose(eq.alkalinity(dic, eq.ph_where_co2_at_dic(dic, co2)), alkalinity, absolute=2e-4)
                # The NH₃ and H₂S boundaries are the isolines of their borders.
                for key, border in (('nh3_zone', result.nh3.ph), ('h2s_zone', result.h2s.ph)):
                    self.assertEqual(case[key] is None, border is None, key)
                    for dic, alkalinity in case[key] or []:
                        if key == 'h2s_zone' and border > 12:
                            break                      # the source draws a border above pH 12 at 12
                        slope, intercept = eq.isoline(border)
                        self.assertClose(slope * dic + intercept, alkalinity, absolute=1e-4)
                self.assert_safe_zone(case, result)
                self.assert_omega(case, eq)

    def assert_safe_zone(self, case, result):
        """Where the H₂S limit does not narrow it, the safe zone has the source's four corners; where it does,
        the source ignored it (WQ-30) and ours follows the H₂S isoline, or is empty when no pH is safe."""
        eq = result.equilibria
        zone = deffeyes.safe_zone(result, deffeyes.Box(1e4, 1e4, 1, 1))
        low, high = (value / chemistry.MG_CACO3_PER_MEQ for value in (case['alkalinity_low'], case['alkalinity_high']))
        co2 = case['co2_limit'] / chemistry.MG_CO2_PER_MMOL
        narrowed = result.h2s.ph is not None and result.h2s.ph > eq.ph_where_co2(low, co2)
        crossed = result.nh3.ph is not None and eq.ph_where_co2(high, co2) > result.nh3.ph
        # The corners differ from the source's by its bisection and its CO₂ molar mass: within 5e−6 mmol/L.
        near = 5e-6
        if not narrowed and not crossed:
            self.assertIsNotNone(case['safe_zone'])
            for corner in case['safe_zone']:
                self.assertLess(min(math.dist(corner, vertex) for vertex in zone), near, corner)
        elif not narrowed:
            # The CO₂ border passes the NH₃ border inside the band: the source's quadrilateral crosses itself
            # (WQ-30); ours keeps its bottom corners and closes where the two borders meet.
            top_left, top_right, bottom_right, bottom_left = case['safe_zone']
            self.assertGreater(top_left[0], top_right[0])
            for corner in (bottom_right, bottom_left):
                self.assertLess(min(math.dist(corner, vertex) for vertex in zone), near, corner)
            apex = max(zone, key=lambda vertex: vertex[1])
            self.assertLess(apex[1], high)
            self.assertAlmostEqual(eq.ph_at(*apex), result.nh3.ph, places=6)
            self.assertAlmostEqual(eq.co2(apex[0], result.nh3.ph) / co2, 1, places=6)
        elif result.h2s.ph >= result.nh3.ph:
            self.assertEqual(zone, [])
        else:
            on_h2s = [vertex for vertex in zone if abs(eq.ph_at(*vertex) - result.h2s.ph) < 1e-6]
            self.assertGreaterEqual(len(on_h2s), 2)

    def assert_omega(self, case, eq):
        """Ω = 1, drawn by the source down to 0 ‰ and by ours from 5 ‰ (WQ-32): at each of the source's DICs
        the source's alkalinity, within its rounding of the DIC (to 4 decimals) times the line's slope."""
        for key, ksp in (('calcite', eq.ksp_calcite), ('aragonite', eq.ksp_aragonite)):
            carbonate = ksp / (case['calcium_mg_l'] / chemistry.MG_CALCIUM_PER_MOL) * 1000
            for dic, alkalinity in case[key] or []:
                ph = eq.ph_where_carbonate(dic, carbonate)
                if not deffeyes.PH_RANGE[0] <= ph <= deffeyes.PH_RANGE[1]:
                    continue                           # the source's bisection stops at the ends of its range
                ours = eq.alkalinity(dic, ph)
                nearby = eq.alkalinity(dic + 1e-5, eq.ph_where_carbonate(dic + 1e-5, carbonate))
                slope = abs(nearby - ours) / 1e-5
                self.assertClose(ours, alkalinity, absolute=1e-4 + 5e-5 * slope)


# ---- the chart's geometry and its SVG -----------------------------------------------------------------------
def default_analysis(**water):
    values = {'temperature_c': 12, 'salinity_ppt': 1, 'ph': 7.0, 'alkalinity_mg_l': 80, 'tan_mg_l': 0.5,
              'total_sulfide_ug_l': 2, **water}
    return analyse(Water(**values), Limits(0.0103, 15, 2, 50, 100), Target(7.5, 100))


def unpixel(chart, x, y):
    """A point of the SVG back in DIC and alkalinity."""
    plot = chart.plot
    return ((float(x) - plot['left']) / plot['size'] * chart.box.dic,
            (plot['bottom'] - float(y)) / plot['size'] * chart.box.alkalinity)


def inside(polygon, point):
    """Whether a point is inside a polygon (ray casting)."""
    x, y = point
    found = False
    for (x1, y1), (x2, y2) in zip(polygon, polygon[1:] + polygon[:1]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            found = not found
    return found


def pairs(points):
    return [tuple(map(float, pair.split(','))) for pair in points.split()]


class GeometryTests(SimpleTestCase):
    PIXEL = 1e-4           # the SVG rounds to 0.01 px: 0.005 px is 5.8e-5 on a 6-unit axis of 520 px

    def test_the_isolines_are_the_formulas_lines(self):
        result = default_analysis()
        chart = deffeyes.draw(result)
        drawn = {isoline['ph']: isoline for isoline in chart.isolines}
        self.assertIn('7.00', drawn)
        self.assertEqual(drawn['7.00']['label']['text'], 'pH 7.0')
        self.assertIsNone(drawn['7.25']['label'])
        for ph_text, isoline in drawn.items():
            slope, intercept = result.equilibria.isoline(float(ph_text))
            for x, y in pairs(isoline['points']):
                dic, alkalinity = unpixel(chart, x, y)
                with self.subTest(ph=ph_text):
                    self.assertAlmostEqual(alkalinity, slope * dic + intercept, delta=self.PIXEL * (1 + slope))
                    self.assertTrue(chart.box.inside((dic, alkalinity), slack=1e-6))

    def test_the_point_and_the_target_are_where_the_values_put_them(self):
        for water in ({}, {'alkalinity_mg_l': 800, 'ph': 8.0}, {'salinity_ppt': 35, 'alkalinity_mg_l': 115, 'ph': 8.1},
                      {'ph': 6.0, 'alkalinity_mg_l': 300}):
            result = default_analysis(**water)
            chart = deffeyes.draw(result)
            with self.subTest(**water):
                dic, alkalinity = unpixel(chart, chart.point['x'], chart.point['y'])
                self.assertAlmostEqual(dic, result.dic, delta=self.PIXEL * chart.box.dic / 6)
                self.assertAlmostEqual(alkalinity, result.alkalinity_meq, delta=self.PIXEL * chart.box.alkalinity / 6)
                self.assertTrue(0 < dic < chart.box.dic and 0 < alkalinity < chart.box.alkalinity)
                dic, alkalinity = unpixel(chart, chart.target['x'], chart.target['y'])
                self.assertAlmostEqual(dic, result.target_dic, delta=self.PIXEL * chart.box.dic / 6)
                self.assertAlmostEqual(alkalinity, result.target_alkalinity_meq,
                                       delta=self.PIXEL * chart.box.alkalinity / 6)

    def test_the_axes_grow_to_hold_the_water_and_stay_at_six_otherwise(self):
        self.assertEqual(deffeyes.draw(default_analysis()).box, deffeyes.Box(6.0, 6.0, 1.0, 1.0))
        box = deffeyes.draw(default_analysis(alkalinity_mg_l=800, ph=8.0)).box
        self.assertEqual((box.alkalinity, box.alkalinity_step), (18, 2.0))       # 16 meq/L with 10 % to spare
        self.assertGreaterEqual(box.dic, default_analysis(alkalinity_mg_l=800, ph=8.0).dic * 1.1)

    def test_each_region_is_where_its_limit_is_passed(self):
        result = default_analysis()
        eq, shape = result.equilibria, deffeyes.geometry(result)
        box = shape.box
        for key, polygon in shape.regions.items():
            for vertex in polygon:
                self.assertTrue(box.inside(vertex), (key, vertex))
        # NH₃ above its isoline, H₂S below its isoline, CO₂ below its curve: at each vertex the pH is past the
        # border, or the vertex is on it.
        for dic, alkalinity in shape.regions['nh3']:
            if dic > 1e-9:
                self.assertGreaterEqual(eq.ph_at(dic, alkalinity), result.nh3.ph - 1e-9)
        for dic, alkalinity in shape.regions['h2s']:
            if dic > 1e-9 and alkalinity > 1e-9:
                self.assertLessEqual(eq.ph_at(dic, alkalinity), result.h2s.ph + 1e-9)
        # The CO₂ curve is drawn in the water's own constants at the limit over the bicarbonate-range ratio of the limits'
        # basis to its own CO₂, K1 10^offset over the basis's (Equilibria::co2_chart_ratio, cross review F1): a ratio of the
        # equilibria alone, so a replay page still shares one diagram among frames equal but for pH and alkalinity
        # (sensors.tests.test_page_share); the judged CO₂ on the curve within 1.5 % of the limit.
        basis = eq.limits_equilibria()
        ratio = eq.k1 * 10 ** eq.ph_offset / (basis.k1 * 10 ** basis.ph_offset)
        co2 = 15 / ratio / chemistry.MG_CO2_PER_MMOL
        self.assertLess(co2, 15 / chemistry.MG_CO2_PER_MMOL)
        for dic, alkalinity in shape.regions['co2']:
            ph = eq.ph_at(dic, alkalinity)
            if ph is not None:
                self.assertGreaterEqual(eq.co2(dic, ph), co2 * (1 - 1e-9))
        # The boundaries lie on the lines: the CO₂ curve's points hold the limit, the isolines' the border pH.
        for dic, alkalinity in shape.boundaries['co2'][0]:
            ph = eq.ph_at(dic, alkalinity)
            if alkalinity > 1e-9:
                self.assertAlmostEqual(eq.co2(dic, ph) / co2, 1, places=8)
                judged = eq.co2_judged(alkalinity, ph)[0] * chemistry.MG_CO2_PER_MMOL
                self.assertAlmostEqual(judged / 15, 1, delta=0.015)
        for key in ('nh3', 'h2s'):
            border = getattr(result, key).ph
            for dic, alkalinity in shape.boundaries[key][0]:
                slope, intercept = eq.isoline(border)
                self.assertAlmostEqual(alkalinity, slope * dic + intercept, places=9)

    def test_inside_the_safe_zone_every_limit_is_kept(self):
        result = default_analysis()
        eq, zone = result.equilibria, deffeyes.geometry(result).regions['safe']
        self.assertGreater(len(zone), 4)
        for dic, alkalinity in zone:
            ph = eq.ph_at(dic, alkalinity)
            self.assertLessEqual(ph, result.nh3.ph + 1e-6)
            floor = max(result.h2s.ph, eq.ph_where_co2(alkalinity, 15 / chemistry.MG_CO2_PER_MMOL))
            self.assertGreaterEqual(ph, floor - 1e-6)
            self.assertTrue(50 / 50.04345 - 1e-9 <= alkalinity <= 100 / 50.04345 + 1e-9)
        # A water in the middle of the zone is ok on every limit.
        dic = sum(vertex[0] for vertex in zone) / len(zone)
        alkalinity = sum(vertex[1] for vertex in zone) / len(zone)
        inside = default_analysis(ph=eq.ph_at(dic, alkalinity), alkalinity_mg_l=alkalinity * 50.04345)
        self.assertEqual((inside.nh3.status, inside.co2.status, inside.h2s.status), (Status.OK,) * 3)

    def test_the_safe_zone_follows_the_h2s_limit_and_has_one_when_tan_cannot_reach_its_limit(self):
        # The source ignored H₂S and drew no safe zone when the TAN was under the limit (WQ-30).
        low_tan = deffeyes.geometry(default_analysis(tan_mg_l=0.005))
        self.assertTrue(low_tan.regions['safe'])
        self.assertNotIn('nh3', low_tan.regions)
        sulfidic = default_analysis(total_sulfide_ug_l=4.5)              # its H₂S border between CO₂'s and NH₃'s
        self.assertLess(sulfidic.co2.ph, sulfidic.h2s.ph)
        self.assertLess(sulfidic.h2s.ph, sulfidic.nh3.ph)
        zone = deffeyes.geometry(sulfidic).regions['safe']
        phs = [sulfidic.equilibria.ph_at(dic, alkalinity) for dic, alkalinity in zone]
        self.assertGreaterEqual(min(phs), sulfidic.h2s.ph - 1e-6)
        self.assertGreaterEqual(sum(1 for ph in phs if abs(ph - sulfidic.h2s.ph) < 1e-6), 2)
        no_safe_ph = default_analysis(total_sulfide_ug_l=5000)            # its H₂S border above the NH₃ border
        self.assertGreater(no_safe_ph.h2s.ph, no_safe_ph.nh3.ph)
        shape = deffeyes.geometry(no_safe_ph)
        self.assertNotIn('safe', shape.regions)
        self.assertIn('Safe zone: no pH in the alkalinity band is inside every limit.',
                      [str(note) for note in shape.notes])

    def test_omega_only_in_muccis_range_and_with_calcium(self):
        sea = analyse(Water(25, 35, 8.1, 115, calcium_mg_l=412), Limits())
        shape = deffeyes.geometry(sea)
        self.assertTrue(shape.omega['calcite'] and shape.omega['aragonite'])
        # On the line the carbonate (mmol/L) times the calcium (mol/L) is the Ksp per litre: Mucci's per-kg² Ksp times
        # the square of the sea water's density (the correction of 2026-11-10; the per-kg Ksp alone put the line where Ω
        # is 1 / ρ², 0.955 at S 35 and 25 °C).
        density = native.seawater_density(25.0, 35.0)
        self.assertAlmostEqual(density, 1.023343, delta=1e-6)
        carbonate = sea.equilibria.ksp_calcite * density ** 2 / (412 / chemistry.MG_CALCIUM_PER_MOL) * 1000
        for line in shape.omega['calcite']:
            for dic, alkalinity in line[1:-1]:
                ph = sea.equilibria.ph_at(dic, alkalinity)
                self.assertAlmostEqual(sea.equilibria.carbonate(dic, ph) / carbonate, 1, places=6)
        self.assertEqual(deffeyes.geometry(analyse(Water(25, 1, 8.1, 115, calcium_mg_l=412))).omega, {})
        self.assertEqual(deffeyes.geometry(analyse(Water(25, 35, 8.1, 115))).omega, {})

    def test_no_safe_zone_without_a_value_or_a_limit_it_needs(self):
        # A missing value is never taken for a safe one: no zone, and a note that names what is missing.
        water = {'temperature_c': 12, 'salinity_ppt': 1, 'ph': 7.0, 'alkalinity_mg_l': 80, 'tan_mg_l': 0.5,
                 'total_sulfide_ug_l': 2}
        limits = {'nh3_n_mg_l': 0.0103, 'co2_mg_l': 15, 'h2s_ug_l': 2, 'alkalinity_low_mg_l': 50,
                  'alkalinity_high_mg_l': 100}
        self.assertTrue(deffeyes.geometry(analyse(Water(**water), Limits(**limits))).regions['safe'])
        for missing_water, missing_limits, note in (
            ({'tan_mg_l': None}, {}, 'Safe zone: not drawn without the TAN.'),
            ({}, {'nh3_n_mg_l': None}, 'Safe zone: not drawn without the NH₃ limit.'),
            ({}, {'co2_mg_l': None}, 'Safe zone: not drawn without the CO₂ limit.'),
            ({}, {'h2s_ug_l': None}, 'Safe zone: not drawn without the H₂S limit, a total sulfide being given.'),
            ({}, {'alkalinity_low_mg_l': None, 'alkalinity_high_mg_l': None},
             'Safe zone: not drawn without the alkalinity band.'),
            ({}, {'alkalinity_low_mg_l': 80, 'alkalinity_high_mg_l': 80},
             'Safe zone: not drawn, the alkalinity band is empty (its high end is not above its low end).'),
        ):
            result = analyse(Water(**{**water, **missing_water}), Limits(**{**limits, **missing_limits}))
            shape = deffeyes.geometry(result)
            with self.subTest(note=note):
                self.assertNotIn('safe', shape.regions)
                self.assertEqual(deffeyes.safe_zone(result, shape.box), [])
                self.assertIn(note, [str(text) for text in shape.notes])
        # The reviewer's case: no TAN; the source draws no zone either.
        result = analyse(Water(12, 1, 7.0, 80, None, 2), Limits(0.0103, 15, 2, 50, 100))
        self.assertNotIn('safe', deffeyes.geometry(result).regions)

    def test_without_a_total_sulfide_the_zone_is_drawn_and_says_h2s_is_not_assessed(self):
        limits = Limits(0.0103, 15, 2, 50, 100)
        unassessed = analyse(Water(12, 1, 7.0, 80, 0.5, None), limits)
        shape = deffeyes.geometry(unassessed)
        self.assertIn('Safe zone: H₂S not assessed, no total sulfide given.', [str(text) for text in shape.notes])
        chart = deffeyes.draw(unassessed)
        self.assertIn({'key': 'safe', 'name': 'Safe zone (H₂S not assessed)'}, chart.legend)
        # Its zone is the one of a sulfide too little to reach the limit at any pH: H₂S does not narrow it.
        harmless = analyse(Water(12, 1, 7.0, 80, 0.5, 1), limits)
        self.assertIsNone(harmless.h2s.ph)
        self.assertEqual(shape.regions['safe'], deffeyes.geometry(harmless).regions['safe'])
        self.assertIn({'key': 'safe', 'name': 'Safe zone'}, deffeyes.draw(harmless).legend)

    def test_a_border_off_the_charts_ph_range_is_said_in_words(self):
        def table(border):
            return render_to_string('farm/_deffeyes_border.html', {'border': border})

        # TAN just above its limit: NH₃ passes it only above pH 12.5. Not a number, no region, a note; ok.
        result = default_analysis(tan_mg_l=0.01031)
        border = result.nh3
        self.assertGreater(border.ph, deffeyes.PH_RANGE[1])
        self.assertTrue(border.off_chart)
        self.assertEqual(border.status, Status.OK)
        shape = deffeyes.geometry(result)
        self.assertNotIn('nh3', shape.regions)
        self.assertIn('NH₃: the limit is not reached anywhere on this chart.', [str(text) for text in shape.notes])
        html = table(border)
        self.assertIn('not reached in the chart', html)
        self.assertNotIn(f'{border.ph:.3f}', html)
        self.assertNotIn('+', html)
        # Total sulfide just above the limit: H₂S passes it only below pH 4.
        result = default_analysis(total_sulfide_ug_l=2 / H2S_PER_S / 0.9999)
        self.assertLess(result.h2s.ph, deffeyes.PH_RANGE[0])
        self.assertTrue(result.h2s.off_chart)
        self.assertNotIn('h2s', deffeyes.geometry(result).regions)
        self.assertIn('not reached in the chart', table(result.h2s))
        # Much sulfide against a small limit: H₂S passes it at every pH of the chart. Shaded, said, critical.
        result = analyse(Water(12, 1, 7.0, 80, 0.5, 10000), Limits(0.0103, 15, 0.01, 50, 100))
        self.assertGreater(result.h2s.ph, deffeyes.PH_RANGE[1])
        self.assertTrue(result.h2s.everywhere)
        self.assertEqual(result.h2s.status, Status.CRITICAL)
        chart = deffeyes.draw(result)
        self.assertIn({'key': 'h2s', 'name': 'H₂S toxic (at every pH of the chart)'}, chart.legend)
        html = table(result.h2s)
        self.assertIn('passed at every pH of the chart', html)
        self.assertNotIn(f'{result.h2s.ph:.3f}', html)
        # Much TAN against a small limit: NH₃ passes it at every pH of the chart.
        result = default_analysis(tan_mg_l=100, ph=7.0)
        result = analyse(result.water, Limits(0.0001, 15, 2, 50, 100))
        self.assertLess(result.nh3.ph, deffeyes.PH_RANGE[0])
        self.assertTrue(result.nh3.everywhere)
        self.assertIn({'key': 'nh3', 'name': 'NH₃ toxic (at every pH of the chart)'}, deffeyes.draw(result).legend)
        # Inside the range the border is a number with its margin.
        html = table(default_analysis().nh3)
        # Judged on the larger NH₃, here the ideal share its limit was set on (cross review F1): 7.986; formula 3's
        # activity-corrected share alone would put it at 8.045, formula 1 at 8.040.
        self.assertIn('7.986', html)
        self.assertIn('+0.99', html)

    def assert_shaded_where_passed(self, result, key, toxic):
        """Points sampled over the box: a point whose pH passes the border (`toxic(ph)`) is in the region,
        any other point is not, except within a hair of the border; returns how many were toxic."""
        shape = deffeyes.geometry(result)
        region, box, eq = shape.regions.get(key, []), shape.box, result.equilibria
        passed, wrong = 0, []
        for i in range(1, 80):
            for j in range(1, 80):
                dic, alkalinity = box.dic * i / 80, box.alkalinity * j / 80
                ph = eq.ph_at(dic, alkalinity)
                if ph is None or abs(ph - getattr(result, key).ph) < 1e-6:
                    continue
                passed += toxic(ph)
                if inside(region, (dic, alkalinity)) != toxic(ph):
                    wrong.append((dic, alkalinity, ph))
        self.assertEqual(wrong, [])
        return passed

    def test_a_border_off_the_charts_range_is_shaded_where_it_meets_a_large_box(self):
        # The reviewer's case, which the form accepts: in a 35 × 22 box the top-left corner reaches pH 13.3,
        # past an NH₃ border of 13.08; the table says it in words, the chart shades the sliver.
        # (formula 1, as the reviewer drew it: formula 3's ionic strength moves the border to 13.14 and the box to 30)
        result = analyse(Water(0, 0, 7.0, 1000, 0.100, 2, formula=1), Limits(0.0999, 15, 2, 50, 1000))
        self.assertTrue(result.nh3.off_chart)
        self.assertAlmostEqual(result.nh3.ph, 13.084, places=3)
        self.assertEqual((deffeyes.box_of(result).dic, deffeyes.box_of(result).alkalinity), (35, 22))
        self.assertGreater(self.assert_shaded_where_passed(result, 'nh3', lambda ph: ph > result.nh3.ph), 0)
        self.assertNotIn('NH₃: the limit is not reached anywhere on this chart.',
                         [str(text) for text in deffeyes.geometry(result).notes])
        # H₂S below pH 4 in a box wide in DIC: a low pH with much alkalinity, a total sulfide just above the limit.
        result = analyse(Water(12, 0, 5.0, 1000, 0.5, 2 / H2S_PER_S / 0.9995), Limits(0.0103, 15, 2, 50, 1000))
        self.assertTrue(result.h2s.off_chart)
        self.assertLess(result.h2s.ph, deffeyes.PH_RANGE[0])
        self.assertGreater(self.assert_shaded_where_passed(result, 'h2s', lambda ph: ph < result.h2s.ph), 0)
        # A small box that the border misses: nothing to shade, and the note says so.
        result = default_analysis(tan_mg_l=0.01031)
        self.assertEqual(self.assert_shaded_where_passed(result, 'nh3', lambda ph: ph > result.nh3.ph), 0)
        self.assertIn('NH₃: the limit is not reached anywhere on this chart.',
                      [str(text) for text in deffeyes.geometry(result).notes])

    def test_the_isolines_take_the_sources_colours(self):
        # phIsolineColor (deffeyes-data.ts): sequentialColor(floor((pH − 5.5) / 0.5)) of shared-contracts'
        # domainScale.sequential, clamped to its ten steps.
        for ph, colour in ((4.25, '#DC2626'), (5.75, '#DC2626'), (6.0, '#EF4444'), (6.5, '#F97316'),
                           (7.0, '#EAB308'), (7.5, '#22C55E'), (8.0, '#06B6D4'), (8.5, '#3B82F6'),
                           (9.0, '#6366F1'), (9.75, '#A855F7'), (10.0, '#7C3AED'), (12.5, '#7C3AED')):
            with self.subTest(ph=ph):
                self.assertEqual(deffeyes.isoline_colour(ph), colour)

    def test_a_layer_left_out_is_not_drawn(self):
        chart = deffeyes.draw(default_analysis(), layers={'nh3'})
        self.assertEqual([region['key'] for region in chart.regions], ['nh3'])
        self.assertEqual(chart.isolines, [])
        self.assertIsNone(chart.target)
        self.assertTrue(chart.point['star'])

    def test_the_svg_has_every_part_with_plain_coordinates_in_every_language(self):
        result = default_analysis()
        for language in ('en', 'tr', 'nb'):
            with translation.override(language):
                html = render_to_string('farm/_deffeyes_chart.html', {'chart': deffeyes.draw(result)})
            with self.subTest(language=language):
                # A dot decimal everywhere; in a list of points a comma only between x and y.
                for value in re.findall(r' points="([^"]*)"', html):
                    self.assertRegex(value, r'^-?[\d.]+,-?[\d.]+( -?[\d.]+,-?[\d.]+)*$')
                for value in re.findall(r' (?:x|y|x1|y1|x2|y2|data-x|data-y|transform|viewBox)="([^"]*)"', html):
                    self.assertNotIn(',', value)
                for key in ('nh3', 'co2', 'h2s', 'safe'):
                    self.assertIn(f'deffeyes-zone-{key}', html)
                self.assertIn('class="deffeyes-point"', html)
                # Every isoline that crosses the chart; the others pass wholly above it (at 12 °C pH 12.25 and
                # 12.5, their hydroxide alone more than 6 meq/L) or below it (pH 4.25).
                drawn = {float(ph) for ph in re.findall(r'class="deffeyes-isoline[^"]*" data-ph="([\d.]+)"', html)}
                hidden = set(ISOLINE_PHS) - drawn
                self.assertEqual(len(drawn) + len(hidden), 34)
                self.assertEqual(hidden, {4.25, 12.25, 12.5})
                for ph in hidden:
                    slope, intercept = result.equilibria.isoline(ph)
                    self.assertTrue(intercept > 6 or slope * 6 + intercept < 0, ph)
        self.assertIn('pH 7,0', html)                                # the labels in the language
        self.assertIn('pH &gt; 7,99', html)


# ---- the page --------------------------------------------------------------------------------------------
class CalculatorPageTests(TestCase):
    url = reverse('farm:water_calculator')

    def setUp(self):
        self.user = get_user_model().objects.create_user('ali', 'ali@example.com', 'eski-sifre-123')
        self.user.groups.add(role('Water reader', 'view_watermeasurement'))
        self.client.force_login(self.user)

    def test_it_opens_with_the_defaults_drawn(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        for text in ('Water Quality Management Chart', '<svg class="deffeyes-chart"', 'Carbon dioxide (CO₂)',
                     'NH₃ toxic (pH &gt; 7.99)', 'CO₂ toxic (&gt; 15 mg/L)', 'H₂S toxic (pH &lt; 5.93)',
                     '1.987 mmol/L', '19.62 mg/L', '17.12 mg/L', 'wq-critical', 'data-formula="4"'):
            # formula 4 (fresh water judged as formula 3 judged it); NH₃ and CO₂ judged on the larger, the limits' basis (cross review F1): CO₂ 19.62 mg/L, the
            # activity-corrected 17.12 said beside it
            self.assertIn(text, html)
        self.assertContains(response, f'href="{self.url}" aria-current="page"')
        self.assertContains(response, f'href="{reverse("farm:water")}" title="Water chemistry" aria-current="page"')
        self.assertContains(response, 'value="0.0103"')

    def test_the_values_in_the_address_draw_their_water(self):
        response = self.client.get(self.url, {'temperature_c': '25', 'ph': '8.1', 'salinity_ppt': '35',
                                              'alkalinity_mg_l': '115', 'calcium_mg_l': '412', 'drawn': '1',
                                              'layers': ['omega', 'isolines']})
        analysis = response.context['analysis']
        self.assertAlmostEqual(analysis.alkalinity_meq, 115 / 50.04345)
        self.assertContains(response, 'deffeyes-omega-calcite')
        self.assertNotContains(response, 'deffeyes-zone-')
        self.assertContains(response, 'CO₂: no limit given.', count=0)        # its layer is not asked for

    def test_a_wrong_value_is_refused_on_its_field_and_nothing_is_drawn(self):
        response = self.client.get(self.url, {'temperature_c': '12', 'ph': '11.8', 'salinity_ppt': '0',
                                              'alkalinity_mg_l': '20', 'target_ph': '7', 'drawn': '1'})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context['chart'])
        errors = response.context['form'].errors
        self.assertIn('the hydroxide and borate alone', errors['alkalinity_mg_l'][0])
        self.assertEqual(errors['target_alkalinity_mg_l'], ['Give both or neither.'])
        response = self.client.get(self.url, {'temperature_c': '12', 'ph': '7', 'salinity_ppt': '0',
                                              'alkalinity_mg_l': '80', 'alkalinity_low_mg_l': '80',
                                              'alkalinity_high_mg_l': '80', 'drawn': '1'})
        self.assertEqual(response.context['form'].errors['alkalinity_high_mg_l'],
                         ['The band goes up: its high end is above its low end.'])
        response = self.client.get(self.url, {'temperature_c': '12', 'ph': '25', 'salinity_ppt': '0',
                                              'alkalinity_mg_l': '', 'drawn': '1'})
        self.assertEqual(set(response.context['form'].errors), {'ph', 'alkalinity_mg_l'})
        self.assertNotContains(response, '<svg class="deffeyes-chart"')

    def test_reading_the_water_is_enough_and_nothing_is_stored(self):
        self.client.get(self.url, {'temperature_c': '12', 'ph': '7', 'salinity_ppt': '0', 'alkalinity_mg_l': '80'})
        self.assertFalse(WaterMeasurement.all_objects.exists())
        stranger = get_user_model().objects.create_user('veli', 'veli@example.com')
        stranger.groups.add(role('Tanks', 'view_tank'))
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_the_water_page_has_the_calculator_tab(self):
        response = self.client.get(reverse('farm:water'))
        self.assertContains(response, f'<a class="ui-tab" href="{self.url}">Calculator</a>', html=True)

    def test_it_speaks_each_language(self):
        for language, words in {
            'tr': ('Su Kalitesi Yönetim Çizelgesi', 'Hesaplayıcı', '1,987 mmol/L', 'pH 7,0'),
            'nb': ('Diagram for styring av vannkvalitet', 'Kalkulator', '1,987 mmol/L', 'pH 7,0'),
        }.items():
            Profile.objects.update_or_create(user=self.user, defaults={'language': language})
            response = self.client.get(self.url)
            for word in words:
                self.assertContains(response, word, msg_prefix=language)
            self.assertContains(response, 'value="0,0103"', msg_prefix=language)

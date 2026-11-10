"""Formula 3 (golden v3), the application's since the switch (owner, 2026-11-09): I1 and I2 (chemcore/findings/B1.md;
chemcore/findings/I2-comparison.md), beside formula 1 (golden v1).

Up to a salinity of 1 the water takes its ionic strength from what is measured: an estimate, the conductivity at 25 °C
(I = 1.6e-5 κ, κ in µS/cm, Russell 1976) else the salinity (DOE 1994, as sea water), never below the measured ions'
lower bound, the hardness with the alkalinity else the alkalinity alone (as sodium bicarbonate); nothing measured, 0.
The constants there are the fresh-water (thermodynamic) ones, each made a concentration constant with Davies activity
coefficients (Davies 1962, log γ = −A z² (√I / (1 + √I) − 0.3 I), A of the temperature): the NBS pH becomes the free
[H⁺] through γH, and K1, K2, Kw, KB, KH2S follow the ions they hold. From 5 the seawater constants of v1 (the NBS
conversion with the temperature's A); between 1 and 5 each constant blended."""
import gzip
import hashlib
import importlib.util
import json
import math
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from ..water import chemistry, native

ROOT = Path(settings.BASE_DIR)
V3 = ROOT / 'chemcore' / 'golden' / 'v3'
CACO3 = 100.0869                     # mg per mmol (IUPAC 2007), as the core's hardness reads it
FIELDS = ('ph_offset', 'k1', 'k2', 'kw', 'kb', 'boron', 'k_nh4', 'k_h2s', 'ksp_calcite', 'ksp_aragonite')


# The Debye–Hückel A (log10, molal) as tabulated by Hamer (1968), NSRDS-NBS 24, table 3 (Malmberg & Maryott's ε and
# the density of water): {°C: A}.
A_TABLE = {0.0: 0.4918, 5.0: 0.4953, 10.0: 0.4989, 15.0: 0.5027, 20.0: 0.5067, 25.0: 0.5108, 30.0: 0.5151}


def tabulated_a(temp_c):
    """The table's A at a temperature, linearly between its rows (0 to 25 °C)."""
    rows = sorted(A_TABLE.items())
    for (t0, a0), (t1, a1) in zip(rows, rows[1:]):
        if t0 <= temp_c <= t1:
            return a0 + (a1 - a0) * (temp_c - t0) / (t1 - t0)
    raise ValueError(temp_c)


def v1_a(temp_c):
    """Formula 1's A: a fixed dielectric constant of 79 (I1)."""
    return 1820000.0 * (79.0 * (temp_c + 273.15)) ** -1.5


def recorder():
    spec = importlib.util.spec_from_file_location('record_golden_v3', ROOT / 'chemcore' / 'scripts' / 'record_golden_v3.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class IonicStrengthTests(SimpleTestCase):
    def test_from_the_conductivity_first(self):
        self.assertEqual((native.FRESH_UP_TO, native.SEA_FROM), (1.0, 5.0))
        self.assertEqual(native.fresh_ionic_strength(0.0, 80.0, conductivity_25_us_cm=1000.0, hardness_mg_l=300.0),
                         (1.6e-5 * 1000.0, 'conductivity'))

    def test_never_below_the_measured_ions(self):
        """An estimate below the measured ions' lower bound is taken as the bound: 500 µS/cm (I 0.008) beside 300 mg/L of
        hardness and 80 of alkalinity (at least 0.0089); a salinity of 0.01 ‰ (0.0002) beside 80 mg/L (0.0016)."""
        found, source = native.fresh_ionic_strength(0.0, 80.0, conductivity_25_us_cm=500.0, hardness_mg_l=300.0)
        self.assertEqual(source, 'hardness')
        self.assertGreater(found, 1.6e-5 * 500.0)
        self.assertEqual(native.fresh_ionic_strength(0.01, 80.0)[1], 'alkalinity')
        self.assertEqual(native.fresh_ionic_strength(0.0, None), (0.0, 'none'))

    def test_else_from_the_hardness_and_the_alkalinity(self):
        for hardness, alkalinity in ((250.0, 100.0), (50.0, 200.0), (300.0, 300.0)):
            with self.subTest(hardness=hardness, alkalinity=alkalinity):
                divalent = hardness / CACO3                        # mmol/L of Ca²⁺ and Mg²⁺
                bicarbonate = alkalinity / chemistry.MG_CACO3_PER_MEQ   # meq/L, as HCO₃⁻
                # The ions measured, and the monovalent ones their charges must have to balance (the least there are).
                expected = 0.5e-3 * (4 * divalent + bicarbonate + abs(2 * divalent - bicarbonate))
                found, source = native.fresh_ionic_strength(0.0, alkalinity, hardness_mg_l=hardness)
                self.assertEqual(source, 'hardness')
                self.assertAlmostEqual(found, expected, delta=1e-15)

    def test_else_from_the_salinity_else_from_the_alkalinity_alone(self):
        self.assertEqual(native.fresh_ionic_strength(2.0, 80.0), (native.ionic_strength(2.0), 'salinity'))
        found, source = native.fresh_ionic_strength(0.0, 80.0)
        self.assertEqual(source, 'alkalinity')
        self.assertAlmostEqual(found, 80.0 / chemistry.MG_CACO3_PER_MEQ / 1000, delta=1e-15)

    def test_sea_water_keeps_its_own(self):
        for salinity in (5.0, 10.0, 35.0):
            with self.subTest(salinity=salinity):
                self.assertEqual(native.fresh_ionic_strength(salinity, 80.0, conductivity_25_us_cm=500.0),
                                 (native.ionic_strength(salinity), 'seawater'))

    def test_above_davies_range_it_is_refused(self):
        """Cross review F3: Davies holds to an ionic strength of about 0.5; beyond it (a sea water's conductivity with no
        salinity, mS/cm typed as µS/cm) the fresh path refuses, never a positive log γ."""
        self.assertEqual(native.DAVIES_MAX, 0.5)
        self.assertEqual(native.fresh_ionic_strength(0.0, 80.0, conductivity_25_us_cm=31250.0), (0.5, 'conductivity'))
        for call in (lambda: native.fresh_ionic_strength(0.0, 80.0, conductivity_25_us_cm=40000.0),
                     lambda: native.equilibria_v3(12.0, 0.0, 80.0, conductivity_25_us_cm=1e6),
                     lambda: native.davies_log_gamma(12.0, 0.6, 1)):
            with self.assertRaisesRegex(ValueError, 'ionic strength above 0.5'):
                call()


class DaviesTests(SimpleTestCase):
    def test_a_is_the_temperatures_own(self):
        """I1 (cross review F2): A from the dielectric constant and the density of the temperature meets the table within
        0.03 % from 0 to 30 °C; formula 1's fixed ε = 79 was 7.5 % too large at 12 °C and 15 % at 2 °C."""
        for temp_c, a in A_TABLE.items():
            with self.subTest(temp_c=temp_c):
                self.assertAlmostEqual(native.debye_huckel_a(temp_c) / a, 1, delta=0.0003)
        self.assertAlmostEqual(v1_a(12.0) / tabulated_a(12.0) - 1, 0.075, delta=0.01)
        self.assertAlmostEqual(v1_a(2.0) / tabulated_a(2.0) - 1, 0.15, delta=0.01)

    def test_the_equation_at_cold_and_warm_temperatures(self):
        for temp_c in (2.0, 5.0, 12.0, 25.0):
            for strength in (0.001, 0.01, 0.05, 0.1):
                root = math.sqrt(strength)
                expected = -tabulated_a(temp_c) * (root / (1 + root) - 0.3 * strength)
                with self.subTest(temp_c=temp_c, strength=strength):
                    # γ within 0.1 % of Davies with the table's A, monovalent and divalent
                    self.assertAlmostEqual(10 ** (native.davies_log_gamma(temp_c, strength, 1) - expected), 1, delta=1e-3)
                    self.assertAlmostEqual(10 ** (native.davies_log_gamma(temp_c, strength, 2) - 4 * expected), 1,
                                           delta=1e-3)
                    self.assertEqual(native.davies_log_gamma(temp_c, strength, 2),
                                     4 * native.davies_log_gamma(temp_c, strength, 1))

    def test_the_literatures_value(self):
        # Stumm & Morgan (1996), table 3.3: by Davies a monovalent ion at I = 0.01 and 25 °C has γ = 0.90, a divalent 0.66.
        self.assertAlmostEqual(10 ** native.davies_log_gamma(25.0, 0.01, 1), 0.90, delta=0.005)
        self.assertAlmostEqual(10 ** native.davies_log_gamma(25.0, 0.01, 2), 0.66, delta=0.01)
        self.assertEqual(native.davies_log_gamma(12.0, 0.0, 1), 0.0)


class BoundaryTests(SimpleTestCase):
    """The fresh path up to 1 ‰, the sea path from 5 ‰ (Millero et al. 2006 measured K1, K2 from S 1; Dickson's 1990 KSO4
    and KB hold from S 5), each constant blended between: nothing jumps at either end (the comparison, the jump table)."""

    def test_the_sea_weight(self):
        for salinity, weight in ((0.0, 0.0), (1.0, 0.0), (3.0, 0.5), (5.0, 1.0), (35.0, 1.0)):
            with self.subTest(salinity=salinity):
                self.assertEqual(native.sea_weight(salinity), weight)

    def test_no_jump_at_either_end_of_the_band(self):
        for temp_c in (0.0, 2.0, 5.0, 8.0, 12.0, 25.0):
            for ions in ({}, {'conductivity_25_us_cm': 3700.0}, {'hardness_mg_l': 300.0}):
                for edge in (native.FRESH_UP_TO, native.SEA_FROM):
                    below = native.equilibria_v3(temp_c, edge - 1e-9, 120.0, **ions).values()[2:9]
                    above = native.equilibria_v3(temp_c, edge + 1e-9, 120.0, **ions).values()[2:9]
                    with self.subTest(temp_c=temp_c, ions=ions, edge=edge):
                        for one, two in zip(below, above):
                            self.assertAlmostEqual(two / one, 1, delta=1e-7)


class EquilibriaV3Tests(SimpleTestCase):
    def test_from_a_salinity_of_5_it_is_v1_but_for_the_nbs_conversions_a_and_the_kw(self):
        """Sea water keeps v1's constants bit for bit but two: its NBS pH is converted with the temperature's A (I1), and
        its Kw is Millero's (1995) on his seawater scale over [H+]SWS / [H+]free, as K1, K2 and KNH4 are converted (the
        correction of 2026-11-10; v1 keeps the 2007 Guide's approximate total-scale value, by name)."""
        for temp_c in (2.0, 12.0, 25.0):
            for salinity in (5.0, 10.0, 35.0):
                with self.subTest(temp_c=temp_c, salinity=salinity):
                    found = native.equilibria_v3(temp_c, salinity, 100.0, conductivity_25_us_cm=500.0)
                    v1 = native.equilibria(temp_c, salinity)
                    for name, value, old in zip(native.Equilibria.fields[3:], found.values()[3:], v1.values()[3:]):
                        if name != 'kw':
                            self.assertEqual(value, old, name)
                    self.assertEqual(found.kw, native.kw_sws(temp_c, salinity) / native.free_to_sws(temp_c, salinity))
                    self.assertEqual(v1.kw, native.kw_total(temp_c, salinity) / native.free_to_total(temp_c, salinity))
                    # the two differ by the Guide's 0.015 in ln Kw and by the fluoride between the two scales
                    self.assertAlmostEqual(found.kw / v1.kw, 1, delta=0.012)
                    self.assertNotEqual(found.kw, v1.kw)
                    strength = native.ionic_strength(salinity)
                    term = math.sqrt(strength) / (1 + math.sqrt(strength)) - 0.2 * strength
                    shift = -(native.debye_huckel_a(temp_c) - v1_a(temp_c)) * term
                    self.assertAlmostEqual(found.ph_offset, v1.ph_offset + shift, delta=1e-12)

    def test_fresh_water_constants_are_the_thermodynamic_ones_with_davies_activities(self):
        for temp_c, salinity, alkalinity, ions in ((12.0, 0.0, 80.0, {'conductivity_25_us_cm': 300.0}),
                                                   (8.0, 0.0, 200.0, {'hardness_mg_l': 300.0}),
                                                   (18.0, 0.8, 120.0, {}), (25.0, 0.0, 20.0, {})):
            with self.subTest(temp_c=temp_c, salinity=salinity, ions=ions):
                strength, _source = native.fresh_ionic_strength(salinity, alkalinity, **ions)
                one = native.davies_log_gamma(temp_c, strength, 1)
                two = native.davies_log_gamma(temp_c, strength, 2)
                ideal = native.equilibria(temp_c, 0.0)                  # v1's fresh water: every activity 1
                found = native.equilibria_v3(temp_c, salinity, alkalinity, **ions)
                self.assertEqual(found.ph_offset, one)
                close = {'rel_tol': 1e-13}
                self.assertTrue(math.isclose(found.k1, ideal.k1 / 10 ** (2 * one), **close))      # γH γHCO₃
                self.assertTrue(math.isclose(found.k2, ideal.k2 / 10 ** two, **close))            # γH γCO₃ / γHCO₃
                # γH γOH; Kw° is pure water's, Millero's (1995) at S 0 (v1's is the Guide's, 1.49 % lower)
                self.assertTrue(math.isclose(found.kw, native.kw_sws(temp_c, 0.0) / 10 ** (2 * one), **close))
                self.assertAlmostEqual(native.kw_sws(temp_c, 0.0) / ideal.kw, math.exp(0.015), delta=1e-12)
                self.assertTrue(math.isclose(found.k_h2s, ideal.k_h2s / 10 ** (2 * one), **close))
                self.assertTrue(math.isclose(found.kb, ideal.kb / 10 ** (2 * one), **close))
                self.assertEqual(found.k_nh4, ideal.k_nh4)                  # γH and γNH₄ cancel
                self.assertEqual(found.boron, native.equilibria(temp_c, salinity).boron)
                self.assertEqual(found.ksp_calcite, native.equilibria(temp_c, salinity).ksp_calcite)

    def test_with_no_ions_it_is_v1_but_for_the_kw(self):
        # Nothing measured (S 0, no alkalinity): an ionic strength of 0, v1's ideal fresh water exactly, but for Kw, which
        # is pure water's (Millero 1995 at S 0: pKw 13.995 at 25 °C; v1's, the 2007 Guide's shifted constant, gives
        # 14.001); with a tiny conductivity and no alkalinity, log γ goes as √I (at 1e-20 µS/cm, I = 1.6e-25, log γ about
        # −2e-13).
        for found in (native.equilibria_v3(12.0, 0.0), native.equilibria_v3(12.0, 0.0, conductivity_25_us_cm=1e-20)):
            for name, value, ideal in zip(FIELDS, found.values()[2:], native.equilibria(12.0, 0.0).values()[2:]):
                with self.subTest(name=name):
                    if name == 'kw':
                        ideal = native.kw_sws(12.0, 0.0)
                    self.assertTrue(math.isclose(value, ideal, rel_tol=1e-9, abs_tol=1e-12), (value, ideal))
        self.assertAlmostEqual(-math.log10(native.equilibria_v3(25.0, 0.0).kw), 13.995, delta=0.001)
        self.assertAlmostEqual(-math.log10(native.equilibria(25.0, 0.0).kw), 14.0012, delta=0.0001)

    def test_ions_lower_the_co2_and_the_nh3_share_at_a_measured_ph_and_alkalinity(self):
        # CO₂ = aH [HCO₃⁻] γHCO₃ / K1°: an ion-rich water holds less CO₂ at the pH its meter reads; NH₃'s corrected share
        # is K / (K + [H⁺]) with [H⁺] = aH / γH, smaller; the judged share is the larger, the ideal (cross review F1).
        for conductivity in (100.0, 500.0, 2000.0):
            v1, v3 = native.equilibria(12.0, 0.0), native.equilibria_v3(12.0, 0.0, 80.0, conductivity_25_us_cm=conductivity)
            meq = 80.0 / chemistry.MG_CACO3_PER_MEQ
            with self.subTest(conductivity=conductivity):
                self.assertLess(v3.co2(v3.dic(meq, 7.0), 7.0), v1.co2(v1.dic(meq, 7.0), 7.0))
                self.assertLess(v3.nh3_share_corrected(7.5), v1.nh3_share(7.5))
                self.assertEqual(v3.nh3_share(7.5), v1.nh3_share(7.5))   # judged on the larger, the ideal (F1)
                self.assertLess(v3.ph_offset, 0.0)


class GoldenV3Tests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.module = recorder()
        cls.records = cls.module.record_all()

    def test_the_core_reproduces_golden_v3_bit_for_bit(self):
        manifest = json.loads((V3 / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['golden_version'], 'v3')
        self.assertEqual(manifest['beside'], 'v1')
        for name, records in self.records.items():
            with self.subTest(block=name):
                data = (V3 / f'{name}.jsonl.gz').read_bytes()
                self.assertEqual(manifest['blocks'][name]['sha256'], hashlib.sha256(data).hexdigest())
                self.assertEqual(gzip.decompress(data), gzip.decompress(self.module.encode(records)))

    def test_the_corpus_holds_fresh_hard_and_brackish_waters_from_every_source(self):
        rows = self.records['waters']
        self.assertEqual({row['source'] for row in rows},
                         {'conductivity', 'hardness', 'salinity', 'alkalinity', 'seawater'})
        self.assertTrue(all(row['v3']['constants']['k1'] == row['v1']['constants']['k1'] for row in rows
                            if row['salinity'] >= 5 and row['ions'].get('water_origin') != 'salt_added'))
        # Salt-added water (cross review F3): the fresh path to the Davies limit, past it the sea path.
        salted = [row for row in rows if row['ions'] == {'water_origin': 'salt_added'}]
        self.assertTrue(all(row['v3']['provenance']['sea_weight'] == (1.0 if row['salinity'] >= 28.4 else 0.0)
                            for row in salted))
        self.assertTrue(any(row['v3'] != row['v1'] for row in rows if row['salinity'] < 5))

    def test_the_application_reads_formula_3_and_formula_1_is_still_golden_v1s(self):
        self.assertIs(chemistry.water_equilibria, native.water_equilibria)
        self.assertEqual(chemistry.water_equilibria(12.0, 0.0, 80.0), native.equilibria_v3(12.0, 0.0, 80.0))
        self.assertEqual(chemistry.water_equilibria(12.0, 0.0, 80.0, formula=1), native.equilibria(12.0, 0.0))
        self.assertEqual(chemistry.equilibria(12.0, 0.0).ph_offset, 0.0)

    def test_the_analyses_of_formula_3_differ_from_formula_1_below_5_permil_only_by_the_waters_ions(self):
        rows = self.records['analyses']
        self.assertEqual(len(rows), len(self.records['waters']))
        for row in rows:
            if row['salinity'] == 0 and not row['ions']:
                # alkalinity alone: formula 3 never shows more CO2 or NH3 than formula 1's ideal water
                self.assertLessEqual(row['v3']['co2_mg_l'], row['v1']['co2_mg_l'])
                self.assertLessEqual(row['v3']['nh3_n_mg_l'], row['v1']['nh3_n_mg_l'])

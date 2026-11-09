"""I2, fresh water's ionic strength (chemcore/findings/B1.md, I2; owner amendment B5): golden v3 beside v1, not used by
the application until the owner decides (chemcore/findings/I2-comparison.md).

Below a salinity of 5 the v3 water takes its ionic strength from what is measured: the conductivity (I = 1.6e-5 κ,
κ in µS/cm, Russell 1976), else the hardness with the alkalinity (the least ionic strength their ions give), else the
salinity (DOE 1994, as sea water), else the alkalinity alone (as sodium bicarbonate, the least it can be). The
constants there are the fresh-water (thermodynamic) ones, each made a concentration constant with Davies activity
coefficients (Davies 1962, log γ = −A z² (√I / (1 + √I) − 0.3 I)): the NBS pH becomes the free [H⁺] through γH, and
K1, K2, Kw, KB, KH2S follow the ions they hold. From a salinity of 5 the seawater path of v1 is kept bit for bit."""
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
        self.assertEqual(native.FRESH_BELOW, 5.0)
        self.assertEqual(native.fresh_ionic_strength(0.0, 80.0, conductivity_us_cm=500.0, hardness_mg_l=300.0),
                         (1.6e-5 * 500.0, 'conductivity'))

    def test_else_from_the_hardness_and_the_alkalinity(self):
        for hardness, alkalinity in ((250.0, 100.0), (50.0, 200.0), (300.0, 300.0)):
            with self.subTest(hardness=hardness, alkalinity=alkalinity):
                divalent = hardness / CACO3                        # mmol/L of Ca²⁺ and Mg²⁺
                bicarbonate = alkalinity / chemistry.MG_CACO3_PER_MEQ   # meq/L, as HCO₃⁻
                # The ions measured, and the monovalent ones their charges must have to balance (the least there are).
                expected = 0.5e-3 * (4 * divalent + bicarbonate + abs(2 * divalent - bicarbonate))
                found, source = native.fresh_ionic_strength(1.0, alkalinity, hardness_mg_l=hardness)
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
                self.assertEqual(native.fresh_ionic_strength(salinity, 80.0, conductivity_us_cm=500.0),
                                 (native.ionic_strength(salinity), 'seawater'))

    def test_above_davies_range_it_is_refused(self):
        """Cross review F3: Davies holds to an ionic strength of about 0.5; beyond it (a sea water's conductivity with no
        salinity, mS/cm typed as µS/cm) the fresh path refuses, never a positive log γ."""
        self.assertEqual(native.DAVIES_MAX, 0.5)
        self.assertEqual(native.fresh_ionic_strength(0.0, 80.0, conductivity_us_cm=31250.0), (0.5, 'conductivity'))
        for call in (lambda: native.fresh_ionic_strength(0.0, 80.0, conductivity_us_cm=40000.0),
                     lambda: native.equilibria_v3(12.0, 0.0, 80.0, conductivity_us_cm=1e6),
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


class EquilibriaV3Tests(SimpleTestCase):
    def test_from_a_salinity_of_5_it_is_v1_but_for_the_nbs_conversions_a(self):
        """Sea water keeps v1's constants bit for bit; its NBS pH is converted with the temperature's A (I1)."""
        for temp_c in (2.0, 12.0, 25.0):
            for salinity in (5.0, 10.0, 35.0):
                with self.subTest(temp_c=temp_c, salinity=salinity):
                    found = native.equilibria_v3(temp_c, salinity, 100.0, conductivity_us_cm=500.0)
                    v1 = native.equilibria(temp_c, salinity)
                    self.assertEqual(found.values()[3:], v1.values()[3:])
                    strength = native.ionic_strength(salinity)
                    term = math.sqrt(strength) / (1 + math.sqrt(strength)) - 0.2 * strength
                    shift = -(native.debye_huckel_a(temp_c) - v1_a(temp_c)) * term
                    self.assertAlmostEqual(found.ph_offset, v1.ph_offset + shift, delta=1e-12)

    def test_fresh_water_constants_are_the_thermodynamic_ones_with_davies_activities(self):
        for temp_c, salinity, alkalinity, ions in ((12.0, 0.0, 80.0, {'conductivity_us_cm': 300.0}),
                                                   (8.0, 0.0, 200.0, {'hardness_mg_l': 300.0}),
                                                   (18.0, 2.0, 120.0, {}), (25.0, 0.0, 20.0, {})):
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
                self.assertTrue(math.isclose(found.kw, ideal.kw / 10 ** (2 * one), **close))      # γH γOH
                self.assertTrue(math.isclose(found.k_h2s, ideal.k_h2s / 10 ** (2 * one), **close))
                self.assertTrue(math.isclose(found.kb, ideal.kb / 10 ** (2 * one), **close))
                self.assertEqual(found.k_nh4, ideal.k_nh4)                  # γH and γNH₄ cancel
                self.assertEqual(found.boron, native.equilibria(temp_c, salinity).boron)
                self.assertEqual(found.ksp_calcite, native.equilibria(temp_c, salinity).ksp_calcite)

    def test_with_no_ions_it_is_v1(self):
        # log γ goes as √I: at 1e-20 µS/cm, I = 1.6e-25 and log γ about −2e-13.
        found = native.equilibria_v3(12.0, 0.0, 80.0, conductivity_us_cm=1e-20)
        for name, value, ideal in zip(FIELDS, found.values()[2:], native.equilibria(12.0, 0.0).values()[2:]):
            with self.subTest(name=name):
                self.assertTrue(math.isclose(value, ideal, rel_tol=1e-9, abs_tol=1e-12), (value, ideal))

    def test_ions_lower_the_co2_and_the_nh3_share_at_a_measured_ph_and_alkalinity(self):
        # CO₂ = aH [HCO₃⁻] γHCO₃ / K1°: an ion-rich water holds less CO₂ at the pH its meter reads; NH₃'s share is
        # K / (K + [H⁺]) with [H⁺] = aH / γH, larger.
        for conductivity in (100.0, 500.0, 2000.0):
            v1, v3 = native.equilibria(12.0, 0.0), native.equilibria_v3(12.0, 0.0, 80.0, conductivity_us_cm=conductivity)
            meq = 80.0 / chemistry.MG_CACO3_PER_MEQ
            with self.subTest(conductivity=conductivity):
                self.assertLess(v3.co2(v3.dic(meq, 7.0), 7.0), v1.co2(v1.dic(meq, 7.0), 7.0))
                self.assertLess(v3.nh3_share(7.5), v1.nh3_share(7.5))
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
                            if row['salinity'] >= 5))
        self.assertTrue(any(row['v3'] != row['v1'] for row in rows if row['salinity'] < 5))

    def test_the_application_still_reads_v1(self):
        self.assertIs(chemistry.equilibria, native.equilibria)
        self.assertEqual(chemistry.equilibria(12.0, 0.0).ph_offset, 0.0)

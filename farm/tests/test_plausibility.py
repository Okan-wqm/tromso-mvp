"""Plausibility warnings on a water's ionic inputs (cross review F5): shown with the value, never a refusal.

An error that makes the ionic strength too low is on the safe side, and the measured ions' bound catches many; the
non-conservative ones passed silently: a sea water's conductivity on a fresh unit, a conductivity borrowed from a
saltier point, a conductivity that disagrees with the salinity. Each is now said beside the value worked out:

- the conductivity against the salinity: the salinity's ionic strength outside what the conductivity allows, from a
  NaCl water's 8.4e-6 to a bicarbonate water's 1.6e-5 per µS/cm (Russell 1976), each widened by Russell's ±30 % scatter:
  5.9e-6 to 2.1e-5;
- the estimate against the measured ions' bound: a conductivity (no salinity) giving more than 10 times the ionic
  strength the hardness and alkalinity account for (salted, or in mS/cm?), or less than the bound by more than Russell's
  scatter, 1.5 times (not compensated to 25 °C, or in the wrong unit? the bound is used);
- a sea water's conductivity on a fresh water: with a salinity under 1 permil (or none), a conductivity that PSS-78
  (UNESCO 1983, extended below 2 by Hill et al. 1986) reads as 1 permil or more."""
from django.test import SimpleTestCase

from ..water import messages, native, read
from .test_water import WaterTestCase


class PracticalSalinityTests(SimpleTestCase):
    def test_pss78_at_25_degrees(self):
        """Standard sea water (S 35) conducts C(35, 25 °C, 0) = 42.914 mS/cm × r_t(25) at 25 °C; PSS-78 gives 35 there,
        and Hill et al.'s extension 0 at no conductivity."""
        r25 = 0.6766097 + 2.00564e-2 * 25 + 1.104259e-4 * 25 ** 2 - 6.9698e-7 * 25 ** 3 + 1.0031e-9 * 25 ** 4
        self.assertAlmostEqual(native.practical_salinity(42914.0 * r25), 35.0, delta=1e-4)
        self.assertAlmostEqual(native.practical_salinity(0.0), 0.0, delta=1e-9)
        one = native.practical_salinity(2000.0)
        self.assertGreater(one, 0.95)
        self.assertLess(one, 1.15)


class WarningTests(SimpleTestCase):
    def warnings(self, salinity, alkalinity=None, **ions):
        return native.water_equilibria(12.0, salinity, alkalinity, **ions).warnings

    def test_a_plausible_water_has_none(self):
        self.assertEqual(self.warnings(0.0, 80.0, conductivity_25_us_cm=300.0, hardness_mg_l=100.0), [])
        self.assertEqual(self.warnings(35.0, 115.0, conductivity_25_us_cm=53000.0), [])
        self.assertEqual(self.warnings(3.0, 80.0, conductivity_25_us_cm=5500.0), [])
        self.assertEqual(self.warnings(0.0, 80.0), [])

    def test_the_conductivity_against_the_salinity(self):
        self.assertEqual(self.warnings(3.0, 80.0, conductivity_25_us_cm=500.0), ['conductivity_salinity'])
        self.assertEqual(self.warnings(1.0, 80.0, conductivity_25_us_cm=20000.0), ['conductivity_salinity'])

    def test_the_estimate_against_the_measured_ions(self):
        self.assertEqual(self.warnings(0.0, 20.0, conductivity_25_us_cm=1500.0, hardness_mg_l=20.0),
                         ['conductivity_above_ions'])
        self.assertEqual(self.warnings(0.0, 200.0, conductivity_25_us_cm=100.0, hardness_mg_l=300.0),
                         ['conductivity_below_ions'])

    def test_a_sea_waters_conductivity_on_a_fresh_water(self):
        self.assertIn('seawater_conductivity', self.warnings(0.0, 80.0, conductivity_25_us_cm=20000.0))
        self.assertNotIn('seawater_conductivity', self.warnings(0.0, 80.0, conductivity_25_us_cm=1500.0))

    def test_said_with_the_value_and_never_refused(self):
        eq = native.water_equilibria(12.0, 0.0, 80.0, conductivity_25_us_cm=20000.0)
        said = messages.provenance(eq)
        self.assertIn('Check', said)
        self.assertIn('sea water of', said)
        self.assertEqual(eq.ionic_strength, 1.6e-5 * 20000.0)              # the value is still worked out
        self.assertEqual(native.equilibria(12.0, 0.0).warnings, [])       # formula 1 has none


class ReadTests(WaterTestCase):
    def test_a_samples_nh3_says_the_warning_in_its_title(self):
        self.sample(hours=2, tan_mg_l='2', ph='7.5', temperature_c='12', alkalinity_mg_l='80',
                    conductivity_25_us_cm='20000')
        nh3 = read.latest([self.mid1])[self.mid1.pk].get('nh3_n_mg_l')
        self.assertIsNotNone(nh3.value)
        self.assertIn('sea water of', nh3.provenance)

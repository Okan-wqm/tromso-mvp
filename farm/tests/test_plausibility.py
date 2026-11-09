"""Plausibility warnings on a water's ionic inputs (cross review F5): shown with the value, never a refusal.

An error that makes the ionic strength too low is on the safe side, and the measured ions' bound catches many; the
non-conservative ones passed silently: a sea water's conductivity on a fresh unit, a conductivity borrowed from a
saltier point, a conductivity that disagrees with the salinity. Each is now said beside the value worked out:

- the conductivity against the salinity: the salinity's ionic strength outside what the conductivity allows, from a
  NaCl water's 8.4e-6 to a bicarbonate water's 1.6e-5 per µS/cm (Russell 1976), each widened by Russell's ±30 % scatter:
  5.9e-6 to 2.1e-5;
- the estimate against the measured ions' bound: with the hardness measured and no salinity, a conductivity giving more
  than 30 times the ionic strength the hardness and alkalinity account for (an intensive RAS's nitrate, chloride and
  sulfate give 10 to 20 times: round 2 tuned it so normal RAS water stays quiet), or less than the bound by more than
  Russell's scatter, 1.5 times (not compensated to 25 °C, or in the wrong unit? the bound is used);
- a sea water's conductivity on a fresh water: with a salinity under 1 permil (or none), a conductivity that PSS-78
  (UNESCO 1983, extended below 2 by Hill et al. 1986) reads as 5 permil or more, past the band (about 8 950 µS/cm; a hard
  fresh RAS at 2000 to 3000 µS/cm stays quiet)."""
from django.test import SimpleTestCase
from django.urls import reverse

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
        # Ordinary intensive RAS water (nitrate, chloride and sulfate build up): no warning (round 2).
        self.assertEqual(self.warnings(0.0, 80.0, conductivity_25_us_cm=1000.0), [])
        self.assertEqual(self.warnings(0.0, 80.0, conductivity_25_us_cm=2000.0, hardness_mg_l=100.0), [])
        self.assertEqual(self.warnings(0.0, 80.0, conductivity_25_us_cm=3000.0, hardness_mg_l=150.0), [])

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
        self.assertNotIn('seawater_conductivity', self.warnings(0.0, 80.0, conductivity_25_us_cm=3000.0))
        self.assertNotIn('conductivity_above_ions', self.warnings(0.0, 20.0, conductivity_25_us_cm=20000.0))  # no hardness

    def test_said_with_the_value_and_never_refused(self):
        eq = native.water_equilibria(12.0, 0.0, 80.0, conductivity_25_us_cm=20000.0)
        said = messages.provenance(eq)
        self.assertIn('Check the salinity', said)
        self.assertIn('sea water of 5 ‰ or more', said)
        self.assertIn('the unit’s water origin', said)
        self.assertEqual(eq.ionic_strength, 1.6e-5 * 20000.0)              # the value is still worked out
        self.assertEqual(native.equilibria(12.0, 0.0).warnings, [])       # formula 1 has none


class ReadTests(WaterTestCase):
    def test_a_samples_nh3_says_the_warning_in_its_title(self):
        self.sample(hours=2, tan_mg_l='2', ph='7.5', temperature_c='12', alkalinity_mg_l='80',
                    conductivity_25_us_cm='20000')
        nh3 = read.latest([self.mid1])[self.mid1.pk].get('nh3_n_mg_l')
        self.assertIsNotNone(nh3.value)
        self.assertIn('sea water of', nh3.provenance)


class ReportTests(WaterTestCase):
    def test_the_printed_report_says_the_provenance_and_the_warnings(self):
        page = self.client.get(reverse('farm:water_calculator_report'), {
            'temperature_c': '12', 'ph': '7', 'salinity_ppt': '0', 'alkalinity_mg_l': '80',
            'conductivity_25_us_cm': '20000', 'drawn': '1'})
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'Formula 3: ionic strength 0.3200')
        self.assertContains(page, 'Check the salinity')
        self.assertContains(page, 'CO₂ judged on the basis its limits were set on')

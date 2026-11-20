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
from django.utils import translation

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


class NH3PastGuardTests(SimpleTestCase):
    """The K_NH4 panel's decision of 2026-11-10, row 3: above 30 °C or a salinity of 35 ‰ the judged NH₃ is outside what
    its guard holds (chemcore/core/tests/nh3_guard.rs) and may read below a Clegg & Whitfield (1995) based value (1.3 %
    at 35 °C, 5.6 % at 40 °C, S 35): a warning said with every value worked out from that water, never a refusal."""

    def warnings(self, temp_c, salinity, **more):
        return native.water_equilibria(temp_c, salinity, 115.0, **more).warnings

    def test_above_30_degrees_or_a_salinity_of_35_only(self):
        for temp_c, salinity in ((0.0, 0.0), (12.0, 0.0), (30.0, 0.0), (0.0, 35.0), (30.0, 35.0)):
            with self.subTest(temp_c=temp_c, salinity=salinity):
                self.assertEqual(self.warnings(temp_c, salinity), [])
        for temp_c, salinity in ((30.5, 0.0), (31.0, 35.0), (12.0, 35.5), (40.0, 40.0)):
            with self.subTest(temp_c=temp_c, salinity=salinity):
                self.assertEqual(self.warnings(temp_c, salinity), ['nh3_past_guard'])
        self.assertEqual(self.warnings(32.0, 10.0, water_origin='salt_added'), ['nh3_past_guard'])
        self.assertEqual(native.water_equilibria(32.0, 3.0, 80.0, conductivity_25_us_cm=500.0).warnings,
                         ['conductivity_salinity', 'nh3_past_guard'])
        self.assertEqual(native.water_equilibria(35.0, 40.0, formula=1).warnings, [])      # formula 1 has none

    def test_said_with_the_value_in_three_languages_and_never_refused(self):
        eq = native.water_equilibria(35.0, 35.0, 115.0)
        self.assertGreater(eq.nh3_share(8.0), 0)                           # the NH₃ is still worked out and judged
        said = messages.provenance(eq)
        self.assertIn('NH₃ and CO₂: above 30 °C or a salinity of 35 ‰', said)
        self.assertIn('the best estimate itself was not checked there', said)
        self.assertNotIn('above 30 °C', messages.provenance(native.water_equilibria(30.0, 35.0, 115.0)))
        english = str(messages.WARNINGS['nh3_past_guard'])
        for language in ('nb', 'tr'):
            with self.subTest(language=language), translation.override(language):
                words = str(messages.WARNINGS['nh3_past_guard'])
                self.assertNotEqual(words, english)
                self.assertIn('NH₃', words)
                self.assertIn('30 °C', words)
                self.assertIn('35 ‰', words)
                self.assertIn(words, messages.provenance(eq))


class ReadTests(WaterTestCase):
    def test_a_samples_nh3_says_the_warning_in_its_title(self):
        self.sample(hours=2, tan_mg_l='2', ph='7.5', temperature_c='12', alkalinity_mg_l='80',
                    conductivity_25_us_cm='20000')
        nh3 = read.latest([self.mid1])[self.mid1.pk].get('nh3_n_mg_l')
        self.assertIsNotNone(nh3.value)
        self.assertIn('sea water of', nh3.provenance)

    def test_a_warm_samples_nh3_says_it_is_past_the_guard(self):
        self.sample(hours=2, tan_mg_l='2', ph='7.5', temperature_c='31', alkalinity_mg_l='80')
        nh3 = read.latest([self.mid1])[self.mid1.pk].get('nh3_n_mg_l')
        self.assertIsNotNone(nh3.value)                                    # judged all the same
        self.assertIn('NH₃ and CO₂: above 30 °C or a salinity of 35 ‰', nh3.provenance)


class ReportTests(WaterTestCase):
    def test_the_printed_report_says_the_provenance_and_the_warnings(self):
        page = self.client.get(reverse('farm:water_calculator_report'), {
            'temperature_c': '12', 'ph': '7', 'salinity_ppt': '0', 'alkalinity_mg_l': '80',
            'conductivity_25_us_cm': '20000', 'drawn': '1'})
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'Formula 4: ionic strength 0.3200')
        self.assertContains(page, 'Check the salinity')
        self.assertContains(page, 'CO₂ judged on the safe side')

    def test_the_calculator_and_its_report_say_the_nh3_guard_warning(self):
        water = {'temperature_c': '32', 'ph': '7', 'salinity_ppt': '0', 'alkalinity_mg_l': '80', 'tan_mg_l': '1',
                 'drawn': '1'}
        for name in ('farm:water_calculator', 'farm:water_calculator_report'):
            with self.subTest(page=name):
                page = self.client.get(reverse(name), water)
                self.assertEqual(page.status_code, 200)
                self.assertContains(page, 'NH₃ and CO₂: above 30 °C or a salinity of 35 ‰')
                cool = self.client.get(reverse(name), {**water, 'temperature_c': '30'})
                self.assertNotContains(cool, 'NH₃ and CO₂: above 30 °C or a salinity of 35 ‰')


class BelowFittedTemperatureTests(WaterTestCase):
    """The water-chemistry audit of 2026-11-19, F10: a temperature is taken from −3 °C (sea water at Tromsø goes below
    0 °C), the constants are fitted from 0 °C. Below it every value worked out from the water says so; 0 °C itself is
    quiet. A warning, never a refusal: the judged values stay on the safe side there (the audit's out/09_cold.txt)."""

    def test_below_0_degrees_only(self):
        for temp_c, salinity in ((0.0, 0.0), (0.0, 34.0), (12.0, 34.0)):
            with self.subTest(temp_c=temp_c, salinity=salinity):
                self.assertNotIn('below_fitted_temp', native.water_equilibria(temp_c, salinity, 115.0).warnings)
        for temp_c, salinity in ((-0.1, 34.0), (-1.9, 30.0), (-3.0, 0.0)):
            with self.subTest(temp_c=temp_c, salinity=salinity):
                self.assertEqual(native.water_equilibria(temp_c, salinity, 115.0).warnings, ['below_fitted_temp'])
        self.assertEqual(native.water_equilibria(-1.9, 34.0, formula=1).warnings, [])      # formula 1 has none

    def test_said_with_a_samples_nh3_in_three_languages_and_still_judged(self):
        self.sample(hours=2, tan_mg_l='2', ph='7.8', temperature_c='-1.5', salinity_ppt='34')
        nh3 = read.latest([self.mid1])[self.mid1.pk].get('nh3_n_mg_l')
        self.assertIsNotNone(nh3.value)                                     # worked out and judged all the same
        self.assertIn('Below 0 °C', nh3.provenance)
        self.assertIn('fitted from 0 °C', nh3.provenance)
        english = str(messages.WARNINGS['below_fitted_temp'])
        for language in ('nb', 'tr'):
            with self.subTest(language=language), translation.override(language):
                words = str(messages.WARNINGS['below_fitted_temp'])
                self.assertNotEqual(words, english)
                self.assertIn('0 °C', words)

    def test_the_calculator_says_it(self):
        water = {'temperature_c': '-1.5', 'ph': '7.8', 'salinity_ppt': '34', 'alkalinity_mg_l': '115',
                 'tan_mg_l': '1', 'drawn': '1'}
        for name in ('farm:water_calculator', 'farm:water_calculator_report'):
            with self.subTest(page=name):
                self.assertContains(self.client.get(reverse(name), water), 'Below 0 °C')
                self.assertNotContains(self.client.get(reverse(name), {**water, 'temperature_c': '0'}), 'Below 0 °C')

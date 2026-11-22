"""The switch to formula 4 (the water-chemistry audit of 2026-11-19, its paper debate's consensus and the owner's decision
of the same day, Rule S; chemcore/core/src/formula4.rs): every chemistry of the application is worked out by the core's
FORMULA_VERSION, 4, and says so; formula 3 (and 1) are still worked out exactly by name. What a farm sees: in salt water
the judged NH₃ and CO₂ are the best estimate at the pH ± 0.03 (the uncertainty of a pH reading, US EPA 1989) and the
words say it; fresh water is judged as before; a pH on another scale is put on the NBS scale by Millero's (1986) step.
The core's own grid tests are chemcore/core/tests/formula4.rs."""
import math

from django.test import SimpleTestCase
from django.utils import translation

from ..water import chemistry, deffeyes, messages, native

LIMITS = deffeyes.Limits(nh3_n_mg_l=0.0103, co2_mg_l=15.0, h2s_ug_l=2.0, alkalinity_low_mg_l=50.0,
                         alkalinity_high_mg_l=150.0)


class FormulaTests(SimpleTestCase):
    def test_the_application_works_out_formula_4_and_keeps_1_and_3_by_name(self):
        self.assertEqual((native.formula_version(), native.FORMULA_VERSION, chemistry.FORMULA_VERSION), (4, 4, 4))
        self.assertEqual(native.FORMULAS, (1, 3, 4))
        self.assertEqual(deffeyes.Water(12.0, 34.0, 7.6, 100.0).formula, 4)
        self.assertEqual(chemistry.water_equilibria(12.0, 34.0, 100.0), native.equilibria_v4(12.0, 34.0, 100.0))
        self.assertEqual(chemistry.water_equilibria(12.0, 34.0, 100.0, formula=3), native.equilibria_v3(12.0, 34.0, 100.0))
        self.assertEqual(chemistry.water_equilibria(12.0, 34.0, formula=1), native.equilibria(12.0, 34.0))
        with self.assertRaisesRegex(ValueError, 'the core has 1, 3 and 4'):
            chemistry.water_equilibria(12.0, 34.0, formula=2)

    def test_a_sea_analysis_judges_the_best_estimate_at_the_ph_plus_and_minus_0_03(self):
        analysis = deffeyes.analyse(deffeyes.Water(12.0, 34.0, 7.6, 100.0, tan_mg_l=1.0), LIMITS)
        eq = analysis.equilibria
        self.assertTrue(analysis.provenance.startswith('Formula 4: '))
        self.assertAlmostEqual(analysis.nh3_corrected_n_mg_l, eq.nh3_share_corrected(7.6), delta=1e-15)
        self.assertAlmostEqual(analysis.nh3_n_mg_l, eq.nh3_share_corrected(7.6 + native.PH_UNCERTAINTY), delta=1e-12)
        meq = 100.0 / chemistry.MG_CACO3_PER_MEQ
        self.assertAlmostEqual(analysis.co2_mg_l / chemistry.MG_CO2_PER_MMOL,
                               eq.co2(eq.dic(meq, 7.6 - native.PH_UNCERTAINTY), 7.6 - native.PH_UNCERTAINTY), delta=1e-12)
        # The owner's example (the consensus): best estimate 0.00608, judged 0.00652 (formula 3 judged 0.00672).
        self.assertEqual(round(analysis.nh3_corrected_n_mg_l, 5), 0.00608)
        self.assertEqual(round(analysis.nh3_n_mg_l, 5), 0.00651)
        three = deffeyes.analyse(deffeyes.Water(12.0, 34.0, 7.6, 100.0, tan_mg_l=1.0, formula=3), LIMITS)
        self.assertAlmostEqual(three.nh3_n_mg_l, 0.006715, delta=5e-7)

    def test_fresh_water_is_judged_as_formula_3_judged_it(self):
        for conductivity in (None, 300.0, 3000.0):
            four = deffeyes.analyse(deffeyes.Water(12.0, 0.0, 7.6, 80.0, tan_mg_l=0.5, total_sulfide_ug_l=2.0,
                                                   conductivity_25_us_cm=conductivity), LIMITS)
            three = deffeyes.analyse(deffeyes.Water(12.0, 0.0, 7.6, 80.0, tan_mg_l=0.5, total_sulfide_ug_l=2.0,
                                                    conductivity_25_us_cm=conductivity, formula=3), LIMITS)
            with self.subTest(conductivity=conductivity):
                self.assertEqual((four.co2_mg_l, four.nh3_n_mg_l, four.co2_corrected_mg_l, four.h2s_ug_l),
                                 (three.co2_mg_l, three.nh3_n_mg_l, three.co2_corrected_mg_l, three.h2s_ug_l))
                # The best estimate takes Clegg & Whitfield's pure-water constant: within 0.5 % of formula 3's.
                self.assertAlmostEqual(four.nh3_corrected_n_mg_l / three.nh3_corrected_n_mg_l, 1, delta=0.005)

    def test_a_total_scale_ph_takes_millero_s_step(self):
        eq = chemistry.water_equilibria(12.0, 34.0)
        self.assertEqual(eq.ph_offset, native.ph_offset_v4(12.0, 34.0))
        self.assertEqual(eq.ph_nbs(7.95, 'total'), 7.95 + math.log10(native.free_to_total(12.0, 34.0)) - eq.ph_offset)
        # 25 °C: pH NBS − pH total (molal) is Millero's line, 0.1306 + 0.00073 S.
        self.assertAlmostEqual(native.nbs_minus_total_25(34.0), 0.1306 + 0.00073 * 34.0, delta=1e-15)


class WordsTests(SimpleTestCase):
    def test_the_judged_words_say_the_margin_and_its_source_in_three_languages(self):
        self.assertEqual(native.PH_UNCERTAINTY, 0.03)
        for kind, sign in (('nh3', '+ 0.03'), ('co2', '− 0.03')):
            english = str(messages.JUDGED[kind, 'limits'])
            with self.subTest(kind=kind):
                self.assertIn(sign, english)
                self.assertIn('US EPA 1989', english)
                self.assertIn('best estimate %(value)s mg/L', english)
                self.assertNotIn('Khoo', english)
                self.assertNotIn('activity-corrected', english)
                english % {'value': '0.0121'}                      # formats (no stray % sign)
                for language in ('nb', 'tr'):
                    with translation.override(language):
                        words = str(messages.JUDGED[kind, 'limits'])
                        self.assertNotEqual(words, english)
                        self.assertIn('0,03', words)
                        self.assertIn('EPA', words)
                        words % {'value': '0,0121'}

    def test_the_co2_words_say_the_margin_the_core_gives_over_the_whole_range(self):
        """The judged CO₂ over its best estimate from 5 ‰, as the program works it out (S 5 to 40, 0 to 30 °C): never
        below 10^0.03 − 1, at most about 10 % up to pH 8.2 and 14 % at pH 9 with 50 mg/L, more with less alkalinity (it
        said "about 7 to 9 %", true only to about pH 8: the independent review of formula 4, can-follow 2)."""
        def margins(phs, alkalinities):
            found = []
            for salinity in (5.0, 10.0, 34.0, 40.0):
                for temperature in (0.0, 12.0, 30.0):
                    for alkalinity in alkalinities:
                        for ph in phs:
                            if deffeyes.why_impossible(temperature, salinity, ph, alkalinity):
                                continue                             # below its floor (S 40, 30 °C, pH 8.5, 10 mg/L)
                            analysis = deffeyes.analyse(deffeyes.Water(temperature, salinity, ph, alkalinity))
                            self.assertEqual(analysis.co2_basis, 'limits')
                            found.append(analysis.co2_mg_l / analysis.co2_corrected_mg_l - 1)
            return found

        least = 10 ** native.PH_UNCERTAINTY - 1
        up_to_8_2 = margins([6.0, 6.5, 7.0, 7.5, 8.0, 8.2], [50.0, 100.0, 200.0])
        at_9 = margins([9.0], [50.0, 100.0, 200.0])
        low_alkalinity = margins([8.5], [10.0])
        self.assertGreaterEqual(min(up_to_8_2 + at_9 + low_alkalinity), least - 1e-12)
        self.assertLess(max(up_to_8_2), 0.10)
        self.assertGreater(max(up_to_8_2), 0.09)                     # "up to about 10 %"
        self.assertTrue(0.135 < max(at_9) < 0.145)                   # "14 % at pH 9"
        self.assertGreater(max(low_alkalinity), 0.145)               # "more ... with a low alkalinity"
        english = str(messages.JUDGED['co2', 'limits'])
        self.assertIn('at least 7 %% above it', english)
        self.assertIn('up to about 10 %% at pH 8.2 and 14 %% at pH 9 with 50 mg/L', english)
        self.assertNotIn('7 to 9', english)
        for language, number in (('nb', '14'), ('tr', '14')):
            with translation.override(language):
                words = str(messages.JUDGED['co2', 'limits'])
                self.assertIn(number, words)
                self.assertIn('8,2', words)

    def test_a_sea_nh3_says_what_its_best_estimate_rests_on(self):
        eq = chemistry.water_equilibria(12.0, 34.0, 100.0)
        said = messages.judged('nh3', 'limits', 0.0061, eq)
        self.assertIn('best estimate 0.0061 mg/L', said)
        self.assertIn(str(messages.BEST_SEA), said)
        self.assertIn('Millero', str(messages.BEST_SEA))
        self.assertIn('Clegg & Whitfield', str(messages.BEST_SEA))
        fresh = messages.judged('nh3', 'limits', 0.0061, chemistry.water_equilibria(12.0, 0.0, 100.0))
        self.assertNotIn(str(messages.BEST_SEA), fresh)
        self.assertIn('7 %', messages.judged_on_nbs('total'))
        self.assertIn('Millero', messages.judged_on_nbs('total'))

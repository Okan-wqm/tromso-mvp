"""The switch to formula 4 (the water-chemistry audit of 2026-11-19, its paper debate's consensus and the owner's decision
of the same day, Rule S; chemcore/core/src/formula4.rs): every chemistry of the application is worked out by the core's
FORMULA_VERSION, 4, and says so; formula 3 (and 1) are still worked out exactly by name. What a farm sees: in salt water
the judged NH₃ and CO₂ are the best estimate at the pH ± 0.03 (the uncertainty of a pH reading, US EPA 1989) and the
words say it; fresh water is judged as before; a pH on another scale is put on the NBS scale by Millero's (1986) step.
The core's own grid tests are chemcore/core/tests/formula4.rs."""
import math
import re

from django.test import SimpleTestCase
from django.utils import translation

from ..water import chemistry, deffeyes, messages, native, parameters

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

    def test_the_co2_words_name_the_floor_and_the_direction_the_core_holds_over_the_whole_range(self):
        """The judged CO₂ over its best estimate from 5 ‰, as the program works it out over everything it accepts (the
        bounds of farm/water/parameters.py: T −3 to 40 °C, S to 50 ‰, pH 2 to 12, alkalinity 0 to 1000 mg/L): never below
        10^0.03 − 1 (7.15 %), lower the higher the alkalinity (at every temperature, salinity and pH), and with no
        maximum to name: beside the alkalinity floor it passes 100 % (a sweep of 1.3 million waters reached +171 000 %).
        The words say the floor and the direction and no maximum: "up to about 10 % at pH 8.2 and 14 % at pH 9 with
        50 mg/L" was false, +11.3 % and +19.1 % are in the range (the verification of 2026-11-22, F2); before it said
        "about 7 to 9 %", true only to about pH 8 (the independent review of formula 4, can-follow 2)."""
        bound = {parameter.code: (float(parameter.low), float(parameter.high)) for parameter in parameters.MEASURED}
        (t_low, t_high), (ph_low, ph_high) = bound['temperature_c'], bound['ph']
        (a_low, a_high), s_high = bound['alkalinity_mg_l'], bound['salinity_ppt'][1]
        temperatures = [t_low, 0.0, 6.0, 12.0, 20.0, 30.0, t_high]
        salinities = [native.SEA_FROM, 7.5, 10.0, 20.0, 34.0, 40.0, s_high]
        phs = [ph_low + 0.25 * step for step in range(int((ph_high - ph_low) / 0.25) + 1)]
        alkalinities = [a_low, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0, 200.0, 500.0, a_high]
        margins = []
        for salinity in salinities:
            for temperature in temperatures:
                for ph in phs:
                    row = []                                         # the margin along the alkalinity, one water each
                    for alkalinity in alkalinities:
                        if deffeyes.why_impossible(temperature, salinity, ph, alkalinity):
                            continue                                 # at or below the alkalinity floor of its pH
                        analysis = deffeyes.analyse(deffeyes.Water(temperature, salinity, ph, alkalinity))
                        if analysis.co2_corrected_mg_l <= 0:
                            continue                                 # no CO₂ to compare with
                        self.assertEqual(analysis.co2_basis, 'limits')
                        row.append(analysis.co2_mg_l / analysis.co2_corrected_mg_l - 1)
                    for lower_alkalinity, higher_alkalinity in zip(row, row[1:]):
                        self.assertLessEqual(higher_alkalinity, lower_alkalinity + 1e-9,
                                             f'S {salinity}, {temperature} °C, pH {ph}: more alkalinity, more margin')
                    margins += row
        self.assertGreater(len(margins), 15000)                      # the sweep ran (17 116 waters at the time of writing)
        least = 10 ** native.PH_UNCERTAINTY - 1
        self.assertGreaterEqual(min(margins), least - 1e-12)         # "at least 7 %" (the least found: +7.1535 %)
        self.assertLess(min(margins), 0.08)                          # and 7 is the whole percent below the least
        self.assertGreater(max(margins), 1.0)                        # no maximum to name: past 100 % near the floor
        english = str(messages.JUDGED['co2', 'limits'])
        self.assertIn('at least 7 %% above it and more the lower the alkalinity;', english)
        for language in ('en', 'nb', 'tr'):
            with translation.override(language):
                words = str(messages.JUDGED['co2', 'limits'])
                # The one percentage the words give is the floor; no pH, no alkalinity, no other figure belongs to it.
                self.assertEqual([number for pair in re.findall(r'%%\s?(\d+)|(\d+)\s?%%', words) for number in pair
                                  if number], ['7'])
                for removed in ('up to', 'opptil', 'yaklaşık', '8.2', '8,2', 'pH 9', '50 mg/L', '7 to 9'):
                    self.assertNotIn(removed, words)
                words % {'value': '0.0121'}                          # still formats
        with translation.override('nb'):
            self.assertIn('minst 7 %% over det og mer jo lavere alkaliteten er;', str(messages.JUDGED['co2', 'limits']))
        with translation.override('tr'):
            self.assertIn('en az %% 7 üstünde, alkalinite ne kadar düşükse o kadar fazla;',
                          str(messages.JUDGED['co2', 'limits']))

    def test_the_nh3_words_say_up_to_7_percent_and_less_the_higher_the_ph_over_the_whole_range(self):
        """The judged NH₃-N over its best estimate from 5 ‰, as the program works it out over everything it accepts
        (the bounds of farm/water/parameters.py: T −3 to 40 °C, S to 50 ‰, pH 2 to 12): the 10^0.03 is the ratio
        r = [NH₃]/[NH₄⁺], and NH₃-N is r / (1 + r) of the TAN, so the NH₃-N is (10^0.03 − 1) / (1 + 10^0.03 r) above its
        best estimate: at most 10^0.03 − 1 (7.15 %, where r is nothing), never rising with the pH (r does), and as
        little as 0.013 % at pH 12 (a sweep of 241,595 waters). "About 7 % above it" was false there: the NH₃-N is that
        much above only while little of the TAN is NH₃ (the verification of 2026-11-22, F2 and its follow-up). The
        words, and those said beside a pH put on the NBS scale (the same margin: only the pH it starts from moves), say
        "up to about 7 % above it, less the higher the pH"."""
        bound = {parameter.code: (float(parameter.low), float(parameter.high)) for parameter in parameters.MEASURED}
        (t_low, t_high), (ph_low, ph_high) = bound['temperature_c'], bound['ph']
        s_high = bound['salinity_ppt'][1]
        temperatures = [t_low, 0.0, 6.0, 12.0, 20.0, 30.0, t_high]
        salinities = [native.SEA_FROM, 7.5, 10.0, 20.0, 34.0, 40.0, s_high]
        phs = [ph_low + 0.25 * step for step in range(int((ph_high - ph_low) / 0.25) + 1)]
        ratio = 10 ** native.PH_UNCERTAINTY
        margins = []
        for salinity in salinities:
            for temperature in temperatures:
                for alkalinity in (100.0, 1000.0):
                    row = []                                         # the margin along the pH, one water each
                    for ph in phs:
                        if deffeyes.why_impossible(temperature, salinity, ph, alkalinity):
                            continue                                 # at or below the alkalinity floor of its pH
                        analysis = deffeyes.analyse(deffeyes.Water(temperature, salinity, ph, alkalinity, tan_mg_l=1.0))
                        self.assertEqual(analysis.nh3_basis, 'limits')
                        share = analysis.nh3_corrected_n_mg_l / 1.0                 # the best estimate's share of the TAN
                        margin = analysis.nh3_n_mg_l / analysis.nh3_corrected_n_mg_l - 1
                        # The closed form: the whole of the margin is the shift of r by 10^0.03.
                        self.assertAlmostEqual(margin, (ratio - 1) / (1 + ratio * share / (1 - share)), delta=1e-9)
                        row.append(margin)
                    for lower_ph, higher_ph in zip(row, row[1:]):
                        self.assertLessEqual(higher_ph, lower_ph + 1e-12,
                                             f'S {salinity}, {temperature} °C, alkalinity {alkalinity}: more pH, more')
                    margins += row
        self.assertGreater(len(margins), 3000)                       # the sweep ran (3 790 waters at the time of writing)
        self.assertLess(max(margins), ratio - 1 + 1e-12)             # "up to": never above 10^0.03 − 1 ...
        self.assertGreater(max(margins), 0.07)                       # ... and 7 is where it gets to (+7.1519 %)
        self.assertLess(min(margins), 0.001)                         # "less": to nothing worth the name at pH 12
        said = {'en': ('up to about 7 %% above it, less the higher the pH;',
                       'up to about 7 %% above its best estimate, less the higher the pH.'),
                'nb': ('opptil omtrent 7 %% over det, mindre jo høyere pH er;',
                       'opptil omtrent 7 %% over det beste estimatet, mindre jo høyere pH er.'),
                'tr': ('en fazla yaklaşık %% 7 üstünde, pH yükseldikçe daha az;',
                       'en fazla yaklaşık %% 7 üstünde, pH yükseldikçe daha az.')}
        for language, (judged, on_nbs) in said.items():
            with translation.override(language):
                for words, phrase in ((str(messages.JUDGED['nh3', 'limits']), judged),
                                      (str(messages.JUDGED_ON_NBS), on_nbs)):
                    with self.subTest(language=language, phrase=phrase):
                        self.assertIn(phrase, words)
                        # The one percentage the words give is the top; no other figure belongs to it.
                        self.assertEqual([number for pair in re.findall(r'%%\s?(\d+)|(\d+)\s?%%', words)
                                          for number in pair if number], ['7'])
                        words % {'value': '0.0121', 'scale': 'total scale'}         # still formats

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

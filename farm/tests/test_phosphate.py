"""The optional phosphate (PO₄-P) of a water (the independent check of 2026-11-09, hypothesis 12a; owner-approved
2026-11-10; chemcore/findings/phosphate.md).

Phosphate is part of the alkalinity a titration measures (Dickson 1981's definition, as Dickson, Sabine & Christian
2007 give it: [HPO₄²⁻] + 2 [PO₄³⁻] − [H₃PO₄]). The core did not know it: the CO₂ of a pH and an alkalinity came out too
high (the safe side), and what a dose or a stripping does came out without the phosphate's buffer, the CO₂ after it far
too low (the unsafe side: 57 to 71 % at 10 mg/L in fresh water). Now a water may say its PO₄-P:

- without it every result is what it was, bit for bit (golden v1, golden v3's blocks);
- with it the water's own DIC and CO₂ count it, and so does every dose, recipe and simulator step;
- the judged CO₂, its status, border and the chart's CO₂ curve never fall because of it: they are the water's without
  the phosphate (the limits' basis counts none, as Standard Methods 4500-CO₂ D);
- the NH₃ does not depend on it."""
import uuid
from decimal import Decimal as D

from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import timezone, translation

from core.models import Profile

from ..forms.water import CalculatorForm
from ..models import WaterFreshness, WaterMeasurement
from ..water import calculation, deffeyes, freshness, messages, native, parameters, read
from .test_water import WaterTestCase

LIMITS = deffeyes.Limits(nh3_n_mg_l=0.0103, co2_mg_l=15.0, alkalinity_low_mg_l=50.0, alkalinity_high_mg_l=150.0)


def analysis(phosphate=None, salinity=0.0, alkalinity=100.0, ph=7.2, **more):
    water = deffeyes.Water(15.0, salinity, ph, alkalinity, tan_mg_l=1.0, phosphate_p_mg_l=phosphate, **more)
    return deffeyes.analyse(water, LIMITS)


class CoreTests(SimpleTestCase):
    """The core's doors from Python (its own tests are chemcore/core/tests/phosphate.rs)."""

    def test_the_constants_are_pure_waters_at_a_salinity_of_0(self):
        import math
        for constant, pk in ((native.k1p_sws, 2.149), (native.k2p_sws, 7.200), (native.k3p_sws, 12.345)):
            self.assertAlmostEqual(-math.log10(constant(25.0, 0.0)), pk, delta=0.001)
        self.assertEqual(native.MG_P_PER_MMOL, 30.973762)

    def test_without_a_phosphate_the_water_is_what_it_was(self):
        for salinity in (0.0, 3.0, 35.0):
            bare = native.water_equilibria(15.0, salinity, 100.0)
            for none in (None, 0.0):
                same = native.water_equilibria(15.0, salinity, 100.0, phosphate_p_mg_l=none)
                self.assertEqual(same, bare)
                self.assertEqual((same.phosphate, same.k1p, same.k2p, same.k3p), (0.0, 0.0, 0.0, 0.0))
                self.assertEqual(same.isoline(7.2), bare.isoline(7.2))
            self.assertEqual(analysis(None, salinity), analysis(0.0, salinity))
        # Formula 1 does not read it.
        self.assertEqual(native.water_equilibria(15.0, 1.0, 100.0, phosphate_p_mg_l=10.0, formula=1),
                         native.equilibria(15.0, 1.0))
        with self.assertRaises(ValueError):
            native.water_equilibria(15.0, 0.0, 100.0, phosphate_p_mg_l=-1.0)

    def test_with_it_the_waters_own_co2_and_dic_are_lower_and_the_judged_co2_is_not(self):
        for salinity in (0.0, 3.0, 35.0):
            with self.subTest(salinity=salinity):
                bare, given = analysis(None, salinity), analysis(10.0, salinity)
                eq = given.equilibria
                self.assertAlmostEqual(eq.phosphate, 10.0 / 30.973762 / 1000, delta=1e-15)
                self.assertLess(given.dic, bare.dic)
                self.assertLess(given.co2_corrected_mg_l, bare.co2_corrected_mg_l)
                # The judged CO₂, its border and its status: the water's without the phosphate, to the last bit.
                self.assertEqual(given.co2_mg_l, bare.co2_mg_l)
                self.assertEqual((given.co2.ph, given.co2.status), (bare.co2.ph, bare.co2.status))
                self.assertEqual(given.co2_basis, 'limits')
                # The NH₃ does not read it.
                self.assertEqual((given.nh3_n_mg_l, given.nh3.ph), (bare.nh3_n_mg_l, bare.nh3.ph))
        # Its size at the check's typical water (15 °C, 2 meq/L, pH 7.0, 10 mg/L): the CO₂ without it was 6 % too high
        # in fresh water, 17 % in sea water.
        for salinity, wanted in ((0.0, 0.06), (35.0, 0.17)):
            bare = analysis(None, salinity, alkalinity=2 * native.MG_CACO3_PER_MEQ, ph=7.0)
            given = analysis(10.0, salinity, alkalinity=2 * native.MG_CACO3_PER_MEQ, ph=7.0)
            self.assertAlmostEqual(bare.co2_corrected_mg_l / given.co2_corrected_mg_l - 1, wanted, delta=0.02)

    def test_a_dose_meets_the_phosphates_buffer(self):
        """A simulator step of sodium hydroxide: with the phosphate the pH rises less and the CO₂ left is higher than the
        core said before (the unsafe side the input closes)."""
        steps = {}
        for phosphate in (None, 10.0):
            water = deffeyes.Water(15.0, 0.0, 7.2, 100.0, tan_mg_l=1.0, phosphate_p_mg_l=phosphate)
            made = calculation.calculate(water, LIMITS, None, 1.0, layers=frozenset(), chosen=[], volume=1.0,
                                         amounts={'naoh': 20.0})
            steps[phosphate] = made.steps[-1].step
        self.assertLess(steps[10.0].ph, steps[None].ph - 0.2)
        self.assertGreater(steps[10.0].co2_mg_l, 1.5 * steps[None].co2_mg_l)

    def test_a_water_whose_phosphate_alone_is_its_alkalinity_cannot_be(self):
        why = deffeyes.why_impossible(15.0, 0.0, 7.5, 10.0, phosphate_p_mg_l=10.0)
        self.assertIn('the hydroxide, the borate and the phosphate given alone are that much', why)
        self.assertEqual(deffeyes.why_impossible(15.0, 0.0, 7.5, 10.0), '')
        with self.assertRaises(native.ImpossibleWaterError):
            analysis(10.0, alkalinity=10.0, ph=7.5)

    def test_the_words_say_the_phosphate_and_what_judged(self):
        given = analysis(10.0)
        self.assertIn('phosphate 10.00 mg/L as P counted in the alkalinity', given.provenance)
        self.assertIn('CO₂ judged without the phosphate', given.co2_judged)
        self.assertIn('never below what it was before the phosphate was given', given.co2_judged)
        self.assertNotIn('phosphate', analysis(None).provenance)
        self.assertNotIn('phosphate', analysis(None, conductivity_25_us_cm=500.0).co2_judged)
        english = str(messages.JUDGED_WITHOUT_PHOSPHATE)
        for language in ('nb', 'tr'):
            with self.subTest(language=language), translation.override(language):
                self.assertNotEqual(str(messages.JUDGED_WITHOUT_PHOSPHATE), english)
                self.assertNotEqual(str(parameters.get('phosphate_p_mg_l').label), 'Phosphate (mg/L PO₄ as P)')
                self.assertIn('PO₄', str(parameters.get('phosphate_p_mg_l').label))


class ParameterTests(WaterTestCase):
    def test_it_is_a_water_parameter_like_the_others(self):
        phosphate = parameters.get('phosphate_p_mg_l')
        self.assertEqual((str(phosphate.label), phosphate.decimals, phosphate.low, phosphate.high),
                         ('Phosphate (mg/L PO₄ as P)', 2, D('0'), D('100')))
        self.assertIn('divide by 3.07', str(phosphate.help))
        self.assertIn(phosphate, parameters.LIMITED)                      # a farm sets its own limits on it
        # How long it stays fresh is the farm's reference data, seeded at 7 days.
        self.assertEqual(freshness.SEEDS['phosphate_p_mg_l'], 168)
        self.assertEqual(WaterFreshness.objects.get(parameter='phosphate_p_mg_l').fresh_hours, 168)
        from sensors import quantities
        self.assertEqual((quantities.get('phosphate_p_mg_l').unit, quantities.get('phosphate_p_mg_l').water), ('mg/L', True))

    def test_a_sample_holds_it_and_the_pages_show_it(self):
        sample = self.sample(phosphate_p_mg_l='8.5', ph='7.2')
        self.assertEqual(WaterMeasurement.objects.get(pk=sample.pk).phosphate_p_mg_l, D('8.50'))
        self.assertEqual(read.latest([self.mid1])[self.mid1.pk].get('phosphate_p_mg_l').value, D('8.50'))
        for query in ({'unit': self.t1.pk}, {'unit': self.t1.pk, 'view': 'history'}):
            self.assertContains(self.client.get(reverse('farm:water'), query), 'PO₄-P (mg/L)')
        self.assertContains(self.client.get(reverse('farm:water_record')), 'Phosphate (mg/L PO₄ as P)')
        local = timezone.localtime(self.ago(hours=2)).strftime('%Y-%m-%dT%H:%M')
        data = {'token': str(uuid.uuid4()), 'point': str(self.mid1.pk), 'measured_at': local, 'source': 'manual',
                'notes': '', **{code: '' for code in parameters.COLUMNS}, 'phosphate_p_mg_l': '101'}
        response = self.client.post(reverse('farm:water_record'), data, headers={'X-Modal': '1'})
        self.assertEqual(response.status_code, 422)
        self.assertIn('phosphate_p_mg_l', response.context['form'].errors)


class CalculatorTests(WaterTestCase):
    WATER = {'temperature_c': '15', 'ph': '7.2', 'salinity_ppt': '0', 'alkalinity_mg_l': '100', 'tan_mg_l': '1',
             'drawn': '1'}

    def page(self, name='farm:water_calculator', **values):
        return self.client.get(reverse(name), {**self.WATER, **values})

    def test_left_empty_the_calculator_is_what_it_was(self):
        self.assertIsNone(CalculatorForm.DEFAULTS['phosphate_p_mg_l'])
        plain, empty = self.page(), self.page(phosphate_p_mg_l='')
        self.assertEqual(plain.context['analysis'], empty.context['analysis'])
        self.assertEqual(plain.context['analysis'], analysis(None))
        self.assertNotContains(plain, 'counted in the alkalinity')

    def test_with_a_phosphate_the_page_and_the_report_say_it(self):
        for name in ('farm:water_calculator', 'farm:water_calculator_report'):
            with self.subTest(page=name):
                page = self.page(name, phosphate_p_mg_l='10')
                self.assertEqual(page.status_code, 200)
                self.assertEqual(page.context['analysis'], analysis(10.0))
                self.assertContains(page, 'phosphate 10.00 mg/L as P counted in the alkalinity')
                self.assertContains(page, 'CO₂ judged without the phosphate')
        self.assertContains(self.page(), 'name="phosphate_p_mg_l"')

    def test_an_impossible_water_is_refused_with_the_phosphate_in_the_reason(self):
        page = self.page(alkalinity_mg_l='10', ph='7.5', phosphate_p_mg_l='10')
        self.assertIsNone(page.context['result'])
        self.assertIn('the phosphate given', page.context['form'].errors['alkalinity_mg_l'][0])

    def test_a_units_phosphate_goes_into_its_chart_and_the_calculator(self):
        self.sample(temperature_c='15', ph='7.2', salinity_ppt='0', alkalinity_mg_l='100', phosphate_p_mg_l='10')
        offered = calculation.offers(self.t1)
        self.assertEqual(offered['phosphate_p_mg_l'].value, D('10.00'))
        chart = calculation.chart_of(self.t1)
        self.assertAlmostEqual(chart.calculation.analysis.equilibria.phosphate, 10.0 / 30.973762 / 1000, delta=1e-15)
        self.assertIn('phosphate 10.00 mg/L as P counted in the alkalinity', chart.calculation.analysis.provenance)
        page = self.client.get(reverse('farm:water_unit_chart', args=[self.t1.pk]))
        self.assertContains(page, 'counted in the alkalinity')

    def test_in_three_languages(self):
        for language, words in (('nb', 'fosfat'), ('tr', 'fosfat')):
            with self.subTest(language=language):
                Profile.objects.update_or_create(user=self.user, defaults={'language': language})
                self.assertContains(self.page(phosphate_p_mg_l='10'), words)

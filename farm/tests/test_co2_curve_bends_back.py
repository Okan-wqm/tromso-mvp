"""A CO₂ curve that bends back says so (the independent review of 2026-11-16, R9). With a phosphate the chart's judged
CO₂ curve is drawn row by row of the alkalinity in the water's own DIC, which near an alkalinity of 0 (a pH under about
4.7, where the phosphate holds negative alkalinity) falls before it rises. The review's water: 12 °C, S 0, P 30 mg/L,
limit 15 mg/L: (DIC 0.2148, alkalinity 0) -> (0.1914, 0.0625) -> rising, and no note. The core now gives the note
`co2.bends_back` exactly when the drawn curve does it, and the chart says it in words."""
from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import translation

from ..water import deffeyes, messages
from .test_water import WaterTestCase

SAID = ('CO₂: near an alkalinity of 0 the curve bends back. With the phosphate given the water’s own DIC falls before it '
        'rises there (a pH under about 4.7, where the phosphate holds negative alkalinity); no fish water is in that '
        'corner.')
LIMITS = deffeyes.Limits(co2_mg_l=15.0)


def shape(phosphate):
    water = deffeyes.Water(temperature_c=12.0, salinity_ppt=0.0, ph=7.0, alkalinity_mg_l=80.0, phosphate_p_mg_l=phosphate)
    return deffeyes.geometry(deffeyes.analyse(water, LIMITS), layers=frozenset({'co2'}))


class NoteTests(SimpleTestCase):
    def test_the_reviews_water_bends_back_and_says_so(self):
        found = shape(30.0)
        (curve,) = found.boundaries['co2']
        self.assertAlmostEqual(curve[0][0], 0.2186, delta=1e-3)      # the review: 0.2148 (its own alkalinity)
        self.assertEqual(curve[0][1], 0.0)
        self.assertAlmostEqual(curve[1][0], 0.1980, delta=1e-3)      # the review: 0.1914
        self.assertAlmostEqual(curve[1][1], 0.0625, delta=1e-12)
        self.assertGreater(curve[2][0], curve[1][0])
        self.assertEqual([str(note) for note in found.notes], [SAID])

    def test_the_note_is_there_exactly_when_the_drawn_curve_bends_back(self):
        for phosphate in (None, 0.01, 0.5, 1.0, 3.0, 10.0, 30.0):
            with self.subTest(phosphate=phosphate):
                found = shape(phosphate)
                (curve,) = found.boundaries['co2']
                bends = any(two[0] < one[0] for one, two in zip(curve, curve[1:]))
                self.assertEqual(SAID in [str(note) for note in found.notes], bends)
        self.assertEqual(shape(None).notes, [])                       # without a phosphate: never

    def test_the_words_in_three_languages(self):
        self.assertEqual(str(messages.note('co2.bends_back')), SAID)
        for language, words in (('nb', 'bøyer kurven tilbake'), ('tr', 'eğri geri kıvrılır')):
            with self.subTest(language=language), translation.override(language):
                self.assertIn(words, str(messages.note('co2.bends_back')))


class PageTests(WaterTestCase):
    WATER = {'temperature_c': '12', 'salinity_ppt': '0', 'alkalinity_mg_l': '80', 'ph': '7.00', 'co2_limit_mg_l': '15',
             'drawn': '1', 'layers': ['co2']}

    def test_the_calculator_and_its_report_say_it_under_the_chart(self):
        for name in ('farm:water_calculator', 'farm:water_calculator_results', 'farm:water_calculator_report'):
            with self.subTest(page=name):
                self.assertContains(self.client.get(reverse(name), {**self.WATER, 'phosphate_p_mg_l': '30'}),
                                    'near an alkalinity of 0 the curve bends back')
                self.assertNotContains(self.client.get(reverse(name), self.WATER), 'the curve bends back')

    def test_a_units_chart_says_it(self):
        self.sample(temperature_c='12', ph='7.00', salinity_ppt='0', alkalinity_mg_l='80', phosphate_p_mg_l='30')
        self.limit('co2_mg_l', critical_high=15)
        self.stock()
        page = self.client.get(reverse('farm:water_unit_chart', args=[self.t1.pk]))
        self.assertContains(page, 'near an alkalinity of 0 the curve bends back')

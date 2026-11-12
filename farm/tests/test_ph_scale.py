"""The scale of a pH (the K_NH4 panel's decision of 2026-11-10, row 6; the owner's decision of 2026-11-11 on the scale
selector).

Every pH the application stores, shows and judges is on the NBS scale: what a meter calibrated with NBS/NIST buffers
reads. The panel found the largest single hazard of the ammonia chemistry here, larger than any question about a
constant: a total-scale pH (a seawater sensor calibrated with TRIS) typed in as NBS. So the input says its scale."""
import math

from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import translation

from ..water import native, parameters
from .test_water import WaterTestCase

HELP = ('As a pH meter or kit calibrated with NBS/NIST buffers reads it, at the water’s own temperature. A total-scale '
        'pH (a seawater sensor calibrated with TRIS) reads 0.10 to 0.14 lower in water of 5 to 35 ‰: typed here as NBS, '
        'the NH₃ worked out is 20 to 27 % too low.')


class HelpTests(SimpleTestCase):
    def test_the_ph_says_its_scale_and_the_hazard_in_three_languages(self):
        ph = parameters.get('ph')
        self.assertEqual(str(ph.label), 'pH (NBS scale)')
        self.assertEqual(str(ph.help), HELP)
        for language, words in (('nb', ('NBS/NIST', 'TRIS', '0,10', '0,14', '5 til 35 ‰', '20 til 27 %')),
                                ('tr', ('NBS/NIST', 'TRIS', '0,10', '0,14', '5–35 ‰', '% 20–27'))):
            with self.subTest(language=language), translation.override(language):
                said = str(ph.help)
                self.assertNotEqual(said, HELP)
                for word in words:
                    self.assertIn(word, said)

    def test_the_numbers_in_the_help_are_the_cores_own(self):
        """By the core's own factors (formula 3) over 5 to 35 ‰ and 0 to 30 °C: the NBS pH less the total-scale pH,
        log10([H⁺]total / [H⁺]free) less the offset free − NBS, is 0.10 to 0.14; a total-scale pH of 8 typed as NBS
        makes the judged NH₃ 20 to 27 % lower than at the NBS pH the water really has."""
        apart, low = [], []
        for salinity in (5.0, 10.0, 20.0, 30.0, 35.0):
            for temp_c in (0.0, 5.0, 10.0, 15.0, 20.0, 25.0, 30.0):
                eq = native.water_equilibria(temp_c, salinity, 115.0)
                difference = math.log10(native.free_to_total(temp_c, salinity)) - eq.ph_offset
                apart.append(difference)
                low.append(1 - eq.nh3_share(8.0) / eq.nh3_share(8.0 + difference))
        self.assertEqual((round(min(apart), 2), round(max(apart), 2)), (0.10, 0.14))
        self.assertEqual((round(100 * min(low)), round(100 * max(low))), (20, 27))


class PageTests(WaterTestCase):
    def test_the_record_form_and_the_calculator_say_it_beside_the_ph(self):
        for name in ('farm:water_record', 'farm:water_calculator'):
            with self.subTest(page=name):
                page = self.client.get(reverse(name))
                self.assertEqual(page.status_code, 200)
                self.assertContains(page, 'calibrated with NBS/NIST buffers')
                self.assertContains(page, 'typed here as NBS, the NH₃ worked out is 20 to 27 % too low')

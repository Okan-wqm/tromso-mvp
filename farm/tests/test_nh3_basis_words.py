"""What the NH₃ limits' sea-water basis says it is (the water-chemistry audit of 2026-11-19, F5, after its check
against the primary papers, F:\\dev\\balik-notes\\chem-audit-fable\\PAPERS-CHECK-A.md): Khoo, Culberson & Bates
(1977)'s eq. 11 (p. 285), a constant on the free hydrogen ion scale (their eq. 7, p. 283) and molal (Table III, p. 288),
applied to the meter's NBS pH without converting it: the safe side. Not "as Bower & Bidwell 1978": their tables take
Whitfield's (1974) values and never cite Khoo; and no paper says the tables take an NBS pH. Words only: no number
moves."""
from django.utils import translation

from ..water import messages, read
from .test_ph_scale import SeaTestCase


class BasisWordsTests(SeaTestCase):
    def test_a_sea_samples_nh3_says_what_its_basis_is(self):
        self.record(ph_scale='nbs', ph='7.80', temperature_c='4', salinity_ppt='34', tan_mg_l='1')
        said = read.latest([self.sea_point])[self.sea_point.pk].get('nh3_n_mg_l').provenance
        self.assertIn('from 5 ‰ the free-scale pKa of Khoo et al. 1977, eq. 11, applied to the meter’s NBS pH without '
                      'converting it', said)
        self.assertIn('the safe side', said)
        for wrong in ('Bower & Bidwell', 'sea-water tables', 'pKa on the NBS pH'):
            with self.subTest(wrong=wrong):
                self.assertNotIn(wrong, said)

    def test_in_three_languages(self):
        english = str(messages.JUDGED['nh3', 'limits'])
        for language in ('nb', 'tr'):
            with self.subTest(language=language), translation.override(language):
                words = str(messages.JUDGED['nh3', 'limits'])
                self.assertNotEqual(words, english)
                self.assertIn('Khoo', words)
                self.assertNotIn('Bower', words)

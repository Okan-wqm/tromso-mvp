"""The wording and record findings of the water-chemistry audit of 2026-11-19 (F:\\dev\\balik-notes\\chem-audit-fable\\
AUDIT.md): what the pages say about how a value was worked out, put right. No number moves with any of them.

- F6: the activity-corrected NH₃ shown beside the judged one in salt water rests on the application's own NBS
  conversion and reads below the published references in cold sea water: information, not the better value;
- F7: a kit's nitrite (NO₂⁻) is divided by 3.28 (46.0055 / 14.0067 = 3.2845), not 3.29;
- F8: sea water's ionic strength is per kg of water (DOE 1994), not per litre;
- F11: an NH₃ worked out from a pH measured on the total, seawater or free scale is judged on the NBS scale, the safe
  side, and the page says so."""
from decimal import Decimal as D

from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import translation

from ..water import messages, native, parameters, read
from .test_ph_scale import SeaTestCase

# Standard atomic weights (IUPAC; the ones the help's other factors were worked out with).
N, H, O = D('14.0067'), D('1.00794'), D('15.9994')


class KitFactorTests(SimpleTestCase):
    def test_each_kit_factor_is_its_molar_masses_ratio_at_two_decimals(self):
        """F7: the factor a kit's reading as the ion is divided by to give it as N is the ion's molar mass over N's."""
        self.assertEqual((N + 2 * O) / N, D('46.0055') / N)
        for code, ion, said in (('nitrite_n_mg_l', N + 2 * O, 'NO₂⁻'), ('nitrate_n_mg_l', N + 3 * O, 'NO₃⁻'),
                                ('tan_mg_l', N + 4 * H, 'NH₄⁺'), ('tan_mg_l', N + 3 * H, 'NH₃')):
            factor = (ion / N).quantize(D('0.01'))
            with self.subTest(ion=said):
                self.assertIn(f'reads {said}: divide by {factor}', str(parameters.get(code).help))
        self.assertIn('divide by 3.28', str(parameters.get('nitrite_n_mg_l').help))


class SeaWordsTests(SeaTestCase):
    def nh3(self, point):
        return read.latest([point])[point.pk].get('nh3_n_mg_l')

    def test_the_corrected_value_says_what_it_rests_on(self):
        """F6, in a sea sample's NH₃ title; a fresh water's does not say it."""
        self.record(ph_scale='nbs', ph='7.80', temperature_c='4', salinity_ppt='34', tan_mg_l='1')
        said = self.nh3(self.sea_point).provenance
        self.assertIn(str(messages.CORRECTED_SEA), said)
        self.sample(hours=1, tan_mg_l='1', ph='7.5', temperature_c='12', conductivity_25_us_cm='500')
        fresh = self.nh3(self.mid1).provenance
        self.assertIn('NH₃ judged on the basis its limits were set on', fresh)
        self.assertNotIn(str(messages.CORRECTED_SEA), fresh)

    def test_an_nh3_from_a_total_scale_ph_says_it_is_judged_on_the_safe_side(self):
        """F11: the pH was put on the NBS scale and the NH₃ judged on the limits' basis: the safe side,
        said beside the NH₃. A pH typed as NBS says nothing of it."""
        self.record(ph='7.95', temperature_c='12', salinity_ppt='34', tan_mg_l='1')
        nh3 = self.nh3(self.sea_point)
        self.assertIn('The pH was measured on the total scale: the NH₃ is judged on the NBS scale', nh3.provenance)
        self.assertIn('the safe side', nh3.provenance)
        self.record(ph_scale='nbs', ph='8.08', temperature_c='12', salinity_ppt='34', tan_mg_l='1', hours=0)
        self.assertNotIn('The pH was measured on the', self.nh3(self.sea_point).provenance)

    def test_the_words_are_in_three_languages(self):
        for words in (messages.CORRECTED_SEA, messages.JUDGED_ON_NBS):
            english = str(words)
            for language in ('nb', 'tr'):
                with self.subTest(words=english[:30], language=language), translation.override(language):
                    self.assertNotEqual(str(words), english)

    def test_the_calculator_says_the_ionic_strengths_unit(self):
        """F8: per kg of water from a salinity (DOE 1994), per litre from the fresh path's conductivity."""
        water = {'temperature_c': '12', 'ph': '7.8', 'alkalinity_mg_l': '115', 'drawn': '1'}
        sea = self.client.get(reverse('farm:water_calculator'), {**water, 'salinity_ppt': '34'})
        self.assertContains(sea, '0.7014 mol/kg H₂O')
        self.assertNotContains(sea, '0.7014 mol/L')
        fresh = self.client.get(reverse('farm:water_calculator'),
                                {**water, 'salinity_ppt': '0', 'conductivity_25_us_cm': '300'})
        self.assertContains(fresh, '0.0048 mol/L')
        self.assertEqual(messages.ionic_strength_unit(native.water_equilibria(12.0, 34.0)), 'mol/kg H₂O')
        self.assertEqual(messages.ionic_strength_unit(native.water_equilibria(12.0, 0.0, conductivity_25_us_cm=300.0)),
                         'mol/L')

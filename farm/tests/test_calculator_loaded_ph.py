"""The calculator never converts a pH twice (the independent review of 2026-11-16, R2). A pH loaded from a unit is the
unit's stored value: on the NBS scale already, whatever scale it was measured on. The review's water: a sea unit's
sample of total-scale 7.95 at 12 °C and 34 ‰, stored as 8.08. Loaded into the calculator it is 8.08 on the NBS scale;
with the scale then set to "total" on the unchanged value, the calculator took 8.08 for a total-scale pH and worked
with 8.2145: NH₃-N +35 %, CO₂ −29.7 % (the unsafe side), and said nothing. Now the loaded value is carried beside the
pH (`ph_loaded`), the page says what was measured and that the value is NBS, and another scale on the unchanged
loaded value is refused with the reason; a pH typed over it is a new measurement and is converted as any other."""
from decimal import Decimal as D
from urllib.parse import parse_qsl

from django.urls import reverse

from core.models import Profile

from ..models import Tank
from ..water import native, services
from .helpers import point_of
from .test_ph_scale import SeaTestCase
from .test_stock import make_unit

SAID = 'measured 7.95 on the total scale, stored as 8.08 NBS'
REFUSED = ('pH 8.08 is the value loaded from S-01: it is on the NBS scale already (a stored pH always is) and is not '
           'converted again. Leave the scale at NBS, or type the pH as it was measured with its scale.')
WATER = {'temperature_c': '12', 'salinity_ppt': '34', 'alkalinity_mg_l': '115', 'tan_mg_l': '1', 'drawn': '1'}


class LoadedPhTests(SeaTestCase):
    def setUp(self):
        super().setUp()
        self.record(ph='7.95', temperature_c='12', salinity_ppt='34', alkalinity_mg_l='115', tan_mg_l='1.000')
        self.owner = f'tank:{self.sea.pk}'
        self.url = reverse('farm:water_calculator')

    def loaded(self, **more):
        """The calculator's address after the unit was chosen, as the browser sends it on with a field changed."""
        page = self.client.get(self.url, {**WATER, 'ph': '7.50', 'ph_scale': 'total', 'point': self.owner})
        self.assertEqual(page.status_code, 302)
        query = dict(part.split('=', 1) for part in page['Location'].split('?', 1)[1].split('&'))
        from urllib.parse import unquote_plus
        return {**{unquote_plus(name): unquote_plus(value) for name, value in query.items()}, **more}

    def test_a_loaded_ph_is_nbs_and_the_page_says_what_was_measured(self):
        page = self.client.get(self.url, {**WATER, 'ph': '7.50', 'ph_scale': 'total', 'point': self.owner}, follow=True)
        form = page.context['form']
        self.assertEqual((form.cleaned_data['ph'], form.cleaned_data['ph_scale'], form.cleaned_data['ph_loaded']),
                         (D('8.08'), 'nbs', D('8.08')))
        self.assertIsNone(page.context['ph_conversion'])
        self.assertAlmostEqual(page.context['analysis'].water.ph, 8.08, delta=1e-12)
        self.assertAlmostEqual(page.context['analysis'].nh3_n_mg_l, 0.02001, delta=0.00001)
        self.assertContains(page, SAID)
        row = next(row for row in page.context['source']['rows'] if row['offer'].field == 'ph')
        self.assertEqual(str(row['measured']), SAID)
        self.assertFalse(row['changed'])

    def test_another_scale_on_the_unchanged_loaded_value_is_refused_with_the_reason(self):
        for scale in ('total', 'sws', 'free'):
            with self.subTest(scale=scale):
                page = self.client.get(self.url, self.loaded(ph_scale=scale))
                self.assertEqual(page.status_code, 200)
                self.assertEqual(page.context['form'].errors['ph_scale'], [REFUSED])
                self.assertIsNone(page.context['result'])
                self.assertIsNone(page.context['ph_conversion'])
                self.assertContains(page, 'is on the NBS scale already')
                self.assertNotContains(page, '8.21')

    def test_8_08_never_becomes_8_2145(self):
        """Every way the unchanged loaded value can come back with another scale: the address the browser sends, the
        review's own address (without `ph_loaded`), the unit no longer chosen, the live parts and the report."""
        wrong = native.water_equilibria(12.0, 34.0, 115.0).ph_nbs(8.08, 'total')
        self.assertAlmostEqual(wrong, 8.2145, delta=0.0001)
        sent = self.loaded(ph_scale='total')
        review = {**WATER, 'ph': '8.08', 'ph_scale': 'total', 'point': self.owner, 'loaded': self.owner}
        unchosen = {**sent, 'point': ''}
        for name in ('farm:water_calculator', 'farm:water_calculator_results', 'farm:water_calculator_report'):
            for label, query in (('sent', sent), ('review', review), ('unchosen', unchosen)):
                with self.subTest(page=name, query=label):
                    page = self.client.get(reverse(name), query)
                    self.assertEqual(page.status_code, 200)
                    self.assertIn('ph_scale', page.context['form'].errors)
                    self.assertIsNone(page.context['result'])
                    self.assertIsNone(page.context['analysis'])
                    self.assertIsNone(page.context['ph_conversion'])

    def test_left_at_nbs_the_loaded_value_is_worked_out_as_it_is(self):
        page = self.client.get(self.url, self.loaded())
        self.assertEqual(page.context['form'].errors, {})
        self.assertAlmostEqual(page.context['analysis'].water.ph, 8.08, delta=1e-12)

    def test_a_ph_typed_over_the_loaded_one_is_a_measurement_and_is_converted(self):
        page = self.client.get(self.url, self.loaded(ph='7.95', ph_scale='total'))
        self.assertEqual(page.context['form'].errors, {})
        self.assertAlmostEqual(page.context['analysis'].water.ph,
                               native.water_equilibria(12.0, 34.0, 115.0).ph_nbs(7.95, 'total'), delta=1e-12)
        self.assertEqual(page.context['ph_conversion']['code'], 'total')
        row = next(row for row in page.context['source']['rows'] if row['offer'].field == 'ph')
        self.assertTrue(row['changed'])

    def test_a_typed_ph_without_a_unit_is_converted_as_before(self):
        page = self.client.get(self.url, {**WATER, 'ph': '8.08', 'ph_scale': 'total'})
        self.assertEqual(page.context['form'].errors, {})
        self.assertAlmostEqual(page.context['analysis'].water.ph, 8.2145, delta=0.0001)

    def test_a_unit_without_a_ph_loads_none_and_carries_none(self):
        page = self.client.get(self.url, {**WATER, 'ph': '8.08', 'ph_scale': 'total', 'point': f'tank:{self.t1.pk}'},
                               follow=True)
        form = page.context['form']
        self.assertIsNone(form.cleaned_data['ph_loaded'])
        self.assertEqual((form.cleaned_data['ph'], form.cleaned_data['ph_scale']), (D('8.08'), 'total'))

    def test_an_nbs_sample_loads_without_the_words(self):
        self.record(ph='7.80', ph_scale='nbs', temperature_c='12', salinity_ppt='34', alkalinity_mg_l='115', hours=0)
        page = self.client.get(self.url, {'point': self.owner}, follow=True)
        self.assertEqual(page.context['form'].cleaned_data['ph_loaded'], D('7.80'))
        self.assertNotContains(page, 'stored as')
        refused = self.client.get(self.url, self.loaded(ph_scale='total'))
        self.assertIn('pH 7.80 is the value loaded from S-01', refused.context['form'].errors['ph_scale'][0])

    def test_in_three_languages(self):
        for language, said, refused in (('nb', 'lagret som 8,08 NBS', 'er allerede på NBS-skalaen'),
                                        ('tr', '8,08 NBS olarak saklandı', 'zaten NBS ölçeğinde')):
            with self.subTest(language=language):
                Profile.objects.update_or_create(user=self.user, defaults={'language': language})
                sent = self.loaded()
                self.assertEqual(sent['ph_loaded'], '8,08')
                self.assertContains(self.client.get(self.url, sent), said)
                page = self.client.get(self.url, {**sent, 'ph_scale': 'total'})
                self.assertIn(refused, page.context['form'].errors['ph_scale'][0])
                self.assertIsNone(page.context['result'])


VIEWS = ('farm:water_calculator', 'farm:water_calculator_results', 'farm:water_calculator_report')
UNSAID = 'this address does not say it was typed'


class ChangedUnitTests(SeaTestCase):
    """The rule never depends on what the page happened to send (the verification of 2026-11-18, V-B). A value is typed
    only when the form says so (the value carried beside it differs, or nothing gave the field a value); otherwise it
    is the loaded, already converted one. "Values from" changed to a unit WITHOUT a pH left the stored 8.08 of S-01 in
    the field with an empty `ph_loaded`, and "total" on it was converted to 8.2145 (NH₃-N +35 %, CO₂ −29.7 %); an
    address without `ph_loaded` after a newer sample on the unit likewise; and the phosphate the same (5.01 from 15.35
    as PO₄ became 1.63)."""

    def setUp(self):
        super().setUp()
        self.other = make_unit('S-03', self.hall)                  # a sea unit with a temperature only
        Tank.objects.filter(pk=self.other.pk).update(water_type='saltwater', water_origin='seawater')
        self.other.refresh_from_db()
        self.record(point=point_of(self.other), ph_scale='nbs', temperature_c='12.0', hours=2)
        self.a, self.b = f'tank:{self.sea.pk}', f'tank:{self.other.pk}'
        self.url = reverse('farm:water_calculator')

    def load(self, query):
        """The address the calculator redirects to when a unit was just chosen."""
        page = self.client.get(self.url, query)
        self.assertEqual(page.status_code, 302)
        return dict(parse_qsl(page['Location'].split('?', 1)[1], keep_blank_values=True))

    def not_converted(self, query, field, said):
        for name in VIEWS:
            with self.subTest(view=name):
                page = self.client.get(reverse(name), query)
                self.assertEqual(page.status_code, 200)
                self.assertIn(said, page.context['form'].errors[field][0])
                self.assertIsNone(page.context['analysis'])
                self.assertIsNone(page.context['result'])
                self.assertIsNone(page.context['ph_conversion'])
                self.assertNotContains(page, '8.21')

    def ph(self):
        self.record(ph='7.95', temperature_c='12', salinity_ppt='34', alkalinity_mg_l='115', tan_mg_l='1.000')
        return self.load({**WATER, 'ph': '7.50', 'point': self.a})

    def test_the_loaded_ph_stays_loaded_when_the_unit_is_changed_to_one_without_a_ph(self):
        moved = self.load({**self.ph(), 'point': self.b})
        self.assertEqual((moved['ph'], moved['ph_scale'], moved['ph_loaded'], moved['loaded']),
                         ('8.08', 'nbs', '8.08', self.b))
        page = self.client.get(self.url, moved)                        # as it arrives: NBS, nothing converted
        self.assertEqual(page.context['form'].errors, {})
        self.assertAlmostEqual(page.context['analysis'].water.ph, 8.08, delta=1e-12)
        for scale in ('total', 'sws', 'free'):
            self.not_converted({**moved, 'ph_scale': scale}, 'ph_scale',
                               'pH 8.08 is the value loaded from a unit or a loop')

    def test_a_ph_typed_at_the_unit_without_one_is_converted_as_any_other(self):
        moved = self.load({**self.ph(), 'point': self.b})
        page = self.client.get(self.url, {**moved, 'ph': '7.95', 'ph_scale': 'total'})
        self.assertEqual(page.context['form'].errors, {})
        self.assertAlmostEqual(page.context['analysis'].water.ph, native.water_equilibria(12.0, 34.0, 115.0).ph_nbs(
            7.95, 'total'), delta=1e-9)

    def test_a_ph_typed_with_its_scale_before_the_unit_was_chosen_keeps_its_scale(self):
        moved = self.load({**WATER, 'ph': '7.95', 'ph_scale': 'total', 'point': self.b})
        self.assertEqual((moved['ph'], moved['ph_scale'], moved['ph_loaded']), ('7.95', 'total', ''))
        page = self.client.get(self.url, moved)
        self.assertEqual(page.context['form'].errors, {})
        self.assertEqual(page.context['ph_conversion']['code'], 'total')

    def test_a_typed_ph_stays_typed_when_the_unit_is_changed_to_one_without_a_ph(self):
        """Typed over the loaded value of S-01 (the carried one differs), then S-03 chosen: still a measurement."""
        moved = self.load({**self.ph(), 'ph': '7.95', 'ph_scale': 'total', 'point': self.b})
        self.assertEqual((moved['ph'], moved['ph_scale'], moved['ph_loaded']), ('7.95', 'total', ''))
        self.assertEqual(self.client.get(self.url, moved).context['ph_conversion']['code'], 'total')

    def test_an_address_without_ph_loaded_after_a_newer_sample_is_not_converted(self):
        sent = self.ph()
        self.record(ph='8.10', ph_scale='nbs', temperature_c='12', salinity_ppt='34', hours=0)
        old_link = {name: value for name, value in {**sent, 'ph_scale': 'total'}.items() if name != 'ph_loaded'}
        self.not_converted(old_link, 'ph_scale', UNSAID)
        self.not_converted({**old_link, 'ph_loaded': ''}, 'ph_scale', UNSAID)
        self.not_converted({**sent, 'ph_scale': 'total'}, 'ph_scale', 'pH 8.08 is the value loaded from S-01')

    def phosphate(self):
        services.record(self.user, point=self.sea_point, measured_at=self.ago(hours=1), source='manual',
                        values={'ph': D('7.80'), 'temperature_c': D('12.0'), 'salinity_ppt': D('34.0'),
                                'alkalinity_mg_l': D('115'), 'phosphate_p_mg_l': D('15.35')}, phosphate_unit='po4')
        return self.load({**WATER, 'ph': '7.50', 'point': self.a})

    def test_the_loaded_phosphate_stays_loaded_when_the_unit_is_changed_to_one_without_it(self):
        moved = self.load({**self.phosphate(), 'point': self.b})
        self.assertEqual((moved['phosphate_p_mg_l'], moved['phosphate_unit'], moved['phosphate_loaded']),
                         ('5.01', 'p', '5.01'))
        self.not_converted({**moved, 'phosphate_unit': 'po4'}, 'phosphate_unit',
                           'Phosphate 5.01 is the value loaded from a unit or a loop')
        page = self.client.get(self.url, moved)
        self.assertAlmostEqual(page.context['analysis'].equilibria.phosphate * 1000, 0.16175, delta=0.00001)

    def test_an_address_without_phosphate_loaded_after_a_newer_sample_is_not_converted(self):
        sent = self.phosphate()
        self.record(ph_scale='nbs', phosphate_p_mg_l='5.50', hours=0)
        old_link = {name: value for name, value in {**sent, 'phosphate_unit': 'po4'}.items()
                    if name != 'phosphate_loaded'}
        self.not_converted(old_link, 'phosphate_unit', UNSAID)

    def test_the_unsaid_refusal_in_norwegian_and_turkish(self):
        self.ph()
        self.record(ph='8.10', ph_scale='nbs', temperature_c='12', salinity_ppt='34', hours=0)
        for language, said in (('nb', 'sier ikke at den ble skrevet inn'), ('tr', 'elle yazıldığını söylemiyor')):
            with self.subTest(language=language):
                Profile.objects.update_or_create(user=self.user, defaults={'language': language})
                page = self.client.get(self.url, {'temperature_c': '12', 'salinity_ppt': '34', 'alkalinity_mg_l': '115',
                                                  'tan_mg_l': '1', 'drawn': '1', 'ph': '8,08', 'ph_scale': 'total',
                                                  'point': self.a, 'loaded': self.a})
                self.assertIn(said, page.context['form'].errors['ph_scale'][0])

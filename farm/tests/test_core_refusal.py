"""A water the core refuses to work out is said in words at every door, never a server error (the independent review of
2026-11-16, R1). The review's water: a fresh unit's sample of 12.0 °C, S 0.0, alkalinity 80, pH 7.20, TAN 1.000 and a
conductivity of 40 000 µS/cm (inside the parameter's range, so it is stored): its ionic strength is past the Davies
equation's range (0.5), and the core refuses it. The water page and the history said so already (read._ammonia); the
unit's chart, the calculator with the values typed and the calculator loaded from the unit raised. One gate answers for
all of them: deffeyes.why_impossible, which every door asks before it works a water out, gives the core's refusal as
its reason (deffeyes.unworkable), so a water with no reason there is never refused behind it."""
from decimal import Decimal as D

from django.test import SimpleTestCase
from django.urls import reverse

from ..models import Tank
from ..water import calculation, deffeyes, native, services
from .test_water import WaterTestCase

WHY = ('Cannot be worked out: ionic strength above 0.5: outside the range of the Davies equation (a conductivity in '
       'mS/cm, or a sea water without its salinity?).')
WATER = {'temperature_c': '12', 'salinity_ppt': '0', 'alkalinity_mg_l': '80', 'ph': '7.2', 'tan_mg_l': '1',
         'conductivity_25_us_cm': '40000', 'drawn': '1'}


class GateTests(SimpleTestCase):
    def test_the_core_refuses_the_water(self):
        with self.assertRaises(ValueError):
            native.water_equilibria(12.0, 0.0, 80.0, 40000.0)

    def test_the_gate_says_the_cores_reason(self):
        self.assertEqual(deffeyes.unworkable(12.0, 0.0, 80.0, conductivity_25_us_cm=40000.0), WHY)
        self.assertEqual(deffeyes.why_impossible(12.0, 0.0, 7.2, 80.0, conductivity_25_us_cm=40000.0), WHY)
        self.assertFalse(deffeyes.possible(12.0, 0.0, 7.2, 80.0, conductivity_25_us_cm=40000.0))

    def test_on_both_sides_of_the_range(self):
        """The review's thresholds: 31 250 µS/cm with the origin not said (1.6e-5 per µS/cm), 59 524 salt-added."""
        for origin, last, first in (('', 31250.0, 31251.0), ('salt_added', 59523.0, 59525.0)):
            with self.subTest(origin=origin):
                self.assertEqual(deffeyes.unworkable(12.0, 0.0, 80.0, conductivity_25_us_cm=last, water_origin=origin), '')
                self.assertEqual(deffeyes.unworkable(12.0, 0.0, 80.0, conductivity_25_us_cm=first, water_origin=origin),
                                 WHY)

    def test_a_water_that_can_be_worked_out_has_no_reason_and_the_floor_is_said_as_before(self):
        self.assertEqual(deffeyes.unworkable(12.0, 0.0, 80.0), '')
        self.assertEqual(deffeyes.why_impossible(12.0, 0.0, 7.2, 80.0), '')
        self.assertIn('At this pH the alkalinity is above', deffeyes.why_impossible(10.0, 0.0, 12.4, 100.0))

    def test_a_value_that_is_no_number_is_a_reason_too(self):
        self.assertIn('Cannot be worked out: ', deffeyes.why_impossible(float('nan'), 0.0, 7.2, 80.0))
        self.assertIn('Cannot be worked out: ', deffeyes.why_impossible(12.0, -1.0, 7.2, 80.0))


class DoorTests(WaterTestCase):
    def setUp(self):
        super().setUp()
        self.stored = services.record(
            self.user, point=self.mid1, measured_at=self.ago(hours=1), source='manual',
            values={'ph': D('7.20'), 'temperature_c': D('12.0'), 'salinity_ppt': D('0.0'), 'alkalinity_mg_l': D('80'),
                    'tan_mg_l': D('1.000'), 'conductivity_25_us_cm': D('40000')})

    def test_the_sample_is_stored(self):
        self.assertEqual(self.stored.conductivity_25_us_cm, D('40000'))

    def test_the_units_chart_is_refused_with_the_reason(self):
        found = calculation.chart_of(Tank.objects.get(pk=self.t1.pk))
        self.assertIsInstance(found, calculation.Refusal)
        self.assertEqual(found.impossible, WHY)
        self.assertEqual(found.missing, [])

    def test_the_units_chart_page_says_why_there_is_no_chart(self):
        page = self.client.get(reverse('farm:water_unit_chart', args=[self.t1.pk]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'Cannot be worked out: ionic strength above 0.5')
        self.assertIsNone(page.context['chart'])
        page = self.client.get(reverse('farm:water_system_chart', args=[self.ras.pk]))
        self.assertEqual(page.status_code, 200)

    def test_the_calculator_with_the_values_typed_says_why_there_is_no_result(self):
        for name in ('farm:water_calculator', 'farm:water_calculator_results', 'farm:water_calculator_report'):
            with self.subTest(page=name):
                page = self.client.get(reverse(name), WATER)
                self.assertEqual(page.status_code, 200)
                self.assertIsNone(page.context['result'])
                self.assertEqual(page.context['form'].non_field_errors(), [WHY])
        self.assertContains(self.client.get(reverse('farm:water_calculator'), WATER),
                            'Cannot be worked out: ionic strength above 0.5')

    def test_the_calculator_with_another_ph_scale_says_it_too(self):
        page = self.client.get(reverse('farm:water_calculator'), {**WATER, 'ph_scale': 'total'})
        self.assertEqual(page.status_code, 200)
        self.assertIsNone(page.context['result'])
        self.assertEqual(page.context['form'].non_field_errors(), [WHY])

    def test_the_calculator_loaded_from_the_unit_says_why_there_is_no_result(self):
        page = self.client.get(reverse('farm:water_calculator'), {'point': f'tank:{self.t1.pk}'}, follow=True)
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.context['form'].cleaned_data['conductivity_25_us_cm'], D('40000'))
        self.assertIsNone(page.context['result'])
        self.assertEqual(page.context['form'].non_field_errors(), [WHY])
        self.assertContains(page, 'Cannot be worked out: ionic strength above 0.5')

    def test_the_water_page_and_the_history_say_it_as_before(self):
        for query in ({'unit': self.t1.pk}, {'unit': self.t1.pk, 'view': 'history'}):
            with self.subTest(query=query):
                page = self.client.get(reverse('farm:water'), query)
                self.assertEqual(page.status_code, 200)
                self.assertContains(page, 'Cannot be worked out: ionic strength above 0.5')

    def test_in_three_languages(self):
        from core.models import Profile
        for language, words in (('nb', 'Kan ikke regnes ut: '), ('tr', 'Hesaplanamıyor: ')):
            with self.subTest(language=language):
                Profile.objects.update_or_create(user=self.user, defaults={'language': language})
                self.assertContains(self.client.get(reverse('farm:water_unit_chart', args=[self.t1.pk])), words)
                self.assertContains(self.client.get(reverse('farm:water_calculator'),
                                                    {**WATER, 'ph': '7,2'}), words)

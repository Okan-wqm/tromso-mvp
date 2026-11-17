"""Fresh water with salt added never takes a pH on a seawater scale, at any salinity (the independent review of
2026-11-16, R4). The total, the seawater and the free scale are defined by sea water's sulfate and fluoride; water
salted with NaCl has neither. Inside the Davies range (to about 28.4 ‰ as NaCl) it was refused already; past it the
core works such a water out by the sea path, for want of another, and took that for sea water: a salt-added unit's
total-scale 7.95 at 12 °C was stored as 8.09 at S 29 and 30 and as 8.08 at S 35 (the core: S 30, total 8.00 -> 8.1372),
against the module's own rule and the words of its refusal. Now the core's one rule (chemcore/core/src/scale.rs
`converts`) refuses it by its origin, so the sample, the round and the calculator all say the reason."""
from django.test import SimpleTestCase
from django.urls import reverse

from ..models import WaterMeasurement
from ..water import native
from .test_ph_scale import NOT_SEA, SeaTestCase

SALINITIES = ('5', '20', '28', '29', '30', '35', '40')


class CoreTests(SimpleTestCase):
    def test_the_core_refuses_it_at_every_salinity_both_ways(self):
        for salinity in SALINITIES:
            eq = native.water_equilibria(12.0, float(salinity), 80.0, water_origin='salt_added')
            for scale in ('total', 'sws', 'free'):
                with self.subTest(salinity=salinity, scale=scale):
                    self.assertFalse(eq.takes_ph_scale(scale))
                    with self.assertRaises(native.SeawaterScaleError):
                        eq.ph_nbs(8.0, scale)
                    with self.assertRaises(native.SeawaterScaleError):
                        eq.ph_on(8.0, scale)
            self.assertTrue(eq.takes_ph_scale('nbs'))
            self.assertEqual(eq.ph_nbs(8.0, 'nbs'), 8.0)

    def test_the_reviews_water_is_one_the_sea_path_works_out(self):
        """S 30 salt-added is past the Davies limit: its constants are the sea path's (sea_weight 1), which is why the
        rule must ask the origin."""
        eq = native.water_equilibria(12.0, 30.0, 80.0, water_origin='salt_added')
        self.assertEqual((eq.sea_weight, eq.water_origin), (1.0, 'salt_added'))
        self.assertEqual(native.water_equilibria(12.0, 20.0, 80.0, water_origin='salt_added').sea_weight, 0.0)

    def test_sea_water_is_converted_as_before(self):
        for origin in ('', 'seawater'):
            for salinity in (29.0, 30.0, 35.0):
                eq = native.water_equilibria(12.0, salinity, 80.0, water_origin=origin)
                self.assertTrue(eq.takes_ph_scale('total'))
        self.assertAlmostEqual(native.water_equilibria(12.0, 30.0, 80.0).ph_nbs(8.0, 'total'), 8.1372, delta=0.0001)


class DoorTests(SeaTestCase):
    def test_a_salt_added_units_sample_is_refused_at_every_salinity(self):
        for hours, salinity in enumerate(SALINITIES, start=1):
            for scale in ('total', 'sws', 'free'):
                with self.subTest(salinity=salinity, scale=scale):
                    self.assertEqual(self.refused(point=self.salted_point, ph='7.95', ph_scale=scale, temperature_c='12',
                                                  salinity_ppt=salinity, hours=hours), {'ph_scale': [NOT_SEA]})
        self.assertEqual(WaterMeasurement.objects.count(), 0)

    def test_its_nbs_ph_is_stored_as_it_is(self):
        sample = self.record(point=self.salted_point, ph='7.95', ph_scale='nbs', temperature_c='12', salinity_ppt='30')
        self.assertEqual((str(sample.ph), sample.ph_scale, sample.ph_as_measured), ('7.95', '', None))

    def test_the_sea_unit_beside_it_is_converted_as_before(self):
        for hours, (salinity, stored) in enumerate((('29', '8.09'), ('30', '8.09'), ('35', '8.08')), start=1):
            sample = self.record(ph='7.95', temperature_c='12', salinity_ppt=salinity, hours=hours)
            self.assertEqual((str(sample.ph), sample.ph_scale), (stored, 'total'))

    def test_the_calculator_refuses_it_with_the_reason(self):
        water = {'temperature_c': '12', 'alkalinity_mg_l': '115', 'tan_mg_l': '1', 'drawn': '1', 'ph': '7.95',
                 'water_origin': 'salt_added'}
        for salinity in SALINITIES:
            with self.subTest(salinity=salinity):
                page = self.client.get(reverse('farm:water_calculator'),
                                       {**water, 'salinity_ppt': salinity, 'ph_scale': 'total'})
                self.assertEqual(page.status_code, 200)
                self.assertEqual(page.context['form'].errors['ph_scale'], [NOT_SEA])
                self.assertIsNone(page.context['result'])
                plain = self.client.get(reverse('farm:water_calculator'), {**water, 'salinity_ppt': salinity})
                self.assertEqual(plain.context['form'].errors, {})
                self.assertAlmostEqual(plain.context['analysis'].water.ph, 7.95, delta=1e-12)

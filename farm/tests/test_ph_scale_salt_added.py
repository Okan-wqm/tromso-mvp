"""Fresh water with salt added never takes a pH on a seawater scale, at any salinity (the independent review of
2026-11-16, R4). The total, the seawater and the free scale are defined by sea water's sulfate and fluoride; water
salted with NaCl has neither. Inside the Davies range (to about 28.4 ‰ as NaCl) it was refused already; past it the
core works such a water out by the sea path, for want of another, and took that for sea water: a salt-added unit's
total-scale 7.95 at 12 °C was stored as 8.09 at S 29 and 30 and as 8.08 at S 35 (the core: S 30, total 8.00 -> 8.1372),
against the module's own rule and the words of its refusal. Now the core's one rule (chemcore/core/src/scale.rs
`converts`) refuses it by its origin, so the sample, the round and the calculator all say the reason."""
import uuid
from types import SimpleNamespace
from urllib.parse import parse_qsl

from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import timezone

from ..models import System, Tank, WaterMeasurement
from ..water import calculation, native, read
from .helpers import point_of
from .test_ph_scale import NOT_SEA, SeaTestCase
from .test_stock import make_unit

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


class MixedLoopTests(SeaTestCase):
    """A loop whose units do not all say the same origin (the verification of 2026-11-18, V-C): a salt-added unit in it
    makes its water salt-added (the refusing side), never "not said" (the converting side). The verifier's loop of B-01
    (salt added) and B-02 (not said, a new unit's default) stored a total-scale 7.95 as 8.09 at S 29 and 30 and as
    8.08 at S 35 at its loop point, while the own point of B-01 refused. Decided in one place beside the origin of a
    point's water (read.scale_origin), so the sample door, the round and the calculator loaded from the loop all
    follow. The constants of the loop's water stay read.common_origin's ("not said" where the units differ, cross
    review F3: farm/tests/test_water_origin.py), so no worked-out number moves."""

    def setUp(self):
        super().setUp()
        self.mixed = System.objects.create(name='RAS 2', code='R2', site=self.bergen, production_department=self.hall)
        self.b1 = make_unit('B-01', self.hall, system=self.mixed)
        self.b2 = make_unit('B-02', self.hall, system=self.mixed)
        Tank.objects.filter(pk=self.b1.pk).update(water_type='brackish', water_origin='salt_added')
        Tank.objects.filter(pk=self.b2.pk).update(water_type='brackish')
        self.b1.refresh_from_db()
        self.b2.refresh_from_db()
        self.loop_point = point_of(self.mixed)

    def test_the_origin_of_units_that_do_not_agree(self):
        unit = lambda origin: SimpleNamespace(water_origin=origin)      # noqa: E731
        for origins, wanted in ((('salt_added', ''), 'salt_added'), (('', 'salt_added'), 'salt_added'),
                                (('salt_added', 'seawater'), 'salt_added'), (('salt_added', 'salt_added'), 'salt_added'),
                                (('seawater', ''), ''), (('seawater', 'seawater'), 'seawater'), (('', ''), ''),
                                ((), '')):
            with self.subTest(origins=origins):
                self.assertEqual(read.scale_origin([unit(origin) for origin in origins]), wanted)
        for owner in (self.mixed, self.loop_point):
            self.assertEqual((calculation.scale_origin_of(owner), calculation.origin_of(owner)), ('salt_added', ''))
        self.assertEqual((calculation.scale_origin_of(self.b1), calculation.scale_origin_of(self.b2)),
                         ('salt_added', ''))
        self.assertEqual(calculation.scale_origin_of(self.sea), 'seawater')

    def test_the_loops_sample_is_refused_at_every_salinity(self):
        for hours, salinity in enumerate(SALINITIES, start=1):
            for scale in ('total', 'sws', 'free'):
                with self.subTest(salinity=salinity, scale=scale):
                    self.assertEqual(self.refused(point=self.loop_point, ph='7.95', ph_scale=scale, temperature_c='12',
                                                  salinity_ppt=salinity, hours=hours), {'ph_scale': [NOT_SEA]})
        self.assertEqual(WaterMeasurement.objects.count(), 0)
        sample = self.record(point=self.loop_point, ph='7.95', ph_scale='nbs', temperature_c='12', salinity_ppt='30')
        self.assertEqual((str(sample.ph), sample.ph_scale), ('7.95', ''))

    def test_the_round_refuses_the_loops_row_and_stores_nothing(self):
        url = f'{reverse("farm:water_round")}?site={self.bergen.pk}&columns=temperature_c&columns=ph&columns=salinity_ppt'
        page = self.client.get(url)
        points = [row.point for row in page.context['rows']]
        self.assertIn(self.loop_point, points)
        local = timezone.localtime(self.ago(hours=1)).strftime('%Y-%m-%dT%H:%M')
        data = {'token': str(uuid.uuid4()), 'measured_at': local, 'source': 'manual', 'ph_scale': 'total'}
        for point in points:
            for code in ('temperature_c', 'ph', 'salinity_ppt'):
                data[f'point-{point.pk}-{code}'] = ''
        for point in (self.sea_point, self.loop_point):
            data.update({f'point-{point.pk}-ph': '7.95', f'point-{point.pk}-temperature_c': '12',
                         f'point-{point.pk}-salinity_ppt': '30'})
        response = self.client.post(url, data, headers={'X-Modal': '1'})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(WaterMeasurement.objects.count(), 0)
        errors = {row.point: dict(row.errors) for row in response.context['rows'] if row.errors}
        self.assertEqual(list(errors), [self.loop_point])
        self.assertIn(NOT_SEA, str(errors[self.loop_point]))

    def test_the_calculator_loaded_from_the_loop_refuses_the_scale(self):
        self.record(point=self.loop_point, ph='7.80', ph_scale='nbs', temperature_c='12', salinity_ppt='30')
        url = reverse('farm:water_calculator')
        page = self.client.get(url, {'point': f'system:{self.mixed.pk}'}, follow=True)
        self.assertEqual(page.context['form'].cleaned_data['water_origin'], '')       # the constants': not said
        sent = dict(parse_qsl(page.redirect_chain[-1][0].split('?', 1)[1], keep_blank_values=True))
        for name in ('farm:water_calculator', 'farm:water_calculator_results', 'farm:water_calculator_report'):
            for salinity in ('29', '30', '35'):
                with self.subTest(view=name, salinity=salinity):
                    typed = self.client.get(reverse(name),
                                            {**sent, 'ph': '7.95', 'ph_scale': 'total', 'salinity_ppt': salinity})
                    self.assertEqual(typed.context['form'].errors['ph_scale'], [NOT_SEA])
                    self.assertIsNone(typed.context['result'])
                    self.assertIsNone(typed.context['ph_conversion'])
        # Typed on the NBS scale it is worked out as before; an origin said on the form stands, as for any water.
        plain = self.client.get(url, {**sent, 'ph': '7.95', 'salinity_ppt': '30'})
        self.assertEqual(plain.context['form'].errors, {})
        said = self.client.get(url, {**sent, 'ph': '7.95', 'ph_scale': 'total', 'salinity_ppt': '30',
                                     'water_origin': 'seawater'})
        self.assertEqual(said.context['ph_conversion']['code'], 'total')

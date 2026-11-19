"""A water's origin: sea-water-derived or salt-added fresh water (cross review F3 and F4).

Formula 3's band (1 to 5 permil) blends in the seawater constants, which carry sea water's ions: sulfate and fluoride on
the pH scales, magnesium and calcium ion pairs in Millero's K1 and K2, borate. A fresh RAS salted with NaCl to a few
permil (smolt, disease control) has none of them, and the band would put its CO2 6 to 10 % low. So a unit may say where
its salt came from: salt-added fresh water takes the fresh (Davies) path up to the Davies limit, its ionic strength
from NaCl (the salinity as NaCl's molality, the conductivity by NaCl's factor, about 8.4e-6 per µS/cm instead of
Russell's 1.6e-5, which fits bicarbonate waters and overstates a NaCl water's ionic strength about 1.9 times), and no
seawater boron. Unsaid, the band stays and its provenance says what it assumes."""
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from django.urls import reverse

from ..models import Tank
from ..water import chemistry, deffeyes, messages, native, read
from .helpers import role
from .test_water import WaterTestCase

NACL = 58.443                       # g/mol (IUPAC 2007: Na 22.98977, Cl 35.453)


class OriginTests(SimpleTestCase):
    def test_salt_added_water_takes_the_fresh_path_with_nacls_ionic_strength(self):
        eq = native.water_equilibria(12.0, 3.0, 80.0, water_origin='salt_added')
        self.assertEqual((eq.sea_weight, eq.water_origin, eq.strength_source), (0.0, 'salt_added', 'salinity'))
        self.assertAlmostEqual(eq.ionic_strength, 3.0 / NACL / (1 - 0.003), delta=1e-12)     # NaCl's molality
        self.assertEqual(eq.boron, 0.0)                                                       # no seawater boron
        strength = eq.ionic_strength
        self.assertEqual(eq.ph_offset, native.davies_log_gamma(12.0, strength, 1))

    def test_salt_added_water_holds_more_co2_than_the_band_gives_it(self):
        """The cross review's measure: at 3 permil the fresh path gives 4.6 to 9.2 % more CO2 than the sea path."""
        meq = 80.0 / chemistry.MG_CACO3_PER_MEQ
        for temp_c in (2.0, 10.0, 25.0):
            salted = native.water_equilibria(temp_c, 3.0, 80.0, water_origin='salt_added')
            banded = native.water_equilibria(temp_c, 3.0, 80.0)
            with self.subTest(temp_c=temp_c):
                self.assertGreater(salted.co2(salted.dic(meq, 7.0), 7.0), banded.co2(banded.dic(meq, 7.0), 7.0))

    def test_the_conductivity_of_a_salt_added_water_is_read_by_nacls_factor(self):
        """F4: 0.01 mol/L NaCl conducts about 1185 µS/cm at 25 °C (molar conductivity 118.5 S cm²/mol): I / κ = 8.4e-6;
        Russell's 1.6e-5 (bicarbonate waters) stays for any other water."""
        self.assertEqual(native.IONIC_PER_MICROSIEMENS, 1.6e-5)
        self.assertEqual(native.IONIC_PER_MICROSIEMENS_NACL, 8.4e-6)
        self.assertEqual(native.fresh_ionic_strength(0.0, None, conductivity_25_us_cm=3000.0),
                         (1.6e-5 * 3000.0, 'conductivity'))
        self.assertEqual(native.fresh_ionic_strength(0.0, None, conductivity_25_us_cm=3000.0, water_origin='salt_added'),
                         (8.4e-6 * 3000.0, 'conductivity'))
        eq = native.water_equilibria(12.0, 2.0, 80.0, conductivity_25_us_cm=5000.0, water_origin='salt_added')
        self.assertEqual((eq.ionic_strength, eq.sea_weight), (8.4e-6 * 5000.0, 0.0))

    def test_up_to_the_davies_limit_then_the_sea_path(self):
        self.assertEqual(native.water_equilibria(12.0, 20.0, 80.0, water_origin='salt_added').sea_weight, 0.0)
        beyond = native.water_equilibria(12.0, 35.0, 80.0, water_origin='salt_added')      # NaCl I 0.62 > 0.5
        self.assertEqual((beyond.sea_weight, beyond.strength_source), (1.0, 'seawater'))

    def test_seawater_derived_and_unsaid_keep_the_band(self):
        for origin in ('', 'seawater'):
            with self.subTest(origin=origin):
                eq = native.water_equilibria(12.0, 3.0, 80.0, water_origin=origin)
                self.assertEqual(eq.sea_weight, 0.5)
                self.assertEqual(eq.values(), native.water_equilibria(12.0, 3.0, 80.0).values())
        with self.assertRaises(ValueError):
            native.water_equilibria(12.0, 3.0, 80.0, water_origin='rain')

    def test_the_provenance_says_what_the_band_assumes(self):
        """F3: in the band, unsaid, the provenance says it assumes sea water's ions; said, it says the origin."""
        unsaid = messages.provenance(native.water_equilibria(12.0, 3.0, 80.0))
        self.assertIn('assumes sea water’s ion composition; salt-added fresh water may read low CO₂', unsaid)
        sea = messages.provenance(native.water_equilibria(12.0, 3.0, 80.0, water_origin='seawater'))
        self.assertNotIn('assumes', sea)
        salted = messages.provenance(native.water_equilibria(12.0, 3.0, 80.0, water_origin='salt_added'))
        self.assertIn('salt-added fresh water', salted)
        self.assertNotIn('assumes', messages.provenance(native.water_equilibria(12.0, 0.0, 80.0)))

    def test_the_analysis_and_the_judging_take_the_origin(self):
        water = deffeyes.Water(12.0, 3.0, 7.5, 80.0, tan_mg_l=0.5, water_origin='salt_added')
        found = deffeyes.analyse(water, deffeyes.Limits(nh3_n_mg_l=0.0103, co2_mg_l=15.0))
        self.assertEqual(found.equilibria.water_origin, 'salt_added')
        # Judged on the larger: the ideal water (no seawater boron) against the corrected.
        ideal = native.water_equilibria(12.0, 0.0)
        self.assertGreaterEqual(found.equilibria.nh3_share(7.5), ideal.nh3_share(7.5))
        self.assertEqual(found.nh3_basis, 'limits')
        self.assertEqual(native.alkalinity_floor(12.0, 3.0, 10.5, 80.0, water_origin='salt_added'),
                         found.equilibria.isoline(10.5)[1] * chemistry.MG_CACO3_PER_MEQ)


class UnitOriginTests(WaterTestCase):
    def test_a_unit_says_its_water_origin(self):
        field = Tank._meta.get_field('water_origin')
        self.assertEqual([value for value, _label in field.choices], ['seawater', 'salt_added'])
        self.assertTrue(field.blank)
        self.assertEqual(self.t1.water_origin, '')

    def test_a_salt_added_units_ammonia_takes_the_fresh_path(self):
        Tank.objects.filter(pk__in=[self.t1.pk, self.t2.pk]).update(water_origin='salt_added')
        self.sample(hours=2, tan_mg_l='2', ph='7.5', temperature_c='12', salinity_ppt='3', alkalinity_mg_l='80')
        nh3 = read.latest([self.mid1])[self.mid1.pk].get('nh3_n_mg_l')
        self.assertIn('salt-added fresh water', nh3.provenance)
        self.assertNotIn('% seawater constants', nh3.provenance)

    def test_a_unit_without_an_origin_keeps_the_band_and_says_so(self):
        self.sample(hours=2, tan_mg_l='2', ph='7.5', temperature_c='12', salinity_ppt='3', alkalinity_mg_l='80')
        nh3 = read.latest([self.mid1])[self.mid1.pk].get('nh3_n_mg_l')
        self.assertIn('50 % seawater constants', nh3.provenance)
        self.assertIn('assumes sea water’s ion composition', nh3.provenance)

    def test_a_loop_of_units_with_different_origins_says_none(self):
        Tank.objects.filter(pk=self.t1.pk).update(water_origin='salt_added')
        self.sample(self.loop, hours=2, tan_mg_l='2', ph='7.5', temperature_c='12', salinity_ppt='3',
                    alkalinity_mg_l='80')
        nh3 = read.latest([self.loop])[self.loop.pk].get('nh3_n_mg_l')
        self.assertIn('assumes sea water’s ion composition', nh3.provenance)

    def test_the_calculator_takes_the_origin(self):
        user = get_user_model().objects.create_user('reader', 'reader@example.com', 'eski-sifre-123')
        user.groups.add(role('Water reader', 'view_watermeasurement'))
        self.client.force_login(user)
        page = self.client.get(reverse('farm:water_calculator'), {
            'temperature_c': '12', 'ph': '7', 'salinity_ppt': '3', 'alkalinity_mg_l': '80',
            'water_origin': 'salt_added', 'drawn': '1'})
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.context['analysis'].equilibria.water_origin, 'salt_added')
        self.assertContains(page, 'salt-added fresh water')


class DaviesLimitTests(SimpleTestCase):
    """Salt-added water leaves the fresh path where NaCl's ionic strength reaches the Davies limit, 0.5: S 28.39 permil
    (by the conductivity, 8.4e-6 κ = 0.5 at about 59 500 µS/cm). Its basis stays the ideal water on both sides (the
    larger of the two sides' bases), so the judged NH3 and CO2 never drop across it; the corrected values jump."""

    def test_the_judged_values_never_drop_across_the_davies_limit(self):
        meq = 80.0 / chemistry.MG_CACO3_PER_MEQ
        for temp_c in (2.0, 12.0, 25.0):
            below = native.water_equilibria(temp_c, 28.3, 80.0, water_origin='salt_added')
            above = native.water_equilibria(temp_c, 28.5, 80.0, water_origin='salt_added')
            with self.subTest(temp_c=temp_c):
                self.assertEqual((below.sea_weight, above.sea_weight), (0.0, 1.0))
                for ph in (7.0, 7.5, 8.0):
                    self.assertGreaterEqual(above.nh3_share(ph), below.nh3_share(ph) * (1 - 1e-12))
                    self.assertGreaterEqual(above.co2_judged(meq, ph)[0], below.co2_judged(meq, ph)[0] * (1 - 1e-12))

    def test_the_judged_basis_says_salt_added_water_keeps_the_ideal(self):
        eq = native.water_equilibria(12.0, 3.0, 80.0, water_origin='salt_added')
        self.assertIn('salt-added water: the ideal throughout', messages.judged('nh3', 'limits', 0.001, eq))
        self.assertIn('salt-added water: the ideal throughout', messages.judged('co2', 'limits', 1.0, eq))

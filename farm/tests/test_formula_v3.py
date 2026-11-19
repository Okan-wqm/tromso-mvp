"""The switch to formula 3 (owner, 2026-11-09; chemcore/findings/I2-comparison.md): every chemistry of the application
is worked out by the core's FORMULA_VERSION, 3 (fresh water's own ionic strength from its conductivity at 25 °C, its
hardness, alkalinity or salinity; the Debye-Hückel A of its temperature; the seawater constants from 5 ‰, blended from
1 ‰), and every value shown says the formula it was worked out by. Formula 1 (golden v1) is still worked out exactly,
only when asked for by name. Nothing worked out is stored (a past sample's NH3 is worked out on read by today's formula
and says so)."""
import ast
from decimal import Decimal as D
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from django.urls import reverse

from ..water import calculation, chemistry, deffeyes, dosing, messages, native, read
from .helpers import role
from .test_water import WaterTestCase

ROOT = Path(settings.BASE_DIR)
JUDGED = ('NH₃ judged on the basis its limits were set on (to 1 ‰ the ideal water, every activity 1, as Emerson et al. '
          '1975; from 5 ‰ the free-scale pKa of Khoo et al. 1977, eq. 11, applied to the meter’s NBS pH without '
          'converting it, which reads more NH₃ than a converted pH would: the safe side, on purpose; salt-added water: '
          'the ideal throughout), the larger; activity-corrected %s mg/L.')
LIMITS = deffeyes.Limits(nh3_n_mg_l=0.0103, co2_mg_l=15.0, h2s_ug_l=2.0, alkalinity_low_mg_l=50.0,
                         alkalinity_high_mg_l=150.0)


class FormulaTests(SimpleTestCase):
    def test_the_application_works_out_formula_3(self):
        self.assertEqual(native.formula_version(), 3)
        self.assertEqual(native.FORMULA_VERSION, 3)
        self.assertEqual(native.FORMULAS, (1, 3))
        self.assertEqual(deffeyes.Water(12.0, 0.0, 7.0, 80.0).formula, 3)

    def test_an_analysis_takes_the_waters_own_ionic_strength_and_says_so(self):
        water = deffeyes.Water(12.0, 0.0, 7.0, 80.0, tan_mg_l=0.5, conductivity_25_us_cm=300.0)
        analysis = deffeyes.analyse(water, LIMITS)
        eq = analysis.equilibria
        self.assertEqual(eq, chemistry.water_equilibria(12.0, 0.0, 80.0, conductivity_25_us_cm=300.0))
        self.assertEqual((eq.formula, eq.ionic_strength, eq.strength_source, eq.sea_weight),
                         (3, 1.6e-5 * 300.0, 'conductivity', 0.0))
        self.assertEqual(analysis.provenance, 'Formula 3: ionic strength 0.0048, from the conductivity at 25 °C.')
        ideal = deffeyes.analyse(deffeyes.Water(12.0, 0.0, 7.0, 80.0, tan_mg_l=0.5, formula=1), LIMITS)
        # The activity-corrected values are lower; the judged ones are the larger, here the ideal (cross review F1).
        self.assertLess(analysis.co2_corrected_mg_l, ideal.co2_mg_l)
        self.assertLess(analysis.nh3_corrected_n_mg_l, ideal.nh3_n_mg_l)
        self.assertEqual((analysis.co2_mg_l, analysis.nh3_n_mg_l), (ideal.co2_mg_l, ideal.nh3_n_mg_l))

    def test_formula_1_is_still_golden_v1s_and_only_by_name(self):
        for salinity in (0.0, 2.0, 35.0):
            with self.subTest(salinity=salinity):
                found = deffeyes.analyse(deffeyes.Water(12.0, salinity, 7.0, 80.0, formula=1)).equilibria
                self.assertEqual(found, native.equilibria(12.0, salinity))
                self.assertEqual(found.formula, 1)
        with self.assertRaisesRegex(ValueError, 'unknown formula version'):
            deffeyes.analyse(deffeyes.Water(12.0, 0.0, 7.0, 80.0, formula=2))

    def test_the_band_says_its_seawater_share(self):
        eq = chemistry.water_equilibria(12.0, 3.0, 80.0)
        self.assertEqual(messages.provenance(eq),
                         'Formula 3: ionic strength 0.0599, from the salinity; 50 % seawater constants (assumes sea '
                         'water’s ion composition; salt-added fresh water may read low CO₂: say the unit’s water origin).')

    def test_dosing_and_the_saturation_follow_the_waters_own_equilibria(self):
        water = deffeyes.Water(12.0, 0.0, 7.0, 80.0, conductivity_25_us_cm=1000.0)
        analysis = deffeyes.analyse(water, LIMITS)
        start = (analysis.dic, analysis.alkalinity_meq)
        (first, after) = dosing.simulate(analysis.equilibria, start, 7.0, {'nahco3': 50.0}, 1.0)
        self.assertAlmostEqual(first.co2_mg_l, analysis.co2_mg_l, delta=1e-9)
        self.assertAlmostEqual(after.ph, analysis.equilibria.ph_at(after.dic, after.alkalinity), delta=1e-9)
        made = calculation.calculate(water, LIMITS, deffeyes.Target(7.5, 100.0), 1.0, deffeyes.ALL_LAYERS,
                                     chosen=['nahco3', 'degas'], volume=1.0, amounts={'nahco3': 50.0})
        self.assertEqual(made.analysis.equilibria.strength_source, 'conductivity')
        self.assertEqual(made.steps[1].step.ph, after.ph)

    def test_a_pair_the_floor_refuses_is_judged_in_the_waters_own_medium(self):
        floor = native.alkalinity_floor(10.0, 0.0, 10.5, 80.0, conductivity_25_us_cm=2000.0)
        self.assertEqual(floor, native.water_equilibria(10.0, 0.0, 80.0, conductivity_25_us_cm=2000.0).isoline(10.5)[1]
                         * chemistry.MG_CACO3_PER_MEQ)
        self.assertNotEqual(floor, native.alkalinity_floor(10.0, 0.0, 10.5, formula=1))

    def test_no_application_module_works_out_formula_1(self):
        """chemistry.equilibria(t, s), nh3_fraction and ph_free are formula 1's: only the tests, the recorders and the
        doors that name them may call them."""
        called = []
        for path in [*ROOT.glob('*/**/*.py')]:
            relative = path.relative_to(ROOT).as_posix()
            if ('/tests/' in relative or relative.split('/')[-1].startswith('test') or '/migrations/' in relative
                    or relative.startswith(('chemcore/', 'node_modules/', 'static/')) or relative in (
                        'farm/water/native.py', 'farm/water/chemistry.py')):
                continue
            tree = ast.parse(path.read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in (
                        'equilibria', 'nh3_fraction', 'ph_free', 'equilibria_v3'):
                    called.append(f'{relative}:{node.lineno} {node.func.attr}')
        self.assertEqual(called, [])


class ReadTests(WaterTestCase):
    def nh3(self):
        return read.latest([self.mid1])[self.mid1.pk].get('nh3_n_mg_l')

    def test_a_tans_ammonia_takes_the_points_fresh_ions_and_says_its_formula(self):
        self.sample(hours=30, alkalinity_mg_l='120', conductivity_25_us_cm='450')
        self.sample(hours=2, tan_mg_l='2', ph='7.5', temperature_c='8')
        eq = chemistry.water_equilibria(8.0, 0.0, 120.0, conductivity_25_us_cm=450.0)
        nh3 = self.nh3()
        self.assertEqual(nh3.value, (D(2) * D(eq.nh3_share(7.5))).quantize(D('0.0001')))
        # Judged on the larger, here the ideal share the limits were set on; the corrected one is said (F1).
        self.assertEqual(nh3.value, (D(2) * D(native.equilibria(8.0, 0.0).nh3_share(7.5))).quantize(D('0.0001')))
        corrected = (D(2) * D(eq.nh3_share_corrected(7.5))).quantize(D('0.0001'))
        self.assertLess(corrected, nh3.value)
        self.assertEqual(nh3.provenance,
                         'Formula 3: ionic strength 0.0072, from the conductivity at 25 °C. ' + JUDGED % corrected)
        page = self.client.get(reverse('farm:water'))
        self.assertContains(page, 'Formula 3: ionic strength 0.0072, from the conductivity at 25 °C.')

    def test_with_nothing_measured_the_ammonia_is_formula_1s_ideal_water_and_says_so(self):
        self.sample(hours=2, tan_mg_l='2', ph='7.5', temperature_c='12')
        nh3 = self.nh3()
        self.assertEqual(nh3.value, (D(2) * D(native.equilibria(12.0, 0.0).nh3_share(7.5))).quantize(D('0.0001')))
        self.assertEqual(nh3.provenance, 'Formula 3: ionic strength 0.0000, none measured, taken as 0 (the safe side).')

    def test_a_stale_alkalinity_never_enters(self):
        self.sample(hours=24 * 20, alkalinity_mg_l='120')               # older than its 14 days
        self.sample(hours=2, tan_mg_l='2', ph='7.5', temperature_c='12')
        self.assertEqual(self.nh3().provenance,
                         'Formula 3: ionic strength 0.0000, none measured, taken as 0 (the safe side).')

    def test_a_conductivity_beyond_the_fresh_path_says_why_and_the_basis_alone_is_shown(self):
        """The core refuses the activity correction; the limits' basis needs no conductivity, and the judged NH3 is never
        below it (the re-check of 2026-11-18, RC-3): the value is the basis's, the ideal water's here, and says so."""
        self.sample(hours=2, tan_mg_l='2', ph='7.5', temperature_c='12', conductivity_25_us_cm='50000')
        nh3 = self.nh3()
        self.assertEqual(nh3.value, (D(2) * D(native.equilibria(12.0, 0.0).nh3_share(7.5))).quantize(D('0.0001')))
        self.assertIn('ionic strength above 0.5', nh3.note)
        self.assertIn('ionic strength above 0.5', nh3.refused)
        self.assertEqual(nh3.measured, 'at least: the limits’ basis')


class CalculatorTests(WaterTestCase):
    def test_the_calculator_says_the_formula_and_the_ionic_strength(self):
        user = get_user_model().objects.create_user('reader', 'reader@example.com', 'eski-sifre-123')
        user.groups.add(role('Water reader', 'view_watermeasurement'))
        self.client.force_login(user)
        page = self.client.get(reverse('farm:water_calculator'), {
            'temperature_c': '12', 'ph': '7', 'salinity_ppt': '0', 'alkalinity_mg_l': '80', 'hardness_mg_l': '300',
            'drawn': '1'})
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.context['analysis'].equilibria.strength_source, 'hardness')
        self.assertContains(page, 'Ionic strength')
        self.assertContains(page, 'data-formula="3"')
        self.assertContains(page, 'at least that of the hardness and the alkalinity')

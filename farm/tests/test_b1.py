"""B1 (owner amendment, 2026-11-05): the water chemistry against the source platform's own engine, over the golden
corpus, every output and intermediate (chemcore/scripts/b1_compare.py; the source's outputs in
chemcore/golden/b1/source.json.gz, made by farm/tests/deffeyes_reference/b1/driver.ts from the engine copied
unchanged). Every disagreement above its declared noise floor (chemcore/golden/b1/floors.toml) is a finding of
chemcore/findings/B1.md, listed in chemcore/findings/b1-registry.json; nothing is tolerated silently, and a finding
whose disagreement has gone fails too (the record must follow). Each finding's stated cause is tested: with that cause
taken out, the two sides agree within the floor."""
import gzip
import hashlib
import importlib.util
import json
import math
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from ..water import chemistry, deffeyes, dosing

ROOT = Path(settings.BASE_DIR)
REGISTRY = ROOT / 'chemcore' / 'findings' / 'b1-registry.json'
H2S_PER_S = chemistry.H2S_PER_S
SOURCE_CO2 = 44.0096               # water-quality.ts co2MmToMg
SOURCE_MOLAR_MASS = {'nahco3': 84.007, 'na2co3': 105.988, 'naoh': 39.997, 'caco3': 100.087, 'caoh2': 74.093,
                     'cao': 56.077, 'co2': 44.010, 'degas': 44.010, 'hcl': 36.461}     # reagents.ts REAGENTS mw


def comparer():
    spec = importlib.util.spec_from_file_location('b1_compare', ROOT / 'chemcore' / 'scripts' / 'b1_compare.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class B1Tests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.b1 = comparer()
        cls.source = cls.b1.load_source()
        cls.rows = cls.b1.compare(cls.source, keep=True)
        cls.registry = json.loads(REGISTRY.read_text(encoding='utf-8'))

    def registered(self):
        return {quantity: finding for finding, entry in self.registry['findings'].items()
                for quantity in entry['quantities']}

    def test_the_source_outputs_are_of_the_recorded_engine_and_of_these_inputs(self):
        provenance = (ROOT / 'chemcore' / 'golden' / 'b1' / 'PROVENANCE.txt').read_text(encoding='utf-8')
        self.assertIn('352aa2a8a94a178dd6543de6b741c520f5a1d6f3', provenance)
        self.assertIn(self.source['engine'].split()[-1], provenance)
        inputs = json.dumps(self.b1.inputs(), sort_keys=True).encode('utf-8')
        self.assertIn(f'inputs sha256 {hashlib.sha256(inputs).hexdigest()}', provenance,
                      'the golden changed since the source was run: run the B1 harness again (README)')
        for block in ('constants', 'carbonate', 'analysis', 'geometry', 'dosing'):
            self.assertGreater(len(self.source[block]), 50 if block != 'geometry' else 20, block)

    def test_every_disagreement_is_a_registered_finding(self):
        registered = self.registered()
        silent = {quantity: row for quantity, row in self.rows.items() if row['disagree'] and quantity not in registered}
        self.assertEqual(silent, {}, 'a disagreement with the source that no finding covers (chemcore/findings/B1.md)')

    def test_every_open_finding_still_disagrees(self):
        for quantity, finding in self.registered().items():
            with self.subTest(quantity=quantity, finding=finding):
                self.assertIn(quantity, self.rows, 'the quantity is no longer compared')
                self.assertGreater(self.rows[quantity]['disagree'], 0,
                                   f'{finding} no longer disagrees on {quantity}: update the finding and the registry')

    def test_the_comparison_covers_the_intermediates_the_chart_is_built_from(self):
        compared = set(self.rows)
        for quantity in ('constants.k1_free', 'constants.k2_free', 'constants.kw_free', 'constants.kb_free',
                         'constants.k_nh4_free', 'constants.k_h2s_free', 'constants.ph_free_7', 'constants.ksp_calcite',
                         'carbonate.alpha0', 'carbonate.isoline_slope', 'carbonate.isoline_intercept', 'carbonate.dic',
                         'carbonate.co2', 'carbonate.carbonate', 'carbonate.nh3_share', 'carbonate.h2s_share',
                         'link.co2_of_python_dic', 'link.carbonate_of_python_dic', 'chart.co2_boundary',
                         'chart.nh3_boundary', 'chart.h2s_boundary', 'chart.omega_calcite', 'chart.isoline_end',
                         'analysis.nh3_status', 'analysis.h2s_status', 'dosing.recipe_grams'):
            self.assertIn(quantity, compared)

    # -- each finding's cause, taken out, leaves agreement ---------------------------------------------------------
    def disagreements(self, quantity):
        """Every (inputs, ours, theirs, extra) of a quantity above its floor."""
        return self.rows.get(quantity, {}).get('all', [])

    def test_b1_01_the_co2_molar_mass_explains_every_co2_difference(self):
        for case, ours, theirs, _extra in self.disagreements('analysis.co2_mg_l'):
            self.assertTrue(math.isclose(ours * SOURCE_CO2 / chemistry.MG_CO2_PER_MMOL, theirs, rel_tol=1e-12))
        for case, ours, theirs, _extra in self.disagreements('carbonate.ph_where_co2_15'):
            eq = chemistry.equilibria(case['temp_c'], case['salinity'])
            again = eq.ph_where_co2(case['alkalinity_mg_l'] / chemistry.MG_CACO3_PER_MEQ, 15 / SOURCE_CO2)
            self.assertLessEqual(abs(again - theirs), 1e-8)

    def test_b1_02_the_source_answers_an_unreachable_co2_with_its_search_end(self):
        for case, ours, theirs, _extra in self.disagreements('carbonate.ph_where_co2_at_dic'):
            self.assertIsNone(ours)
            self.assertIn(theirs, (0, 14))

    def test_b1_03_the_source_clamps_a_border_to_its_search_range(self):
        """NH3 is searched over pH 4 to 12 (a border above 12 comes out 12), H2S over 4 to 12.5 with 3.0 and 13.5
        for 'beyond' (WQ-34); ours is the real border."""
        for case, ours, theirs, _extra in self.disagreements('analysis.nh3_border'):
            self.assertGreater(ours, 12.0)
            self.assertLessEqual(abs(theirs - 12.0), 1e-8)
        for case, ours, theirs, _extra in self.disagreements('analysis.h2s_border'):
            self.assertTrue((ours < 4.0 and theirs == 3.0) or (ours > 12.5 and theirs == 13.5), (ours, theirs))
        # the chart's lines and corners that differ are drawn from such a border: NH3 above 12, H2S outside 4 to 12
        for quantity in ('chart.nh3_boundary', 'chart.safe_zone_nh3_side', 'analysis.nh3_share_at_border_pct',
                         'chart.h2s_boundary', 'chart.h2s_zone_drawn'):
            for case, _ours, _theirs, _extra in self.disagreements(quantity):
                analysis = deffeyes.analyse(deffeyes.Water(**case['water']), deffeyes.Limits(**case['limits']))
                with self.subTest(quantity=quantity):
                    if 'nh3' in quantity:
                        self.assertGreater(analysis.nh3.ph, 12.0)
                    else:
                        self.assertTrue(analysis.h2s.ph < 4.0 or analysis.h2s.ph > 12.0, analysis.h2s.ph)

    def test_b1_04_the_molar_masses_explain_every_recipe_difference(self):
        for case, ours, theirs in self.b1.recipe_doses(self.source):
            key, grams = ours
            self.assertTrue(math.isclose(grams * SOURCE_MOLAR_MASS[key] / dosing.BY_KEY[key].molar_mass, theirs,
                                         rel_tol=1e-11), (key, grams, theirs))

    def test_b1_05_a_base_with_stripping_is_the_only_missing_recipe(self):
        for case, ours, theirs, _extra in self.disagreements('dosing.recipe_count'):
            self.assertEqual((theirs, ours), (0, 1))
            self.assertEqual(case['chosen'][1], 'degas')
            self.assertIn(case['chosen'][0], ('naoh', 'caoh2', 'cao'))

    def test_b1_06_the_simulator_differs_by_its_clamps_and_the_molar_masses(self):
        for case, ours, theirs, _extra in self.disagreements('dosing.simulate_dic'):
            self.assertTrue(ours < 0 and theirs == 0 or math.isclose(ours, theirs, rel_tol=1e-4), (ours, theirs))

    def test_b1_07_the_safe_zone_differs_where_the_source_ignores_h2s_crosses_itself_or_vanishes(self):
        """WQ-30, three ways. Ours draws none where the source draws one: H2S narrows the band away (ours without the
        sulfide draws it), or the source's quadrilateral is inverted (its CO2 corner left of its NH3 corner: no pH of
        the band is inside both limits). Ours draws one where the source draws none: the TAN cannot reach the NH3
        limit, the safest water, where the source's NH3 border is NaN and its zone vanishes."""
        for case, ours, theirs, corners in self.disagreements('chart.safe_zone_drawn'):
            water, limits = case['water'], case['limits']
            if ours:
                self.assertFalse(theirs)
                self.assertLessEqual(water['tan_mg_l'], limits['nh3_n_mg_l'], case)
                continue
            self.assertTrue(theirs)
            analysis = deffeyes.analyse(deffeyes.Water(**{**water, 'total_sulfide_ug_l': None}),
                                        deffeyes.Limits(**{**limits, 'h2s_ug_l': None}))
            without_h2s = bool(deffeyes.safe_zone(analysis, deffeyes.box_of(analysis)))
            top_left, top_right, bottom_right, bottom_left = corners
            inverted = top_left[0] >= top_right[0] or bottom_left[0] >= bottom_right[0]
            self.assertTrue(without_h2s or inverted, case)

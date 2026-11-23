"""Formula 4 (golden v4), the application's since 2026-11-19 (the water-chemistry audit's consensus and the owner's
decision, Rule S; chemcore/core/src/formula4.rs), beside formula 3 (golden v3, kept by name).

The core reproduces golden v4 bit for bit; and golden v4 against golden v3, water by water on the same corpus, moves
only what formula 4 moves: up to 1 ‰ the judged CO₂ not at all and the judged NH₃ only where the best estimate is the
larger (a water with nothing measured); from 5 ‰ the NBS step and K_NH4, and the judged NH₃ and CO₂ the best estimate at
the pH ± 0.03; every other constant as it was."""
import gzip
import hashlib
import importlib.util
import json
import math
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from ..water import native

ROOT = Path(settings.BASE_DIR)
V4 = ROOT / 'chemcore' / 'golden' / 'v4'
V3 = ROOT / 'chemcore' / 'golden' / 'v3'
UNMOVED = ('k1', 'k2', 'kw', 'kb', 'boron', 'k_h2s', 'ksp_calcite', 'ksp_aragonite')


def recorder():
    spec = importlib.util.spec_from_file_location('record_golden_v4', ROOT / 'chemcore' / 'scripts' / 'record_golden_v4.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read(path, block):
    return [json.loads(line) for line in gzip.decompress((path / f'{block}.jsonl.gz').read_bytes()).splitlines()]


class GoldenV4Tests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.module = recorder()
        cls.records = cls.module.record_all()

    def test_the_core_reproduces_golden_v4_bit_for_bit(self):
        manifest = json.loads((V4 / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual((manifest['golden_version'], manifest['beside']), ('v4', 'v3'))
        self.assertEqual(manifest['core']['formula_version'], 4)
        for name, records in self.records.items():
            with self.subTest(block=name):
                data = (V4 / f'{name}.jsonl.gz').read_bytes()
                self.assertEqual(manifest['blocks'][name]['sha256'], hashlib.sha256(data).hexdigest())
                self.assertEqual(gzip.decompress(data), gzip.decompress(self.module.encode(records)))

    def test_every_record_is_formula_4_by_name(self):
        self.assertTrue(all(row['v4']['provenance']['formula'] == 4 for row in self.records['waters']))
        self.assertEqual(native.FORMULA_VERSION, 4)
        self.assertEqual(native.FORMULAS, (1, 3, 4))

    def test_against_golden_v3_only_what_formula_4_changes_moves(self):
        v3 = {(row['temp_c'], row['salinity'], row['alkalinity_mg_l'], json.dumps(row['ions'], sort_keys=True)): row['v3']
              for row in read(V3, 'waters')}
        margin = 10 ** native.PH_UNCERTAINTY - 1
        seen = {'fresh': 0, 'sea': 0}
        for row in self.records['waters']:
            old = v3[row['temp_c'], row['salinity'], row['alkalinity_mg_l'], json.dumps(row['ions'], sort_keys=True)]
            new = row['v4']
            with self.subTest(row={key: row[key] for key in ('temp_c', 'salinity', 'alkalinity_mg_l', 'ions')}):
                for name in UNMOVED:
                    self.assertEqual(new['constants'][name], old['constants'][name], name)
                self.assertEqual({**new['provenance'], 'formula': 3}, old['provenance'])
                salted = row['ions'].get('water_origin') == 'salt_added'
                if new['provenance']['sea_weight'] == 0:
                    seen['fresh'] += 1
                    self.assertEqual(new['constants']['ph_offset'], old['constants']['ph_offset'])
                    for at_new, at_old in zip(new['at_ph'], old['at_ph']):
                        self.assertEqual(at_new['co2_judged_mg_l'], at_old['co2_judged_mg_l'])
                        self.assertEqual(at_new['co2_mg_l'], at_old['co2_mg_l'])
                        self.assertEqual(at_new['nh3_share_limits'], at_old['nh3_share_limits'])
                        self.assertEqual(at_new['nh3_share'], max(at_old['nh3_share'], at_new['nh3_share_corrected']))
                elif new['provenance']['sea_weight'] == 1 and not salted:
                    seen['sea'] += 1
                    self.assertEqual(new['constants']['ph_offset'], native.ph_offset_v4(row['temp_c'], row['salinity']))
                    for at in new['at_ph']:
                        judged, best = at['nh3_share'], at['nh3_share_corrected']
                        self.assertAlmostEqual((judged / (1 - judged)) / (best / (1 - best)) - 1, margin, delta=1e-9)
                        self.assertGreaterEqual(at['co2_judged_mg_l'] / at['co2_mg_l'] - 1, margin - 1e-9)
        self.assertGreater(seen['fresh'], 500)
        self.assertGreater(seen['sea'], 300)

    def test_the_scales_take_the_new_step(self):
        for row in self.records['scales']:
            with self.subTest(temp_c=row['temp_c'], salinity=row['salinity']):
                self.assertEqual(row['ph_offset'], native.ph_offset_v4(row['temp_c'], row['salinity']))
                to_total = native.free_to_total(row['temp_c'], row['salinity'])
                for ph, nbs in zip(self.module.v3().PHS, row['nbs_of']['total']):
                    self.assertTrue(math.isclose(nbs, ph + math.log10(to_total) - row['ph_offset'], abs_tol=1e-12))

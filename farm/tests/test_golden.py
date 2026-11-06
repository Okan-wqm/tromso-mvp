"""The golden reference of the water chemistry (chemcore/golden, README: Water-chemistry core): what today's Python
returns for a fixed corpus, recorded by chemcore/scripts/record_golden.py in this Linux image, and the independent
50-digit anchors of chemcore/golden/anchors.json. Nothing may change a result silently: while the Python formulas are
the implementation they must reproduce golden v1 bit for bit, and the recorder must reproduce itself."""
import gzip
import hashlib
import importlib.util
import json
import math
import sys
import tomllib
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from ..water import chemistry

ROOT = Path(settings.BASE_DIR)
GOLDEN = ROOT / 'chemcore' / 'golden'
V1 = GOLDEN / 'v1'
BLOCKS = ['constants', 'carbonate', 'analysis', 'geometry', 'dosing', 'plots', 'edges']


def recorder():
    spec = importlib.util.spec_from_file_location('record_golden', ROOT / 'chemcore' / 'scripts' / 'record_golden.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def block(name):
    with gzip.open(V1 / f'{name}.jsonl.gz', 'rt', encoding='utf-8') as stream:
        return [json.loads(line) for line in stream]


def tolerances():
    return tomllib.loads((ROOT / 'chemcore' / 'tolerances.toml').read_text(encoding='utf-8'))


class GoldenV1Tests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        module = recorder()
        cls.records = module.record_all()
        cls.first = {name: module.encode(records) for name, records in cls.records.items()}
        cls.second = {name: module.encode(records) for name, records in module.record_all().items()}
        cls.manifest = json.loads((V1 / 'manifest.json').read_text(encoding='utf-8'))

    def test_the_recorder_reproduces_itself_byte_for_byte(self):
        self.assertEqual(sorted(self.first), sorted(BLOCKS))
        for name in BLOCKS:
            with self.subTest(block=name):
                self.assertEqual(hashlib.sha256(self.first[name]).hexdigest(),
                                 hashlib.sha256(self.second[name]).hexdigest())

    def test_the_implementation_reproduces_golden_v1_within_each_quantitys_class(self):
        spec = importlib.util.spec_from_file_location('golden_parity', ROOT / 'chemcore' / 'scripts' / 'golden_parity.py')
        parity = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(parity)
        ceilings = {}
        for name in BLOCKS:
            with self.subTest(block=name):
                golden = block(name)
                self.assertEqual(len(self.records[name]), len(golden))
                found = []
                for expected, actual in zip(golden, json.loads(json.dumps(self.records[name]))):
                    found += parity.compare(expected, actual, ceilings=ceilings)
                self.assertEqual(found[:5], [], f'{name}: {len(found)} values outside their class of golden v1. '
                                 'Nothing may change silently; the owner decides (README, Water-chemistry core).')
        sys.stderr.write(chr(10) + '[golden v1 parity, share of each gate used] ' + ', '.join(f'{kind} {value:.2e}'
                                                             for kind, value in sorted(ceilings.items())) + chr(10))

    def test_the_manifest_states_the_provenance(self):
        self.assertEqual(self.manifest['golden_version'], 'v1')
        self.assertEqual(self.manifest['recorded_with']['system'], 'Linux')
        self.assertEqual(self.manifest['recorded_with']['libc'][0], 'glibc')
        self.assertTrue({'farm/water/chemistry.py', 'farm/water/deffeyes.py', 'farm/water/dosing.py'}
                        <= set(self.manifest['formula_modules']))
        for name in BLOCKS:
            with self.subTest(block=name):
                data = (V1 / f'{name}.jsonl.gz').read_bytes()
                self.assertEqual(self.manifest['blocks'][name]['sha256'], hashlib.sha256(data).hexdigest())

    def test_the_committed_reference_stays_small(self):
        """Tier 1 is committed: at most 3 MB compressed (plan 6.1)."""
        self.assertLessEqual(sum(path.stat().st_size for path in V1.iterdir()), 3_000_000)


class CorpusTests(SimpleTestCase):
    """The corpus covers what the plan names, the edges included, and records which inputs Python refuses."""

    def test_every_block_has_records(self):
        for name in BLOCKS:
            with self.subTest(block=name):
                self.assertGreater(len(block(name)), 10)

    def test_the_edges_record_what_python_refused(self):
        edges = block('edges')
        absolute_zero = next(edge for edge in edges if edge['kind'] == 'equilibria' and edge['temp_c'] == -273.15
                             and edge['salinity'] == 0.0)
        self.assertEqual(absolute_zero['result'], {'raises': 'ZeroDivisionError'})
        negative = next(edge for edge in edges if edge['kind'] == 'equilibria' and edge['salinity'] == -1.0)
        self.assertEqual(negative['result'], {'raises': 'ValueError'})
        floors = [edge for edge in edges if edge['kind'] == 'floor']
        self.assertEqual(len(floors), 32)
        self.assertEqual({edge['possible'] for edge in floors}, {True, False})
        self.assertTrue(any(edge['kind'] == 'box' and edge['box'].get('raises') == 'StopIteration' for edge in edges))

    def test_solves_carry_their_path(self):
        record = block('carbonate')[0]
        path = record['ph_where_co2_15_path'][0]
        self.assertIn(path['end'], ('low', 'high', 'none', 'mid'))
        if path['end'] == 'mid':
            self.assertEqual(path['steps'], 38)          # [0, 14] halved to under 1e-10


class ToleranceTests(SimpleTestCase):
    """chemcore/tolerances.toml: the parity classes and their start gates (plan 6.2); never looser than these
    without a written finding."""
    START = {'closed_form': ('rel', 1e-12), 'solved_ph': ('abs', 2e-10), 'bisection_geometry': ('abs', 1e-8),
             'closed_geometry': ('abs', 1e-10)}

    def test_every_class_is_there_and_no_looser_than_its_start_gate(self):
        classes = tolerances()['classes']
        for name, (kind, gate) in self.START.items():
            with self.subTest(tolerance=name):
                self.assertLessEqual(classes[name][kind], gate)
        for name in ('discrete', 'quantised'):
            self.assertEqual(classes[name], {'exact': True})


class AnchorTests(SimpleTestCase):
    """Today's Python against the 50-digit anchors typed from the papers (each paper's check value asserted by the
    generator): agreement to the closed-form class."""

    def test_the_constants_agree_with_the_papers_to_the_last_digits(self):
        rel = tolerances()['classes']['closed_form']['rel']
        for anchor in json.loads((GOLDEN / 'anchors.json').read_text(encoding='utf-8'))['anchors']:
            t, s, values = anchor['temp_c'], anchor['salinity'], anchor['values']
            eq = chemistry.equilibria(t, s)
            ours = {
                'free_to_sws': chemistry._free_to_sws(t, s), 'free_to_total': chemistry._free_to_total(t, s),
                'k1_free': eq.k1, 'k2_free': eq.k2, 'kw_free': eq.kw, 'kb_free': eq.kb, 'k_nh4_free': eq.k_nh4,
                'k_h2s_free': eq.k_h2s, 'k1_sws': chemistry.k1_sws(t, s), 'k2_sws': chemistry.k2_sws(t, s),
                'kw_total': chemistry.kw_total(t, s), 'kb_total': chemistry.kb_total(t, s),
                'k_nh4_sws': chemistry.k_nh4_sws(t, s), 'k_h2s_total': chemistry.k_h2s_total(t, s),
                'ksp_calcite': eq.ksp_calcite, 'ksp_aragonite': eq.ksp_aragonite,
                'oxygen_solubility': chemistry.oxygen_solubility(t, s), 'k0_co2': chemistry.k0_co2(t, s),
                'total_boron': eq.boron,
                'dic_at_ph_free_7_5_alk_2': eq.dic(2.0, 7.5 - eq.ph_offset),
                'co2_at_ph_free_7_5_alk_2': eq.co2(eq.dic(2.0, 7.5 - eq.ph_offset), 7.5 - eq.ph_offset)}
            self.assertEqual(set(ours), set(values))
            for name, value in ours.items():
                with self.subTest(water=(t, s), value=name):
                    expected = float(values[name])
                    self.assertTrue(math.isclose(value, expected, rel_tol=rel, abs_tol=0.0 if expected else 1e-300),
                                    f'{value!r} against {values[name]}')

"""The Rust core's chart in its own units (chemcore/core/src/geometry.rs, through farm/water/native.py) against golden
v1: the box, the isolines, the NH3, CO2 and H2S regions and borders, the safe zone, the Omega lines, the target and the
notes of 600 charts (120 with every vertex, the rest by count, area, length and ends) and of the Omega edges, within
the classes of chemcore/tolerances.toml; the notes come as codes and farm/water/messages.py says each in the words the
chart always used; the safe zone in a box of the caller's."""
import gzip
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from django.conf import settings
from django.test import SimpleTestCase
from django.utils import translation

from ..water import deffeyes, native

ROOT = Path(settings.BASE_DIR)
V1 = ROOT / 'chemcore' / 'golden' / 'v1'


def script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'chemcore' / 'scripts' / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def block(name):
    with gzip.open(V1 / f'{name}.jsonl.gz', 'rt', encoding='utf-8') as stream:
        return [json.loads(line) for line in stream]


def shape_of(found):
    """The core's dict in the shape the golden recorder reads (deffeyes.Geometry's attributes)."""
    from ..water import messages
    return SimpleNamespace(
        box=deffeyes.Box(*found['box']), point=found['point'], target=found['target'],
        notes=[messages.note(code) for code in found['notes']],
        isolines=[SimpleNamespace(ph=ph, labelled=labelled, segment=segment) for ph, labelled, segment in found['isolines']],
        regions=found['regions'], boundaries=found['boundaries'], omega=found['omega'])


def chart(record, layers=deffeyes.ALL_LAYERS):
    target = record['target']
    return native.geometry(record['water'], record['limits'],
                           None if target is None else (target['ph'], target['alkalinity_mg_l']), record['pressure'],
                           sorted(layers))


class GeometryParityTests(SimpleTestCase):
    def test_every_chart_of_golden_v1_within_its_class(self):
        recorder, compare = script('record_golden'), script('golden_parity').compare
        ceilings, found, count = {}, [], 0
        with translation.override('en'):
            for record in block('geometry'):
                if 'raises' in record:
                    continue
                ours = recorder.geometry_record(deffeyes, shape_of(chart(record)), record['full'])
                found += compare(record['geometry'], json.loads(json.dumps(ours)), ceilings=ceilings)
                count += 1
        sys.stderr.write(chr(10) + f'[geometry parity, {count} charts, share of each gate used] '
                         + ', '.join(f'{kind} {value:.2e}' for kind, value in sorted(ceilings.items())) + chr(10))
        self.assertEqual(count, 600)
        self.assertEqual(found[:5], [])

    def test_the_omega_edges_of_golden_v1(self):
        recorder, compare = script('record_golden'), script('golden_parity').compare
        with translation.override('en'):
            for edge in block('edges'):
                if edge['kind'] != 'omega':
                    continue
                record = {'water': {'temperature_c': 10.0, 'salinity_ppt': edge['salinity'], 'ph': 8.0,
                                    'alkalinity_mg_l': 115.0, 'calcium_mg_l': 400.0},
                          'limits': {}, 'target': None, 'pressure': 1.0}
                ours = recorder.geometry_record(deffeyes, shape_of(chart(record, {'omega'})), True)
                with self.subTest(salinity=edge['salinity']):
                    self.assertEqual(compare(edge['geometry'], json.loads(json.dumps(ours))), [])


class NotesTests(SimpleTestCase):
    def test_every_code_the_core_gives_has_its_words(self):
        from ..water import messages
        codes = {'co2.no_limit', 'safe.no_band', 'safe.empty_band', 'safe.no_tan', 'safe.no_nh3_limit',
                 'safe.no_co2_limit', 'safe.no_h2s_limit', 'safe.h2s_not_assessed', 'safe.no_safe_ph',
                 'omega.out_of_range', 'nh3.no_tan', 'nh3.no_limit', 'nh3.not_reached', 'nh3.cannot_reach',
                 'h2s.no_sulfide', 'h2s.no_limit', 'h2s.not_reached', 'h2s.cannot_reach'}
        self.assertEqual(set(messages.NOTES), codes)
        with translation.override('en'):
            self.assertEqual(messages.note('co2.no_limit'), 'CO₂: no limit given.')
        with self.assertRaises(KeyError):
            messages.note('no.such.code')

    def test_a_layer_that_is_not_one_is_refused(self):
        with self.assertRaises(ValueError):
            native.geometry({'temperature_c': 12.0, 'salinity_ppt': 1.0, 'ph': 7.0, 'alkalinity_mg_l': 80.0}, {},
                            layers=['no-such-layer'])


class SafeZoneInABoxTests(SimpleTestCase):
    def test_the_safe_zone_in_the_callers_box(self):
        water = {'temperature_c': 12.0, 'salinity_ppt': 1.0, 'ph': 7.0, 'alkalinity_mg_l': 80.0, 'tan_mg_l': 0.5}
        limits = {'nh3_n_mg_l': 0.0103, 'co2_mg_l': 15.0, 'alkalinity_low_mg_l': 50.0, 'alkalinity_high_mg_l': 150.0}
        zone = native.safe_zone(water, limits, (1e4, 1e4, 1.0, 1.0))
        self.assertGreater(len(zone), 4)
        self.assertEqual(native.safe_zone_gaps(water, {**limits, 'co2_mg_l': None}), ['safe.no_co2_limit'])
        self.assertEqual(native.safe_zone_gaps({**water, 'tan_mg_l': None}, limits), ['safe.no_tan'])

"""The Rust core's analysis of a water (chemcore/core/src/analysis.rs, through farm/water/native.py) against golden v1:
every value, border, margin and status of 1 500 analyses and of the edges (the floor cases, pH outside the chart, the
NH3 limit at the TAN, the B1 cases), the alkalinity floor, the chart's box with its 1-2-5 steps and ties, and the
judging rule (critical past the border, a warning within 0.2 pH), within the classes of chemcore/tolerances.toml."""
import gzip
import importlib.util
import json
import sys
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from ..water import native

ROOT = Path(settings.BASE_DIR)
V1 = ROOT / 'chemcore' / 'golden' / 'v1'
ERRORS = {'ZeroDivisionError': ZeroDivisionError, 'ValueError': ValueError, 'OverflowError': OverflowError}


def block(name):
    with gzip.open(V1 / f'{name}.jsonl.gz', 'rt', encoding='utf-8') as stream:
        return [json.loads(line) for line in stream]


def parity():
    spec = importlib.util.spec_from_file_location('golden_parity', ROOT / 'chemcore' / 'scripts' / 'golden_parity.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def analyse(record):
    target = record['target'] or {}
    result = native.analyse(**record['water'], **record['limits'], target_ph=target.get('ph'),
                            target_alkalinity_mg_l=target.get('alkalinity_mg_l'), pressure=record['pressure'])
    del result['equilibria']
    return result


class AnalysisParityTests(SimpleTestCase):
    def test_every_analysis_of_golden_v1_within_its_class(self):
        compare, ceilings, found = parity().compare, {}, []
        records = [r for r in block('analysis')] + [r['analysis'] for r in block('edges') if r['kind'] in (
            'floor', 'ph', 'nh3_limit')] + [r for r in block('edges') if r['kind'] == 'b1_case']
        self.assertGreater(len(records), 1500)
        for record in records:
            if 'raises' in record:
                with self.assertRaises(ERRORS[record['raises']]):
                    analyse(record)
                continue
            found += compare(record['analysis'], json.loads(json.dumps(analyse(record))), ceilings=ceilings)
        self.assertEqual(found[:5], [])

    def test_the_analysis_carries_the_waters_equilibria(self):
        result = native.analyse(12.0, 1.0, 7.0, 80.0)
        self.assertEqual(result['equilibria'], native.equilibria(12.0, 1.0))
        self.assertEqual((result['nh3']['status'], result['co2']['status'], result['h2s']['status']),
                         ('not_measured', 'no_limit', 'not_measured'))


class FloorAndBoxTests(SimpleTestCase):
    def test_the_floor_and_the_impossible_pairs_of_golden_v1(self):
        ties = []
        for edge in block('edges'):
            if edge['kind'] != 'floor':
                continue
            args = (edge['temp_c'], edge['salinity'], edge['ph'])
            floor = native.alkalinity_floor(*args)
            self.assertLessEqual(abs(floor - edge['floor']), 1e-12 + 1e-12 * abs(floor))
            impossible = native.why_impossible(*args, edge['alkalinity_mg_l'])
            if abs(edge['alkalinity_mg_l'] - edge['floor']) <= 1e-12 + 1e-12 * abs(edge['floor']):
                # A tie: an alkalinity on the floor or one ulp beside it. Two libms put the floor a last bit apart,
                # so the decision there may flip; such cases are listed, never hidden.
                ties.append((args, edge['alkalinity_mg_l'], edge['possible'], impossible is None))
                continue
            self.assertEqual(impossible is None, edge['possible'], edge)
        flips = [tie for tie in ties if tie[2] != tie[3]]
        sys.stderr.write(chr(10) + f'[floor ties] {len(ties)} ties, {len(flips)} flipped: {flips}' + chr(10))
        self.assertGreaterEqual(len(ties), 16)     # 8 waters x (on the floor, one ulp above), at least

    def test_the_box_of_golden_v1_with_its_ties(self):
        for edge in block('edges'):
            if edge['kind'] != 'box':
                continue
            analysis = native.analyse(12.0, 1.0, 7.0, 80.0, alkalinity_low_mg_l=50.0,
                                      alkalinity_high_mg_l=edge['alkalinity_high_mg_l'])
            call = lambda: native.box_of(analysis['dic'], analysis['alkalinity_meq'], None,  # noqa: E731
                                         edge['alkalinity_high_mg_l'], [])
            with self.subTest(high=edge['alkalinity_high_mg_l']):
                if 'raises' in edge['box']:
                    # Python ran out of 1-2-5 steps with a bare StopIteration; the core says why (a ValueError).
                    self.assertEqual(edge['box']['raises'], 'StopIteration')
                    with self.assertRaises(native.ChartTooLargeError):
                        call()
                    self.assertTrue(issubclass(native.ChartTooLargeError, ValueError))
                else:
                    box = edge['box']['value']
                    self.assertEqual(call(), (box['dic'], box['alkalinity'], box['dic_step'], box['alkalinity_step']))

    def test_the_box_holds_the_target_and_the_extra_points(self):
        self.assertEqual(native.box_of(1.0, 1.0, (7.0, 2.0), None, []), (8.0, 6.0, 1.0, 1.0))
        self.assertEqual(native.box_of(1.0, 1.0, None, None, [(1.0, 30.0)]), (6.0, 35.0, 1.0, 5.0))
        self.assertEqual(native.box_of(-3.0, 1.0, None, None, []), (6.0, 6.0, 1.0, 1.0))


class JudgeTests(SimpleTestCase):
    def test_critical_past_the_border_a_warning_within_02_ok_short_of_it(self):
        self.assertEqual(native.judge(8.0, 8.0, True)['status'], 'critical')
        self.assertEqual(native.judge(7.85, 8.0, True)['status'], 'warning')
        self.assertEqual(native.judge(7.8, 8.0, True)['status'], 'ok')    # 8.0 - 7.8 is 0.2000000000000002, as in Python
        self.assertEqual(native.judge(7.79, 8.0, True)['status'], 'ok')
        self.assertEqual(native.judge(7.0, 6.0, False)['margin'], 1.0)
        self.assertEqual(native.judge(7.0, None, False), {'ph': None, 'toxic_above': False, 'margin': None,
                                                         'status': 'ok', 'on_chart': False, 'everywhere': False,
                                                         'off_chart': False})
        self.assertEqual(native.judge(7.0, 3.0, True, 'no_limit')['status'], 'no_limit')

    def test_a_border_off_the_chart_is_said_in_words(self):
        self.assertTrue(native.judge(7.0, 3.5, True)['everywhere'])
        self.assertTrue(native.judge(7.0, 13.0, True)['off_chart'])
        self.assertTrue(native.judge(7.0, 13.0, False)['everywhere'])
        self.assertTrue(native.judge(7.0, 12.5, False)['on_chart'])

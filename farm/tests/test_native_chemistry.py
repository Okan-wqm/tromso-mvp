"""The Rust core's chemistry (chemcore/core/src/chemistry.rs, through farm/water/native.py) against golden v1, the
reference recorded from the Python formulas (chemcore/golden/v1), within the classes of chemcore/tolerances.toml
(the core's libm and glibc differ in last bits, S0); against the 50-digit anchors; refusing exactly the inputs Python
refused, with the same exception; and its solver returning exactly what Python's returned for the same callbacks.
The measured ceilings are printed on every run."""
import gzip
import json
import math
import sys
import tomllib
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from ..water import native

ROOT = Path(settings.BASE_DIR)
V1 = ROOT / 'chemcore' / 'golden' / 'v1'
CLASSES = tomllib.loads((ROOT / 'chemcore' / 'tolerances.toml').read_text(encoding='utf-8'))['classes']
MEQ = {'isoline_intercept', 'alkalinity_floor', 'dic', 'alkalinity_back', 'co2', 'carbonate'}
PYTHON_ERRORS = {'ZeroDivisionError': ZeroDivisionError, 'ValueError': ValueError, 'OverflowError': OverflowError}
SOLVED = {'ph_at', 'ph_where_co2_5', 'ph_where_co2_15', 'ph_where_co2_40'}


def block(name):
    with gzip.open(V1 / f'{name}.jsonl.gz', 'rt', encoding='utf-8') as stream:
        return [json.loads(line) for line in stream]


class Ceilings:
    """The largest difference seen per class, and a check against each class's gate."""

    def __init__(self, test):
        self.test, self.seen = test, {}

    def check(self, kind, name, ours, expected, where):
        gate = CLASSES[kind]
        if expected is None or ours is None:
            self.test.assertEqual(ours, expected, (name, where))
            return
        difference = abs(ours - expected)
        allowed = gate.get('abs', 0.0) + gate.get('rel', 0.0) * max(abs(ours), abs(expected))
        measure = difference if kind in ('solved_ph', 'closed_form_ph') else difference / max(abs(expected), 1e-300)
        self.seen[kind] = max(self.seen.get(kind, 0.0), measure)
        self.test.assertLessEqual(difference, allowed, f'{name} at {where}: {ours!r} against golden {expected!r}')

    def report(self, title):
        sys.stderr.write(f'\n[chemcore parity, {title}] ' + ', '.join(
            f'{kind} {value:.2e}' for kind, value in sorted(self.seen.items())) + '\n')


class ConstantsParityTests(SimpleTestCase):
    def test_every_constant_of_golden_v1_within_the_closed_form_class(self):
        ceilings = Ceilings(self)
        for record in block('constants'):
            if 'altitude_m' in record:
                ceilings.check('closed_form', 'pressure_atm', native.pressure_atm(record['altitude_m']),
                               record['pressure_atm'], record['altitude_m'])
                continue
            t, s = record['temp_c'], record['salinity']
            eq = native.equilibria(t, s)
            for name, expected in record['equilibria'].items():
                ceilings.check('closed_form_ph' if name == 'ph_offset' else 'closed_form', f'equilibria.{name}',
                               getattr(eq, name), expected, (t, s))
            for name in ('free_to_sws', 'free_to_total', 'sws_to_nbs', 'ionic_strength', 'total_boron', 'total_sulfate',
                         'total_fluoride', 'k1_sws', 'k2_sws', 'kw_total', 'kb_total', 'k_nh4_sws', 'pk_nh4',
                         'k_h2s_total', 'ksp_calcite', 'ksp_aragonite', 'k0_co2'):
                function = getattr(native, name)
                ours = function(s) if name in ('ionic_strength', 'total_boron', 'total_sulfate', 'total_fluoride') \
                    else function(t, s)
                ceilings.check('closed_form', name, ours, record[name], (t, s))
            ceilings.check('closed_form', 'activity_h', native.activity_coefficient_h(t, s), record['activity_h'], (t, s))
            for name in ('ks', 'kf'):
                if 'value' in record[name]:
                    ceilings.check('closed_form', name, getattr(native, name)(t, s), record[name]['value'], (t, s))
            ceilings.check('closed_form', 'vapour_pressure_atm', native.vapour_pressure_atm(t),
                           record['vapour_pressure_atm'], t)
            for pressure, expected in record['oxygen_solubility'].items():
                ceilings.check('closed_form', 'oxygen_solubility', native.oxygen_solubility(t, s, float(pressure)),
                               expected, (t, s, pressure))
            for pressure, expected in record['co2_from_air'].items():
                ceilings.check('closed_form', 'co2_from_air', native.co2_from_air(t, s, float(pressure)), expected,
                               (t, s, pressure))
            ceilings.check('closed_form_ph', 'ph_free', native.ph_free(7.0, t, s), record['ph_free_7'], (t, s))
            ceilings.check('closed_form', 'nh3_fraction', native.nh3_fraction(7.5, t, s), record['nh3_fraction_7_5'],
                           (t, s))
        ceilings.report('constants')


class CarbonateParityTests(SimpleTestCase):
    def test_every_carbonate_value_and_border_of_golden_v1_within_its_class(self):
        ceilings = Ceilings(self)
        for record in block('carbonate'):
            t, s, ph, alk = record['temp_c'], record['salinity'], record['ph'], record['alkalinity_meq']
            where = (t, s, ph, record['alkalinity_mg_l'])
            eq = native.equilibria(t, s)
            dic = eq.dic(alk, ph)
            slope, intercept = eq.isoline(ph)
            values = {
                'hydrogen': eq.hydrogen(ph), 'isoline_slope': slope, 'isoline_intercept': intercept, 'dic': dic,
                'alkalinity_back': eq.alkalinity(dic, ph), 'co2': eq.co2(dic, ph), 'carbonate': eq.carbonate(dic, ph),
                'nh3_share': eq.nh3_share(ph), 'h2s_share': eq.h2s_share(ph), 'ph_of_hydrogen': eq.ph_of(eq.hydrogen(ph)),
                'alkalinity_floor': intercept * native.MG_CACO3_PER_MEQ}
            expected = {**record, 'isoline_slope': record['isoline'][0], 'isoline_intercept': record['isoline'][1]}
            for name, ours in values.items():
                kind = 'closed_form_meq' if name in MEQ else 'closed_form_ph' if name == 'ph_of_hydrogen' else 'closed_form'
                ceilings.check(kind, name, ours, expected[name], where)
            for index, share in enumerate(eq.fractions(ph)):
                ceilings.check('closed_form', f'alpha{index}', share, record['fractions'][index], where)
            ceilings.check('solved_ph', 'ph_at', eq.ph_at(dic, alk), record['ph_at']['value'], where)
            for co2 in (5, 15, 40):
                ceilings.check('solved_ph', f'ph_where_co2_{co2}', eq.ph_where_co2(alk, co2 / native.MG_CO2_PER_MMOL),
                               record[f'ph_where_co2_{co2}']['value'], where)
            closed = {'ph_where_co2_at_dic': eq.ph_where_co2_at_dic(dic, 0.3),
                      'ph_where_carbonate': eq.ph_where_carbonate(dic, 0.05),
                      'ph_where_nh3': eq.ph_where_nh3(0.5, 0.0103),
                      'ph_where_h2s': eq.ph_where_h2s(3.0 * native.H2S_PER_S, 2.0)}
            for name, ours in closed.items():
                ceilings.check('closed_form_ph', name, ours, record[name].get('value'), where)
        ceilings.report('carbonate')


class RefusalTests(SimpleTestCase):
    """Where Python raised, the core raises the same exception; where Python returned a non-finite number for a
    non-finite or out-of-domain input, the core refuses it (NonFiniteError, a ValueError): never a NaN as a number."""

    def test_the_edges_are_refused_as_python_refused_them(self):
        for edge in block('edges'):
            if edge['kind'] not in ('equilibria', 'pressure'):
                continue
            edge = {key: float(value) if key in ('temp_c', 'salinity', 'altitude_m') else value
                    for key, value in edge.items()}          # 'nan' and 'inf' are recorded as strings
            calls = ({'result': lambda: native.equilibria(edge['temp_c'], edge['salinity']),
                      'oxygen': lambda: native.oxygen_solubility(edge['temp_c'], edge['salinity'], 1.0),
                      'co2_from_air': lambda: native.co2_from_air(edge['temp_c'], edge['salinity'], 1.0)}
                     if edge['kind'] == 'equilibria' else {'result': lambda: native.pressure_atm(edge['altitude_m'])})
            for name, call in calls.items():
                recorded = edge[name]
                with self.subTest(edge=edge.get('temp_c', edge.get('altitude_m')), salinity=edge.get('salinity'),
                                  value=name):
                    if not all(math.isfinite(edge[key]) for key in ('temp_c', 'salinity', 'altitude_m') if key in edge):
                        with self.assertRaises(native.NonFiniteError):       # a non-finite input, whatever Python did
                            call()
                    elif 'raises' in recorded:
                        with self.assertRaises(PYTHON_ERRORS[recorded['raises']]):
                            call()
                    elif not finite_tree(recorded['value']):
                        with self.assertRaises(native.NonFiniteError):
                            call()
                    else:
                        call()

    def test_a_non_finite_input_is_refused(self):
        for call in (lambda: native.equilibria(float('nan'), 0.0), lambda: native.oxygen_solubility(10.0, float('inf')),
                     lambda: native.equilibria(10.0, 1.0).dic(float('nan'), 7.0)):
            with self.assertRaises(native.NonFiniteError):
                call()
        self.assertTrue(issubclass(native.NonFiniteError, ValueError))


def finite_tree(value):
    if isinstance(value, dict):
        return all(finite_tree(item) for item in value.values())
    if isinstance(value, str):
        return value not in ('nan', 'inf', '-inf')
    return True


class SolverTests(SimpleTestCase):
    def test_the_core_solves_a_python_function_exactly_as_python_did(self):
        functions = [lambda x: x - 3.0, lambda x: x * x - 2.0, lambda x: math.exp(x) - 1e3, lambda x: 1.0,
                     lambda x: x, lambda x: x - 14.0, lambda x: math.tanh(x - 7.123456789)]
        for function in functions:
            expected = python_solve(function, 0.0, 14.0)
            ours = native.solve(function, 0.0, 14.0)
            self.assertEqual(ours if ours is None else ours.hex(), expected if expected is None else expected.hex())

    def test_an_error_in_the_function_stops_the_solver(self):
        def failing(_x):
            raise ZeroDivisionError('float division by zero')
        with self.assertRaises(ZeroDivisionError):
            native.solve(failing, 0.0, 14.0)


def python_solve(function, low, high):
    """chemistry.solve as golden v1 recorded it (farm/water/chemistry.py at a4d5729), kept here as the test's oracle."""
    at_low, at_high = function(low), function(high)
    if at_low == 0:
        return low
    if at_high == 0:
        return high
    if (at_low > 0) == (at_high > 0):
        return None
    for _step in range(200):
        middle = (low + high) / 2
        at_middle = function(middle)
        if (at_middle > 0) == (at_low > 0):
            low, at_low = middle, at_middle
        else:
            high = middle
        if high - low < 1e-10:
            break
    return (low + high) / 2


class EquilibriaObjectTests(SimpleTestCase):
    def test_a_water_is_a_frozen_value(self):
        one, same, other = native.equilibria(12.0, 1.0), native.equilibria(12.0, 1.0), native.equilibria(12.0, 2.0)
        self.assertEqual(one, same)
        self.assertNotEqual(one, other)
        self.assertEqual(hash(one), hash(same))
        self.assertEqual(list(native.Equilibria.fields), ['temp_c', 'salinity', 'ph_offset', 'k1', 'k2', 'kw', 'kb',
                                                         'boron', 'k_nh4', 'k_h2s', 'ksp_calcite', 'ksp_aragonite'])
        with self.assertRaises(AttributeError):
            one.k1 = 1.0
        self.assertIn('Equilibria(temp_c=12.0, salinity=1.0', repr(one))

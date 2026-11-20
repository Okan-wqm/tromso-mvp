"""Parity with golden v1 by class (chemcore/tolerances.toml): a record of today's implementation against the
recorded one, field by field. Since the formulas run in the Rust core, whose libm differs from glibc in last bits
(S0), "the same" is "within the class of the quantity"; everything that is not a float must be equal.

Classes by the field's place in the record (the plan, 6.2):
- a pH (a border, a margin, a solved or closed-form pH): solved_ph, absolute;
- a chart coordinate, a plot's point, a simulator step, a summary's area or length: bisection_geometry, absolute;
- every other float: closed_form_meq (relative, with an absolute floor for values near 0).
Not compared: the solver's path signatures and counts of the recorder (`paths`, `solves`): the core's own solves are
not visible to the recorder once the Python solver is gone; the solved values they lead to are compared.
A value recorded as non-finite ('nan', 'inf') or an input Python accepted only to return such a value is now refused:
the recorded value and the record {'raises': 'NonFiniteError'} are taken as the same (owner amendment B3: never a NaN
shown as a number)."""
import math
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CLASSES = tomllib.loads((ROOT / 'chemcore' / 'tolerances.toml').read_text(encoding='utf-8'))['classes']
GEOMETRY = {'regions', 'boundaries', 'omega', 'isolines', 'point', 'target', 'waypoint', 'wedge', 'dosing_path',
            'reagent_lines', 'simulator', 'first', 'last', 'area', 'length', 'series', 'steps', 'box', 'x', 'y', 'bands',
            'verticals', 'horizontals', 'dots', 'geometry', 'visual'}
PH = {'ph', 'margin', 'ph_at', 'ph_free_7', 'ph_of_hydrogen', 'ph_offset', 'floor_ph'}
SKIPPED = {'paths', 'solves', 'ph_at_path'}
NON_FINITE = {'nan', 'inf', '-inf'}


def kind_of(path):
    names = {str(part) for part in path}
    if names & GEOMETRY:
        return 'bisection_geometry'
    last = str(path[-1]) if path else ''
    if last in PH or last.startswith('ph_where') or any(str(part) in PH for part in path[-2:]):
        return 'solved_ph'
    return 'closed_form_meq'


INPUTS = ('temp_c', 'salinity', 'altitude_m')
TIE = 1e-12
# Fields an implementation added since golden v1 was recorded (each with its step); a field v1 holds is never
# skipped, and a field missing from the implementation is always a difference.
ADDED = {'angle', 'counter_productive', 'priority',       # a reagent's angle, a recipe's ranks (S7)
         'conductivity_25_us_cm', 'hardness_mg_l', 'formula',   # a water's ions and its formula (formula 3's switch)
         # the judged NH3 and CO2's activity-corrected value and basis (cross review F1); for formula 1 the corrected
         # equals the judged and the basis is 'limits' (farm/tests/test_limits_basis.py)
         'co2_corrected_mg_l', 'co2_basis', 'nh3_corrected_n_mg_l', 'nh3_basis',
         'water_origin',                                         # a water's origin, '' not said (cross review F3)
         'phosphate_p_mg_l'}                                     # a water's optional phosphate, None: not given
# Exceptions the core names where Python raised an accidental one: (recorded, now). Each is a deliberate, tested change.
RENAMED_RAISES = {('StopIteration', 'ChartTooLargeError')}     # the box beyond 12 steps of 5e7 (S5)


def compare(expected, actual, path=(), found=None, ceilings=None, refused=False):
    """The differences beyond each class's gate, as (path, expected, actual); `ceilings` collects, per class, the
    largest share of its gate a difference used (1 = at the gate). `refused`: the record's input is not finite, so
    the core refuses every value of it (NonFiniteError), whatever Python returned."""
    found = [] if found is None else found
    if not path and isinstance(expected, dict):
        refused = any(isinstance(expected.get(key), str) and expected[key] in NON_FINITE for key in INPUTS)
        if expected.get('kind') == 'floor' and abs(expected['alkalinity_mg_l'] - expected['floor']) <= TIE * (
                1 + abs(expected['floor'])):
            # A tie: an alkalinity on the floor or one ulp beside it, where two libms may decide `possible` apart
            # (farm/tests/test_native_analysis.py lists them); the rest of the record is compared.
            expected = {key: value for key, value in expected.items() if key != 'possible'}
            actual = {key: value for key, value in actual.items() if key != 'possible'}
    if isinstance(expected, dict) and isinstance(actual, dict):
        if set(expected) == {'value'} and actual.get('raises') == 'NonFiniteError' and (
                refused or not finite(expected['value'])):
            return found
        for key in sorted(set(expected) | set(actual)):
            if key in SKIPPED or str(key).endswith('_path'):
                continue
            if key not in expected and key in ADDED:
                continue                    # a field the implementation added since v1, listed in ADDED
            if key not in expected or key not in actual:
                found.append((path + (key,), expected.get(key, '<missing>'), actual.get(key, '<missing>')))
                continue
            compare(expected[key], actual[key], path + (key,), found, ceilings, refused)
    elif isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            found.append((path + ('len',), len(expected), len(actual)))
        else:
            for index, (one, two) in enumerate(zip(expected, actual)):
                compare(one, two, path + (index,), found, ceilings, refused)
    elif isinstance(expected, float) and isinstance(actual, (float, int)) and not isinstance(actual, bool) \
            or isinstance(expected, int) and isinstance(actual, float) and not isinstance(expected, bool):
        kind = kind_of(path)
        gate = CLASSES[kind]
        difference = abs(expected - actual)
        allowed = gate.get('abs', 0.0) + gate.get('rel', 0.0) * max(abs(expected), abs(actual))
        if ceilings is not None:
            ceilings[kind] = max(ceilings.get(kind, 0.0), difference / allowed if allowed else float(difference > 0))
        if difference > allowed:
            found.append((path, expected, actual))
    elif expected != actual and (expected, actual) not in RENAMED_RAISES:
        found.append((path, expected, actual))
    return found


def finite(value):
    if isinstance(value, dict):
        return all(finite(item) for item in value.values())
    if isinstance(value, list):
        return all(finite(item) for item in value)
    if isinstance(value, str):
        return value not in NON_FINITE
    if isinstance(value, float):
        return math.isfinite(value)
    return True

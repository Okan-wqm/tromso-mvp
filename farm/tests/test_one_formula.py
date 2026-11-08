"""One formula (owner rule): a formula lives in the Rust core only (chemcore/core/src), and the Python modules that
used to hold it keep their names as doors to it, with no arithmetic of their own. A module is listed here in the
commit that switches it to the core and deletes its Python bodies (README, Water-chemistry core)."""
import ast
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from ..water import chemistry, native

ROOT = Path(settings.BASE_DIR)
SWITCHED = ['farm/water/chemistry.py']
# Functions of a module still partly in Python, switched one by one: no arithmetic, no number, no math of their own.
SWITCHED_FUNCTIONS = {'farm/water/deffeyes.py': ['judge', 'analyse', 'alkalinity_floor', 'why_impossible', 'possible',
                                                 'box_of', 'geometry', 'safe_zone', 'safe_zone_gaps'],
                      'farm/water/dosing.py': ['split', 'recipes', 'at_target', 'visual', 'simulate'],
                      'farm/water/charts.py': ['bands', 'nh3_plot', 'h2s_plot', 'carbonate_plot', 'saturation_index',
                                               'saturation_plot', 'plots'],
                      'farm/water/calculation.py': ['judge_step']}
# What a switch deleted: the module must not hold it any more (one formula, in the core).
DELETED = {'farm/water/deffeyes.py': ['_axis', '_clip', '_cross', 'clip_to_box', 'clip_segment', 'clip_polyline',
                                     '_isoline_segment', '_half', 'co2_curve', '_co2_region', 'omega_line',
                                     '_toxic_region', '_nh3_note', '_h2s_note'],
           'farm/water/dosing.py': ['molar_mass', '_dose', 'recipe', '_below_air', 'direction_line', 'angle', 'unit_move'],
           'farm/water/charts.py': ['widen', 'grid', '_verticals'],
           'farm/water/calculation.py': ['below_air']}


def arithmetic(node):
    """Arithmetic or a numeric comparison (`is None`, `not`, `in` and formatting a translated text are not formulas)."""
    if isinstance(node, ast.BinOp):
        # text formatting, _('... %(floor)s ...') % {...}, is words, not a formula
        return not (isinstance(node.op, ast.Mod) and isinstance(node.left, ast.Call)
                    and getattr(node.left.func, 'id', '') in ('_', 'gettext', 'ngettext'))
    if isinstance(node, ast.UnaryOp):
        return not isinstance(node.op, ast.Not)
    if isinstance(node, ast.Compare):
        return not all(isinstance(op, (ast.Is, ast.IsNot, ast.In, ast.NotIn)) for op in node.ops)
    return False


class OneFormulaTests(SimpleTestCase):
    def test_a_switched_module_holds_no_formula(self):
        for name in SWITCHED:
            tree = ast.parse((ROOT / name).read_text(encoding='utf-8'))
            with self.subTest(module=name):
                imported = {alias.name for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))
                            for alias in node.names}
                self.assertFalse(imported & {'math', 'cmath', 'decimal', 'fractions', 'numpy'}, imported)
                self.assertEqual([node.name for node in ast.walk(tree)
                                  if isinstance(node, (ast.FunctionDef, ast.Lambda, ast.ClassDef))], [])
                numbers = [node.value for node in ast.walk(tree)
                           if isinstance(node, ast.Constant) and isinstance(node.value, (int, float))
                           and not isinstance(node.value, bool)]
                self.assertEqual(numbers, [])
                operations = [type(node).__name__ for node in ast.walk(tree) if isinstance(node, (ast.BinOp, ast.UnaryOp))]
                self.assertEqual(operations, [])

    def test_a_switched_function_holds_no_formula(self):
        for name, functions in SWITCHED_FUNCTIONS.items():
            tree = ast.parse((ROOT / name).read_text(encoding='utf-8'))
            defined = {node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
            for function in functions:
                with self.subTest(module=name, function=function):
                    node = defined[function]
                    self.assertEqual([ast.unparse(each) for each in ast.walk(node) if arithmetic(each)], [])
                    # a default argument (pressure=1.0) and a display precision (shown(floor, 1)) are not formulas
                    allowed = {id(each) for each in node.args.defaults} | {
                        id(argument) for call in ast.walk(node) if isinstance(call, ast.Call)
                        and getattr(call.func, 'id', '') == 'shown' for argument in call.args[1:]}
                    self.assertEqual([each.value for each in ast.walk(node) if isinstance(each, ast.Constant)
                                      and isinstance(each.value, (int, float)) and not isinstance(each.value, bool)
                                      and id(each) not in allowed], [])
                    self.assertFalse({each.value.id for each in ast.walk(node) if isinstance(each, ast.Attribute)
                                      and isinstance(each.value, ast.Name)} & {'math', 'chemistry'})

    def test_what_a_switch_deleted_is_gone(self):
        for name, functions in DELETED.items():
            tree = ast.parse((ROOT / name).read_text(encoding='utf-8'))
            defined = {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
            with self.subTest(module=name):
                self.assertEqual(sorted(defined & set(functions)), [])

    def test_the_chemistry_names_are_the_cores(self):
        for name in ('equilibria', 'solve', 'oxygen_solubility', 'co2_from_air', 'pressure_atm', 'nh3_fraction',
                     'k1_sws', 'kw_total', 'kb_total', 'k_h2s_total', 'ksp_calcite', 'MG_CACO3_PER_MEQ',
                     'MG_CO2_PER_MMOL', 'H2S_PER_S'):
            with self.subTest(name=name):
                self.assertIs(getattr(chemistry, name), getattr(native, name))
        self.assertIs(chemistry._free_to_total, native.free_to_total)

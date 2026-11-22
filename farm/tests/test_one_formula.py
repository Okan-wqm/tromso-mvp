"""One formula (owner rule): a formula lives in the Rust core only (chemcore/core/src), and the Python modules that
used to hold it keep their names as doors to it, with no arithmetic of their own. A module is listed here in the
commit that switches it to the core and deletes its Python bodies (README, Water-chemistry core)."""
import ast
import re
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
                      'farm/water/charts.py': ['bands', 'saturation_index', 'plots'],
                      'farm/water/calculation.py': ['judge_step']}
# What a switch deleted: the module must not hold it any more (one formula, in the core).
DELETED = {'farm/water/deffeyes.py': ['_axis', '_clip', '_cross', 'clip_to_box', 'clip_segment', 'clip_polyline',
                                     '_isoline_segment', '_half', 'co2_curve', '_co2_region', 'omega_line',
                                     '_toxic_region', '_nh3_note', '_h2s_note'],
           'farm/water/dosing.py': ['molar_mass', '_dose', 'recipe', '_below_air', 'direction_line', 'angle', 'unit_move'],
           'farm/water/charts.py': ['widen', 'grid', '_verticals',
                                    # doors nothing but the tests called (S10): charts.plots(analysis)[key]
                                    'nh3_plot', 'h2s_plot', 'carbonate_plot', 'saturation_plot'],
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


# S10, the retirement audit. The modules that were the Python chemistry and are now doors to the core.
DOORS = ['farm/water/chemistry.py', 'farm/water/deffeyes.py', 'farm/water/dosing.py', 'farm/water/charts.py',
         'farm/water/calculation.py']
# The functions of the doors that compute with numbers and are not chemistry, each with why (reviewed): the picture
# (the SVG scene stays Python, S8 deferred by the owner), a unit a value is shown in, and the checks of an input.
NOT_CHEMISTRY = {
    'farm/water/deffeyes.py': {'Box.inside': 'a pixel point inside the drawn box (the scene)',
                               'isoline_colour': 'the colour ramp of an isoline (the scene)',
                               '_pairs': 'a flat array read as points (the scene)',
                               'render': 'the SVG in pixels (the scene)', '_arrow': 'an arrow head (the scene)',
                               '_star': 'the target star (the scene)',
                               'shown': 'a number rounded to a few decimals as the language writes it (display)',
                               # A monitoring card's picture (owner decisions 4 and 12): a window on the core's figure,
                               # in per cent of the picture; every border, region and the water are the core's.
                               'crossing': "where a polyline of the core's figure meets a height (the scene)",
                               'close_window': "the close view's window on the core's figure (the scene)",
                               '_simplify': 'points a pixel cannot show left out of a drawn line (the scene)',
                               '_inside': "a point inside a polygon of the core's figure (the scene)",
                               '_window_part': 'the part of a drawn segment inside the window (the scene)',
                               '_step': 'the step of an axis (the scene)',
                               'picture': "the card's picture in per cent of its size (the scene)"},
    'farm/water/dosing.py': {'Dose.mg_l': "mmol/L times the core's molar mass, the dose in g/m³ shown when no volume is "
                                          "given: the same product the core makes for the grams (dosing.rs), so the "
                                          "two cannot differ; moving it into the core would change the recorded shape "
                                          "of golden v1's dosing block",
                             'Dose.kilograms': 'grams shown as kilograms'},
    'farm/water/charts.py': {'nice_step': 'the step of an axis (the scene)',
                             '_decimals': 'the decimals of an axis label (the scene)',
                             'draw': 'a small chart in pixels (the scene)'},
    'farm/water/calculation.py': {'Calculation.final': 'counts the steps the simulator reached',
                                  'Calculation.change': "the difference of the core's values, shown",
                                  'calculate': 'counts the reagents chosen',
                                  'offers': "the altitude's accepted range (an input check)",
                                  'limit_offers': "a limit pair's order (an input check)"},
}


NUMERIC_CALLS = {'abs', 'divmod', 'max', 'min', 'pow', 'round', 'sum'}


def computes(node):
    """Arithmetic, an ordering of numbers, a numeric built-in or a call into math, an augmented assignment or a sign
    flip of a name (equality, identity and membership are not; a translated text formatted with % is words; a negative
    literal is a number, not arithmetic)."""
    if isinstance(node, ast.Call):
        return (getattr(node.func, 'id', '') in NUMERIC_CALLS
                or (isinstance(node.func, ast.Attribute) and getattr(node.func.value, 'id', '') in ('math', 'cmath')))
    if isinstance(node, ast.AugAssign):
        return True
    if isinstance(node, ast.UnaryOp):
        return isinstance(node.op, (ast.USub, ast.UAdd)) and not isinstance(node.operand, ast.Constant)
    if isinstance(node, ast.BinOp):
        return not ((isinstance(node.op, ast.Mod) and isinstance(node.left, ast.Call)
                     and getattr(node.left.func, 'id', '') in ('_', 'gettext', 'ngettext'))
                    or isinstance(node.op, ast.BitOr))
    if isinstance(node, ast.Compare):
        return any(isinstance(op, (ast.Lt, ast.LtE, ast.Gt, ast.GtE)) for op in node.ops)
    return False


def functions_of(tree):
    """{'name' or 'Class.name': FunctionDef} of a module's functions and methods."""
    found = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            found[node.name] = node
        elif isinstance(node, ast.ClassDef):
            found.update({f'{node.name}.{each.name}': each for each in node.body if isinstance(each, ast.FunctionDef)})
    return found


class RetirementTests(SimpleTestCase):
    """S10: once every function moved, no Python formula is left in the doors and no door is left without a caller."""

    def test_a_door_computes_nothing_but_what_is_listed_as_not_chemistry(self):
        for name in DOORS:
            tree = ast.parse((ROOT / name).read_text(encoding='utf-8'))
            # The module's top and the bodies of its classes outside their methods (a dataclass field's default).
            tops = [statement for statement in tree.body if not isinstance(statement, (ast.FunctionDef, ast.ClassDef))]
            tops += [statement for node in tree.body if isinstance(node, ast.ClassDef) for statement in node.body
                     if not isinstance(statement, ast.FunctionDef)]
            outside = [ast.unparse(each) for statement in tops for each in ast.walk(statement)
                       if computes(each)]
            with self.subTest(module=name, function=None):
                self.assertEqual(outside, [], 'a formula outside the core, at the top of the module')
            for function, node in functions_of(tree).items():
                found = [ast.unparse(each) for statement in node.body for each in ast.walk(statement) if computes(each)]
                with self.subTest(module=name, function=function):
                    if function in NOT_CHEMISTRY.get(name, {}):
                        self.assertTrue(found, 'listed as computing, but it no longer does: take it off the list')
                    else:
                        self.assertEqual(found, [], 'a formula outside the core (chemcore/core/src)')

    def test_every_name_a_door_gives_has_a_caller_outside_the_tests(self):
        """A door nothing calls is a dead path: it goes (the tests call what the code calls)."""
        # Every app, the templates, the browser's code and the shipped files; not the tests, the migrations, the
        # installed packages or the core's own module.
        skip = {'tests', 'migrations', 'node_modules', 'target', '.venv', 'staticfiles', '__pycache__', '.git'}
        callers = [path for pattern in ('*.py', '*.html', '*.ts', '*.js') for path in ROOT.rglob(pattern)
                   if not skip & set(path.relative_to(ROOT).parts) and path.name != 'test_one_formula.py'
                   and not path.name.startswith('test_') and path != ROOT / 'farm' / 'water' / 'native.py']
        text = {path: path.read_text(encoding='utf-8', errors='replace') for path in callers}
        for name in DOORS:
            tree = ast.parse((ROOT / name).read_text(encoding='utf-8'))
            given = set(functions_of(tree))
            given |= {alias.asname or alias.name for node in tree.body if isinstance(node, ast.ImportFrom)
                      and node.module == 'native' for alias in node.names}
            given |= {target.id for node in tree.body if isinstance(node, ast.Assign) for target in node.targets
                      if isinstance(target, ast.Name)}
            for each in sorted(given):
                short = each.split('.')[-1]
                if short.startswith('__'):
                    continue
                pattern = re.compile(rf'\b{re.escape(short)}\b')
                used = [path for path, body in text.items() if path != ROOT / name and pattern.search(body)]
                own = len(pattern.findall(text[ROOT / name]))
                with self.subTest(module=name, name=each):
                    self.assertTrue(used or own > 1, 'nothing outside the tests calls it')

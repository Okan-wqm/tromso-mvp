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

    def test_the_chemistry_names_are_the_cores(self):
        for name in ('equilibria', 'solve', 'oxygen_solubility', 'co2_from_air', 'pressure_atm', 'nh3_fraction',
                     'k1_sws', 'kw_total', 'kb_total', 'k_h2s_total', 'ksp_calcite', 'MG_CACO3_PER_MEQ',
                     'MG_CO2_PER_MMOL', 'H2S_PER_S'):
            with self.subTest(name=name):
                self.assertIs(getattr(chemistry, name), getattr(native, name))
        self.assertIs(chemistry._free_to_total, native.free_to_total)

"""A test that reads rows is a TestCase (the data-layering audit, M-1). The reference rows the migrations seed (the water's
freshness, the platform settings) are kept by the database and read without a stand-in in the code, but a
TransactionTestCase empties its worker's database when it ends: Django runs every TestCase first, then the other tests in
no set order, so a SimpleTestCase that declares a database may meet one emptied (whole suite 45386081998: 45
PlatformSettings.DoesNotExist). A SimpleTestCase may ask the database only for what no emptying removes, the schema and
the session's role, each listed here with its reason."""
import ast
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parent.parent
SKIP = {'node_modules', '.git', 'static', 'frontend', 'chemcore', 'sensors-ingest', '.venv', '.build'}

# {(module, class): reason}: a SimpleTestCase with a database that reads no row.
ALLOWED = {
    ('core/tests_commands.py', 'DevCommandTests'): "the session's database role (core.management.devtool.superuser)",
    ('farm/tests/test_size_mix_review.py', 'SizeAckConstraintMigrationTests'): "a constraint's state in pg_constraint",
}


def simple_test_cases_with_a_database():
    found = set()
    for path in sorted(ROOT.rglob('*.py')):
        relative = path.relative_to(ROOT)
        if set(relative.parts) & SKIP or not (relative.name.startswith(('test_', 'tests_')) or relative.name == 'tests.py'
                                              or 'tests' in relative.parts):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if not isinstance(node, ast.ClassDef):
                continue
            bases = {base.id if isinstance(base, ast.Name) else getattr(base, 'attr', '') for base in node.bases}
            declares = any(isinstance(item, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == 'databases' for target in item.targets) for item in node.body)
            if 'SimpleTestCase' in bases and declares:
                found.add((relative.as_posix(), node.name))
    return found


class SimpleTestCaseDatabaseTests(SimpleTestCase):
    def test_a_simple_test_case_asks_the_database_only_for_what_no_emptying_removes(self):
        self.assertEqual(simple_test_cases_with_a_database(), set(ALLOWED),
                         'A test that reads rows is a TestCase; list a SimpleTestCase here only for the schema or the role.')

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
    ('core/tests_boot.py', 'BootTests'): 'the server started as a server against the test database (the seal with '
                                         'nobody looking, review F1): it reads no row of its own',
}


def _base_names(node):
    return {base.id if isinstance(base, ast.Name) else getattr(base, 'attr', '') for base in node.bases}


def _declares_databases(node):
    """`databases = ...` or `databases: set = ...` in the class's body."""
    for item in node.body:
        targets = item.targets if isinstance(item, ast.Assign) else [item.target] if isinstance(item, ast.AnnAssign)             else []
        if any(isinstance(target, ast.Name) and target.id == 'databases' for target in targets):
            return True
    return False


def test_classes():
    """[(module, ClassDef)] of every test module."""
    for path in sorted(ROOT.rglob('*.py')):
        relative = path.relative_to(ROOT)
        if set(relative.parts) & SKIP or not (relative.name.startswith(('test_', 'tests_')) or relative.name == 'tests.py'
                                              or 'tests' in relative.parts):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if isinstance(node, ast.ClassDef):
                yield relative.as_posix(), node


def simple_classes(classes):
    """The names of the classes that are SimpleTestCases and no TestCase: SimpleTestCase itself and every class that
    derives from one of them, through the project's own bases too (by name)."""
    simple, rows = {'SimpleTestCase'}, {'TestCase', 'TransactionTestCase', 'LiveServerTestCase'}
    while True:
        grown = {node.name for _module, node in classes if _base_names(node) & simple and not _base_names(node) & rows}
        rows_grown = {node.name for _module, node in classes if _base_names(node) & rows}
        if grown <= simple and rows_grown <= rows:
            return simple - rows
        simple |= grown
        rows |= rows_grown


def simple_test_cases_with_a_database(classes=None):
    classes = list(test_classes()) if classes is None else classes
    simple = simple_classes(classes)
    return {(module, node.name) for module, node in classes if node.name in simple and _declares_databases(node)}


class SimpleTestCaseDatabaseTests(SimpleTestCase):
    def test_a_simple_test_case_asks_the_database_only_for_what_no_emptying_removes(self):
        self.assertEqual(simple_test_cases_with_a_database(), set(ALLOWED),
                         'A test that reads rows is a TestCase; list a SimpleTestCase here only for the schema or the role.')

    def test_an_annotated_databases_and_a_derived_simple_case_are_seen(self):
        tree = ast.parse(chr(10).join((
            'class Base(SimpleTestCase):', '    pass',
            'class Derived(Base):', '    databases: set = {"default"}',
            'class Rows(TestCase):', '    databases = {"default"}',
            'class RowsBase(Rows):', '    databases = {"default"}')))
        classes = [('x/tests.py', node) for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
        self.assertEqual(simple_test_cases_with_a_database(classes), {('x/tests.py', 'Derived')})

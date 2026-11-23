"""The one door to the water-chemistry core (farm/water/native.py) and the start check core.E001: the server
runs only with the chemcore build that chemcore/EXPECTED names, and never without one (no Python fallback)."""
import ast
import importlib
import sys
import types
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.core.checks import Error
from django.test import SimpleTestCase

from core import checks
from farm.water import native


class Handshake(SimpleTestCase):
    def test_the_installed_core_is_the_expected_one(self):
        self.assertEqual(checks.chemcore_matches(None), [])

    def test_expected_names_version_formula_version_and_hash(self):
        expected = native.expected()
        self.assertEqual(expected, {'version': native.version(), 'formula_version': str(native.formula_version()),
                                    'core_hash': native.core_hash()})

    def test_another_hash_stops_the_server(self):
        with mock.patch.object(native, 'core_hash', return_value='0' * 16):
            errors = checks.chemcore_matches(None)
        self.assertEqual([error.id for error in errors], ['core.E001'])
        self.assertIsInstance(errors[0], Error)
        self.assertIn('core_hash', errors[0].msg)

    def test_another_formula_version_stops_the_server(self):
        with mock.patch.object(native, 'formula_version', return_value=999):
            errors = checks.chemcore_matches(None)
        self.assertEqual([error.id for error in errors], ['core.E001'])
        self.assertIn('formula_version', errors[0].msg)

    def test_a_missing_expected_file_stops_the_server(self):
        with mock.patch.object(native, 'EXPECTED', Path(settings.BASE_DIR) / 'chemcore' / 'NO-SUCH-FILE'):
            errors = checks.chemcore_matches(None)
        self.assertEqual([error.id for error in errors], ['core.E001'])

    def test_a_malformed_expected_file_stops_the_server(self):
        with mock.patch.object(native, 'expected', side_effect=ValueError('line 2: not "name value"')):
            errors = checks.chemcore_matches(None)
        self.assertEqual([error.id for error in errors], ['core.E001'])


class NoFallback(SimpleTestCase):
    def test_without_the_module_the_door_does_not_open(self):
        try:
            with mock.patch.dict(sys.modules, {'chemcore': None}):
                with self.assertRaises(ImportError):
                    importlib.reload(native)
        finally:
            importlib.reload(native)

    def test_the_source_directory_is_not_the_module(self):
        """Without the wheel, `import chemcore` finds the checkout's chemcore/ directory as an empty namespace
        package (seen in the old runner image): the door refuses it, by name, at import."""
        empty = types.ModuleType('chemcore')
        empty.__path__ = [str(Path(settings.BASE_DIR) / 'chemcore')]
        try:
            with mock.patch.dict(sys.modules, {'chemcore': empty}):
                with self.assertRaisesRegex(ImportError, 'not installed'):
                    importlib.reload(native)
        finally:
            importlib.reload(native)

    def test_only_the_door_imports_the_core(self):
        """No module but farm/water/native.py names chemcore: one seam, nothing to bypass it."""
        base = Path(settings.BASE_DIR)
        importers = []
        for path in base.rglob('*.py'):
            if {'node_modules', '.venv', 'chemcore'} & set(path.relative_to(base).parts):
                continue
            tree = ast.parse(path.read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                names = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                         else [node.module or ''] if isinstance(node, ast.ImportFrom) else [])
                if any(name == 'chemcore' or name.startswith('chemcore.') for name in names):
                    importers.append(path.relative_to(base).as_posix())
        self.assertEqual(sorted(set(importers)), ['farm/water/native.py'])

"""No chemistry in the browser (owner amendment B2): the Deffeyes calculations are protected know-how, so no
calculation function, formula or constant may be reachable there, and no WebAssembly is ever shipped. The browser
receives finished results only.

What is shipped to the browser: everything under frontend/ (compiled into static/js), static/ and a collected
staticfiles/, and the inline scripts of the rendered pages. None of it may hold an entry of the deny-list
chemcore/guard-list.txt (the core's public names and its coefficients, generated from the code by
chemcore/scripts/gen_guard_list.py), a .wasm file or a source map. Templates are rendered on the server; only their
<script> blocks reach the browser as code, so only those are read."""
import importlib.util
import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from farm.tests.helpers import role

ROOT = Path(settings.BASE_DIR)
GUARD_LIST = ROOT / 'chemcore' / 'guard-list.txt'
SHIPPED = ['frontend', 'static', 'staticfiles']
IDENTIFIER = re.compile(r'\b[A-Za-z_][A-Za-z0-9_]*\b')
NUMBER = re.compile(r'(?<![A-Za-z0-9_.])(?:\d+\.\d+(?:[eE][-+]?\d+)?|\d+[eE][-+]?\d+)')
SCRIPT = re.compile(r'<script\b[^>]*>(.*?)</script>', re.S | re.I)


def generator():
    spec = importlib.util.spec_from_file_location('gen_guard_list', ROOT / 'chemcore' / 'scripts' / 'gen_guard_list.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def deny_list():
    names, numbers = set(), set()
    for line in GUARD_LIST.read_text(encoding='utf-8').splitlines():
        kind, _space, value = line.partition(' ')
        if kind == 'name':
            names.add(value)
        elif kind == 'number':
            numbers.add(float(value))
    return names, numbers


def chemistry_in(text):
    """The deny-list entries a text holds: names as whole identifiers, numbers by value (6320.813 or 6.320813e3)."""
    names, numbers = deny_list()
    found = sorted(set(IDENTIFIER.findall(text)) & names)
    found += sorted({literal for literal in NUMBER.findall(text) if float(literal) in numbers})
    return found


def shipped_files():
    for top in SHIPPED:
        folder = ROOT / top
        if folder.is_dir():
            yield from (path for path in sorted(folder.rglob('*')) if path.is_file())


class DenyListTests(SimpleTestCase):
    def test_the_deny_list_is_generated_from_the_code_as_it_is(self):
        self.assertEqual(GUARD_LIST.read_text(encoding='utf-8'), generator().text(ROOT),
                         'chemcore/guard-list.txt is stale: python chemcore/scripts/gen_guard_list.py > '
                         'chemcore/guard-list.txt')

    def test_the_deny_list_holds_the_formulas(self):
        names, numbers = deny_list()
        self.assertTrue({'oxygen_solubility', 'k1_sws', 'why_impossible', 'safe_zone', 'MG_CACO3_PER_MEQ'} <= names)
        self.assertTrue({6320.813, 5143.692, 157570.1, 50.04345} <= numbers)

    def test_the_scan_finds_a_name_and_a_coefficient_in_any_spelling(self):
        self.assertEqual(chemistry_in('const k = k1_sws(t, s) * 6.320813e3; // why_impossible'),
                         ['k1_sws', 'why_impossible', '6.320813e3'])
        self.assertEqual(chemistry_in('width: 520px; x="64.25"; const label = "pH 7.5";'), [])


class ShippedFilesTests(SimpleTestCase):
    def test_no_webassembly_and_no_source_map_is_shipped(self):
        for path in shipped_files():
            with self.subTest(path=path.relative_to(ROOT).as_posix()):
                self.assertNotEqual(path.suffix, '.wasm')
                self.assertFalse(path.name.endswith('.map'))

    def test_no_shipped_file_holds_chemistry(self):
        for path in shipped_files():
            try:
                text = path.read_text(encoding='utf-8')
            except UnicodeDecodeError:
                continue                     # a binary (an icon, a font): no code
            with self.subTest(path=path.relative_to(ROOT).as_posix()):
                self.assertEqual(chemistry_in(text), [])

    def test_no_template_script_holds_chemistry(self):
        for path in sorted((ROOT / 'templates').rglob('*.html')):
            scripts = '\n'.join(SCRIPT.findall(path.read_text(encoding='utf-8')))
            with self.subTest(path=path.relative_to(ROOT).as_posix()):
                self.assertEqual(chemistry_in(scripts), [])


class RenderedPagesTests(TestCase):
    """The calculator's pages, filled in, as the browser gets them: their inline scripts carry no chemistry and no
    WebAssembly is loaded."""
    values = {'temperature_c': '12', 'ph': '7', 'salinity_ppt': '1', 'alkalinity_mg_l': '80', 'tan_mg_l': '0.5',
              'total_sulfide_ug_l': '2', 'volume_m3': '1', 'target_ph': '7.5', 'target_alkalinity_mg_l': '100',
              'alkalinity_low_mg_l': '50', 'alkalinity_high_mg_l': '100', 'nh3_n_limit_mg_l': '0.0103',
              'co2_limit_mg_l': '15', 'h2s_limit_ug_l': '2', 'drawn': '1'}

    def setUp(self):
        user = get_user_model().objects.create_user('guard', 'guard@example.com', 'guard-password-1')
        user.groups.add(role('Water reader', 'view_watermeasurement'))
        self.client.force_login(user)

    def test_the_calculator_pages_carry_results_not_formulas(self):
        for name in ('farm:water_calculator', 'farm:water_calculator_results', 'farm:water_calculator_report'):
            with self.subTest(page=name):
                response = self.client.get(reverse(name), self.values)
                self.assertEqual(response.status_code, 200)
                html = response.content.decode()
                self.assertEqual(chemistry_in('\n'.join(SCRIPT.findall(html))), [])
                self.assertNotIn('.wasm', html)
                self.assertNotIn('WebAssembly', html)

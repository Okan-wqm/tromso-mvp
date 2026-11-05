"""Lean endpoints (owner amendment B2): no endpoint may be a "compute anything" API that lets a caller recover the
formulas by probing. Which views run the water chemistry on values taken from the request is worked out from the
code (below), and must be exactly the reviewed list ALLOWED, each with its reason and its permission; a new one
fails until it is reviewed here.

How a view is found to compute on request values: a view function (its first parameter `request`), with the
module's own helpers it calls, reads request.GET, request.POST or request.body, AND reaches the chemistry: a name
from farm/water/{chemistry,deffeyes,dosing,charts,calculation,native}.py, or a class (a form) whose code does."""
import ast
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import URLPattern, URLResolver, get_resolver, reverse

from farm.tests.helpers import role

ROOT = Path(settings.BASE_DIR)
CHEMISTRY_MODULES = {'chemistry', 'deffeyes', 'dosing', 'charts', 'calculation', 'native'}
SKIPPED = {'node_modules', '.venv', 'chemcore', 'migrations', 'tests', 'static', 'staticfiles'}

# url name -> why it may compute on values from the request (each refuses a user without its permission: below)
ALLOWED = {}


def python_modules():
    """(dotted module name, syntax tree) of every module of the project but tests and migrations."""
    for path in sorted(ROOT.rglob('*.py')):
        parts = path.relative_to(ROOT).with_suffix('').parts
        if set(parts) & SKIPPED or parts[-1].startswith('test'):
            continue
        yield '.'.join(parts), ast.parse(path.read_text(encoding='utf-8'))


def absolute(module, node):
    """The absolute module of an ImportFrom in `module` (a dotted name; a package is its __init__)."""
    if not node.level:
        return node.module or ''
    package = module.split('.')[:-1] if not module.endswith('__init__') else module.split('.')[:-1]
    base = package[:len(package) - node.level + 1]
    return '.'.join(base + ([node.module] if node.module else []))


def chemistry_names(module, tree):
    """The names under which a module reaches the chemistry: the chemistry modules it imports and the names it
    imports from them."""
    names = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        source = absolute(module, node)
        if source.startswith('farm.water.') and source.split('.')[2] in CHEMISTRY_MODULES:
            names |= {alias.asname or alias.name for alias in node.names}
        elif source == 'farm.water':
            names |= {alias.asname or alias.name for alias in node.names if alias.name in CHEMISTRY_MODULES}
    return names


def used_names(node):
    return {each.id for each in ast.walk(node) if isinstance(each, ast.Name)}


def reads_request(node):
    for each in ast.walk(node):
        if (isinstance(each, ast.Attribute) and each.attr in ('GET', 'POST', 'body')
                and isinstance(each.value, ast.Name) and each.value.id == 'request'):
            return True
    return False


def chemistry_classes():
    """Names of the classes (forms) whose own code reaches the chemistry."""
    found = set()
    for module, tree in python_modules():
        reach = chemistry_names(module, tree)
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and used_names(node) & reach:
                found.add(node.name)
    return found


def computing_views():
    """{(module, function)} of the views that compute on request values."""
    classes = chemistry_classes()
    found = set()
    for module, tree in python_modules():
        reach = chemistry_names(module, tree) | classes
        functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}

        def closure(name, seen):
            if name in seen or name not in functions:
                return seen
            seen.add(name)
            for called in used_names(functions[name]):
                closure(called, seen)
            return seen

        for name, node in functions.items():
            if not node.args.args or node.args.args[0].arg != 'request':
                continue
            parts = [functions[each] for each in closure(name, set())]
            if any(reads_request(part) for part in parts) and any(used_names(part) & reach for part in parts):
                found.add((module, name))
    return found


def url_names():
    """{(module, function): url name with namespace} of every URL pattern."""
    names = {}

    def walk(patterns, namespace):
        for pattern in patterns:
            if isinstance(pattern, URLResolver):
                walk(pattern.url_patterns, f'{namespace}{pattern.namespace}:' if pattern.namespace else namespace)
            elif isinstance(pattern, URLPattern) and pattern.name:
                view = getattr(pattern.callback, '__wrapped__', pattern.callback)
                while hasattr(view, '__wrapped__'):
                    view = view.__wrapped__
                names[(view.__module__, view.__name__)] = f'{namespace}{pattern.name}'

    walk(get_resolver().url_patterns, '')
    return names


class LeanEndpointsTests(SimpleTestCase):
    def test_only_the_reviewed_views_compute_on_request_values(self):
        urls = url_names()
        computing = {urls.get(view, f'(no URL) {view[0]}.{view[1]}') for view in computing_views()}
        self.assertEqual(sorted(computing), sorted(ALLOWED),
                         'A view computes the water chemistry on values from the request: review it for probing '
                         '(owner amendment B2) and add it to ALLOWED with its reason, or stop it computing.')

    def test_the_finder_sees_the_calculator(self):
        """The finder is not vacuous: it finds the calculator's form and the views that bind it."""
        self.assertIn('CalculatorForm', chemistry_classes())
        self.assertIn(('farm.water.views', 'calculator'), computing_views())


class PermissionTests(TestCase):
    def test_each_computing_view_refuses_without_its_permission(self):
        stranger = get_user_model().objects.create_user('stranger', 'stranger@example.com', 'stranger-password-1')
        stranger.groups.add(role('Tanks only', 'view_tank'))
        self.client.force_login(stranger)
        for name in ALLOWED:
            args = ['00000000-0000-0000-0000-000000000000'] if name == 'farm:water_unit_chart' else []
            with self.subTest(view=name):
                self.assertEqual(self.client.get(reverse(name, args=args), {'temperature_c': '12', 'ph': '7'}).status_code,
                                 403)

    def test_each_computing_view_sends_a_visitor_to_sign_in(self):
        for name in ALLOWED:
            args = ['00000000-0000-0000-0000-000000000000'] if name == 'farm:water_unit_chart' else []
            with self.subTest(view=name):
                response = self.client.get(reverse(name, args=args))
                self.assertIn(response.status_code, (302, 403))
                if response.status_code == 302:
                    self.assertIn(settings.LOGIN_URL, response['Location'])

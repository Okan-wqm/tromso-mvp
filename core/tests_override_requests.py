"""A test that makes a request inside `translation.override(lang)` comes out of the request with the REQUEST's language
active (LocaleMiddleware activates it and does not restore the override), so words translated after the request in
the same block are in that language, not in `lang`: a check built from them silently compares the wrong words
(found in two HR tests, 2026-11-24). This guard reads every test module and refuses a translation call that follows a
test-client request inside one override block: translate first, then request, or close the block before the request."""
import ast
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

TRANSLATING = {'_', 'gettext', 'ngettext', 'pgettext', 'npgettext', 'gettext_lazy'}


def _is_request(node):
    if not isinstance(node, ast.Call):
        return False
    name = ast.unparse(node.func)
    return 'client' in name and name.rsplit('.', 1)[-1] in {'get', 'post', 'put', 'patch', 'delete', 'head', 'options'}


def _is_translation(node):
    if not isinstance(node, ast.Call):
        return False
    name = ast.unparse(node.func)
    return name.rsplit('.', 1)[-1] in TRANSLATING or name.endswith('_said')


def offences(tree, path):
    found = []
    for block in ast.walk(tree):
        if not isinstance(block, ast.With) or not any('override' in ast.unparse(i.context_expr) for i in block.items):
            continue
        requested = False
        for statement in block.body:
            nodes = list(ast.walk(statement))
            if requested:
                found += [f'{path}:{n.lineno}' for n in nodes if _is_translation(n)]
            requested = requested or any(_is_request(n) for n in nodes)
    return found


class OverrideRequestTests(SimpleTestCase):
    def test_no_translation_follows_a_request_inside_one_override(self):
        root = Path(settings.BASE_DIR)
        found = []
        for path in sorted(root.rglob('test*.py')):
            if {'node_modules', '.venv', 'static'} & set(path.relative_to(root).parts):
                continue
            found += offences(ast.parse(path.read_text(encoding='utf-8')), path.relative_to(root).as_posix())
        self.assertEqual(found, [], 'translate before the request, or close the override block before it')

    def test_the_guard_sees_the_mistake(self):
        bad = ast.parse('with translation.override("nb"):\n    r = self.client.get("/")\n    w = _("Yes")\n')
        good = ast.parse('with translation.override("nb"):\n    w = _("Yes")\n    r = self.client.get("/")\n')
        self.assertEqual(offences(bad, 'x.py'), ['x.py:3'])
        self.assertEqual(offences(good, 'x.py'), [])

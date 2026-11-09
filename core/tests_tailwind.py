"""The console's Tailwind (docs/design/system/tailwind.md): built from frontend/tailwind.css into static/css/tw.css by the
pinned CLI (scripts/tailwind.mjs; its --check, run by CI and npm test, fails when the committed file is stale). Here what
holds without Node: the theme names the role tokens and nothing else, the build has no preflight and styles nothing
but an element that carries a `tw:` class (so the pages not redesigned stay exactly as they are), it reads every
template and app, every page loads it last, and the tool is pinned and listed."""
import json
import re
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.test import SimpleTestCase

ROOT = Path(settings.BASE_DIR)
SOURCE = ROOT / 'frontend' / 'tailwind.css'
BUILT = ROOT / 'static' / 'css' / 'tw.css'


def without_comments(css):
    return re.sub(r'/\*.*?\*/', '', css, flags=re.S)


def selectors(css):
    """The selectors of every style rule, inside @media and @supports too; at-rule heads and @property are left out."""
    found, depth_heads = [], []
    for match in re.finditer(r'([^{};]+)\{|\}', without_comments(css)):
        head = match.group(1)
        if head is None:
            if depth_heads:
                depth_heads.pop()
            continue
        head = head.strip()
        inside_property = any(h.startswith('@property') for h in depth_heads)
        if not head.startswith('@') and not inside_property and not any(h.startswith('@layer properties') for h in depth_heads):
            found += [part.strip() for part in head.split(',')]
        depth_heads.append(head)
    return found


class TailwindSourceTests(SimpleTestCase):
    def test_the_theme_names_only_the_design_systems_role_tokens(self):
        source = without_comments(SOURCE.read_text(encoding='utf-8'))
        tokens = set(re.findall(r'(--[a-z0-9-]+)\s*:', (ROOT / 'static' / 'css' / 'tokens.css').read_text(encoding='utf-8')))
        theme = re.search(r'@theme[^{]*\{(.*?)\}', source, re.S).group(1)
        colours = dict(re.findall(r'(--color-[a-z0-9-]+)\s*:\s*([^;]+);', theme))
        self.assertGreater(len(colours), 20)
        for name, value in colours.items():
            with self.subTest(colour=name):
                token = re.fullmatch(r'var\((--[a-z0-9-]+)\)', value.strip())
                self.assertIsNotNone(token, f'{name}: {value} is not a role token')
                self.assertIn(token.group(1), tokens)
        self.assertNotRegex(source, r'#[0-9A-Fa-f]{3,8}\b|rgba?\(|hsla?\(|oklch\(|oklab\(')

    def test_only_the_utilities_are_built_no_preflight_and_no_default_theme(self):
        imports = re.findall(r'@import\s+"([^"]+)"', without_comments(SOURCE.read_text(encoding='utf-8')))
        self.assertEqual(imports, ['tailwindcss/utilities.css'])

    def test_every_class_carries_the_prefix(self):
        self.assertRegex(SOURCE.read_text(encoding='utf-8'), r'@theme inline prefix\(tw\)')

    def test_the_build_reads_every_template_and_every_app(self):
        source = SOURCE.read_text(encoding='utf-8')
        self.assertIn('@source "../templates/**/*.html";', source)
        listed = set(re.search(r'@source "\.\./\{([^}]+)\}/\*\*/\*\.py";', source).group(1).split(','))
        ours = {Path(config.path).relative_to(ROOT).parts[0] for config in apps.get_app_configs()
                if Path(config.path).is_relative_to(ROOT)}
        self.assertEqual(ours - listed, set(), 'an app the build does not read for class names')


class TailwindBuildTests(SimpleTestCase):
    def test_it_is_built_and_committed(self):
        self.assertTrue(BUILT.is_file(), 'run `npm run build:css` and commit static/css/tw.css')
        self.assertTrue(BUILT.read_text(encoding='utf-8').startswith('/*! tailwindcss v'))

    def test_it_styles_only_an_element_with_a_tw_class(self):
        """No reset, no element rule, no rule on a class a template already uses: what is not redesigned is untouched."""
        found = selectors(BUILT.read_text(encoding='utf-8'))
        self.assertTrue(found, 'tw.css holds no rule: is a tw: class in a template?')
        self.assertEqual([selector for selector in found if not selector.startswith('.tw\\:')], [])

    def test_it_is_in_no_cascade_layer(self):
        """A layered utility would lose to every unlayered rule of the older sheets (base.css `a`, app.css `.content h2`)."""
        css = without_comments(BUILT.read_text(encoding='utf-8'))
        self.assertEqual(re.findall(r'@layer (?!properties)[^;{]*', css), [])


class TailwindWiringTests(SimpleTestCase):
    def test_every_page_loads_it_last(self):
        base = (ROOT / 'templates' / 'app_base.html').read_text(encoding='utf-8')
        sheets = re.findall(r"<link rel=\"stylesheet\" href=\"\{% asset '([^']+)' %\}\">", base)
        self.assertEqual(sheets[-1], 'css/tw.css')

    def test_the_tool_is_pinned_listed_and_built_by_npm_run_build(self):
        package = json.loads((ROOT / 'package.json').read_text(encoding='utf-8'))
        versions = {package['devDependencies'][name] for name in ('tailwindcss', '@tailwindcss/cli')}
        self.assertEqual(len(versions), 1)
        self.assertRegex(versions.pop(), r'^\d+\.\d+\.\d+$')
        self.assertIn('scripts/tailwind.mjs', package['scripts']['build'])
        self.assertEqual(package['scripts']['check:css'], 'node scripts/tailwind.mjs --check')
        third_party = (ROOT / 'THIRD_PARTY.md').read_text(encoding='utf-8')
        self.assertIn('`tailwindcss`, `@tailwindcss/cli`', third_party)

    def test_ci_fails_on_a_stale_build(self):
        ci = (ROOT / '.github' / 'workflows' / 'ci.yml').read_text(encoding='utf-8')
        frontend = ci[ci.index('\n  frontend:'):ci.index('\n  rust:')]
        self.assertLess(frontend.index('npm run check:css'), frontend.index('npm run build'))

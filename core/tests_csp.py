"""The Content-Security-Policy, and the pages keeping it.

Every response says where a page may load from: its own address only, scripts only from files of this project or with
the response's nonce (the import map), no inline style, no plug-ins, no frame around it. So even a name that slipped
past the escaping could not run as a script. And no page asks another site for anything: the font is served from the
project's static files (a page that loaded it from Google sent every reader's address there)."""
import re
from html.parser import HTMLParser
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from .tests_escaping import _sources
from .tests_routes import routes

HEADER = 'Content-Security-Policy'


def policy(response):
    """{directive: [sources]} of the response's policy."""
    found = {}
    for part in response[HEADER].split(';'):
        name, *values = part.split()
        found[name] = values
    return found


class Page(HTMLParser):
    """What of a page the policy rules on: its script and style elements, style attributes, handlers, addresses."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.scripts, self.styles, self.inline_styles, self.handlers, self.addresses = [], [], [], [], []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'script':
            self.scripts.append(attrs)
        if tag == 'style':
            self.styles.append(attrs)
        if 'style' in attrs:
            self.inline_styles.append(tag)
        self.handlers += [name for name in attrs if name.startswith('on')]
        for name in ('src', 'href', 'action', 'formaction', 'data'):
            if attrs.get(name):
                self.addresses.append((tag, attrs[name]))


def offences(html, nonce):
    """What on the page the policy would block, or what reaches another site."""
    page = Page()
    page.feed(html)
    found = []
    for script in page.scripts:
        if script.get('type') == 'application/json':
            continue                                                 # data, never run (json_script)
        if 'src' not in script and script.get('nonce') != nonce:
            found.append(f'an inline script without the nonce: {script}')
    found += [f'a <style> element without the nonce: {style}' for style in page.styles if style.get('nonce') != nonce]
    found += [f'a style attribute on <{tag}>' for tag in page.inline_styles]
    found += [f'an event handler attribute {name}' for name in page.handlers]
    for tag, address in page.addresses:
        if re.match(r'\s*javascript:', address, re.I):
            found.append(f'a javascript: address on <{tag}>')
        elif re.match(r'(https?:)?//', address) and tag in ('script', 'link', 'img', 'iframe', 'object', 'embed'):
            found.append(f'<{tag}> loads from another site: {address}')
    return found


class PolicyTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser('root', 'root@example.com', 'x')

    def test_every_response_carries_a_strict_policy(self):
        for signed_in in (False, True):
            if signed_in:
                self.client.force_login(self.admin)
            response = self.client.get('/accounts/login/' if not signed_in else '/')
            directives = policy(response)
            self.assertEqual(directives['default-src'], ["'self'"])
            self.assertIn("'self'", directives['script-src'])
            self.assertTrue(any(value.startswith("'nonce-") for value in directives['script-src']))
            for name in ('script-src', 'style-src', 'default-src'):
                self.assertNotIn("'unsafe-inline'", directives.get(name, []), name)
                self.assertNotIn("'unsafe-eval'", directives.get(name, []), name)
            self.assertEqual(directives['style-src'], ["'self'"])
            self.assertEqual(directives['font-src'], ["'self'"])
            self.assertEqual(directives['object-src'], ["'none'"])
            self.assertEqual(directives['base-uri'], ["'none'"])
            self.assertEqual(directives['frame-ancestors'], ["'none'"])
            self.assertEqual(directives['form-action'], ["'self'"])

    def test_the_import_map_carries_the_response_nonce(self):
        self.client.force_login(self.admin)
        response = self.client.get('/')
        nonce = re.search(r"'nonce-([^']+)'", response[HEADER]).group(1)
        self.assertRegex(response.content.decode(), rf'<script type="importmap" nonce="{re.escape(nonce)}">')
        second = self.client.get('/')
        self.assertNotEqual(re.search(r"'nonce-([^']+)'", second[HEADER]).group(1), nonce)

    def test_every_page_without_arguments_keeps_the_policy(self):
        """Every route that takes no record, opened by the platform admin (who sees every part of every page): nothing
        on it is blocked by its own policy, and nothing is loaded from another site."""
        self.client.force_login(self.admin)
        found = {}
        for route in routes():
            if route.takes_record or route.name in ('logout',):
                continue
            for headers in ({}, {'X-Modal': '1'}):
                response = self.client.get(route.path, headers=headers)
                if response.status_code != 200 or 'text/html' not in response.get('Content-Type', ''):
                    continue
                self.assertIn(HEADER, response, route)
                match = re.search(r"'nonce-([^']+)'", response[HEADER])
                problems = offences(response.content.decode(), match.group(1) if match else None)
                if problems:
                    found[f'{route}{" (dialog)" if headers else ""}'] = problems
        self.assertEqual(found, {})


class TemplateTests(SimpleTestCase):
    """The templates themselves: what a page holds only with data (a capacity bar, a card's widgets) is checked here."""

    def test_no_template_holds_what_the_policy_blocks(self):
        found = []
        for name, path in _sources('*.html'):
            text = path.read_text(encoding='utf-8')
            for problem in offences(re.sub(r'\{[{%#].*?[%}#]\}', 'x', text, flags=re.S), nonce='x'):
                found.append(f'{name}: {problem}')
            if re.search(r'<script(?![^>]*\bsrc=)(?![^>]*application/json)[^>]*>', text):
                found.append(f'{name}: an inline script')
        self.assertEqual(found, [])

    def test_no_template_loads_anything_from_another_site(self):
        found = [name for name, path in _sources('*.html')       # a link to follow (a DOI) loads nothing
                 if re.search(r'<(script|link|img|iframe|source|object|embed)\b[^>]*\b(src|href|data)="(https?:)?//',
                              path.read_text(encoding='utf-8'))]
        self.assertEqual(found, [])


class FontTests(SimpleTestCase):
    def test_the_font_is_served_from_the_projects_static_files_with_its_licence(self):
        static = Path(settings.BASE_DIR) / 'static'
        css = (static / 'css' / 'base.css').read_text(encoding='utf-8')
        faces = re.findall(r'@font-face\s*\{(.*?)\}', css, re.S)
        self.assertTrue(faces)
        for face in faces:
            self.assertIn('Bricolage Grotesque', face)
            for url in re.findall(r'url\(["\']?([^)"\']+)', face):
                self.assertFalse(url.startswith(('http:', 'https:', '//')), url)
                self.assertTrue((static / 'css' / url).resolve().is_file(), url)
        self.assertTrue((static / 'fonts' / 'OFL.txt').is_file())
        third_party = (Path(settings.BASE_DIR) / 'THIRD_PARTY.md').read_text(encoding='utf-8')
        self.assertIn('Bricolage Grotesque', third_party)
        self.assertIn('OFL-1.1', third_party)

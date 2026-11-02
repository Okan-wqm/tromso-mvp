"""Asset URLs change whenever the file changes, so a browser cannot keep an old copy."""
import json
import os
import re
import tempfile
import time

from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.core.checks import Warning as CheckWarning
from django.test import TestCase, override_settings
from django.urls import reverse

from .checks import compiled_scripts
from .templatetags.assets import asset, module_map


def static_dir_with(*files):
    root = tempfile.mkdtemp()
    for name in files:
        path = os.path.join(root, *name.split('/'))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write('/* test */')
    return root


class AssetTagTests(TestCase):
    def setUp(self):
        self.root = static_dir_with('css/site.css', 'js/main.js', 'js/dom.js', 'img/logo.svg')
        override = override_settings(STATICFILES_DIRS=[self.root])
        override.enable()
        self.addCleanup(override.disable)
        finders.get_finder.cache_clear()
        self.addCleanup(finders.get_finder.cache_clear)

    def test_the_url_carries_the_files_modification_time_and_changes_with_it(self):
        first = asset('css/site.css')
        self.assertRegex(first, r'^/static/css/site\.css\?v=\d+$')
        path = os.path.join(self.root, 'css', 'site.css')
        os.utime(path, (time.time() + 60, time.time() + 60))
        self.assertNotEqual(asset('css/site.css'), first)

    def test_an_unknown_file_gets_its_plain_url(self):
        self.assertEqual(asset('css/missing.css'), '/static/css/missing.css')

    def test_the_import_map_versions_every_compiled_module_and_nothing_else(self):
        html = module_map()
        imports = json.loads(re.search(r'<script type="importmap">(.*)</script>', html).group(1))['imports']
        self.assertEqual(set(imports), {'/static/js/dom.js', '/static/js/main.js'})
        self.assertEqual(imports['/static/js/dom.js'], asset('js/dom.js'))


class PagesUseVersionedAssetsTests(TestCase):
    def test_console_and_sign_in_pages_link_only_versioned_assets(self):
        self.client.force_login(get_user_model().objects.create_superuser('root', 'root@example.com', 'x'))
        for html in (self.client.get(reverse('home')).content.decode(),
                     self.client.get(reverse('farm:site_list')).content.decode()):
            links = re.findall(r'(?:href|src)="(/static/[^"]+)"', html)
            self.assertTrue(links)
            for link in links:
                if finders.find(link.removeprefix('/static/').split('?')[0]):   # compiled scripts exist after a build
                    self.assertRegex(link, r'\?v=\d+$', link)
            self.assertIn('<script type="importmap">', html)
            self.assertLess(html.index('type="importmap"'), html.index('type="module"'))   # the map comes first
        self.client.logout()
        sign_in = self.client.get(reverse('login')).content.decode()
        self.assertRegex(sign_in, r'href="/static/css/auth\.css\?v=\d+"')


class BuildCheckTests(TestCase):
    def test_a_missing_build_is_reported_by_the_system_check(self):
        with override_settings(STATICFILES_DIRS=[tempfile.mkdtemp()]):
            finders.get_finder.cache_clear()
            try:
                problems = compiled_scripts(None)
            finally:
                finders.get_finder.cache_clear()
        self.assertEqual([p.id for p in problems], ['core.W001'])
        self.assertIsInstance(problems[0], CheckWarning)


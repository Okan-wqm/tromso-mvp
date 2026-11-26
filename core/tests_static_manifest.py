"""Static files under hashed names, as a production server serves them (config/settings.py STORAGES with DEBUG off,
core/templatetags/assets.py): `collectstatic` succeeds on the project's files, every asset a template names is in the
manifest under a name holding its content's hash (so the proxy may let a browser keep it for a year, deploy/proxy), and
the compiled modules reach their hashed files through the import map by the plain address their own imports use."""
import json
import re
import shutil
import tempfile
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles import finders
from django.contrib.staticfiles.storage import staticfiles_storage
from django.core.management import call_command
from django.test import SimpleTestCase, override_settings
from django.utils.functional import empty

from .templatetags.assets import asset, module_map

MANIFEST = {'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
            'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.ManifestStaticFilesStorage'}}
HASHED = re.compile(r'^/static/(?P<name>.+)\.[0-9a-f]{12}\.(?P<ext>[A-Za-z0-9]+)$')
NAMED = re.compile(r"""\{%\s*(?:asset|static)\s+['"]([^'"]+)['"]\s*%\}""")


def template_assets():
    """Every static path a template names literally ({% asset 'x' %}, {% static 'x' %}), with the template's name."""
    roots = [Path(settings.BASE_DIR) / 'templates'] + sorted(Path(settings.BASE_DIR).glob('*/templates'))
    found = {}
    for root in roots:
        for template in root.rglob('*.html'):
            for path in NAMED.findall(template.read_text(encoding='utf-8')):
                found.setdefault(path, str(template.relative_to(settings.BASE_DIR)))
    return found


class HashedStaticFilesTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.root = Path(tempfile.mkdtemp())
        cls.addClassCleanup(shutil.rmtree, cls.root, ignore_errors=True)
        override = override_settings(STATIC_ROOT=cls.root, STORAGES=MANIFEST)
        override.enable()
        cls.addClassCleanup(override.disable)
        staticfiles_storage._wrapped = empty
        cls.addClassCleanup(setattr, staticfiles_storage, '_wrapped', empty)
        call_command('collectstatic', interactive=False, verbosity=0)
        staticfiles_storage._wrapped = empty          # read the manifest just written

    def test_every_asset_a_template_names_is_served_under_a_hashed_name(self):
        named = template_assets()
        self.assertIn('css/tw.css', named)
        for path, template in sorted(named.items()):
            with self.subTest(path=path, template=template):
                url = asset(path)
                self.assertRegex(url, HASHED, f'{template} names {path}')
                self.assertTrue((self.root / url.removeprefix('/static/')).is_file(), url)

    def test_the_import_map_sends_each_module_by_its_plain_address_to_its_hashed_file(self):
        html = module_map({})
        imports = json.loads(re.search(r'<script type="importmap">(.*)</script>', html).group(1))['imports']
        built = sorted(p.relative_to(Path(settings.BASE_DIR) / 'static').as_posix()
                       for p in (Path(settings.BASE_DIR) / 'static' / 'js').rglob('*.js'))
        self.assertTrue(built, 'static/js is empty: run npm run build first')
        self.assertEqual(sorted(imports), [f'/static/{path}' for path in built])
        for plain, hashed in imports.items():
            match = HASHED.match(hashed)
            self.assertIsNotNone(match, hashed)
            self.assertEqual(f"/static/{match['name']}.{match['ext']}", plain)
            self.assertTrue((self.root / hashed.removeprefix('/static/')).is_file(), hashed)

    def test_the_stylesheets_name_the_hashed_fonts(self):
        fonts = (self.root / asset('css/fonts.css').removeprefix('/static/')).read_text(encoding='utf-8')
        urls = re.findall(r'url\("([^"]+)"\)', fonts)
        self.assertTrue(urls)
        for url in urls:
            self.assertRegex(url, r'^\.\./fonts/[^/]+\.[0-9a-f]{12}\.woff2$')
            self.assertTrue((self.root / 'css' / url).resolve().is_file(), url)

    def test_the_source_folders_are_not_read_for_a_page(self):
        # a production page takes its names from the manifest, not by looking at the files on every request
        finders.get_finder.cache_clear()
        with override_settings(STATICFILES_DIRS=[tempfile.mkdtemp()]):
            finders.get_finder.cache_clear()
            try:
                self.assertRegex(asset('css/tw.css'), HASHED)
                self.assertIn('/static/js/shell.js', module_map({}))
            finally:
                finders.get_finder.cache_clear()

"""The islands' entry on a server-rendered page ({% island %}, core/templatetags/assets.py), read from a fixture manifest in
Vite's format (core/testdata/islands-manifest.json), and the build checks (core.W001, core.E007 under --deploy)."""
import json
import os
import re
import tempfile
from pathlib import Path

from django.template import Context, Template
from django.test import SimpleTestCase, override_settings

from django.core.checks import Error as CheckError

from core.checks import compiled_scripts, compiled_scripts_deployed
from core.templatetags.assets import ManifestUnreadable, UnknownIsland, islands_manifest

FIXTURE = str(Path(__file__).resolve().parent / 'testdata' / 'islands-manifest.json')


def render(text, context=None):
    return Template('{% load assets %}' + text).render(Context(context or {}))


@override_settings(ISLANDS_MANIFEST=FIXTURE)
class IslandTagTests(SimpleTestCase):
    def test_the_manifest_names_each_island_with_its_chunks_once_each(self):
        found = islands_manifest()
        self.assertEqual(set(found), {'units', 'water', 'gallery'})     # gallery: core/layout_pages.py's shell-next
        self.assertEqual(found['units'], {'file': 'units-Ab12Cd34.js', 'imports': ['chunks/ui-Ef56Gh78.js', 'chunks/react-Qr78St90.js'],
                                          'css': ['assets/units-Zz99Yy88.css', 'assets/deep-Ee88Ff99.css']})
        self.assertEqual(found['water']['imports'], ['chunks/ui-Ef56Gh78.js', 'chunks/react-Qr78St90.js', 'chunks/uplot-Mn34Op56.js'])
        self.assertEqual(found['water']['css'], ['assets/deep-Ee88Ff99.css'])      # a stylesheet two imports deep (review M5)

    def test_an_island_is_its_root_its_props_as_data_and_its_module(self):
        html = render('{% island "units" props label="Loading the units…" %}', {'props': {'rows': [{'code': 'HA-K01'}]}})
        self.assertIn('<div class="ui-island" data-island="units" data-props="island-units-1"><p class="ui-loading" role="status">'
                      'Loading the units…</p></div>', html)
        self.assertIn('<script id="island-units-1" type="application/json">{"rows": [{"code": "HA-K01"}]}</script>', html)
        self.assertIn('<link rel="stylesheet" href="/static/islands/assets/units-Zz99Yy88.css">', html)
        self.assertIn('<link rel="modulepreload" href="/static/islands/chunks/ui-Ef56Gh78.js">', html)
        self.assertIn('<script type="module" src="/static/islands/units-Ab12Cd34.js"></script>', html)
        self.assertNotIn('style=', html)

    def test_props_can_never_close_the_data_block_or_run(self):
        html = render('{% island "units" props %}', {'props': {'name': '</script><script>alert(1)</script>'}})
        self.assertNotIn('</script><script>alert(1)', html)
        block = re.search(r'<script id="island-units-1" type="application/json">(.*?)</script>', html).group(1)
        self.assertEqual(json.loads(block), {'name': '</script><script>alert(1)</script>'})

    def test_two_roots_of_one_island_load_its_module_once(self):
        html = render('{% island "units" a %}{% island "units" b %}{% island "water" a %}', {'a': {}, 'b': {}})
        self.assertEqual(html.count('src="/static/islands/units-Ab12Cd34.js"'), 1)
        self.assertEqual(re.findall(r'data-props="([^"]+)"', html), ['island-units-1', 'island-units-2', 'island-water-3'])

    def test_an_unknown_island_fails_loudly(self):
        with self.assertRaises(UnknownIsland):
            render('{% island "nothing" %}')


class IslandBuildCheckTests(SimpleTestCase):
    def test_no_manifest_is_a_missing_build_and_an_empty_one_is_a_build_without_islands(self):
        folder = tempfile.mkdtemp()
        missing = os.path.join(folder, 'manifest.json')
        with override_settings(ISLANDS_MANIFEST=missing):
            self.assertIsNone(islands_manifest())
            self.assertIn('manifest.json', ' '.join(problem.msg for problem in compiled_scripts(None)))
        with open(missing, 'w', encoding='utf-8') as handle:
            handle.write('{}\n')
        with override_settings(ISLANDS_MANIFEST=missing):
            self.assertEqual(islands_manifest(), {})
            self.assertNotIn('manifest.json', ' '.join(problem.msg for problem in compiled_scripts(None)))

    def test_a_manifest_cut_short_is_reported_not_a_crash_and_stops_a_deployment(self):
        folder = tempfile.mkdtemp()
        cut = os.path.join(folder, 'manifest.json')
        with open(cut, 'w', encoding='utf-8') as handle:
            handle.write('{"frontend/islands/units.tsx": {"file": "units-')
        with override_settings(ISLANDS_MANIFEST=cut):
            warned = compiled_scripts(None)
            self.assertEqual([problem.id for problem in warned], ['core.W001'])
            self.assertIn('cannot be read', warned[0].msg)
            stopped = compiled_scripts_deployed(None)
            self.assertEqual([(problem.id, problem.level) for problem in stopped], [('core.E007', CheckError.level)])
            with self.assertRaises(ManifestUnreadable):
                render('{% island "units" %}')
        missing = os.path.join(folder, 'none.json')
        with override_settings(ISLANDS_MANIFEST=missing):
            self.assertEqual([problem.id for problem in compiled_scripts_deployed(None)], ['core.E007'])

    def test_the_manifest_is_no_dot_file_so_collectstatic_takes_it(self):
        from django.conf import settings
        from core.templatetags.assets import MANIFEST
        self.assertEqual(MANIFEST, 'islands/manifest.json')
        config = (Path(settings.BASE_DIR) / 'vite.config.mjs').read_text(encoding='utf-8')
        self.assertIn("manifest: 'manifest.json'", config)

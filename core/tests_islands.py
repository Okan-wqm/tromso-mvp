"""The islands' entry on a server-rendered page ({% island %}, core/templatetags/assets.py), read from a fixture manifest in
Vite's format (core/testdata/islands-manifest.json), and the build check (core.W001)."""
import json
import os
import re
import tempfile
from pathlib import Path

from django.template import Context, Template
from django.test import SimpleTestCase, override_settings

from core.checks import compiled_scripts
from core.templatetags.assets import UnknownIsland, islands_manifest

FIXTURE = str(Path(__file__).resolve().parent / 'testdata' / 'islands-manifest.json')


def render(text, context=None):
    return Template('{% load assets %}' + text).render(Context(context or {}))


@override_settings(ISLANDS_MANIFEST=FIXTURE)
class IslandTagTests(SimpleTestCase):
    def test_the_manifest_names_each_island_with_its_chunks_once_each(self):
        found = islands_manifest()
        self.assertEqual(set(found), {'units', 'water', 'sensor-charts'})
        self.assertEqual(found['units'], {'file': 'units-Ab12Cd34.js', 'imports': ['chunks/ui-Ef56Gh78.js', 'chunks/react-Qr78St90.js'],
                                          'css': ['assets/units-Zz99Yy88.css']})
        self.assertEqual(found['water']['imports'], ['chunks/ui-Ef56Gh78.js', 'chunks/react-Qr78St90.js', 'chunks/uplot-Mn34Op56.js'])

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

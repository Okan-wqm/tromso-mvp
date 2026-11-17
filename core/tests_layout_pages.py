"""The parts the browser layout test lays out are what the templates print now (core/layout_pages.py): a template changed
without `manage.py layout_pages` fails here, so the browser test never checks markup the pages no longer have."""
from django.core.management import call_command
from django.test import SimpleTestCase

from . import layout_pages


class LayoutPagesTests(SimpleTestCase):
    def test_the_committed_parts_are_what_the_templates_print_now(self):
        self.assertEqual(layout_pages.stale(), [], 'run `manage.py layout_pages` and commit the result')
        call_command('layout_pages', '--check', verbosity=0)

    def test_the_parts_are_the_real_templates(self):
        pages = layout_pages.rendered()
        self.assertIn('class="table-wrap"', pages['stock.html'])
        self.assertIn('class="wq-source"', pages['water.html'])
        self.assertIn('lang="nb"', pages['card-nb.html'])
        self.assertIn('class="form-actions"', pages['approve.html'])
        for name in ('wall-small-en.html', 'wall-small-tr.html'):
            self.assertIn('data-key="band"', pages[name])
            self.assertEqual(pages[name].count('<article class="monitor-card '), 20)
            self.assertIn('is-fit mw-31 mh-12', pages[name])
            self.assertIn('class="monitor-ph-window', pages[name])
        self.assertIn('lang=', pages['card-nb.html'])
        self.assertNotEqual(pages['wall-small-en.html'], pages['wall-small-tr.html'])
        # the pane of a unit gone into: the dock's own markup around its Big card
        self.assertIn('class="monitor-window monitor-pane"', pages['dock-big-tr.html'])
        self.assertIn('is-fit mw-48 mh-61', pages['dock-big-tr.html'])
        self.assertIn('class="monitor-chart-svg', pages['dock-big-tr.html'])
        self.assertIn('id="open-', pages['wall-small-tr.html'])

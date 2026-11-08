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

"""The parts the browser layout test lays out are what the templates print now (core/layout_pages.py): a template changed
without `manage.py layout_pages` fails here, so the browser test never checks markup the pages no longer have."""
from django.core.management import call_command
from django.test import TestCase

from . import layout_pages


class LayoutPagesTests(TestCase):
    # A TestCase: the water's freshness rules are the rows the migrations seed, read without a stand-in (the data-layering
    # audit, M-1), and a TestCase runs before any TransactionTestCase empties its worker's database.

    def test_the_committed_parts_are_what_the_templates_print_now(self):
        self.assertEqual(layout_pages.stale(), [], 'run `manage.py layout_pages` and commit the result')
        call_command('layout_pages', '--check', verbosity=0)

    def test_the_parts_are_the_real_templates(self):
        pages = layout_pages.rendered()
        self.assertIn('class="table-wrap"', pages['stock.html'])
        self.assertIn('class="wq-source"', pages['water.html'])
        self.assertIn('lang="nb"', pages['card-nb.html'])
        self.assertIn('class="form-actions"', pages['approve.html'])
        # the Reports page's strip: twelve link tabs (all, five urgent kinds, six scheduled), the current one a scheduled kind
        self.assertEqual(pages['report-tabs.html'].count('class="ui-tab"'), 12)
        self.assertIn('href="/reports/?kind=smolt" aria-current="page">Smolt', pages['report-tabs.html'])
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
        # the strip beside the wall: its units lead to Monitoring; with an open alarm, one link each
        from django.urls import reverse
        monitor, alarms = reverse('monitoring:monitor'), reverse('alarms:alarm_list')
        self.assertIn(f'<a class="ui-strip-item" href="{monitor}" data-strip="alarms" data-status="critical">',
                      pages['strip-units.html'])
        self.assertIn(f'href="{alarms}" data-strip-part="alarms">1 open alarm</a>', pages['strip-split.html'])
        self.assertIn(f'href="{monitor}" data-strip-part="units">', pages['strip-split.html'])

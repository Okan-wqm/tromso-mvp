"""The page characterisation (core/pagesays.py): what it reads from an old page, and what it counts as carried by a
new page's payload."""
from django.test import SimpleTestCase

from .pagesays import says, unsaid

OLD = """<html><body><nav><a href="/menu/">Menu</a></nav>
<main class="content"><h1>Storage locations</h1>
<script>var x = "never said";</script>
<table><tr><th>Location</th><th>On hand now</th></tr>
<tr><td><a href="/storage-locations/1/">Feed store 1</a> <span>FS-01</span></td><td>920 kg<span>1 lot</span></td></tr>
<tr><td>Silo 2</td><td>0</td></tr><tr><td>Silo 3</td><td>0</td></tr></table>
<form><input type="search" name="q" placeholder="Search storage locations"><input type="hidden" name="csrf" value="t">
</form></main><footer>Not content</footer></body></html>"""


class SaysTests(SimpleTestCase):
    def test_only_the_main_is_read_its_runs_links_and_controls_never_scripts_or_hidden_fields(self):
        items = says(OLD)
        self.assertIn(('text', 'Storage locations'), items)
        self.assertIn(('href', '/storage-locations/1/'), items)
        self.assertIn(('control', 'q'), items)
        self.assertIn(('text', 'Search storage locations'), items)
        self.assertIn(('text', '920 kg'), items)
        self.assertIn(('text', '1 lot'), items)
        for absent in ('Menu', '/menu/', 'never said', 'Not content', 'csrf'):
            self.assertNotIn(absent, [value for _kind, value in items])

    def test_a_payload_carrying_every_fact_leaves_nothing_unsaid(self):
        payload = {'title': 'Storage locations', 'search': {'name': 'q', 'placeholder': 'Search storage locations'},
                   'columns': ['Location', 'On hand now'],
                   'rows': [{'name': 'Feed store 1', 'code': 'FS-01', 'url': '/storage-locations/1/',
                             'onHand': '920 kg', 'lots': '1 lot'},
                            {'name': 'Silo 2', 'onHand': '0'}, {'name': 'Silo 3', 'onHand': '0'}]}
        self.assertEqual(unsaid(OLD, payload), [])

    def test_a_dropped_column_link_or_repeated_figure_is_unsaid(self):
        payload = {'title': 'Storage locations', 'search': {'name': 'q', 'placeholder': 'Search storage locations'},
                   'columns': ['Location'],
                   'rows': [{'name': 'Feed store 1', 'code': 'FS-01', 'onHand': '920 kg', 'lots': '1 lot'},
                            {'name': 'Silo 2', 'onHand': '0'}, {'name': 'Silo 3'}]}
        self.assertEqual(unsaid(OLD, payload),
                         [('text', 'On hand now'), ('href', '/storage-locations/1/'), ('text', '0')])

    def test_a_bare_figure_is_never_found_inside_a_longer_text(self):
        old = '<main><p>3</p><p>kg on hand</p></main>'
        self.assertEqual(unsaid(old, {'note': '3 kg on hand, 13 lots'}), [('text', '3')])

    def test_an_ignored_text_is_left_out_by_name(self):
        self.assertEqual(unsaid('<main><p>Filter</p></main>', {}, ignore={'Filter'}), [])

    def test_the_new_pages_own_markup_around_its_island_counts_too(self):
        old = '<main><h1>Overview</h1><p>2</p></main>'
        self.assertEqual(unsaid(old, {'figure': '2'}), [('text', 'Overview')])
        self.assertEqual(unsaid(old, {'figure': '2'}, new_html='<main><h1>Overview</h1><div data-island="x"></div></main>'), [])

    def test_a_run_of_only_punctuation_is_layout_not_a_fact(self):
        old = '<main><p>by admin <span>·</span> 24.11.2026</p><p><del>14</del> <span>→</span> <ins>31</ins></p></main>'
        self.assertEqual([value for _kind, value in says(old)], ['by admin', '24.11.2026', '14', '31'])

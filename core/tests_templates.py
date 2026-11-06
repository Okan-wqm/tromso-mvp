"""Template rules every page relies on."""
import re
from html.parser import HTMLParser
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

# Django's {# #} comment is one line only: a {# that does not close on its own line is printed on the
# page as text (it once showed in the unit drawer). Longer comments use {% comment %} … {% endcomment %}.
OPEN_COMMENT = re.compile(r'\{#(?!.*#\})')


class TemplateCommentTests(SimpleTestCase):
    def test_no_comment_spans_lines(self):
        found = []
        for directory in [*settings.TEMPLATES[0]['DIRS'], *Path(settings.BASE_DIR).glob('*/templates')]:
            for path in sorted(Path(directory).rglob('*.html')):
                for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
                    if OPEN_COMMENT.search(line):
                        found.append(f'{path.relative_to(settings.BASE_DIR)}:{number}')
        self.assertEqual(found, [], 'a {# comment must close on its own line; use {% comment %} for longer ones')


# ---- the shared parts of a page, read from the templates and the style sheets ----------------------------------------
VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'source', 'track', 'wbr'}
TEMPLATE_CODE = re.compile(r'\{%.*?%\}|\{\{.*?\}\}|\{#.*?#\}', re.S)


def templates():
    """(path relative to the project, the template's markup without its template code) of every template."""
    for directory in [*settings.TEMPLATES[0]['DIRS'], *Path(settings.BASE_DIR).glob('*/templates')]:
        for path in sorted(Path(directory).rglob('*.html')):
            yield path.relative_to(settings.BASE_DIR).as_posix(), TEMPLATE_CODE.sub('', path.read_text(encoding='utf-8'))


class Outline(HTMLParser):
    """The open elements while a template is read: `found` collects what `check(tag, classes, stack)` reports."""
    def __init__(self, check):
        super().__init__()
        self.check, self.stack, self.found = check, [], []

    def handle_starttag(self, tag, attrs):
        classes = (dict(attrs).get('class') or '').split()
        problem = self.check(tag, classes, self.stack)
        if problem:
            self.found.append((self.getpos()[0], problem))
        if tag not in VOID:
            self.stack.append((tag, classes, []))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break


def outline(check):
    found = []
    for name, markup in templates():
        reader = Outline(check)
        reader.feed(markup)
        found += [f'{name}:{line} {problem}' for line, problem in reader.found]
    return found


class PagePartsTests(SimpleTestCase):
    def test_every_table_scrolls_in_the_shared_frame(self):
        """A table is printed in a .table-wrap: the frame that scrolls a wide table inside itself and shows that more of
        it lies to a side (static/css/components.css), so no table widens the page or hides its last columns unseen."""
        def check(tag, classes, stack):
            if tag == 'table' and not any('table-wrap' in open_classes for _, open_classes, _ in stack):
                return 'a table outside a .table-wrap'
        self.assertEqual(outline(check), [])

    def test_a_forms_buttons_end_with_its_one_primary(self):
        """The buttons of a form or a dialog (.form-actions): the others first, then at most one filled button (the
        primary, or a danger button) last; a ghost button is never after it."""
        def check(tag, classes, stack):
            if 'button' not in classes:
                return None
            group = next((buttons for _, open_classes, buttons in reversed(stack) if 'form-actions' in open_classes), None)
            if group is None:
                return None
            if group and 'button-ghost' not in group[-1]:
                return 'a button after the primary one'
            group.append(classes)
        self.assertEqual(outline(check), [])


def without_minmax(value):
    """A track list without its minmax(…) groups (nested brackets and all)."""
    while (start := value.find('minmax(')) >= 0:
        depth, end = 0, start + len('minmax')
        for end in range(end, len(value)):
            depth += {'(': 1, ')': -1}.get(value[end], 0)
            if depth == 0:
                break
        value = value[:start] + value[end + 1:]
    return value


class StyleSheetTests(SimpleTestCase):
    def test_a_grid_track_never_grows_with_its_content(self):
        """A bare `1fr` track is at least as wide as its widest content (minmax(auto, 1fr)), so one long word, a wide
        table or a row of buttons in it widens the page; every fraction track is minmax(0, …)fr."""
        found = []
        for path in sorted(Path(settings.BASE_DIR, 'static', 'css').glob('*.css')):
            for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
                for value in re.findall(r'grid-template-columns:\s*([^;}]+)', line):
                    if re.search(r'\d*\.?\d+fr\b', without_minmax(value)):
                        found.append(f'{path.name}:{number} {value.strip()}')
        self.assertEqual(found, [])

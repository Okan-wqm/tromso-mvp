"""Template rules every page relies on."""
import re
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase
from django.utils import formats, translation

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


# A date or a time on the page is said in the language's own formats (config/formats/<language>/formats.py, else Django's):
# the date, the date and time, the time, a day and month, a weekday's name. A spelled format ("m/d/Y", "H:i") or a short one
# (English's SHORT_DATE_FORMAT is 10/26/2026, its TIME_FORMAT 9:04 p.m.) is a second style; inside a tag, an attribute a
# machine reads (datetime=, a date input's value, an address) is ISO.
SAID = {'DATE_FORMAT', 'DATETIME_FORMAT', 'TIME_FORMAT', 'MONTH_DAY_FORMAT', 'D', 'l'}
MACHINE = {'c', 'Y-m-d', 'U'}
DATE_FILTER = re.compile(r'\|(?:date|time):(["\'])(.*?)\1')


class DateFormatTests(SimpleTestCase):
    def test_a_page_says_dates_and_times_in_the_languages_formats(self):
        found = []
        for directory in [*settings.TEMPLATES[0]['DIRS'], *Path(settings.BASE_DIR).glob('*/templates')]:
            for path in sorted(Path(directory).rglob('*.html')):
                text = path.read_text(encoding='utf-8')
                for match in DATE_FILTER.finditer(text):
                    shape = match.group(2)
                    in_tag = text.rfind('<', 0, match.start()) > text.rfind('>', 0, match.start())
                    if shape in SAID or (shape in MACHINE and in_tag):
                        continue
                    line = text.count('\n', 0, match.start()) + 1
                    found.append(f'{path.relative_to(settings.BASE_DIR).as_posix()}:{line} {match.group(0)}')
        self.assertEqual(found, [])

    def test_every_language_shows_a_date_the_european_way_and_a_time_on_the_24_hour_clock(self):
        """Owner rule: a date shown on a page is dd.mm.yyyy, a date and time dd.mm.yyyy HH:MM, a day and month dd.mm., in
        English, Norwegian and Turkish alike (config/formats/<language>/formats.py, one place)."""
        moment = datetime(2026, 10, 6, 9, 4)
        for language in ('en', 'nb', 'tr'):
            with self.subTest(language=language), translation.override(language):
                self.assertEqual((formats.date_format(moment, 'DATE_FORMAT'), formats.time_format(moment, 'TIME_FORMAT'),
                                  formats.date_format(moment, 'DATETIME_FORMAT'),
                                  formats.date_format(moment, 'MONTH_DAY_FORMAT'),
                                  formats.date_format(moment, 'SHORT_DATE_FORMAT'),
                                  formats.date_format(moment, 'SHORT_DATETIME_FORMAT')),
                                 ('06.10.2026', '09:04', '06.10.2026 09:04', '06.10.', '06.10.2026', '06.10.2026 09:04'))


class FieldMarkupTests(SimpleTestCase):
    """One field markup for every form (templates/django/forms/field.html, which draws registration/_field.html, the
    template crud/form.html includes too): the label bound to the control, the server's own constraints on the control
    (min, max, step: the browser's check mirrors the server's rule, nothing is written twice in TypeScript), the help line
    and the errors tied to the control by aria-describedby, and aria-invalid on a field in error. Every layout Django
    offers draws the same markup."""

    def form(self):
        from django import forms

        class Reading(forms.Form):
            ph = forms.DecimalField(label='pH', min_value=0, max_value=14, decimal_places=2,
                                    help_text='Measured at the tank.')
            count = forms.IntegerField(label='Fish', min_value=1)

        reading = Reading(data={'ph': '15', 'count': ''})
        reading.is_valid()
        return reading

    def test_every_layout_draws_the_one_field_markup(self):
        from django.template.loader import render_to_string
        reading = self.form()
        drawn = {'form': str(reading), 'as_p': reading.as_p(), 'as_table': reading.as_table(), 'as_ul': reading.as_ul(),
                 'field group': reading['ph'].as_field_group() + reading['count'].as_field_group(),
                 'crud include': ''.join(render_to_string('registration/_field.html', {'field': reading[name]})
                                         for name in ('ph', 'count'))}
        for layout, html in drawn.items():
            with self.subTest(layout=layout):
                self.assertEqual(html.count('<div class="field has-error">'), 2)
                self.assertIn('<label for="id_ph">pH</label>', html)
                ph = re.search(r'<input[^>]*name="ph"[^>]*>', html).group(0)
                for attribute in ('min="0"', 'max="14"', 'step="0.01"', 'aria-invalid="true"',
                                  'aria-describedby="id_ph_helptext id_ph_error"'):
                    self.assertIn(attribute, ph)
                self.assertIn('<div class="help" id="id_ph_helptext">Measured at the tank.</div>', html)
                self.assertRegex(html, r'<ul class="errorlist" id="id_ph_error"><li>[^<]+</li></ul>')
                count = re.search(r'<input[^>]*name="count"[^>]*>', html).group(0)
                self.assertIn('min="1"', count)
                self.assertIn('aria-describedby="id_count_error"', count)

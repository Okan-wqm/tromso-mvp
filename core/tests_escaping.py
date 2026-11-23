"""Text is escaped on every page: no template switches Django's escaping off, and markup reaches a page only from the
few places that build it and escape every piece of text they put in it.

A form's help text is text, not markup. Several forms write people's names into it (a task whose place was deleted,
equipment whose system was deleted), so a template that printed it raw would run whatever a site or system name holds
in the browser of the next person who opens the form."""
import re
from pathlib import Path

from django import forms
from django.conf import settings
from django.template import Context, Template
from django.template.loader import render_to_string
from django.test import SimpleTestCase

HOSTILE = '<img src=x onerror=alert(1)>'
ESCAPED = '&lt;img src=x onerror=alert(1)&gt;'

# Filters and tags that hand a value to the page unescaped.
UNESCAPED = re.compile(r'\|\s*safe(seq)?\b|\{%\s*autoescape\s+off\b')

# The only templates allowed to turn escaping off, and why. A plain-text e-mail is never read as HTML.
PLAIN_TEXT = {
    'templates/mail/invitation_body.txt': 'the invitation e-mail, sent as plain text (core.accountmail)',
    'templates/mail/reset_body.txt': 'the password reset e-mail, sent as plain text (core.accountmail)',
}

# Every place in the code that marks a string as safe markup. Each one escapes the text it puts in; the test named
# beside it proves that with hostile text. A new entry needs the same: a reason and a test.
MARKUP_BUILDERS = {
    'core/templatetags/assets.py': 'the import map: static file paths of this project only (core.tests_assets)',
    'knowledge/citation.py': 'a reference: every field escaped (CitationEscapingTests below)',
    'knowledge/search.py': 'a found passage: escaped, then only the markers become <mark> '
                           '(knowledge.tests.test_search ...test_a_passage_is_escaped_with_only_the_found_words_marked)',
    'sensors/views.py': 'a sensor chart: sensors/chart.py escapes the title and every label '
                        '(sensors.tests.test_read, the chart of a unit named <T-01>)',
}
SAFE_MARKERS = re.compile(r'\bmark_safe\(|\bSafeString\(|\bSafeText\(')


def _sources(pattern):
    root = Path(settings.BASE_DIR)
    # docs/ holds the design system's previews and the written reports, frontend/test the browser tests' fixture pages:
    # pages read beside the code, never served by it.
    skipped = {'node_modules', '.venv', 'staticfiles', '.build', 'media', 'docs', 'frontend'}
    for path in sorted(root.rglob(pattern)):
        relative = path.relative_to(root)
        if skipped & set(relative.parts):
            continue
        yield relative.as_posix(), path


class TemplateEscapingTests(SimpleTestCase):
    def test_no_template_prints_a_value_unescaped(self):
        found = []
        for name, path in [*_sources('*.html'), *_sources('*.txt')]:        # a mail's templates are .txt
            if name in PLAIN_TEXT:
                continue
            for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
                if UNESCAPED.search(line):
                    found.append(f'{name}:{number}')
        self.assertEqual(found, [], 'a template printed a value with |safe or autoescape off: text must be escaped')

    def test_the_plain_text_templates_are_there_and_go_out_as_plain_text(self):
        from core import accountmail
        self.assertEqual({f'templates/mail/{kind}_body.txt' for kind in (accountmail.INVITATION, accountmail.RESET)},
                         set(PLAIN_TEXT))
        for name in PLAIN_TEXT:
            self.assertTrue((Path(settings.BASE_DIR) / name).is_file(), name)
        # what goes out, as accountmail builds it for each kind (not a property of Django's class)
        from django.contrib.auth import get_user_model
        from django.test import override_settings
        person = get_user_model()(pk=1, username='kari', email='kari@example.com')
        with override_settings(PUBLIC_BASE_URL='https://farm.example'):
            for kind in (accountmail.INVITATION, accountmail.RESET):
                built = accountmail.message(person, kind, person, 'en', 'MQ', 'token')
                self.assertEqual((built.content_subtype, getattr(built, 'alternatives', [])), ('plain', []), kind)
                self.assertEqual(built.message().get_content_type(), 'text/plain', kind)

    def test_only_the_known_builders_mark_markup_safe(self):
        found = set()
        for name, path in _sources('*.py'):
            if '/tests' in f'/{name}' or name.split('/')[-1].startswith('test'):
                continue
            if SAFE_MARKERS.search(path.read_text(encoding='utf-8')):
                found.add(name)
        self.assertEqual(found, set(MARKUP_BUILDERS),
                         'a new place builds markup: escape every piece of text in it, add a test with hostile text, '
                         'and name it in MARKUP_BUILDERS')


class HelpForm(forms.Form):
    name = forms.CharField(help_text=f'Its place, {HOSTILE}, is deleted: choose another.')


class HelpTextTests(SimpleTestCase):
    """A help text is shown as the text it is, however the field is drawn."""

    def test_the_project_field_template_escapes_it(self):
        html = render_to_string('registration/_field.html', {'field': HelpForm()['name']})
        self.assertIn(ESCAPED, html)
        self.assertNotIn(HOSTILE, html)

    def test_every_django_form_layout_escapes_it(self):
        form = HelpForm()
        layouts = {
            '{{ form }}': Template('{{ form }}').render(Context({'form': form})),
            'as_div': form.as_div(), 'as_p': form.as_p(), 'as_table': form.as_table(), 'as_ul': form.as_ul(),
            'as_field_group': form['name'].as_field_group(),
        }
        for layout, html in layouts.items():
            with self.subTest(layout=layout):
                self.assertIn(ESCAPED, html)
                self.assertNotIn(HOSTILE, html)

    def test_markup_the_code_built_and_escaped_is_kept(self):
        from django.utils.html import format_html
        form = HelpForm()
        form.fields['name'].help_text = format_html('<b>{}</b>', HOSTILE)
        html = render_to_string('registration/_field.html', {'field': form['name']})
        self.assertIn(f'<b>{ESCAPED}</b>', html)


class CitationEscapingTests(SimpleTestCase):
    def test_every_field_of_a_reference_is_escaped(self):
        from knowledge.citation import reference
        from knowledge.models import Document
        document = Document(title=HOSTILE, authors=f'Olsen, {HOSTILE}', year=2019, venue=HOSTILE, volume=HOSTILE,
                            issue=HOSTILE, page_range=HOSTILE, url=f'https://example.org/"{HOSTILE}')
        html = str(reference(document))
        self.assertNotIn('<img', html)
        self.assertIn(ESCAPED, html)
        self.assertNotIn('"<', html)

"""A date or a moment is typed in the language's own format (config/formats/<language>/formats.py), shown back in it and
read in it, ISO accepted too: the browser's own date box says it in the browser's language (11/06/2026 09:19 AM beside
"6 Nov 2026"). Every form uses the shared inputs (core.widgets.DayInput, MomentInput) and every list's date filter the
shared reading (core.dates.read_day); no page has a browser date box."""
import re
from datetime import date, datetime
from pathlib import Path

from django import forms
from django.conf import settings
from django.test import SimpleTestCase
from django.utils import translation

from .dates import read_day
from .widgets import DayInput, MomentInput

DAY, MOMENT = date(2026, 10, 26), datetime(2026, 10, 26, 21, 4)
SHOWN = {'en': ('26 Oct 2026', '26 Oct 2026 21:04'), 'nb': ('26.10.2026', '26.10.2026 21:04'),
         'tr': ('26.10.2026', '26.10.2026 21:04')}


class Form(forms.Form):
    day = forms.DateField(widget=DayInput)
    moment = forms.DateTimeField(widget=MomentInput)


class DateInputTests(SimpleTestCase):
    def test_a_date_and_a_moment_are_shown_and_read_in_the_languages_format_and_in_iso(self):
        for language, (day, moment) in SHOWN.items():
            with self.subTest(language=language), translation.override(language):
                html = str(Form(initial={'day': DAY, 'moment': MOMENT}))
                self.assertIn(f'value="{day}"', html)
                self.assertIn(f'value="{moment}"', html)
                self.assertNotRegex(html, r'type="(date|datetime-local)"')
                for typed in ({'day': day, 'moment': moment}, {'day': '2026-10-26', 'moment': '2026-10-26 21:04'}):
                    form = Form(typed)
                    self.assertTrue(form.is_valid(), form.errors)
                    self.assertEqual((form.cleaned_data['day'], form.cleaned_data['moment'].replace(tzinfo=None)),
                                     (DAY, MOMENT))
                self.assertEqual((read_day(day), read_day('2026-10-26'), read_day('nonsense'), read_day('')),
                                 (DAY, DAY, None, None))

    def test_no_page_or_form_has_a_browser_date_box(self):
        found = []
        for path in sorted(Path(settings.BASE_DIR).rglob('*')):
            if path.suffix not in ('.html', '.py') or any(part in ('tests', 'migrations', 'node_modules', '.build')
                                                          for part in path.parts) or path.name.startswith('tests'):
                continue
            for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
                if re.search(r'''attrs=\{'type': '(date|datetime-local)'|type="(date|datetime-local)"''', line):
                    found.append(f'{path.relative_to(settings.BASE_DIR).as_posix()}:{number}')
        self.assertEqual(found, [])

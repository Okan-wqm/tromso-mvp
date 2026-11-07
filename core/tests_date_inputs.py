"""A date or a moment is typed and shown the European way in every language (owner rule): 06.11.2026 and 06.11.2026 09:19,
day first, the 24-hour clock (config/formats/<language>/formats.py), ISO read too; never the browser's own date box, which
says it in the browser's language (11/06/2026 09:19 AM). Every form's date field takes the shared inputs
(core.widgets.DayInput, MomentInput) and reads 06.11.2026 and 06.11.2026 09:19; every list's date filter the shared
reading (core.dates.read_day)."""
import importlib
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
SHOWN = {language: ('26.10.2026', '26.10.2026 21:04') for language in ('en', 'nb', 'tr')}


def all_subclasses(cls):
    for sub in cls.__subclasses__():
        yield sub
        yield from all_subclasses(sub)


class Form(forms.Form):
    day = forms.DateField(widget=DayInput)
    moment = forms.DateTimeField(widget=MomentInput)


class DateInputTests(SimpleTestCase):
    def test_a_date_and_a_moment_are_shown_and_read_the_european_way_in_every_language_and_iso_too(self):
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

    def test_every_forms_date_field_reads_and_shows_the_european_way(self):
        """Every form of the project (every app's forms, read from the classes, no instance needed): a date field reads
        06.11.2026 and shows it so, a date-and-time field 06.11.2026 09:19, through the shared inputs."""
        apps = ('core', 'farm', 'hr', 'reports', 'tasks', 'inventory', 'experiments', 'knowledge', 'sensors', 'monitoring',
                'messaging')
        for module in apps:
            for name in ('forms', 'views'):
                try:
                    importlib.import_module(f'{module}.{name}')
                except ModuleNotFoundError:
                    pass
        found = 0
        with translation.override('en'):
            for form in all_subclasses(forms.BaseForm):
                if form.__module__.split('.')[0] not in apps:          # the project's forms, not Django's own
                    continue
                for name, field in getattr(form, 'base_fields', {}).items():
                    if not isinstance(field, (forms.DateField, forms.DateTimeField)):
                        continue
                    found += 1
                    where = f'{form.__module__}.{form.__name__}.{name}'
                    moment = isinstance(field, forms.DateTimeField)
                    self.assertIsInstance(field.widget, MomentInput if moment else DayInput, where)
                    typed = '06.11.2026 09:19' if moment else '06.11.2026'
                    value = field.to_python(typed)
                    self.assertEqual((value.year, value.month, value.day), (2026, 11, 6), where)
                    self.assertIn(f'value="{typed}"', field.widget.render(name, value), where)
        self.assertGreater(found, 20)

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

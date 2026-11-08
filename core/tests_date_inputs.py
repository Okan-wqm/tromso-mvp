"""A date or a moment is typed and shown the European way in every language (owner rule): 06.11.2026 and 06.11.2026 09:19,
day first, the 24-hour clock (config/formats/<language>/formats.py), ISO read too; never the browser's own date box, which
says it in the browser's language (11/06/2026 09:19 AM). Every form's date field takes the shared inputs
(core.widgets.DayInput, MomentInput) and reads 06.11.2026 and 06.11.2026 09:19; every list's date filter the shared
reading (core.dates.read_day)."""
import importlib
import pkgutil
import re
from datetime import date, datetime
from pathlib import Path

from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
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
        """Every form of the project (every module of every app walked, the forms read from the classes, no instance
        needed): a date field reads 06.11.2026 and shows it so, a date-and-time field 06.11.2026 09:19, through the
        shared inputs."""
        apps = ('core', 'farm', 'hr', 'reports', 'tasks', 'inventory', 'experiments', 'knowledge', 'sensors', 'monitoring',
                'messaging')
        for app in apps:                                       # every module of every app, as a form may live anywhere
            package = importlib.import_module(app)
            for info in pkgutil.walk_packages(package.__path__, f'{app}.'):
                if not re.search(r'\.(tests?\w*|test_\w+|migrations|management)(\.|$)', info.name):
                    importlib.import_module(info.name)
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


WINDOW_TEXT = 'from 01.01.1900 to 31.12.2100'


class DateWindowAndShapeTests(SimpleTestCase):
    """read_day owns the one window of dates a page reads (01.01.1900 to 31.12.2100) and the one shape (dd.mm.yyyy, or
    ISO): a slash, a two-digit year, a date outside the window is no date; a form says the shape it wants; a moment needs
    its time (never a silent 00:00)."""

    def test_read_day_reads_only_the_european_shape_and_iso_inside_the_window(self):
        for language in ('en', 'nb', 'tr'):
            with self.subTest(language=language), translation.override(language):
                self.assertEqual((read_day('06.11.2026'), read_day('2026-11-06'), read_day('01.01.1900'),
                                  read_day('31.12.2100')),
                                 (date(2026, 11, 6), date(2026, 11, 6), date(1900, 1, 1), date(2100, 12, 31)))
                for refused in ('11/06/2026', '6/11/2026', '06-11-2026', '06.11.26', '06.11.0026', '31.12.9999',
                                '01.01.0001', '31.12.1899', '01.01.2101', '31.02.2026',
                                '٠٦.١١.٢٠٢٦', '０６.１１.２０２６', 20261106, date(2026, 11, 6), ['06.11.2026']):
                    self.assertIsNone(read_day(refused), refused)          # other digits and anything not text too

    def test_a_form_refuses_another_shape_with_the_shape_it_wants_and_a_moment_without_its_time(self):
        for typed, error in (({'day': '11/06/2026', 'moment': '06.11.2026 09:19'},
                              {'day': ['Give the date as dd.mm.yyyy, e.g. 06.11.2026.']}),
                             ({'day': '06.11.26', 'moment': '06.11.2026 09:19'},
                              {'day': ['Give the date as dd.mm.yyyy, e.g. 06.11.2026.']}),
                             ({'day': '31.12.9999', 'moment': '06.11.2026 09:19'},
                              {'day': [f'Give a date {WINDOW_TEXT}.']}),
                             ({'day': '06.11.2026', 'moment': '06.11.2026'},
                              {'moment': ['Give the date and the time as dd.mm.yyyy HH:MM, e.g. 06.11.2026 09:19.']}),
                             ({'day': '06.11.2026', 'moment': '2026-11-06'},
                              {'moment': ['Give the date and the time as dd.mm.yyyy HH:MM, e.g. 06.11.2026 09:19.']}),
                             ({'day': '06.11.2026', 'moment': '01.01.0001 09:19'},
                              {'moment': [f'Give a date {WINDOW_TEXT}.']})):
            with self.subTest(typed=typed):
                self.assertEqual(Form(typed).errors, error)


class DateFilterTests(TestCase):
    """Every list's date filter reads through read_day: a date outside the window, or not a date, is said back to the
    person (the page still answers), never a server error."""
    PAGES = (('/activity/', ('from', 'to')), ('/operations/feeding/', ('from', 'to')),
             ('/operations/feeding/?view=days', ('from', 'to')), ('/operations/harvests/', ('from', 'to')),
             ('/operations/health/treatments/', ('from', 'to')), ('/operations/health/lice/', ('from', 'to')),
             ('/operations/harvest-plan/', ('from', 'to')), ('/operations/storage/?tab=movements', ('from', 'to')),
             ('/operations/tasks/', ('from', 'to')), ('/operations/water/?view=history', ('from', 'to')),
             ('/hr/time/attendance/', ('from', 'to')), ('/hr/schedule/', ('week',)), ('/hr/overview/', ('week',)),
             ('/production/team/schedule/', ('week',)), ('/production/team/overview/', ('week',)),
             ('/production/team/attendance/', ('from', 'to')))

    def test_every_filter_says_a_date_it_cannot_read_and_never_fails(self):
        self.client.force_login(get_user_model().objects.create_superuser('root', 'root@example.com', 'x'))
        for page, names in self.PAGES:
            for name in names:
                for typed in ('31.12.9999', '01.01.0001', '11/06/2026'):
                    address = f'{page}{"&" if "?" in page else "?"}{name}={typed}'
                    with self.subTest(address=address):
                        response = self.client.get(address)
                        self.assertEqual(response.status_code, 200)
                        self.assertContains(response, f'“{typed}” is not a date this page reads')

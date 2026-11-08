"""No page fails on a malformed address (F-006, F-176, F-120): every page that takes no argument, and the pages that
read a date, a year or a message number from the address, are asked with values a person or an old link can put
there; a value a page cannot use is taken as not given (core.query), never a server error."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import URLPattern, URLResolver, get_resolver, reverse

from farm.models import ProductionDepartment, Site
from farm.tests.test_stock import make_unit
from messaging import services as messaging

# Values a person or an old link can put in an address: impossible dates, dates at the ends of the calendar, digits
# Python's str.isdigit() takes but int() does not (², ٣), numbers past a bigint, negative and empty ones.
NASTY = [
    {'from': '2026-13-45', 'to': '2026-02-30', 'week': '2026-W45', 'day': '20261106', 'date': '06.11.2026',
     'before': '²', 'after': '٣', 'year': '²', 'page': '²', 'month': '13', 'period': '2026-99', 'cursor': '-1'},
    {'from': '0001-01-01', 'to': '9999-12-31', 'week': '9999-12-31', 'day': '0001-01-01', 'date': '9999-12-31',
     'before': '99999999999999999999', 'after': '99999999999999999999', 'year': '99999', 'page': '-1'},
    {'from': '', 'to': ' ', 'week': 'x', 'before': '-5', 'after': '', 'year': '0', 'page': '99999999999999999999'},
]


def _routes(patterns=None, prefix=''):
    """(name, pattern) of every route of the project, with its namespace."""
    for pattern in get_resolver().url_patterns if patterns is None else patterns:
        if isinstance(pattern, URLResolver):
            yield from _routes(pattern.url_patterns, f'{prefix}{pattern.namespace}:' if pattern.namespace else prefix)
        elif isinstance(pattern, URLPattern) and pattern.name:
            yield f'{prefix}{pattern.name}', pattern


class EveryPageTests(TestCase):
    """Every page that takes no argument, and the pages that read a date, a year or a message number from the
    address, answered with each set of NASTY values: never a server error."""

    @classmethod
    def setUpTestData(cls):
        cls.root = get_user_model().objects.create_superuser('root', 'root@example.com', 'x')
        cls.site = Site.objects.create(name='Bergen', code='BG')
        department = ProductionDepartment.objects.create(site=cls.site, name='Hall', code='HA')
        cls.unit = make_unit('T-01', department)
        cls.conversation = messaging.create_channel(cls.root, 'Operations')

    def setUp(self):
        self.client.force_login(self.root)
        self.client.raise_request_exception = True

    def answers(self, url, **base):
        broken = []
        for params in NASTY:
            try:
                status = self.client.get(url, {**params, **base}).status_code
            except Exception as error:   # noqa: BLE001 - any exception is the server error this test is about
                broken.append(f'{url} {params}: {type(error).__name__}: {error}')
            else:
                if status >= 500:
                    broken.append(f'{url} {params}: {status}')
        return broken

    def test_no_page_without_an_argument_fails_on_a_malformed_address(self):
        broken = []
        for name, pattern in _routes():
            if pattern.pattern.converters or name in ('logout', 'set_language'):
                continue
            try:
                url = reverse(name)
            except Exception:   # noqa: BLE001 - a route that needs a keyword it does not declare as a converter
                continue
            broken += self.answers(url)
        self.assertEqual(broken, [])

    def test_the_pages_that_read_a_message_a_year_or_a_place_from_the_address(self):
        pk = self.conversation.pk
        broken = []
        for url, base in ((reverse('messaging:conversation', args=[pk]), {}), (reverse('messaging:poll', args=[pk]), {}),
                          (reverse('reports:duty_done'), {'duty': 'driftsplan', 'site': str(self.site.pk)}),
                          (reverse('farm:water'), {'unit': str(self.unit.pk), 'view': 'history'})):
            broken += self.answers(url, **base)
        self.assertEqual(broken, [])

    def test_the_database_viewer_reads_its_page_number_by_the_same_rule(self):
        # Cross review F9: str.isdecimal() took another script's digits as a page number.
        url = reverse('core:database_table', args=['sites'])
        for value in ('٣', '²', '-2', '99999999999999999999'):
            with self.subTest(value=value):
                self.assertEqual(self.client.get(url, {'page': value}).context['grid'].page_number, 1)
        self.assertEqual(self.client.get(url, {'page': '2'}).context['grid'].page_number, 2)

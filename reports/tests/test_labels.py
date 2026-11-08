"""One label registry (reports/labels.py) names every key a report's content can hold, as the report pages name it: the
key of every dict the computation writes (reports/compute, read from its code, so a new key cannot slip by), the lice stages
and a notice's narrative. Nothing falls back to the raw key. And what the pages really show: a report of every kind, computed
and rendered, every row and every difference named."""
import ast
import html
import re
from datetime import date, datetime, time, timezone as utc
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from django.utils import timezone, translation

from farm.models import HandlingPlanItem, HealthEvent
from farm.models.site import zone_of
from farm.stock import services as stock_services

from .. import compute, labels
from ..compute import lice, notices, slaughter
from ..compute.common import flatten
from ..models import Report
from ..periods import MONTH, WEEK, YEAR, Period
from .helpers import OCTOBER, WEEK_47, day
from .test_notices import NoticeTestCase


def keys_written():
    """Every string key of a dict literal in reports/compute, every string key it assigns (`content['contact'] = …`), and
    the keys it writes from a list of names. A static net only: the test below reads what the pages really show. A dict
    that fills a message (`_('… %(unit)s …') % {...}`) holds the message's placeholders, not content."""
    found = set(lice.STAGES) | set(notices.NARRATIVE) | set(slaughter.WEEKDAYS)
    for path in Path(settings.BASE_DIR, 'reports', 'compute').glob('*.py'):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        messages = {id(node.right) for node in ast.walk(tree) if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict) and id(node) not in messages:
                found |= {key.value for key in node.keys if isinstance(key, ast.Constant) and isinstance(key.value, str)}
            elif (isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Store)
                  and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str)):
                found.add(node.slice.value)
    return found - labels.NOT_CONTENT


class LabelRegistryTests(SimpleTestCase):
    def test_every_key_the_computation_writes_has_its_label(self):
        self.assertEqual(sorted(keys_written() - set(labels.FIELDS) - set(labels.RECORDS) - labels.SILENT), [])

    def test_an_unknown_key_is_never_shown_raw(self):
        self.assertEqual(labels.describe('/units/1/no_such_key', {'units': {'1': {'number': 'K-01'}}}),
                         'Unit K-01 · (unnamed figure)')


RAW_KEY = re.compile(r'^[a-z][a-z0-9_]*$')        # the shape of a content key; a code or a day of data never has it


def raw_words(label):
    """The parts of a row's label that are a content key shown as itself, or the unnamed-figure fallback."""
    known = {str(words) for words in labels.FIELDS.values()}
    return [part for part in label.split(' · ')
            if part == str(labels.UNNAMED) or (RAW_KEY.match(part) and part not in known)]


@override_settings(STOCK_BACKDATE_DAYS=3650)
class EveryKeyThatReachesAPageTests(NoticeTestCase):
    maxDiff = None
    """What the pages really show, not what the code's literals hold: a report of every kind computed from records that
    fill each optional part (the contact person every report has, a health event, an escape, a planned slaughter by
    weekday, October's stock), its print page rendered (the rows of `labels.outline`, which the sea-lice and cleaner-fish
    pages show too) and every path of its content described as a filed report's differences describe it. No row and no
    difference is a raw key or "(unnamed figure)"."""

    def setUp(self):
        super().setUp()
        self.october()
        batch = self.stock(self.m1, 3000, '200', day(9, 25))
        escaped = stock_services.record_escape(self.user, unit=self.m1, batch=batch, day=day(10, 25), count=300,
                                               cause='A net tore in the storm', found_time=time(6, 15),
                                               health_status='Healthy', recaptured=12)
        HandlingPlanItem.objects.create(kind='harvest', date=day(11, 17), unit=self.m1, batch=batch,
                                        planned_kg=Decimal(2500), facility=self.facility, created_by=self.user)
        welfare_event = HealthEvent.objects.create(site=self.sea, date=day(10, 21), kind='vet_visit',
                                                   created_by=self.user)
        narrative = {'what_happened': 'What it was', 'cause': 'Why', 'fish_dead': 3, 'fish_injured': 2,
                     'fish_involved': 40, 'situation': 'Calm now', 'measures': 'Net mended'}
        self.reports = [
            self.report(Report.Kind.SEA_LICE, Period(WEEK, date(2026, 10, 19)), site=self.sea),
            self.report(Report.Kind.SMOLT, OCTOBER),
            self.report(Report.Kind.CLEANER_FISH, OCTOBER, site=self.sea),
            self.report(Report.Kind.BIOMASS, OCTOBER, site=self.sea),
            self.report(Report.Kind.LAND_STOCK, Period(YEAR, date(2026, 1, 1))),
            self.report(Report.Kind.SITE_IN_USE, occurred_on=day(9, 20)),
            self.report(Report.Kind.SITE_EMPTIED, occurred_on=day(10, 25)),
            self.report(Report.Kind.SLAUGHTER_PLANNED, WEEK_47),
            self.report(Report.Kind.ESCAPE, site=self.sea, occurred_on=day(10, 25), escape=escaped.escape_record,
                        found_at=datetime(2026, 10, 25, 6, 15, tzinfo=utc.utc), **narrative),
            self.report(Report.Kind.DISEASE, site=self.sea, occurred_on=day(10, 20), health_event=self.event,
                        found_at=datetime(2026, 10, 20, 8, tzinfo=utc.utc), **narrative),
            self.report(Report.Kind.WELFARE, site=self.sea, occurred_on=day(10, 21), health_event=welfare_event,
                        found_at=datetime(2026, 10, 21, 8, tzinfo=utc.utc), **narrative),
        ]

    def test_every_kind_is_here(self):
        self.assertEqual({report.kind for report in self.reports}, set(compute.COMPUTE))

    def test_no_row_of_a_print_page_and_no_difference_shows_a_raw_key(self):
        found = {}
        for report in self.reports:
            content = compute.compute(report).content
            page = self.client.get(reverse('reports:report_print', args=[report.pk])).content.decode()
            rows = [html.unescape(label) for label in re.findall(r'<th scope="row">([^<]*)</th>', page)]
            self.assertTrue(rows, report.kind)
            # a filed report's differences describe the leaves of its content (reports/services.py, flatten)
            described = [labels.describe(path, content) for path in sorted(flatten(content))]
            bad = sorted({label for label in rows + described if raw_words(label)})
            if bad:
                found[report.kind] = bad
        self.assertEqual(found, {})

    def test_the_parts_the_review_found_are_named(self):
        escape = next(report for report in self.reports if report.kind == Report.Kind.ESCAPE)
        content = compute.compute(escape).content
        self.assertEqual(labels.describe('/contact/name', content), 'Contact person · Name')
        self.assertEqual(labels.describe('/escape/cause', content), 'Escape · Cause')
        with translation.override('nb'):
            self.assertEqual(labels.describe('/escape/cause', content), 'Rømming · Årsak')   # not "cause of death"
        slaughter = next(report for report in self.reports if report.kind == Report.Kind.SLAUGHTER_PLANNED)
        content = compute.compute(slaughter).content
        site_key = next(iter(content['localities']))
        code = next(iter(content['localities'][site_key]['species']))
        self.assertEqual(labels.describe(f'/localities/{site_key}/species/{code}/monday', content),
                         f'Site Fjord · Species · {code} · Monday')
        disease = next(report for report in self.reports if report.kind == Report.Kind.DISEASE)
        content = compute.compute(disease).content
        self.assertEqual(labels.describe('/health_event/units/0', content), 'Health event · Unit 1')   # M-01's number
        self.assertIn(('Health event · Units', '1'), labels.outline(content))

    def test_no_value_on_a_page_is_an_iso_date_or_time_and_found_at_is_on_the_sites_clock(self):
        """A notice's "Found at" is typed on the site's clock: the detail and print pages show it there, dd.mm.yyyy HH:MM,
        never the stored ISO instant in UTC; every date a row shows is dd.mm.yyyy. The CSV keeps the ISO instant with its
        offset (machine format, its zone said)."""
        iso = re.compile(r'\b\d{4}-\d{2}-\d{2}(T\d{2}:\d{2})?')
        found = {}
        for report in self.reports:
            for name in ('reports:report_print', 'reports:report_detail'):
                page = self.client.get(reverse(name, args=[report.pk])).content.decode()
                values = re.findall(r'<td>([^<]*)</td>', page) + re.findall(r'<dd>([^<]*)</dd>', page)
                bad = sorted({value for value in values if iso.search(value)})
                if bad:
                    found[(report.kind, name)] = bad
        self.assertEqual(found, {})
        escape = next(report for report in self.reports if report.kind == Report.Kind.ESCAPE)
        shown = timezone.localtime(escape.found_at, zone_of(self.sea)).strftime('%d.%m.%Y %H:%M')
        for name in ('reports:report_print', 'reports:report_detail'):
            self.assertContains(self.client.get(reverse(name, args=[escape.pk])), shown)
        csv_text = self.client.get(reverse('reports:report_export', args=[escape.pk, 'csv'])).content.decode()
        self.assertIn('2026-10-25T06:15:00+00:00', csv_text)


class PeriodKeyTests(SimpleTestCase):
    """A period's key in an address (?period=) is read by core.dates.read_period: four ASCII digits of a year inside the
    window of dates (1900-2100), a month 01-12, a week the year has; anything else is no period (ValueError)."""

    def test_what_it_reads_and_what_it_refuses(self):
        self.assertEqual(Period.from_key('2026-W45'), Period(WEEK, date(2026, 11, 2)))
        self.assertEqual(Period.from_key('2026-11'), Period(MONTH, date(2026, 11, 1)))
        self.assertEqual(Period.from_key('2026'), Period(YEAR, date(2026, 1, 1)))
        for key in ('1-W01', '9999-12', '0001', '1-01', '2026-13', '2026-00', '2026-W54', '2026-W00', '2026-1', '2026-W5',
                    ' 2026', '２０２６', '1899', '2101-01', '', '2026-11-01'):
            with self.subTest(key=key), self.assertRaises(ValueError):
                Period.from_key(key)

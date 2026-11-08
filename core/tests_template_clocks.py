"""Every time a page shows is on a named clock: a site's (`|site_clock:site`) or the company's (`|company_clock`), never
the server's UTC, which `|date` and `|time` fall back to for an aware moment. In the tests (settings.CLOCK_GUARD) the two
filters refuse an aware moment outright, so any page a test renders with an unclocked time fails; the machine formats
(`c`, `U`, `Y-m-d`, for a `datetime` attribute or an address) stay allowed."""
from datetime import date, datetime, time, timezone as utc

from django.conf import settings
from django.template import Context, Template
from django.test import SimpleTestCase, override_settings

from .clock_guard import UnclockedTime

MOMENT = datetime(2026, 3, 2, 8, 19, tzinfo=utc.utc)          # 09:19 in Oslo, 17:19 in Tokyo


def render(text, **values):
    return Template('{% load dates %}' + text).render(Context(values))


class TemplateClockGuardTests(SimpleTestCase):
    def test_the_guard_is_on_in_the_tests(self):
        self.assertTrue(settings.CLOCK_GUARD)

    def test_an_aware_moment_without_a_clock_is_refused(self):
        for text in ('{{ t|date:"DATETIME_FORMAT" }}', '{{ t|date }}', '{{ t|time:"TIME_FORMAT" }}',
                     '{{ t|date:"DATE_FORMAT" }}'):
            with self.subTest(text=text), self.assertRaises(UnclockedTime):
                render(text, t=MOMENT)

    def test_a_clocked_moment_a_date_a_naive_time_and_the_machine_formats_pass(self):
        self.assertEqual(render('{{ t|company_clock|date:"DATETIME_FORMAT" }}', t=MOMENT), '02.03.2026 09:19')
        self.assertEqual(render('{{ t|site_clock:"Asia/Tokyo"|time:"TIME_FORMAT" }}', t=MOMENT), '17:19')
        self.assertEqual(render('{{ t|site_clock:None|time:"TIME_FORMAT" }}', t=MOMENT), '09:19')   # no site: the company's
        self.assertEqual(render('{{ t|date:"c" }}', t=MOMENT), '2026-03-02T08:19:00+00:00')
        self.assertEqual(render('{{ d|date:"DATE_FORMAT" }} {{ n|time:"TIME_FORMAT" }}', d=date(2026, 3, 2), n=time(6)),
                         '02.03.2026 06:00')

    def test_site_clock_reads_a_site_or_a_zone(self):
        from farm.models import Site
        site = Site(name='Tokyo', code='TK', timezone='Asia/Tokyo')
        self.assertEqual(render('{{ t|site_clock:site|time:"TIME_FORMAT" }}', t=MOMENT, site=site), '17:19')
        self.assertEqual(render('{{ t|site_clock:site|time:"TIME_FORMAT" }}', t=None, site=site), '')

    @override_settings(COMPANY_TIME_ZONE='Europe/Istanbul')
    def test_company_clock_follows_the_setting(self):
        self.assertEqual(render('{{ t|company_clock|time:"TIME_FORMAT" }}', t=MOMENT), '11:19')

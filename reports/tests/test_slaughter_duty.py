"""The planned-slaughter duty is derived from the harvest, planned or done (restkontrollforskriften § 9a), stays owed after its
week has passed until the notice is filed or a person closes it with a reason, and a closure is logged and can be reopened."""
from datetime import date, datetime, timezone as utc
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.urls import reverse

from core.models import AuditLog
from farm.models import HandlingPlanItem
from farm.stock import services as stock
from farm.tests.helpers import role

from .. import compute, due, services
from ..kinds import ReportKind
from ..models import DueClosure, Report
from ..periods import WEEK, Period
from .helpers import day
from .test_due import TODAY, DueTestCase, filed


class SlaughterDutyTests(DueTestCase):
    def setUp(self):
        super().setUp()
        self.batch = self.stock(self.m1, 1000, '4000', day(10, 1))

    def plan(self, on, kilos=2500, **fields):
        return HandlingPlanItem.objects.create(kind='harvest', date=on, unit=self.m1, batch=self.batch,
                                               planned_kg=Decimal(kilos), facility=self.facility,
                                               created_by=self.user, **fields)

    def harvest(self, on, count=100):
        return stock.record_harvest(self.user, unit=self.m1, batch=self.batch, day=on, count=count,
                                    measured_weight_kg=Decimal(count * 4), facility=self.facility)

    def rows(self):
        return [row for row in due.due(TODAY).rows if row.kind == ReportKind.SLAUGHTER_PLANNED]

    def test_a_week_that_has_passed_is_still_owed_until_it_is_filed(self):
        item = self.plan(date(2026, 10, 20))
        HandlingPlanItem.objects.filter(pk=item.pk).update(created_at=datetime(2026, 10, 1, 9, tzinfo=utc.utc))
        row, = self.rows()
        self.assertEqual((row.period.key, row.overdue, row.deadline), ('2026-W43', True, date(2026, 10, 15)))
        filed(ReportKind.SLAUGHTER_PLANNED, facility=self.facility, period=row.period, **self.filed_by())
        self.assertEqual(self.rows(), [])

    def test_a_plan_already_recorded_as_a_harvest_still_owes_its_notice(self):
        item = self.plan(date(2026, 10, 20))
        operation = self.harvest(date(2026, 10, 20))
        HandlingPlanItem.objects.filter(pk=item.pk).update(operation=operation)
        self.assertEqual([row.period.key for row in self.rows()], ['2026-W43'])

    def test_a_harvest_nobody_planned_owes_the_notice_too(self):
        self.harvest(date(2026, 10, 21))
        row, = self.rows()
        self.assertEqual((row.place, row.period.key, row.overdue, row.deadline),
                         (self.facility, '2026-W43', True, date(2026, 10, 15)))
        self.assertEqual(row.start_query, {'kind': 'slaughter_planned', 'facility': self.facility.pk,
                                           'period': '2026-W43'})

    def test_what_is_not_a_duty_is_left_out(self):
        self.plan(date(2026, 10, 20), cancelled_reason='Weather')                  # cancelled
        self.plan(date(2026, 9, 10))                                                  # before the site reports (1 October)
        self.assertEqual(self.rows(), [])
        self.sea.reports_from = None
        self.sea.save()
        self.plan(date(2026, 10, 27))
        self.assertEqual(self.rows(), [])                                              # the site reports from no date

    def test_the_report_of_a_week_reads_the_unplanned_harvest_and_says_so(self):
        operation = self.harvest(date(2026, 10, 21), count=200)
        report = self.report(Report.Kind.SLAUGHTER_PLANNED, Period(WEEK, date(2026, 10, 19)))
        result = compute.compute(report)
        locality, = result.content['localities'].values()
        self.assertEqual(locality['species']['SAL']['wednesday'], 800)               # 200 fish weighed 800 kg
        self.assertEqual(result.content['items'], [str(operation.pk)])
        self.assertIn('The harvest of M-01 on 2026-10-21 was not planned: its weighed kilos are reported, late.',
                      result.warnings)
        before = compute.fingerprint(compute.scope(report))
        stock.void(self.user, operation, 'Entered twice')
        self.assertNotEqual(compute.fingerprint(compute.scope(report)), before)


class ClosureTests(DueTestCase):
    def setUp(self):
        super().setUp()
        self.batch = self.stock(self.m1, 1000, '4000', day(10, 1))
        stock.record_harvest(self.user, unit=self.m1, batch=self.batch, day=date(2026, 10, 21), count=100,
                             measured_weight_kg=Decimal(400), facility=self.facility)
        self.row = next(row for row in due.due(TODAY).rows if row.kind == ReportKind.SLAUGHTER_PLANNED)
        self.query = f'kind=slaughter_planned&facility={self.facility.pk}&period={self.row.period.key}'
        self.url = reverse('reports:due_close') + '?' + self.query

    def planned(self):
        return [row for row in due.due(TODAY).rows if row.kind == 'slaughter_planned']

    def test_closing_with_a_reason_stops_the_listing_and_is_logged_and_reopening_brings_it_back(self):
        self.assertContains(self.client.get(self.url), 'Close Planned slaughter')
        response = self.client.post(self.url, {'reason': 'The fish went to another facility'})
        self.assertEqual(response.status_code, 302)
        closure = DueClosure.objects.get()
        self.assertEqual((closure.kind, closure.facility, closure.site, closure.period_start, closure.closed_by,
                          closure.reason), ('slaughter_planned', self.facility, None, date(2026, 10, 19), self.user,
                                            'The fish went to another facility'))
        self.assertEqual(self.planned(), [])
        entry = AuditLog.objects.get(entity_type='closed report', action='create')
        self.assertEqual(entry.changes['Why it is closed'], [None, 'The fish went to another facility'])
        page = self.client.get(reverse('reports:report_list'), {'kind': 'slaughter_planned'})
        self.assertContains(page, 'Closed without filing')
        self.assertContains(page, 'The fish went to another facility')
        self.client.post(reverse('reports:due_reopen', args=[closure.pk]))
        self.assertFalse(DueClosure.objects.exists())
        self.assertTrue(self.planned())
        self.assertEqual(AuditLog.objects.filter(entity_type='closed report', action='delete').count(), 1)

    def test_a_reason_is_needed_and_nothing_else_can_be_closed(self):
        response = self.client.post(self.url, {'reason': '  '})
        self.assertEqual(response.status_code, 422)
        self.assertFalse(DueClosure.objects.exists())
        other = reverse('reports:due_close') + f'?kind=slaughter_planned&facility={self.facility.pk}&period=2026-W30'
        self.assertEqual(self.client.get(other).status_code, 404)
        with self.assertRaises(ValidationError):
            services.close_due(self.user, kind='slaughter_planned', place=self.facility,
                               period=Period(WEEK, date(2026, 7, 6)), reason='x')

    def test_the_database_holds_one_closure_with_a_reason_for_a_place_that_fits_the_kind(self):
        good = {'kind': 'slaughter_planned', 'facility': self.facility, 'period_start': date(2026, 10, 19),
                'reason': 'x'}
        DueClosure.objects.create(**good)
        for fields in ({}, {'reason': ''}, {'facility': None, 'site': self.sea}, {'kind': 'smolt'},
                       {'kind': 'escape', 'facility': None, 'site': self.sea}):
            with self.subTest(fields), self.assertRaises(IntegrityError), transaction.atomic():
                DueClosure.objects.create(**{**good, **fields})

    def test_only_who_may_change_reports_closes_one(self):
        reader = get_user_model().objects.create_user('ola', 'ola@example.com', 'x')
        reader.groups.add(role('Reader', 'view_report'))
        self.client.force_login(reader)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.url, {'reason': 'x'}).status_code, 403)
        self.assertNotContains(self.client.get(reverse('reports:report_list')), 'Close without filing')

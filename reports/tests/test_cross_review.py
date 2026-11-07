"""The cross-review's report findings (REVIEW-CROSS.md 4, 8, 9): the lice fingerprint reads a plan's harvest, so a harvest
voided after filing shows; the report list works a report's deadline out once; and a harvest recorded from a plan dated
before the site's reports-from date is owed nowhere in this system (the plan's week was the farm's to report before it
used the system), decided and tested."""
from datetime import date, datetime, timezone as utc
from decimal import Decimal
from unittest import mock

from django.test import override_settings
from django.urls import reverse

from farm.models import Batch, HandlingPlanItem
from farm.stock import services as stock

from .. import compute, due
from ..kinds import ReportKind
from ..models import Report
from ..periods import WEEK, Period
from .helpers import day
from .test_due import TODAY, DueTestCase
from .test_lice import LiceTestCase


class LiceFingerprintTests(LiceTestCase):
    def test_a_plans_harvest_voided_after_filing_changes_the_fingerprint(self):
        batch = Batch.objects.get(movements__unit=self.m1)
        item = HandlingPlanItem.objects.create(kind='harvest', date=day(11, 5), unit=self.m1, batch=batch,
                                               planned_count=10, facility=self.facility, created_by=self.user)
        operation = stock.record_harvest(self.user, unit=self.m1, batch=batch, day=day(11, 5), count=10,
                                         measured_weight_kg=Decimal(2), facility=self.facility, plan_item=item)
        before = compute.fingerprint(compute.scope(self.draft))
        stock.void(self.user, operation, 'Wrong cage')
        self.assertNotEqual(before, compute.fingerprint(compute.scope(self.draft)))


@override_settings(STOCK_BACKDATE_DAYS=3650)
class ReportListDeadlineTests(DueTestCase):
    def test_the_list_works_each_deadline_out_once(self):
        for start in (date(2026, 10, 19), date(2026, 10, 26)):
            self.report(Report.Kind.SLAUGHTER_PLANNED, Period(WEEK, start))
        with mock.patch.object(compute, 'deadline', wraps=compute.deadline) as worked_out:
            self.client.get(reverse('reports:report_list'))
        self.assertEqual(worked_out.call_count, 2)


@override_settings(STOCK_BACKDATE_DAYS=3650)
class PlanBeforeReportsFromTests(DueTestCase):
    def test_a_harvest_of_a_plan_before_the_reports_from_date_is_owed_nowhere(self):
        batch = self.stock(self.m1, 1000, '4000', day(9, 1))
        item = HandlingPlanItem.objects.create(kind='harvest', date=date(2026, 9, 28), unit=self.m1, batch=batch,
                                               planned_kg=Decimal(400), facility=self.facility, created_by=self.user)
        HandlingPlanItem.objects.filter(pk=item.pk).update(created_at=datetime(2026, 9, 1, 9, tzinfo=utc.utc))
        stock.record_harvest(self.user, unit=self.m1, batch=batch, day=date(2026, 10, 5), count=100,
                             measured_weight_kg=Decimal(400), facility=self.facility, plan_item=item)
        self.assertEqual([row for row in due.due(TODAY).rows if row.kind == ReportKind.SLAUGHTER_PLANNED], [])

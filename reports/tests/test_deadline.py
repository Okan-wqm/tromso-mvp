"""One deadline for the planned-slaughter report (audit F-101): the due list, the report list, the report's page and the
filing all read the one function, so they say the same day, and that day does not move once the harvest is done (the fast
the plan asked for still started when it did: restkontrollforskriften § 9a, "senest når fisken er satt til sulting")."""
from datetime import date, datetime, timezone as utc
from decimal import Decimal

from django.test import override_settings
from django.urls import reverse

from farm.models import HandlingPlanItem, HandlingRule, Supplier
from farm.models.handling import HandlingKind
from farm.stock import services as stock

from .. import compute, due, services
from ..kinds import ReportKind
from ..models import Report
from ..periods import WEEK, Period
from .helpers import day, previewed
from .test_due import TODAY, DueTestCase

MONDAY = date(2026, 10, 26)            # week 44; Thursday of the week before: 22 October


@override_settings(STOCK_BACKDATE_DAYS=3650)
class OneDeadlineTests(DueTestCase):
    def setUp(self):
        super().setUp()
        self.facility.operator = Supplier.objects.create(name='Fjord Slakteri AS', code='FSL', supplies=['slaughter'],
                                                         organisation_number='912345678')
        self.facility.save()
        self.batch = self.stock(self.m1, 1000, '4000', day(10, 1))
        # 120 h before Monday 26: the fish start fasting on Wednesday 21, before Thursday 22.
        HandlingRule.objects.create(kind=HandlingKind.HARVEST, species=self.salmon, min_fasting_hours=120)
        self.item = HandlingPlanItem.objects.create(kind='harvest', date=MONDAY, unit=self.m1, batch=self.batch,
                                                    planned_kg=Decimal(2500), facility=self.facility,
                                                    created_by=self.user)
        HandlingPlanItem.objects.filter(pk=self.item.pk).update(created_at=datetime(2026, 10, 1, 9, tzinfo=utc.utc))
        self.week = Period.of(WEEK, MONDAY)
        self.report_ = self.report(Report.Kind.SLAUGHTER_PLANNED, self.week)

    def due_row(self):
        rows = [row for row in due.due(TODAY).rows
                if row.kind == ReportKind.SLAUGHTER_PLANNED and row.period == self.week]
        return rows[0] if rows else None

    def readers(self):
        """The day each reader says: the due list, the report list, the report's page, the one function."""
        report = Report.objects.get(pk=self.report_.pk)
        listed = self.client.get(reverse('reports:report_list'))
        [shown] = [each for each in listed.context['objects'] if each.pk == report.pk]
        page = self.client.get(reverse('reports:report_detail', args=[report.pk]))
        row = self.due_row()
        return {'due': row.deadline if row else None, 'list': shown.deadline, 'detail': page.context['deadline'],
                'function': compute.deadline(report)}

    def test_every_reader_says_the_same_day(self):
        self.assertEqual(set(self.readers().values()), {date(2026, 10, 21)})

    def test_the_day_does_not_move_once_the_harvest_is_done(self):
        operation = stock.record_harvest(self.user, unit=self.m1, batch=self.batch, day=MONDAY, count=500,
                                         measured_weight_kg=Decimal(2000), facility=self.facility,
                                         plan_item=self.item)
        self.item.refresh_from_db()
        self.assertEqual(self.item.operation, operation)
        self.assertEqual(set(self.readers().values()), {date(2026, 10, 21)})

    def test_a_slaughter_agreed_late_is_due_the_day_it_was_agreed_everywhere(self):
        HandlingPlanItem.objects.filter(pk=self.item.pk).update(created_at=datetime(2026, 10, 23, 9, tzinfo=utc.utc))
        self.assertEqual(set(self.readers().values()), {date(2026, 10, 23)})

    def test_the_filing_keeps_the_same_day_and_the_pages_show_it_after(self):
        expected = compute.deadline(self.report_)
        services.submit(self.user, self.report_, submitted_at=datetime(2026, 11, 2, 9, 0, tzinfo=utc.utc),
                        channel='altinn', reference='AR-9', version=self.report_.version,
                        content_sha256=previewed(self.report_))
        report = Report.objects.get(pk=self.report_.pk)
        self.assertEqual((report.deadline_on, report.filed_late), (expected, True))
        HandlingRule.objects.filter(species=self.salmon).update(min_fasting_hours=24)      # a rule changed later
        readers = self.readers()
        self.assertEqual((readers['list'], readers['detail'], readers['function']), (expected, expected, expected))

"""An increased-mortality event still unexplained 14 days on raises a welfare notice (dyrehelseforskriften § 7 second
paragraph; coverage review R27): the trigger, what ends it, what it is not."""
from datetime import date

from farm.models import HealthEvent

from .. import due
from ..kinds import ReportKind
from .helpers import day
from .test_due import TODAY, DueTestCase, filed


class UnexplainedMortalityTests(DueTestCase):
    def event(self, on=date(2026, 10, 15), **fields):
        return HealthEvent.objects.create(site=self.sea, date=on, kind='mortality', **fields)

    def rows(self):
        return [row for row in due.due(TODAY).rows if row.kind == ReportKind.WELFARE]

    def test_it_is_owed_when_the_mortality_has_no_diagnosis_after_14_days(self):
        event = self.event()
        row, = self.rows()
        self.assertEqual((row.place, row.event, row.period, row.deadline), (self.sea, event, None, None))
        self.assertEqual(row.start_query, {'kind': 'welfare', 'health_event': event.pk})
        line, = [line for line in due.due(TODAY).lines_of(ReportKind.WELFARE) if line.place == self.sea]
        self.assertEqual((line.status, line.count), (due.DUE, 1))

    def test_not_before_the_14_days_have_passed(self):
        self.event(date(2026, 10, 21))                       # 13 days before 3 November
        self.assertEqual(self.rows(), [])
        self.event(date(2026, 10, 20))                       # 14 days
        self.assertEqual(len(self.rows()), 1)

    def test_a_diagnosis_or_a_closing_says_the_cause_is_clear(self):
        self.event(diagnosis='sea_lice', confirmation='confirmed')
        self.event(closed_on=day(10, 25), outcome='A blower fault; fixed')
        self.assertEqual(self.rows(), [])

    def test_a_listed_disease_is_the_disease_notice_not_this_one(self):
        self.event(diagnosis='isa', confirmation='suspected')
        self.assertEqual(self.rows(), [])
        self.assertEqual(len([row for row in due.due(TODAY).rows if row.kind == ReportKind.DISEASE]), 1)

    def test_another_kind_of_event_or_a_day_before_the_sites_reports_from_date_is_not_it(self):
        HealthEvent.objects.create(site=self.sea, date=date(2026, 10, 15), kind='observation')
        self.event(date(2026, 9, 20))
        self.assertEqual(self.rows(), [])

    def test_a_filed_notice_ends_it_and_a_draft_stays_owed(self):
        event = self.event()
        filed(ReportKind.WELFARE, self.sea, health_event=event, occurred_on=date(2026, 10, 15), **self.filed_by())
        self.assertEqual(self.rows(), [])
        other = self.event(date(2026, 10, 10))
        draft = self.report('welfare', site=self.sea, health_event=other, occurred_on=date(2026, 10, 10))
        self.assertEqual([row.report for row in self.rows()], [draft])

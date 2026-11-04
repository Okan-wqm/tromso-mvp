"""What is due (reports/due.py): which reports a site owes by its production form, type and fish, from its reports-from date
to the last closed period, minus the filed ones; the planned slaughters, escapes and diseases; the sites not set up; the filed
reports whose records changed; the list page that shows them; and `check_reports`."""
import hashlib
import io
from datetime import date, datetime, timezone as utc
from decimal import Decimal
from unittest import mock

from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse

from farm.feeding import services as feeding
from farm.models import Feed, HandlingPlanItem, HealthEvent, Site
from farm.stock import services as stock
from farm.tests.helpers import role

from .. import compute, due, integrity, services
from ..kinds import ReportKind
from ..models import Report, ReportSnapshot
from ..periods import MONTH, WEEK, YEAR, Period
from .helpers import OCTOBER, ReportTestCase, day

TODAY = date(2026, 11, 3)             # a Tuesday


def filed(kind, site=None, period=None, facility=None, **fields):
    """A report recorded as filed, with its frozen content: what a person's filing leaves."""
    values = {'submitted_at': datetime(2026, 11, 1, 9, 0, tzinfo=utc.utc), 'channel': 'altinn', 'reference': 'AR-1',
              **fields}
    report = Report.objects.create(kind=kind, site=site, facility=facility, period_start=period.start if period else None,
                                   **values)
    content = {'kind': kind}
    ReportSnapshot.objects.create(report=report, format_version=compute.FORMAT_VERSION, content=content,
                                  content_sha256=compute.content_hash(content),
                                  sources_fingerprint=hashlib.sha256(b'x').hexdigest())
    return report


class DueTestCase(ReportTestCase):
    def setUp(self):
        super().setUp()
        self.hatchery.production_form = Site.ProductionForm.SETTEFISK
        self.hatchery.reports_from = date(2026, 9, 1)
        self.hatchery.save()
        self.sea.production_form = Site.ProductionForm.MATFISK
        self.sea.reports_from = date(2026, 10, 1)
        self.sea.save()

    def rows(self, kind=None):
        found = due.due(TODAY).rows
        return [row for row in found if kind is None or row.kind == kind]

    def filed_by(self, **fields):
        return {'submitted_by': self.user, 'created_by': self.user, 'updated_by': self.user, **fields}


class SiteReportsTests(DueTestCase):
    def test_a_juvenile_site_owes_the_smolt_report_for_each_month_it_held_fish_since_its_reports_from_date(self):
        self.october()                                           # fish from 20 September
        rows = self.rows(ReportKind.SMOLT)
        self.assertEqual([(row.place, row.period.key, row.deadline, row.overdue) for row in rows], [
            (self.hatchery, '2026-09', date(2026, 10, 7), True), (self.hatchery, '2026-10', date(2026, 11, 7), False)])
        # A month with no fish before its reports-from date, nor one still open, is not owed.
        self.assertFalse(any(row.period.key in ('2026-08', '2026-11') for row in rows))

    def test_a_filed_report_is_no_longer_due_and_a_draft_stays_with_its_deadline(self):
        self.october()
        filed(ReportKind.SMOLT, self.hatchery, Period(MONTH, date(2026, 9, 1)), **self.filed_by())
        draft = self.report(Report.Kind.SMOLT, OCTOBER)
        rows = self.rows(ReportKind.SMOLT)
        self.assertEqual([(row.period.key, row.report) for row in rows], [('2026-10', draft)])

    def test_a_sea_site_owes_the_lice_weeks_it_held_salmonids_and_the_monthly_biomass(self):
        self.stock(self.m1, 1000, '100', day(10, 5))
        weeks = self.rows(ReportKind.SEA_LICE)
        self.assertEqual([row.period.key for row in weeks], ['2026-W41', '2026-W42', '2026-W43', '2026-W44'])
        self.assertEqual(weeks[0].deadline, date(2026, 10, 13))                   # Tuesday of the next week
        self.assertEqual([(row.period.key, row.deadline) for row in self.rows(ReportKind.BIOMASS)],
                         [('2026-10', date(2026, 11, 7))])
        self.assertEqual(self.rows(ReportKind.CLEANER_FISH), [])                  # no cleaner fish held

    def test_another_species_owes_no_lice_report_and_a_cleaner_species_owes_the_cleaner_report(self):
        self.salmon.official_code = 'COD'
        self.salmon.save()
        self.stock(self.m1, 1000, '100', day(10, 5))
        self.assertEqual(self.rows(ReportKind.SEA_LICE), [])
        self.salmon.cleaner_fish_type = 'lumpfish'
        self.salmon.save()
        self.assertEqual([row.period.key for row in self.rows(ReportKind.CLEANER_FISH)], ['2026-10'])
        self.assertEqual(self.rows(ReportKind.BIOMASS), [])                       # cleaner fish are not in it (D-2)

    def test_a_land_site_of_food_fish_owes_the_yearly_stock_once_the_year_has_closed(self):
        self.hatchery.production_form = Site.ProductionForm.MATFISK
        self.hatchery.reports_from = date(2025, 6, 1)
        self.hatchery.save()
        self.stock(self.k1, 100, '100', date(2025, 12, 20))
        rows = self.rows(ReportKind.LAND_STOCK)
        self.assertEqual([(row.period.key, row.deadline) for row in rows], [('2025', date(2026, 1, 7))])
        self.assertEqual(self.rows(ReportKind.SMOLT), [])

    def test_a_period_ending_before_the_reports_from_date_is_not_owed(self):
        self.october()
        self.hatchery.reports_from = date(2026, 10, 15)
        self.hatchery.save()
        self.assertEqual([row.period.key for row in self.rows(ReportKind.SMOLT)], ['2026-10'])


class NotSetUpTests(DueTestCase):
    def test_a_site_with_fish_and_no_reports_from_date_or_no_production_form_is_listed_not_hidden(self):
        self.october()
        self.hatchery.reports_from = None
        self.hatchery.save()
        self.stock(self.m1, 1000, '100', day(10, 5))
        self.sea.production_form = ''
        self.sea.save()
        found = due.due(TODAY)
        self.assertEqual([(item.site, item.reports_from, item.production_form) for item in found.not_set_up],
                         [(self.sea, False, True), (self.hatchery, True, False)])
        self.assertEqual(self.rows(ReportKind.SMOLT), [])                          # nothing is guessed for it
        self.assertTrue(self.rows(ReportKind.SEA_LICE))                            # a sea site's lice follow its fish

    def test_a_species_without_an_official_code_is_named_where_it_is_missed(self):
        self.salmon.official_code = ''
        self.salmon.save()
        self.stock(self.m1, 1000, '100', day(10, 5))
        found = due.due(TODAY)
        self.assertEqual([(item.site, item.species, item.reports_from, item.production_form)
                          for item in found.not_set_up], [(self.sea, [str(self.salmon)], False, False)])
        self.assertEqual(self.rows(ReportKind.SEA_LICE), [])               # not known to be a salmonid
        page = self.client.get(reverse('reports:report_list'))
        self.assertContains(page, f'no official code for {self.salmon}')

    def test_a_site_without_fish_is_not_listed(self):
        self.hatchery.reports_from = None
        self.hatchery.save()
        self.assertEqual(due.due(TODAY).not_set_up, [])


class NoticesTests(DueTestCase):
    def test_a_planned_slaughter_of_this_week_or_later_is_owed_per_facility_and_week(self):
        batch = self.stock(self.m1, 1000, '4000', day(10, 1))
        agreed = datetime(2026, 10, 20, 9, 0, tzinfo=utc.utc)             # long before this week's Thursday
        for on, kilos in ((date(2026, 11, 5), 2500), (date(2026, 10, 20), 100)):
            item = HandlingPlanItem.objects.create(kind='harvest', date=on, unit=self.m1, batch=batch,
                                                   planned_kg=Decimal(kilos), facility=self.facility,
                                                   created_by=self.user)
            HandlingPlanItem.objects.filter(pk=item.pk).update(created_at=agreed)
        rows = self.rows(ReportKind.SLAUGHTER_PLANNED)
        self.assertEqual([(row.place, row.period.key, row.overdue) for row in rows],
                         [(self.facility, '2026-W45', True)])                 # Thursday 29 October has passed
        self.assertEqual(rows[0].deadline, date(2026, 10, 29))
        self.assertEqual(rows[0].start_query, {'kind': 'slaughter_planned', 'facility': self.facility.pk,
                                                'period': '2026-W45'})

    def test_a_slaughter_agreed_after_its_deadline_is_owed_from_the_day_it_was_agreed(self):
        batch = self.stock(self.m1, 1000, '4000', day(10, 1))
        item = HandlingPlanItem.objects.create(kind='harvest', date=date(2026, 11, 5), unit=self.m1, batch=batch,
                                               planned_kg=Decimal(2500), facility=self.facility, created_by=self.user)
        HandlingPlanItem.objects.filter(pk=item.pk).update(created_at=datetime(2026, 11, 2, 9, 0, tzinfo=utc.utc))
        row, = self.rows(ReportKind.SLAUGHTER_PLANNED)
        self.assertEqual((row.deadline, row.overdue), (date(2026, 11, 2), True))      # Thursday 29 October had passed
        HandlingPlanItem.objects.filter(pk=item.pk).update(created_at=datetime(2026, 11, 3, 9, 0, tzinfo=utc.utc))
        row, = self.rows(ReportKind.SLAUGHTER_PLANNED)
        self.assertEqual((row.deadline, row.overdue), (date(2026, 11, 3), False))     # agreed today: due today

    def test_an_escape_and_a_listed_disease_are_owed_until_a_notice_is_filed(self):
        batch = self.stock(self.m1, 3000, '200', day(9, 25))
        escape = stock.record_escape(self.user, unit=self.m1, batch=batch, day=day(10, 25), count=300,
                                     cause='A net tore').escape_record
        event = HealthEvent.objects.create(site=self.sea, date=day(10, 20), kind='vet_visit', diagnosis='isa',
                                           confirmation='suspected')
        HealthEvent.objects.create(site=self.sea, date=day(10, 20), kind='vet_visit', diagnosis='sea_lice',
                                   confirmation='confirmed')                      # not a listed disease
        escapes, diseases = self.rows(ReportKind.ESCAPE), self.rows(ReportKind.DISEASE)
        self.assertEqual([(row.place, row.event, row.deadline) for row in escapes], [(self.sea, escape, None)])
        self.assertEqual([(row.place, row.event) for row in diseases], [(self.sea, event)])
        self.assertEqual(escapes[0].start_query, {'kind': 'escape', 'escape': escape.pk})
        self.assertEqual(diseases[0].start_query, {'kind': 'disease', 'health_event': event.pk})
        filed(ReportKind.ESCAPE, self.sea, escape=escape, occurred_on=day(10, 25), **self.filed_by())
        filed(ReportKind.DISEASE, self.sea, health_event=event, occurred_on=day(10, 20), **self.filed_by())
        self.assertEqual((self.rows(ReportKind.ESCAPE), self.rows(ReportKind.DISEASE)), ([], []))

    def test_a_notice_of_a_day_before_the_sites_reports_from_date_or_of_a_site_with_none_is_not_owed(self):
        batch = self.stock(self.m1, 3000, '200', day(9, 25))
        stock.record_escape(self.user, unit=self.m1, batch=batch, day=day(9, 28), count=30, cause='A net tore')
        HealthEvent.objects.create(site=self.sea, date=day(9, 28), kind='vet_visit', diagnosis='isa',
                                   confirmation='suspected')
        self.assertEqual((self.rows(ReportKind.ESCAPE), self.rows(ReportKind.DISEASE)), ([], []))   # from 1 October
        stock.record_escape(self.user, unit=self.m1, batch=batch, day=day(10, 25), count=30, cause='A net tore')
        HealthEvent.objects.create(site=self.sea, date=day(10, 20), kind='vet_visit', diagnosis='isa',
                                   confirmation='suspected')
        self.assertEqual((len(self.rows(ReportKind.ESCAPE)), len(self.rows(ReportKind.DISEASE))), (1, 1))
        self.sea.reports_from = None
        self.sea.save()
        self.assertEqual((self.rows(ReportKind.ESCAPE), self.rows(ReportKind.DISEASE)), ([], []))

    def test_a_disease_told_through_a_telephone_filing_is_not_owed(self):
        event = HealthEvent.objects.create(site=self.sea, date=day(10, 20), kind='vet_visit', diagnosis='isa',
                                           confirmation='suspected')
        self.assertEqual([row.event for row in self.rows(ReportKind.DISEASE)], [event])
        filed(ReportKind.DISEASE, self.sea, health_event=event, occurred_on=day(10, 20), channel='telephone',
              reference='', **self.filed_by())
        self.assertEqual(self.rows(ReportKind.DISEASE), [])

    def test_a_draft_notice_stays_owed(self):
        event = HealthEvent.objects.create(site=self.sea, date=day(10, 20), kind='vet_visit', diagnosis='isa',
                                           confirmation='suspected')
        draft = Report.objects.create(kind='disease', site=self.sea, health_event=event, occurred_on=day(10, 20),
                                      created_by=self.user)
        self.assertEqual([row.report for row in self.rows(ReportKind.DISEASE)], [draft])

    def test_overdue_ones_come_first_then_by_deadline(self):
        self.october()
        self.stock(self.m1, 1000, '100', day(10, 5))
        rows = due.due(TODAY).rows
        flags = [row.overdue for row in rows]
        self.assertEqual(flags, sorted(flags, reverse=True))


class ChangedSinceFilingTests(DueTestCase):
    def test_a_filed_report_whose_records_changed_is_listed(self):
        self.october()
        report = self.report(Report.Kind.SMOLT, OCTOBER)
        with override_settings(STOCK_BACKDATE_DAYS=3650):
            services.submit(self.user, report, submitted_at=datetime(2026, 11, 2, 9, 0, tzinfo=utc.utc),
                            channel='altinn', reference='AR-2', version=report.version)
            self.assertEqual(due.no_longer_match(TODAY), [])
            stock.void(self.user, self.out, 'Wrong unit')
            self.assertEqual(due.no_longer_match(TODAY), [Report.objects.get(pk=report.pk)])

    def test_the_list_reads_the_rows_a_report_reads_and_never_folds_a_ledger(self):
        self.october()
        report = self.report(Report.Kind.SMOLT, OCTOBER)
        with override_settings(STOCK_BACKDATE_DAYS=3650):
            services.submit(self.user, report, submitted_at=datetime(2026, 11, 2, 9, 0, tzinfo=utc.utc),
                            channel='altinn', reference='AR-2', version=report.version)
            stock.void(self.user, self.out, 'Wrong unit')
            with mock.patch.object(compute, 'compute', side_effect=AssertionError('the list folded a ledger')):
                self.assertEqual(len(due.no_longer_match(TODAY)), 1)

    def test_a_report_a_filed_correction_replaced_is_not_listed(self):
        self.october()
        report = self.report(Report.Kind.SMOLT, OCTOBER)
        with override_settings(STOCK_BACKDATE_DAYS=3650):
            services.submit(self.user, report, submitted_at=datetime(2026, 11, 2, 9, 0, tzinfo=utc.utc),
                            channel='altinn', reference='AR-2', version=report.version)
            stock.void(self.user, self.out, 'Wrong unit')
            self.assertEqual([found.pk for found in due.no_longer_match(TODAY)], [report.pk])
            correction = services.start_correction(self.user, Report.objects.get(pk=report.pk))
            self.assertEqual([found.pk for found in due.no_longer_match(TODAY)], [report.pk])   # a draft replaces nothing
            services.submit(self.user, correction, submitted_at=datetime(2026, 11, 3, 9, 0, tzinfo=utc.utc),
                            channel='altinn', reference='AR-3', version=correction.version)
            self.assertEqual(due.no_longer_match(TODAY), [])

    def test_a_notice_is_read_again_whatever_its_day(self):
        batch = self.stock(self.m1, 3000, '200', day(9, 25))
        operation = stock.record_escape(self.user, unit=self.m1, batch=batch, day=day(10, 25), count=300,
                                        cause='A net tore')
        notice = self.report(Report.Kind.ESCAPE, site=self.sea, escape=operation.escape_record,
                             occurred_on=day(10, 25), what_happened='A net tore',
                             found_at=datetime(2026, 10, 25, 8, 0, tzinfo=utc.utc))
        with override_settings(STOCK_BACKDATE_DAYS=3650):
            services.submit(self.user, notice, submitted_at=datetime(2026, 11, 2, 9, 0, tzinfo=utc.utc),
                            channel='altinn', reference='AR-4', version=notice.version)
            self.assertEqual(due.no_longer_match(TODAY), [])
            stock.void(self.user, operation, 'Entered twice')
        with override_settings(STOCK_BACKDATE_DAYS=31):
            self.assertEqual([found.pk for found in due.no_longer_match(date(2027, 3, 1))], [notice.pk])

    def test_a_report_of_a_period_older_than_the_backdating_window_is_not_read_again(self):
        self.october()
        report = self.report(Report.Kind.SMOLT, OCTOBER)
        with override_settings(STOCK_BACKDATE_DAYS=3650):
            services.submit(self.user, report, submitted_at=datetime(2026, 11, 2, 9, 0, tzinfo=utc.utc),
                            channel='altinn', reference='AR-2', version=report.version)
            stock.void(self.user, self.out, 'Wrong unit')
        with override_settings(STOCK_BACKDATE_DAYS=31):
            self.assertEqual(due.no_longer_match(date(2027, 3, 1)), [])


class ScopeTests(DueTestCase):
    def test_every_kinds_scope_is_the_one_its_computation_reads(self):
        self.october()
        operation = stock.record_escape(self.user, unit=self.m1, batch=self.first, day=day(10, 26), count=10,
                                        cause='A net tore')
        event = HealthEvent.objects.create(site=self.sea, date=day(10, 20), kind='vet_visit', diagnosis='isa',
                                           confirmation='suspected')
        HandlingPlanItem.objects.create(kind='harvest', date=day(11, 18), unit=self.m1, batch=self.first,
                                        planned_kg=Decimal(2500), facility=self.facility, created_by=self.user)
        reports = [
            self.report(Report.Kind.SMOLT, OCTOBER),
            self.report(Report.Kind.BIOMASS, OCTOBER, site=self.sea),
            self.report(Report.Kind.CLEANER_FISH, OCTOBER, site=self.sea),
            self.report(Report.Kind.SEA_LICE, Period(WEEK, date(2026, 10, 19)), site=self.sea),
            self.report(Report.Kind.SLAUGHTER_PLANNED, Period(WEEK, date(2026, 11, 16))),
            self.report(Report.Kind.LAND_STOCK, Period(YEAR, date(2026, 1, 1)), site=self.hatchery),
            self.report(Report.Kind.SITE_IN_USE, site=self.sea, occurred_on=day(10, 15)),
            self.report(Report.Kind.SITE_EMPTIED, site=self.hatchery, occurred_on=day(10, 25)),
            self.report(Report.Kind.ESCAPE, site=self.sea, escape=operation.escape_record, occurred_on=day(10, 26)),
            self.report(Report.Kind.DISEASE, site=self.sea, health_event=event, occurred_on=day(10, 20)),
            self.report(Report.Kind.WELFARE, site=self.sea, health_event=event, occurred_on=day(10, 20)),
        ]
        self.assertEqual({report.kind for report in reports}, set(compute.COMPUTE))
        self.assertEqual(set(compute.SCOPE), set(compute.COMPUTE))
        for report in reports:
            with self.subTest(kind=report.kind):
                self.assertEqual(compute.fingerprint(compute.scope(report)),
                                 compute.fingerprint(compute.compute(report).scope))

    def test_a_feeding_up_to_the_months_end_changes_the_biomass_fingerprint_and_a_later_one_does_not(self):
        self.october()
        report = self.report(Report.Kind.BIOMASS, OCTOBER, site=self.sea)
        before = compute.fingerprint(compute.scope(report))
        feed = Feed.objects.create(name='Pellet', code='P1', feed_type='grower')
        feeding.record_feeding(self.user, unit=self.m1, day=day(11, 2), feed=feed, amount_kg=Decimal('0.3'),
                               target='production')
        self.assertEqual(compute.fingerprint(compute.scope(report)), before)
        feeding.record_feeding(self.user, unit=self.m1, day=day(10, 28), feed=feed, amount_kg=Decimal('0.3'),
                               target='production')
        self.assertNotEqual(compute.fingerprint(compute.scope(report)), before)


    def test_giving_a_batch_its_year_class_changes_the_fingerprint_of_the_reports_that_read_it(self):
        self.october()
        report = self.report(Report.Kind.SMOLT, OCTOBER)
        before = compute.fingerprint(compute.scope(report))
        stock.correct_batch(self.user, batch=self.first, year_class=2025, provenance='')
        self.assertNotEqual(compute.fingerprint(compute.scope(report)), before)


class TheListPageTests(DueTestCase):
    def setUp(self):
        super().setUp()
        self.october()

    def test_the_page_lists_what_is_due_with_a_start_link_for_people_who_may_create(self):
        page = self.client.get(reverse('reports:report_list'))
        self.assertContains(page, 'Reports and notices due')
        self.assertContains(page, 'Smolt')
        self.assertContains(page, f'{reverse("reports:report_create")}?kind=smolt&amp;site={self.hatchery.pk}&amp;'
                                  'period=2026-09')
        self.assertContains(page, 'Overdue')
        self.client.force_login(self.reader())
        page = self.client.get(reverse('reports:report_list'))
        self.assertContains(page, 'Smolt')
        self.assertNotContains(page, 'Start</a>')

    def reader(self):
        from django.contrib.auth import get_user_model
        person = get_user_model().objects.create_user('ola', 'ola@example.com', 'x')
        person.groups.add(role('Reader', 'view_report'))
        return person

    def test_a_draft_is_opened_not_started_again(self):
        draft = self.report(Report.Kind.SMOLT, Period(MONTH, date(2026, 9, 1)))
        page = self.client.get(reverse('reports:report_list'))
        self.assertContains(page, f'href="{reverse("reports:report_detail", args=[draft.pk])}">Open the draft')

    def test_a_site_that_is_not_set_up_is_named_with_a_link_to_its_form(self):
        self.hatchery.reports_from = None
        self.hatchery.save()
        page = self.client.get(reverse('reports:report_list'))
        self.assertContains(page, 'Not set up for reports')
        self.assertContains(page, f'href="{reverse("farm:site_edit", args=[self.hatchery.pk])}">Hatchery (HA)</a>')
        self.assertContains(page, 'no reports-from date')


class CheckReportsTests(DueTestCase):
    def test_a_filed_report_has_its_content_and_its_hash_and_the_command_says_so(self):
        filed(ReportKind.SMOLT, self.hatchery, OCTOBER, **self.filed_by())
        self.assertEqual(integrity.problems(), [])
        out = io.StringIO()
        call_command('check_reports', stdout=out)
        self.assertIn('The reports add up.', out.getvalue())

    def test_what_it_finds(self):
        bare = Report.objects.create(kind='smolt', site=self.hatchery, period_start=OCTOBER.start,
                                     submitted_at=datetime(2026, 11, 1, 9, tzinfo=utc.utc), submitted_by=self.user,
                                     channel='altinn', reference='x')
        draft = self.report(Report.Kind.SMOLT, Period(MONTH, date(2026, 9, 1)))
        ReportSnapshot.objects.create(report=draft, format_version=1, content={'a': 1}, content_sha256='0' * 64,
                                      sources_fingerprint='1' * 64)
        original = filed(ReportKind.SMOLT, self.hatchery, Period(MONTH, date(2026, 8, 1)), **self.filed_by())
        elsewhere = Report.objects.create(kind='smolt', site=self.sea, period_start=date(2026, 8, 1), corrects=original)
        found = integrity.problems()
        self.assertIn(f'Smolt {bare.pk} was filed and has no frozen content.', found)
        self.assertIn(f'Smolt {draft.pk} is a draft and has a frozen content.', found)
        self.assertIn(f'Smolt {elsewhere.pk} corrects {original.pk}, which is not of the same report.', found)
        with self.assertRaises(Exception) as caught:
            call_command('check_reports', stdout=io.StringIO())
        self.assertIn('problem(s) in the reports', str(caught.exception))

    def test_a_content_that_does_not_match_its_hash_or_is_of_a_format_this_version_does_not_know(self):
        report = Report.objects.create(kind='smolt', site=self.hatchery, period_start=OCTOBER.start,
                                       submitted_at=datetime(2026, 11, 1, 9, tzinfo=utc.utc), submitted_by=self.user,
                                       channel='altinn', reference='x')
        ReportSnapshot.objects.create(report=report, format_version=7, content={'a': 1}, content_sha256='0' * 64,
                                      sources_fingerprint='1' * 64)
        found = integrity.problems()
        self.assertIn(f'Smolt {report.pk}: the frozen content does not match its hash.', found)
        self.assertIn(f'Smolt {report.pk} has a content of format 7, which this version does not know.', found)

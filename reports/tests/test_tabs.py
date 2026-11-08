"""A tab for every kind of report, the line for each site and kind that says whether it is due and why not (the due list, one
place), and the upcoming reports of the company overview."""
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse

from farm.models import HandlingPlanItem, HealthEvent, Site
from farm.stock import services as stock
from farm.tests.helpers import role

from .. import due, kinds
from ..kinds import KINDS, ReportKind
from ..models import Report
from .helpers import OCTOBER, day
from .test_due import TODAY, DueTestCase, filed
from farm import withdrawal_gate


class LinesTestCase(DueTestCase):
    def line(self, kind, place):
        found = [line for line in due.due(TODAY).lines_of(kind) if line.place == place]
        self.assertEqual(len(found), 1, (kind, place))
        return found[0]

    def reason(self, kind, place):
        return self.line(kind, place).reason


class TabsOfKindsTests(LinesTestCase):
    def test_the_tabs_cover_every_kind_once_urgent_before_scheduled(self):
        self.assertEqual(set(kinds.URGENT) | set(kinds.SCHEDULED), set(KINDS))
        self.assertEqual(len(kinds.URGENT) + len(kinds.SCHEDULED), len(KINDS))
        self.assertEqual(set(kinds.URGENT), set(kinds.EVENTS))
        self.assertEqual(set(kinds.SCHEDULED), set(kinds.PERIODIC))

    def test_every_kind_has_a_line_for_every_site_or_facility(self):
        found = due.due(TODAY)
        for kind in kinds.SCHEDULED + kinds.URGENT:
            places = {line.place for line in found.lines_of(kind)}
            expected = {self.facility} if kind == ReportKind.SLAUGHTER_PLANNED else {self.hatchery, self.sea}
            self.assertEqual(places, expected, kind)


class PeriodicReasonsTests(LinesTestCase):
    def test_sea_lice(self):
        self.assertEqual(self.reason(ReportKind.SEA_LICE, self.hatchery), 'Hatchery is not a sea site')
        self.assertEqual(self.reason(ReportKind.SEA_LICE, self.sea),
                         'no salmonids in the sea at Fjord since 2026-10-01')
        self.stock(self.m1, 1000, '100', day(10, 5))
        line = self.line(ReportKind.SEA_LICE, self.sea)
        self.assertEqual((line.status, line.count), (due.DUE, 4))
        for row in due.due(TODAY).rows:
            if row.kind == ReportKind.SEA_LICE:
                filed(ReportKind.SEA_LICE, self.sea, row.period, **self.filed_by())
        line = self.line(ReportKind.SEA_LICE, self.sea)
        self.assertEqual((line.status, line.reason), (due.UP_TO_DATE, 'every period since 2026-10-01 with fish is filed'))

    def test_the_period_now_running_is_owed_once_it_has_closed(self):
        self.stock(self.m1, 1000, '100', day(11, 2))
        line = self.line(ReportKind.SEA_LICE, self.sea)
        self.assertEqual((line.status, line.reason), (due.NOT_DUE, 'owed once the month or week now running has closed'))

    def test_a_site_with_no_reports_from_date_owes_no_period(self):
        self.sea.reports_from = None
        self.sea.save()
        self.assertEqual(self.reason(ReportKind.SEA_LICE, self.sea),
                         'no reports-from date: its periods are not counted')

    def test_cleaner_fish(self):
        self.assertEqual(self.reason(ReportKind.CLEANER_FISH, self.sea), 'no cleaner fish held at Fjord since 2026-10-01')
        self.assertEqual(self.reason(ReportKind.CLEANER_FISH, self.hatchery), 'Hatchery is not a sea site')
        self.salmon.cleaner_fish_type = 'lumpfish'
        self.salmon.save()
        self.stock(self.m1, 1000, '100', day(10, 5))
        self.assertEqual(self.line(ReportKind.CLEANER_FISH, self.sea).status, due.DUE)

    def test_smolt(self):
        self.assertEqual(self.reason(ReportKind.SMOLT, self.sea), 'Fjord is not a juvenile (settefisk) site')
        self.assertEqual(self.reason(ReportKind.SMOLT, self.hatchery), 'no fish held at Hatchery since 2026-09-01')
        self.october()
        self.assertEqual(self.line(ReportKind.SMOLT, self.hatchery).count, 2)
        self.sea.production_form = ''
        self.sea.save()
        self.assertEqual(self.reason(ReportKind.SMOLT, self.sea), 'site not set up: no production form')

    def test_biomass(self):
        self.assertEqual(self.reason(ReportKind.BIOMASS, self.hatchery), 'a juvenile site reports smolt, not the monthly biomass')
        self.assertEqual(self.reason(ReportKind.BIOMASS, self.sea), 'no production fish held at Fjord since 2026-10-01')
        self.hatchery.production_form = Site.ProductionForm.MATFISK
        self.hatchery.save()
        self.assertEqual(self.reason(ReportKind.BIOMASS, self.hatchery), 'Hatchery is on land: it reports its yearly stock')
        self.sea.production_form = ''
        self.sea.save()
        self.assertEqual(self.reason(ReportKind.BIOMASS, self.sea), 'site not set up: no production form')

    def test_the_yearly_stock_of_a_land_site(self):
        self.assertEqual(self.reason(ReportKind.LAND_STOCK, self.sea), 'Fjord is at sea: it reports the monthly biomass')
        # A juvenile site on land reports it for its cleaner fish only.
        self.assertEqual(self.reason(ReportKind.LAND_STOCK, self.hatchery), 'no cleaner fish held at Hatchery since 2026-09-01')
        self.hatchery.production_form = Site.ProductionForm.MATFISK
        self.hatchery.reports_from = date(2025, 6, 1)
        self.hatchery.save()
        self.assertEqual(self.reason(ReportKind.LAND_STOCK, self.hatchery), 'no fish held at Hatchery since 2025-06-01')
        self.stock(self.k1, 100, '100', date(2025, 12, 20))
        self.assertEqual(self.line(ReportKind.LAND_STOCK, self.hatchery).status, due.DUE)

    def test_planned_slaughter(self):
        self.assertEqual(self.reason(ReportKind.SLAUGHTER_PLANNED, self.facility),
                         'no planned or recorded harvest to Fjord Slakteri is waiting for its notice')
        batch = self.stock(self.m1, 1000, '4000', day(10, 1))
        HandlingPlanItem.objects.create(kind='harvest', date=date(2026, 11, 5), unit=self.m1, batch=batch,
                                        planned_kg=Decimal(2500), facility=self.facility, created_by=self.user)
        line = self.line(ReportKind.SLAUGHTER_PLANNED, self.facility)
        self.assertEqual((line.status, line.count), (due.DUE, 1))


class NoticeReasonsTests(LinesTestCase):
    def test_escape_and_disease_are_due_when_one_is_unreported_else_say_so(self):
        self.assertEqual(self.reason(ReportKind.ESCAPE, self.sea), 'no escape without a filed notice since 2026-10-01')
        self.assertEqual(self.reason(ReportKind.DISEASE, self.sea),
                         'no listed disease without a filed notice since 2026-10-01')
        batch = self.stock(self.m1, 3000, '200', day(9, 25))
        stock.record_escape(self.user, unit=self.m1, batch=batch, day=day(10, 25), count=30, cause='A net tore')
        HealthEvent.objects.create(site=self.sea, date=day(10, 20), kind='vet_visit', diagnosis='isa',
                                   confirmation='suspected')
        self.assertEqual((self.line(ReportKind.ESCAPE, self.sea).status, self.line(ReportKind.ESCAPE, self.sea).count),
                         (due.DUE, 1))
        self.assertEqual(self.line(ReportKind.DISEASE, self.sea).status, due.DUE)
        self.sea.reports_from = None
        self.sea.save()
        self.assertEqual(self.reason(ReportKind.ESCAPE, self.sea), 'no reports-from date: nothing is counted')

    def test_welfare_and_the_two_notices_of_a_land_site_are_started_by_a_person(self):
        self.assertEqual(self.reason(ReportKind.WELFARE, self.sea),
                         'no increased mortality has stayed unexplained for 14 days; otherwise started by a person '
                         'when an event happens')
        for kind in (ReportKind.SITE_IN_USE, ReportKind.SITE_EMPTIED):
            self.assertEqual(self.reason(kind, self.hatchery), 'only a site of food fish or broodstock on land reports it')
            self.assertEqual(self.reason(kind, self.sea), 'only a site of food fish or broodstock on land reports it')
        self.hatchery.production_form = Site.ProductionForm.MATFISK
        self.hatchery.save()
        self.assertEqual(self.reason(ReportKind.SITE_IN_USE, self.hatchery), 'started by a person when it happens')
        self.hatchery.production_form = ''
        self.hatchery.save()
        self.assertEqual(self.reason(ReportKind.SITE_EMPTIED, self.hatchery), 'site not set up: no production form')


class TabPageTests(DueTestCase):
    def setUp(self):
        super().setUp()
        self.october()
        self.smolt = self.report(Report.Kind.SMOLT, OCTOBER)
        self.biomass = self.report(Report.Kind.BIOMASS, OCTOBER, site=self.sea)

    def page(self, **query):
        return self.client.get(reverse('reports:report_list'), query)

    def test_a_tab_for_every_kind_is_always_there_in_two_groups(self):
        page = self.page()
        groups = [(group['label'], [tab['label'] for tab in group['tabs']]) for group in page.context['tabs']]
        self.assertEqual([label for label, _tabs in groups], ['', 'Urgent', 'Scheduled'])
        self.assertEqual(sum(len(tabs) for _label, tabs in groups), 1 + len(KINDS))
        self.assertEqual(groups[1][1][:3], ['Welfare event', 'Disease', 'Escape'])
        self.assertEqual(groups[2][1][:4], ['Sea lice', 'Monthly biomass', 'Smolt', 'Cleaner fish'])
        for kind in KINDS:
            self.assertContains(page, f'?kind={kind}')
        self.assertContains(page, 'aria-current="page">All reports')

    def test_a_tab_lists_the_reports_of_its_kind_and_where_it_stands(self):
        page = self.page(kind='smolt')
        self.assertEqual(list(page.context['objects']), [self.smolt])
        self.assertContains(page, 'aria-current="page">Smolt')
        self.assertContains(page, 'Where it stands')
        self.assertContains(page, 'Fjord is not a juvenile (settefisk) site')
        self.assertContains(page, f'{reverse("reports:report_create")}?kind=smolt')
        page = self.page(kind='biomass')
        self.assertEqual(list(page.context['objects']), [self.biomass])
        self.assertContains(page, 'a juvenile site reports smolt, not the monthly biomass')

    def test_a_tab_with_no_report_still_says_why_nothing_is_due(self):
        page = self.page(kind='cleaner_fish')
        self.assertEqual(list(page.context['objects']), [])
        self.assertContains(page, 'Where it stands')
        self.assertContains(page, 'Hatchery is not a sea site')

    def test_the_site_filter_narrows_the_lines_and_the_tabs_keep_it(self):
        page = self.page(kind='sea_lice', site=self.sea.pk)
        self.assertEqual([line.place for line in page.context['lines']], [self.sea])
        self.assertContains(page, f'site={self.sea.pk}&amp;kind=smolt')

    def test_the_all_tab_keeps_the_due_and_not_set_up_blocks_a_kind_tab_has_its_own(self):
        self.hatchery.reports_from = None
        self.hatchery.save()
        self.assertContains(self.page(), 'Not set up for reports')
        self.assertNotContains(self.page(kind='smolt'), 'Not set up for reports')

    def test_a_person_who_may_not_start_a_report_gets_no_start_link(self):
        reader = get_user_model().objects.create_user('ola', 'ola@example.com', 'x')
        reader.groups.add(role('Reader', 'view_report'))
        self.client.force_login(reader)
        page = self.page(kind='smolt')
        self.assertContains(page, 'Where it stands')
        self.assertNotContains(page, 'Start one')
        nobody = get_user_model().objects.create_user('per', 'per@example.com', 'x')
        self.client.force_login(nobody)
        self.assertEqual(self.page(kind='smolt').status_code, 403)


class UpcomingTests(DueTestCase):
    def test_the_overview_lists_the_next_deadlines_overdue_first_for_people_who_read_reports(self):
        self.october()
        page = self.client.get(reverse('home'))
        self.assertContains(page, 'Upcoming reports')
        block = page.context['upcoming']
        self.assertTrue(block['rows'])
        self.assertEqual(block['rows'][0].overdue, True)
        owed = due.due()
        self.assertEqual(block['overdue'], sum(1 for row in owed.rows if row.overdue)
                         + sum(1 for line in owed.duties if line.status == 'overdue'))     # the duties outside the system too
        self.assertContains(page, 'class="overdue"')
        self.assertContains(page, reverse('reports:report_list'))

    def test_it_says_when_nothing_is_due_and_is_left_out_for_people_without_the_area(self):
        page = self.client.get(reverse('home'))
        self.assertContains(page, 'No report is due.')
        outsider = get_user_model().objects.create_user('per', 'per@example.com', 'x')
        self.client.force_login(outsider)
        page = self.client.get(reverse('home'))
        self.assertIsNone(page.context['upcoming'])
        self.assertNotContains(page, 'Upcoming reports')

    def test_more_than_the_block_shows_is_counted(self):
        self.october()
        block = self.client.get(reverse('home')).context['upcoming']
        total = len(due.due().rows)
        self.assertEqual(len(block['rows']) + block['more'], total)


class EscapeLabelTests(DueTestCase):
    @withdrawal_gate.opened('test fixture: withdrawal inputs written straight in the database')
    def test_an_escape_is_named_as_one_wherever_it_is_offered_or_listed(self):
        from core.models import AuditLog
        from ..forms import escape_label
        batch = self.stock(self.m1, 3000, '200', day(9, 25))
        operation = stock.record_escape(self.user, unit=self.m1, batch=batch, day=day(10, 12), count=50,
                                        cause='A tear of about 0.4 m')
        text = 'Escape of 50 fish from M-01, 2026-10-12'
        escape = operation.escape_record
        self.assertEqual((str(operation), str(escape), operation.escape), (text, text, escape))
        self.assertEqual(escape_label(escape), f'{text} · A tear of about 0.4 m')     # the picker
        row, = [row for row in due.due(TODAY).rows if row.kind == ReportKind.ESCAPE]  # the due list
        self.assertEqual(str(row.event), text)
        page = self.client.get(reverse('reports:report_list'))
        self.assertContains(page, text)
        self.assertNotContains(page, 'Count adjustment')
        entry = AuditLog.objects.filter(entity_type='stock operation').latest('created_at')   # the activity log
        self.assertEqual(entry.entity_label, f'Escape · M-01 · {batch.code} · 2026-10-12')
        # A count adjustment that is not an escape keeps its kind's name.
        other = stock.StockOperation.objects.create(kind='adjustment', date=day(10, 13))
        self.assertEqual((other.escape, str(other)), (None, 'Count adjustment 2026-10-13'))

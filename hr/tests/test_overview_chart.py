import re
from datetime import date, datetime, time, timezone as utc
from decimal import Decimal

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from farm.models import ProductionDepartment, Site

from .. import read
from ..models import LeaveType, LeaveRequest, SchedulingSettings, Shift, ShiftAssignment
from ..units import token
from .helpers import user
from .helpers_people import PeopleTestCase, TOP, employee, place

MONDAY = date(2026, 3, 2)
VIEW = ('view_employee', 'view_shiftassignment', 'view_officedepartment')


class OverviewTestCase(PeopleTestCase):
    def setUp(self):
        super().setUp()
        self.early = Shift.objects.create(name='Early', code='EARLY', starts_at=time(6), ends_at=time(14),
                                          break_minutes=30)
        self.lead = user('boss', *VIEW, group='View role')
        ProductionDepartment.objects.filter(pk=self.dept_a.pk).update(manager=self.lead)
        SchedulingSettings.get()

    def plan(self, person, day, shift='early'):
        return ShiftAssignment.objects.create(employee=person, day=day, shift=self.early if shift == 'early' else None)


class OverviewReadTests(OverviewTestCase):
    def test_per_person_days_hours_and_the_standard_week_and_per_day_footers(self):
        for n in range(4):
            self.plan(self.in_a, date(2026, 3, 2 + n))                          # Mon-Thu, 7.5 h each = 30 h
        self.plan(self.in_a, date(2026, 3, 6), shift=None)                      # Friday planned off
        kind = LeaveType.objects.create(name='Annual', code='AN')
        LeaveRequest.objects.create(employee=self.in_a, leave_type=kind, first_day=date(2026, 3, 7), last_day=date(2026, 3, 7),
                                    status='approved', decided_at=datetime(2026, 1, 1, tzinfo=utc.utc))
        overview = read.overview(self.lead, MONDAY)
        row = overview.rows[0]
        self.assertEqual((row.employee, row.working, row.off, row.leave), (self.in_a, 4, 1, 1))
        self.assertEqual((row.planned_minutes, str(row.planned_hours), row.over_minutes, row.over), (1800, '30', -600, False))
        self.assertEqual(overview.standard_minutes, 2400)
        self.assertEqual([item['working'] for item in overview.footer], [1, 1, 1, 1, 0, 0, 0])
        self.assertEqual([item['off'] for item in overview.footer], [0, 0, 0, 0, 1, 0, 0])
        self.assertEqual([item['leave'] for item in overview.footer], [0, 0, 0, 0, 0, 1, 0])

    def test_a_week_over_the_standard_is_marked_and_the_standard_is_the_setting(self):
        for n in range(6):
            self.plan(self.in_a, date(2026, 3, 2 + n))                          # 6 x 7.5 h = 45 h
        row = read.overview(self.lead, MONDAY).rows[0]
        self.assertEqual((row.over_minutes, row.over), (300, True))
        SchedulingSettings.objects.update(standard_week_minutes=2700)
        self.assertEqual(read.overview(self.lead, MONDAY).rows[0].over_minutes, 0)

    def test_the_overview_has_the_scope_of_the_week_and_nothing_wider(self):
        self.plan(self.in_b, MONDAY)
        self.assertEqual([r.employee for r in read.overview(self.lead, MONDAY).rows], [self.in_a])
        self.assertEqual({r.employee for r in read.overview(self.hr, MONDAY).rows}, {self.in_a, self.in_b, self.in_fin})

    def test_the_queries_do_not_grow_with_the_people(self):
        read.overview(self.lead, MONDAY)
        def count(people):
            for n in range(people):
                person = employee(f'E-{6000 + n + people}', f'Many{n}')
                place(person, self.dept_a)
                self.plan(person, MONDAY)
            with CaptureQueriesContext(connection) as queries:
                read.overview(self.lead, MONDAY)
            return len(queries)
        self.assertEqual(count(4), count(40))


class DayStateTests(OverviewTestCase):
    """A person's day has one state (read.Cell.state), read by the schedule and the team overview alike: approved leave
    first (a planned shift or a planned day off under it is for someone else to cover), then a planned shift, then a
    planned day off, else nothing planned."""

    def test_approved_leave_reads_on_leave_on_the_schedule_and_in_the_overview(self):
        self.plan(self.in_a, MONDAY, shift=None)                                # planned off, then leave approved
        self.plan(self.in_a, date(2026, 3, 3))                                  # planned to work, then leave approved
        self.plan(self.in_a, date(2026, 3, 4), shift=None)                      # planned off, no leave
        kind = LeaveType.objects.create(name='Annual', code='AN')
        LeaveRequest.objects.create(employee=self.in_a, leave_type=kind, first_day=MONDAY, last_day=date(2026, 3, 3),
                                    status='approved', decided_at=datetime(2026, 1, 1, tzinfo=utc.utc))
        cells = read.week(self.lead, MONDAY).rows[0].cells
        self.assertEqual([cell.state for cell in cells[:5]], ['leave', 'leave', 'off', 'none', 'none'])
        row = read.overview(self.lead, MONDAY).rows[0]
        self.assertEqual((row.working, row.off, row.leave), (0, 1, 2))
        self.client.force_login(self.lead)
        page = self.client.get(reverse('hr:production_shiftassignment_list'), {'week': MONDAY.isoformat()}).content.decode()
        days = re.findall(r'data-day="(2026-03-0[2-4])".*?</td>', page, re.S)
        cell = {day: text for day, text in re.findall(r'data-day="(2026-03-0[2-4])"(.*?)</td>', page, re.S)}
        self.assertEqual(len(days), 3)
        for day, state in (('2026-03-02', 'On leave'), ('2026-03-03', 'On leave'), ('2026-03-04', 'Off')):
            self.assertIn(f'>{state}</span>', cell[day], day)
            self.assertNotIn('>Off</span>' if state == 'On leave' else '>On leave</span>', cell[day], day)


class OverviewPageTests(OverviewTestCase):
    def test_the_page_its_filters_and_the_verb(self):
        self.plan(self.in_a, MONDAY)
        self.plan(self.in_b, MONDAY)
        self.client.force_login(self.lead)
        url = reverse('hr:production_overview')
        page = self.client.get(url, {'week': MONDAY.isoformat()})
        self.assertEqual([r.employee for r in page.context['overview'].rows], [self.in_a])
        self.assertEqual((page.context['title'], page.context['eyebrow']), ('Team overview', 'Time & attendance'))
        for query in ({'department': token(self.dept_b)}, {'q': 'Bravo'}, {'week': 'nonsense', 'page': 'x'}):
            rows = self.client.get(url, query).context['overview'].rows
            self.assertEqual({r.employee.last_name for r in rows} - {'Alfa'}, set(), query)
        self.client.force_login(user('stranger'))
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_it_is_a_page_of_the_menu_under_time_and_shifts(self):
        self.client.force_login(self.lead)
        response = self.client.get(reverse('hr:production_overview'))
        shown = [entry['label'] for section in response.context['rail_sections'] for group in section['groups']
                 for entry in group['entries']]
        self.assertIn('Team overview', shown)


def walk(node):
    """Every box below `node`, depth first."""
    for child in node.children:
        yield child
        yield from walk(child)


class OrgChartTests(OverviewTestCase):
    """Two charts of one company: Company's office tree with one Production box (computed, never a row: nothing to delete),
    and Production's sites with their production departments. Head counts are the viewer's to see."""

    def names(self, node):
        return [(child.kind, child.label, child.direct, child.total, [(g.label, g.direct, g.total) for g in child.children])
                for child in node.children]

    def production_box(self, tree):
        """The one Production box, wherever the rule hangs it."""
        found = [node for node in walk(tree) if node.kind == read.PRODUCTION_ROOT]
        self.assertEqual(len(found), 1)
        return found[0]

    def test_the_production_chart_has_the_sites_and_their_production_departments(self):
        tree = read.org_tree(self.hr, read.PRODUCTION)
        self.assertEqual(tree.total, 2)
        self.assertEqual(self.names(tree), [('site', 'Bergen', 0, 2, [('Hatchery A', 1, 1), ('Nursery B', 1, 1)])])
        self.assertEqual(tree.children[0].children[0].manager, self.lead)

    def test_the_company_chart_has_the_office_tree_and_one_production_box(self):
        tree = read.org_tree(self.hr, read.OFFICE)
        self.assertEqual(self.names(tree), [('office', 'Administration', 0, 3, [('Finance', 1, 1), ('Production', 2, 2)])])
        self.assertEqual(tree.total, 3)

    def test_with_one_top_department_the_production_box_hangs_under_it_and_counts_in_its_total(self):
        administration = read.org_tree(self.hr, read.OFFICE).children[0]
        self.assertEqual([child.kind for child in administration.children], [read.OFFICE, read.PRODUCTION_ROOT])
        self.assertEqual((administration.direct, administration.total), (0, 3))

    def test_with_several_top_departments_or_none_the_production_box_stands_beside_them(self):
        from ..models import OfficeDepartment
        OfficeDepartment.objects.create(site=self.site, name='Board', code='BRD')
        tree = read.org_tree(self.hr, read.OFFICE)
        self.assertEqual([(c.kind, c.label, c.total) for c in tree.children],
                         [('office', 'Administration', 1), ('office', 'Board', 0), (read.PRODUCTION_ROOT, 'Production', 2)])
        self.assertEqual(tree.total, 3)
        for posting in self.in_fin.postings.all():
            posting.soft_delete(self.hr)
        for department in (self.finance, self.admin_dept, OfficeDepartment.objects.get(code='BRD')):
            department.soft_delete(self.hr)
        self.assertEqual([(c.kind, c.total) for c in read.org_tree(self.hr, read.OFFICE).children],
                         [(read.PRODUCTION_ROOT, 2)])

    def test_the_production_box_is_there_with_no_production_department_and_counts_only_live_ones(self):
        for department in ProductionDepartment.objects.all():
            for posting in department.postings.all():
                posting.soft_delete(self.hr)
            department.soft_delete(self.hr)
        box = self.production_box(read.org_tree(self.hr, read.OFFICE))
        self.assertEqual((box.kind, box.direct, box.total), (read.PRODUCTION_ROOT, 0, 0))

    def test_a_production_department_appears_renames_and_goes_with_no_hr_write(self):
        new = ProductionDepartment.objects.create(site=self.site, name='Smolt hall', code='SMO')
        tree = lambda: [c.label for c in read.org_tree(self.hr, read.PRODUCTION).children[0].children]
        self.assertIn('Smolt hall', tree())
        ProductionDepartment.objects.filter(pk=new.pk).update(name='Smolt hall 2')
        self.assertIn('Smolt hall 2', tree())
        new.soft_delete(self.hr)
        self.assertNotIn('Smolt hall 2', tree())

    def test_the_counts_are_the_viewers_to_see_and_a_site_less_department_has_its_own_box(self):
        orphan = ProductionDepartment.objects.create(site=None, name='Orphan hall', code='ORP')
        place(employee('E-9', 'India'), orphan)
        boss = read.org_tree(self.lead, read.PRODUCTION)
        self.assertEqual(boss.total, 1)                                          # only the lead's own team
        self.assertIn(('site', ''), [(c.kind, c.label) for c in boss.children])  # the department without a site
        self.assertEqual(read.org_tree(self.hr, read.PRODUCTION).total, 3)
        self.assertEqual(self.production_box(read.org_tree(self.lead, read.OFFICE)).total, 1)

    def test_deep_nesting_totals_below_and_the_company_page(self):
        from ..models import OfficeDepartment
        sub = OfficeDepartment.objects.create(name='Payables', code='PAB', parent=self.finance, site=self.site)
        place(employee('E-10', 'Juliet'), sub)
        top = next(c for c in read.org_tree(self.hr, read.OFFICE).children if c.label == 'Administration')
        self.assertEqual((top.direct, top.total), (0, 4))                     # Finance, Payables and the Production box (2)
        self.client.force_login(self.hr)
        page = self.client.get(reverse('hr:orgchart'))
        self.assertContains(page, 'Payables')
        self.assertNotContains(page, 'Hatchery A')
        self.assertEqual((page.context['title'], page.context['eyebrow']), ('Organization chart', 'HR dashboard'))

    def test_the_production_box_links_to_the_production_chart_only_for_who_may_open_it(self):
        target = reverse('hr:production_orgchart')
        self.client.force_login(self.hr)                                          # holds hr.view_employee
        self.assertContains(self.client.get(reverse('hr:orgchart')), f'href="{target}"')
        office_reader = user('office', 'view_officedepartment', group='Office reader role')
        self.client.force_login(office_reader)
        page = self.client.get(reverse('hr:orgchart'))
        self.assertContains(page, 'org-production_root')
        self.assertNotContains(page, f'href="{target}"')

    def test_the_production_page_and_its_verb(self):
        self.client.force_login(self.hr)
        page = self.client.get(reverse('hr:production_orgchart'))
        self.assertContains(page, 'Hatchery A')
        self.assertNotContains(page, 'Finance')
        self.assertEqual((page.context['title'], page.context['eyebrow']), ('Organization chart', 'People'))
        self.client.force_login(user('office', 'view_officedepartment', group='Office reader role'))
        self.assertEqual(self.client.get(reverse('hr:production_orgchart')).status_code, 403)

    def test_the_verb_decides(self):
        self.client.force_login(user('stranger'))
        self.assertEqual(self.client.get(reverse('hr:orgchart')).status_code, 403)
        self.client.force_login(self.lead)
        self.assertEqual(self.client.get(reverse('hr:orgchart')).status_code, 200)

    def test_the_queries_do_not_grow_with_the_departments_and_people(self):
        for realm in (read.PRODUCTION, read.OFFICE):
            read.org_tree(self.hr, realm)

            def count(departments):
                for n in range(departments):
                    dept = ProductionDepartment.objects.create(site=self.site, name=f'Hall {n}-{departments}-{realm}',
                                                               code=f'H{n}X{departments}{realm[0]}')
                    place(employee(f'E-{7000 + n + departments}{realm[0]}', f'Many{n}'), dept)
                with CaptureQueriesContext(connection) as queries:
                    read.org_tree(self.hr, realm)
                return len(queries)
            self.assertEqual(count(3), count(30), realm)

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


class OrgChartTests(OverviewTestCase):
    def tree(self, actor):
        return read.org_tree(actor)

    def names(self, node):
        return [(child.kind, child.label, child.direct, child.total, [(g.label, g.direct, g.total) for g in child.children])
                for child in node.children]

    def test_sites_production_departments_and_office_departments_with_their_head_counts(self):
        tree = self.tree(self.hr)
        self.assertEqual(tree.total, 3)
        self.assertEqual(self.names(tree), [
            ('site', 'Bergen', 0, 2, [('Hatchery A', 1, 1), ('Nursery B', 1, 1)]),
            ('office', 'Administration', 0, 1, [('Finance', 1, 1)]),
        ])
        finance = tree.children[1].children[0]
        self.assertEqual(finance.kind, 'office')
        self.assertEqual(tree.children[0].children[0].manager, self.lead)

    def test_a_production_department_appears_renames_and_goes_with_no_hr_write(self):
        new = ProductionDepartment.objects.create(site=self.site, name='Smolt hall', code='SMO')
        self.assertIn('Smolt hall', [c.label for c in self.tree(self.hr).children[0].children])
        ProductionDepartment.objects.filter(pk=new.pk).update(name='Smolt hall 2')
        self.assertIn('Smolt hall 2', [c.label for c in self.tree(self.hr).children[0].children])
        new.soft_delete(self.hr)
        self.assertNotIn('Smolt hall 2', [c.label for c in self.tree(self.hr).children[0].children])

    def test_the_counts_are_the_viewers_to_see_and_a_site_less_department_has_its_own_box(self):
        orphan = ProductionDepartment.objects.create(site=None, name='Orphan hall', code='ORP')
        place(employee('E-9', 'India'), orphan)
        boss = self.tree(self.lead)
        self.assertEqual(boss.total, 1)                                          # only the lead's own team
        labels = [(c.kind, c.label) for c in boss.children]
        self.assertIn(('site', ''), labels)                                      # the department without a site
        self.assertEqual(self.tree(self.hr).total, 4)

    def test_deep_nesting_totals_below_and_the_page(self):
        from ..models import OfficeDepartment
        sub = OfficeDepartment.objects.create(name='Payables', code='PAB', parent=self.finance, site=self.site)
        place(employee('E-10', 'Juliet'), sub)
        top = next(c for c in self.tree(self.hr).children if c.label == 'Administration')
        self.assertEqual((top.direct, top.total), (0, 2))
        self.assertEqual(top.children[0].total, 2)
        self.client.force_login(self.hr)
        page = self.client.get(reverse('hr:orgchart'))
        self.assertContains(page, 'Payables')
        self.assertContains(page, 'Administration')
        self.assertEqual((page.context['title'], page.context['eyebrow']), ('Organization chart', 'HR dashboard'))

    def test_the_verb_decides(self):
        self.client.force_login(user('stranger'))
        self.assertEqual(self.client.get(reverse('hr:orgchart')).status_code, 403)
        self.client.force_login(self.lead)
        self.assertEqual(self.client.get(reverse('hr:orgchart')).status_code, 200)

    def test_the_queries_do_not_grow_with_the_departments_and_people(self):
        read.org_tree(self.hr)
        def count(departments):
            for n in range(departments):
                dept = ProductionDepartment.objects.create(site=self.site, name=f'Hall {n}-{departments}',
                                                           code=f'H{n}X{departments}')
                place(employee(f'E-{7000 + n + departments}', f'Many{n}'), dept)
            with CaptureQueriesContext(connection) as queries:
                read.org_tree(self.hr)
            return len(queries)
        self.assertEqual(count(3), count(30))

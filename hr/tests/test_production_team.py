"""Production › Team: the HR pages served a second time under Production (core.crud.Mount) for the production people, and
Company › HR left with the office's. One set of records: the same rows, rules and log, split by the realm (hr.scope). A
record of the other realm is a 404 on every address; a decision returns to the panel it was made in; the menu shows each
person their side, and a menu line it hides never decides what may be opened."""
from datetime import date, datetime, time, timezone as utc

from django.contrib.auth import get_user_model
from django.urls import reverse

from core import navigation
from core.models import AuditLog
from farm.models import ProductionDepartment

from ..models import AttendanceRecord, Employee, LeaveRequest, LeaveType, Shift, ShiftAssignment
from ..units import token
from .helpers import user
from .helpers_people import PeopleTestCase

MONDAY = date(2026, 3, 2)
HR_ALL = ('view_employee', 'add_employee', 'change_employee', 'all_employee', 'view_officedepartment',
          'view_shiftassignment', 'add_shiftassignment', 'change_shiftassignment', 'delete_shiftassignment',
          'view_attendancerecord', 'add_attendancerecord', 'change_attendancerecord', 'delete_attendancerecord',
          'view_leaverequest', 'add_leaverequest', 'change_leaverequest')
WORKER = ('view_attendancerecord', 'view_shiftassignment', 'view_leaverequest', 'add_leaverequest')

ROUTES = {
    'hr:production_today': '/production/team/',
    'hr:production_today_board': '/production/team/today/board/',
    'hr:production_shiftassignment_list': '/production/team/schedule/',
    'hr:production_shiftassignment_create': '/production/team/schedule/new/',
    'hr:production_roster_plan': '/production/team/schedule/plan/',
    'hr:production_overview': '/production/team/overview/',
    'hr:production_attendancerecord_list': '/production/team/attendance/',
    'hr:production_leaverequest_list': '/production/team/leave/',
    'hr:production_leaverequest_create': '/production/team/leave/new/',
    'hr:production_employee_list': '/production/team/people/',
    'hr:production_employee_create': '/production/team/people/new/',
    'hr:production_orgchart': '/production/team/organization/',
}


def labels(response):
    return [entry['label'] for section in response.context['rail_sections']
            for group in section['groups'] for entry in group['entries']]


class RouteTests(PeopleTestCase):
    def test_every_production_route_is_under_production_team_and_in_the_production_panel(self):
        for name, address in ROUTES.items():
            self.assertEqual(reverse(name), address, name)
            self.assertEqual(navigation.workspace_of(address), 'production', name)
        self.assertEqual(reverse('hr:production_punch', args=['in']), '/production/team/today/clock-in/')
        self.assertEqual(navigation.workspace_of(reverse('hr:today')), 'company')

    def test_the_team_section_in_the_production_menu(self):
        admin = user('hradmin2', *HR_ALL, group='HR all role')
        self.client.force_login(admin)
        response = self.client.get(reverse('hr:production_today'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['workspace']['key'], 'production')
        sections = {section['label']: [entry['label'] for group in section['groups'] for entry in group['entries']]
                    for section in response.context['rail_sections']}
        self.assertEqual(sections['Team'], ['Today & attendance', 'Shift schedule', 'Leave requests', 'Attendance',
                                            'Team overview', 'Team list', 'Organization chart'])
        self.assertEqual(list(sections)[-1], 'Team')


class SplitTests(PeopleTestCase):
    """The HR administrator (Everyone) sees the office people in Company and the production people in Production."""

    def setUp(self):
        super().setUp()
        self.admin = user('hrall', *HR_ALL, group='HR all role')
        self.kind = LeaveType.objects.create(name='Annual leave', code='ANNUAL')
        self.leave_a = LeaveRequest.objects.create(employee=self.in_a, leave_type=self.kind, first_day=MONDAY,
                                                   last_day=MONDAY)
        self.leave_fin = LeaveRequest.objects.create(employee=self.in_fin, leave_type=self.kind, first_day=MONDAY,
                                                     last_day=MONDAY)
        self.early = Shift.objects.create(name='Early', code='EARLY', starts_at=time(6), ends_at=time(14))
        self.plan_a = ShiftAssignment.objects.create(employee=self.in_a, day=MONDAY, shift=self.early)
        self.plan_fin = ShiftAssignment.objects.create(employee=self.in_fin, day=MONDAY, shift=self.early)
        self.punch_a = AttendanceRecord.objects.create(employee=self.in_a, clock_in=datetime(2026, 3, 2, 6, tzinfo=utc.utc),
                                                       clock_out=datetime(2026, 3, 2, 9, tzinfo=utc.utc), note='Entered')
        self.punch_fin = AttendanceRecord.objects.create(employee=self.in_fin,
                                                         clock_in=datetime(2026, 3, 2, 6, tzinfo=utc.utc),
                                                         clock_out=datetime(2026, 3, 2, 9, tzinfo=utc.utc), note='Entered')
        self.client.force_login(self.admin)

    def listed(self, name, **query):
        return self.client.get(reverse(name), query).context['objects']

    def test_leave_requests_split(self):
        self.assertEqual([row['request'] for row in self.listed('hr:leaverequest_list', tab='all')], [self.leave_fin])
        self.assertEqual([row['request'] for row in self.listed('hr:production_leaverequest_list', tab='all')],
                         [self.leave_a])

    def test_the_schedule_and_overview_split(self):
        company = self.client.get(reverse('hr:shiftassignment_list'), {'week': MONDAY.isoformat()}).context['week']
        production = self.client.get(reverse('hr:production_shiftassignment_list'),
                                     {'week': MONDAY.isoformat()}).context['week']
        self.assertEqual([row.employee for row in company.rows], [self.in_fin])
        self.assertEqual([row.employee.last_name for row in production.rows], ['Alfa', 'Bravo'])
        overview = self.client.get(reverse('hr:production_overview'), {'week': MONDAY.isoformat()}).context['overview']
        self.assertEqual([row.employee.last_name for row in overview.rows], ['Alfa', 'Bravo'])

    def test_attendance_and_the_team_list_split(self):
        query = {'from': '2026-03-01', 'to': '2026-03-03'}
        self.assertEqual(list(self.listed('hr:attendancerecord_list', **query)), [self.punch_fin])
        self.assertEqual(list(self.listed('hr:production_attendancerecord_list', **query)), [self.punch_a])
        self.assertEqual([e.last_name for e in self.listed('hr:employee_list')], ['Charlie'])
        self.assertEqual([e.last_name for e in self.listed('hr:production_employee_list')], ['Alfa', 'Bravo'])

    def test_a_record_of_the_other_realm_is_a_404_on_every_address_and_nothing_changes(self):
        logs = AuditLog.objects.count()
        for name, pk in (('hr:leaverequest_detail', self.leave_a.pk), ('hr:production_leaverequest_detail', self.leave_fin.pk),
                         ('hr:shiftassignment_edit', self.plan_a.pk), ('hr:production_shiftassignment_edit', self.plan_fin.pk),
                         ('hr:attendancerecord_edit', self.punch_a.pk),
                         ('hr:production_attendancerecord_edit', self.punch_fin.pk),
                         ('hr:production_attendancerecord_delete', self.punch_fin.pk),
                         ('hr:employee_detail', self.in_a.pk), ('hr:production_employee_detail', self.in_fin.pk),
                         ('hr:production_employee_edit', self.in_fin.pk),
                         ('hr:production_leaverequest_reject', self.leave_fin.pk)):
            self.assertEqual(self.client.get(reverse(name, args=[pk])).status_code, 404, name)
        for name, pk in (('hr:production_leaverequest_reject', self.leave_fin.pk),
                         ('hr:production_leaverequest_cancel', self.leave_fin.pk),
                         ('hr:leaverequest_cancel', self.leave_a.pk),
                         ('hr:production_attendancerecord_delete', self.punch_fin.pk),
                         ('hr:production_shiftassignment_delete', self.plan_fin.pk)):
            self.assertEqual(self.client.post(reverse(name, args=[pk]), {'note': 'x'}).status_code, 404, name)
        self.assertEqual(LeaveRequest.objects.filter(status='pending').count(), 2)
        self.assertEqual(AttendanceRecord.objects.count(), 2)
        self.assertEqual(AuditLog.objects.count(), logs)

    def test_a_decision_in_production_returns_to_production(self):
        response = self.client.post(reverse('hr:production_leaverequest_reject', args=[self.leave_a.pk]), {'note': 'No'})
        self.assertRedirects(response, reverse('hr:production_leaverequest_list'), fetch_redirect_response=False)
        self.leave_a.refresh_from_db()
        self.assertEqual(self.leave_a.status, 'rejected')

    def test_the_pages_are_headed_by_the_production_menu(self):
        page = self.client.get(reverse('hr:production_leaverequest_list'))
        self.assertEqual((str(page.context['group']), str(page.context['title'])), ('Time & attendance', 'Leave requests'))
        page = self.client.get(reverse('hr:production_employee_list'))
        self.assertEqual((str(page.context['group']), str(page.context['title'])), ('People', 'Team list'))
        page = self.client.get(reverse('hr:production_attendancerecord_list'))
        self.assertEqual(str(page.context['title']), 'Attendance')
        page = self.client.get(reverse('hr:leaverequest_list'))
        self.assertEqual(str(page.context['group']), 'Time & shifts')

    def test_the_employee_form_offers_the_departments_of_its_panel(self):
        def offered(name):
            form = self.client.get(reverse(name)).context['form']
            return {value.split(':')[0] for _group, options in form.fields['department'].choices[1:]
                    for value, _label in options}
        self.assertEqual(offered('hr:production_employee_create'), {'production'})
        self.assertEqual(offered('hr:employee_create'), {'office'})

    def test_a_move_offers_every_department_so_a_person_can_change_sides(self):
        form = self.client.get(reverse('hr:production_employee_edit', args=[self.in_a.pk])).context['form']
        kinds = {value.split(':')[0] for _group, options in form.fields['department'].choices[1:]
                 for value, _label in options}
        self.assertEqual(kinds, {'production', 'office'})

    def test_a_person_created_in_production_opens_in_production(self):
        response = self.client.post(reverse('hr:production_employee_create'), {
            'employee_number': 'E-50', 'first_name': 'New', 'last_name': 'Person', 'employment_type': 'staff',
            'joined_on': '2026-01-01', 'department': token(self.dept_a), 'title': 'Feeder', 'from_day': '2026-01-01'})
        created = Employee.objects.get(employee_number='E-50')
        self.assertRedirects(response, reverse('hr:production_employee_edit', args=[created.pk]),
                             fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse('hr:production_employee_edit', args=[created.pk])).status_code, 200)


class ManagerTests(PeopleTestCase):
    def setUp(self):
        super().setUp()
        self.planner = user('planner', 'view_shiftassignment', 'add_shiftassignment', 'view_leaverequest',
                            'change_leaverequest', 'view_attendancerecord', group='Planner role')
        ProductionDepartment.objects.filter(pk=self.dept_a.pk).update(manager=self.planner)
        self.client.force_login(self.planner)

    def test_a_department_manager_finds_their_people_in_production_only(self):
        production = self.client.get(reverse('hr:production_shiftassignment_list'),
                                     {'week': MONDAY.isoformat()}).context['week']
        self.assertEqual([row.employee for row in production.rows], [self.in_a])
        company = self.client.get(reverse('hr:shiftassignment_list'), {'week': MONDAY.isoformat()}).context['week']
        self.assertEqual(company.rows, [])

    def test_the_create_form_in_production_offers_the_production_team(self):
        form = self.client.get(reverse('hr:production_shiftassignment_create')).context['form']
        self.assertEqual(list(form.fields['employee'].queryset), [self.in_a])
        form = self.client.get(reverse('hr:shiftassignment_create')).context['form']
        self.assertEqual(list(form.fields['employee'].queryset), [])


class MenuCourtesyTests(PeopleTestCase):
    def setUp(self):
        super().setUp()
        self.worker = user('ann', *WORKER, group='Worker role')
        Employee.objects.filter(pk=self.in_a.pk).update(user=self.worker, first_name='', last_name='')

    def test_a_production_only_worker_has_no_company_hr_lines_but_may_still_open_the_pages(self):
        self.client.force_login(self.worker)
        company = labels(self.client.get(reverse('home')))
        self.assertNotIn('Leave requests', company)
        self.assertNotIn('Today & attendance', company)
        production = labels(self.client.get(reverse('hr:production_today')))
        self.assertIn('Leave requests', production)
        self.assertNotIn('Team overview', production)            # not a lead
        self.assertEqual(self.client.get(reverse('hr:leaverequest_list')).status_code, 200)

    def test_an_office_person_keeps_the_company_lines(self):
        office = user('cy', *WORKER, group='Office worker role')
        Employee.objects.filter(pk=self.in_fin.pk).update(user=office, first_name='', last_name='')
        self.client.force_login(office)
        self.assertIn('Leave requests', labels(self.client.get(reverse('home'))))

    def test_a_lead_has_team_overview(self):
        self.client.force_login(self.lead_a)
        self.assertIn('Team overview', labels(self.client.get(reverse('hr:production_today'))))

    def test_a_punch_in_production_returns_to_production(self):
        self.client.force_login(self.worker)
        response = self.client.post(reverse('hr:production_punch', args=['in']))
        self.assertRedirects(response, reverse('hr:production_today'), fetch_redirect_response=False)
        self.assertEqual(AttendanceRecord.objects.filter(employee=self.in_a, clock_out__isnull=True).count(), 1)

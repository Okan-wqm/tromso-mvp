"""The team scope: who reaches whom, by function and by URL. Out of scope is a 404 on every verb, by address and by query,
and nothing is written or logged."""
from datetime import date

from django.contrib.auth import get_user_model
from django.urls import reverse

from core.models import AuditLog
from farm.models import ProductionDepartment

from .. import scope
from ..models import Employee, OfficeDepartment, Posting
from ..units import token
from .helpers import user
from .helpers_people import LEAD_PERMS, PeopleTestCase, TOP, employee, place

DAY = date(2026, 3, 2)


class TeamFunctionTests(PeopleTestCase):
    def names(self, person, day=None):
        return sorted(e.last_name for e in scope.team(person, day))

    def test_a_manager_reaches_the_people_placed_in_their_department_that_day(self):
        self.assertEqual(self.names(self.lead_a, DAY), ['Alfa'])
        self.assertEqual(self.names(self.lead_b, DAY), ['Bravo'])
        self.assertEqual(self.names(self.client_user(), DAY), [])

    def client_user(self):
        return user('nobody')

    def test_a_person_always_reaches_themselves(self):
        account = get_user_model().objects.create_user('ann', 'ann@example.com', 'x')
        Employee.objects.filter(pk=self.in_a.pk).update(user=account, first_name='', last_name='')
        self.assertEqual([e.pk for e in scope.team(account, DAY)], [self.in_a.pk])

    def test_a_manager_of_an_office_department_reaches_it_and_every_department_below(self):
        boss = user('boss')
        OfficeDepartment.objects.filter(pk=self.admin_dept.pk).update(manager=boss)
        self.assertEqual(self.names(boss, DAY), ['Charlie'])               # Finance is below Administration
        OfficeDepartment.objects.filter(pk=self.admin_dept.pk).update(manager=None)
        OfficeDepartment.objects.filter(pk=self.finance.pk).update(manager=boss)
        self.assertEqual(self.names(boss, DAY), ['Charlie'])
        sibling = OfficeDepartment.objects.create(name='Legal', code='LEG', parent=self.admin_dept, site=self.site)
        place(employee('E-7', 'Golf'), sibling)
        self.assertEqual(self.names(boss, DAY), ['Charlie'])               # not the sibling department

    def test_everyone_reaches_every_employee(self):
        self.assertEqual(self.names(self.hr, DAY), ['Alfa', 'Bravo', 'Charlie'])

    def test_a_deleted_department_or_placement_gives_no_team(self):
        placing = Posting.objects.get(employee=self.in_a)
        placing.soft_delete(self.hr)
        self.assertEqual(self.names(self.lead_a, DAY), [])
        placing.is_deleted = False
        placing.save()
        self.assertEqual(self.names(self.lead_a, DAY), ['Alfa'])
        self.dept_a.soft_delete(self.hr)
        self.assertEqual(self.names(self.lead_a, DAY), [])

    def test_a_deleted_employee_is_nobodys(self):
        self.in_a.soft_delete(self.hr)
        self.assertEqual(self.names(self.lead_a, DAY), [])

    def test_a_person_who_moved_belongs_to_the_old_manager_before_the_move_and_the_new_one_from_it(self):
        mover = employee('E-8', 'Hotel')
        place(mover, self.dept_a, TOP, date(2026, 3, 31))
        place(mover, self.dept_b, date(2026, 4, 1))
        self.assertEqual(self.names(self.lead_a, date(2026, 3, 31)), ['Alfa', 'Hotel'])
        self.assertEqual(self.names(self.lead_a, date(2026, 4, 1)), ['Alfa'])
        self.assertEqual(self.names(self.lead_b, date(2026, 3, 31)), ['Bravo'])
        self.assertEqual(self.names(self.lead_b, date(2026, 4, 1)), ['Bravo', 'Hotel'])
        days = scope.visible_days(self.lead_a, date(2026, 3, 30), date(2026, 4, 2))
        self.assertEqual(sorted(days[mover.pk]), [date(2026, 3, 30), date(2026, 3, 31)])
        self.assertIsNone(scope.visible_days(self.hr, date(2026, 3, 30), date(2026, 4, 2)))

    def test_the_manager_field_is_what_makes_a_team(self):
        ProductionDepartment.objects.filter(pk=self.dept_a.pk).update(manager=self.lead_b)
        self.assertEqual(self.names(self.lead_a, DAY), [])
        self.assertEqual(self.names(self.lead_b, DAY), ['Alfa', 'Bravo'])

    def test_a_manager_without_the_role_still_has_a_team_but_no_page(self):
        manager = user('plain')
        ProductionDepartment.objects.filter(pk=self.dept_a.pk).update(manager=manager)
        self.assertEqual(self.names(manager, DAY), ['Alfa'])
        self.client.force_login(manager)
        self.assertEqual(self.client.get(reverse('hr:employee_list')).status_code, 403)


class EmployeeUrlMatrixTests(PeopleTestCase):
    """Every actor against every employee route: the verb (403) and the row (404)."""

    def status(self, actor, method, name, *args, data=None):
        self.client.logout()
        if actor is not None:
            self.client.force_login(actor)
        request = getattr(self.client, method)
        return request(reverse(name, args=args), data or {}).status_code

    def test_the_read_routes(self):
        auditor = user('auditor', 'view_employee', 'all_employee', group='Auditor role')
        root = get_user_model().objects.create_superuser('root', 'root@example.com', 'x')
        stranger = user('stranger')
        expect = {          # actor -> (list, detail of A's person, detail of B's person)
            'anonymous': (None, 302, 302, 302),
            'stranger': (stranger, 403, 403, 403),
            'lead_a': (self.lead_a, 200, 200, 404),
            'lead_b': (self.lead_b, 200, 404, 200),
            'hr': (self.hr, 200, 200, 200),
            'auditor': (auditor, 200, 200, 200),
            'root': (root, 200, 200, 200),
        }
        for label, (actor, listed, mine, other) in expect.items():
            self.assertEqual(self.status(actor, 'get', 'hr:employee_list'), listed, label)
            self.assertEqual(self.status(actor, 'get', 'hr:employee_detail', self.in_a.pk), mine, label)
            self.assertEqual(self.status(actor, 'get', 'hr:employee_detail', self.in_b.pk), other, label)

    def test_the_write_routes_by_verb_and_row(self):
        edit_lead = user('editor', 'view_employee', 'change_employee', group='Edit role')
        ProductionDepartment.objects.filter(pk=self.dept_a.pk).update(manager=edit_lead)
        expect = {          # actor -> (create GET, edit own team GET, edit other team GET)
            'lead_a (read only)': (self.lead_a, 403, 403, 403),
            'editor': (edit_lead, 403, 200, 404),
            'hr': (self.hr, 200, 200, 200),
        }
        for label, (actor, create, mine, other) in expect.items():
            self.assertEqual(self.status(actor, 'get', 'hr:employee_create'), create, label)
            self.assertEqual(self.status(actor, 'get', 'hr:employee_edit', self.in_a.pk), mine, label)
            self.assertEqual(self.status(actor, 'get', 'hr:employee_edit', self.in_b.pk), other, label)

    def test_there_is_no_delete_route_for_anyone(self):
        for person in (self.in_a, self.in_b):
            for actor in (self.hr, self.lead_a):
                self.client.force_login(actor)
                self.assertEqual(self.client.post(f'/hr/team/{person.pk}/delete/').status_code, 404)
                self.assertEqual(self.client.get(f'/hr/team/{person.pk}/delete/').status_code, 404)

    def test_every_route_of_the_hr_resources_has_an_expectation(self):
        from django.urls import get_resolver
        names = sorted(name for name in get_resolver().namespace_dict['hr'][1].reverse_dict if isinstance(name, str))
        known = {'employee_list', 'employee_create', 'employee_edit', 'employee_detail',
                 'officedepartment_list', 'officedepartment_create', 'officedepartment_edit',
                 'officedepartment_delete', 'shift_list', 'shift_create', 'shift_edit', 'shift_delete', 'holiday_list',
                 'holiday_create', 'holiday_edit', 'holiday_delete', 'schedulingsettings_list',
                 'schedulingsettings_edit', 'shiftassignment_list', 'shiftassignment_create', 'shiftassignment_edit',
                 'shiftassignment_delete', 'roster_plan', 'leaverequest_list', 'leaverequest_create', 'leaverequest_edit',
                 'leaverequest_detail', 'leaverequest_approve', 'leaverequest_reject', 'leaverequest_cancel',
                 'leavetype_list', 'leavetype_create', 'leavetype_edit', 'leavetype_delete', 'attendancerecord_list',
                 'attendancerecord_create', 'attendancerecord_edit', 'attendancerecord_delete', 'today', 'today_board', 'punch', 'orgchart', 'overview'}
        self.assertEqual(set(names) - known, set(), 'give every new HR route a row in the URL matrix')


class OutOfScopeWritesTests(PeopleTestCase):
    def setUp(self):
        super().setUp()
        self.editor = user('editor', 'view_employee', 'change_employee', 'view_auditlog', group='Edit role')
        ProductionDepartment.objects.filter(pk=self.dept_a.pk).update(manager=self.editor)

    def snapshot(self):
        return (list(Employee.all_objects.order_by('pk').values_list('pk', 'last_name', 'version', 'is_deleted')),
                list(Posting.all_objects.order_by('pk').values_list('pk', 'valid_until', 'title', 'is_deleted')),
                AuditLog.objects.count())

    def test_an_edit_or_a_move_of_someone_in_another_team_is_a_404_and_changes_nothing(self):
        self.client.force_login(self.editor)
        before = self.snapshot()
        response = self.client.post(reverse('hr:employee_edit', args=[self.in_b.pk]), {
            'employee_number': 'E-2', 'last_name': 'Taken', 'first_name': 'Over', 'employment_type': 'staff',
            'joined_on': '2026-01-01', 'department': token(self.dept_a), 'title': 'Mine', 'from_day': '2026-03-01',
            'version': '1'})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.snapshot(), before)

    def test_the_list_never_shows_another_team_by_search_or_by_a_widening_filter(self):
        self.client.force_login(self.editor)
        for query in ({'q': 'Bravo'}, {'department': token(self.dept_b)}, {'q': 'E-2'}, {'type': 'staff'},
                      {'status': 'current', 'department': token(self.finance)}):
            listed = {e.last_name for e in self.client.get(reverse('hr:employee_list'), query).context['objects']}
            self.assertNotIn('Bravo', listed, query)
            self.assertNotIn('Charlie', listed, query)

    def test_a_lead_cannot_place_their_own_person_into_a_department_that_does_not_exist_or_is_stale(self):
        self.client.force_login(self.editor)
        before = self.snapshot()
        response = self.client.post(reverse('hr:employee_edit', args=[self.in_a.pk]), {
            'employee_number': 'E-1', 'last_name': 'Alfa', 'first_name': 'Ann', 'employment_type': 'staff',
            'joined_on': '2026-01-01', 'department': 'production:00000000-0000-0000-0000-000000000000',
            'title': 'X', 'from_day': '2026-03-01', 'version': '1'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('department', response.context['form'].errors)
        self.assertEqual(self.snapshot(), before)

    def test_a_lead_creating_a_person_has_no_team_to_put_them_in(self):
        creator = user('creator', 'view_employee', 'add_employee', group='Create role')
        ProductionDepartment.objects.filter(pk=self.dept_b.pk).update(manager=creator)
        self.client.force_login(creator)
        before = self.snapshot()
        response = self.client.post(reverse('hr:employee_create'), {
            'employee_number': 'E-50', 'last_name': 'New', 'first_name': 'Nina', 'employment_type': 'staff',
            'joined_on': '2026-02-01', 'department': token(self.dept_b), 'title': '', 'from_day': ''})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.snapshot(), before)         # the person was not created either: one transaction


class ActivityLogTests(PeopleTestCase):
    def test_the_people_are_in_the_log_for_the_holders_of_everyone_only(self):
        self.client.force_login(self.hr)
        from ..units import token as department_token
        self.client.post(reverse('hr:employee_create'), {
            'employee_number': 'E-60', 'last_name': 'Logged', 'first_name': 'Lena', 'employment_type': 'staff',
            'joined_on': '2026-02-01', 'department': department_token(self.finance), 'title': 'Clerk', 'from_day': ''})
        reader = user('reader', 'view_auditlog', group='Log role')
        auditor = user('auditor', 'view_auditlog', 'all_employee', group='Auditor role')
        self.client.force_login(reader)
        page = self.client.get(reverse('core:activity_log')).context['page']
        self.assertEqual([e.entity_type for e in page.object_list if e.entity_type in ('employee', 'placement')], [])
        self.client.force_login(auditor)
        types = {e.entity_type for e in self.client.get(reverse('core:activity_log')).context['page'].object_list}
        self.assertEqual({'employee', 'placement'} & types, {'employee', 'placement'})
        # asking for the type by the address finds nothing for the reader
        self.client.force_login(reader)
        found = self.client.get(reverse('core:activity_log'), {'type': 'employee'}).context['page'].object_list
        self.assertEqual(list(found), [])


class DepartmentHeadCountTests(PeopleTestCase):
    def counts(self, actor):
        self.client.force_login(actor)
        rows = self.client.get(reverse('hr:officedepartment_list')).context['objects']
        return {row.name: row.head_count for row in rows}

    def test_a_head_count_is_the_people_in_it_today_that_the_viewer_may_reach(self):
        everyone = self.counts(self.hr)
        self.assertEqual(everyone, {'Hatchery A': 1, 'Nursery B': 1, 'Administration': 0, 'Finance': 1})
        self.hr_dept_viewer = user('viewer', 'view_officedepartment')
        self.assertEqual(set(self.counts(self.hr_dept_viewer).values()), {0})            # no team, no count
        lead = user('lead', 'view_officedepartment', 'view_employee', group='Lead role')
        ProductionDepartment.objects.filter(pk=self.dept_a.pk).update(manager=lead)
        counts = self.counts(lead)
        self.assertEqual((counts['Hatchery A'], counts['Nursery B'], counts['Finance']), (1, 0, 0))

    def test_head_counts_follow_the_placements_not_a_stored_number(self):
        before = self.counts(self.hr)['Nursery B']
        place(employee('E-9', 'India'), self.dept_b, date(2026, 1, 1))
        self.assertEqual(self.counts(self.hr)['Nursery B'], before + 1)
        Posting.objects.filter(employee__employee_number='E-9').update(valid_until=date(2026, 1, 31))
        self.assertEqual(self.counts(self.hr)['Nursery B'], before)

"""The HR reads take a realm and only narrow by it (the same reader serves Company › HR and Production › Team), in the same
number of queries whatever the number of people; and a decision or a punch returns to the page it was made on (a checked
`next`), never to an address outside the site."""
from datetime import date, datetime, time, timezone as utc

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from farm.models import ProductionDepartment

from .. import read, scope
from ..models import Employee, LeaveRequest, LeaveType, Shift, ShiftAssignment
from .helpers import user
from .helpers_people import PeopleTestCase, employee, place

MONDAY = date(2026, 3, 2)
PRODUCTION, OFFICE = scope.PRODUCTION, scope.OFFICE


def last_names(rows):
    return sorted(row.employee.last_name for row in rows)


class RealmReadTests(PeopleTestCase):
    def setUp(self):
        super().setUp()
        self.early = Shift.objects.create(name='Early', code='EARLY', starts_at=time(6), ends_at=time(14))
        for person in (self.in_a, self.in_b, self.in_fin):
            ShiftAssignment.objects.create(employee=person, day=MONDAY, shift=self.early)
        self.hr_planner = user('hrplan', 'view_shiftassignment', 'all_employee', 'view_attendancerecord',
                               group='HR planner role')

    def test_the_week_and_the_overview_narrowed_to_a_realm(self):
        self.assertEqual(last_names(read.week(self.hr_planner, MONDAY, realm=PRODUCTION).rows), ['Alfa', 'Bravo'])
        self.assertEqual(last_names(read.week(self.hr_planner, MONDAY, realm=OFFICE).rows), ['Charlie'])
        self.assertEqual(last_names(read.week(self.hr_planner, MONDAY).rows), ['Alfa', 'Bravo', 'Charlie'])
        self.assertEqual(last_names(read.overview(self.hr_planner, MONDAY, realm=PRODUCTION).rows), ['Alfa', 'Bravo'])
        self.assertEqual(last_names(read.overview(self.hr_planner, MONDAY, realm=OFFICE).rows), ['Charlie'])

    def test_a_person_who_moved_shows_only_the_days_of_the_realm(self):
        mover = employee('E-8', 'Hotel')
        place(mover, self.dept_a, date(2026, 1, 1), date(2026, 3, 3))
        place(mover, self.finance, date(2026, 3, 4))
        row = next(row for row in read.week(self.hr_planner, MONDAY, realm=PRODUCTION).rows if row.employee == mover)
        self.assertEqual([cell.visible for cell in row.cells], [True, True, False, False, False, False, False])
        row = next(row for row in read.week(self.hr_planner, MONDAY, realm=OFFICE).rows if row.employee == mover)
        self.assertEqual([cell.visible for cell in row.cells], [False, False, True, True, True, True, True])

    def test_the_board_narrowed_to_a_realm(self):
        moment = datetime(2026, 3, 2, 8, 0, tzinfo=utc.utc)
        self.assertEqual(last_names(read.board(self.hr_planner, moment, realm=PRODUCTION).rows), ['Alfa', 'Bravo'])
        self.assertEqual(last_names(read.board(self.hr_planner, moment, realm=OFFICE).rows), ['Charlie'])

    def test_the_head_counts_narrowed_to_a_realm(self):
        production = read.head_counts(self.hr, MONDAY, realm=PRODUCTION)
        self.assertEqual(production, {(PRODUCTION, self.dept_a.pk): 1, (PRODUCTION, self.dept_b.pk): 1})
        self.assertEqual(read.head_counts(self.hr, MONDAY, realm=OFFICE), {(OFFICE, self.finance.pk): 1})

    def test_the_week_in_a_realm_runs_the_same_queries_for_few_and_many_people(self):
        read.week(self.hr_planner, MONDAY, realm=PRODUCTION)       # warm the permission cache

        def count(people):
            for n in range(people):
                person = employee(f'E-{3000 + n + people}', f'Many{n}')
                place(person, self.dept_a)
                ShiftAssignment.objects.create(employee=person, day=MONDAY, shift=self.early)
            with CaptureQueriesContext(connection) as queries:
                read.week(self.hr_planner, MONDAY, realm=PRODUCTION)
            return len(queries)
        self.assertEqual(count(5), count(40))


class ReturnTests(PeopleTestCase):
    """A decision, a cancel or a punch returns to `next` when it is an address of this site, else to its own page."""

    def setUp(self):
        super().setUp()
        self.kind = LeaveType.objects.create(name='Annual leave', code='ANNUAL')
        self.lead = user('boss', 'view_employee', 'view_leaverequest', 'change_leaverequest', 'view_attendancerecord',
                         group='Lead role')
        ProductionDepartment.objects.filter(pk=self.dept_a.pk).update(manager=self.lead)
        self.client.force_login(self.lead)

    def ask(self):
        return LeaveRequest.objects.create(employee=self.in_a, leave_type=self.kind, first_day=MONDAY, last_day=MONDAY)

    def test_a_decision_returns_to_a_local_next(self):
        for name, data in (('hr:leaverequest_reject', {'note': 'No'}), ('hr:leaverequest_cancel', {})):
            response = self.client.post(reverse(name, args=[self.ask().pk]), {**data, 'next': '/hr/leave/?tab=all'})
            self.assertRedirects(response, '/hr/leave/?tab=all', fetch_redirect_response=False)

    def test_a_foreign_next_is_ignored(self):
        for name in ('hr:leaverequest_reject', 'hr:leaverequest_cancel'):
            response = self.client.post(reverse(name, args=[self.ask().pk]), {'note': 'x',
                                                                             'next': 'https://evil.example/'})
            self.assertRedirects(response, reverse('hr:leaverequest_list'), fetch_redirect_response=False)

    def test_a_punch_returns_to_a_local_next_and_ignores_a_foreign_one(self):
        account = user('ann', 'view_attendancerecord', group='Staff role')
        Employee.objects.filter(pk=self.in_a.pk).update(user=account, first_name='', last_name='')
        self.client.force_login(account)
        response = self.client.post(reverse('hr:punch', args=['in']), {'next': '/hr/?from=punch'})
        self.assertRedirects(response, '/hr/?from=punch', fetch_redirect_response=False)
        response = self.client.post(reverse('hr:punch', args=['out']), {'next': '//evil.example/'})
        self.assertRedirects(response, reverse('hr:today'), fetch_redirect_response=False)

"""A production worker's crew (Crew, hr.crew_shiftassignment): under their own week, the name and shift code and times of the
people in their own production department on each day, and nothing else of theirs: no note, no finding, no leave or its type,
no punch, no employee number, no planned hours, no link. A day off, a day on leave and a day with nothing planned are the
same empty cell."""
from datetime import date, datetime, time, timezone as utc

from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .. import read
from ..models import AttendanceRecord, Employee, LeaveRequest, LeaveType, Shift, ShiftAssignment
from .helpers import user
from .helpers_people import PeopleTestCase, employee, place

MONDAY = date(2026, 3, 2)
WORKER = ('view_attendancerecord', 'view_shiftassignment', 'crew_shiftassignment', 'view_leaverequest',
          'add_leaverequest')


class CrewTestCase(PeopleTestCase):
    def setUp(self):
        super().setUp()
        self.worker = user('ann', *WORKER, group='Worker role')
        Employee.objects.filter(pk=self.in_a.pk).update(user=self.worker, first_name='', last_name='')
        self.peer = employee('E-4', 'Delta', 'Dina')
        self.off_peer = employee('E-5', 'Echo', 'Eli')
        self.leave_peer = employee('E-6', 'Foxtrot', 'Fay')
        for person in (self.peer, self.off_peer, self.leave_peer):
            place(person, self.dept_a)
        self.early = Shift.objects.create(name='Early', code='EARLY', starts_at=time(6), ends_at=time(14), tone=2)
        ShiftAssignment.objects.create(employee=self.peer, day=MONDAY, shift=self.early, note='Private note words')
        ShiftAssignment.objects.create(employee=self.off_peer, day=MONDAY, shift=None, note='Off note words')
        ShiftAssignment.objects.create(employee=self.in_b, day=MONDAY, shift=self.early)   # another department
        ShiftAssignment.objects.create(employee=self.in_a, day=MONDAY, shift=self.early)
        self.sick = LeaveType.objects.create(name='Sick leave', code='SICK', needs_approval=False)
        LeaveRequest.objects.create(employee=self.leave_peer, leave_type=self.sick, first_day=MONDAY, last_day=MONDAY,
                                    status='approved', decided_at=datetime(2026, 1, 1, tzinfo=utc.utc),
                                    reason='Private reason words')
        AttendanceRecord.objects.create(employee=self.peer, clock_in=datetime(2026, 3, 2, 5, tzinfo=utc.utc),
                                        clock_out=datetime(2026, 3, 2, 13, tzinfo=utc.utc), note='Punch note words')

    def page(self, actor=None, name='hr:production_shiftassignment_list'):
        self.client.force_login(actor or self.worker)
        return self.client.get(reverse(name), {'week': MONDAY.isoformat()})


class CrewReadTests(CrewTestCase):
    def test_the_crew_is_the_department_on_each_day_with_shift_code_and_times(self):
        crew = read.crew_week(self.worker, MONDAY)
        self.assertEqual(crew.days[0], MONDAY)
        rows = {row.name: row for row in crew.rows}
        self.assertEqual(set(rows), {'Dina Delta', 'Eli Echo', 'Fay Foxtrot'})
        monday = rows['Dina Delta'].cells[0]
        self.assertEqual((monday.day, monday.shift_code, monday.starts_at, monday.ends_at, monday.tone),
                         (MONDAY, 'EARLY', time(6), time(14), 2))
        self.assertEqual(rows['Dina Delta'].department, 'Hatchery A')

    def test_off_on_leave_and_nothing_planned_are_the_same_empty_cell(self):
        rows = {row.name: row for row in read.crew_week(self.worker, MONDAY).rows}
        self.assertIsNone(rows['Eli Echo'].cells[0])            # planned off
        self.assertIsNone(rows['Fay Foxtrot'].cells[0])         # on approved sick leave
        self.assertIsNone(rows['Dina Delta'].cells[1])          # nothing planned

    def test_the_rows_carry_no_record_and_nothing_private(self):
        crew = read.crew_week(self.worker, MONDAY)
        for row in crew.rows:
            self.assertEqual(set(vars(row)), {'name', 'department', 'cells'})
            for cell in row.cells:
                if cell is not None:
                    self.assertEqual(set(vars(cell)), {'day', 'shift_code', 'starts_at', 'ends_at', 'tone'})
                    self.assertNotIsInstance(cell, ShiftAssignment)

    def test_a_crew_of_another_department_never_shows(self):
        self.assertNotIn('Bob Bravo', [row.name for row in read.crew_week(self.worker, MONDAY).rows])

    def test_the_queries_do_not_grow_with_the_crew(self):
        read.crew_week(self.worker, MONDAY)

        def count(people):
            for n in range(people):
                person = employee(f'E-{3000 + n + people}', f'Many{n}')
                place(person, self.dept_a)
                ShiftAssignment.objects.create(employee=person, day=MONDAY, shift=self.early)
            with CaptureQueriesContext(connection) as queries:
                read.crew_week(self.worker, MONDAY)
            return len(queries)
        self.assertEqual(count(5), count(40))


class CrewPageTests(CrewTestCase):
    def test_the_worker_sees_their_own_week_and_the_crew_block(self):
        response = self.page()
        self.assertEqual([row.employee for row in response.context['week'].rows], [self.in_a])
        self.assertEqual({row.name for row in response.context['crew'].rows}, {'Dina Delta', 'Eli Echo', 'Fay Foxtrot'})
        self.assertContains(response, 'Crew this week')
        self.assertContains(response, 'Dina Delta')

    def test_the_page_carries_nothing_private_of_the_crew(self):
        html = self.page().content.decode()
        for private in ('Private note words', 'Off note words', 'Private reason words', 'Punch note words', 'Sick leave',
                        'SICK', 'E-4', 'E-5', 'E-6', str(self.peer.pk), str(self.leave_peer.pk)):
            self.assertNotIn(private, html, private)

    def test_without_crew_there_is_no_block(self):
        plain = user('bob', 'view_shiftassignment', group='Plain role')
        Employee.objects.filter(pk=self.in_b.pk).update(user=plain, first_name='', last_name='')
        response = self.page(plain)
        self.assertIsNone(response.context['crew'])
        self.assertNotContains(response, 'Crew this week')

    def test_who_is_no_worker_has_no_crew_block_and_an_unplaced_worker_is_told_why_it_is_empty(self):
        """A crew is a worker's: someone with no employee record (the platform admin) gets no block; a worker with no
        production placement this week is told so, never that nobody else is placed in their department."""
        admin = get_user_model().objects.create_superuser('root', 'root@example.com', 'x')
        response = self.page(admin)
        self.assertIsNone(response.context['crew'])
        self.assertNotContains(response, 'Crew this week')
        unplaced = user('cyd', *WORKER, group='Unplaced worker role')
        employee('E-7', '', '', user=unplaced)                  # an account's row: the name is the account's
        response = self.page(unplaced)
        self.assertFalse(response.context['crew'].placed)
        self.assertContains(response, 'You are not placed in a production department this week, so you have no crew.')
        self.assertNotContains(response, 'Nobody else is placed in your department this week.')
        self.assertTrue(read.crew_week(self.worker, MONDAY).placed)

    def test_the_company_page_has_no_crew_block(self):
        office = user('ola', *WORKER, group='Office crew role')            # an office person reads the company page
        Employee.objects.filter(pk=self.in_fin.pk).update(user=office, first_name='', last_name='')
        self.assertIsNone(self.page(office, name='hr:shiftassignment_list').context['crew'])
        # A production-only worker's company Shift schedule is refused, as its menu leaves it out.
        self.assertEqual(self.page(name='hr:shiftassignment_list').status_code, 403)

    def test_a_colleagues_records_stay_out_of_reach_by_address(self):
        self.client.force_login(self.worker)
        plan = ShiftAssignment.objects.get(employee=self.peer, day=MONDAY)
        for name in ('hr:production_shiftassignment_edit', 'hr:production_shiftassignment_delete'):
            self.assertIn(self.client.get(reverse(name, args=[plan.pk])).status_code, (403, 404), name)
        leave = LeaveRequest.objects.get(employee=self.leave_peer)
        self.assertEqual(self.client.get(reverse('hr:production_leaverequest_detail', args=[leave.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('hr:production_employee_detail', args=[self.peer.pk])).status_code, 403)

    def test_a_leave_search_by_type_finds_only_ones_own(self):
        own = LeaveRequest.objects.create(employee=self.in_a, leave_type=self.sick, first_day=date(2026, 3, 9),
                                          last_day=date(2026, 3, 9), status='approved',
                                          decided_at=datetime(2026, 1, 1, tzinfo=utc.utc))
        self.client.force_login(self.worker)
        found = self.client.get(reverse('hr:production_leaverequest_list'), {'q': 'sick', 'tab': 'all'}).context['objects']
        self.assertEqual([row['request'] for row in found], [own])

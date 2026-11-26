"""One write path and one rule per question in HR (the architecture audit of 26.11.2026, H-1, H-5 and M-6), each as a
test that failed before its fix:

- the leave correction window is the platform owner's setting, read in core.platform, never a figure of HR's own;
- a tab's save is the service's: presence entered on the Attendance page goes through hr.services.enter_presence, a last
  day typed on a person's form through hr.services.leave_company, and every HR tab locks the person before it writes a
  record of theirs (HR's lock order), as the services do;
- one rule says which day and which site govern a person's moment (the placement of the company's day, the day on that
  site's clock): the Attendance list, the board and the person's own open clock-in read it, so a site on another clock
  than the company's is read the same way by every page;
- the roster's batch plan reaches a person per day, as the service does: next week's newcomer is planned, not a 404;
  painting one's own cell is told why, as the cell's own dialog says."""
from datetime import date, datetime, time, timedelta, timezone as utc
from unittest import mock

from django.contrib.messages import get_messages
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from core.models import PlatformSettings
from core.testing import FrozenClock
from farm.models import ProductionDepartment, Site

from .. import read, services
from ..models import AttendanceRecord, Employee, LeaveType, Posting, Shift, ShiftAssignment
from ..units import token
from .helpers import user
from .helpers_people import PeopleTestCase, TOP, employee, place
from .test_leave import LeaveTestCase, request_for
from .test_leave_correction import FIRST, LAST, on

UTC = utc.utc
EVERY_VERB = ('view_employee', 'view_shiftassignment', 'add_shiftassignment', 'change_shiftassignment',
              'delete_shiftassignment', 'view_attendancerecord', 'add_attendancerecord', 'change_attendancerecord',
              'delete_attendancerecord', 'view_leaverequest', 'add_leaverequest', 'change_leaverequest')


# ---- H-1: the correction window is the platform's ------------------------------------------------------------------
class CorrectionWindowIsThePlatformsTests(LeaveTestCase):
    def setUp(self):
        super().setUp()
        self.leave = request_for(self.in_a, FIRST, LAST, self.annual, status='approved')

    def test_a_shorter_window_refuses_a_correction_hr_used_to_allow_and_says_its_days(self):
        PlatformSettings.objects.update(correction_window_days=7)
        with on(LAST + timedelta(days=8)):
            self.assertFalse(services.can_correct(self.lead, self.leave))
            with self.assertRaisesMessage(Exception, 'more than 7 days ago'):
                services.cancel_leave(self.lead, self.leave)
        self.leave.refresh_from_db()
        self.assertEqual(self.leave.status, 'approved')

    def test_a_longer_window_allows_a_correction_hr_used_to_refuse(self):
        PlatformSettings.objects.update(correction_window_days=60)
        with on(LAST + timedelta(days=40)):
            services.shorten_leave(self.lead, self.leave, date(2026, 1, 9))
        self.leave.refresh_from_db()
        self.assertEqual(self.leave.last_day, date(2026, 1, 9))


# ---- H-5: a tab's save is the service's ------------------------------------------------------------------------------
def lock_before_write(case, table, call):
    """Runs `call` and checks that the person's row was locked before the first row of `table` was written."""
    with CaptureQueriesContext(connection) as seen:
        response = call()
    sql = [query['sql'] for query in seen.captured_queries]
    written = next((n for n, text in enumerate(sql) if text.startswith(f'INSERT INTO "{table}"')), None)
    case.assertIsNotNone(written, getattr(response, 'context', None) and response.context['form'].errors)
    locked = [n for n, text in enumerate(sql) if ' FROM "employees"' in text and ' FOR ' in text and 'UPDATE' in text]
    case.assertTrue(locked and locked[0] < written, f'the person is locked at {locked}, the {table} row written at {written}')


class TabsLockThePersonFirstTests(PeopleTestCase):
    """HR's lock order is the person first, then the person's records (hr.services): a tab that saved the record and
    locked the person after it could wait on a last day being set the other way round."""

    def setUp(self):
        super().setUp()
        self.lead = user('boss', *EVERY_VERB, group='Lead role')
        ProductionDepartment.objects.filter(pk=self.dept_a.pk).update(manager=self.lead)
        self.client.force_login(self.lead)

    def test_entering_presence(self):
        lock_before_write(self, 'attendance_records', lambda: self.client.post(
            reverse('hr:production_attendancerecord_create'), {'employee': str(self.in_a.pk), 'clock_in': '2026-03-02T07:00',
                                                               'clock_out': '2026-03-02T15:00', 'note': 'Phone was dead'}))

    def test_planning_a_day_in_its_dialog(self):
        shift = Shift.objects.create(name='Early', code='EARLY', starts_at=time(6), ends_at=time(14))
        lock_before_write(self, 'shift_assignments', lambda: self.client.post(
            reverse('hr:production_shiftassignment_create'), {'employee': str(self.in_a.pk), 'day': '2026-03-02',
                                                              'shift': str(shift.pk), 'note': ''}))

    def test_filing_leave(self):
        kind = LeaveType.objects.create(name='Annual', code='AN')
        lock_before_write(self, 'leave_requests', lambda: self.client.post(
            reverse('hr:production_leaverequest_create'), {'employee': str(self.in_a.pk), 'leave_type': str(kind.pk),
                                                           'first_day': '2026-03-02', 'last_day': '2026-03-03',
                                                           'reason': ''}))


class TabsCallTheServiceTests(PeopleTestCase):
    def test_presence_typed_on_the_attendance_page_is_entered_by_the_service(self):
        lead = user('boss', *EVERY_VERB, group='Lead role')
        ProductionDepartment.objects.filter(pk=self.dept_a.pk).update(manager=lead)
        self.client.force_login(lead)
        with mock.patch.object(services, 'enter_presence', wraps=services.enter_presence) as entered:
            response = self.client.post(reverse('hr:production_attendancerecord_create'), {
                'employee': str(self.in_a.pk), 'clock_in': '2026-03-02T07:00', 'clock_out': '2026-03-02T15:00',
                'note': 'Phone was dead'})
        self.assertEqual(response.status_code, 302)
        entered.assert_called_once()
        self.assertEqual(AttendanceRecord.objects.get().note, 'Phone was dead')

    def test_a_last_day_typed_on_the_person_form_is_set_by_leave_company(self):
        self.client.force_login(self.hr)
        with mock.patch.object(services, 'leave_company', wraps=services.leave_company) as leaving:
            response = self.client.post(reverse('hr:production_employee_edit', args=[self.in_a.pk]), {
                'employee_number': 'E-1', 'last_name': 'Alfa', 'first_name': 'Ann', 'employment_type': 'staff',
                'joined_on': '2026-01-01', 'left_on': '2026-03-15', 'department': token(self.dept_a),
                'title': 'Technician', 'from_day': '2026-01-01', 'version': '1'})
        self.assertEqual(response.status_code, 302)
        leaving.assert_called_once()
        self.in_a.refresh_from_db()
        self.assertEqual(self.in_a.left_on, date(2026, 3, 15))


# ---- M-6: one rule for the day and the site of a person's moment ------------------------------------------------------
class AnotherClockTests(FrozenClock, PeopleTestCase):
    """The company is on Oslo's clock (settings.COMPANY_TIME_ZONE); departments A and B are on a site in Auckland
    (UTC+13 in March). Ann is in A up to 2 March and in B from 3 March. 01:00 on 3 March in Auckland is 12:00 UTC on
    2 March, still 2 March on the company's clock: the placement of the company's day (A) governs the stretch, so it is
    A's lead's to enter and to list, shown on A's site's clock as 3 March 01:00 (hr.read.governing). The clock stands
    at 20:00 UTC on 2 March: the form offers a lead the people of their team today."""
    NOW = datetime(2026, 3, 2, 20, tzinfo=UTC)

    def setUp(self):
        super().setUp()
        auckland = Site.objects.create(name='Auckland', code='AK', timezone='Pacific/Auckland')
        ProductionDepartment.objects.filter(pk__in=[self.dept_a.pk, self.dept_b.pk]).update(site=auckland)
        self.boss_a = user('bossa', *EVERY_VERB, group='Boss A role')
        self.boss_b = user('bossb', *EVERY_VERB, group='Boss B role')
        ProductionDepartment.objects.filter(pk=self.dept_a.pk).update(manager=self.boss_a)
        ProductionDepartment.objects.filter(pk=self.dept_b.pk).update(manager=self.boss_b)
        Posting.objects.filter(employee=self.in_a).update(valid_until=date(2026, 3, 2))
        place(self.in_a, self.dept_b, start=date(2026, 3, 3))

    def listed(self, actor):
        self.client.force_login(actor)
        return [record.pk for record in self.client.get(reverse('hr:production_attendancerecord_list'),
                                                        {'from': '01.03.2026', 'to': '04.03.2026'}).context['objects']]

    def test_a_stretch_a_lead_enters_is_on_that_leads_list_and_no_one_elses(self):
        self.client.force_login(self.boss_a)
        response = self.client.post(reverse('hr:production_attendancerecord_create'), {
            'employee': str(self.in_a.pk), 'clock_in': '2026-03-03T01:00', 'clock_out': '2026-03-03T05:00',
            'note': 'Phone was dead'})
        self.assertEqual(response.status_code, 302, response.context and response.context['form'].errors)
        record = AttendanceRecord.objects.get()
        self.assertEqual(record.clock_in, datetime(2026, 3, 2, 12, tzinfo=UTC))
        self.assertEqual((self.listed(self.boss_a), self.listed(self.boss_b)), ([record.pk], []))
        self.client.force_login(self.boss_a)
        shown = self.client.get(reverse('hr:production_attendancerecord_edit', args=[record.pk])).context['form']
        self.assertEqual(shown['clock_in'].value().isoformat(), '2026-03-03T01:00:00')


class MoveDayBoardTests(FrozenClock, PeopleTestCase):
    """Ann moves from A (a site in Auckland) to B (a site on UTC) on 3 March. At 05:00 UTC on the 3rd it is the 3rd on
    the company's clock (06:00 in Oslo), so B governs her: its department and its clock, though a clock in Los Angeles
    still reads the 2nd."""
    NOW = datetime(2026, 3, 3, 5, tzinfo=UTC)

    def setUp(self):
        super().setUp()
        auckland = Site.objects.create(name='Auckland', code='AK', timezone='Pacific/Auckland')
        Site.objects.create(name='Los Angeles', code='LA', timezone='America/Los_Angeles')
        ProductionDepartment.objects.filter(pk=self.dept_a.pk).update(site=auckland)
        Posting.objects.filter(employee=self.in_a).update(valid_until=date(2026, 3, 2))
        place(self.in_a, self.dept_b, start=date(2026, 3, 3))

    def test_the_board_reads_the_department_and_the_clock_of_the_companys_day(self):
        AttendanceRecord.objects.create(employee=self.in_a, clock_in=datetime(2026, 3, 3, 4, tzinfo=UTC), via='self')
        row = next(row for row in read.board(self.hr, self.NOW).rows if row.employee == self.in_a)
        self.assertEqual((row.department, row.zone.key, row.day), (self.dept_b, 'UTC', date(2026, 3, 3)))

    def test_the_own_open_clock_in_is_shown_on_the_clock_it_was_made_on(self):
        worker = user('ann', 'view_attendancerecord', group='Worker role')
        Employee.objects.filter(pk=self.in_a.pk).update(user=worker, first_name='', last_name='')
        AttendanceRecord.objects.create(employee=self.in_a, clock_in=datetime(2026, 3, 2, 20, tzinfo=UTC), via='self')
        self.client.force_login(worker)
        page = self.client.get(reverse('hr:production_today'))
        self.assertEqual(page.context['open_zone'].key, 'Pacific/Auckland')     # 21:00 on 2 March in Oslo: A's day


class PlanPerDayTests(FrozenClock, PeopleTestCase):
    """Today is Wednesday 4 March. Nina joins the planner's department A from Monday 9 March (she is in B until then)."""
    NOW = datetime(2026, 3, 4, 12, tzinfo=UTC)

    def setUp(self):
        super().setUp()
        self.planner = user('planner', *EVERY_VERB, group='Planner role')
        ProductionDepartment.objects.filter(pk=self.dept_a.pk).update(manager=self.planner)
        self.nina = employee('E-60', 'Nilsen', 'Nina')
        place(self.nina, self.dept_b, TOP, date(2026, 3, 8))
        place(self.nina, self.dept_a, date(2026, 3, 9))
        self.early = Shift.objects.create(name='Early', code='EARLY', starts_at=time(6), ends_at=time(14))
        self.client.force_login(self.planner)

    def paint(self, *cells, shift=None):
        return self.client.post(reverse('hr:production_roster_plan'), {
            'cells': [f'{person.pk}:{day.isoformat()}' for person, day in cells],
            'shift': shift or str(self.early.pk), 'next': '/production/team/schedule/?week=2026-03-09'})

    def test_next_weeks_newcomer_is_planned_from_the_grid(self):
        response = self.paint((self.nina, date(2026, 3, 9)), (self.nina, date(2026, 3, 10)))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(sorted(ShiftAssignment.objects.filter(employee=self.nina).values_list('day', flat=True)),
                         [date(2026, 3, 9), date(2026, 3, 10)])

    def test_a_day_before_she_is_the_planners_is_a_404_and_writes_nothing(self):
        self.assertEqual(self.paint((self.nina, date(2026, 3, 6)), (self.nina, date(2026, 3, 9))).status_code, 404)
        self.assertEqual(ShiftAssignment.objects.count(), 0)

    def test_painting_ones_own_cell_is_told_why_and_writes_nothing(self):
        Employee.objects.filter(pk=self.in_a.pk).update(user=self.planner, first_name='', last_name='')
        response = self.paint((self.in_a, date(2026, 3, 9)))
        self.assertEqual(response.status_code, 302)
        said = [str(message) for message in get_messages(response.wsgi_request)]
        self.assertIn('You do not plan your own days.', said)
        self.assertEqual(ShiftAssignment.objects.count(), 0)


# ---- the review of the branch (F:/dev/balik-notes/hr-one-path/REVIEW-1.md) ------------------------------------------
def hr_functions():
    """(module, function node) of every function of the HR production code."""
    import ast
    from pathlib import Path
    hr = Path(__file__).resolve().parent.parent
    for path in sorted(hr.rglob('*.py')):
        if 'tests' in path.parts or 'migrations' in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if isinstance(node, ast.FunctionDef):
                yield path.relative_to(hr.parent).as_posix(), node


class OnePlaceTests(PeopleTestCase):
    def test_the_week_starts_in_one_place(self):
        self.assertEqual([module for module, function in hr_functions() if function.name == 'monday'], ['hr/rules.py'])

    def test_the_person_is_locked_by_one_helper_at_one_strength(self):
        """L-1: every lock of a person's row is hr.services.lock_person's or lock_people's (FOR NO KEY UPDATE)."""
        import ast
        found = {f'{module}:{function.name}' for module, function in hr_functions()
                 if 'Employee.objects.select_for_update' in ast.unparse(function)}
        self.assertEqual(found, {'hr/services.py:lock_person', 'hr/services.py:lock_people'})


class PlanRaceTests(PeopleTestCase):
    """M-3: a plan saved between a dialog's check and its save is not overwritten: Create expects no plan for the cell,
    Edit the plan it read."""

    def setUp(self):
        super().setUp()
        self.planner = user('planner', *EVERY_VERB, group='Planner role')
        ProductionDepartment.objects.filter(pk=self.dept_a.pk).update(manager=self.planner)
        self.early = Shift.objects.create(name='Early', code='EARLY', starts_at=time(6), ends_at=time(14))
        self.late = Shift.objects.create(name='Late', code='LATE', starts_at=time(14), ends_at=time(22))
        self.client.force_login(self.planner)

    def test_a_create_that_meets_a_plan_saved_meanwhile_is_refused_and_changes_nothing(self):
        from ..resources.roster import ShiftAssignmentResource
        create = ShiftAssignmentResource.create_record.__func__

        def raced(cls, request, form):
            ShiftAssignment.objects.create(employee=self.in_a, day=date(2026, 3, 2), shift=self.late)   # another lead's
            return create(cls, request, form)
        with mock.patch.object(ShiftAssignmentResource, 'create_record', classmethod(raced)):
            response = self.client.post(reverse('hr:production_shiftassignment_create'), {
                'employee': str(self.in_a.pk), 'day': '2026-03-02', 'shift': str(self.early.pk), 'note': ''})
        self.assertEqual(response.context['form'].errors, {'day': ['This person already has a plan for this day.']})
        self.assertEqual(ShiftAssignment.objects.count(), 0)                  # the raced row went with the refused save

    def test_the_service_refuses_a_cell_that_is_not_as_the_caller_expects(self):
        other = ShiftAssignment.objects.create(employee=self.in_a, day=date(2026, 3, 2), shift=self.late)
        elsewhere = ShiftAssignment.objects.create(employee=self.in_a, day=date(2026, 3, 3), shift=self.late)
        for expected in (None, elsewhere):
            with self.subTest(expected=expected), self.assertRaisesMessage(
                    Exception, 'This person already has a plan for this day.'):
                services.plan_day(self.planner, self.in_a, date(2026, 3, 2), self.early, '', expected)
        other.refresh_from_db()
        self.assertEqual((other.shift, other.version), (self.late, 1))
        row, _warnings = services.plan_day(self.planner, self.in_a, date(2026, 3, 2), self.early, '', other)
        self.assertEqual((row.pk, row.shift), (other.pk, self.early))


class BatchPlanBoundTests(PlanPerDayTests):
    def test_two_cells_centuries_apart_are_checked_cell_by_cell(self):
        """L-2: the view asks the reach of each cell, never a set of every day between the first and the last."""
        from .. import scope
        with mock.patch.object(scope, '_days', side_effect=AssertionError('a span of days was built')):
            response = self.paint((self.in_a, date(1900, 1, 1)), (self.in_a, date(2100, 12, 31)))
        self.assertIn(response.status_code, (302, 404))
        self.assertEqual(ShiftAssignment.objects.count(), 0)


class LeaveReachTests(LeaveTestCase):
    """L-4: a request is filed and moved only to a first day on which the person is the user's (the day it is listed and
    decided by). Ann is the lead's until 31 May 2027 and another lead's from June."""

    def setUp(self):
        super().setUp()
        Posting.objects.filter(employee=self.in_a).update(valid_until=date(2027, 5, 31))
        place(self.in_a, self.dept_b, start=date(2027, 6, 1))

    def test_a_lead_does_not_file_for_a_first_day_that_is_another_leads(self):
        response = self.file(self.lead, self.in_a, date(2027, 6, 7), date(2027, 6, 8))
        self.assertEqual(response.context['form'].errors, {'first_day': ['You do not see this person on this day.']})
        self.assertEqual(self.file(self.ann_user, self.in_a, date(2027, 6, 7), date(2027, 6, 8)).status_code, 302)

    def test_a_lead_does_not_move_a_request_to_a_first_day_that_is_another_leads(self):
        request = request_for(self.in_a, date(2027, 5, 24), date(2027, 5, 25), self.annual)
        with self.assertRaisesMessage(Exception, 'You do not see this person on this day.'):
            services.change_leave(self.lead, request, self.annual, date(2027, 6, 7), date(2027, 6, 8))
        request.refresh_from_db()
        self.assertEqual(request.first_day, date(2027, 5, 24))
        services.change_leave(self.lead, request, self.annual, date(2027, 5, 27), date(2027, 5, 28))


class RefusedAtTheSaveTests(PeopleTestCase):
    def test_a_refusal_at_the_save_answers_422_on_create_as_on_edit(self):
        """L-6: the form again with the reason, and the status every refusal at the save has."""
        lead = user('boss', *EVERY_VERB, group='Lead role')
        ProductionDepartment.objects.filter(pk=self.dept_a.pk).update(manager=lead)
        self.client.force_login(lead)
        response = self.client.post(reverse('hr:production_attendancerecord_create'), {
            'employee': str(self.in_a.pk), 'clock_in': '2026-03-02T07:00', 'clock_out': '', 'note': ''})
        self.assertEqual((response.status_code, list(response.context['form'].errors)), (422, ['note']))
        self.assertEqual(AttendanceRecord.objects.count(), 0)


class RestoreTests(PeopleTestCase):
    def test_the_admins_restore_refuses_a_record_its_service_writes(self):
        """M-2: a voided stretch brought back by the delete plan's restore would skip the service's rules (the lead's
        reach, the employment, never one's own): it is refused with the way forward, and nothing changes."""
        from django.core.exceptions import ValidationError

        from core import softdelete
        record = AttendanceRecord.objects.create(employee=self.in_a, clock_in=datetime(2026, 3, 2, 6, tzinfo=UTC),
                                                 clock_out=datetime(2026, 3, 2, 14, tzinfo=UTC), via='self')
        record.soft_delete(self.hr)
        with self.assertRaises(ValidationError) as refused:
            softdelete.restore(record, self.hr)
        self.assertIn('enter it again', ' '.join(refused.exception.messages))
        self.assertTrue(AttendanceRecord.all_objects.get(pk=record.pk).is_deleted)

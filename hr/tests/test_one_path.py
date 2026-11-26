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
class AnotherClockTests(PeopleTestCase):
    """The company is on Oslo's clock (settings.COMPANY_TIME_ZONE); departments A and B are on a site in Auckland
    (UTC+13 in March). Ann is in A up to 2 March and in B from 3 March. 01:00 on 3 March in Auckland is 12:00 UTC on
    2 March, still 2 March on the company's clock: the placement of the company's day (A) gives the site and its clock,
    and on that clock the stretch is of 3 March, B's day (hr.read.governing)."""

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
        self.client.force_login(self.boss_b)
        response = self.client.post(reverse('hr:production_attendancerecord_create'), {
            'employee': str(self.in_a.pk), 'clock_in': '2026-03-03T01:00', 'clock_out': '2026-03-03T05:00',
            'note': 'Phone was dead'})
        self.assertEqual(response.status_code, 302, response.context and response.context['form'].errors)
        record = AttendanceRecord.objects.get()
        self.assertEqual(record.clock_in, datetime(2026, 3, 2, 12, tzinfo=UTC))
        self.assertEqual((self.listed(self.boss_b), self.listed(self.boss_a)), ([record.pk], []))


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

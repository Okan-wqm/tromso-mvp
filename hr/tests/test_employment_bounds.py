"""A person's HR records lie within their employment: no shift planned, no presence entered or punched and no leave asked
for a day before they joined or after their last day. A lead was held to it by the placements (they end on the last day);
a holder of Everyone, and the person themselves (their own clock-in, their own leave), were not. One rule
(hr.services.check_employed) for every path; a refusal writes nothing."""
from datetime import date, datetime, time, timezone as utc
from unittest import mock

from django.core.exceptions import ValidationError
from django.urls import reverse

from core.models import AuditLog

from .. import services
from ..models import AttendanceRecord, Employee, LeaveRequest, LeaveType, Shift, ShiftAssignment
from .helpers import user
from .helpers_people import PeopleTestCase

JOINED, LEFT = date(2026, 1, 1), date(2026, 3, 31)


def at(day, hour):
    return datetime.combine(day, time(hour), tzinfo=utc.utc)


class EmploymentCase(PeopleTestCase):
    def setUp(self):
        super().setUp()
        self.everyone = user('everyone', 'view_employee', 'change_employee', 'view_shiftassignment', 'add_shiftassignment',
                             'change_shiftassignment', 'view_attendancerecord', 'add_attendancerecord',
                             'view_leaverequest', 'add_leaverequest', 'change_leaverequest', 'all_employee',
                             group='Everyone role')
        self.ann = user('ann', 'view_attendancerecord', 'view_leaverequest', 'add_leaverequest', group='Staff role')
        Employee.objects.filter(pk=self.in_a.pk).update(user=self.ann, first_name='', last_name='', left_on=LEFT)
        self.in_a.refresh_from_db()
        self.early = Shift.objects.create(name='Early', code='EARLY', starts_at=time(6), ends_at=time(14))
        self.annual = LeaveType.objects.create(name='Annual leave', code='ANNUAL')

    def counts(self):
        return (ShiftAssignment.all_objects.count(), AttendanceRecord.objects.count(), LeaveRequest.objects.count(),
                AuditLog.objects.count())


class EmploymentBoundsTests(EmploymentCase):

    def test_no_shift_is_planned_outside_the_employment(self):
        before = self.counts()
        for day in (date(2025, 12, 31), date(2026, 4, 1)):
            with self.subTest(day=day), self.assertRaises(ValidationError):
                services.plan_shifts(self.everyone, [(self.in_a, day)], self.early)
        self.assertEqual(self.counts(), before)
        services.plan_shifts(self.everyone, [(self.in_a, LEFT)], self.early)            # the last day is a working day
        self.assertEqual(ShiftAssignment.objects.count(), 1)

    def test_no_presence_is_entered_outside_the_employment(self):
        before = self.counts()
        with self.assertRaises(ValidationError):
            services.enter_presence(self.everyone, self.in_a, at(date(2026, 4, 2), 6), at(date(2026, 4, 2), 14), 'Forgot')
        self.assertEqual(self.counts(), before)

    def test_the_attendance_form_refuses_a_day_outside_the_employment(self):
        self.client.force_login(self.everyone)
        before = self.counts()
        response = self.client.post(reverse('hr:attendancerecord_create'), {
            'employee': str(self.in_a.pk), 'clock_in': '2026-04-02T06:00', 'clock_out': '2026-04-02T14:00',
            'note': 'Forgot'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].errors)
        self.assertEqual(self.counts(), before)

    def test_a_person_who_has_left_cannot_clock_in(self):
        before = self.counts()
        with mock.patch('django.utils.timezone.now', return_value=at(date(2026, 4, 2), 6)), \
                self.assertRaises(ValidationError):
            services.clock_in(self.ann)
        self.assertEqual(self.counts(), before)

    def test_no_leave_is_asked_outside_the_employment(self):
        before = self.counts()
        for actor in (self.ann, self.everyone):
            self.client.force_login(actor)
            response = self.client.post(reverse('hr:production_leaverequest_create'), {
                'employee': str(self.in_a.pk), 'leave_type': str(self.annual.pk), 'first_day': '2026-03-30',
                'last_day': '2026-04-03', 'reason': ''})
            self.assertEqual(response.status_code, 200, actor)
            self.assertTrue(response.context['form'].errors, actor)
        self.assertEqual(self.counts(), before)

    # Only the employment rule refuses these: the person still works here (in every team, in the panel's realm today), and
    # the day is before they joined.
    def reachable_today(self):
        Employee.objects.filter(pk=self.in_a.pk).update(left_on=None)
        self.in_a.refresh_from_db()

    def test_the_attendance_form_refuses_a_day_before_the_person_joined(self):
        self.reachable_today()
        self.client.force_login(self.everyone)
        before = self.counts()
        response = self.client.post(reverse('hr:production_attendancerecord_create'), {
            'employee': str(self.in_a.pk), 'clock_in': '2025-12-30T06:00', 'clock_out': '2025-12-30T14:00',
            'note': 'Forgot'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('joined on', ' '.join(response.context['form'].non_field_errors()))
        self.assertEqual(self.counts(), before)

    def test_the_leave_form_refuses_days_before_the_person_joined(self):
        self.reachable_today()
        before = self.counts()
        for actor in (self.ann, self.everyone):
            self.client.force_login(actor)
            response = self.client.post(reverse('hr:production_leaverequest_create'), {
                'employee': str(self.in_a.pk), 'leave_type': str(self.annual.pk), 'first_day': '2025-12-29',
                'last_day': '2026-01-02', 'reason': ''})
            self.assertEqual(response.status_code, 200, actor)
            self.assertIn('joined on', ' '.join(response.context['form'].non_field_errors()), actor)
        self.assertEqual(self.counts(), before)


class EmploymentChangesTests(EmploymentCase):
    """The rule holds when the records come first: approving a leave the last day now cuts, or moving a first or last day
    past records already written, is refused with the reason; the database refuses it too, whatever writes."""

    def setUp(self):
        super().setUp()
        Employee.objects.filter(pk=self.in_a.pk).update(left_on=None)
        self.in_a.refresh_from_db()

    def test_approving_a_pending_leave_past_a_last_day_set_since_is_refused(self):
        pending = LeaveRequest.objects.create(employee=self.in_a, leave_type=self.annual, first_day=date(2026, 3, 30),
                                              last_day=date(2026, 4, 3))
        Employee.objects.filter(pk=self.in_a.pk).update(left_on=LEFT)          # written under the request
        with self.assertRaises(ValidationError):
            services.decide_leave(self.everyone, pending, approve=True)
        pending.refresh_from_db()
        self.assertEqual(pending.status, 'pending')
        pending.delete()               # the database refuses the pair at the commit (Django reads it as the test ends)

    def test_a_last_day_before_approved_leave_or_a_punch_is_refused(self):
        LeaveRequest.objects.create(employee=self.in_a, leave_type=self.annual, first_day=date(2026, 4, 6),
                                    last_day=date(2026, 4, 8), status='approved', decided_at=at(date(2026, 3, 1), 9))
        before = self.counts()
        with self.assertRaises(ValidationError):
            services.leave_company(self.everyone, self.in_a, LEFT)
        self.in_a.refresh_from_db()
        self.assertIsNone(self.in_a.left_on)
        self.assertEqual(self.counts(), before)

    def test_the_person_form_refuses_a_first_day_after_records_already_written(self):
        AttendanceRecord.objects.create(employee=self.in_a, clock_in=at(date(2026, 1, 5), 6),
                                        clock_out=at(date(2026, 1, 5), 14), via='self')
        self.client.force_login(user('hradmin2', 'view_employee', 'change_employee', 'all_employee', group='HR2'))
        response = self.client.post(reverse('hr:production_employee_edit', args=[self.in_a.pk]), {
            'employee_number': self.in_a.employee_number, 'employment_type': self.in_a.employment_type,
            'user': str(self.ann.pk), 'joined_on': '2026-02-01', 'version': str(self.in_a.version)})
        self.assertEqual(response.status_code, 200)              # the form again, not saved
        self.assertIn('joined_on', response.context['form'].errors)
        self.in_a.refresh_from_db()
        self.assertEqual(self.in_a.joined_on, JOINED)

    def test_the_database_refuses_a_record_outside_the_employment_whatever_writes(self):
        from django.db import IntegrityError, connection, transaction

        def deferred_again():          # SET CONSTRAINTS lasts to the end of the transaction the test class shares
            with connection.cursor() as cursor:
                cursor.execute('SET CONSTRAINTS ALL DEFERRED')
        self.addCleanup(deferred_again)
        Employee.objects.filter(pk=self.in_a.pk).update(left_on=LEFT)
        for write in (
                lambda: ShiftAssignment.objects.create(employee=self.in_a, day=date(2026, 4, 2), shift=self.early),
                lambda: LeaveRequest.objects.create(employee=self.in_a, leave_type=self.annual,
                                                    first_day=date(2025, 12, 30), last_day=date(2026, 1, 2)),
                lambda: AttendanceRecord.objects.create(employee=self.in_a, clock_in=at(date(2026, 4, 9), 6),
                                                        via='self')):
            with self.subTest(write=write), self.assertRaises(IntegrityError), transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
                write()
        with self.assertRaises(IntegrityError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
            ShiftAssignment.objects.create(employee=self.in_a, day=date(2026, 3, 2), shift=self.early)
            Employee.objects.filter(pk=self.in_a.pk).update(left_on=date(2026, 2, 27))


class CheckedUnderTheLockTests(EmploymentCase):
    """The save checks the rule again with the person's row locked (a last day may be committed between the form's check
    and the save): a refusal there is put on the form and nothing is written."""

    def test_a_refusal_at_the_save_is_on_the_form_and_writes_nothing(self):
        Employee.objects.filter(pk=self.in_a.pk).update(left_on=None)
        self.client.force_login(self.everyone)
        before = self.counts()
        refused = ValidationError('Ann left on 31 Mar 2026.')
        with mock.patch.object(services, 'lock_employed', side_effect=refused):
            response = self.client.post(reverse('hr:production_leaverequest_create'), {
                'employee': str(self.in_a.pk), 'leave_type': str(self.annual.pk), 'first_day': '2026-03-02',
                'last_day': '2026-03-03', 'reason': ''})
        self.assertEqual(response.status_code, 200)
        self.assertIn('Ann left on 31 Mar 2026.', response.context['form'].non_field_errors())
        self.assertEqual(self.counts(), before)


class LockOrderTests(EmploymentCase):
    """HR takes its locks person first, then the person's records (plan_shifts, clock-in, leave_company already do): an
    approval and an edit of a leave lock the person before the leave, so they never wait on each other the other way
    round. The person is locked FOR NO KEY UPDATE: a record being added for them (which holds a key-share lock on the
    person) does not deadlock with it."""

    def locks(self, call):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as seen:
            call()
        return [query['sql'].split(' FROM ')[1].split()[0].strip('"') + (' no key' if 'NO KEY' in query['sql'] else '')
                for query in seen.captured_queries if 'FOR ' in query['sql'] and 'UPDATE' in query['sql']]

    def test_an_approval_locks_the_person_before_the_leave(self):
        Employee.objects.filter(pk=self.in_a.pk).update(left_on=None)
        pending = LeaveRequest.objects.create(employee=self.in_a, leave_type=self.annual, first_day=date(2026, 3, 2),
                                              last_day=date(2026, 3, 3))
        taken = self.locks(lambda: services.decide_leave(self.everyone, pending, approve=True))
        self.assertEqual(taken[:2], ['employees no key', 'leave_requests'])

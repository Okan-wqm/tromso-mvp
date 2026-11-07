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


class EmploymentBoundsTests(PeopleTestCase):
    def setUp(self):
        super().setUp()
        self.everyone = user('everyone', 'view_employee', 'view_shiftassignment', 'add_shiftassignment',
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
            response = self.client.post(reverse('hr:leaverequest_create'), {
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

"""Deciding leave in Production › Team: the approve dialog lists the person's planned shifts inside the request (to replace
them), never blocks the approval; the menu shows the decider how many requests wait for them."""
from datetime import date, time

from django.urls import reverse

from farm.models import ProductionDepartment

from .. import read
from ..models import Employee, LeaveRequest, LeaveType, Shift, ShiftAssignment
from .helpers import user
from .helpers_people import PeopleTestCase, employee, place

MONDAY, TUESDAY, WEDNESDAY, SUNDAY = date(2026, 3, 2), date(2026, 3, 3), date(2026, 3, 4), date(2026, 3, 1)
DECIDER = ('view_employee', 'view_leaverequest', 'add_leaverequest', 'change_leaverequest', 'view_attendancerecord')


def labels_with_badges(response):
    return {entry['label']: entry['badge'] for section in response.context['rail_sections']
            for group in section['groups'] for entry in group['entries']}


class ImpactTestCase(PeopleTestCase):
    def setUp(self):
        super().setUp()
        self.lead = user('boss', *DECIDER, group='Lead role')
        ProductionDepartment.objects.filter(pk=self.dept_a.pk).update(manager=self.lead)
        self.kind = LeaveType.objects.create(name='Annual leave', code='ANNUAL')
        self.early = Shift.objects.create(name='Early', code='EARLY', starts_at=time(6), ends_at=time(14))
        self.night = Shift.objects.create(name='Night', code='NIGHT', starts_at=time(22), ends_at=time(6))
        for day, which in ((SUNDAY, self.early), (MONDAY, self.early), (TUESDAY, self.night), (WEDNESDAY, None)):
            ShiftAssignment.objects.create(employee=self.in_a, day=day, shift=which)
        self.item = LeaveRequest.objects.create(employee=self.in_a, leave_type=self.kind, first_day=MONDAY,
                                                last_day=WEDNESDAY)


class LeaveImpactTests(ImpactTestCase):
    def test_the_planned_shifts_inside_the_request_and_none_outside(self):
        self.assertEqual(read.leave_impact(self.lead, self.item), [(MONDAY, self.early), (TUESDAY, self.night)])

    def test_the_approve_dialog_lists_them_and_the_approval_is_not_blocked(self):
        self.client.force_login(self.lead)
        url = reverse('hr:production_leaverequest_approve', args=[self.item.pk])
        dialog = self.client.get(url)
        self.assertEqual(dialog.status_code, 200)
        self.assertEqual(dialog.context['impact'], [(MONDAY, self.early), (TUESDAY, self.night)])
        self.assertContains(dialog, 'NIGHT')
        self.assertContains(dialog, '2 planned shifts of the person in these days')
        response = self.client.post(url, {'note': ''})
        self.assertRedirects(response, reverse('hr:production_leaverequest_list'), fetch_redirect_response=False)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, 'approved')

    def test_the_dialog_is_refused_to_who_may_not_decide(self):
        reader = user('reader', 'view_leaverequest', group='Reader role')
        ProductionDepartment.objects.filter(pk=self.dept_a.pk).update(manager=reader)
        self.client.force_login(reader)
        self.assertEqual(self.client.get(reverse('hr:production_leaverequest_approve', args=[self.item.pk])).status_code,
                         403)
        stranger = user('stranger', *DECIDER, group='Stranger role')
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(reverse('hr:production_leaverequest_approve', args=[self.item.pk])).status_code,
                         404)


class PendingBadgeTests(ImpactTestCase):
    def test_the_badge_counts_the_requests_the_viewer_may_decide(self):
        LeaveRequest.objects.create(employee=self.in_b, leave_type=self.kind, first_day=MONDAY, last_day=MONDAY)
        self.assertEqual(read.pending_leave_badge(self.lead).count, 1)
        own = Employee.objects.create(employee_number='E-70', joined_on=date(2026, 1, 1), user=self.lead)
        place(own, self.dept_b)
        LeaveRequest.objects.create(employee=own, leave_type=self.kind, first_day=MONDAY, last_day=MONDAY)
        self.assertEqual(read.pending_leave_badge(self.lead).count, 1)               # not their own
        self.item.status = 'cancelled'
        self.item.save()
        self.assertEqual(read.pending_leave_badge(self.lead).count, 0)

    def test_a_reader_who_may_not_decide_has_no_number(self):
        reader = user('reader', 'view_leaverequest', group='Reader role')
        ProductionDepartment.objects.filter(pk=self.dept_a.pk).update(manager=reader)
        self.assertEqual(read.pending_leave_badge(reader).count, 0)

    def test_the_badge_is_beside_production_leave_requests(self):
        self.client.force_login(self.lead)
        badges = labels_with_badges(self.client.get(reverse('hr:production_today')))
        self.assertEqual(badges['Leave requests'].text, '1')
        office_person = employee('E-71', 'Office')
        place(office_person, self.finance)
        self.assertEqual(read.pending_leave_badge(self.hr).count, 0)                   # hr has no Edit on leave

    def test_a_badge_without_an_address_is_not_polled(self):
        self.client.force_login(self.lead)
        html = self.client.get(reverse('hr:production_today')).content.decode()
        self.assertIn('<span class="rail-badge">1</span>', html)
        self.assertNotIn('data-poll=""', html)

"""The kind of a person's leave (sick, annual) is for the person, for who may decide their requests and for the holders of
Everyone: a reader without the right to decide sees the dates and the status, never the type, neither in the list nor on the
request's page nor by searching for it (a search for "sick" must not tell who is ill)."""
from datetime import date, datetime, timezone as utc

from django.urls import reverse

from farm.models import ProductionDepartment

from ..models import Employee, LeaveRequest, LeaveType
from .helpers import user
from .helpers_people import PeopleTestCase

MONDAY = date(2026, 3, 2)


class LeaveTypePrivacyTests(PeopleTestCase):
    def setUp(self):
        super().setUp()
        self.sick = LeaveType.objects.create(name='Sick leave', code='SICK', needs_approval=False)
        self.reader = user('reader', 'view_leaverequest', group='Leave reader role')
        ProductionDepartment.objects.filter(pk=self.dept_a.pk).update(manager=self.reader)
        self.decider = user('decider', 'view_leaverequest', 'change_leaverequest', group='Leave decider role')
        ProductionDepartment.objects.filter(pk=self.dept_b.pk).update(manager=self.decider)
        self.ann = user('ann', 'view_leaverequest', group='Staff role')
        Employee.objects.filter(pk=self.in_a.pk).update(user=self.ann, first_name='', last_name='')
        self.hr_leave = user('hrleave', 'view_leaverequest', 'all_employee', group='HR leave role')
        stamp = datetime(2026, 1, 1, tzinfo=utc.utc)
        self.ill_a = LeaveRequest.objects.create(employee=self.in_a, leave_type=self.sick, first_day=MONDAY,
                                                 last_day=MONDAY, status='approved', decided_at=stamp)
        self.ill_b = LeaveRequest.objects.create(employee=self.in_b, leave_type=self.sick, first_day=MONDAY,
                                                 last_day=MONDAY, status='approved', decided_at=stamp)

    def rows(self, actor, **query):
        self.client.force_login(actor)
        response = self.client.get(reverse('hr:production_leaverequest_list'), {'tab': 'all', **query})
        return response, {row['request']: row for row in response.context['objects']}

    def test_a_reader_who_may_not_decide_sees_the_request_but_not_its_type(self):
        response, rows = self.rows(self.reader)
        self.assertEqual(list(rows), [self.ill_a])
        self.assertFalse(rows[self.ill_a]['show_type'])
        self.assertNotContains(response, 'Sick leave')
        detail = self.client.get(reverse('hr:production_leaverequest_detail', args=[self.ill_a.pk]))
        self.assertEqual(detail.status_code, 200)
        self.assertNotContains(detail, 'Sick leave')

    def test_a_search_for_the_type_finds_nothing_for_that_reader(self):
        _response, rows = self.rows(self.reader, q='sick')
        self.assertEqual(rows, {})
        _response, rows = self.rows(self.reader, q='ann')
        self.assertEqual(list(rows), [self.ill_a])                      # the person is still found by name

    def test_the_person_a_decider_and_everyone_see_the_type(self):
        for actor, request in ((self.ann, self.ill_a), (self.decider, self.ill_b), (self.hr_leave, self.ill_a)):
            response, rows = self.rows(actor)
            self.assertTrue(rows[request]['show_type'], actor)
            self.assertContains(response, 'Sick leave')
            _response, found = self.rows(actor, q='sick')
            self.assertIn(request, found, actor)

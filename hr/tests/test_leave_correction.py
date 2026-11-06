"""An approved leave that has begun can still be corrected by someone who may decide it: shortened (the person came back
early: a new last day, from the first day to the day before the old last day) or cancelled (it was never taken). The
person cannot do either to their own started leave; a decider cannot touch their own. Each is logged; a refusal writes
nothing."""
from datetime import date

from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse

from core.models import AuditLog

from .. import services
from ..models import LeaveRequest
from .test_leave import LeaveTestCase, request_for

FIRST, LAST = date(2026, 1, 5), date(2026, 1, 16)        # begun long ago on the test's clock


class StartedLeaveCorrectionTests(LeaveTestCase):
    def setUp(self):
        super().setUp()
        self.started = request_for(self.in_a, FIRST, LAST, self.annual, status='approved')

    def state(self):
        self.started.refresh_from_db()
        return self.started.status, self.started.last_day, AuditLog.objects.count()

    def test_a_decider_shortens_a_started_leave_and_it_is_logged(self):
        logged = AuditLog.objects.count()
        services.shorten_leave(self.lead, self.started, date(2026, 1, 9))
        self.assertEqual(self.state(), ('approved', date(2026, 1, 9), logged + 1))

    def test_the_new_last_day_lies_inside_the_leave(self):
        before = self.state()
        for wrong in (date(2026, 1, 4), LAST, date(2026, 1, 20)):
            with self.subTest(day=wrong), self.assertRaises(ValidationError):
                services.shorten_leave(self.lead, self.started, wrong)
        self.assertEqual(self.state(), before)
        services.shorten_leave(self.lead, self.started, FIRST)                 # down to its first day
        self.assertEqual(self.state()[1], FIRST)

    def test_the_person_and_a_decider_on_their_own_cannot(self):
        before = self.state()
        with self.assertRaises(PermissionDenied):
            services.shorten_leave(self.ann_user, self.started, date(2026, 1, 9))
        with self.assertRaises(PermissionDenied):
            services.cancel_leave(self.ann_user, self.started)
        own = request_for(self.in_b, FIRST, LAST, self.annual, status='approved')
        from ..models import Employee
        Employee.objects.filter(pk=self.in_b.pk).update(user=self.hr_leave, first_name='', last_name='')
        own.refresh_from_db()
        with self.assertRaises(PermissionDenied):
            services.shorten_leave(self.hr_leave, own, date(2026, 1, 9))
        self.assertEqual(self.state(), before)

    def test_a_decider_cancels_a_started_leave_that_was_never_taken(self):
        services.cancel_leave(self.lead, self.started)
        self.assertEqual(self.state()[0], 'cancelled')

    def test_only_an_approved_leave_is_shortened(self):
        pending = request_for(self.in_a, date(2026, 2, 2), date(2026, 2, 6), self.annual)
        with self.assertRaises(PermissionDenied):
            services.shorten_leave(self.lead, pending, date(2026, 2, 3))

    def test_the_page_offers_it_to_a_decider_and_the_route_does_it(self):
        self.client.force_login(self.lead)
        url = reverse('hr:production_leaverequest_shorten', args=[self.started.pk])
        page = self.client.get(reverse('hr:production_leaverequest_detail', args=[self.started.pk])).content.decode()
        self.assertIn(f'action="{url}"', page)
        response = self.client.post(url, {'last_day': '2026-01-09'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.state()[1], date(2026, 1, 9))
        self.client.force_login(self.ann_user)
        page = self.client.get(reverse('hr:production_leaverequest_detail', args=[self.started.pk])).content.decode()
        self.assertNotIn(f'action="{url}"', page)
        self.assertEqual(self.client.post(url, {'last_day': '2026-01-08'}).status_code, 403)
        self.assertEqual(LeaveRequest.objects.get(pk=self.started.pk).last_day, date(2026, 1, 9))

"""An approved leave that has begun can still be corrected by someone who may decide it: shortened (the person came back
early: a new last day, from the first day to the day before the old last day) or cancelled (it was never taken). The
person cannot do either to their own started leave; a decider cannot touch their own. Each is logged; a refusal writes
nothing. A correction is made only within the platform's correction window after the leave's last day
(hr.services.correction_window_days): an older leave is refused with the reason."""
import re
from datetime import date, timedelta
from unittest import mock

from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse

from core.models import AuditLog

from .. import services
from ..models import LeaveRequest
from .test_leave import LeaveTestCase, request_for

FIRST, LAST = date(2026, 1, 5), date(2026, 1, 16)
TODAY = date(2026, 1, 12)                                 # the leave has begun and runs on


def on(day):
    """The site's clock on `day`, for the services and the page alike."""
    return mock.patch.multiple('hr.services', site_today=mock.Mock(return_value=day))


class StartedLeaveCorrectionTests(LeaveTestCase):
    def setUp(self):
        super().setUp()
        self.started = request_for(self.in_a, FIRST, LAST, self.annual, status='approved')
        clock = on(TODAY)
        clock.start()
        self.addCleanup(clock.stop)
        page_clock = mock.patch('hr.resources.leave.site_today', return_value=TODAY)
        page_clock.start()
        self.addCleanup(page_clock.stop)

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
        # the shared day box (core.widgets.DayInput), never a browser date box, offering the latest day it takes: the
        # day before the last
        box = re.search(r'<input[^>]*name="last_day"[^>]*>', page).group(0)
        self.assertIn('data-date-input="day"', box)
        self.assertNotIn('type="date"', box)
        self.assertIn('value="15.01.2026"', box)
        response = self.client.post(url, {'last_day': 'nonsense'})          # not a day: said, nothing changed
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.state()[1], LAST)
        response = self.client.post(url, {'last_day': '09.01.2026'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.state()[1], date(2026, 1, 9))
        self.client.force_login(self.ann_user)
        page = self.client.get(reverse('hr:production_leaverequest_detail', args=[self.started.pk])).content.decode()
        self.assertNotIn(f'action="{url}"', page)
        self.assertEqual(self.client.post(url, {'last_day': '2026-01-08'}).status_code, 403)
        self.assertEqual(LeaveRequest.objects.get(pk=self.started.pk).last_day, date(2026, 1, 9))


class CorrectionWindowTests(LeaveTestCase):
    """A leave whose last day lies more than the window behind today is history: no one corrects it any more."""

    def setUp(self):
        super().setUp()
        self.leave = request_for(self.in_a, FIRST, LAST, self.annual, status='approved')

    def test_the_window_is_the_platform_setting_and_31_days_until_it_exists(self):
        self.assertEqual(services.correction_window_days(), 31)

    def test_inside_the_window_a_decider_corrects(self):
        other = request_for(self.in_a, date(2026, 1, 19), LAST + timedelta(days=3), self.annual, status='approved')
        with on(LAST + timedelta(days=31)):
            services.shorten_leave(self.lead, self.leave, date(2026, 1, 9))      # its new last day is now the one counted
            services.cancel_leave(self.lead, other)
        self.leave.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual((self.leave.last_day, other.status), (date(2026, 1, 9), 'cancelled'))

    def test_past_the_window_both_are_refused_with_the_reason_and_nothing_changes(self):
        before = (AuditLog.objects.count(), LeaveRequest.objects.get(pk=self.leave.pk).last_day)
        with on(LAST + timedelta(days=32)):
            for correct in (lambda: services.shorten_leave(self.lead, self.leave, date(2026, 1, 9)),
                            lambda: services.cancel_leave(self.lead, self.leave)):
                with self.assertRaises(ValidationError) as refused:
                    correct()
                self.assertIn('31 days', ' '.join(refused.exception.messages))
            self.assertFalse(services.can_correct(self.lead, self.leave))
        self.assertEqual((AuditLog.objects.count(), LeaveRequest.objects.get(pk=self.leave.pk).last_day), before)

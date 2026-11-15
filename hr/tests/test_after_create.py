"""A person who may create and not edit lands on a page they may open (flow fault M-18): a worker who filed a leave
request was sent to the request's edit page and met "403 Forbidden", though the request was stored. After a create the
tab opens the new record for editing only for a person who may edit it; else its own page (when the tab has one), else
the list (core.crud.CreateView.created)."""
from django.urls import reverse

from ..models import LeaveRequest
from .test_leave import MONDAY, TUESDAY, LeaveTestCase


class AfterCreateTests(LeaveTestCase):
    def test_a_worker_who_files_a_leave_request_lands_on_the_request_not_on_a_refusal(self):
        self.assertFalse(self.ann_user.has_perm('hr.change_leaverequest'))
        response = self.file(self.ann_user, self.in_a, MONDAY, TUESDAY)
        request = LeaveRequest.objects.get()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('hr:production_leaverequest_detail', args=[request.pk]))
        self.assertEqual(self.client.get(response['Location']).status_code, 200)

    def test_the_same_form_sent_again_lands_there_too(self):
        self.client.force_login(self.ann_user)
        form = self.client.get(reverse('hr:production_leaverequest_create')).context['form']
        data = {'employee': str(self.in_a.pk), 'leave_type': str(self.annual.pk), 'first_day': MONDAY.isoformat(),
                'last_day': MONDAY.isoformat(), 'reason': '', 'entry_key': str(form['entry_key'].value())}
        first = self.client.post(reverse('hr:production_leaverequest_create'), data)
        again = self.client.post(reverse('hr:production_leaverequest_create'), data)
        self.assertEqual(LeaveRequest.objects.count(), 1)
        self.assertEqual(again['Location'], first['Location'])
        self.assertEqual(self.client.get(again['Location']).status_code, 200)

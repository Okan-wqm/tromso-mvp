from datetime import date, datetime, timezone as utc
from decimal import Decimal
from unittest import mock

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connection, transaction
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from core.models import AuditLog
from core.testing import FrozenClock
from farm.models import ProductionDepartment, Site

from .. import leave, read, services
from ..models import Employee, Holiday, LeaveRequest, LeaveType, SchedulingSettings, Shift, ShiftAssignment
from .helpers import PRIVATE, fields_of, user
from .helpers_people import PeopleTestCase, TOP, employee, place

FRIDAY, MONDAY, TUESDAY = date(2026, 3, 6), date(2026, 3, 9), date(2026, 3, 10)
STAFF_PERMS = ('view_employee', 'view_leaverequest', 'add_leaverequest')
LEAD_LEAVE_PERMS = ('view_employee', 'view_leaverequest', 'add_leaverequest', 'change_leaverequest')


def request_for(person, first, last, kind, status='pending', **fields):
    if status in ('approved', 'rejected'):
        fields.setdefault('decided_at', datetime(2026, 1, 1, tzinfo=utc.utc))
    return LeaveRequest.objects.create(employee=person, leave_type=kind, first_day=first, last_day=last, status=status,
                                       **fields)


# The requests are dated on fixed days (March 2026, one in June 2027 as "not begun yet"), and a request can be cancelled
# only before its first day: the clock is held (README, Tests), or the June 2027 one has begun from 01.06.2027 on
# (found with TEST_CLOCK=2027-12-31T23:30:00+00:00). The moment is the day these tests last ran on the real clock.
class LeaveTestCase(FrozenClock, PeopleTestCase):
    NOW = datetime(2026, 11, 11, 12, 0, tzinfo=utc.utc)

    def setUp(self):
        super().setUp()
        self.annual = LeaveType.objects.create(name='Annual leave', code='ANNUAL')
        self.sick = LeaveType.objects.create(name='Sick leave', code='SICK', needs_approval=False)
        self.limited = LeaveType.objects.create(name='Welfare', code='WELF', annual_days=Decimal('3'))
        # Ann (in A) has an account; Bob (in B) too; the leads manage A and B
        self.ann_user = user('ann', *STAFF_PERMS, group='Staff role')
        Employee.objects.filter(pk=self.in_a.pk).update(user=self.ann_user, first_name='', last_name='')
        self.in_a.refresh_from_db()
        self.lead = user('boss', *LEAD_LEAVE_PERMS, group='Lead role')
        ProductionDepartment.objects.filter(pk=self.dept_a.pk).update(manager=self.lead)
        self.hr_leave = user('hrleave', 'view_employee', 'view_leaverequest', 'add_leaverequest', 'change_leaverequest',
                             'all_employee', group='HR leave role')

    def file(self, actor, person, first, last, kind=None, **extra):
        self.client.force_login(actor)
        return self.client.post(reverse('hr:production_leaverequest_create'), {
            'employee': str(person.pk), 'leave_type': str((kind or self.annual).pk), 'first_day': first.isoformat(),
            'last_day': last.isoformat(), 'reason': '', **extra})


class LeaveTypeTests(LeaveTestCase):
    def test_create_read_edit_delete_every_column(self):
        admin = user('typeadmin', 'view_leavetype', 'add_leavetype', 'change_leavetype', 'delete_leavetype',
                     group='Type role')
        self.client.force_login(admin)
        self.client.post(reverse('hr:leavetype_create'), {'name': 'Parental', 'code': 'par', 'annual_days': '12.5',
                                                          'needs_approval': 'on', 'status': 'active'})
        kind = LeaveType.objects.get(code='PAR')
        self.assertEqual({name: getattr(kind, name) for name in fields_of(LeaveType)},
                         {'name': 'Parental', 'code': 'PAR', 'annual_days': Decimal('12.50'), 'needs_approval': True,
                          'status': 'active'})
        self.assertIn(kind, self.client.get(reverse('hr:leavetype_list')).context['objects'])
        self.client.post(reverse('hr:leavetype_edit', args=[kind.pk]), {
            'name': 'Parental', 'code': 'PAR', 'annual_days': '', 'status': 'inactive', 'version': '1'})
        kind.refresh_from_db()
        self.assertEqual((kind.annual_days, kind.needs_approval, kind.status, kind.version), (None, False, 'inactive', 2))
        self.client.post(reverse('hr:leavetype_delete', args=[kind.pk]))
        self.assertTrue(LeaveType.all_objects.get(pk=kind.pk).is_deleted)

    def test_the_database_constraints(self):
        for fields in ({'code': 'ANNUAL'}, {'code': 'bad code'}, {'code': 'NEG', 'annual_days': Decimal('-1')},
                       {'code': 'ST', 'status': 'gone'}):
            with self.assertRaises(IntegrityError, msg=fields), transaction.atomic():
                LeaveType.objects.bulk_create([LeaveType(name='X', **fields)])
        self.annual.soft_delete(self.hr)
        LeaveType.objects.create(name='Again', code='ANNUAL')

    def test_a_type_with_requests_is_not_deleted(self):
        request_for(self.in_a, MONDAY, MONDAY, self.annual)
        from core.softdelete import plan_delete
        self.assertFalse(plan_delete(self.annual).can_delete)


class LeaveDaysTests(LeaveTestCase):
    def test_a_request_is_charged_for_working_weekdays_without_holidays(self):
        site = self.site
        self.assertEqual(leave.leave_days(FRIDAY, date(2026, 3, 13), site), Decimal(6))         # Fri, Mon-Fri
        Holiday.objects.create(day=TUESDAY, name='Every site')
        Holiday.objects.create(day=date(2026, 3, 11), name='Here', site=site)
        Holiday.objects.create(day=date(2026, 3, 12), name='Elsewhere', site=Site.objects.create(name='X', code='XX'))
        self.assertEqual(leave.leave_days(FRIDAY, date(2026, 3, 13), site), Decimal(4))
        self.assertEqual(leave.leave_days(FRIDAY, date(2026, 3, 13), None), Decimal(5))         # no site: company days only

    def test_the_working_weekdays_are_a_setting(self):
        SchedulingSettings.get()
        SchedulingSettings.objects.update(working_weekdays=[0, 1, 2, 3, 4, 5])                  # Mon-Sat
        self.assertEqual(leave.leave_days(FRIDAY, date(2026, 3, 9), self.site), Decimal(3))      # Fri, Sat, Mon

    def test_a_request_over_new_year_is_split_by_year(self):
        self.assertEqual(leave.charged_by_year(date(2026, 12, 30), date(2027, 1, 5), None),
                         {2026: Decimal(2), 2027: Decimal(3)})

    def test_a_balance_counts_pending_and_approved_requests_of_the_year(self):
        request_for(self.in_a, MONDAY, TUESDAY, self.limited)                                   # pending, 2 days
        request_for(self.in_a, date(2026, 4, 6), date(2026, 4, 6), self.limited, status='rejected')
        request_for(self.in_a, date(2026, 4, 7), date(2026, 4, 7), self.limited, status='cancelled')
        self.assertEqual(leave.used(self.in_a, self.limited, 2026), Decimal(2))
        self.assertEqual(leave.balance(self.in_a, self.limited, 2026), Decimal(1))
        self.assertIsNone(leave.balance(self.in_a, self.annual, 2026))                          # no limit
        self.assertEqual(leave.balance(self.in_a, self.limited, 2027), Decimal(3))

    def test_away_on_says_away_or_not_and_nothing_more(self):
        request_for(self.in_a, MONDAY, TUESDAY, self.sick, status='approved')
        request_for(self.in_b, MONDAY, MONDAY, self.annual, status='pending')
        bob = user('bob')
        Employee.objects.filter(pk=self.in_b.pk).update(user=bob, first_name='', last_name='')
        self.assertEqual(leave.away_on(MONDAY, [self.ann_user.pk, bob.pk]), {self.ann_user.pk})
        self.assertEqual(leave.away_on(date(2026, 3, 11), [self.ann_user.pk]), set())


class LeaveRequestModelTests(LeaveTestCase):
    def refused(self, **fields):
        values = {'employee': self.in_a, 'leave_type': self.annual, 'first_day': MONDAY, 'last_day': MONDAY, **fields}
        with self.assertRaises(IntegrityError), transaction.atomic():
            LeaveRequest.objects.bulk_create([LeaveRequest(**values)])

    def test_the_days_are_ordered_and_the_status_is_known(self):
        self.refused(first_day=TUESDAY, last_day=MONDAY)
        self.refused(status='gone')

    def test_a_decision_has_its_time(self):
        self.refused(status='approved')
        self.refused(status='rejected')
        request_for(self.in_a, MONDAY, MONDAY, self.annual, status='approved')                  # decided_at set by the helper

    def test_a_person_has_one_pending_or_approved_request_for_a_day_but_adjacent_days_are_fine(self):
        request_for(self.in_a, MONDAY, TUESDAY, self.annual)
        self.refused(first_day=TUESDAY, last_day=date(2026, 3, 11))                             # overlaps on the 10th
        self.refused(first_day=date(2026, 3, 1), last_day=MONDAY, leave_type=self.sick)
        request_for(self.in_a, date(2026, 3, 11), date(2026, 3, 12), self.annual)               # the next day: allowed
        request_for(self.in_a, date(2026, 3, 8), date(2026, 3, 8), self.annual)                 # the day before
        request_for(self.in_b, MONDAY, TUESDAY, self.annual)                                    # another person

    def test_rejected_and_cancelled_requests_and_deleted_ones_do_not_hold_the_days(self):
        for status in ('rejected', 'cancelled'):
            request_for(self.in_a, MONDAY, TUESDAY, self.annual, status=status)
        held = request_for(self.in_a, MONDAY, TUESDAY, self.annual)
        held.soft_delete(self.hr)
        request_for(self.in_a, MONDAY, TUESDAY, self.annual)

    def test_nobody_decides_their_own_leave_whatever_writes(self):
        request = request_for(self.in_a, MONDAY, MONDAY, self.annual)
        with connection.cursor() as cursor, self.assertRaises(IntegrityError), transaction.atomic():
            cursor.execute('UPDATE leave_requests SET decided_by_id = %s, status = %s, decided_at = now() WHERE id = %s',
                           [self.ann_user.pk, 'approved', request.pk])
        with self.assertRaises(IntegrityError), transaction.atomic():
            request_for(self.in_a, date(2026, 3, 16), date(2026, 3, 16), self.annual, status='approved',
                        decided_by=self.ann_user)
        request_for(self.in_a, date(2026, 3, 17), date(2026, 3, 17), self.annual, status='approved',
                    decided_by=self.lead)                                                        # someone else: fine
        request.refresh_from_db()
        self.assertEqual(request.status, 'pending')

    def test_every_column_is_covered(self):
        self.assertEqual(fields_of(LeaveRequest), {'employee', 'leave_type', 'first_day', 'last_day', 'status', 'reason',
                                                   'decision_note', 'decided_by', 'decided_at'})


class FilingTests(LeaveTestCase):
    def test_a_person_files_for_themselves_pending_and_the_reason_is_theirs(self):
        self.file(self.ann_user, self.in_a, MONDAY, TUESDAY, reason='Family matter')
        request = LeaveRequest.objects.get()
        self.assertEqual({name: getattr(request, name) for name in fields_of(LeaveRequest)},
                         {'employee': self.in_a, 'leave_type': self.annual, 'first_day': MONDAY, 'last_day': TUESDAY,
                          'status': 'pending', 'reason': 'Family matter', 'decision_note': '', 'decided_by': None,
                          'decided_at': None})
        self.assertEqual(request.created_by, self.ann_user)
        # the form opens for them with themselves chosen
        form = self.client.get(reverse('hr:production_leaverequest_create')).context['form']
        self.assertEqual(form.initial['employee'], self.in_a.pk)

    def test_a_type_that_needs_no_approval_is_granted_at_once_with_no_decider(self):
        self.file(self.ann_user, self.in_a, MONDAY, MONDAY, kind=self.sick)
        request = LeaveRequest.objects.get()
        self.assertEqual((request.status, request.decided_by), ('approved', None))
        self.assertIsNotNone(request.decided_at)

    def test_the_same_form_sent_twice_files_once(self):
        self.client.force_login(self.ann_user)
        form = self.client.get(reverse('hr:production_leaverequest_create')).context['form']
        key = form['entry_key'].value()
        data = {'employee': str(self.in_a.pk), 'leave_type': str(self.annual.pk), 'first_day': '2026-03-09',
                'last_day': '2026-03-09', 'reason': '', 'entry_key': str(key)}
        self.client.post(reverse('hr:production_leaverequest_create'), data)
        self.client.post(reverse('hr:production_leaverequest_create'), data)
        self.assertEqual(LeaveRequest.objects.count(), 1)

    def test_the_form_refuses_what_cannot_be_charged_or_clashes_or_goes_over_the_allowance(self):
        errors = self.file(self.ann_user, self.in_a, TUESDAY, MONDAY).context['form'].errors
        self.assertIn('last_day', errors)
        errors = self.file(self.ann_user, self.in_a, date(2026, 3, 14), date(2026, 3, 15)).context['form'].errors   # a weekend
        self.assertIn('last_day', errors)
        self.file(self.ann_user, self.in_a, MONDAY, TUESDAY)
        errors = self.file(self.ann_user, self.in_a, TUESDAY, date(2026, 3, 11)).context['form'].errors
        self.assertIn('last_day', errors)                                                         # the exclusion constraint
        errors = self.file(self.ann_user, self.in_a, date(2026, 4, 6), date(2026, 4, 9), kind=self.limited).context['form'].errors
        self.assertEqual(list(errors), ['leave_type'])                                          # 4 days of 3
        self.assertEqual(LeaveRequest.objects.count(), 1)

    def test_a_lead_files_for_their_team_and_the_reason_is_not_theirs_to_enter(self):
        self.file(self.lead, self.in_a, MONDAY, MONDAY, reason='Typed by the lead')
        request = LeaveRequest.objects.get()
        self.assertEqual((request.employee, request.reason, request.created_by), (self.in_a, '', self.lead))

    def test_a_person_cannot_file_for_someone_outside_their_team(self):
        before = LeaveRequest.objects.count()
        response = self.file(self.ann_user, self.in_b, MONDAY, MONDAY)
        self.assertIn('employee', response.context['form'].errors)
        response = self.file(self.lead, self.in_b, MONDAY, MONDAY)
        self.assertIn('employee', response.context['form'].errors)
        self.assertEqual(LeaveRequest.objects.count(), before)

    def test_a_pending_request_can_be_changed_by_a_lead_with_edit_and_a_decided_one_cannot(self):
        self.file(self.ann_user, self.in_a, MONDAY, MONDAY, reason='First')
        request = LeaveRequest.objects.get()
        self.client.force_login(self.ann_user)                           # Read and Create: no Edit, no change
        self.assertEqual(self.client.get(reverse('hr:production_leaverequest_edit', args=[request.pk])).status_code, 403)
        self.client.force_login(self.lead)
        self.client.post(reverse('hr:production_leaverequest_edit', args=[request.pk]), {
            'leave_type': str(self.annual.pk), 'first_day': '2026-03-10', 'last_day': '2026-03-11', 'version': '1'})
        request.refresh_from_db()
        self.assertEqual((request.first_day, request.last_day, request.reason, request.version),
                         (TUESDAY, date(2026, 3, 11), 'First', 2))        # the reason is not the lead's to see or change
        LeaveRequest.objects.filter(pk=request.pk).update(status='approved', decided_at=datetime(2026, 1, 1, tzinfo=utc.utc),
                                                          decided_by=self.hr_leave, version=3)
        response = self.client.post(reverse('hr:production_leaverequest_edit', args=[request.pk]), {
            'leave_type': str(self.annual.pk), 'first_day': '2026-03-12', 'last_day': '2026-03-12', 'version': '3'})
        self.assertTrue(response.context['form'].non_field_errors())
        request.refresh_from_db()
        self.assertEqual(request.first_day, TUESDAY)


class DecisionTests(LeaveTestCase):
    def state(self):
        return (list(LeaveRequest.all_objects.order_by('pk').values_list('pk', 'status', 'decided_by', 'version',
                                                                         'decision_note')), AuditLog.objects.count())

    def test_the_lead_of_the_team_approves_and_rejects_with_the_decider_the_time_and_a_logged_row(self):
        first = request_for(self.in_a, MONDAY, MONDAY, self.annual)
        second = request_for(self.in_a, TUESDAY, TUESDAY, self.annual)
        services.decide_leave(self.lead, first, True)
        services.decide_leave(self.lead, second, False, ' Short staffed ')
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual((first.status, first.decided_by, first.version), ('approved', self.lead, 2))
        self.assertIsNotNone(first.decided_at)
        self.assertEqual((second.status, second.decision_note), ('rejected', 'Short staffed'))
        log = AuditLog.objects.get(entity_id=str(second.pk))
        self.assertEqual(log.changes['Status'], [{'msgid': 'Pending'}, {'msgid': 'Rejected'}])
        self.assertEqual(log.changes['Decision note'], [None, PRIVATE])
        self.assertNotIn('Short staffed', str(log.changes))

    def test_every_refusal_changes_nothing_and_logs_nothing(self):
        mine = request_for(self.in_a, MONDAY, MONDAY, self.annual)
        other_team = request_for(self.in_b, MONDAY, MONDAY, self.annual)
        done = request_for(self.in_a, TUESDAY, TUESDAY, self.annual, status='approved', decided_by=self.hr_leave)
        before = self.state()
        for actor, target in (
                (self.ann_user, mine),                                 # their own, and no Edit
                (self.lead, other_team),                               # not their team
                (self.lead, done),                                     # already decided
                (user('plain', 'view_leaverequest', group='Plain role'), mine),   # no verb
        ):
            with self.assertRaises(PermissionDenied):
                services.decide_leave(actor, target, True)
        self.assertEqual(self.state(), before)

    def test_nobody_decides_their_own_leave_even_with_every_verb(self):
        own = user('selfish', *LEAD_LEAVE_PERMS, 'all_employee', group='Selfish role')
        Employee.objects.filter(pk=self.in_b.pk).update(user=own, first_name='', last_name='')
        request = request_for(self.in_b, MONDAY, MONDAY, self.annual)
        before = self.state()
        with self.assertRaises(PermissionDenied):
            services.decide_leave(own, request, True)
        self.assertEqual(self.state(), before)
        services.decide_leave(self.hr_leave, request, True)                 # someone who holds Everyone may

    def test_a_leads_own_request_goes_to_someone_who_reaches_the_lead(self):
        lead_person = Employee.objects.create(employee_number='E-70', user=self.lead, joined_on=TOP)
        place(lead_person, self.dept_a)
        request = request_for(lead_person, MONDAY, MONDAY, self.annual)
        with self.assertRaises(PermissionDenied):
            services.decide_leave(self.lead, request, True)
        services.decide_leave(self.hr_leave, request, True)

    def test_the_decision_routes_post_and_the_list_buttons(self):
        request = request_for(self.in_a, MONDAY, MONDAY, self.annual)
        self.client.force_login(self.lead)
        listed = self.client.get(reverse('hr:production_leaverequest_list')).context['objects']
        self.assertEqual([(row['request'], row['can_decide'], row['can_cancel']) for row in listed], [(request, True, True)])
        self.assertEqual(self.client.get(reverse('hr:production_leaverequest_reject', args=[request.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('hr:production_leaverequest_approve', args=[request.pk])).status_code, 200)   # the dialog
        self.client.post(reverse('hr:production_leaverequest_reject', args=[request.pk]), {'note': 'No'})
        request.refresh_from_db()
        self.assertEqual((request.status, request.decision_note), ('rejected', 'No'))
        again = self.client.post(reverse('hr:production_leaverequest_approve', args=[request.pk]), follow=True)
        self.assertEqual(again.status_code, 403)                            # decided: no longer anyone's to decide


class CancelTests(LeaveTestCase):
    def test_a_pending_request_can_be_cancelled_by_the_person_or_a_decider_and_frees_the_days(self):
        request = request_for(self.in_a, MONDAY, TUESDAY, self.annual)
        services.cancel_leave(self.ann_user, request)
        request.refresh_from_db()
        self.assertEqual(request.status, 'cancelled')
        request_for(self.in_a, MONDAY, TUESDAY, self.annual)                # the days are free again
        other = request_for(self.in_a, date(2026, 3, 16), date(2026, 3, 16), self.annual)
        services.cancel_leave(self.lead, other)

    def test_an_approved_request_can_be_cancelled_only_before_its_first_day_on_the_sites_clock(self):
        future = request_for(self.in_a, date(2027, 6, 1), date(2027, 6, 1), self.annual, status='approved')
        started = request_for(self.in_a, date(2026, 1, 5), date(2026, 1, 9), self.annual, status='approved')
        services.cancel_leave(self.ann_user, future)
        before = (LeaveRequest.objects.filter(status='approved').count(), AuditLog.objects.count())
        with self.assertRaises(PermissionDenied):
            services.cancel_leave(self.ann_user, started)
        self.assertEqual((LeaveRequest.objects.filter(status='approved').count(), AuditLog.objects.count()), before)

    def test_the_first_day_is_read_on_the_sites_clock(self):
        Site.objects.filter(pk=self.site.pk).update(timezone='Pacific/Auckland')           # a day ahead of UTC
        request = request_for(self.in_a, date(2026, 6, 2), date(2026, 6, 2), self.annual, status='approved')
        with mock.patch('django.utils.timezone.now', return_value=datetime(2026, 6, 1, 14, 0, tzinfo=utc.utc)):
            with self.assertRaises(PermissionDenied):                     # 02:00 on the 2nd in Auckland: it has begun
                services.cancel_leave(self.ann_user, request)
        with mock.patch('django.utils.timezone.now', return_value=datetime(2026, 6, 1, 9, 0, tzinfo=utc.utc)):
            services.cancel_leave(self.ann_user, request)                 # 21:00 on the 1st in Auckland

    def test_decided_requests_and_strangers_cannot_cancel(self):
        rejected = request_for(self.in_a, MONDAY, MONDAY, self.annual, status='rejected')
        mine = request_for(self.in_b, MONDAY, MONDAY, self.annual)
        for actor, target in ((self.ann_user, rejected), (self.ann_user, mine), (self.lead, mine)):
            with self.assertRaises(PermissionDenied):
                services.cancel_leave(actor, target)


class PrivacyAndScopeTests(LeaveTestCase):
    def setUp(self):
        super().setUp()
        self.request = request_for(self.in_a, MONDAY, MONDAY, self.sick, reason='A diagnosis')

    def page(self, actor, name='hr:production_leaverequest_list', *args):
        self.client.force_login(actor)
        return self.client.get(reverse(name, args=args))

    def test_the_lead_sees_the_type_and_never_the_reason_the_person_and_everyone_see_it(self):
        lead = self.page(self.lead)
        self.assertContains(lead, 'Sick leave')
        self.assertNotContains(lead, 'A diagnosis')
        self.assertNotContains(self.page(self.lead, 'hr:production_leaverequest_detail', self.request.pk), 'A diagnosis')
        self.assertContains(self.page(self.ann_user), 'A diagnosis')
        self.assertContains(self.page(self.ann_user, 'hr:production_leaverequest_detail', self.request.pk), 'A diagnosis')
        self.assertContains(self.page(self.hr_leave), 'A diagnosis')

    def test_the_lead_cannot_read_the_reason_through_the_edit_form_either(self):
        self.client.force_login(self.lead)
        form = self.client.get(reverse('hr:production_leaverequest_edit', args=[self.request.pk])).context['form']
        self.assertNotIn('reason', form.fields)
        self.client.post(reverse('hr:production_leaverequest_edit', args=[self.request.pk]), {
            'leave_type': str(self.annual.pk), 'first_day': '2026-03-09', 'last_day': '2026-03-09', 'reason': 'overwritten',
            'version': '1'})
        self.request.refresh_from_db()
        self.assertEqual(self.request.reason, 'A diagnosis')

    def test_the_reason_is_never_in_the_log_or_the_viewer(self):
        self.client.force_login(self.ann_user)
        self.file(self.ann_user, self.in_a, TUESDAY, TUESDAY, reason='Secret words')
        self.assertNotIn('Secret words', str(list(AuditLog.objects.values_list('changes', flat=True))))
        entry = AuditLog.objects.filter(entity_type='leave request').latest('created_at')
        self.assertEqual(entry.changes['Reason'], [None, PRIVATE])
        from config.database import VIEWER
        self.assertEqual(set(VIEWER.masked['leave_requests']), {'reason', 'decision_note'})

    def test_another_teams_requests_are_a_404_on_every_verb_and_never_listed(self):
        other = request_for(self.in_b, MONDAY, MONDAY, self.annual)
        self.client.force_login(self.lead)
        before = self.state_of(other)
        self.assertEqual(list(r['request'] for r in self.client.get(reverse('hr:production_leaverequest_list'), {'tab': 'all'}
                                                                    ).context['objects']), [self.request])
        for query in ({'q': 'Bravo'}, {'tab': 'all', 'q': 'Annual'}):
            self.assertNotIn(other, [r['request'] for r in self.client.get(reverse('hr:production_leaverequest_list'), query
                                                                           ).context['objects']])
        for method, name in (('get', 'hr:production_leaverequest_detail'), ('get', 'hr:production_leaverequest_edit'),
                             ('post', 'hr:production_leaverequest_edit'), ('post', 'hr:production_leaverequest_approve'),
                             ('get', 'hr:production_leaverequest_reject'), ('post', 'hr:production_leaverequest_reject'),
                             ('post', 'hr:production_leaverequest_cancel')):
            response = getattr(self.client, method)(reverse(name, args=[other.pk]), {'version': '1', 'note': 'x'})
            self.assertEqual(response.status_code, 404, (method, name))
        self.assertEqual(self.state_of(other), before)

    def state_of(self, request):
        request = LeaveRequest.all_objects.get(pk=request.pk)
        return (request.status, request.version, request.decided_by_id, AuditLog.objects.count())

    def test_a_reader_cannot_decide_through_the_urls_and_a_stranger_reaches_nothing(self):
        self.client.force_login(self.ann_user)                      # Read and Create only
        for name in ('hr:production_leaverequest_approve', 'hr:production_leaverequest_reject'):
            self.assertEqual(self.client.post(reverse(name, args=[self.request.pk])).status_code, 403, name)
        stranger = user('stranger')
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(reverse('hr:production_leaverequest_list')).status_code, 403)
        self.assertEqual(self.client.post(reverse('hr:production_leaverequest_cancel', args=[self.request.pk])).status_code, 403)

    def test_the_tabs_and_counts(self):
        request_for(self.in_a, TUESDAY, TUESDAY, self.annual, status='approved')
        request_for(self.in_a, date(2026, 3, 11), date(2026, 3, 11), self.annual, status='rejected')
        self.client.force_login(self.lead)
        counts = self.client.get(reverse('hr:production_leaverequest_list')).context['counts']
        self.assertEqual(counts, {'pending': 1, 'approved': 1, 'rejected': 1})
        for tab, expected in (('pending', 1), ('approved', 1), ('rejected', 1), ('all', 3), ('nonsense', 1)):
            rows = self.client.get(reverse('hr:production_leaverequest_list'), {'tab': tab}).context['objects']
            self.assertEqual(len(rows), expected, tab)

    def test_the_list_runs_the_same_queries_for_few_and_many_requests(self):
        self.client.force_login(self.lead)
        self.client.get(reverse('hr:production_leaverequest_list'))                                      # warm the permission cache
        def count(people):
            for n in range(people):
                person = employee(f'E-{4000 + n + people}', f'Many{n}')
                place(person, self.dept_a)
                request_for(person, MONDAY, TUESDAY, self.annual)
            with CaptureQueriesContext(connection) as queries:
                self.client.get(reverse('hr:production_leaverequest_list'))
            return len(queries)
        self.assertEqual(count(3), count(30))


class RosterMeetsLeaveTests(LeaveTestCase):
    def setUp(self):
        super().setUp()
        self.early = Shift.objects.create(name='Early', code='EARLY', starts_at=datetime(2026, 1, 1, 6).time(),
                                          ends_at=datetime(2026, 1, 1, 14).time())
        self.planner = user('planner', 'view_employee', 'view_shiftassignment', 'add_shiftassignment',
                            group='Planner role')
        ProductionDepartment.objects.filter(pk=self.dept_a.pk).update(manager=self.planner)

    def test_approved_leave_blocks_planning_a_shift_on_that_day_and_pending_does_not(self):
        request_for(self.in_a, MONDAY, TUESDAY, self.annual, status='approved')
        before = ShiftAssignment.objects.count()
        with self.assertRaises(ValidationError):
            services.plan_shifts(self.planner, [(self.in_a, MONDAY)], self.early)
        self.assertEqual(ShiftAssignment.objects.count(), before)
        request_for(self.in_a, date(2026, 3, 11), date(2026, 3, 11), self.annual)               # pending
        services.plan_shifts(self.planner, [(self.in_a, date(2026, 3, 11))], self.early)
        self.assertEqual(ShiftAssignment.objects.count(), 1)

    def test_the_week_shows_leave_over_the_plan_and_flags_a_shift_on_leave(self):
        ShiftAssignment.objects.create(employee=self.in_a, day=MONDAY, shift=self.early)
        request_for(self.in_a, MONDAY, MONDAY, self.annual, status='approved')
        request_for(self.in_a, TUESDAY, TUESDAY, self.annual, status='pending')
        row = read.week(self.planner, MONDAY).rows[0]
        self.assertEqual([c.on_leave for c in row.cells[:3]], [True, False, False])          # pending is not leave
        self.assertEqual([item.code for item in row.cells[0].findings], ['leave_overlap'])
        self.assertTrue(row.cells[0].blocks)


class LeavingTheCompanyTests(LeaveTestCase):
    def test_a_last_day_cancels_later_pending_requests_and_removes_later_plans(self):
        later = request_for(self.in_a, date(2026, 6, 1), date(2026, 6, 2), self.annual)
        straddling = request_for(self.in_a, date(2026, 3, 30), date(2026, 4, 1), self.annual, status='approved')
        early_shift = Shift.objects.create(name='E', code='E1', starts_at=datetime(2026, 1, 1, 6).time(),
                                           ends_at=datetime(2026, 1, 1, 14).time())
        ShiftAssignment.objects.create(employee=self.in_a, day=date(2026, 3, 20), shift=early_shift)
        ShiftAssignment.objects.create(employee=self.in_a, day=date(2026, 4, 20), shift=early_shift)
        services.leave_company(self.hr, self.in_a, date(2026, 4, 1))
        later.refresh_from_db()
        straddling.refresh_from_db()
        self.assertEqual((later.status, straddling.status), ('cancelled', 'approved'))
        self.assertEqual(list(ShiftAssignment.objects.values_list('day', flat=True)), [date(2026, 3, 20)])

    def test_a_last_day_inside_approved_leave_is_refused_until_the_leave_is_put_right(self):
        request_for(self.in_a, date(2026, 3, 30), date(2026, 4, 3), self.annual, status='approved')
        with self.assertRaises(ValidationError):
            services.leave_company(self.hr, self.in_a, date(2026, 4, 1))
        self.in_a.refresh_from_db()
        self.assertIsNone(self.in_a.left_on)

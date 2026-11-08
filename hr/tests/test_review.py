"""What the independent review of the branch found, each as a test that fails without its fix: records belong to the manager
of the day, a lead does not write their own attendance or plan, the Manager and the account link are not for everyone to set,
private text edits are logged, and the database holds two rules that were only Python."""
from datetime import date, datetime, time, timedelta, timezone as utc

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.urls import reverse

from core.models import AuditLog
from farm.models import ProductionDepartment

from .. import read, rules, services
from ..models import AttendanceRecord, Employee, LeaveRequest, LeaveType, Shift, ShiftAssignment
from ..units import token
from .helpers import user
from .helpers_people import PeopleTestCase, TOP, employee, place

PERMS = ('view_employee', 'view_shiftassignment', 'add_shiftassignment', 'change_shiftassignment',
         'delete_shiftassignment', 'view_attendancerecord', 'add_attendancerecord', 'change_attendancerecord',
         'delete_attendancerecord', 'view_leaverequest', 'add_leaverequest', 'change_leaverequest')
MOVE_DAY = date(2026, 4, 1)


class Moved(PeopleTestCase):
    """P is in department A up to 31 March and in B from 1 April; each department has a manager with every HR verb."""

    def setUp(self):
        super().setUp()
        self.old = user('oldboss', *PERMS, group='Old role')
        self.new = user('newboss', *PERMS, group='New role')
        ProductionDepartment.objects.filter(pk=self.dept_a.pk).update(manager=self.old)
        ProductionDepartment.objects.filter(pk=self.dept_b.pk).update(manager=self.new)
        self.p = employee('E-80', 'Papa')
        place(self.p, self.dept_a, TOP, MOVE_DAY - timedelta(days=1))
        place(self.p, self.dept_b, MOVE_DAY)
        self.shift = Shift.objects.create(name='Early', code='EARLY', starts_at=time(6), ends_at=time(14))
        self.cell = ShiftAssignment.objects.create(employee=self.p, day=date(2026, 3, 10), shift=self.shift, note='old note')
        self.punch = AttendanceRecord.objects.create(
            employee=self.p, clock_in=datetime(2026, 3, 10, 6, tzinfo=utc.utc), via='entered', note='old reason')
        kind = LeaveType.objects.create(name='Annual', code='AN')
        self.request = LeaveRequest.objects.create(employee=self.p, leave_type=kind, first_day=date(2026, 3, 10),
                                                   last_day=date(2026, 3, 10))

    def status(self, actor, method, name, pk):
        self.client.force_login(actor)
        return getattr(self.client, method)(reverse(name, args=[pk]), {'version': '1', 'note': 'x'}).status_code

    def test_the_old_record_stays_with_the_old_manager_on_every_verb(self):
        for name, obj in (('hr:production_shiftassignment_edit', self.cell), ('hr:production_shiftassignment_delete', self.cell),
                          ('hr:production_attendancerecord_edit', self.punch), ('hr:production_attendancerecord_delete', self.punch),
                          ('hr:production_leaverequest_detail', self.request), ('hr:production_leaverequest_edit', self.request)):
            self.assertEqual(self.status(self.new, 'get', name, obj.pk), 404, ('new manager', name))
            self.assertEqual(self.status(self.old, 'get', name, obj.pk), 200, ('old manager', name))
        for name in ('hr:production_leaverequest_approve', 'hr:production_leaverequest_cancel'):
            self.assertEqual(self.status(self.new, 'post', name, self.request.pk), 404, name)
        self.assertEqual(self.status(self.new, 'post', 'hr:production_shiftassignment_delete', self.cell.pk), 404)
        self.assertEqual(self.status(self.new, 'post', 'hr:production_attendancerecord_delete', self.punch.pk), 404)
        self.assertEqual((ShiftAssignment.objects.count(), AttendanceRecord.objects.count()), (1, 1))
        self.assertEqual(LeaveRequest.objects.get().status, 'pending')

    def test_a_new_record_after_the_move_is_the_new_managers(self):
        later = ShiftAssignment.objects.create(employee=self.p, day=MOVE_DAY + timedelta(days=2), shift=self.shift)
        self.assertEqual(self.status(self.new, 'get', 'hr:production_shiftassignment_edit', later.pk), 200)
        self.assertEqual(self.status(self.old, 'get', 'hr:production_shiftassignment_edit', later.pk), 404)

    def test_the_lists_follow_the_day_too(self):
        self.client.force_login(self.new)
        rows = self.client.get(reverse('hr:production_leaverequest_list'), {'tab': 'all'}).context['objects']
        self.assertEqual([r['request'] for r in rows], [])
        self.client.force_login(self.old)
        rows = self.client.get(reverse('hr:production_leaverequest_list'), {'tab': 'all'}).context['objects']
        self.assertEqual([r['request'] for r in rows], [self.request])

    def test_the_week_names_the_department_of_a_day_the_viewer_reaches_and_hides_the_other_teams_findings(self):
        night = Shift.objects.create(name='Night', code='NIGHT', starts_at=time(22), ends_at=time(6))
        late = Shift.objects.create(name='Late', code='LATE', starts_at=time(14), ends_at=time(22))
        ShiftAssignment.objects.create(employee=self.p, day=date(2026, 3, 31), shift=night)      # A's last day: 22:00-06:00
        ShiftAssignment.objects.create(employee=self.p, day=MOVE_DAY, shift=late)                # B's first day, 8 h of rest
        row = next(r for r in read.week(self.new, date(2026, 3, 30)).rows if r.employee == self.p)
        self.assertEqual(row.department, self.dept_b)                                          # not A, where the week began
        self.assertEqual([c.visible for c in row.cells[:3]], [False, False, True])
        self.assertEqual([item.code for c in row.cells for item in c.findings], [])           # the night is A's: no finding
        old = next(r for r in read.week(self.old, date(2026, 3, 30)).rows if r.employee == self.p)
        self.assertEqual(old.department, self.dept_a)


class SelfAndPrivilegeTests(PeopleTestCase):
    def setUp(self):
        super().setUp()
        self.lead = user('boss', *PERMS, group='Lead role')
        ProductionDepartment.objects.filter(pk=self.dept_a.pk).update(manager=self.lead)
        Employee.objects.filter(pk=self.in_a.pk).update(user=self.lead, first_name='', last_name='')
        self.in_a.refresh_from_db()
        self.shift = Shift.objects.create(name='Early', code='EARLY', starts_at=time(6), ends_at=time(14))

    def test_a_lead_does_not_plan_or_write_their_own_days(self):
        own = ShiftAssignment.objects.create(employee=self.in_a, day=date(2026, 3, 10), shift=self.shift)
        punch = AttendanceRecord.objects.create(employee=self.in_a, clock_in=datetime(2026, 3, 10, 6, tzinfo=utc.utc),
                                                via='entered', note='x')
        self.client.force_login(self.lead)
        for name, obj in (('hr:production_shiftassignment_edit', own), ('hr:production_shiftassignment_delete', own),
                          ('hr:production_attendancerecord_edit', punch), ('hr:production_attendancerecord_delete', punch)):
            self.assertEqual(self.client.post(reverse(name, args=[obj.pk]), {'version': '1'}).status_code, 403, name)
        response = self.client.post(reverse('hr:production_shiftassignment_create'), {
            'employee': str(self.in_a.pk), 'day': '2026-03-11', 'shift': str(self.shift.pk), 'note': ''})
        self.assertTrue(response.context['form'].non_field_errors())
        with self.assertRaises(Exception):
            services.plan_shifts(self.lead, [(self.in_a, date(2026, 3, 12))], self.shift)
        self.assertEqual((ShiftAssignment.objects.count(), AttendanceRecord.objects.count()), (1, 1))
        # someone who holds Everyone may
        services.plan_shifts(user('allplanner', *PERMS, 'all_employee', group='All planner'),
                             [(self.in_a, date(2026, 3, 12))], self.shift)

    def test_only_those_who_administer_hr_choose_a_production_departments_manager(self):
        editor = user('depteditor', 'view_productiondepartment', 'change_productiondepartment', group='Dept role')
        self.client.force_login(editor)
        form = self.client.get(reverse('farm:productiondepartment_edit', args=[self.dept_b.pk])).context['form']
        self.assertTrue(form.fields['manager'].disabled)
        self.client.post(reverse('farm:productiondepartment_edit', args=[self.dept_b.pk]), {
            'name': 'Nursery B', 'code': 'NUR-B', 'type': 'production', 'manager': str(editor.pk), 'version': '1'})
        self.dept_b.refresh_from_db()
        self.assertNotEqual(self.dept_b.manager, editor)
        admin = user('hradmin2', 'view_productiondepartment', 'change_productiondepartment', 'change_officedepartment',
                     group='Admin role')
        self.client.force_login(admin)
        self.client.post(reverse('farm:productiondepartment_edit', args=[self.dept_b.pk]), {
            'name': 'Nursery B', 'code': 'NUR-B', 'type': 'production', 'manager': str(editor.pk), 'version': '2'})
        self.dept_b.refresh_from_db()
        self.assertEqual(self.dept_b.manager, editor)

    def test_only_the_holders_of_everyone_link_an_account_to_a_person(self):
        editor = user('personeditor', 'view_employee', 'change_employee', group='Person role')
        ProductionDepartment.objects.filter(pk=self.dept_b.pk).update(manager=editor)
        spare = user('spare')
        self.client.force_login(editor)
        form = self.client.get(reverse('hr:production_employee_edit', args=[self.in_b.pk])).context['form']
        self.assertTrue(form.fields['user'].disabled)
        self.assertNotIn(spare, form.fields['user'].queryset)
        self.client.post(reverse('hr:production_employee_edit', args=[self.in_b.pk]), {
            'employee_number': 'E-2', 'last_name': 'Bravo', 'first_name': 'Bob', 'employment_type': 'staff',
            'joined_on': '2026-01-01', 'user': str(spare.pk), 'department': token(self.dept_b), 'title': 'Feeder',
            'from_day': '2026-01-01', 'version': '1'})
        self.in_b.refresh_from_db()
        self.assertIsNone(self.in_b.user)
        self.client.force_login(self.hr)
        self.assertIn(spare, self.client.get(reverse('hr:production_employee_edit', args=[self.in_b.pk])).context['form'].fields['user'].queryset)


class SmallRuleTests(PeopleTestCase):
    def test_a_long_decision_note_is_an_error_not_a_server_error(self):
        lead = user('boss', *PERMS, group='Lead role')
        ProductionDepartment.objects.filter(pk=self.dept_a.pk).update(manager=lead)
        kind = LeaveType.objects.create(name='Annual', code='AN')
        request = LeaveRequest.objects.create(employee=self.in_a, leave_type=kind, first_day=date(2026, 3, 10),
                                              last_day=date(2026, 3, 10))
        with self.assertRaises(ValidationError):
            services.decide_leave(lead, request, True, 'x' * 501)
        self.client.force_login(lead)
        response = self.client.post(reverse('hr:production_leaverequest_approve', args=[request.pk]), {'note': 'x' * 501})
        self.assertEqual(response.status_code, 302)
        request.refresh_from_db()
        self.assertEqual(request.status, 'pending')

    def test_an_old_leave_conflict_does_not_block_planning_another_day(self):
        kind = LeaveType.objects.create(name='Annual', code='AN')
        shift = Shift.objects.create(name='Early', code='EARLY', starts_at=time(6), ends_at=time(14))
        ShiftAssignment.objects.create(employee=self.in_a, day=date(2026, 3, 10), shift=shift)
        LeaveRequest.objects.create(employee=self.in_a, leave_type=kind, first_day=date(2026, 3, 10),
                                    last_day=date(2026, 3, 10), status='approved',
                                    decided_at=datetime(2026, 1, 1, tzinfo=utc.utc))
        everyone = user('allplanner', *PERMS, 'all_employee', group='All planner')
        services.plan_shifts(everyone, [(self.in_a, date(2026, 3, 11))], shift)           # another day of that week: fine
        with self.assertRaises(ValidationError):
            services.plan_shifts(everyone, [(self.in_a, date(2026, 3, 10))], shift)        # the day on leave: refused

    def test_replacing_a_private_text_by_another_is_logged_without_its_words(self):
        kind = LeaveType.objects.create(name='Annual', code='AN')
        lead = user('boss', *PERMS, group='Lead role')
        Employee.objects.filter(pk=self.in_a.pk).update(user=lead, first_name='', last_name='')
        self.client.force_login(lead)
        self.client.post(reverse('hr:production_leaverequest_create'), {
            'employee': str(self.in_a.pk), 'leave_type': str(kind.pk), 'first_day': '2026-03-10', 'last_day': '2026-03-10',
            'reason': 'First words'})
        request = LeaveRequest.objects.get()
        before = AuditLog.objects.count()
        self.client.force_login(self.hr)
        # a holder of Everyone edits the request's reason
        hr_edit = user('editall', 'view_leaverequest', 'change_leaverequest', 'all_employee', group='Edit all')
        self.client.force_login(hr_edit)
        self.client.post(reverse('hr:production_leaverequest_edit', args=[request.pk]), {
            'leave_type': str(kind.pk), 'first_day': '2026-03-10', 'last_day': '2026-03-10', 'reason': 'Other words',
            'version': '1'})
        entry = AuditLog.objects.order_by('created_at').last()
        self.assertEqual(AuditLog.objects.count(), before + 1)
        self.assertEqual(set(entry.changes), {'Reason'})
        self.assertNotIn('words', str(entry.changes))

    def test_the_database_holds_a_note_with_words_and_a_pending_request_without_a_decision(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            AttendanceRecord.objects.bulk_create([AttendanceRecord(
                employee=self.in_a, clock_in=datetime(2026, 3, 10, 6, tzinfo=utc.utc), via='entered', note='   ')])
        kind = LeaveType.objects.create(name='Annual', code='AN')
        with self.assertRaises(IntegrityError), transaction.atomic():
            LeaveRequest.objects.bulk_create([LeaveRequest(
                employee=self.in_a, leave_type=kind, first_day=date(2026, 3, 10), last_day=date(2026, 3, 10),
                decided_at=datetime(2026, 1, 1, tzinfo=utc.utc))])

    def test_an_edit_that_leaves_the_times_alone_does_not_rewrite_the_seconds(self):
        lead = user('boss', *PERMS, group='Lead role')
        ProductionDepartment.objects.filter(pk=self.dept_a.pk).update(manager=lead)
        record = AttendanceRecord.objects.create(
            employee=self.in_a, clock_in=datetime(2026, 3, 10, 8, 0, 45, tzinfo=utc.utc), via='entered', note='first')
        self.client.force_login(lead)
        self.client.post(reverse('hr:production_attendancerecord_edit', args=[record.pk]), {
            'clock_in': '2026-03-10T08:00', 'clock_out': '', 'note': 'second', 'version': '1'})
        record.refresh_from_db()
        self.assertEqual((record.clock_in.second, record.note, record.version), (45, 'second', 2))

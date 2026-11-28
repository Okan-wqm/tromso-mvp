"""The two production role presets (hr.roles, `manage.py hr_roles`): created once when absent, never overwriting a role an
administrator changed, every permission one the role matrix offers; a person holding one walks exactly the pages it is for."""
from io import StringIO

from django.contrib.auth.models import Group
from django.core.management import call_command
from django.urls import reverse

from core import access

from .. import roles
from ..models import Employee
from .helpers_people import PeopleTestCase
from .helpers import user
from core.testing import delete_confirmed


def run():
    out = StringIO()
    call_command('hr_roles', stdout=out)
    return out.getvalue()


def codenames(name):
    return set(Group.objects.get(name=name).permissions.values_list('codename', flat=True))


class PresetTests(PeopleTestCase):
    def test_the_command_creates_both_roles_once(self):
        run()
        self.assertEqual(codenames('Production manager'), {
            'view_attendancerecord', 'add_attendancerecord', 'change_attendancerecord', 'view_shiftassignment',
            'add_shiftassignment', 'change_shiftassignment', 'delete_shiftassignment', 'view_leaverequest',
            'add_leaverequest', 'change_leaverequest', 'all_production_employee'})
        self.assertEqual(codenames('Production worker'), {
            'view_attendancerecord', 'view_shiftassignment', 'crew_shiftassignment', 'view_leaverequest',
            'add_leaverequest'})
        groups = Group.objects.count()
        run()
        self.assertEqual(Group.objects.count(), groups)

    def test_a_role_an_administrator_changed_is_left_alone(self):
        run()
        worker = Group.objects.get(name='Production worker')
        worker.permissions.remove(*worker.permissions.filter(codename='crew_shiftassignment'))
        self.assertIn('kept', run())
        self.assertNotIn('crew_shiftassignment', codenames('Production worker'))

    def test_every_permission_is_one_the_matrix_offers_and_none_is_a_key_of_everything(self):
        offered = {access.perm_name(permission) for permission in access.permissions()}
        for preset in roles.PRESETS:
            for name in preset.permissions:
                self.assertIn(name, offered, (preset.name, name))
                self.assertNotIn(name, {'hr.all_employee', 'hr.view_employee', 'core.browse_database'})
                self.assertFalse(name.startswith('auth.'), name)


class MatrixRoundTripTests(PeopleTestCase):
    """A preset opened in the role matrix and saved as it is (even only renamed) keeps exactly its rights: the matrix's
    one rule (Create, Edit and Delete include Read; Crew, All production and Everyone only widen whose rows the other
    rights reach) is the rule the presets are written in."""

    def test_saving_each_preset_unchanged_gives_it_nothing(self):
        from django.contrib.auth import get_user_model
        run()
        admin = get_user_model().objects.create_superuser('root', 'root@example.com', 'x')
        self.client.force_login(admin)
        for preset in roles.PRESETS:
            group = Group.objects.get(name=preset.name)
            before = codenames(preset.name)
            response = self.client.post(reverse('core:group_edit', args=[group.pk]), {
                'name': f'{preset.name} (renamed)', 'version': '',
                'permissions': [str(permission.pk) for permission in group.permissions.all()]})
            self.assertLess(response.status_code, 400, preset.name)
            group.refresh_from_db()
            self.assertEqual(group.name, f'{preset.name} (renamed)')
            self.assertEqual(codenames(group.name), before, preset.name)
            self.assertNotIn('view_employee', codenames(group.name))

    def test_every_preset_is_closed_under_the_matrix_rule(self):
        for preset in roles.PRESETS:
            self.assertEqual(access.implied(preset.permissions), set(preset.permissions), preset.name)


class WalkTests(PeopleTestCase):
    """Each preset on every address it might try."""

    def setUp(self):
        super().setUp()
        run()
        self.manager = user('manager')
        self.manager.groups.add(Group.objects.get(name='Production manager'))
        self.worker = user('ann')
        self.worker.groups.add(Group.objects.get(name='Production worker'))
        Employee.objects.filter(pk=self.in_a.pk).update(user=self.worker, first_name='', last_name='')

    def walk(self, actor, expected):
        self.client.force_login(actor)
        for name, status in expected.items():
            self.assertEqual(self.client.get(reverse(name)).status_code, status, name)

    def test_the_production_manager_has_the_team_pages_and_nothing_else(self):
        self.walk(self.manager, {
            'hr:production_today': 200, 'hr:production_shiftassignment_list': 200, 'hr:production_leaverequest_list': 200,
            'hr:production_attendancerecord_list': 200, 'hr:production_overview': 200,
            'hr:production_employee_list': 403, 'hr:production_orgchart': 403, 'hr:employee_list': 403,
            'hr:schedulingsettings_list': 403, 'hr:holiday_list': 403, 'hr:leavetype_list': 403, 'hr:shift_list': 403,
            'hr:officedepartment_list': 403, 'core:group_list': 403, 'core:user_list': 403, 'core:database': 403,
            'core:activity_log': 403})
        self.client.force_login(self.manager)
        week = self.client.get(reverse('hr:production_shiftassignment_list')).context['week']
        self.assertEqual({row.employee.pk for row in week.rows}, {self.in_a.pk, self.in_b.pk})   # every production person
        self.assertEqual(self.client.get(reverse('hr:employee_detail', args=[self.in_fin.pk])).status_code, 403)

    def test_the_production_manager_clears_a_cell_and_enters_and_corrects_attendance(self):
        """Owner decision F-203: the manager's preset clears a planned day and enters and corrects the attendance of the
        production people, through the pages, each logged; voiding a stretch stays outside it."""
        from datetime import date, datetime, time, timezone as utc
        from core.models import AuditLog
        from ..models import AttendanceRecord, Shift, ShiftAssignment
        day = date(2026, 3, 2)
        early = Shift.objects.create(name='Early', code='EARLY', starts_at=time(6), ends_at=time(14))
        cell = ShiftAssignment.objects.create(employee=self.in_b, day=day, shift=early)
        self.client.force_login(self.manager)
        response = self.client.post(reverse('hr:production_roster_plan'), {
            'cells': [f'{self.in_b.pk}:{day.isoformat()}'], 'shift': 'clear'})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(ShiftAssignment.all_objects.get(pk=cell.pk).is_deleted)
        self.assertEqual(AuditLog.objects.filter(entity_id=str(cell.pk), action='delete', user=self.manager).count(), 1)
        response = self.client.post(reverse('hr:production_attendancerecord_create'), {
            'employee': str(self.in_b.pk), 'clock_in': '2026-03-02T06:00', 'clock_out': '', 'note': 'Phone was dead'})
        self.assertEqual(response.status_code, 302, response.context and response.context['form'].errors)
        record = AttendanceRecord.objects.get()
        self.assertEqual((record.employee, record.clock_out, record.via, record.created_by),
                         (self.in_b, None, 'entered', self.manager))
        response = self.client.post(reverse('hr:production_attendancerecord_edit', args=[record.pk]), {
            'clock_in': '2026-03-02T06:00', 'clock_out': '2026-03-02T14:00', 'note': 'Left at two', 'version': '1'})
        self.assertEqual(response.status_code, 302, response.context and response.context['form'].errors)
        record.refresh_from_db()
        self.assertEqual(record.clock_out, datetime(2026, 3, 2, 14, tzinfo=utc.utc))
        self.assertEqual(list(AuditLog.objects.filter(entity_id=str(record.pk)).order_by('created_at')
                              .values_list('action', 'user__username')), [('create', 'manager'), ('update', 'manager')])
        voiding = reverse('hr:production_attendancerecord_delete', args=[record.pk])
        self.assertEqual(delete_confirmed(self.client, voiding).status_code, 403)         # voiding is not in the preset
        self.assertFalse(AttendanceRecord.all_objects.get().is_deleted)

    def test_the_production_worker_has_their_own_pages_and_nothing_else(self):
        self.walk(self.worker, {
            'hr:production_today': 200, 'hr:production_shiftassignment_list': 200, 'hr:production_leaverequest_list': 200,
            'hr:production_leaverequest_create': 200, 'hr:production_attendancerecord_list': 200,
            'hr:production_employee_list': 403, 'hr:production_orgchart': 403, 'hr:production_shiftassignment_create': 403,
            'hr:schedulingsettings_list': 403, 'hr:leavetype_list': 403, 'core:group_list': 403, 'core:database': 403})
        self.client.force_login(self.worker)
        week = self.client.get(reverse('hr:production_shiftassignment_list')).context['week']
        self.assertEqual([row.employee for row in week.rows], [self.in_a])
        self.assertIsNotNone(self.client.get(reverse('hr:production_shiftassignment_list')).context['crew'])

    def test_the_sole_manager_does_not_decide_their_own_leave(self):
        from datetime import date
        from ..models import LeaveRequest, LeaveType
        own = Employee.objects.create(employee_number='E-77', joined_on=date(2026, 1, 1), user=self.manager)
        from .helpers_people import place
        place(own, self.dept_a)
        kind = LeaveType.objects.create(name='Annual leave', code='ANNUAL')
        item = LeaveRequest.objects.create(employee=own, leave_type=kind, first_day=date(2026, 3, 2),
                                           last_day=date(2026, 3, 2))
        self.client.force_login(self.manager)
        self.assertEqual(self.client.post(reverse('hr:production_leaverequest_reject', args=[item.pk]),
                                          {'note': 'x'}).status_code, 403)
        item.refresh_from_db()
        self.assertEqual(item.status, 'pending')


class PresetLogTests(PeopleTestCase):
    """The data-layering audit, L-3: a permission granted by `manage.py hr_roles` is in the activity log, as one granted on
    the roles tab is (by the system, with the permissions as the matrix reads them); a role kept as it is logs nothing."""

    def test_each_role_made_is_logged_once(self):
        from core.models import AuditLog
        run()
        logged = AuditLog.objects.filter(action=AuditLog.Action.CREATE, entity_type='role')
        made = {str(group.pk) for group in Group.objects.filter(name__in=[preset.name for preset in roles.PRESETS])}
        self.assertEqual({entry.entity_id for entry in logged}, made)
        self.assertTrue(all(entry.user_id is None for entry in logged))
        run()
        self.assertEqual(AuditLog.objects.filter(action=AuditLog.Action.CREATE, entity_type='role').count(), len(made))

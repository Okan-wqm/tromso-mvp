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
            'view_attendancerecord', 'view_shiftassignment', 'add_shiftassignment', 'change_shiftassignment',
            'view_leaverequest', 'add_leaverequest', 'change_leaverequest', 'all_production_employee'})
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

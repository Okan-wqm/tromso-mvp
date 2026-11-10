"""Migration hr/0012 (owner decision F-203, 2026-11-10): a Production manager role that exists already gets the three rights
the preset now carries (clear a planned day, enter and correct attendance). `manage.py hr_roles` never overwrites a role, so
without it a role saved earlier would keep its old rights. Each right given is one row of the activity log; a right the
role held already is neither given nor logged; going back takes away exactly what the migration gave."""
from importlib import import_module

from django.apps import apps
from django.contrib.auth.models import Group, Permission
from django.db import connection

from core.models import AuditLog

from .. import roles
from .helpers_people import PeopleTestCase

OLD = ('hr.view_attendancerecord', 'hr.view_shiftassignment', 'hr.add_shiftassignment', 'hr.change_shiftassignment',
       'hr.view_leaverequest', 'hr.add_leaverequest', 'hr.change_leaverequest', 'hr.all_production_employee')
NEW = ('hr.delete_shiftassignment', 'hr.add_attendancerecord', 'hr.change_attendancerecord')
SAID = {'hr.delete_shiftassignment': 'Shift schedule: delete', 'hr.add_attendancerecord': 'Attendance: create',
        'hr.change_attendancerecord': 'Attendance: edit'}


def migration():
    return import_module('hr.migrations.0012_production_manager_rights')


def permission(name):
    app, codename = name.split('.')
    return Permission.objects.get(content_type__app_label=app, codename=codename)


def codenames(group):
    return {f'{p.content_type.app_label}.{p.codename}' for p in group.permissions.select_related('content_type')}


def role(name='Production manager', rights=OLD):
    group = Group.objects.create(name=name)
    group.permissions.set([permission(right) for right in rights])
    return group


def run(direction='grant'):
    with connection.schema_editor() as editor:
        getattr(migration(), direction)(apps, editor)


def entries(group):
    return [(entry.user_name, entry.action, entry.entity_type, entry.entity_label, entry.changes['Permissions'])
            for entry in AuditLog.objects.filter(entity_id=str(group.pk)).order_by('created_at', 'changes')]


class ManagerRightsMigrationTests(PeopleTestCase):
    def test_a_role_saved_with_the_old_preset_gets_the_three_rights_each_logged(self):
        group = role()
        run()
        self.assertEqual(codenames(group), {*OLD, *NEW})
        self.assertEqual(codenames(group), set(roles.PRESETS[0].permissions))          # the preset as it is today
        self.assertCountEqual(entries(group), [('system', 'update', 'role', 'Production manager', [None, SAID[right]])
                                               for right in NEW])
        for entry in AuditLog.objects.filter(entity_id=str(group.pk)):
            self.assertIn('hr 0012', entry.changes['Note'][1])
        run()                                                                           # again: nothing to give, nothing said
        self.assertEqual(AuditLog.objects.filter(entity_id=str(group.pk)).count(), 3)

    def test_a_right_the_role_held_already_is_not_given_again_and_what_an_administrator_changed_stays(self):
        """An administrator had given the role Create on Attendance and the Team list, and taken planning away: the
        migration gives the two missing rights, says only those, and touches nothing else."""
        changed = ('hr.view_attendancerecord', 'hr.add_attendancerecord', 'hr.view_shiftassignment', 'hr.view_employee')
        group = role(rights=changed)
        run()
        self.assertEqual(codenames(group), {*changed, 'hr.delete_shiftassignment', 'hr.change_attendancerecord'})
        self.assertCountEqual([said for *_rest, said in entries(group)],
                              [[None, 'Shift schedule: delete'], [None, 'Attendance: edit']])

    def test_no_role_is_made_and_other_roles_are_left_alone(self):
        other = role('Night lead')
        before = AuditLog.objects.count()
        run()
        self.assertFalse(Group.objects.filter(name='Production manager').exists())
        self.assertEqual(codenames(other), set(OLD))
        self.assertEqual(AuditLog.objects.count(), before)

    def test_going_back_takes_away_what_it_gave_and_nothing_else_logged(self):
        """The role held Create on Attendance before; the migration gave the other two. Going back takes those two away
        (each logged) and leaves the one the administrator gave. A right the administrator took away since is not there
        to take, and is not said."""
        group = role(rights=(*OLD, 'hr.add_attendancerecord'))
        run()
        group.permissions.remove(permission('hr.change_attendancerecord'))              # the administrator, afterwards
        run('withdraw')
        self.assertEqual(codenames(group), {*OLD, 'hr.add_attendancerecord'})
        self.assertCountEqual([said for *_rest, said in entries(group)],
                              [[None, 'Shift schedule: delete'], [None, 'Attendance: edit'],
                               ['Shift schedule: delete', None]])
        run()                                                                           # forward again gives both back
        self.assertEqual(codenames(group), {*OLD, *NEW})

    def test_the_migration_names_the_rights_the_matrix_offers_as_the_log_says_them(self):
        from core import access
        offered = {access.perm_name(found) for found in access.permissions()}
        self.assertEqual(set(migration().RIGHTS), set(NEW))
        for right, said in migration().RIGHTS.items():
            self.assertIn(right, offered)
            self.assertEqual(access.summary([permission(right)]), said)

    def test_a_right_given_by_hand_after_a_way_back_is_not_taken_by_a_second_way_back(self):
        """Review R16: given, taken away again, then an administrator gives Create on Attendance by hand; going back a
        second time finds nothing of its own to take (given minus taken away again is nothing), and the right stays."""
        group = role()
        run()
        run('withdraw')
        self.assertEqual(codenames(group), set(OLD))
        group.permissions.add(permission('hr.add_attendancerecord'))                    # the administrator, by hand
        before = AuditLog.objects.filter(entity_id=str(group.pk)).count()
        run('withdraw')
        self.assertEqual(codenames(group), {*OLD, 'hr.add_attendancerecord'})
        self.assertEqual(AuditLog.objects.filter(entity_id=str(group.pk)).count(), before)

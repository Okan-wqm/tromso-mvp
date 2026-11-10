"""The Production manager preset also clears a planned day and enters and corrects attendance (owner decision F-203,
2026-11-10): Delete on the Shift schedule, Create and Edit on Attendance. `manage.py hr_roles` never overwrites a role, so
a Production manager role saved earlier would keep its old rights; this gives an existing one the three, each right given
one row of the activity log (by 'system'). A right the role holds already is neither given nor said, whatever else an
administrator changed in the role stays, and no role is made. The names are written here, as they are when this migration
is made (a migration never reads live code; hr/tests/test_manager_rights.py holds them to the matrix).

Going back takes away exactly what this gave and is still held (read from its own log rows, by the role's id, so a role
renamed since is found), each logged: a right an administrator gave before or took away since is left as it is."""
from django.db import migrations

from core.migrations._log import SYSTEM, entries, system_entry

ROLE = 'Production manager'
# The right, and how the activity log says it (core.access.summary: 'Area: action').
RIGHTS = {
    'hr.delete_shiftassignment': 'Shift schedule: delete',
    'hr.add_attendancerecord': 'Attendance: create',
    'hr.change_attendancerecord': 'Attendance: edit',
}
GIVEN = 'hr 0012: the Production manager preset now clears a planned day and enters and corrects attendance (owner ' \
        'decision F-203).'
TAKEN = 'hr 0012 reversed: the right this migration gave is taken away again.'


def _permission(apps, right):
    app, codename = right.split('.')
    return apps.get_model('auth', 'Permission').objects.filter(content_type__app_label=app, codename=codename).first()


def grant(apps, schema_editor):
    group = apps.get_model('auth', 'Group').objects.filter(name=ROLE).first()
    if group is None:
        return
    held = set(group.permissions.values_list('content_type__app_label', 'codename'))
    for right, said in RIGHTS.items():
        permission = _permission(apps, right)
        if permission is None or tuple(right.split('.')) in held:
            continue
        group.permissions.add(permission)
        system_entry(schema_editor, 'role', group.pk, group.name, {'Permissions': [None, said], 'Note': [None, GIVEN]})


def withdraw(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    owed = {}                                    # {(role id, how the log says the right): given minus taken away again}
    for role_id, who, _action, changes in entries(schema_editor, 'role'):
        note = (changes.get('Note') or [None, None])[1] if who == SYSTEM else None
        old, new = changes.get('Permissions') or [None, None]
        if note == GIVEN:
            owed[(role_id, new)] = owed.get((role_id, new), 0) + 1
        elif note == TAKEN:
            owed[(role_id, old)] = owed.get((role_id, old), 0) - 1
    for right, said in RIGHTS.items():
        permission = _permission(apps, right)
        for (role_id, given), count in owed.items():
            group = Group.objects.filter(pk=role_id).first() if given == said and count > 0 else None
            if group is None or permission is None or not group.permissions.filter(pk=permission.pk).exists():
                continue
            group.permissions.remove(permission)
            system_entry(schema_editor, 'role', group.pk, group.name, {'Permissions': [said, None], 'Note': [None, TAKEN]})


class Migration(migrations.Migration):
    dependencies = [
        ('hr', '0011_employment_bounds'),
        ('auth', '0012_alter_user_first_name_max_length'),
        ('core', '0007_audit_severity'),
    ]

    operations = [migrations.RunPython(grant, withdraw)]

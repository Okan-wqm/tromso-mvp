"""The two production presets back to exactly their rights. Before the role matrix's one rule (Crew, All production and
Everyone include nothing), saving a preset in the matrix added Read on the Team list; a role saved so keeps it until this
runs. The lists are written here, as they were when this migration was made (a migration never reads live code); a
preset that does not exist is not made. Other roles are left alone: `manage.py check --database default` lists those
whose Read may come only from that old rule (core.W003)."""
from django.db import migrations

PRESETS = {
    'Production manager': (
        'hr.view_attendancerecord', 'hr.view_shiftassignment', 'hr.add_shiftassignment', 'hr.change_shiftassignment',
        'hr.view_leaverequest', 'hr.add_leaverequest', 'hr.change_leaverequest', 'hr.all_production_employee'),
    'Production worker': (
        'hr.view_attendancerecord', 'hr.view_shiftassignment', 'hr.crew_shiftassignment', 'hr.view_leaverequest',
        'hr.add_leaverequest'),
}


def restore(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Permission = apps.get_model('auth', 'Permission')
    for name, rights in PRESETS.items():
        group = Group.objects.filter(name=name).first()
        if group is None:
            continue
        found = [Permission.objects.filter(content_type__app_label=right.split('.')[0], codename=right.split('.')[1]).first()
                 for right in rights]
        group.permissions.set([permission for permission in found if permission is not None])


class Migration(migrations.Migration):
    dependencies = [
        ('hr', '0009_entry_keys'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [migrations.RunPython(restore, migrations.RunPython.noop)]

"""The keys of the forms attendance records and leave requests were created with move to the one table every kind of
record uses (core.models.EntryKey, F-232): copied there, then the columns go."""
from django.db import migrations


def copy_keys(apps, schema_editor):
    EntryKey = apps.get_model('core', 'EntryKey')
    for name in ('AttendanceRecord', 'LeaveRequest'):
        model = apps.get_model('hr', name)
        EntryKey.objects.bulk_create([
            EntryKey(key=key, entity_type=f'hr.{name.lower()}', entity_id=str(pk))
            for pk, key in model.objects.filter(entry_key__isnull=False).values_list('pk', 'entry_key')])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0008_entry_keys'),
        ('hr', '0008_production_permissions'),
    ]

    operations = [
        migrations.RunPython(copy_keys, migrations.RunPython.noop),
        migrations.RemoveField(model_name='attendancerecord', name='entry_key'),
        migrations.RemoveField(model_name='leaverequest', name='entry_key'),
    ]

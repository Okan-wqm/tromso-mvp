"""The keys of the forms tasks and recurring tasks were created with move to the one table every kind of record uses
(core.models.EntryKey, F-232): copied there, then the columns go."""
from django.db import migrations


def copy_keys(apps, schema_editor):
    EntryKey = apps.get_model('core', 'EntryKey')
    for name in ('Task', 'TaskSeries'):
        model = apps.get_model('tasks', name)
        EntryKey.objects.bulk_create([
            EntryKey(key=key, entity_type=f'tasks.{name.lower()}', entity_id=str(pk))
            for pk, key in model.objects.filter(entry_key__isnull=False).values_list('pk', 'entry_key')])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0008_entry_keys'),
        ('tasks', '0001_tasks'),
    ]

    operations = [
        migrations.RunPython(copy_keys, migrations.RunPython.noop),
        migrations.RemoveField(model_name='task', name='entry_key'),
        migrations.RemoveField(model_name='taskseries', name='entry_key'),
    ]

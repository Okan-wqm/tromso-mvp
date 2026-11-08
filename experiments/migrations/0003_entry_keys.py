"""The keys of the copy forms experiments were made with move to the one table every kind of record uses
(core.models.EntryKey, cross review F7): copied there, then the column goes."""
from django.db import migrations


def copy_keys(apps, schema_editor):
    EntryKey = apps.get_model('core', 'EntryKey')
    rows = apps.get_model('experiments', 'Experiment').objects.filter(entry_key__isnull=False)
    EntryKey.objects.bulk_create([EntryKey(key=key, entity_type='experiments.experiment', entity_id=str(pk))
                                  for pk, key in rows.values_list('pk', 'entry_key')])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0010_entry_keys'),
        ('experiments', '0002_design_frozen'),
    ]

    operations = [
        migrations.RunPython(copy_keys, migrations.RunPython.noop),
        migrations.RemoveField(model_name='experiment', name='entry_key'),
    ]

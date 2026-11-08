"""The keys of the forms storage operations were entered with move to the one table every kind of record uses
(core.models.EntryKey, cross review F7): copied there, then the column goes."""
from django.db import migrations


def copy_keys(apps, schema_editor):
    EntryKey = apps.get_model('core', 'EntryKey')
    rows = apps.get_model('inventory', 'InventoryOperation').objects.filter(entry_key__isnull=False)
    EntryKey.objects.bulk_create([EntryKey(key=key, entity_type='inventory.inventoryoperation', entity_id=str(pk))
                                  for pk, key in rows.values_list('pk', 'entry_key')])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0008_entry_keys'),
        ('inventory', '0001_storage'),
    ]

    operations = [
        migrations.RunPython(copy_keys, migrations.RunPython.noop),
        migrations.RemoveField(model_name='inventoryoperation', name='entry_key'),
    ]

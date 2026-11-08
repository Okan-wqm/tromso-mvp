"""The keys of the forms stock operations, feedings, treatments, sea-lice counts and water samples were entered with
move to the one table every kind of record uses (core.models.EntryKey, cross review F7): copied there, then the columns
go. A key two water samples shared (the old rule allowed it at two times) is kept for the first."""
from django.db import migrations

MODELS = ('StockOperation', 'FeedingRecord', 'Treatment', 'LiceCount', 'WaterMeasurement')


def copy_keys(apps, schema_editor):
    EntryKey = apps.get_model('core', 'EntryKey')
    for name in MODELS:
        rows = apps.get_model('farm', name).objects.filter(entry_key__isnull=False).values_list('pk', 'entry_key')
        EntryKey.objects.bulk_create([EntryKey(key=key, entity_type=f'farm.{name.lower()}', entity_id=str(pk))
                                      for pk, key in rows], ignore_conflicts=True)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0008_entry_keys'),
        ('farm', '0030_units_on_a_live_site'),
    ]

    operations = [
        migrations.RunPython(copy_keys, migrations.RunPython.noop),
        migrations.RemoveConstraint(model_name='watermeasurement', name='uq_water_measurements_entry'),
        *[migrations.RemoveField(model_name=name.lower(), name='entry_key') for name in MODELS],
    ]

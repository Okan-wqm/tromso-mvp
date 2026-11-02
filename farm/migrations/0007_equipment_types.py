from django.db import migrations

from farm.equipment_types import sync


class Migration(migrations.Migration):
    """The equipment type catalogue (farm/equipment_types.py). A later change to the catalogue ships
    with a migration like this one that calls `sync` again."""

    dependencies = [
        ('farm', '0006_equipment'),
    ]

    operations = [
        migrations.RunPython(sync, migrations.RunPython.noop),
    ]

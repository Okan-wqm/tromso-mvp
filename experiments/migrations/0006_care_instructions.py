"""An experiment's care and biosecurity instructions (owner 2026-11-24: welfare and people's safety come before
confidentiality): what everyone who works its tanks must do, shown beside its tanks to everyone who works them. Like the
approval and the on-call phone, the lead changes it after the start too: the frozen trigger of 0004 lets it through,
nothing else changes."""
from importlib import import_module

from django.db import migrations, models

FROZEN_V2 = import_module('experiments.migrations.0004_confidential').FROZEN_V2
FROZEN_V3 = FROZEN_V2.replace("'on_call_phone' -", "'on_call_phone' - 'care_instructions' -")
assert FROZEN_V3.count("'care_instructions'") == 2


class Migration(migrations.Migration):

    dependencies = [
        ('experiments', '0005_oversee_defaults'),
    ]

    operations = [
        migrations.AddField(
            model_name='experiment',
            name='care_instructions',
            field=models.CharField(blank=True, db_default='', default='', max_length=1000,
                                   verbose_name='Care and biosecurity instructions'),
        ),
        migrations.RunSQL(FROZEN_V3, reverse_sql=FROZEN_V2),
    ]

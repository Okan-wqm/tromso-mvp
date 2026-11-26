"""The water's freshness rules are changed, never deleted (the data-layering audit, M-1): a DELETE of a row is refused by
the database, as its soft delete already was (chk_water_freshness_kept). The reader (farm/water/freshness.py) no longer
makes a lost row again from the code's constants: there is none to lose."""
from django.db import migrations

from core.operations import KeepRows


class Migration(migrations.Migration):

    dependencies = [
        ('farm', '0050_rev_triggers'),
    ]

    operations = [
        KeepRows('water_freshness', 'The water freshness rules'),
    ]

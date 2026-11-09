"""The size limit of a species (Species.max_weight_ratio): how many times heavier, on average, one batch of the species may
be than another sharing a unit with it (the owner, 2026-11-09: fish of very different weights of the same species must
not be in the same tank). Every species already there, deleted ones too (a restored species keeps the rule), gets the
owner's default 2; the farm edits it in Setup › Species, and empty means no check. Going back drops the column."""
import django.core.validators
from decimal import Decimal

from django.db import migrations, models

DEFAULT = Decimal('2.00')


def seed(apps, schema_editor):
    Species = apps.get_model('farm', 'Species')
    Species._base_manager.filter(max_weight_ratio__isnull=True).update(max_weight_ratio=DEFAULT)


class Migration(migrations.Migration):

    dependencies = [
        ('farm', '0033_oxygen_basis'),
    ]

    operations = [
        migrations.AddField(
            model_name='species',
            name='max_weight_ratio',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=6, null=True, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(1000)], verbose_name='Max weight ratio of batches in one unit'),
        ),
        migrations.AddConstraint(
            model_name='species',
            constraint=models.CheckConstraint(condition=models.Q(('max_weight_ratio__gte', 1), ('max_weight_ratio__lte', 1000)), name='chk_species_max_weight_ratio'),
        ),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]

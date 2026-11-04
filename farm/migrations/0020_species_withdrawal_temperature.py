"""The species' assumed water temperature for a medicine withdrawal (Setup › Reference data › Species): the degree-days
a past day without a measured water temperature adds, and what a withdrawal is projected at when none was measured at
all. Empty (every species starts so) keeps the earlier behaviour: such a day counts as 0 °C and a projection without a
temperature is unknown. Reversible: the column and its check are dropped."""
import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('farm', '0019_water_points'),
    ]

    operations = [
        migrations.AddField(
            model_name='species',
            name='withdrawal_temperature_c',
            field=models.DecimalField(
                blank=True, decimal_places=1, max_digits=4, null=True,
                validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(40)],
                verbose_name='Assumed water temperature for withdrawal (°C)'),
        ),
        migrations.AddConstraint(
            model_name='species',
            constraint=models.CheckConstraint(
                condition=models.Q(('withdrawal_temperature_c__gte', 0), ('withdrawal_temperature_c__lte', 40)),
                name='chk_species_withdrawal_temperature'),
        ),
    ]

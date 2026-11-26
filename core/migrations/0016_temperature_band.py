"""How far, in °C, a place's live temperature may be from the temperature a sample's NH₃ was worked out with and still
keep that temperature fresh: the platform owner's setting (the coordinator's decisions of 2026-11-26), 1.0 °C until
they set another, 0.1 to 5.0."""
from decimal import Decimal

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0015_platform_settings_kept'),
    ]

    operations = [
        migrations.AddField(
            model_name='platformsettings',
            name='temperature_band_c',
            field=models.DecimalField(decimal_places=1, default=Decimal('1.0'), max_digits=2, validators=[django.core.validators.MinValueValidator(Decimal('0.1')), django.core.validators.MaxValueValidator(Decimal('5.0'))], verbose_name='Temperature band (°C)'),
        ),
        migrations.AddConstraint(
            model_name='platformsettings',
            constraint=models.CheckConstraint(condition=models.Q(('temperature_band_c__gte', Decimal('0.1')),
                                                                 ('temperature_band_c__lte', Decimal('5.0'))),
                                              name='chk_platform_settings_temperature_band'),
        ),
    ]

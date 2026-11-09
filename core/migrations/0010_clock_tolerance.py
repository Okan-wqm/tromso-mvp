"""How far ahead of the server's clock a water value may be stamped and still count as fresh: the platform owner's setting
(cross review F10), 300 s as the code held (farm/water/evaluate.py CLOCK_SKEW until now)."""

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0009_platform_settings'),
    ]

    operations = [
        migrations.AddField(
            model_name='platformsettings',
            name='clock_tolerance_seconds',
            field=models.PositiveIntegerField(default=300, validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(3600)], verbose_name='Clock tolerance (seconds)'),
        ),
        migrations.AddConstraint(
            model_name='platformsettings',
            constraint=models.CheckConstraint(condition=models.Q(('clock_tolerance_seconds__gte', 0),
                                                                 ('clock_tolerance_seconds__lte', 3600)),
                                              name='chk_platform_settings_clock_tolerance'),
        ),
    ]

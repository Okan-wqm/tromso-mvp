"""How long a medicine withdrawal whose end is unknown holds fish: the platform owner's setting (the owner's decision
of 17.11.2026), 180 days after the course's last day until they set another."""

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0012_account_mails'),
    ]

    operations = [
        migrations.AddField(
            model_name='platformsettings',
            name='unknown_withdrawal_days',
            field=models.PositiveSmallIntegerField(default=180, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(3650)], verbose_name='An unknown withdrawal end holds for (days)'),
        ),
        migrations.AddConstraint(
            model_name='platformsettings',
            constraint=models.CheckConstraint(condition=models.Q(('unknown_withdrawal_days__gte', 1),
                                                                 ('unknown_withdrawal_days__lte', 3650)),
                                              name='chk_platform_settings_unknown_withdrawal'),
        ),
    ]

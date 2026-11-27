"""Platform settings: how many days of the shift schedule one paint may plan (hr.services.plan_shifts), 500 until the
platform owner sets another, bounded by a database check (the review of wip/hr-one-path, N-5: the bound on what one
request may ask is the owner's, not a figure in the code)."""
import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0018_audit_log_order'),
    ]

    operations = [
        migrations.AddField(
            model_name='platformsettings',
            name='plan_batch_cells',
            field=models.PositiveSmallIntegerField(
                default=500,
                validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(5000)],
                verbose_name='Days planned in one go on the shift schedule'),
        ),
        migrations.AddConstraint(
            model_name='platformsettings',
            constraint=models.CheckConstraint(
                condition=models.Q(('plan_batch_cells__gte', 1), ('plan_batch_cells__lte', 5000)),
                name='chk_platform_settings_plan_batch'),
        ),
    ]

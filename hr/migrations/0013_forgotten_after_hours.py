"""After how many hours an open clock-in counts as a forgotten clock-out (SchedulingSettings.forgotten_after_hours; owner
decision F-095, 2026-11-10): a setting HR edits, 16 hours until it sets another (the one row of settings gets the
default), 1 to 168 as a database check. Going back drops the column."""
import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('hr', '0012_production_manager_rights'),
    ]

    operations = [
        migrations.AddField(
            model_name='schedulingsettings',
            name='forgotten_after_hours',
            field=models.PositiveSmallIntegerField(default=16, validators=[django.core.validators.MinValueValidator(1, 'Give a whole number of hours from 1 to 168 (a week).'), django.core.validators.MaxValueValidator(168, 'Give a whole number of hours from 1 to 168 (a week).')], verbose_name='A clock-in counts as forgotten after (hours)'),
        ),
        migrations.AddConstraint(
            model_name='schedulingsettings',
            constraint=models.CheckConstraint(condition=models.Q(('forgotten_after_hours__gte', 1), ('forgotten_after_hours__lte', 168)), name='chk_scheduling_forgotten_after', violation_error_message='Give a whole number of hours from 1 to 168 (a week).'),
        ),
    ]

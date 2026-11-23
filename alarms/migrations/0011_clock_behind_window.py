"""A device behind is raised only when it is behind on every pass of a window, the user's per severity (round-2 review
N1): 600 s for both, longer than an ingest restart or a gateway's drain after a ten-minute link drop takes, short
enough that a truly slow clock is said within the same quarter hour. Its values never wait for it (alarms/clock.py)."""

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('alarms', '0010_device_clock'),
    ]

    operations = [
        migrations.AddField(
            model_name='severitypolicy',
            name='clock_behind_window_seconds',
            field=models.PositiveIntegerField(default=600, validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(3600)], verbose_name='Device clock behind for (seconds)'),
            preserve_default=False,
        ),
        migrations.AddConstraint(
            model_name='severitypolicy',
            constraint=models.CheckConstraint(condition=models.Q(('clock_behind_window_seconds__gte', 0), ('clock_behind_window_seconds__lte', 3600)), name='chk_alarm_severity_policies_clock_window'),
        ),
    ]

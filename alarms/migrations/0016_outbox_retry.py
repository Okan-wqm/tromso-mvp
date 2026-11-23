"""The outbox's delivery (alarms/outbox.py): how long apart a failing transport is tried with one notification, per
severity, seeded with the defaults (critical 30 s, warning 120 s: five attempts cover two minutes of a push service's
outage for a critical alarm, eight for a warning), from here on the user's rows (Alarm severity rules); and the outbox's
figures on the alarm worker's row (when its sender last went through it, how many notifications wait, since when the
oldest). Back: the columns go."""

import django.core.validators
from django.db import migrations, models

SEEDS = {'critical': 30, 'warning': 120}


def seed(apps, schema_editor):
    Policy = apps.get_model('alarms', 'SeverityPolicy')
    for severity, seconds in SEEDS.items():
        Policy.objects.filter(severity=severity).update(retry_seconds=seconds)


class Migration(migrations.Migration):

    dependencies = [
        ('alarms', '0015_worker_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='severitypolicy',
            name='retry_seconds',
            field=models.PositiveIntegerField(default=30, validators=[django.core.validators.MinValueValidator(1),
                                                                      django.core.validators.MaxValueValidator(3600)],
                                              verbose_name='Retry after (seconds)'),
            preserve_default=False,
        ),
        migrations.RunPython(seed, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='severitypolicy',
            constraint=models.CheckConstraint(condition=models.Q(('retry_seconds__gte', 1), ('retry_seconds__lte', 3600)),
                                              name='chk_alarm_severity_policies_retry'),
        ),
        migrations.AddField(
            model_name='alarmworkerstatus',
            name='last_send_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Outbox last gone through at'),
        ),
        migrations.AddField(
            model_name='alarmworkerstatus',
            name='outbox_waiting',
            field=models.PositiveIntegerField(default=0, verbose_name='Notifications waiting'),
        ),
        migrations.AddField(
            model_name='alarmworkerstatus',
            name='outbox_oldest_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Oldest waiting since'),
        ),
    ]

"""The alarm worker's own row (alarms/worker.py, alarms.AlarmWorkerStatus): whether the process that checks the alarms runs,
when it last finished a pass, and after how long without one the pages and the health check call the alarms unchecked.
Mutable and empty until a worker first starts. Back: the table goes."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('alarms', '0014_subject_own_held'),
    ]

    operations = [
        migrations.CreateModel(
            name='AlarmWorkerStatus',
            fields=[
                ('name', models.CharField(max_length=40, primary_key=True, serialize=False, verbose_name='Name')),
                ('state', models.CharField(choices=[('running', 'Checking the alarms'), ('stopped', 'Stopped')],
                                           max_length=10, verbose_name='State')),
                ('host', models.CharField(blank=True, max_length=100, verbose_name='Host')),
                ('pid', models.PositiveIntegerField(blank=True, null=True, verbose_name='Process')),
                ('started_at', models.DateTimeField(verbose_name='Started at')),
                ('heartbeat_at', models.DateTimeField(verbose_name='Last seen at')),
                ('last_pass_at', models.DateTimeField(blank=True, null=True, verbose_name='Last pass at')),
                ('last_ok_pass_at', models.DateTimeField(blank=True, null=True,
                                                         verbose_name='Last pass without a failed step at')),
                ('last_pass_ms', models.PositiveIntegerField(blank=True, null=True, verbose_name='Last pass took (ms)')),
                ('failed_steps', models.CharField(blank=True, max_length=300, verbose_name='Failed steps of the last pass')),
                ('consecutive_failures', models.PositiveIntegerField(default=0, verbose_name='Failures in a row')),
                ('last_error', models.CharField(blank=True, max_length=300, verbose_name='Last error')),
                ('stale_after_seconds', models.PositiveIntegerField(verbose_name='Unchecked after (seconds)')),
            ],
            options={
                'verbose_name': 'alarm worker status',
                'verbose_name_plural': 'alarm worker statuses',
                'db_table': 'alarm_worker_status',
                'constraints': [
                    models.CheckConstraint(condition=models.Q(('state__in', ['running', 'stopped'])),
                                           name='chk_alarm_worker_status_state'),
                    models.CheckConstraint(condition=models.Q(('stale_after_seconds__gte', 1)),
                                           name='chk_alarm_worker_status_stale_after'),
                ],
            },
        ),
    ]

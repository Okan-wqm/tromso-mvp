import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('alarms', '0002_reference_data'),
    ]

    operations = [
        migrations.CreateModel(
            name='AlarmSubjectState',
            fields=[
                ('key', models.CharField(max_length=200, primary_key=True, serialize=False)),
                ('pending_since', models.DateTimeField(blank=True, null=True)),
                ('clear_since', models.DateTimeField(blank=True, null=True)),
                ('last_bad_at', models.DateTimeField(blank=True, null=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'alarm subject state',
                'verbose_name_plural': 'alarm subject states',
                'db_table': 'alarm_subject_state',
            },
        ),
        migrations.AddField(
            model_name='alarmclearance',
            name='cause',
            field=models.CharField(choices=[('returned', 'Back inside the limit'), ('event_closed', 'The sensor rule no longer holds'), ('structural', 'No longer judged (no fish or no limit)'), ('restored', 'Restored')], default='returned', max_length=12, verbose_name='Why'),
        ),
        migrations.AddConstraint(
            model_name='alarmclearance',
            constraint=models.CheckConstraint(condition=models.Q(('cause__in', ['returned', 'event_closed', 'structural', 'restored'])), name='chk_alarm_clearances_cause'),
        ),
        migrations.AddField(
            model_name='alarmsubjectstate',
            name='open_alarm',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='alarms.alarm', verbose_name='Open alarm'),
        ),
    ]

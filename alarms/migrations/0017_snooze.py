"""Snoozing an alarm (ISA-18.2 shelving; owner decision Q5 of 2026-11-08): who snoozed which alarm, when, until when and why
(`alarm_shelves`), and who ended one early (`alarm_shelve_ends`), both append-only by the alarms' trigger function of
0001; and per severity the longest snooze, seeded with the owner's defaults (critical 4 h, warning 12 h), from here on
the user's rows (Alarm severity rules). Back: the triggers, the tables and the column go."""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

SEEDS = {'critical': 240, 'warning': 720}
TABLES = ('alarm_shelves', 'alarm_shelve_ends')
APPEND_ONLY = ''.join(f"""
CREATE TRIGGER trg_{table}_append_only BEFORE UPDATE OR DELETE ON {table}
    FOR EACH ROW EXECUTE FUNCTION alarms_append_only();
""" for table in TABLES)
DROP = ''.join(f'DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table}; ' for table in TABLES)


def seed(apps, schema_editor):
    Policy = apps.get_model('alarms', 'SeverityPolicy')
    for severity, minutes in SEEDS.items():
        Policy.objects.filter(severity=severity).update(shelve_max_minutes=minutes)


class Migration(migrations.Migration):

    dependencies = [
        ('alarms', '0016_outbox_retry'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AlarmShelve',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('shelved_at', models.DateTimeField(verbose_name='Snoozed at')),
                ('until', models.DateTimeField(verbose_name='Snoozed until')),
                ('reason', models.CharField(max_length=300, verbose_name='Why')),
                ('alarm', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='shelves',
                                            to='alarms.alarm', verbose_name='Alarm')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='alarm_shelves',
                                           to=settings.AUTH_USER_MODEL, verbose_name='Snoozed by')),
            ],
            options={
                'verbose_name': 'alarm snooze',
                'verbose_name_plural': 'alarm snoozes',
                'db_table': 'alarm_shelves',
                'ordering': ['-shelved_at', '-id'],
                'constraints': [
                    models.CheckConstraint(condition=models.Q(('until__gt', models.F('shelved_at'))),
                                           name='chk_alarm_shelves_until'),
                    models.CheckConstraint(condition=models.Q(('reason', ''), _negated=True),
                                           name='chk_alarm_shelves_reason'),
                ],
            },
        ),
        migrations.CreateModel(
            name='AlarmShelveEnd',
            fields=[
                ('shelve', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, primary_key=True,
                                                related_name='end', serialize=False, to='alarms.alarmshelve',
                                                verbose_name='Snooze')),
                ('ended_at', models.DateTimeField(verbose_name='Ended at')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+',
                                           to=settings.AUTH_USER_MODEL, verbose_name='Ended by')),
            ],
            options={
                'verbose_name': 'alarm snooze end',
                'verbose_name_plural': 'alarm snooze ends',
                'db_table': 'alarm_shelve_ends',
            },
        ),
        migrations.RunSQL(APPEND_ONLY, reverse_sql=DROP),
        migrations.AddField(
            model_name='severitypolicy',
            name='shelve_max_minutes',
            field=models.PositiveIntegerField(default=240, verbose_name='Longest snooze (minutes)'),
            preserve_default=False,
        ),
        migrations.RunPython(seed, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='severitypolicy',
            constraint=models.CheckConstraint(condition=models.Q(
                ('pk__in', []),
                models.Q(('severity', 'critical'), ('shelve_max_minutes__gte', 1), ('shelve_max_minutes__lte', 480)),
                models.Q(('severity', 'warning'), ('shelve_max_minutes__gte', 1), ('shelve_max_minutes__lte', 1440)),
                _connector='OR'), name='chk_alarm_severity_policies_shelve'),
        ),
    ]

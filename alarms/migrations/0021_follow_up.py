"""A critical is batched, never covered (alarms/floods.py; the coordinator's bar on the last recheck, 2026-11-24): per
severity how long the next criticals of a kind wait for one follow-up message after a message of that kind went to the
person, seeded 5 s for critical (at most 8 s, inside the owner's 10 s from a value to its message) and 0 for warning (warnings are grouped by their flood window), from here
on the user's rows (Alarm severity rules). The database default 0 holds nothing back for a row written without it.
Back: the column goes."""

from django.db import migrations, models

SEEDS = {'critical': 5, 'warning': 0}


def seed(apps, schema_editor):
    Policy = apps.get_model('alarms', 'SeverityPolicy')
    for severity, seconds in SEEDS.items():
        Policy.objects.filter(severity=severity).update(follow_up_seconds=seconds)


class Migration(migrations.Migration):

    dependencies = [
        ('alarms', '0020_worker_undeliverable'),
    ]

    operations = [
        migrations.AddField(
            model_name='severitypolicy',
            name='follow_up_seconds',
            field=models.PositiveIntegerField(db_default=0, verbose_name='Follow-up after (seconds)'),
        ),
        migrations.RunPython(seed, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='severitypolicy',
            constraint=models.CheckConstraint(
                condition=models.Q(('pk__in', []),
                                   models.Q(('follow_up_seconds__gte', 0), ('follow_up_seconds__lte', 8),
                                            ('severity', 'critical')),
                                   models.Q(('follow_up_seconds__gte', 0), ('follow_up_seconds__lte', 0),
                                            ('severity', 'warning')), _connector='OR'),
                name='chk_alarm_severity_policies_follow_up'),
        ),
    ]

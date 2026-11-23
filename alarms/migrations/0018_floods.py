"""Alarm floods (alarms/floods.py; ISA-18.2, the owner's burst requirement): per severity how many alarms of one kind make
a flood for one person within how long, seeded with the alarm plan's defaults (3 alarms within 120 s, both severities),
from here on the user's rows (Alarm severity rules); on each delivery attempt the kind of alarm it is about and, for a
flood message, how many alarms it covered; and the outcome "grouped": a notification a flood message to the same person
covered, never sent on its own and never sent again. The append-only trigger of the attempts fires on no row here: the
columns are added, no row is changed. Back: the columns go, refused while an attempt says "grouped"."""

import django.core.validators
from django.db import migrations, models

SEEDS = {'critical': (3, 120), 'warning': (3, 120)}


def refuse_with_grouped(apps, schema_editor):
    """Going back while a notification was covered by a flood message: the attempts before this had no word for it, and
    they are append-only (never rewritten to an outcome that is not true)."""
    found = apps.get_model('alarms', 'DeliveryAttempt').objects.filter(outcome='grouped').count()
    if found:
        raise RuntimeError(f'alarms 0018 cannot be reversed: {found} delivery attempt(s) say a flood message covered '
                           f'them, which the alarms before it have no word for. Restore a backup taken before it '
                           f'instead.')


def seed(apps, schema_editor):
    Policy = apps.get_model('alarms', 'SeverityPolicy')
    for severity, (count, window) in SEEDS.items():
        Policy.objects.filter(severity=severity).update(flood_count=count, flood_window_seconds=window)


class Migration(migrations.Migration):

    dependencies = [
        ('alarms', '0017_snooze'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='deliveryattempt',
            name='chk_alarm_delivery_attempts_outcome',
        ),
        migrations.RemoveConstraint(
            model_name='deliveryattempt',
            name='uq_alarm_delivery_attempts_sent_once',
        ),
        migrations.AddField(
            model_name='deliveryattempt',
            name='flood_key',
            field=models.CharField(blank=True, max_length=150, verbose_name='Kind of alarm'),
        ),
        migrations.AddField(
            model_name='deliveryattempt',
            name='flood_size',
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name='Alarms in the flood message'),
        ),
        migrations.AddField(
            model_name='severitypolicy',
            name='flood_count',
            field=models.PositiveIntegerField(default=3, validators=[django.core.validators.MinValueValidator(2),
                                                                     django.core.validators.MaxValueValidator(1000)],
                                              verbose_name='A flood from (alarms)'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='severitypolicy',
            name='flood_window_seconds',
            field=models.PositiveIntegerField(default=120, validators=[django.core.validators.MinValueValidator(10),
                                                                       django.core.validators.MaxValueValidator(3600)],
                                              verbose_name='Flood window (seconds)'),
            preserve_default=False,
        ),
        migrations.RunPython(seed, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='deliveryattempt',
            name='outcome',
            field=models.CharField(choices=[('sent', 'Sent'), ('failed', 'Failed'),
                                            ('grouped', 'Covered by a flood message')],
                                   max_length=10, verbose_name='Outcome'),
        ),
        migrations.AddConstraint(
            model_name='deliveryattempt',
            constraint=models.CheckConstraint(condition=models.Q(('outcome__in', ['sent', 'failed', 'grouped'])),
                                              name='chk_alarm_delivery_attempts_outcome'),
        ),
        migrations.AddConstraint(
            model_name='deliveryattempt',
            constraint=models.UniqueConstraint(condition=models.Q(('outcome__in', ['sent', 'grouped'])),
                                               fields=('notification',), name='uq_alarm_delivery_attempts_sent_once'),
        ),
        migrations.AddConstraint(
            model_name='severitypolicy',
            constraint=models.CheckConstraint(condition=models.Q(('flood_count__gte', 2), ('flood_count__lte', 1000),
                                                                 ('flood_window_seconds__gte', 10),
                                                                 ('flood_window_seconds__lte', 3600)),
                                              name='chk_alarm_severity_policies_flood'),
        ),
        # last, so going back it runs first, on the state that still has what it reads
        migrations.RunPython(migrations.RunPython.noop, refuse_with_grouped),
    ]

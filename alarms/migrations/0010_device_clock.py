"""A device whose clock differs from the platform's is an alarm (owner, 2026-11-09; alarms/clock.py): the alarm names its
device, and each severity's rule holds the device clock limit and its deadband, seeded with the owner's defaults:
- warning 60 s (deadband 10 s): the ingest contract's default future skew (sensors_contract.future_skew_s), past which the
  ingest no longer trusts a device's time;
- critical 300 s (deadband 30 s): the read layer's clock tolerance (farm/water/evaluate.py), past which a value ahead is
  no longer shown as fresh.
A device removed or deactivated ends its clock alarms (cause "device removed")."""

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


SEEDS = {'warning': (60, 10), 'critical': (300, 30)}


def seed(apps, schema_editor):
    Policy = apps.get_model('alarms', 'SeverityPolicy')
    for severity, (limit, deadband) in SEEDS.items():
        Policy.objects.filter(severity=severity).update(clock_skew_seconds=limit, clock_skew_deadband_seconds=deadband)


class Migration(migrations.Migration):

    dependencies = [
        ('alarms', '0009_clearance_causes'),
        ('farm', '0036_opening_balances'),
        ('sensors', '0009_alarm_event_acknowledgement_columns_removed'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='alarm',
            name='chk_alarms_shape',
        ),
        migrations.RemoveConstraint(
            model_name='alarmclearance',
            name='chk_alarm_clearances_cause',
        ),
        migrations.AddField(
            model_name='alarm',
            name='device',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='alarms', to='sensors.device', verbose_name='Device'),
        ),
        migrations.AddField(
            model_name='severitypolicy',
            name='clock_skew_deadband_seconds',
            field=models.PositiveIntegerField(default=10, verbose_name='Device clock deadband (seconds)'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='severitypolicy',
            name='clock_skew_seconds',
            field=models.PositiveIntegerField(default=60, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(3600)], verbose_name='Device clock off by more than (seconds)'),
            preserve_default=False,
        ),
        migrations.RunPython(seed, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='alarmclearance',
            name='cause',
            field=models.CharField(choices=[('returned', 'Back inside the limit'), ('event_closed', 'The sensor rule no longer holds'), ('structural', 'No fish in the unit any more'), ('limit_removed', 'The water limit was removed'), ('restored', 'Restored'), ('unit_removed', 'The unit was removed'), ('merged', 'Merged into the unit’s one alarm of that level'), ('device_removed', 'The device was removed or deactivated')], default='returned', max_length=20, verbose_name='Why'),
        ),
        migrations.AddConstraint(
            model_name='alarm',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('device__isnull', True), ('parameter', ''), ('point__isnull', True), ('sensor_event__isnull', False), ('source', 'sensor_rule')), models.Q(('device__isnull', True), ('point__isnull', False), ('sensor_event__isnull', True), ('source', 'water_limit'), models.Q(('parameter', ''), _negated=True)), models.Q(('point__isnull', True), ('sensor_event__isnull', True), ('source', 'system'), models.Q(('parameter', ''), _negated=True)), _connector='OR'), name='chk_alarms_shape'),
        ),
        migrations.AddConstraint(
            model_name='alarmclearance',
            constraint=models.CheckConstraint(condition=models.Q(('cause__in', ['returned', 'event_closed', 'structural', 'limit_removed', 'restored', 'unit_removed', 'merged', 'device_removed'])), name='chk_alarm_clearances_cause'),
        ),
        migrations.AddConstraint(
            model_name='severitypolicy',
            constraint=models.CheckConstraint(condition=models.Q(('clock_skew_deadband_seconds__gte', 0), ('clock_skew_deadband_seconds__lt', models.F('clock_skew_seconds')), ('clock_skew_seconds__gte', 1), ('clock_skew_seconds__lte', 3600)), name='chk_alarm_severity_policies_clock'),
        ),
    ]

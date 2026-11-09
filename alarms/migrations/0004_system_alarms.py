"""The alarm system's own alarms (source 'system'). Going back is refused once one exists (cross review F14): the alarms
are append-only (a trigger refuses DELETE), so the old shape check could not hold, and removing them would erase the
record of the alarm system's failures. Going back is possible only on a database that never had one."""
from django.db import migrations, models


def refuse_with_system_alarms(apps, schema_editor):
    if apps.get_model('alarms', 'Alarm').objects.filter(source='system').exists():
        raise RuntimeError('alarms 0004 cannot be reversed: a system alarm exists, and the alarms are append-only (their '
                           'history is never deleted). Restore a backup taken before it instead.')


class Migration(migrations.Migration):

    dependencies = [
        ('alarms', '0003_levels'),
        ('sensors', '0009_alarm_event_acknowledgement_columns_removed'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='alarm',
            name='chk_alarms_source',
        ),
        migrations.RemoveConstraint(
            model_name='alarm',
            name='chk_alarms_shape',
        ),
        migrations.AlterField(
            model_name='alarm',
            name='source',
            field=models.CharField(choices=[('sensor_rule', 'Sensor alarm rule'), ('water_limit', 'Water limit'), ('system', 'The alarm system itself')], max_length=12, verbose_name='Source'),
        ),
        migrations.AddConstraint(
            model_name='alarm',
            constraint=models.CheckConstraint(condition=models.Q(('source__in', ['sensor_rule', 'water_limit', 'system'])), name='chk_alarms_source'),
        ),
        migrations.AddConstraint(
            model_name='alarm',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('parameter', ''), ('point__isnull', True), ('sensor_event__isnull', False), ('source', 'sensor_rule')), models.Q(('point__isnull', False), ('sensor_event__isnull', True), ('source', 'water_limit'), models.Q(('parameter', ''), _negated=True)), models.Q(('point__isnull', True), ('sensor_event__isnull', True), ('source', 'system'), models.Q(('parameter', ''), _negated=True)), _connector='OR'), name='chk_alarms_shape'),
        ),
        migrations.RunPython(migrations.RunPython.noop, refuse_with_system_alarms),
    ]

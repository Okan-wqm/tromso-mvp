from django.db import migrations, models


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
    ]

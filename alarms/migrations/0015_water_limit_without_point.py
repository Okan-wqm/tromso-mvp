"""A water-limit alarm may have no sampling point (review 5 of wip/fresh-rule, M1): a unit with no point of its own in a
system with no loop point is read at its system's probes, so its card can go red on a value judged for its fish; its
levels are raised there without a point, on the unit's site and department (alarms/sources.py `_water_subjects`), so
every red card has its alarm. Every other shape is as before. Back: the stricter check again (refused while such an
alarm exists: they are history and are never deleted)."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('alarms', '0014_subject_own_held'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='alarm',
            name='chk_alarms_shape',
        ),
        migrations.AddConstraint(
            model_name='alarm',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('device__isnull', True), ('parameter', ''), ('point__isnull', True), ('sensor_event__isnull', False), ('source', 'sensor_rule')), models.Q(('device__isnull', True), ('sensor_event__isnull', True), ('source', 'water_limit'), models.Q(('parameter', ''), _negated=True)), models.Q(('point__isnull', True), ('sensor_event__isnull', True), ('source', 'system'), models.Q(('parameter', ''), _negated=True)), _connector='OR'), name='chk_alarms_shape'),
        ),
    ]

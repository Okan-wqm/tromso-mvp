"""A water-limit alarm may have no sampling point (review 5 of wip/fresh-rule, M1): a unit with no point of its own in a
system with no loop point is read at its system's probes, so its card can go red on a value judged for its fish; its
levels are raised there without a point, on the unit's site and department (alarms/sources.py `_water_subjects`), so
every red card has its alarm. Every other shape is as before. Back: the stricter check again, refused while such an
alarm exists, saying why (they are history and are never deleted: _reverse.refuse_alarms)."""
from django.db import migrations, models

from ._reverse import refuse_alarms


def refuse_with_alarms_without_a_point(apps, schema_editor):
    refuse_alarms(apps, '0022', "of a water limit have no sampling point (a unit read at its system's probes)",
                  source='water_limit', point__isnull=True)


class Migration(migrations.Migration):

    dependencies = [
        ('alarms', '0021_follow_up'),
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
        # last: going back runs it first, before the stricter check is put back
        migrations.RunPython(migrations.RunPython.noop, refuse_with_alarms_without_a_point),
    ]

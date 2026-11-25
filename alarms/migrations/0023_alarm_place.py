"""An alarm's place, kept on it (alarms/place.py): the unit and the system it is about, which its seal, the activity
log's stamp and the keepers of its fish read (landing review L2, M1, W4). Existing alarms are given theirs from what
they still say:
1. a point: its unit, or the system a loop point samples;
2. an open alarm's subject (`water:unit:<unit>:...`, `system:unit:<unit>:...`): that unit;
3. a sensor rule's event: the place its channel was bound to (a point's unit or system, or a system);
4. an alarm that has none of these and has closed (a unit read at its system with no point, a unit's value that could
   not be evaluated): the unit whose code begins its summary ('T-05: ...', 'T-05, from its system: ...'), on the
   alarm's site, when exactly one unit there has that code.
An alarm still without a place is about no unit (a device's clock, a failed step).

The alarms are append-only (a trigger, alarms 0001): the trigger is set aside for the one statement that gives the
existing alarms their place, in the migration's own transaction, and set back (as alarms/migrations/_reverse.py does);
each alarm given a place is said in the activity log. Going back drops the two columns."""
from django.db import migrations, models
import django.db.models.deletion

from core.migrations._log import system_entry

UNIT_PREFIXES = ('water:unit:', 'system:unit:')


def forwards(apps, schema_editor):
    Alarm = apps.get_model('alarms', 'Alarm')
    State = apps.get_model('alarms', 'AlarmSubjectState')
    Tank = apps.get_model('farm', 'Tank')
    tanks = {str(pk): (code, site) for pk, code, site in Tank.objects.values_list(
        'pk', 'code', 'production_department__site_id')}
    by_code = {}
    for pk, (code, site) in tanks.items():
        by_code.setdefault((site, code), []).append(pk)
    keys = {}
    for alarm_id, key in State.objects.filter(open_alarm__isnull=False).values_list('open_alarm_id', 'key'):
        for prefix in UNIT_PREFIXES:
            if key.startswith(prefix):
                keys[alarm_id] = key[len(prefix):].split(':', 1)[0]
    changed = []
    for alarm in Alarm.objects.select_related('point', 'sensor_event__binding__point').iterator(chunk_size=2000):
        unit = system = None
        if alarm.point_id:
            unit, system = alarm.point.unit_id, alarm.point.system_id
        elif alarm.sensor_event_id and alarm.sensor_event.binding_id:
            binding = alarm.sensor_event.binding
            if binding.point_id:
                unit, system = binding.point.unit_id, binding.point.system_id
            else:
                system = binding.system_id
        key_unit = keys.get(alarm.pk)
        if key_unit in tanks:
            unit = key_unit
        if unit is None and system is None and not alarm.point_id and not alarm.sensor_event_id:
            code = alarm.summary.split(':', 1)[0].split(', from its system', 1)[0].strip()
            found = by_code.get((alarm.site_id, code), [])
            if len(found) == 1:
                unit = found[0]
        if unit is not None or system is not None:
            alarm.unit_id, alarm.system_id = unit, system
            changed.append(alarm)
    if not changed:
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute('ALTER TABLE alarms DISABLE TRIGGER trg_alarms_append_only')
    Alarm.objects.bulk_update(changed, ['unit', 'system'], batch_size=2000)
    with schema_editor.connection.cursor() as cursor:
        cursor.execute('ALTER TABLE alarms ENABLE TRIGGER trg_alarms_append_only')
    for alarm in changed:
        place = {'Unit': [None, tanks[str(alarm.unit_id)][0]]} if alarm.unit_id else {}
        if alarm.system_id:
            place['System'] = [None, str(alarm.system_id)]
        system_entry(schema_editor, 'alarm', alarm.pk, alarm.summary,
                     {**place, 'Note': [None, 'alarms 0023: the place it is about, kept on it (its seal reads it).']})


class Migration(migrations.Migration):

    dependencies = [
        ('alarms', '0022_water_limit_without_point'),
        ('core', '0017_audit_log_order'),
        ('farm', '0050_rev_triggers'),
        ('sensors', '0015_default_no_data_rules'),
    ]

    operations = [
        migrations.AddField(
            model_name='alarm',
            name='unit',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name='alarms', to='farm.tank', verbose_name='Unit'),
        ),
        migrations.AddField(
            model_name='alarm',
            name='system',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name='alarms', to='farm.system', verbose_name='System'),
        ),
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]

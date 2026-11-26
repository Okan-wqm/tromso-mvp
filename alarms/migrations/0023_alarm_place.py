"""An alarm's place, kept on it (alarms/place.py): the unit and the system it is about, which its seal, the activity
log's stamp and the keepers of its fish read (landing review L2, M1, W4). Existing alarms are given theirs from what
they still say:
1. a point: its unit, or the system a loop point samples;
2. an open alarm's subject (`water:unit:<unit>:...`, `system:unit:<unit>:...`): that unit;
3. a sensor rule's event: the place its channel was bound to (a point's unit or system, or a system);
4. an alarm about a unit that says so only in its summary, its first word the unit's code ('T-05: ...',
   'T-05, from S-01 · Loop: ...', 'T-05 holds fish and has no active sampling point ...': a unit read at its system's
   loop point or at none, a unit's value that could not be evaluated, a unit with no water point; landing review 2,
   N5 a and b): the unit of that code on the alarm's site, when exactly one unit there has it.
An alarm whose summary names a code several units of its site have had (a deleted unit's code used again: N5 c) is
given no place: it fails open, and the migration says how many in the activity log, so the owner sees the number.

The alarms are append-only (a trigger, alarms 0001): the trigger is set aside for the one statement that gives the
existing alarms their place, in the migration's own transaction, and set back (as alarms/migrations/_reverse.py does).
One activity-log entry says what it did (N5 e): how many alarms it placed, by unit and by system only, and how many it
could not. Going back drops the two columns."""
import re

from django.db import migrations, models
import django.db.models.deletion

from core.migrations._log import system_entry

UNIT_PREFIXES = ('water:unit:', 'system:unit:')
# A unit's code at the start of a summary that names the unit (core.models.CODE: no space, colon or comma in a code).
SUMMARY_UNIT = re.compile(r'([A-Za-z0-9][A-Za-z0-9._-]*)(?=: |, from | holds fish )')


def placed(alarm, keys, tanks, by_code):
    """(unit id, system id, ambiguous): the place of one existing alarm, and whether its summary named a unit code
    several units of its site have had."""
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
        return key_unit, system, False
    if unit is None and not alarm.sensor_event_id and not alarm.device_id:
        found = SUMMARY_UNIT.match(alarm.summary or '')
        if found:
            units = by_code.get((alarm.site_id, found.group(1)), [])
            if len(units) == 1:
                return units[0], system, False
            if len(units) > 1:
                return None, system, True
    return unit, system, False


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
    changed, counts = [], {'unit': 0, 'system': 0, 'ambiguous': 0, 'none': 0}
    for alarm in Alarm.objects.select_related('point', 'sensor_event__binding__point').iterator(chunk_size=2000):
        unit, system, ambiguous = placed(alarm, keys, tanks, by_code)
        if ambiguous:
            counts['ambiguous'] += 1
        if unit is not None or system is not None:
            alarm.unit_id, alarm.system_id = unit, system
            changed.append(alarm)
            counts['unit' if unit is not None else 'system'] += 1
        elif not ambiguous:
            counts['none'] += 1
    if changed:
        with schema_editor.connection.cursor() as cursor:
            cursor.execute('ALTER TABLE alarms DISABLE TRIGGER trg_alarms_append_only')
        Alarm.objects.bulk_update(changed, ['unit', 'system'], batch_size=2000)
        with schema_editor.connection.cursor() as cursor:
            cursor.execute('ALTER TABLE alarms ENABLE TRIGGER trg_alarms_append_only')
    if any(counts.values()):
        system_entry(schema_editor, 'alarm', '', 'alarms 0023: the place of every alarm', {
            'Placed on a unit': [None, str(counts['unit'])],
            'Placed on a system only': [None, str(counts['system'])],
            'Not placed: a unit code several units of its site have had': [None, str(counts['ambiguous'])],
            'About no unit': [None, str(counts['none'])],
            'Note': [None, 'alarms 0023: the place each alarm is about, kept on it (its seal reads it).']})


class Migration(migrations.Migration):

    dependencies = [
        ('alarms', '0022_water_limit_without_point'),
        ('core', '0007_audit_severity'),            # the log's row of a data migration (core.migrations._log)
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

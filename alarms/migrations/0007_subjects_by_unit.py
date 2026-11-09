"""The water alarms' subjects are keyed by the unit, never by the point that stood for it (cross review F7): every
`water:<point>:<slot>:<severity>` row becomes `water:unit:<unit>:<slot>:<severity>`. Two rows of one unit at one level
(its middle point replaced while an alarm was open) become one: the alarm opened first stays the subject's open alarm,
every other open one is cleared now with the cause "merged" (the append-only record says why, nothing is deleted), and
the timers are merged the safe way: the earliest pending time, the latest bad value's time, no clear timer running (the
off-delay starts again from evidence). Going back (round-2 review N2) first gives the clearances "merged" and "unit
removed" the nearest older cause, "no longer judged" (structural), each logged, then writes the point keys again, each unit's subject at the point of its
open alarm (else its anchor at the time), so nothing is lost either way."""
from collections import defaultdict

from django.db import migrations, models
from django.utils import timezone

from ._reverse import remap


def by_unit(apps, schema_editor):
    State = apps.get_model('alarms', 'AlarmSubjectState')
    Clearance = apps.get_model('alarms', 'AlarmClearance')
    Point = apps.get_model('farm', 'SamplingPoint')
    old = [state for state in State.objects.select_related('open_alarm').filter(key__startswith='water:')
           if not state.key.startswith('water:unit:')]
    units = {str(pk): unit for pk, unit in Point._base_manager.filter(
        pk__in={state.key.split(':')[1] for state in old}).values_list('pk', 'unit_id')}
    groups = defaultdict(list)
    for state in old:
        _water, point, slot, severity = state.key.split(':')
        unit = units.get(point)
        if unit is None:
            continue                  # not a unit's point: never a water subject; left as it is
        groups[f'water:unit:{unit}:{slot}:{severity}'].append(state)
    now = timezone.now()
    for key, states in groups.items():
        open_ = sorted((state for state in states if state.open_alarm_id),
                       key=lambda state: (state.open_alarm.opened_at, state.open_alarm_id))
        kept = open_[0].open_alarm_id if open_ else None
        Clearance.objects.bulk_create([Clearance(alarm_id=state.open_alarm_id, cleared_at=now, cause='merged')
                                       for state in open_[1:]])
        pending = [state.pending_since for state in states if state.pending_since]
        bad = [state.last_bad_at for state in states if state.last_bad_at]
        State.objects.filter(pk__in=[state.pk for state in states]).delete()
        State.objects.create(key=key, open_alarm_id=kept, pending_since=min(pending) if pending and not kept else None,
                             clear_since=None, last_bad_at=max(bad) if bad else None)


def by_point(apps, schema_editor):
    State = apps.get_model('alarms', 'AlarmSubjectState')
    Point = apps.get_model('farm', 'SamplingPoint')
    for state in State.objects.select_related('open_alarm').filter(key__startswith='water:unit:'):
        _water, _unit, unit, slot, severity = state.key.split(':')
        point = state.open_alarm.point_id if state.open_alarm_id else (
            Point._base_manager.filter(unit_id=unit, kind='middle').values_list('pk', flat=True).first())
        if point is None:
            state.delete()            # no point to key it at, and no alarm open: only timers, rebuilt by the next pass
            continue
        State.objects.filter(pk=state.pk).delete()
        State.objects.create(key=f'water:{point}:{slot}:{severity}', open_alarm_id=state.open_alarm_id,
                             pending_since=state.pending_since, clear_since=state.clear_since,
                             last_bad_at=state.last_bad_at)



def back_to_old_causes(apps, schema_editor):
    """Going back: "merged" and "unit removed" did not exist before; both are "no longer judged" (structural)."""
    remap(apps, schema_editor, {'merged': 'structural', 'unit_removed': 'structural'}, '0007')


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_audit_log'),          # going back logs each clearance it changes (audit_log)
        ('alarms', '0006_severity_rules_kept'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='alarmclearance',
            name='chk_alarm_clearances_cause',
        ),
        migrations.AlterField(
            model_name='alarmclearance',
            name='cause',
            field=models.CharField(choices=[('returned', 'Back inside the limit'), ('event_closed', 'The sensor rule no longer holds'), ('structural', 'No longer judged (no fish or no limit)'), ('restored', 'Restored'), ('unit_removed', 'The unit was removed'), ('merged', 'Merged into the unit’s one alarm of that level')], default='returned', max_length=12, verbose_name='Why'),
        ),
        migrations.AddConstraint(
            model_name='alarmclearance',
            constraint=models.CheckConstraint(condition=models.Q(('cause__in', ['returned', 'event_closed', 'structural', 'restored', 'unit_removed', 'merged'])), name='chk_alarm_clearances_cause'),
        ),
        migrations.RunPython(by_unit, by_point),
        migrations.RunPython(migrations.RunPython.noop, back_to_old_causes),
    ]

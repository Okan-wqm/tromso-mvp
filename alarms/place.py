"""Where an alarm is: the unit and the system it is about, decided once, when it opens, and kept on it (Alarm.unit,
Alarm.system). Everything that must know an alarm's place reads those two columns: its seal (alarms/sealing.py: an alarm
on a sealed cell does not exist for whoever may not see the cell), the activity log's stamp that follows the seal
(core.sealing.works_of), and who keeps the fish when nobody on the rules may see it (alarms/routing.py, `keepers`).

An alarm names its place in up to three ways, and `places` reads all of them:
- a subject of a unit (`water:unit:<unit>:...`, a unit's quantity, read at its own point, at its system's loop point
  or at none: alarms/0022; `system:unit:<unit>:...`, a unit's value that could not be evaluated, a unit with fish and
  no water point): the unit, whatever point stood for it;
- a water value at a sampling point (`point`): the point's unit, or the system it samples (a loop point);
- a sensor rule's event (`sensor_event`): the place its channel was bound to when it opened (`binding`): a point's unit
  or system, or a system.
An alarm of the alarm system about no unit (a device's clock, a failed step) has no place."""
from farm.models import SamplingPoint

UNIT_PREFIXES = ('water:unit:', 'system:unit:')


def unit_of_key(key):
    """The unit id a subject key names (`water:unit:<unit>:...`, `system:unit:<unit>:...`), or None."""
    for prefix in UNIT_PREFIXES:
        if key and key.startswith(prefix):
            return key[len(prefix):].split(':', 1)[0] or None
    return None


def _id(value):
    """The id of a record given as itself or as its id."""
    return getattr(value, 'pk', value)


def places(specs, keys=None):
    """[(unit id, system id)] for alarms about to open: `specs` as alarms.services.open_alarms takes them ({point}, or
    {sensor_event}, or neither), `keys` their subjects' keys where known. Read as stored (no viewer: the alarm loop and a
    request alike), one query for any number of alarms."""
    keys = list(keys or [''] * len(specs))
    points = {_id(spec.get('point')) for spec in specs if spec.get('point') is not None}
    by_point = {pk: (unit, system) for pk, unit, system in SamplingPoint._base_manager.filter(pk__in=points)
                .values_list('pk', 'unit_id', 'system_id')} if points else {}
    found = []
    for spec, key in zip(specs, keys):
        point, event = spec.get('point'), spec.get('sensor_event')
        unit = system = None
        if point is not None:
            unit, system = by_point.get(_id(point), (None, None))
        elif event is not None and getattr(event, 'binding_id', None):
            unit, system = bound(event.binding)
        found.append((unit_of_key(key) or unit, system))
    return found


def bound(binding):
    """(unit id, system id) of the place a sensor channel was bound to: a point's unit or system, or a system."""
    if binding.point_id:
        point = binding.point
        return point.unit_id, point.system_id
    return None, binding.system_id


def of_alarm(alarm):
    """(unit id, system id) of an alarm: its kept place, or, for a row written without one (straight in the database),
    its point's. The seal reads the same two paths (alarms/sealing.py)."""
    if alarm.unit_id or alarm.system_id:
        return alarm.unit_id, alarm.system_id
    if alarm.point_id:
        point = alarm.point
        return point.unit_id, point.system_id
    return None, None

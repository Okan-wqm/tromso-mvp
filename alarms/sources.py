"""What holds an alarm, read from the judges that already exist (never judged a second way here):

- the sensor alarm rules: sensors/alarms.py `evaluate` keeps an AlarmEvent per rule and channel; each event gets its
  Alarm when it opens and its clearance when it closes (`sensor_events`);
- the water limits: farm/water/read.py `unit_water` judges every live unit's water (its middle point's, with its other
  own points and its system standing in, the worst fresh value deciding) by the species' limits; a value critical or warning holds an alarm of that severity per point and parameter, a severity that changes
  clears the alarm and opens one at the new severity, and a fresh value back inside the limits (or without a limit) clears
  it. A value that only goes stale never clears it: an alarm does not end by going blind (`water`).
Where an alarm is (its site, its production department) is set when it opens, for the recipient rules."""
from django.db.models import Q

from core import audit
from farm.models import Tank
from farm.models.water_point import site_of
from farm.water import parameters, read as water_read
from farm.water.evaluate import ALERTS, Status
from sensors.models import AlarmEvent, Binding, Channel

from . import services
from .models import Alarm, Source


# ---- the sensor rules ------------------------------------------------------------------------------------------------
def _department_of(channel, at):
    """The production department of the place the channel was bound to at `at`, or None."""
    binding = (Binding.all_objects.filter(channel=channel, valid_from__lte=at)
               .filter(Q(valid_to__isnull=True) | Q(valid_to__gt=at))
               .select_related('point__unit', 'point__system', 'point__equipment', 'system', 'equipment').first())
    if binding is None:
        return None
    place = binding.point.owner if binding.point_id else binding.system or binding.equipment
    return getattr(place, 'production_department', None)


def mirror(event):
    """The alarm of a sensor rule's event, opened at the event's moment where its channel's device is (and cleared at once
    when the event has closed already)."""
    channel = Channel.all_objects.select_related('device__site').filter(channel_no=event.channel_no).first()
    with audit.source_language():
        summary = f'{event.rule}' + (f' · {channel.device.code}' if channel is not None else f' #{event.channel_no}')
    alarm = services.open_alarm(
        at=event.opened_at, severity=event.rule.severity, summary=summary,
        site=channel.device.site if channel is not None else None,
        production_department=_department_of(channel, event.opened_at) if channel is not None else None,
        source=Source.SENSOR_RULE, sensor_event=event)
    if event.closed_at is not None:
        services.clear(alarm, event.closed_at)
    return alarm


def sensor_events():
    """Mirrors the sensor rules' events: (alarms opened, alarms cleared)."""
    opened = cleared = 0
    for event in AlarmEvent.objects.filter(alarm__isnull=True).select_related('rule').order_by('opened_at', 'pk'):
        mirror(event)
        opened += 1
        cleared += event.closed_at is not None
    for alarm in (Alarm.objects.filter(source=Source.SENSOR_RULE, clearance__isnull=True,
                                       sensor_event__closed_at__isnull=False).select_related('sensor_event')):
        services.clear(alarm, alarm.sensor_event.closed_at)
        cleared += 1
    return opened, cleared


# ---- the water limits ------------------------------------------------------------------------------------------------
def _summary(point, reading):
    """'T-01 · Middle: pH (NBS scale) 5.50 (critical)', in English at rest."""
    owner = point.owner
    with audit.source_language():
        label = str(parameters.get(reading.code).label)
        status = str(Status(reading.status).label).lower()
        return f'{getattr(owner, "code", owner)} · {point.name}: {label} {reading.value} ({status})'


def _where(point):
    owner = point.owner
    return {'site': site_of(point), 'production_department': getattr(owner, 'production_department', None)}


def water(now):
    """Opens and clears the water limits' alarms at `now`: (opened, cleared)."""
    # The subjects are the live units, each through the point that stands for it (its middle point: A9.1, never an inlet);
    # a depth point's or the loop's value reaches it as the unit's own worst fresh value, judged for its fish. One read.
    water = water_read.unit_water(list(Tank.objects.all()), now)
    latest = {found.point.pk: found for found in water.values() if found.point is not None}
    by_id = {point_id: found.point for point_id, found in latest.items()}
    held = {(alarm.point_id, alarm.parameter): alarm
            for alarm in Alarm.objects.filter(source=Source.WATER_LIMIT, clearance__isnull=True)}
    opened = cleared = 0
    for point_id, found in latest.items():
        for code, reading in found.readings.items():
            key = (point_id, code)
            alarm = held.pop(key, None)
            if reading.status == Status.STALE:
                continue                                          # nothing new: an open alarm stays open
            if alarm is not None and (reading.status not in ALERTS or reading.status != alarm.severity):
                services.clear(alarm, now)
                cleared += 1
                alarm = None
            if alarm is None and reading.status in ALERTS:
                point = by_id[point_id]
                services.open_alarm(at=now, severity=reading.status, summary=_summary(point, reading),
                                    source=Source.WATER_LIMIT, point=point, parameter=code, **_where(point))
                opened += 1
    # What is left held an alarm at a point no longer read (made inactive, its owner deleted) or a parameter no longer
    # there: nothing says it is over, so it stays open, on the page, until a person sees it.
    return opened, cleared

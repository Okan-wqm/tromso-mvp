"""What holds an alarm, read from the judges that already exist (never judged a second way here):

- the sensor alarm rules: sensors/alarms.py `evaluate` keeps an AlarmEvent per rule and channel; each event gets its
  Alarm when it opens and its clearance when it closes (`sensor_events`);
- the water limits: farm/water/read.py `unit_water` judges every live unit's water (its middle point's, with its other
  own points and its system standing in, the worst fresh value deciding) by the species' limits (`water`). A unit's
  parameter has two levels, each its own alarm subject (ISA-18.2 L and LL): warning holds while the value is judged
  warning or critical, critical while it is judged critical. A level is raised once its condition has held for its
  severity's on-delay, counted from the first offending value's time; it clears once a fresh value is clear of it even
  moved by the parameter's deadband toward danger, for the severity's off-delay (alarms.rules: the user's rows). A value
  that only goes stale never clears it (an alarm does not end by going blind); a unit with no fish or no limit any more
  clears it at once (structural). The timers are the subjects' rows (AlarmSubjectState), so a restart loses none.
Where an alarm is (its site, its production department) is set when it opens, for the recipient rules."""
from django.db.models import Q

from core import audit
from farm.models import Tank
from farm.models.water_point import site_of
from farm.water import parameters, read as water_read
from farm.water.read import LIMITED, OXYGEN
from farm.water.evaluate import ALERTS, RANK, Status, judge, worst
from sensors.models import AlarmEvent, Binding, Channel

from . import services
from .models import Alarm, AlarmSubjectState, ClearCause, Severity, Source


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
        services.clear(alarm, event.closed_at, ClearCause.EVENT_CLOSED)
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
        services.clear(alarm, alarm.sensor_event.closed_at, ClearCause.EVENT_CLOSED)
        cleared += 1
    return opened, cleared


# ---- the water limits ------------------------------------------------------------------------------------------------
# What each level holds on: the judgements that keep a unit's parameter at that level.
HOLDS = {Severity.WARNING: ALERTS, Severity.CRITICAL: (Status.CRITICAL,)}
UNJUDGED = (Status.NO_LIMIT, Status.NOT_MEASURED)


def _summary(point, reading):
    """'T-01 · Middle: pH (NBS scale) 5.50 (critical)', in English at rest."""
    owner = point.owner
    with audit.source_language():
        label = str(parameters.get(reading.code).label)
        status = str(Status(reading.judged).label).lower()
        return f'{getattr(owner, "code", owner)} · {point.name}: {label} {reading.value} ({status})'


def _where(point):
    owner = point.owner
    return {'site': site_of(point), 'production_department': getattr(owner, 'production_department', None)}


def slot_of(code):
    """The quantity a code is: the dissolved oxygen is one, in mg/L or in % (read.OXYGEN); every other code its own."""
    return OXYGEN if code in parameters.SAME_QUANTITY else code


def _slots(found):
    """{slot: the reading that decides it}: per quantity of a unit's water, its limited reading judged worst."""
    slots = {}
    for reading in found.readings.values():
        if reading.code in LIMITED and reading.value is not None:
            slot = slot_of(reading.code)
            if slot not in slots or RANK[reading.judged] < RANK[slots[slot].judged]:
                slots[slot] = reading
    return slots


def _moved(reading, rules):
    """The judgements of a reading's value moved by its parameter's deadband both ways, through its own rows."""
    band = rules.deadband(reading.code)
    return [judge(value, row) for row in reading.limits for value in (reading.value - band, reading.value + band)]


def judged_clear(reading, rules):
    """The judgement of the value that decided `reading`, moved by its parameter's deadband both ways, through the same
    rows and the same judgement (evaluate.judge), and through its other oxygen unit where it was judged so: a level clears
    only when it is clear even so. Never a second rule."""
    decider = reading.worse or reading
    found = _moved(decider, rules) + (_moved(decider.through, rules) if decider.through is not None else [])
    return worst(found) if found else decider.judged


def clear_evidence(reading, severity, rules):
    """Whether this pass's reading says the level is over: fresh, and clear of it by the deadband."""
    return reading.status != Status.STALE and judged_clear(reading, rules) not in HOLDS[severity]


def water(now, rules):
    """Raises and clears the water limits' levels at `now` (alarms.rules `rules`): (opened, cleared)."""
    # The subjects are the live units, each through the point that stands for it (its middle point: A9.1, never an inlet);
    # a depth point's or the loop's value reaches it as the unit's own worst fresh value, judged for its fish. One read.
    found_water = water_read.unit_water(list(Tank.objects.all()), now)
    readings = {}
    for found in found_water.values():
        if found.point is not None:
            for slot, reading in _slots(found).items():
                for severity in HOLDS:
                    readings[f'water:{found.point.pk}:{slot}:{severity}'] = (found.point, severity, reading)
    states = {state.key: state for state in AlarmSubjectState.objects.select_for_update(of=('self',)).select_related(
        'open_alarm').filter(key__in=readings)}
    opened = cleared = 0
    for key, (point, severity, reading) in readings.items():
        state = states.get(key) or AlarmSubjectState(key=key)
        before = (state.open_alarm_id, state.pending_since, state.clear_since, state.last_bad_at)
        decider = reading.worse or reading
        if reading.judged in HOLDS[severity]:
            state.clear_since = None
            state.last_bad_at = max(filter(None, (state.last_bad_at, decider.at)))
            if state.open_alarm_id is None:
                state.pending_since = state.pending_since or decider.at
                if now - state.pending_since >= rules.on_delay(severity):
                    state.open_alarm = services.open_alarm(
                        at=now, severity=severity, summary=_summary(point, reading), source=Source.WATER_LIMIT,
                        point=point, parameter=reading.code, **_where(point))
                    state.pending_since = None
                    opened += 1
        else:
            state.pending_since = None
            if state.open_alarm_id is not None:
                cause = None
                if reading.judged in UNJUDGED:
                    cause = ClearCause.STRUCTURAL
                elif clear_evidence(reading, severity, rules):
                    state.clear_since = state.clear_since or now
                    if now - state.clear_since >= rules.off_delay(severity):
                        cause = ClearCause.RETURNED
                else:
                    state.clear_since = None
                if cause is not None:
                    services.clear(state.open_alarm, now, cause)
                    state.open_alarm, state.clear_since = None, None
                    cleared += 1
        if (state.open_alarm_id, state.pending_since, state.clear_since, state.last_bad_at) != before:
            state.save()
    # A subject read no more (its point made inactive, its owner deleted, the parameter gone) keeps its alarm open: nothing
    # says it is over, so it stays on the page until a person sees it.
    return opened, cleared

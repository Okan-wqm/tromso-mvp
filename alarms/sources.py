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
from dataclasses import dataclass

from django.db.models import Q
from django.utils.translation import gettext as _

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


def clear_evidence(reading, severity, rules, last_bad_at):
    """Whether this pass's reading says the level is over: fresh, taken after the last value that held it (an older value
    that is the newest again, its bad successor voided or its probe taken out, says nothing new: alarm plan, defect 4),
    and clear of it by the deadband."""
    decider = reading.worse or reading
    return (reading.status != Status.STALE and (last_bad_at is None or decider.at > last_bad_at)
            and judged_clear(reading, rules) not in HOLDS[severity])


@dataclass
class Step:
    """What a subject's row says after one pass: an alarm to raise (with what makes it), or one to clear (with why)."""
    raise_alarm: bool = False
    clear_cause: str = None


def advance(state, holds, clear_ok, bad_at, severity, rules, now, structural=False):
    """One pass of a subject's lifecycle on its row (AlarmSubjectState), the one rule every subject follows: while its
    condition holds, the clear timer stops, the last bad value's time is kept and, without an open alarm, the on-delay runs
    from the first offending value's time (`bad_at`); once it is over, an open alarm clears after the off-delay while the
    evidence clears it (`clear_ok`), at once when the subject is no longer judged (`structural`). Returns the Step."""
    step = Step()
    if holds:
        state.clear_since = None
        state.last_bad_at = max(filter(None, (state.last_bad_at, bad_at)))
        if state.open_alarm_id is None:
            state.pending_since = state.pending_since or bad_at
            step.raise_alarm = now - state.pending_since >= rules.on_delay(severity)
        return step
    state.pending_since = None
    if state.open_alarm_id is None:
        return step
    if structural:
        step.clear_cause = ClearCause.STRUCTURAL
    elif clear_ok:
        state.clear_since = state.clear_since or now
        if now - state.clear_since >= rules.off_delay(severity):
            step.clear_cause = ClearCause.RETURNED
    else:
        state.clear_since = None
    return step


STATE_FIELDS = ['open_alarm', 'pending_since', 'clear_since', 'last_bad_at', 'updated_at']


def _states(keys):
    return {state.key: state for state in AlarmSubjectState.objects.select_for_update(of=('self',)).select_related(
        'open_alarm').filter(key__in=keys)}


def _snapshot(state):
    return state.open_alarm_id, state.pending_since, state.clear_since, state.last_bad_at


SENSORS_FAILED = 'sensors_failed'


def water(now, rules):
    """Raises and clears the water limits' levels at `now` (alarms.rules `rules`), and the system alarm of live sources that
    cannot be read: (opened, cleared). While they cannot be read nothing clears: a sample alone must never end an alarm a
    sensor raised (alarm plan, defect 3). Set-based: one read of the water, one of the subjects' rows, and the alarms,
    clearances, log entries and rows written in one statement each, however many units alarm at once (defect 7)."""
    # The subjects are the live units, each through the point that stands for it (its middle point: A9.1, never an inlet);
    # a depth point's or the loop's value reaches it as the unit's own worst fresh value, judged for its fish. One read.
    found_water = water_read.unit_water(list(Tank.objects.all()), now)
    failed = any(found.sensors_failed for found in found_water.values())
    readings = {}
    for found in found_water.values():
        if found.point is not None:
            for slot, reading in _slots(found).items():
                for severity in HOLDS:
                    readings[f'water:{found.point.pk}:{slot}:{severity}'] = (found.point, severity, reading)
    system_key = f'system:{SENSORS_FAILED}'
    states = _states([*readings, system_key])
    raises, clears, before = [], [], {}

    def step(key, holds, clear_ok, bad_at, severity, spec, structural=False, cause=None):
        state = states.setdefault(key, AlarmSubjectState(key=key))
        before[key] = _snapshot(state)
        done = advance(state, holds, clear_ok, bad_at, severity, rules, now, structural=structural)
        if done.raise_alarm:
            raises.append((key, spec()))
        elif done.clear_cause is not None:
            clears.append((state, cause or done.clear_cause))

    for key, (point, severity, reading) in readings.items():
        step(key, reading.judged in HOLDS[severity],
             not failed and clear_evidence(reading, severity, rules, states[key].last_bad_at if key in states else None),
             (reading.worse or reading).at, severity,
             lambda point=point, severity=severity, reading=reading: {
                 'at': now, 'severity': severity, 'summary': _summary(point, reading), 'source': Source.WATER_LIMIT,
                 'point': point, 'parameter': reading.code, **_where(point)},
             structural=reading.judged in UNJUDGED)
    with audit.source_language():
        failure = str(_('The live water values (the sensors) cannot be read: alarms are not cleared until they can.'))
    step(system_key, failed, not failed, now, Severity.CRITICAL, lambda: {
        'at': now, 'severity': Severity.CRITICAL, 'summary': failure, 'source': Source.SYSTEM,
        'parameter': SENSORS_FAILED}, cause=ClearCause.RESTORED)
    services.clear_many([(state.open_alarm, now, cause) for state, cause in clears])
    for state, _cause in clears:
        state.open_alarm, state.clear_since = None, None
    for key, alarm in services.raise_many(raises).items():
        states[key].open_alarm, states[key].pending_since = alarm, None
    changed = [state for key, state in states.items() if key in before and _snapshot(state) != before[key]]
    AlarmSubjectState.objects.bulk_create(changed, update_conflicts=True, unique_fields=['key'],
                                          update_fields=STATE_FIELDS)
    # A subject read no more (its point made inactive, its owner deleted, the parameter gone) keeps its alarm open: nothing
    # says it is over, so it stays on the page until a person sees it.
    return len(raises), len(clears)

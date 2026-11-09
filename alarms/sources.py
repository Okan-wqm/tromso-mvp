"""What holds an alarm, read from the judges that already exist (never judged a second way here):

- the sensor alarm rules: sensors/alarms.py `evaluate` keeps an AlarmEvent per rule and channel; each event gets its
  Alarm when it opens and its clearance when it closes (`sensor_events`);
- the water limits: farm/water/read.py `unit_water` judges every live unit's water (its middle point's, with its other
  own points and its system standing in, the worst fresh value deciding) by the species' limits (`water`). A unit's
  parameter has two levels, each its own alarm subject (ISA-18.2 L and LL): warning holds while the value is judged
  warning or critical, critical while it is judged critical. A level is raised once its condition has held for its
  severity's on-delay, counted from the first offending value's time (the pass's, for a value stamped ahead of the
  clock: `seen_at`); it clears once a fresh value is clear of it even
  moved by the parameter's deadband toward danger, for the severity's off-delay (alarms.rules: the user's rows). A value
  that only goes stale never clears it (an alarm does not end by going blind); a unit with no fish or no limit any more
  clears it at once (structural). The timers are the subjects' rows (AlarmSubjectState), so a restart loses none.
Where an alarm is (its site, its production department) is set when it opens, for the recipient rules."""
import logging
from dataclasses import dataclass

from django.db import transaction
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

logger = logging.getLogger(__name__)


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
    """The worst judgement of every value that takes part in `reading`'s status (the value A9 chose and the place's other
    fresh values, `Reading.deciding`, the worse one among them: alarm plan §2.1, cross review F2), each moved by its
    parameter's deadband both ways, through the same rows and the same judgement (evaluate.judge), and through its other
    oxygen unit where it was judged so: a level clears only when every one of them is clear even so. Never a second
    rule."""
    found = []
    for each in (reading, *(other for other in reading.deciding if other.value is not None)):
        found += _moved(each, rules) + (_moved(each.through, rules) if each.through is not None else [])
    return worst(found) if found else reading.judged


def seen_at(reading, now):
    """When a value counts as taken for an alarm's timers: its own time, or the pass's when it is stamped ahead of the
    server's clock (cross review F1). The read layer lets a value up to the ingest contract's hour ahead decide the status
    (farm/water/read.py worst_fresh), so its alarm runs from the moment the card shows it, never from a moment to come:
    a device whose clock is fast never delays or suppresses an alarm."""
    return min(reading.at, now)


def clear_evidence(reading, severity, rules, last_bad_at, now):
    """Whether this pass's reading says the level is over: fresh, taken after the last value that held it (an older value
    that is the newest again, its bad successor voided or its probe taken out, says nothing new: alarm plan, defect 4),
    and clear of it by the deadband. Times are `seen_at`, the same clamp as the raise."""
    decider = reading.worse or reading
    return (reading.status != Status.STALE and (last_bad_at is None or seen_at(decider, now) > last_bad_at)
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


@dataclass
class Subject:
    """What one pass says of one alarm subject: whether its condition holds, whether the evidence clears it (a bool, or
    a function of the subject's row: its last bad value's time is in it), the time the on-delay runs from (`bad_at`), its severity, the alarm's spec when it is raised (`spec()`), and why it clears: `cause`
    when the evidence clears it, `structural` (a cause) when it is no longer judged at all."""
    key: str
    holds: bool
    clear_ok: bool
    bad_at: object
    severity: str
    spec: object
    cause: str = ClearCause.RETURNED
    structural: str = ''


def settle(subjects, now, rules):
    """Moves every subject one pass on its row (`advance`), set-based (alarm plan, defect 7): one read of the rows, and the
    alarms, clearances, log entries and rows written in one statement each. Returns (opened, cleared)."""
    states = _states([subject.key for subject in subjects])
    raises, clears, before = [], [], {}
    for subject in subjects:
        state = states.setdefault(subject.key, AlarmSubjectState(key=subject.key))
        before[subject.key] = _snapshot(state)
        clear_ok = subject.clear_ok(state) if callable(subject.clear_ok) else subject.clear_ok
        done = advance(state, subject.holds, clear_ok, subject.bad_at, subject.severity, rules, now,
                       structural=bool(subject.structural))
        if done.raise_alarm:
            raises.append((subject.key, subject.spec()))
        elif done.clear_cause is not None:
            clears.append((state, subject.structural or subject.cause))
    services.clear_many([(state.open_alarm, now, cause) for state, cause in clears])
    for state, _cause in clears:
        state.open_alarm, state.clear_since = None, None
    for key, alarm in services.raise_many(raises).items():
        states[key].open_alarm, states[key].pending_since = alarm, None
    changed = [state for key, state in states.items() if key in before and _snapshot(state) != before[key]]
    AlarmSubjectState.objects.bulk_create(changed, update_conflicts=True, unique_fields=['key'],
                                          update_fields=STATE_FIELDS)
    return len(raises), len(clears)


def system_subject(name, holds, severity, summary, now, *, parameter=None, where=None):
    """A subject of the alarm system itself (source 'system', subject `system:<name>`, the alarm's `parameter` what it is
    about, the name by default): raised while `holds`, restored once it no longer does, for the severity's off-delay.
    `where` ({site, production_department}) is set where one applies, so a site's recipient rules reach it
    (alarms/routing.py); without it the alarm is the whole farm's."""
    parameter = parameter or name
    return Subject(f'system:{name}', holds, not holds, now, severity, lambda: {
        'at': now, 'severity': severity, 'summary': summary, 'source': Source.SYSTEM, 'parameter': parameter,
        **(where or {})}, cause=ClearCause.RESTORED)


def _text(message, **values):
    """A system alarm's summary, in English at rest."""
    with audit.source_language():
        return str(message) % values if values else str(message)


SENSORS_FAILED = 'sensors_failed'
ALARM_RULES = 'alarm_rules'
UNIT_UNEVALUATED = 'unit_unevaluated'
STEP_FAILED = 'step_failed'


def _unit_where(unit):
    return {'site': unit.production_department.site, 'production_department': unit.production_department}


def _read(units, now):
    """({unit id: PointWater}, [the units that could not be read]): one read for all of them; when it fails, each unit on
    its own (a savepoint each), so one unit that cannot be read never hides the others (cross review F3)."""
    try:
        with transaction.atomic():
            return water_read.unit_water(units, now), []
    except Exception:
        logger.exception('The water of the units could not be read at once; each unit is read on its own.')
    found, failed = {}, []
    for unit in units:
        try:
            with transaction.atomic():
                found.update(water_read.unit_water([unit], now))
        except Exception:
            logger.exception('The water of unit %s could not be read.', unit)
            failed.append(unit)
    return found, failed


def water_key(unit_id, slot, severity):
    """The subject of a unit's quantity at a level: the unit's, never its point's (cross review F7)."""
    return f'water:unit:{unit_id}:{slot}:{severity}'


UNIT_PREFIXES = ('water:unit:', 'system:unit:')


def _removed(units, now):
    """The subjects with an alarm open whose unit is no longer there (deleted): no value will ever end them, so they end
    at once, with the cause "unit removed" (one query)."""
    there = {str(unit.pk) for unit in units}
    found = []
    query = Q()
    for prefix in UNIT_PREFIXES:
        query |= Q(key__startswith=prefix)
    for key, severity in AlarmSubjectState.objects.filter(query, open_alarm__isnull=False).values_list(
            'key', 'open_alarm__severity'):
        if key.split(':')[2] not in there:
            found.append(Subject(key, False, False, now, severity, None, structural=ClearCause.UNIT_REMOVED))
    return found


def _water_subjects(found, failed, rules, now):
    """The water subjects of one unit's PointWater: per quantity, a warning and a critical level."""
    subjects = []
    for slot, reading in _slots(found).items():
        for severity in HOLDS:
            subjects.append(Subject(
                water_key(found.point.unit_id, slot, severity), reading.judged in HOLDS[severity],
                lambda state, severity=severity, reading=reading: not failed and clear_evidence(
                    reading, severity, rules, state.last_bad_at, now),
                seen_at(reading.worse or reading, now), severity,
                lambda point=found.point, severity=severity, reading=reading: {
                    'at': now, 'severity': severity, 'summary': _summary(point, reading), 'source': Source.WATER_LIMIT,
                    'point': point, 'parameter': reading.code, **_where(point)},
                structural=ClearCause.STRUCTURAL if reading.judged in UNJUDGED else ''))
    return subjects


def water(now, rules):
    """Raises and clears the water limits' levels at `now` (alarms.rules `rules`), and the system alarms of live sources
    that cannot be read and of units that cannot be evaluated: (opened, cleared). While the live sources cannot be read
    nothing clears: a sample alone must never end an alarm a sensor raised (alarm plan, defect 3). A unit that cannot be
    read or evaluated is its own critical system alarm, on its site, and every other unit goes on (cross review F3); its
    water alarms stay as they are (nothing clears them blind). Set-based: one read of the water, one of the subjects'
    rows, and the alarms, clearances, log entries and rows written in one statement each, however many units alarm at
    once (defect 7)."""
    # The subjects are the live units, each through the point that stands for it (its middle point: A9.1, never an inlet);
    # a depth point's or the loop's value reaches it as the unit's own worst fresh value, judged for its fish. One read.
    units = list(Tank.objects.select_related('production_department__site'))
    found_water, unreadable = _read(units, now)
    failed = any(found.sensors_failed for found in found_water.values())
    subjects, unevaluated = [], {unit.pk for unit in unreadable}
    for unit in units:
        found = found_water.get(unit.pk)
        if found is None or found.point is None or unit.pk in unevaluated:
            continue
        try:
            subjects += _water_subjects(found, failed, rules, now)
        except Exception:
            logger.exception('The water of unit %s could not be evaluated.', unit)
            unevaluated.add(unit.pk)
    subjects.append(system_subject(SENSORS_FAILED, failed, Severity.CRITICAL, _text(_(
        'The live water values (the sensors) cannot be read: alarms are not cleared until they can.')), now))
    subjects += [system_subject(f'unit:{unit.pk}:{UNIT_UNEVALUATED}', unit.pk in unevaluated, Severity.CRITICAL, _text(_(
        '%(unit)s: the water could not be evaluated; its alarms are neither raised nor cleared until it can.'),
        unit=unit.code), now, parameter=UNIT_UNEVALUATED, where=_unit_where(unit)) for unit in units]
    # A unit whose water is read no more (no point to read it at, the parameter gone) keeps its alarm open: nothing says it
    # is over. A unit removed has nothing left to judge: its alarms end (cause "unit removed").
    return settle(subjects + _removed(units, now), now, rules)


def supervise(now, rules, steps, failed_steps):
    """The alarm system's own subjects at the end of a pass (EEMUA 191: the alarm system supervises itself):
    - a step of the pass that failed (`steps`, their names; `failed_steps`, those that failed) is a critical system alarm
      from the pass it fails in until it passes again (cross review F3);
    - a severity whose rule row is missing (alarms.rules: the safest values stand in, cross review F6) is a critical
      configuration alarm until the row is back.
    (opened, cleared)"""
    missing = ', '.join(sorted(rules.missing))
    subjects = [system_subject(ALARM_RULES, bool(rules.missing), Severity.CRITICAL, _text(_(
        'The alarm rules are incomplete (no rule row for: %(severities)s): the safest values are used until the rows '
        'are restored.'), severities=missing or '-'), now)]
    subjects += [system_subject(f'step:{name.replace(" ", "_")}', name in failed_steps, Severity.CRITICAL, _text(_(
        'The alarm step "%(step)s" failed: what it does (raising, clearing, notifying or sending alarms) is not done '
        'until it passes again.'), step=name), now, parameter=STEP_FAILED) for name in steps]
    return settle(subjects, now, rules)

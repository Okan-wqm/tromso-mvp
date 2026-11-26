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
  WHICH VALUE CAN END A LEVEL (the verification of FIX3, F3-1 and F3-7; one rule, `clear_evidence` over the row's
  `own_held`). The unit's own value is one measured at the unit's own points; another value is one of the rest of its
  water: its system's loop standing in for it (read.latest), or another fresh value that judged it worse
  (read.worst_fresh, `worse`).
  A level remembers whether the unit's own value held it (`own_held`: set while its own value holds it, forgotten once
  its own value is judged clear of it, or when no alarm is open and nothing holds).
  - Raised by the unit's own value: only the unit's own evidence ends it. An own full sample clear of it (newer than
    the last bad value, and every other fresh value clear too) ends it "returned"; an own sample that gives no value (a
    TAN without its pH), another point's OK value, nothing new, or the bad sample voided (an older value newest again,
    defect 4) end nothing: the unit's own NH₃ is not known to be over.
  - Raised by another value (its own value clear or value-less): the values that judge it end it. Another point's newer
    OK value ends it "returned" when its own value is clear or value-less (F3-1); an own full OK sample ends it only
    when the other values are clear too (worst_fresh keeps a fresh bad one); an own value-less sample changes nothing;
    nothing new ends nothing; the bad sample voided ends it only where a value taken after it is clear (an older value
    newest again is no evidence, defect 4).
  - Either way: another bad value holds it (worst_fresh); a refused value is never evidence; a value that only goes
    stale never ends it; the limit removed or no fish end it with that cause (`_unjudged`).
  - The unit's own bad value gone stale while its system's value stands in (decision of 2026-11-19 on F3-9): the reading
    keeps that status (read.last_own), so the page, the card and the level agree, and all say "last own value …, no
    recent data: measure this unit"; only the unit's own fresh value ends it.
Where an alarm is (its site, its production department) is set when it opens, for the recipient rules."""
import logging
from dataclasses import dataclass
from functools import partial

from django.db import transaction
from django.db.models import Q
from django.utils.translation import gettext as _

from core import audit
from farm.models import Tank, WaterLimit
from farm.stock import read as stock_read
from farm.templatetags.water import figure_past
from farm.models.water_point import site_of
from farm.water import judge as water_judge, messages as water_messages, parameters, read as water_read
from farm.water.read import LIMITED, OXYGEN
from farm.water.evaluate import ALERTS, RANK, Status, judge, worst
from sensors import alarms as sensor_alarms, clock as sensor_clock
from sensors.models import AlarmEvent, Binding, Channel, Device

from . import clock, services
from .models import Alarm, AlarmSubjectState, ClearCause, Severity, Source

logger = logging.getLogger(__name__)
SUMMARY_LENGTH = Alarm._meta.get_field('summary').max_length


# ---- the sensor rules ------------------------------------------------------------------------------------------------
def _department_of(channel, at):
    """The production department of the place the channel was bound to at `at`, or None."""
    return _department_at(Binding.all_objects.filter(channel=channel, valid_from__lte=at)
                          .filter(Q(valid_to__isnull=True) | Q(valid_to__gt=at))
                          .select_related(*sensor_alarms.PLACE_RELATED).first())


def _department_at(binding):
    """The production department of the place a binding holds its channel at (None without one), from the binding with
    its place loaded (sensors.alarms.PLACE_RELATED): no query of its own."""
    if binding is None:
        return None
    place = binding.point.owner if binding.point_id else binding.system or binding.equipment
    return getattr(place, 'production_department', None)


def mirror(event):
    """The alarm of a sensor rule's event, opened at the event's moment where its channel's device is (and cleared at once
    when the event has closed already). It says the rule, the channel and the place it was bound to ('pH (NBS scale): No
    fresh value · PROBE-1 › PH: S-01 › Middle'), in English at rest: a rule of every channel of a quantity (a default
    "No fresh value") names no channel itself."""
    channel = Channel.all_objects.select_related('device__site').filter(channel_no=event.channel_no).first()
    with audit.source_language():
        where = (str(event.binding) if event.binding is not None
                 else channel.device.code if channel is not None else f'#{event.channel_no}')
        summary = f'{event.rule} · {where}'[:SUMMARY_LENGTH]
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
                                       sensor_event__closed_at__isnull=False).select_related('sensor_event__rule')):
        services.clear_many([(alarm, alarm.sensor_event.closed_at, ClearCause.EVENT_CLOSED,
                              _rule_off(alarm.sensor_event.rule))])
        cleared += 1
    return opened, cleared


def _rule_off(rule):
    """{label: text} the clearance's log entry says of a rule switched off or deleted (its event closed because no pass
    visits it any more: sensors/alarms.py `close_switched_off`), in English at rest; None for an active rule."""
    if rule.is_active and not rule.is_deleted:
        return None
    with audit.source_language():
        said = {str(_('Alarm rule')): f'{rule} · {_("Deleted") if rule.is_deleted else _("Inactive")}'}
        if rule.off_reason:
            said[str(_('Why it is switched off'))] = rule.off_reason
        return said


# ---- the water limits ------------------------------------------------------------------------------------------------
# What each level holds on: the judgements that keep a unit's parameter at that level.
HOLDS = {Severity.WARNING: ALERTS, Severity.CRITICAL: (Status.CRITICAL,)}
UNJUDGED = (Status.NO_LIMIT, Status.NOT_MEASURED)


def _summary(point, reading, unit=None):
    """'T-01 · Middle: pH (NBS scale) 5.50 (critical)', in English at rest. A reading without a value of its own that
    another fresh value judged (`decided`) names that value; a refused one judged on its limits' basis says "at least"
    before it, as the page does; one whose status the unit's own stale value keeps says "last own value …, measure this
    unit" (read.last_own)."""
    owner = point.owner if point is not None else None
    with audit.source_language():
        label = str(parameters.get(reading.code).label)
        status = str(Status(reading.judged).label).lower()
        shown = reading if reading.value is not None else reading.worse
        value = figure_past(shown) or shown.value        # a value judged past a bound says the decimals that prove it
        if reading.value is not None and reading.refused:      # its limits' basis alone, as the page says it (F3-5)
            value = _('at least %(value)s') % {'value': value}
        if point is None:                       # a unit read at its system's probes, no point anywhere (M1)
            said = f'{unit.code}, from its system: {label} {value} ({status})'
        else:
            said = f'{getattr(owner, "code", owner)} · {point.name}: {label} {value} ({status})'
            if unit is not None and getattr(point, 'unit_id', None) != unit.pk:   # a unit without a point: its system's
                said = f'{unit.code}, from {said}'
        if reading.last_own is not None:        # the unit's own stale value keeps the level (read.last_own, F3-9)
            said = f'{said}; {water_messages.last_own(reading.last_own)}'
        return said[:SUMMARY_LENGTH]


def _where(point):
    owner = point.owner
    return {'site': site_of(point), 'production_department': getattr(owner, 'production_department', None)}


def slot_of(code):
    """The quantity a code is: the dissolved oxygen is one, in mg/L or in % (read.OXYGEN); every other code its own."""
    return OXYGEN if code in parameters.SAME_QUANTITY else code


def decided(reading):
    """Whether a reading takes part in the limit levels: it has a value (a refused NH₃ judged on its limits' basis
    alone has one, farm/water/read.py `_ammonia_on_basis`), or another fresh value judged it (`Reading.worse`,
    read.worst_fresh): the judgement the water page shows is the one the alarm raises, never a lower one (the re-check
    of 2026-11-18, RC-2: a unit whose own NH₃ the core refused, judged critical by its loop's fresh sample on the page,
    had only the "cannot be evaluated" warning), or it has other fresh values of its water that take part in its status
    (`Reading.deciding`): its levels stay judged by them, so a level another value raised ends when that water
    recovers (the verification of FIX3, F3-1: T-02's own TAN without a pH, critical by its loop's sample, stayed
    critical after the loop's next sample was OK, while its page said "not measured")."""
    return reading.value is not None or reading.worse is not None or bool(known(reading))


def known(reading):
    """The values that take part in a value-less reading's status: its place's other fresh values that have one."""
    return [each for each in reading.deciding if each.value is not None]


def _slots(found):
    """{slot: the reading that decides it}: per quantity of a unit's water, its limited reading judged worst (`decided`
    ones only: a reading without a value and no other value of its water raises nothing here; a refused one is the
    alarm system's warning too, `_refused_subjects`)."""
    slots = {}
    for reading in found.readings.values():
        if reading.code in LIMITED and decided(reading):
            slot = slot_of(reading.code)
            if slot not in slots or RANK[reading.judged] < RANK[slots[slot].judged]:
                slots[slot] = reading
    return slots


def _moved(reading, rules):
    """The judgements of a reading's value moved by its parameter's deadband both ways, through its own rows: the value
    the limits judge (`Reading.judged_value`, unrounded where it was worked out; the audit of 2026-11-19, F3)."""
    band = rules.deadband(reading.code)
    value = reading.judged_value
    return [judge(moved, row) for row in reading.limits for moved in (value - band, value + band)]


def judged_clear(reading, rules):
    """The worst judgement of every value that takes part in `reading`'s status (the value A9 chose and the place's other
    fresh values, `Reading.deciding`, the worse one among them: alarm plan §2.1, cross review F2), each moved by its
    parameter's deadband both ways, through the same rows and the same judgement (evaluate.judge), and through its other
    oxygen unit where it was judged so: a level clears only when every one of them is clear even so. Never a second
    rule."""
    found = []
    for each in (each for each in (reading, *reading.deciding) if each.value is not None):
        found += _moved(each, rules) + (_moved(each.through, rules) if each.through is not None else [])
    return worst(found) if found else reading.judged


def seen_at(reading, now):
    """When a value counts as taken for an alarm's timers: its own time, or the pass's when it is stamped ahead of the
    server's clock (cross review F1). The read layer lets a value up to the ingest contract's hour ahead decide the status
    (farm/water/read.py worst_fresh), so its alarm runs from the moment the card shows it, never from a moment to come:
    a device whose clock is fast never delays or suppresses an alarm."""
    return min(reading.at, now)


def clear_evidence(reading, severity, rules, last_bad_at, now, own_held=False, unit_id=None):
    """Whether this pass's reading says the level is over: fresh, taken after the last value that held it (an older value
    that is the newest again, its bad successor voided or its probe taken out, says nothing new: alarm plan, defect 4),
    and clear of it by the deadband. Times are `seen_at`, the same clamp as the raise. A value the chemistry core refused
    to work out (`Reading.refused`: no value, or its limits' basis alone, a value the judged one is at least) says
    nothing of the level being over. A reading without a value of its own is judged by its water's other values
    (`known`), their newest the one taken after the last bad value. A level the unit's own value holds (`own_held`, the
    rule at the top: F3-7) takes the unit's own value as evidence and nothing else."""
    if own_held and not (reading.value is not None and own(reading, unit_id)):
        return False                    # raised by the unit's own value: only its own value says it is over
    decider = reading.worse or (reading if reading.value is not None else max(known(reading), key=lambda each: each.at,
                                                                              default=None))
    if decider is None:
        return False
    if reading.parameter.inputs:
        # A worked-out value: THE judge says whether it may end a level (farm/water/judge.py `clears`: evidence fresh now,
        # measured strictly after the last bad value; a tie never clears).
        sample = decider.sample.sample
        record = water_judge.Record(
            key=decider, point=None, tier=0, measured_at=seen_at(decider, now),
            created_at=sample.created_at if sample is not None else decider.at, id=str(sample.pk) if sample else '',
            value=decider.value is not None, refused=bool(decider.refused or reading.refused),
            fresh_at_own_time=decider.fresh_until > decider.at, fresh_now=reading.status != Status.STALE)
        return water_judge.clears(record, last_bad_at) and judged_clear(reading, rules) not in HOLDS[severity]
    return (reading.status != Status.STALE and not reading.refused
            and (last_bad_at is None or seen_at(decider, now) > last_bad_at)
            and judged_clear(reading, rules) not in HOLDS[severity])


@dataclass
class Step:
    """What a subject's row says after one pass: an alarm to raise (with what makes it), or one to clear (with why)."""
    raise_alarm: bool = False
    clear_cause: str = None


def advance(state, holds, clear_ok, bad_at, severity, rules, now, structural=False, on_delay=None):
    """One pass of a subject's lifecycle on its row (AlarmSubjectState), the one rule every subject follows: while its
    condition holds, the clear timer stops, the last bad value's time is kept and, without an open alarm, the on-delay runs
    from the first offending value's time (`bad_at`); once it is over, an open alarm clears after the off-delay while the
    evidence clears it (`clear_ok`), at once when the subject is no longer judged (`structural`). `on_delay`, when given,
    stands for the severity's (a device clock behind: its window). Returns the Step."""
    step = Step()
    if holds:
        state.clear_since = None
        state.last_bad_at = max(filter(None, (state.last_bad_at, bad_at)))
        if state.open_alarm_id is None:
            state.pending_since = state.pending_since or bad_at
            step.raise_alarm = now - state.pending_since >= (on_delay if on_delay is not None
                                                             else rules.on_delay(severity))
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


STATE_FIELDS = ['open_alarm', 'pending_since', 'clear_since', 'last_bad_at', 'own_held', 'updated_at']


def _states(keys):
    return {state.key: state for state in AlarmSubjectState.objects.select_for_update(of=('self',)).select_related(
        'open_alarm').filter(key__in=keys)}


def _snapshot(state):
    return state.open_alarm_id, state.pending_since, state.clear_since, state.last_bad_at, state.own_held


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
    detail: object = None          # () -> {label: text} the clearance's log entry adds (what changed), or None
    on_delay: object = None        # a timedelta standing for the severity's on-delay (a device clock behind), or None
    note: object = None            # (row) -> None: what the subject remembers on its row this pass, before its evidence


def settle(subjects, now, rules):
    """Moves every subject one pass on its row (`advance`), set-based (alarm plan, defect 7): one read of the rows, and the
    alarms, clearances, log entries and rows written in one statement each. Returns (opened, cleared)."""
    states = _states([subject.key for subject in subjects])
    raises, clears, before = [], [], {}
    for subject in subjects:
        state = states.setdefault(subject.key, AlarmSubjectState(key=subject.key))
        before[subject.key] = _snapshot(state)
        if subject.note is not None:
            subject.note(state)
        clear_ok = subject.clear_ok(state) if callable(subject.clear_ok) else subject.clear_ok
        done = advance(state, subject.holds, clear_ok, subject.bad_at, subject.severity, rules, now,
                       structural=bool(subject.structural), on_delay=subject.on_delay)
        if done.raise_alarm:
            raises.append((subject.key, subject.spec()))
        elif done.clear_cause is not None:
            clears.append((state, subject.structural or subject.cause, subject.detail))
    services.clear_many([(state.open_alarm, now, cause, detail() if detail else None) for state, cause, detail in clears])
    for state, _cause, _detail in clears:
        state.open_alarm, state.clear_since, state.own_held = None, None, False
    for key, alarm in services.raise_many(raises).items():
        states[key].open_alarm, states[key].pending_since = alarm, None
    changed = [state for key, state in states.items() if key in before and _snapshot(state) != before[key]]
    services.save_states(changed, STATE_FIELDS)
    return len(raises), len(clears)


def system_subject(name, holds, severity, summary, now, *, parameter=None, where=None, bad_at=None, clear_ok=None):
    """A subject of the alarm system itself (source 'system', subject `system:<name>`, the alarm's `parameter` what it is
    about, the name by default): raised while `holds`, restored once it no longer does, for the severity's off-delay.
    `where` ({site, production_department}) is set where one applies, so a site's recipient rules reach it
    (alarms/routing.py); without it the alarm is the whole farm's. `bad_at`: the time the on-delay runs from (the pass's
    by default); `clear_ok`: whether this pass may say it is over (by default whenever it does not hold; False where
    the pass could not look, so nothing ends blind)."""
    parameter = parameter or name
    return Subject(f'system:{name}', holds, not holds if clear_ok is None else clear_ok, bad_at or now, severity, lambda: {
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
ALARMS_UNCHECKED = 'alarms_unchecked'
UNDELIVERABLE = 'notifications_undeliverable'
NO_WATER_POINT = 'no_water_point'
VALUE_UNEVALUATED = 'value_unevaluated'
NO_FRESH_OXYGEN = 'no_fresh_oxygen'
OXYGEN_PROBE_SILENT = 'oxygen_probe_silent'
# Every value the limits judge: each may come without a number for a stated reason (read.Reading.refused): a worked-out
# one the chemistry core refused (the NH₃), a sensor pH that could not be put on the NBS scale (the water-chemistry
# audit of 2026-11-19, F1 and its review's M1: it was silent), and any value a later refusal comes to. A value that is
# never refused costs a subject that never holds (no row is written for it).
REFUSABLE = tuple(parameter.code for parameter in parameters.LIMITED)
DEVICE_CLOCK = 'device_clock'


def _read_nowhere(found):
    """Whether a unit's water is read from nowhere: no water at all, or no point of its own and no system to read it at
    (read.PointWater: `point` and `standing_place` both None). The one place it is decided: what the "no active sampling
    point" warning is about (`water`)."""
    return found is None or (found.point is None and found.standing_place is None)


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


def _water_subjects(unit, found, failed, rules, now):
    """The water subjects of one unit's PointWater: per quantity, a warning and a critical level. A unit with no point of
    its own is read at its system (read.latest `units`): its levels are at the loop point, or, where the system has none,
    without a point (alarms 0022), always on the unit's own site and department and said for the unit: a card at a
    level has its alarm at that level (review 5 of the branch, M1)."""
    subjects, unit_id = [], unit.pk
    point = found.point or found.system_point
    where = _where(point) if found.point is not None else _unit_where(unit)
    for slot, reading in _slots(found).items():
        for severity in HOLDS:
            subjects.append(Subject(
                water_key(unit_id, slot, severity), reading.judged in HOLDS[severity],
                lambda state, severity=severity, reading=reading: not failed and clear_evidence(
                    reading, severity, rules, state.last_bad_at, now, own_held=state.own_held, unit_id=unit_id),
                seen_at(reading.worse or reading, now), severity,
                lambda severity=severity, reading=reading: {
                    'at': now, 'severity': severity, 'summary': _summary(point, reading, unit),
                    'source': Source.WATER_LIMIT, 'point': point, 'parameter': reading.code, **where},
                **_unjudged(reading), note=partial(_note_own, reading, severity, rules, unit_id)))
    return subjects


def own(reading, unit_id):
    """Whether a value was measured at the unit's own points (the rule at the top)."""
    return reading.point is not None and getattr(reading.point, 'unit_id', None) == unit_id


def _note_own(reading, severity, rules, unit_id, state):
    """What a level remembers of who holds it (the rule at the top: `own_held`): the unit's own value holding it sets it;
    the unit's own value judged clear of it (by the deadband, as `judged_clear`) forgets it, and so does a level with no
    alarm open that nothing holds. An own sample that gives no value, or a refused one inside the limits, says nothing."""
    holds = reading.judged in HOLDS[severity]
    decider = reading.worse or reading
    if holds and decider.value is not None and own(decider, unit_id):
        state.own_held = True
    elif not holds and state.open_alarm_id is None:
        state.own_held = False
    elif own(reading, unit_id) and reading.value is not None and not reading.refused and worst(
            _moved(reading, rules) + (_moved(reading.through, rules) if reading.through is not None else [])
    ) not in HOLDS[severity]:
        state.own_held = False


def _unjudged(reading):
    """Why a reading's levels are no longer judged, when they are not: the fish have no limit row for it any more (a limit
    removed: the clearance names the row and who removed it, cross review F12), or there are no fish. A reading without a
    value of its own is judged through its water's other values (`known`): no longer judged only when none of them is
    (its own "not measured" is no cause: F3-1). A refused one without a value says it itself: no limit row judged it."""
    if reading.value is None and not reading.refused:
        judged_by = known(reading)
        if not judged_by or any(each.judged not in UNJUDGED for each in judged_by):
            return {}
        reading = judged_by[0]
    if reading.judged not in UNJUDGED:
        return {}
    if reading.uncovered:
        return {'structural': ClearCause.LIMIT_REMOVED, 'detail': lambda: _removed_limit(reading)}
    return {'structural': ClearCause.STRUCTURAL}


def _removed_limit(reading):
    """{label: the water limit row of the reading's parameter last removed for the fish it no longer judges, who removed
    it and when}, in English at rest."""
    row = (WaterLimit.all_objects.filter(parameter=reading.code, species_id__in=reading.uncovered, is_deleted=True)
           .select_related('species', 'deleted_by').order_by('-deleted_at').first())
    with audit.source_language():
        label = str(_('Limit removed'))
        if row is None:
            return {label: str(_('No removed limit row found: the fish have no limit row for it.'))}
        who = row.deleted_by.get_username() if row.deleted_by else '-'
        return {label: f'#{row.pk} ({row.species}, {row.get_parameter_display()}, {row.get_water_type_display()}) '
                       f'by {who} {row.deleted_at.isoformat() if row.deleted_at else ""}'.strip()}


def _unevaluated_since(reading, now):
    """When a value that cannot be evaluated starts its warning's on-delay: its own time (`seen_at`). A sensor pH measured
    before its channel's pH scale was changed (read.SensorPh.since; an NH₃ worked out with it too) was not refused
    before the change, and the probe's next value, due while that one would still be fresh, is read on the new scale:
    so it starts once that value would have gone stale, never before the change, and None (it does not hold) until
    then. A change of scale does not raise and end a warning in the minute the next value takes (the review of the
    water-chemistry audit, M1); a probe that sends nothing after it is warned of as soon as its value would be stale."""
    ph = reading.sample.ph
    if ph is None or ph.since is None or reading.at >= ph.since:
        return seen_at(reading, now)
    if reading.fresh(now):
        return None
    stale_at = reading.fresh_until
    return min(max(ph.since, stale_at), now)


def _refused_subjects(units, found_water, unevaluated, failed, now):
    """A value the limits would judge that comes without a number for a stated reason (read.Reading.unevaluated: a
    conductivity past the Davies range makes the NH₃ of a TAN sample one; a sensor pH on the total scale without a
    temperature of its moment makes the pH one) is never silent (the verification of 2026-11-18, V-A; the review of the
    water-chemistry audit, M1): per unit and value the limits judge (`REFUSABLE`), a warning of the alarm system on the
    unit's site, "<unit>: <value> cannot be evaluated: <the reason>", its on-delay counted from the value's time as a
    limit's is (for a sensor pH from before its channel's scale changed, once it would have gone stale:
    `_unevaluated_since`). It ends on
    evidence only, with the cause that is true: "restored" once the value is worked out again (the limit's own levels
    then judge it), "the water limit was removed" or "no fish in the unit any more" once nothing judges it (`_unjudged`,
    the limit levels' own rule). A later sample that gives no value (a TAN without its pH) or the refused sample leaving
    the window (`read.WINDOW`) says nothing of the water, so it stays open, as a limit alarm does (the re-check of
    2026-11-18, RC-4: both ended it "restored"); a pass that could not read the unit or the live values ends nothing.
    Beside it the value's own limit levels judge what is known:
    its limits' basis, which needs no conductivity and which the judged value is never below (a critical past the
    critical limit, the re-check of 2026-11-18, RC-3), or another fresh value of the place (`decided`); an open one is
    never cleared by a refused value (`clear_evidence`)."""
    subjects = []
    for unit in units:
        found = found_water.get(unit.pk)
        looked = found is not None and found.for_unit and unit.pk not in unevaluated
        for code in REFUSABLE:
            reading = found.get(code) if looked else None
            if looked and (reading is None or not reading.unevaluated) and code in found.refused_newer:
                # An own point's newer sample the core refused, behind the value shown (read.PointWater.refused_newer):
                # it cannot be evaluated, and says so until a worked-out value there is newer.
                reading = found.refused_newer[code]
            since = _unevaluated_since(reading, now) if reading is not None and reading.unevaluated else None
            holds = since is not None
            summary = ''
            if holds:
                with audit.source_language():
                    summary = f'{unit.code}: {water_messages.unevaluated(reading)}'[:SUMMARY_LENGTH]
            worked_out = reading is not None and reading.value is not None and not reading.refused
            subject = system_subject(
                f'unit:{unit.pk}:{VALUE_UNEVALUATED}:{code}', holds, Severity.WARNING, summary, now, parameter=code,
                where=_unit_where(unit), bad_at=since,
                clear_ok=looked and not failed and worked_out)
            if reading is not None and reading.refused and not holds:      # refused, and nothing judges it any more
                unjudged = _unjudged(reading)
                subject.structural, subject.detail = unjudged.get('structural', ''), unjudged.get('detail')
            subjects.append(subject)
    return subjects


def _silent_subjects(units, found_water, unevaluated, failed, now, oxygen_levels=frozenset(), oxygen_pass=None):
    """Owner decision of 2026-11-23: a unit that holds fish now whose oxygen has no fresh value (read.PointWater.silent_oxygen:
    a typed sample grown old, a unit without sensors, a unit with no point to read its water at; mg/L and % being one
    quantity) is a CRITICAL alarm of the alarm system, one per unit (subject `system:unit:<unit>:no_fresh_oxygen`), on
    the unit's site: "<unit>: Dissolved oxygen (mg/L O₂): no recent data, 3 hours old". Its on-delay runs from when the
    oxygen stopped being fresh (read.Silence.since). It stands aside, so one problem is one alarm:
    - where an oxygen probe is bound to the unit's water (its own points or its system's) and a "No fresh value" rule
      that raises a critical at the freshness covers it (sensors.alarms.watched; never a warning or delayed rule, nor
      a default standing aside for one: review 6 of the branch, M1): that rule's alarm says it;
    - while the CRITICAL level of the water limits holds or is open on the unit's oxygen (`oxygen_levels`: an old
      oxygen value past its critical limit keeps that level, an alarm of its own; review 2 of the branch, R4 p5). An old
      value only past its warning limit is a warning level, so the critical stays here (review 3, N1).
    It ends "restored" once the oxygen is fresh again (or something else says it), "no fish in the unit any more" once
    the unit holds none, and never on a pass that could not read the unit or the live values."""
    oxygen = (parameters.OXYGEN_MG_L, parameters.OXYGEN_PCT)
    watched = sensor_alarms.watched(oxygen, now)
    subjects = []
    for unit in units:
        found = found_water.get(unit.pk)
        looked = found is not None and unit.pk not in unevaluated
        silence = found.silent_oxygen if looked else None
        holds = silence is not None and not (found.targets & watched) and str(unit.pk) not in oxygen_levels
        summary = ''
        if holds:
            with audit.source_language():
                summary = f'{unit.code}: {found.why_silent[0]}'[:SUMMARY_LENGTH]
        subject = system_subject(
            f'unit:{unit.pk}:{NO_FRESH_OXYGEN}', holds, Severity.CRITICAL, summary, now,
            parameter=parameters.OXYGEN_MG_L, where=_unit_where(unit), bad_at=silence.since if holds else None,
            clear_ok=looked and not failed and not holds)
        if looked and not found.holds_fish:
            subject.structural = ClearCause.STRUCTURAL
        subjects.append(subject)
    return subjects + _probe_subjects(oxygen_pass or sensor_alarms.OxygenPass(now), failed, now)


PROBE_PREFIX = f'{OXYGEN_PROBE_SILENT}:'


def _probe_subjects(oxygen_pass, failed, now):
    """A WARNING per silent oxygen probe (subject `system:oxygen_probe_silent:<channel>`, on its device's site and the
    department of its place): a default rule's probe that sent no fresh value at its place while the oxygen of the units
    holding fish there is fresh all the same (a typed sample, another probe: sensors.alarms.silent_probes,
    read.oxygen_known), which its default rule then leaves to this warning (review 2 of the branch, R3 p3: the card
    follows the fresh value): "PROBE-T › O2: T-02 › Middle: the oxygen probe is silent; the oxygen is measured otherwise
    (by hand or by another probe)". Every such probe, wherever it is bound: a unit's own point, its loop, an inlet or a
    piece of equipment no unit's water reads (review 3, N2). Once nothing else is fresh the rule's critical says it and
    this one ends "restored", as it does once the probe sends again, is moved or taken out (its open row is visited
    though the probe is no longer listed); never on a pass that could not read the live values."""
    probes, known = oxygen_pass.probes(), oxygen_pass.known()          # read once in the pass (`OxygenPass`)
    subjects, seen = [], set()
    for place, bindings in probes.items():
        for binding in bindings:
            channel = binding.channel
            seen.add(f'system:{PROBE_PREFIX}{channel.channel_no}')
            holds = place in known
            summary = ''
            if holds:
                summary = _text(_('%(probe)s: the oxygen probe is silent; the oxygen is measured otherwise (by hand or by '
                                  'another probe).'), probe=str(binding))[:SUMMARY_LENGTH]
            # where it is: read with the probes (sensors.alarms.silent_probes: the device's site, the place's
            # department), and only for a warning that holds (review 4 of the branch, L2)
            subjects.append(system_subject(
                f'{PROBE_PREFIX}{channel.channel_no}', holds, Severity.WARNING, summary, now,
                parameter=OXYGEN_PROBE_SILENT, clear_ok=not failed and not holds,
                where={'site': channel.device.site, 'production_department': _department_at(binding)} if holds else None))
    for key in AlarmSubjectState.objects.filter(key__startswith=f'system:{PROBE_PREFIX}',
                                                open_alarm__isnull=False).values_list('key', flat=True):
        if key not in seen:
            subjects.append(Subject(key, False, not failed, now, Severity.WARNING, None, cause=ClearCause.RESTORED))
    return subjects


def _oxygen_levels(subjects):
    """The ids of the units whose oxygen has the CRITICAL level of the water limits holding this pass or open
    (`water_key`): the alarm system's oxygen critical stands aside for it (`_silent_subjects`), never for a warning level
    (review 3 of the branch, N1)."""
    def unit_of(key):
        _water, _unit, unit_id, slot, severity = key.split(':')
        return unit_id if slot == OXYGEN and severity == Severity.CRITICAL else None
    levels = {subject.key: subject for subject in subjects if subject.key.startswith('water:unit:')
              and unit_of(subject.key) is not None}
    held = {unit_of(key) for key, subject in levels.items() if subject.holds}
    return held | {unit_of(key) for key in AlarmSubjectState.objects.filter(key__in=list(levels), open_alarm__isnull=False)
                   .values_list('key', flat=True)}


def water(now, rules, oxygen_pass=None):
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
    # A unit read nowhere: no point of its own and no system (read.latest `units`: its water stands at its system).
    unwatched = [unit.pk for unit in units if unit.pk not in unevaluated and _read_nowhere(found_water.get(unit.pk))]
    stocked = {pk for pk, fish in stock_read.unit_counts(unwatched).items() if fish > 0} if unwatched else set()
    for unit in units:
        found = found_water.get(unit.pk)
        if found is None or not found.for_unit or unit.pk in unevaluated:
            continue
        try:
            subjects += _water_subjects(unit, found, failed, rules, now)
        except Exception:
            logger.exception('The water of unit %s could not be evaluated.', unit)
            unevaluated.add(unit.pk)
    subjects.append(system_subject(SENSORS_FAILED, failed, Severity.CRITICAL, _text(_(
        'The live water values (the sensors) cannot be read: alarms are not cleared until they can.')), now))
    subjects += [system_subject(f'unit:{unit.pk}:{UNIT_UNEVALUATED}', unit.pk in unevaluated, Severity.CRITICAL, _text(_(
        '%(unit)s: the water could not be evaluated; its alarms are neither raised nor cleared until it can.'),
        unit=unit.code), now, parameter=UNIT_UNEVALUATED, where=_unit_where(unit)) for unit in units]
    # A unit with fish read nowhere (no point of its own, no system) has no water alarm at all: a configuration warning
    # of its own (cross review F16), but its oxygen then has no fresh value, the critical of `_silent_subjects` (review 2
    # of the branch, R2), so it holds only for a unit counted with fish that the water does not find holding any now. A
    # unit read at its system has its levels (review 5, M1): its note is the "From its system" its values say.
    stocked = {pk for pk in stocked if found_water.get(pk) is None or found_water[pk].silent_oxygen is None}
    subjects += [system_subject(f'unit:{unit.pk}:{NO_WATER_POINT}', unit.pk in stocked, Severity.WARNING, _text(_(
        '%(unit)s holds fish and has no active sampling point for its own water: its water raises no alarm until it '
        'has one.'), unit=unit.code), now, parameter=NO_WATER_POINT, where=_unit_where(unit)) for unit in units]
    subjects += _refused_subjects(units, found_water, unevaluated, failed, now)
    subjects += _silent_subjects(units, found_water, unevaluated, failed, now, _oxygen_levels(subjects), oxygen_pass)
    # A unit whose water is read no more (no point to read it at, the parameter gone) keeps its alarm open: nothing says it
    # is over. A unit removed has nothing left to judge: its alarms end (cause "unit removed").
    return settle(subjects + _removed(units, now), now, rules)


def device_clocks(now, rules):
    """Raises and clears each active device's clock levels at `now` (alarms/clock.py: a warning and a critical level per
    device, subject `clock:<device>:<severity>`, on the device's site): (opened, cleared). A device removed or deactivated
    ends its alarms (cause "device removed"). Set-based: one read of the devices, three of their skews, one of the rows."""
    devices = list(Device.objects.filter(is_active=True).select_related('site'))
    measured = sensor_clock.skews(now, [device.pk for device in devices])
    subjects = []
    for device in devices:
        skew = measured.get(device.pk)
        for severity in HOLDS:
            subjects.append(Subject(
                f'clock:{device.pk}:{severity}', skew is not None and clock.holds(skew, severity, rules),
                skew is not None and clock.clear(skew, severity, rules), now, severity,
                lambda device=device, skew=skew, severity=severity: {
                    'at': now, 'severity': severity, 'source': Source.SYSTEM, 'parameter': DEVICE_CLOCK,
                    'device': device, 'site': device.site,
                    'summary': _text(_('%(device)s: %(skew)s of the platform’s (its values still count; their alarms '
                                       'are never delayed).'), device=device.code, skew=_clock_text(skew))},
                on_delay=clock.on_delay(skew, severity, rules)))
    there = {str(device.pk) for device in devices}
    for key, severity in AlarmSubjectState.objects.filter(key__startswith='clock:', open_alarm__isnull=False).values_list(
            'key', 'open_alarm__severity'):
        if key.split(':')[1] not in there:
            subjects.append(Subject(key, False, False, now, severity, None, structural=ClearCause.DEVICE_REMOVED))
    return settle(subjects, now, rules)


def _clock_text(skew):
    with audit.source_language():
        return str(clock.describe(skew))


def _clock(moment):
    """A moment on the company's clock, as a summary at rest says it."""
    from core.templatetags.dates import on, zone_for
    return on(moment, zone_for(None)).strftime('%d.%m.%Y %H:%M')


def supervise(now, rules, steps, failed_steps, unchecked=None):
    """The alarm system's own subjects at the end of a pass (EEMUA 191: the alarm system supervises itself):
    - a step of the pass that failed (`steps`, their names; `failed_steps`, those that failed) is a critical system alarm
      from the pass it fails in until it passes again (cross review F3);
    - a severity whose rule row is missing (alarms.rules: the safest values stand in, cross review F6) is a critical
      configuration alarm until the row is back;
    - `unchecked` (from, to): the alarm worker's first pass after a stretch with no pass (it was stopped, killed or could
      not reach the database: alarms/worker.py) is a critical alarm of the alarm system, so the people are told what
      nobody checked; it clears after its off-delay on the passes that follow.
    (opened, cleared)"""
    missing = ', '.join(sorted(rules.missing))
    subjects = [system_subject(ALARM_RULES, bool(rules.missing), Severity.CRITICAL, _text(_(
        'The alarm rules are incomplete (no rule row for: %(severities)s): the safest values are used until the rows '
        'are restored.'), severities=missing or '-'), now)]
    from . import outbox
    stuck = outbox.stuck(rules, now)
    subjects.append(system_subject(UNDELIVERABLE, bool(stuck), Severity.CRITICAL, _text(_(
        '%(count)d critical notification(s) cannot be delivered, the oldest queued %(since)s: the people of those '
        'alarms are not reached, nor would the next level be. Look at the alarms and tell them another way.'),
        count=len(stuck), since=_clock(min((row.queued_at for row in stuck), default=now))), now))
    start, end = unchecked or (now, now)
    subjects.append(system_subject(ALARMS_UNCHECKED, unchecked is not None, Severity.CRITICAL, _text(_(
        'The alarms were not checked from %(start)s to %(end)s (the alarm worker was not running): no alarm was raised '
        'and nobody was told in that time. Look at the farm\'s values of that time.'), start=_clock(start),
        end=_clock(end)), now))
    subjects += [system_subject(f'step:{name.replace(" ", "_")}', name in failed_steps, Severity.CRITICAL, _text(_(
        'The alarm step "%(step)s" failed: what it does (raising, clearing, notifying or sending alarms) is not done '
        'until it passes again.'), step=name), now, parameter=STEP_FAILED) for name in steps]
    return settle(subjects, now, rules)

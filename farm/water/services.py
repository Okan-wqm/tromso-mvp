"""The one write path of the water samples. Every sample is written here, in one transaction, and so is
every void: the forms call these functions and the views show what they refuse on the field it concerns.

- `record` writes one sample, `record_round` the samples of a round (the morning round of a hall),
  all of them or none. A sample is at a sampling point (farm/models/water_point.py): a place on a unit, on a
  system's loop or on a piece of equipment. Each locks the owners of its points and the points in
  primary-key order, refuses a point that is deleted, inactive or on a deleted owner, refuses a form sent twice
  (its key), checks the time and every value, writes the rows and their activity-log rows.
- The time: not in the future and at most the correction window back, on the clock of the point's site, the
  rule of every daily record (farm/stock/dates.py; WQ-10).
- A value: inside its parameter's plausible range and at its precision (farm/water/parameters.py); the
  database checks both again. At least one value per sample; nothing is required beyond that (WQ-08).
- `void` is the undo, as for a stock operation: the sample stops counting and stays in the history with
  its reason; a correction is a void and a new entry. Samples are never edited (WQ-12), with one exception: after a
  formula change the NBS pH of a pH measured on another scale is converted again from what was measured
  (farm/water/rederive.py, `manage.py rederive_ph`), each rewrite logged with its old value.

A failure raises ValidationError, a dict of field to message: 'measured_at', 'point', a parameter's
code, 'reason' or NON_FIELD_ERRORS; for a round, a row's errors are under ('row', index). Nothing is
written."""
import uuid
from collections import defaultdict
from datetime import datetime, time, timedelta
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone
from django.utils.translation import gettext as _, gettext_lazy

from core import access, audit, platform
from core.models import AuditLog, EntryKey
from farm.health import withdrawal
from farm.models import Equipment, ProbeDay, ProbeDayClosing, SamplingPoint, System, Tank, WaterMeasurement
from farm.models.health import FloorOrigin
from farm.models.water import (BASIS_COLUMNS, NBS, PH_SCALE_COLUMNS, PHOSPHATE_UNIT_COLUMNS, PhosphateUnit, PhScale,
                               ProbeDayHow)
from farm.models.water_point import EQUIPMENT, SYSTEM, UNIT, PointKind, local_time, site_of
from farm.stock import dates
from farm.stock.services import AlreadyRecorded, lock_fish

from . import messages, parameters, sources
from .degree_days import zone_key
from .read import OWN_WATER_KINDS, POINT_RELATED, Context, oxygen_basis, ph_on_nbs, scale_origin, tiers

DAY = timedelta(days=1)

# What the activity log shows of a sample: where it was taken, its source, its values and its notes (and its
# time, which the entry carries).
LOGGED = ['point', 'source', *parameters.COLUMNS, *BASIS_COLUMNS, *PH_SCALE_COLUMNS, *PHOSPHATE_UNIT_COLUMNS, 'notes']
# The scale a pH is on unless said otherwise, NBS: farm.models.water's (services.NBS, as the forms name it).
# The unit a phosphate is in unless said otherwise: phosphorus (PO₄-P, mg/L as P), as it is stored.
AS_P = parameters.AS_P
# The most rows a round takes (a hall's points; the form shows them all on one page).
ROUND_ROWS = 200
OWNERS = ((UNIT, Tank), (SYSTEM, System), (EQUIPMENT, Equipment))


def earliest(point):
    """The first day a sample at this point may be dated (and the oldest one that may be voided): the window
    of every daily record (farm/stock/dates.py)."""
    return dates.site_earliest(site_of(point))


def _check_time(measured_at, points):
    if measured_at > timezone.now():
        raise ValidationError({'measured_at': _('The time cannot be in the future.')})
    for point in points:
        if local_time(measured_at, point).date() < earliest(point):
            raise ValidationError({'measured_at': dates.too_old(_('Samples can be dated at most %(days)d days '
                                                                    'back.'))})


def value_errors(values):
    """{code: message} for the values outside their parameter's range or precision."""
    errors = {}
    for code, value in values.items():
        parameter = parameters.get(code)
        if not parameter.plausible(value):
            errors[code] = _('Between %(low)s and %(high)s: check the value.') % {
                'low': parameter.low, 'high': parameter.high}
        elif not parameter.precise(value):
            errors[code] = _('At most %(decimals)d decimals.') % {'decimals': parameter.decimals}
    return errors


def _locked_points(points):
    """The points, locked for this transaction with their owners, in primary-key order (the owners first: units,
    systems, equipment; then the points). A point that is deleted or inactive, or whose owner is deleted, takes no
    sample: the reason is on 'point'. Returns the locked rows, owners loaded, in the order given."""
    owners = {}
    for owner_type, model in OWNERS:
        pks = sorted({getattr(point, f'{owner_type}_id') for point in points if getattr(point, f'{owner_type}_id')})
        owners.update(model.all_objects.select_for_update(of=('self',)).in_bulk(pks))
    related = [path.removeprefix('point__') for path in POINT_RELATED]
    locked = SamplingPoint.all_objects.select_for_update(of=('self',)).select_related(*related).in_bulk(
        sorted(point.pk for point in points))
    found = [locked[point.pk] for point in points]
    for point in found:
        owner = owners[getattr(point, f'{point.owner_type}_id')]
        if owner.is_deleted:
            raise ValidationError({'point': _('%(point)s is deleted.') % {'point': owner.code}})
        if point.is_deleted:
            raise ValidationError({'point': _('%(point)s is deleted.') % {'point': point}})
        if not point.is_active:
            raise ValidationError({'point': _('%(point)s is inactive: it takes no new samples.') % {'point': point}})
    return found


def _sample(user, point, measured_at, source, values, notes, basis=None, measured=None):
    provenance = {}
    for code, found in (basis or {}).items():
        provenance.update(found.fields(code))
    return WaterMeasurement(point=point, measured_at=measured_at, source=source, notes=notes.strip(), created_by=user,
                            updated_by=user, **values, **provenance, **(measured or {}))


def on_nbs(point, values, scale):
    """(the values with their pH on the NBS scale, the sample's provenance of it) for a pH measured on `scale` (NBS, or
    a PhScale). Every pH is stored on the NBS scale (the one scale every page, limit and calculation reads): one
    measured on the total, the seawater or the free scale is put on it here by the core (chemcore/core/src/scale.rs),
    with the temperature and the salinity of the SAME sample, never ones looked up, for sea water of 5 ‰ or more only;
    what was measured, its scale and the formula version are the provenance. NBS, or no pH: the values as they are and
    no provenance. Refused (ValidationError, a dict of field to message) for an unknown scale, without the sample's own
    temperature or salinity, or where the water is not sea water (the core's rule, Equilibria.takes_ph_scale)."""
    if scale in (NBS, '', None):
        return values, {}
    if scale not in PhScale.values:
        raise ValidationError({'ph_scale': _('Choose a pH scale.')})
    if values.get(parameters.PH) is None:
        return values, {}
    missing = {code: str(messages.PH_NEEDED) for code in (parameters.TEMPERATURE, parameters.SALINITY)
               if values.get(code) is None}
    if missing:
        raise ValidationError(missing)
    origin = scale_origin(Context._served([point])[point.pk])       # salt added as soon as one unit of its water says so
    # The one conversion, a sensor's too (read.ph_on_nbs): refused where the core takes no pH on that scale, or with the
    # core's own reason where it cannot work the water out at all (the review of the audit, C5).
    found = ph_on_nbs(values[parameters.PH], scale, values[parameters.TEMPERATURE], values[parameters.SALINITY], origin)
    if found.value is None:
        raise ValidationError({'ph_scale': str(messages.PH_NOT_SEA if found.refused == 'not_sea'
                                               else messages.refused(found.error))})
    return ({**values, parameters.PH: found.value},
            {'ph_scale': scale, 'ph_as_measured': values[parameters.PH], 'ph_converted_formula': found.formula})


def as_p(values, unit):
    """(the values with their phosphate as phosphorus, the sample's provenance of it) for a phosphate entered in
    `unit` (AS_P, or a PhosphateUnit). Every phosphate is stored as P (the one unit every page, limit and calculation
    reads): one entered as PO₄ is put on P here by the molar masses (parameters.phosphate_as_p, the one place), at
    the column's precision; what was entered and its unit are the provenance (the independent review of 2026-11-16,
    R3: a PO₄ reading typed as P is 3.07 times too much in every dose). As P, or no phosphate: the values as they are
    and no provenance. Refused (ValidationError, a dict of field to message) for an unknown unit, and for a value
    below 0, with more decimals than the column keeps, or outside the phosphorus's range: the range is the
    phosphorus's whatever the unit (parameters.phosphate_in_range: as PO₄ up to PO4_HIGH, the bound the calculator
    has too)."""
    if unit in (AS_P, '', None):
        return values, {}
    if unit not in PhosphateUnit.values:
        raise ValidationError({'phosphate_unit': _('Choose the phosphate’s unit.')})
    entered = values.get(parameters.PHOSPHATE)
    if entered is None:
        return values, {}
    parameter = parameters.get(parameters.PHOSPHATE)
    if not parameter.precise(entered):
        raise ValidationError({parameters.PHOSPHATE: _('At most %(decimals)d decimals.') % {
            'decimals': parameter.decimals}})
    converted = parameters.phosphate_as_p(entered, unit).quantize(parameter.step, rounding=ROUND_HALF_UP)
    if not parameters.phosphate_in_range(entered, unit):          # the one bound of every door (parameters.PO4_HIGH)
        raise ValidationError({parameters.PHOSPHATE: str(messages.phosphate_range(converted))})
    return ({**values, parameters.PHOSPHATE: converted}, {'phosphate_unit': unit, 'phosphate_as_measured': entered})


BASIS_NEEDED = {
    parameters.TEMPERATURE: gettext_lazy(
        'Needed with the oxygen: no fresh temperature here at that time to work the other unit out with.'),
    parameters.SALINITY: gettext_lazy(
        'Needed with the oxygen: no fresh salinity here at that time to work the other unit out with.'),
}


def _basis(rows, measured_at, by_row=False, required=False):
    """{index: {code: Basis}} of the rows' oxygen (read.oxygen_basis: found by the server at each row's point and the
    sample's time, never taken from the form); a row with an oxygen and nothing fresh to work it out with is refused,
    its reason on the parameter ('{index}-{code}' for a round, the code alone for one sample), when `required` (the
    forms: a person entering an oxygen is asked for what it needs); else such a row is written without a basis and its
    other unit is not worked out, said so on the pages."""
    found, missing = oxygen_basis(rows, measured_at)
    if missing and required:
        keys = (lambda index, code: f'{index}-{code}') if by_row else (lambda index, code: code)
        raise ValidationError({keys(index, code): str(BASIS_NEEDED[code]) for index, codes in missing.items()
                               for code in codes})
    return found


def label(sample):
    """How the activity log names a sample: where and when, on the site's clock, so a search for a unit's
    code finds it."""
    return f'{audit.english(WaterMeasurement._meta.verbose_name).capitalize()} · {sample.point} · ' \
           f'{local_time(sample.measured_at, sample.point):%Y-%m-%d %H:%M}'


def _log_create(user, sample):
    with audit.source_language():
        changes = {str(_('Measured at')): [None, local_time(sample.measured_at, sample.point).isoformat()]}
        changes.update({label_: [None, value] for label_, value in audit.snapshot(sample, LOGGED).items()
                        if value is not None})
        audit.record(user, AuditLog.Action.CREATE, sample, changes, label=label(sample))


def _write(user, samples, keys):
    """Writes the samples, each logged, and each one's form key (None: none) in the one table (core.models.EntryKey)."""
    WaterMeasurement.objects.bulk_create(samples)
    for sample, key in zip(samples, keys):
        _log_create(user, sample)
        if key is not None:
            EntryKey.note(key, sample)
    return samples


def _values(values):
    """The values entered, without the empty ones."""
    return {code: value for code, value in values.items() if value is not None}


# Who may read the water samples, record one and void one (the pages and the readers ask the same); asked here too (the data-layering audit,
# L-6).
VIEW, RECORD, VOID = 'farm.view_watermeasurement', 'farm.add_watermeasurement', 'farm.delete_watermeasurement'


def record(user, *, point, measured_at, source, values, notes='', token=None, require_basis=False,
           withdrawal_ack=None, ph_scale=NBS, phosphate_unit=AS_P):
    """One sample at one sampling point (a place on a unit, a system's loop or a piece of equipment). Returns the
    sample. `ph_scale`: the scale its pH was measured on (`on_nbs`); NBS unless said. `phosphate_unit`: the unit its
    phosphate was entered in (`as_p`); as P unless said."""
    access.require(user, RECORD)
    values = _values(values)
    with transaction.atomic():
        fish = _fish_of([point], measured_at)
        (point,) = _locked_points([point])
        if token is not None:
            done = EntryKey.record_of(token, WaterMeasurement)
            if done is not None:
                raise AlreadyRecorded(done)
        _check_time(measured_at, [point])
        if not values:
            raise ValidationError({NON_FIELD_ERRORS: _('Enter at least one value.')})
        values, entered = as_p(values, phosphate_unit)          # first: the range checked below is the phosphorus's
        errors = value_errors(values)
        if errors:
            raise ValidationError(errors)
        values, measured = on_nbs(point, values, ph_scale)
        errors = value_errors({parameters.PH: values[parameters.PH]}) if measured else {}
        if errors:
            raise ValidationError(errors)
        measured = {**measured, **entered}
        basis = _basis([(point, values)], measured_at, required=require_basis).get(0)
        return withdrawal.guarded(user, *fish, lambda: _write(
            user, [_sample(user, point, measured_at, source, values, notes, basis, measured)], [token])[0],
            seen=withdrawal_ack)


def row_key(token, point):
    """The key of one row of a round: the round's key and the point, so the same round sent twice records
    each of its samples once (a hypertable's unique key includes the time, which a round shares)."""
    return uuid.uuid5(token, f'point:{point.pk}')


def record_round(user, *, measured_at, source, rows, token=None, require_basis=False, withdrawal_ack=None,
                 ph_scale=NBS, phosphate_unit=AS_P):
    """The samples of a round, at one time and from one source: `rows` = [(point, values, notes)]. A row
    with no value is skipped; the rest are written together or not at all. Returns the samples. `ph_scale`: the scale
    the round's pHs were measured on (`on_nbs`, each row with its own temperature and salinity); NBS unless said.
    `phosphate_unit`: the unit the round's phosphates were entered in (`as_p`); as P unless said."""
    access.require(user, RECORD)
    rows = [(point, _values(values), notes) for point, values, notes in rows]
    rows = [(point, values, notes) for point, values, notes in rows if values]
    if not rows:
        raise ValidationError({NON_FIELD_ERRORS: _('Enter at least one value.')})
    if len({point.pk for point, _values_, _notes in rows}) != len(rows):
        raise ValidationError({NON_FIELD_ERRORS: _('Each point can be listed once.')})
    if len(rows) > ROUND_ROWS:
        raise ValidationError({NON_FIELD_ERRORS: _('A round takes at most %(rows)d rows.')
                               % {'rows': ROUND_ROWS}})
    with transaction.atomic():
        fish = _fish_of([point for point, _values_, _notes in rows], measured_at)
        points = _locked_points([point for point, _values_, _notes in rows])
        keys = [row_key(token, point) if token is not None else None for point in points]
        if token is not None:
            done = next(filter(None, (EntryKey.record_of(key, WaterMeasurement) for key in keys)), None)
            if done is not None:
                raise AlreadyRecorded(done)
        _check_time(measured_at, points)
        errors, entered = {}, {}
        for index, (_point, values, notes) in enumerate(rows):
            try:
                values, entered[index] = as_p(values, phosphate_unit)   # first: the range is the phosphorus's
            except ValidationError as refused:
                errors.update({f'{index}-{code}': reasons for code, reasons in refused.message_dict.items()})
                continue
            rows[index] = (_point, values, notes)
            for code, message in value_errors(values).items():
                errors[f'{index}-{code}'] = message
        if errors:
            raise ValidationError(errors)
        measured = {}
        for index, (point, (_point, values, notes)) in enumerate(zip(points, rows)):
            try:
                values, measured[index] = on_nbs(point, values, ph_scale)
            except ValidationError as refused:
                errors.update({f'{index}-{code}': reasons for code, reasons in refused.message_dict.items()})
                continue
            if measured[index]:
                errors.update({f'{index}-{code}': message
                               for code, message in value_errors({parameters.PH: values[parameters.PH]}).items()})
            rows[index] = (_point, values, notes)
            measured[index] = {**measured[index], **entered[index]}
        if errors:
            raise ValidationError(errors)
        basis = _basis([(point, values) for point, (_point, values, _notes) in zip(points, rows)], measured_at,
                       by_row=True, required=require_basis)
        return withdrawal.guarded(user, *fish, lambda: _write(user, [
            _sample(user, point, measured_at, source, values, notes, basis.get(index), measured.get(index))
            for index, (point, (_point, values, notes)) in enumerate(zip(points, rows))], keys),
            record_of=lambda samples: samples[0], seen=withdrawal_ack)


def void(user, sample, reason, withdrawal_ack=None):
    """The undo: the sample stops counting, with its reason, and stays in the history. Refused for samples
    older than the backdating window."""
    access.require(user, VOID)
    reason = reason.strip()
    if not reason:
        raise ValidationError({'reason': _('Say why it is voided.')})
    with transaction.atomic():
        stored = WaterMeasurement.all_objects.select_related(*POINT_RELATED).get(pk=sample.pk)
        fish = _fish_of([stored.point], stored.measured_at)
        sample = (WaterMeasurement.all_objects.select_for_update(of=('self',)).select_related(*POINT_RELATED)
                  .get(pk=sample.pk))
        if sample.is_deleted:
            raise ValidationError({NON_FIELD_ERRORS: _('This sample is already voided.')})
        if local_time(sample.measured_at, sample.point).date() < earliest(sample.point):
            raise ValidationError({NON_FIELD_ERRORS: dates.too_old(_('Samples older than %(days)d days cannot be '
                                                                     'voided.'))})

        def write():
            sample.void_reason = reason
            sample.soft_delete(user)
            with audit.source_language():
                audit.record(user, AuditLog.Action.VOID, sample, {str(_('Reason for voiding')): [None, reason]},
                             label=label(sample))
            return sample

        return withdrawal.guarded(user, *fish, write, seen=withdrawal_ack)


def _fish_of(points, measured_at):
    """(batch ids, the farm's today) of a sample's write for the withdrawal guard (farm.health.withdrawal.guarded): a
    temperature counts in the degree-days of the withdrawals of the fish of the point's unit, or of the units of its
    system, from its day on, so a backdated or voided one can bring a harvest inside a withdrawal or free fish held today.
    Their batches and units are locked first, as a stock operation locks them (farm.stock.services.lock_fish); a point of
    equipment holds no fish."""
    unit_ids = set()
    for point in points:
        if point.unit_id:
            unit_ids.add(point.unit_id)
        elif point.system_id:
            unit_ids.update(Tank.all_objects.filter(system_id=point.system_id).values_list('pk', flat=True))
    units, batch_ids = lock_fish(unit_ids, local_time(measured_at, points[0]).date())
    return batch_ids, dates.earliest_today(units.values())


# ---- probe days: a temperature probe's closed days (farm.models.ProbeDay) --------------------------------------
# The one writer of the probe days the degree-days read (farm/water/degree_days.py): the daily job closes each day once
# it is over on the place's clock; a person backfills history or corrects a day, through the withdrawal guard. The
# sensors' readings are asked through the water's sources (farm/water/sources.py `covered`), here and nowhere else.
TEMPERATURE = parameters.get(parameters.TEMPERATURE)
PROBE_STEP = Decimal('0.01')
PROBE_BOUND = Decimal('999.99')          # what the column holds: a mean beyond it is kept at it and never counts


class SensorsUnread(Exception):
    """The sensors could not be read: no probe day is written and no day closed (the days stay not closed)."""


def probe_places():
    """[(target, point or None, system or None, clock)] of every place a probe day is closed for: each active
    own-water point (the middle point and the others; never an inlet) of a live unit, each active middle point of a
    live system (its loop), and each live system (its own sensors); `clock`: the time zone its days are counted on."""
    found = []
    points = (SamplingPoint.objects.filter(is_active=True)
              .filter(Q(unit__isnull=False, kind__in=[PointKind.MIDDLE, *OWN_WATER_KINDS])
                      | Q(system__isnull=False, kind=PointKind.MIDDLE)).with_owners())
    for point in points:
        found.append(((sources.POINT, point.pk), point, None, zone_key(site_of(point))))
    for system in System.objects.select_related('site'):
        found.append(((sources.SYSTEM, system.pk), None, system, zone_key(system.site)))
    return found


def _probe_rows(places, days, hours, hold, how, user=None, note=''):
    """The ProbeDay rows (not saved) of every channel that answers for `places` on each of `days` (farm-local days on
    each place's clock): the mean rounded down to 0.01 °C, and whether the day counts: the channel has a range, at
    least `hours` of the day's hours hold a good reading and as many hours are covered, and the mean lies inside the
    temperature's plausible range. SensorsUnread when a source failed: nothing is made of a partial answer."""
    asks, keys = [], []
    for target, point, system, clock in places:
        zone = ZoneInfo(clock)
        for day in days:
            start = datetime.combine(day, time.min, tzinfo=zone)
            asks.append((target, start, datetime.combine(day + DAY, time.min, tzinfo=zone)))
            keys.append((point, system, day))
    if not asks:
        return []
    answer = sources.covered(asks, TEMPERATURE.code, hold)
    if answer.failed:
        raise SensorsUnread('The sensors could not be read: no probe day was written.')
    rows = []
    for index, covered in sorted(answer.values.items()):
        point, system, day = keys[index]
        for each in sorted(covered, key=lambda found: found.channel_no):
            if abs(each.mean) < 1000:
                kept = Decimal(repr(each.mean)).quantize(PROBE_STEP, rounding=ROUND_FLOOR)
            else:                                  # beyond what the column holds: kept at its bound, never counted
                kept = PROBE_BOUND if each.mean > 0 else -PROBE_BOUND
            counts = (each.ranged and each.hours >= hours and each.seconds >= hours * 3600
                      and TEMPERATURE.low <= kept <= TEMPERATURE.high)
            rows.append(ProbeDay(point=point, system=system, day=day, channel_no=each.channel_no, mean_c=kept,
                                 covered_seconds=int(each.seconds), hours=each.hours, readings=each.readings,
                                 ranged=each.ranged, hours_needed=hours, hold_seconds=hold, counts=counts, how=how,
                                 created_by=user, note=note))
    return rows


def _unwritten(rows):
    """The rows of `rows` whose place, day and channel have no live row yet (a backfilled or corrected day stands)."""
    if not rows:
        return []
    taken = set(ProbeDay.objects.filter(voided_at__isnull=True, day__in={row.day for row in rows})
                .values_list('point_id', 'system_id', 'day', 'channel_no'))
    return [row for row in rows if (row.point_id, row.system_id, row.day, row.channel_no) not in taken]


def close_probe_days(now=None):
    """The daily job (manage.py close_probe_days, the server's jobs): for every clock a place is on, closes each day
    that is over on it and not closed yet, oldest first (the first run closes yesterday alone: history is not made
    here, `backfill_probe_days`): writes the probe days of every probe bound at a place that day and the day's
    closing. A write nobody can be asked about (farm.health.services.unattended): a withdrawal in force whose end the
    closed days would move EARLIER keeps the end it had as a floor. Returns (the rows written, the closings, the
    floors). SensorsUnread: nothing is written, the days stay not closed (and so pending for the degree-days)."""
    from farm.health import services as health_services
    now = now or timezone.now()
    hours, hold, _cap, _tolerance = platform.degree_day_rules()
    by_clock = defaultdict(list)
    for place in probe_places():
        by_clock[place[3]].append(place)
    last = dict(ProbeDayClosing.objects.values('timezone').annotate(last=Max('day')).values_list('timezone', 'last'))
    todo = []
    for clock, places in sorted(by_clock.items()):
        yesterday = now.astimezone(ZoneInfo(clock)).date() - DAY
        day = last[clock] + DAY if clock in last else yesterday
        while day <= yesterday:
            todo.append((clock, day, places))
            day += DAY
    if not todo:
        return [], [], []

    def write():
        written, closings = [], []
        for clock, day, places in todo:
            rows = _unwritten(_probe_rows(places, [day], hours, hold, ProbeDayHow.CLOSED))
            ProbeDay.objects.bulk_create(rows)
            closings.append(ProbeDayClosing.objects.create(
                timezone=clock, day=day, hours_needed=hours, hold_seconds=hold,
                probe_days=sum(row.counts for row in rows)))
            written += rows
        return written, closings

    days = sorted({day for _clock, day, _places in todo})
    reason = f'The probe days of {days[0].isoformat()} to {days[-1].isoformat()} were closed by the daily job.'
    (written, closings), floors = health_services.unattended(write, FloorOrigin.CLOSING, reason)
    return written, closings, floors


def _places_of(units):
    """The probe places of some units (`probe_places`'s shape): the places of their tiers (farm.water.read.tiers)."""
    found = {}
    for unit_tiers in tiers(units, nested=False).values():
        for tier in unit_tiers:
            points = {(sources.POINT, point.pk): point for point in tier.points}
            for target, _origin in tier.targets:
                point = points.get(target)
                site = site_of(point) if point is not None else tier.owner.site
                found[target] = (target, point, None if point is not None else tier.owner, zone_key(site))
    return list(found.values())


def backfill_probe_days(user, *, units, first, last, reason, withdrawal_ack=None):
    """History, asked for by a person: the probe days of the places of `units` from `first` to `last` (days that are
    over), worked out from the readings and the bindings AS THEY STAND NOW, with today's hours and hold, each row
    marked backfilled with the reason; a place, day and channel that has a live row keeps it. Through the withdrawal
    guard: a withdrawal it would end earlier, or a recorded harvest it would bring inside one, is asked about first.
    Returns the rows written."""
    access.require(user, RECORD)
    reason = (reason or '').strip()
    if not reason:
        raise ValidationError({'reason': _('Say why the probe days are backfilled.')})
    units = list(units or ())
    if not units or first is None or last is None or first > last:
        raise ValidationError({NON_FIELD_ERRORS: _('Name the units and a first and a last day.')})
    places = _places_of(units)
    now = timezone.now()
    if any(last >= now.astimezone(ZoneInfo(clock)).date() for _target, _point, _system, clock in places):
        raise ValidationError({'last': _('Only days that are over can be backfilled.')})
    hours, hold, _cap, _tolerance = platform.degree_day_rules()
    days = [first + offset * DAY for offset in range((last - first).days + 1)]

    def write():
        rows = _unwritten(_probe_rows(places, days, hours, hold, ProbeDayHow.BACKFILLED, user, reason))
        ProbeDay.objects.bulk_create(rows)
        if rows:
            with audit.source_language():
                audit.record(user, AuditLog.Action.CREATE, rows[0], {
                    str(_('First day')): [None, first.isoformat()], str(_('Last day')): [None, last.isoformat()],
                    str(_('Units')): [None, ', '.join(sorted(unit.code for unit in units))],
                    str(_('Probe days written')): [None, len(rows)],
                    str(_('Probe days that count')): [None, sum(row.counts for row in rows)],
                    str(_('Reason')): [None, reason]}, label=str(_('Probe days backfilled')))
        return rows

    return withdrawal.guarded_units(user, [unit.pk for unit in units], first, write, seen=withdrawal_ack,
                                    record_of=lambda rows: rows[0])


def correct_probe_day(user, row, reason, withdrawal_ack=None):
    """A closed probe day corrected: the row is voided (who, when, why) and the day is worked out again from the
    readings and the bindings as they stand now, with today's hours and hold, as a new row marked corrected (none
    when the channel answers nothing for the day any more). Through the withdrawal guard. Returns the new row or
    None."""
    access.require(user, VOID)
    reason = (reason or '').strip()
    if not reason:
        raise ValidationError({'reason': _('Say why the probe day is corrected.')})
    with transaction.atomic():
        row = ProbeDay.objects.select_related('point__unit__production_department__site', 'point__system__site',
                                              'system__site').get(pk=row.pk)
        if row.voided_at is not None:
            raise ValidationError({NON_FIELD_ERRORS: _('This probe day is already voided.')})
        if row.point_id and row.point.unit_id:
            unit_ids = [row.point.unit_id]
        else:
            system_id = row.system_id or row.point.system_id
            unit_ids = list(Tank.all_objects.filter(system_id=system_id).values_list('pk', flat=True))
        target = (sources.POINT, row.point_id) if row.point_id else (sources.SYSTEM, row.system_id)
        clock = zone_key(site_of(row.point) if row.point_id else row.system.site)
        hours, hold, _cap, _tolerance = platform.degree_day_rules()

        def write():
            row.voided_at, row.voided_by, row.void_reason = timezone.now(), user, reason
            row.save(update_fields=['voided_at', 'voided_by', 'void_reason'])
            made = [each for each in _probe_rows([(target, row.point, row.system, clock)], [row.day], hours, hold,
                                                 ProbeDayHow.CORRECTED, user, reason)
                    if each.channel_no == row.channel_no]
            ProbeDay.objects.bulk_create(made)
            with audit.source_language():
                audit.record(user, AuditLog.Action.VOID, row, {
                    str(_('Reason for voiding')): [None, reason],
                    str(_('Mean (°C)')): [str(row.mean_c), str(made[0].mean_c) if made else None]}, label=str(row))
            return made[0] if made else None

        return withdrawal.guarded_units(user, unit_ids, row.day, write, seen=withdrawal_ack,
                                        record_of=lambda _made: row)

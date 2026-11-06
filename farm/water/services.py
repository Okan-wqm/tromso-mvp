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
  its reason; a correction is a void and a new entry. Samples are never edited (WQ-12).

A failure raises ValidationError, a dict of field to message: 'measured_at', 'point', a parameter's
code, 'reason' or NON_FIELD_ERRORS; for a round, a row's errors are under ('row', index). Nothing is
written."""
import uuid

from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from core import audit
from core.models import AuditLog
from core.platform import correction_window_days
from farm.models import Equipment, SamplingPoint, System, Tank, WaterMeasurement
from farm.models.water_point import EQUIPMENT, SYSTEM, UNIT, local_time, site_of
from farm.stock import dates
from farm.stock.services import AlreadyRecorded

from . import parameters
from .read import POINT_RELATED

# What the activity log shows of a sample: where it was taken, its source, its values and its notes (and its
# time, which the entry carries).
LOGGED = ['point', 'source', *parameters.COLUMNS, 'notes']
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
            raise ValidationError({'measured_at': _('Samples can be dated at most %(days)d days back.')
                                   % {'days': correction_window_days()}})


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


def _sample(user, point, measured_at, source, values, notes, key):
    return WaterMeasurement(point=point, measured_at=measured_at, source=source, notes=notes.strip(), entry_key=key,
                            created_by=user, updated_by=user, **values)


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


def _write(user, samples):
    WaterMeasurement.objects.bulk_create(samples)
    for sample in samples:
        _log_create(user, sample)
    return samples


def _values(values):
    """The values entered, without the empty ones."""
    return {code: value for code, value in values.items() if value is not None}


def record(user, *, point, measured_at, source, values, notes='', token=None):
    """One sample at one sampling point (a place on a unit, a system's loop or a piece of equipment). Returns the
    sample."""
    values = _values(values)
    with transaction.atomic():
        (point,) = _locked_points([point])
        if token is not None:
            done = WaterMeasurement.all_objects.filter(entry_key=token, measured_at=measured_at).first()
            if done is not None:
                raise AlreadyRecorded(done)
        _check_time(measured_at, [point])
        if not values:
            raise ValidationError({NON_FIELD_ERRORS: _('Enter at least one value.')})
        errors = value_errors(values)
        if errors:
            raise ValidationError(errors)
        (sample,) = _write(user, [_sample(user, point, measured_at, source, values, notes, token)])
        return sample


def row_key(token, point):
    """The key of one row of a round: the round's key and the point, so the same round sent twice records
    each of its samples once (a hypertable's unique key includes the time, which a round shares)."""
    return uuid.uuid5(token, f'point:{point.pk}')


def record_round(user, *, measured_at, source, rows, token=None):
    """The samples of a round, at one time and from one source: `rows` = [(point, values, notes)]. A row
    with no value is skipped; the rest are written together or not at all. Returns the samples."""
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
        points = _locked_points([point for point, _values_, _notes in rows])
        keys = [row_key(token, point) if token is not None else None for point in points]
        if token is not None:
            done = WaterMeasurement.all_objects.filter(entry_key__in=keys, measured_at=measured_at).first()
            if done is not None:
                raise AlreadyRecorded(done)
        _check_time(measured_at, points)
        errors = {}
        for index, (_point, values, _notes) in enumerate(rows):
            for code, message in value_errors(values).items():
                errors[f'{index}-{code}'] = message
        if errors:
            raise ValidationError(errors)
        return _write(user, [_sample(user, point, measured_at, source, values, notes, key)
                             for point, (_point, values, notes), key in zip(points, rows, keys)])


def void(user, sample, reason):
    """The undo: the sample stops counting, with its reason, and stays in the history. Refused for samples
    older than the backdating window."""
    reason = reason.strip()
    if not reason:
        raise ValidationError({'reason': _('Say why it is voided.')})
    with transaction.atomic():
        sample = (WaterMeasurement.all_objects.select_for_update(of=('self',)).select_related(*POINT_RELATED)
                  .get(pk=sample.pk))
        if sample.is_deleted:
            raise ValidationError({NON_FIELD_ERRORS: _('This sample is already voided.')})
        if local_time(sample.measured_at, sample.point).date() < earliest(sample.point):
            raise ValidationError({NON_FIELD_ERRORS: _('Samples older than %(days)d days cannot be voided.')
                                   % {'days': correction_window_days()}})
        sample.void_reason = reason
        sample.soft_delete(user)
        with audit.source_language():
            audit.record(user, AuditLog.Action.VOID, sample, {str(_('Reason for voiding')): [None, reason]},
                         label=label(sample))
        return sample

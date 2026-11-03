"""The one write path of the stock (stock-db §6.4). Every operation is one function here, and each
goes through `_commit`, the only code that writes StockOperation and StockMovement rows and the only
code that changes a unit's status for stock reasons. In one transaction it:

1. locks the batches, then the units, each in primary-key order (the same order everywhere, so two
   writers never deadlock, and two writers of the same unit or batch take turns);
2. refuses a form sent twice (its token), and checks what needs no folding: the date (not in the
   future, at most STOCK_BACKDATE_DAYS back, in the farm's own time zone; not before the batch was
   stocked), live units and batches, units that may take fish (owner decision Q5), species that may
   be stocked;
3. writes the operation and its lines;
4. folds every batch the operation touches, and every batch that was ever in its units, from the
   first line, and checks the whole timeline, not only today: no share ever below 0 fish, a weighing
   only where there are fish, one species per unit (owner decision Q1), and every feeding recorded
   in its units from its date on still finds fish there at the start or the end of its day (the
   feeding records, farm/feeding), as every treatment on its first day and every sea-lice count (the
   health records, farm/health). A backdated operation is placed where it belongs and accepted only
   if every later day stays valid;
5. checks the capacity of the units fish arrive in, on the operation's date: above the max biomass
   only with the person's acknowledgement, stored on the operation (owner decision Q4);
6. moves the unit statuses that follow the fish (a unit going from empty to stocked, or back), and
   writes the activity log.

A failure raises ValidationError (a dict of field to message, the field names below) and nothing is
written. A void is the undo: steps 1, 4 and 6 with the operation left out; it fails, naming the
operation (or the feeding) that depends on it, when later operations need its fish. `voided` is the
one void of the farm's daily records, a stock operation's and a feeding's.

Fields the errors are reported on: 'date', 'count', 'unit', 'batch', 'species', 'notes',
'avg_weight_g', 'measured_weight_kg', 'destinations', 'over_capacity_ack', 'handling_ack', 'facility',
'transport', 'vessel', 'plan_item', 'health_event' and NON_FIELD_ERRORS.

A harvest, a transfer and a grading run the handling check (farm/handling/check.py) after the locks: a
medicine withdrawal in force or too short a fast is a warning, and the person goes on by acknowledging the
warnings they were shown (stored, one row each, and the operation's log entry is critical; owner decision:
warn, never block). A harvest names where the fish went (HarvestRecord); a harvest or transfer recorded from
a plan links it, in the same transaction. A mortality or a cull may name the health event its fish died or
were culled under (a live event of the unit's site that covers the unit and is not dated after the
operation).

Operations: a stocking (a new batch into one or several units), a mortality, a cull, a weighing, a
transfer (out of one unit into one or several: a split is a transfer into several), a grading (a
transfer whose fish are weighed per size class, the fish that stay weighed too) and a harvest; each is
voidable. Count adjustments have their line kind and checks but no dialog yet."""
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.db import connection, transaction
from django.db.models import IntegerField, Max
from django.db.models.functions import Cast, Substr
from django.utils.translation import gettext as _

from core import audit
from core.models import AuditLog
from farm.feeding import read as feeding_read
from farm.feeding.fold import walk
from farm.handling import check
from farm.health import read as health_read
from farm.models import (
    Batch, HandlingPlanItem, HarvestRecord, HealthEvent, Species, StockMovement, StockOperation, Tank,
)
from farm.models.handling import KIND_OF_OPERATION
from farm.models.harvest import FULFILLED_BY
from farm.models.stock import (
    ARRIVAL_STATUSES, REASONS, AdjustmentReason, MovementKind, OperationKind, TransferReason,
)
from farm.models.tank import NEEDS_NO_FISH
from farm.templatetags.stock import number

from . import read
# The farm's dates are one rule for every daily record; services.local_today and the others stay here.
from .dates import check_date, earliest, local_today, shown_date, site_earliest  # noqa: F401
from .fold import StockError

Status = Tank.Status
GRAMS = Decimal('0.0001')
# A batch may be stocked with a species the farm grows or tries out (the Species tab's rule).
STOCKABLE_SPECIES = (Species.Status.ACTIVE, Species.Status.EXPERIMENTAL)
# What emptying a unit makes of its status (stock-db §6.6); a status not listed stays.
EMPTIED = {Status.ACTIVE: Status.FALLOW, Status.HARVESTING: Status.CLEANING, Status.QUARANTINE: Status.CLEANING}
# The batch fields the activity log shows for a new batch.
BATCH_FIELDS = ['code', 'name', 'species', 'input_stage', 'origin', 'supplier', 'supplier_batch_ref', 'strain',
                'input_date', 'expected_harvest_date', 'notes']


class AlreadyRecorded(Exception):
    """The form was sent before and its operation is recorded: nothing more to do."""

    def __init__(self, operation):
        super().__init__(operation)
        self.operation = operation


@dataclass
class Entry:
    """A line to write. `batch` is None on the lines of a new batch's input until _commit creates it."""
    unit: Tank
    batch: Batch
    kind: str
    count_delta: int
    avg_weight_g: Decimal = None
    measured_weight_kg: Decimal = None
    pair: int = None
    reason: str = ''
    size_class: str = ''
    sample_count: int = None
    sample_weight_kg: Decimal = None


@dataclass
class NewBatch:
    fields: dict = field(default_factory=dict)


# ---- the one write path --------------------------------------------------------------------------
def locked(model, pks):
    """The rows, locked for this transaction in primary-key order, deleted ones included (a feeding
    locks its unit the same way, so a feeding and a stock operation of one unit take turns)."""
    return model.all_objects.select_for_update(of=('self',)).filter(pk__in=pks).order_by('pk').in_bulk()


def _already(token):
    if token is not None:
        done = StockOperation.all_objects.filter(entry_key=token).first()
        if done is not None:
            raise AlreadyRecorded(done)


def _next_code(year):
    """B-<year>-<n>, n one more than any number of that year, voided batches included: a number is
    never given twice. An advisory lock makes two stockings take turns for it."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext('batches.code'))")
    prefix = f'B-{year}-'
    last = (Batch.all_objects.filter(code__startswith=prefix)
            .annotate(n=Cast(Substr('code', len(prefix) + 1), IntegerField())).aggregate(last=Max('n'))['last'])
    return f'{prefix}{(last or 0) + 1:03d}'


def _commit(user, kind, day, entries, *, notes='', ack=False, token=None, new_batch=None, handling_ack=None,
            harvest=None, plan_item=None, health_event=None):
    """Writes an operation and its lines (see the module's docstring); returns the operation. A harvest,
    transfer or grading is checked for a medicine withdrawal and the fast first (`handling_ack` is the
    fingerprint of the warnings the person went on past); a harvest writes its record (`harvest`: its
    facility, transport and vessel); `plan_item` is the planned harvest or transport it fulfils; a mortality
    or cull may name its `health_event`."""
    with transaction.atomic():
        batches = locked(Batch, {entry.batch.pk for entry in entries if entry.batch is not None})
        units = locked(Tank, {entry.unit.pk for entry in entries})
        _already(token)
        _check_static(kind, day, entries, batches, units, new_batch)
        if health_event is not None:
            _check_event(health_event, day, units.values())
        assessment = _handling(kind, day, entries, batches, units, handling_ack)
        before = read.unit_counts(list(units))
        if new_batch is not None:
            batch = Batch(**new_batch.fields, code=_next_code(day.year), input_date=day, created_by=user,
                          updated_by=user)
            batch.full_clean(exclude=['code'])
            batch.save()
            batches[batch.pk] = batch
            for entry in entries:
                entry.batch = batch
            with audit.source_language():
                audit.record_create(user, batch, audit.snapshot(batch, BATCH_FIELDS))
        operation = StockOperation.objects.create(kind=kind, date=day, notes=notes, entry_key=token,
                                                  health_event=health_event, created_by=user, updated_by=user)
        StockMovement.objects.bulk_create([
            StockMovement(operation=operation, batch=batches[entry.batch.pk], unit=units[entry.unit.pk],
                          kind=entry.kind, count_delta=entry.count_delta, avg_weight_g=entry.avg_weight_g,
                          measured_weight_kg=entry.measured_weight_kg, pair=entry.pair, reason=entry.reason,
                          size_class=entry.size_class, sample_count=entry.sample_count,
                          sample_weight_kg=entry.sample_weight_kg)
            for entry in entries])
        over = _check_timeline(operation, batches, units)
        if over:
            if not ack:
                raise ValidationError({'over_capacity_ack': over})
            operation.over_capacity_ack = True
            operation.save(update_fields=['over_capacity_ack'])
        if (harvest is not None) != (kind == OperationKind.HARVEST):
            raise ValueError('A harvest, and only a harvest, writes a harvest record.')
        if harvest is not None:
            record = HarvestRecord(operation=operation, **harvest)
            record.full_clean()
            record.save()
        if assessment is not None and assessment.warnings:
            check.acknowledge(operation, assessment)
        _log(user, AuditLog.Action.CREATE, operation, assessment)
        if plan_item is not None:
            _fulfil(user, plan_item, operation, entries)
        _follow_status(user, units, before)
        return operation


def _handling(kind, day, entries, batches, units, seen):
    """The handling check of a harvest, transfer or grading (farm/handling/check.py), on the source unit and
    batch, after the locks: with warnings, the person must have seen exactly these (`seen`, their
    fingerprint) and gone on; otherwise they are asked (again). None for other operations."""
    handling = KIND_OF_OPERATION.get(kind)
    if handling is None:
        return None
    source = next(entry for entry in entries if entry.count_delta < 0)
    assessment = check.assess(handling, units[source.unit.pk], day, batches[source.batch.pk])
    check.require_acknowledged(assessment, seen)
    return assessment


def _fulfil(user, item, operation, entries):
    """Links the planned harvest or transport this operation fulfils, in its transaction. Refused when the
    plan is deleted or cancelled, already recorded by an operation that counts, or for other fish."""
    item = (HandlingPlanItem.all_objects.select_for_update(of=('self',))
            .select_related('operation', 'unit', 'batch').get(pk=item.pk))
    source = next(entry for entry in entries if entry.count_delta < 0)
    problem = None
    if item.is_deleted:
        problem = _('This plan was deleted.')
    elif item.cancelled_reason:
        problem = _('This plan is cancelled.')
    elif item.done:
        problem = _('This plan is recorded already: void that operation first.')
    elif FULFILLED_BY[item.kind] != operation.kind:
        problem = _('A planned %(plan)s is recorded as a %(operation)s.') % {
            'plan': str(item.get_kind_display()).lower(),
            'operation': str(OperationKind(FULFILLED_BY[item.kind]).label).lower()}
    elif (item.unit_id, item.batch_id) != (source.unit.pk, source.batch.pk):
        problem = _('This plan is for %(batch)s in %(unit)s.') % {'batch': item.batch.code, 'unit': item.unit.code}
    if problem:
        raise ValidationError({'plan_item': problem})
    with audit.source_language():
        item.operation = operation
        item.updated_by = user
        item.version += 1
        item.save()
        audit.record_update(user, item, {str(_('Recorded as')): None}, {str(_('Recorded as')): label(operation)})


def _check_static(kind, day, entries, batches, units, new_batch):
    for unit in units.values():
        if unit.is_deleted:
            raise ValidationError({'unit': _('%(unit)s is deleted.') % {'unit': unit.code}})
    for batch in batches.values():
        if batch.is_deleted:
            raise ValidationError({'batch': _('%(batch)s was voided.') % {'batch': batch.code}})
    check_date(day, units.values())
    if kind != OperationKind.INPUT:
        for batch in batches.values():
            if day < batch.input_date:
                raise ValidationError({'date': _('%(batch)s was stocked on %(date)s: an operation on it cannot be '
                                                  'dated before.') % {'batch': batch.code,
                                                                      'date': shown_date(batch.input_date)}})
    for entry in entries:
        if entry.count_delta > 0 and units[entry.unit.pk].status not in ARRIVAL_STATUSES:
            unit = units[entry.unit.pk]
            raise ValidationError({'unit': _('%(unit)s has the status %(status)s, so it cannot take fish: it can '
                                             'when it is active, preparing or fallow.')
                                   % {'unit': unit.code, 'status': str(unit.get_status_display()).lower()}})
    if new_batch is not None:
        species = new_batch.fields['species']
        if species.is_deleted or species.status not in STOCKABLE_SPECIES:
            raise ValidationError({'species': _('%(species)s is %(status)s: a new batch takes an active or '
                                                'experimental species.')
                                   % {'species': species, 'status': str(species.get_status_display()).lower()}})


def _check_event(event, day, units):
    """The health event a mortality or a cull names: live, of the unit's site, covering the unit (or the whole
    site), and not dated after the operation."""
    event = HealthEvent.all_objects.prefetch_related('units').get(pk=event.pk)
    for unit in units:
        covered = not event.units.all() or unit in event.units.all()
        if event.is_deleted or event.site_id != unit.production_department.site_id or not covered:
            raise ValidationError({'health_event': _('Choose a health event of %(unit)s.') % {'unit': unit.code}})
    if event.date > day:
        raise ValidationError({'health_event': _('The health event is dated %(date)s, after this operation.') % {
            'date': shown_date(event.date)}})


def _check_timeline(operation, batches, units):
    """Folds every batch of the operation and every batch ever in its units (step 4); returns the
    capacity messages of the units the operation brings fish into, empty when none is above its max."""
    arriving = set(StockMovement.objects.filter(operation=operation, count_delta__gt=0).values_list('unit_id',
                                                                                                    flat=True))
    return _validate(set(batches), set(units), operation.date, operation.pk, arriving)


def _validate(batch_ids, unit_ids, day, new_op_id=None, arriving=()):
    """Folds the batches and every batch ever in the units, with the live feedings of the units dated
    `day` or later: only the counts of these units change, and only from that day."""
    batch_ids = batch_ids | read.batches_ever_in(unit_ids)
    lines = read.ledger(batch_ids)
    species = dict(Batch.all_objects.filter(pk__in=batch_ids).values_list('pk', 'species_id'))
    grams_after = {}

    def observe(op, shares):
        arrivals = {line.unit_id for line in lines_of.get(op.id, ()) if line.count_delta > 0}
        for unit_id in arrivals:
            present = {batch_id for (unit, batch_id), share in shares.items() if unit == unit_id and share.count}
            kinds = {species[batch_id] for batch_id in present}
            if len(kinds) > 1:
                raise _mixed(op, unit_id, kinds)
        if op.id == new_op_id:
            for unit_id in arriving:
                grams_after[unit_id] = sum((share.grams for (unit, _b), share in shares.items() if unit == unit_id),
                                           Decimal(0))

    lines_of = {}
    for line in lines:
        lines_of.setdefault(line.op.id, []).append(line)
    health = health_read.dated_records(unit_ids, since=day)
    try:
        walked = walk(lines, feeding_read.feedings(unit_ids, since=day),
                      days=[(unit_id, record_day) for _kind, _record, unit_id, record_day in health], observe=observe)
    except StockError as error:
        raise _explain(error, new_op_id) from None
    if walked.orphans:
        feeding = walked.orphans[0]
        unit, _batch, _species = _names(feeding.unit_id)
        raise ValidationError({NON_FIELD_ERRORS: _(
            'The feeding of %(date)s in %(unit)s would have no fish: void it first.') % {
            'date': shown_date(feeding.date), 'unit': unit}})
    for kind, _record, unit_id, record_day in sorted(health, key=lambda item: item[3]):
        if not walked.days[(unit_id, record_day)].has_fish:
            unit, _batch, _species = _names(unit_id)
            text = (_('The treatment of %(date)s in %(unit)s would have no fish: void it first.') if kind == 'treatment'
                    else _('The sea-lice count of %(date)s in %(unit)s would have no fish: void it first.'))
            raise ValidationError({NON_FIELD_ERRORS: text % {'date': shown_date(record_day), 'unit': unit}})
    return _over_capacity(grams_after, new_op_id)


def _over_capacity(grams_after, op_id):
    if not grams_after:
        return []
    day = StockOperation.all_objects.get(pk=op_id).date
    messages = []
    for unit in Tank.all_objects.filter(pk__in=grams_after).order_by('code'):
        kilos = grams_after[unit.pk] / 1000
        if unit.max_biomass_kg is not None and kilos > unit.max_biomass_kg:
            messages.append(_(
                '%(unit)s would hold %(kilos)s kg on %(date)s, %(percent)s %% of its max biomass (%(max)s kg at '
                '%(density)s kg/m³). Tick the box below to stock it anyway.') % {
                'unit': unit.code, 'date': shown_date(day),
                'kilos': number(kilos), 'percent': number(100 * kilos / unit.max_biomass_kg),
                'max': number(unit.max_biomass_kg), 'density': number(unit.max_density_kg_m3, 2)})
    return messages


def _names(unit_id=None, batch_id=None, species_ids=()):
    unit = Tank.all_objects.filter(pk=unit_id).values_list('code', flat=True).first() if unit_id else ''
    batch = Batch.all_objects.filter(pk=batch_id).values_list('code', flat=True).first() if batch_id else ''
    species = [str(item) for item in Species.all_objects.filter(pk__in=species_ids)]
    return unit, batch, species


def _mixed(op, unit_id, species_ids):
    unit, _batch, species = _names(unit_id, species_ids=species_ids)
    return ValidationError({'species': _('%(unit)s would hold %(species)s on %(date)s: a unit holds one species '
                                         'at a time.') % {'unit': unit, 'species': ' + '.join(sorted(species)),
                                                          'date': shown_date(op.date)}})


def _explain(error, new_op_id):
    """The StockError as a message a person can act on, on the field it concerns."""
    line = error.line
    unit, batch, _species = _names(line.unit_id, line.batch_id)
    params = {'unit': unit, 'batch': batch, 'date': shown_date(line.op.date), 'available': number(error.available),
              'operation': str(OperationKind(line.op.kind).label).lower()}
    ours = line.op.id == new_op_id
    if error.reason == StockError.SHORT:
        if ours:
            text = (_('No fish of %(batch)s are in %(unit)s on %(date)s.') if not error.available else
                    _('Only %(available)s fish of %(batch)s are in %(unit)s on %(date)s.'))
            return ValidationError({'count': text % params})
        return ValidationError({NON_FIELD_ERRORS: _(
            'The %(operation)s of %(date)s in %(unit)s would be left without its fish: only %(available)s fish of '
            '%(batch)s would be there that day. Void that operation first, or correct this one.') % params})
    if error.reason == StockError.NOTHING_TO_WEIGH:
        if ours:
            return ValidationError({'date': _('No fish of %(batch)s are in %(unit)s on %(date)s to weigh.') % params})
        return ValidationError({NON_FIELD_ERRORS: _(
            'The weighing of %(date)s in %(unit)s would find no fish of %(batch)s. Void that weighing first.')
            % params})
    if error.reason == StockError.OVER_BOOK:
        return ValidationError({NON_FIELD_ERRORS: _(
            'These fish of %(batch)s weigh as much as the book holds for %(unit)s on %(date)s, or more: weigh the '
            'unit first.') % params})
    return ValidationError({NON_FIELD_ERRORS: _(
        'The stock of %(batch)s in %(unit)s does not add up on %(date)s.') % params})


def _follow_status(user, units, before):
    """Step 6: a unit that got fish while it had none becomes active: from preparing or fallow by an
    arrival, from any status that holds no fish when a void brings its fish back (the harvest that
    emptied it into cleaning, say). One that lost its last fish becomes fallow (from active) or is to be
    cleaned (from harvesting or quarantine); maintenance stays."""
    after = read.unit_counts(list(units))
    for unit in units.values():
        was, now = before.get(unit.pk, 0), after.get(unit.pk, 0)
        if now > 0 and unit.is_deleted:
            raise ValidationError({NON_FIELD_ERRORS: _('%(unit)s is deleted and would hold fish again: restore it '
                                                       'first.') % {'unit': unit.code}})
        status = None
        if not was and now and unit.status in NEEDS_NO_FISH:
            status = Status.ACTIVE
        elif was and not now:
            status = EMPTIED.get(unit.status)
        if status is None:
            continue
        with audit.source_language():
            old = audit.snapshot(unit, ['status', 'status_reason'])
            unit.status = status
            unit.updated_by = user
            unit.version += 1
            unit.save()
            audit.record_update(user, unit, old, audit.snapshot(unit, ['status', 'status_reason']))


def _describe(line):
    """One line of an operation for the activity log, in English like every log row."""
    text = f'{line.unit.code} · {line.batch.code}: '
    if line.kind == MovementKind.WEIGHING:
        text += f'weighed, average {line.avg_weight_g.normalize():f} g'
        if line.sample_count:
            text += f' ({line.sample_count} fish, {line.sample_weight_kg.normalize():f} kg)'
        return text
    text += f'{line.count_delta:+d} fish'
    if line.avg_weight_g is not None:
        text += f' at {line.avg_weight_g.normalize():f} g'
    if line.size_class:
        text += f', {line.size_class}'
    if line.reason:
        text += f', {audit.english(REASONS[line.kind](line.reason).label)}'
    if line.measured_weight_kg is not None:
        text += f', weighed {line.measured_weight_kg.normalize():f} kg'
    return text


def label(operation, lines=None):
    """How the activity log names an operation: what, where, which batch and when, so a search for a
    unit's or a batch's code finds it."""
    lines = lines if lines is not None else list(operation.movements.select_related('unit', 'batch'))
    units = ', '.join(dict.fromkeys(line.unit.code for line in lines))
    batches = ', '.join(dict.fromkeys(line.batch.code for line in lines))
    return f'{audit.english(operation.get_kind_display())} · {units} · {batches} · {operation.date.isoformat()}'


def _log(user, action, operation, assessment=None):
    """The operation's activity-log entry: what, when, its lines, where a harvest went, and the handling
    warnings the person went on past, which make the entry critical."""
    lines = list(operation.movements.select_related('unit', 'batch'))
    with audit.source_language():
        names = ['kind', 'date', 'notes', *(['over_capacity_ack'] if operation.over_capacity_ack else []),
                 *(['health_event'] if operation.health_event_id else [])]
        changes = {label_: [None, value] for label_, value in audit.snapshot(operation, names).items()
                   if value is not None}
        changes[str(_('Stock lines'))] = [None, '; '.join(_describe(line) for line in lines)]
        record = HarvestRecord.all_objects.filter(operation=operation).first()
        if record is not None:
            changes.update({label_: [None, value] for label_, value in audit.snapshot(
                record, ['facility', 'transport', 'vessel']).items() if value is not None})
        critical = assessment is not None and bool(assessment.warnings)
        if critical:
            changes[str(_('Handling warnings acknowledged'))] = [None, ' '.join(assessment.messages())]
        audit.record(user, action, operation, changes, label=label(operation, lines),
                     severity=AuditLog.Severity.CRITICAL if critical else AuditLog.Severity.NORMAL)


def voided(user, entry, reason, units, label, check=None, sites=()):
    """The void of a daily record, a stock operation, a feeding or a health record: one rule for all. It needs
    its reason, is refused when the record is voided already or dated (`entry.date`) before the backdating
    window of one of its units, or of one of `sites` (a health event of a whole site), then stops counting
    (soft-deleted, with its reason), `check()` runs without it, and the activity log says "Voided" with the
    reason. Inside the caller's transaction, with the record locked."""
    reason = reason.strip()
    if not reason:
        raise ValidationError({'reason': _('Say why it is voided.')})
    if entry.is_deleted:
        raise ValidationError({NON_FIELD_ERRORS: _('This operation is already voided.')})
    firsts = [earliest(unit) for unit in units] + [site_earliest(site) for site in sites]
    if any(entry.date < first for first in firsts):
        raise ValidationError({NON_FIELD_ERRORS: _(
            'Operations older than %(days)d days cannot be voided.') % {'days': settings.STOCK_BACKDATE_DAYS}})
    entry.void_reason = reason
    entry.soft_delete(user)
    if check is not None:
        check()
    with audit.source_language():
        audit.record(user, AuditLog.Action.VOID, entry, {str(_('Reason for voiding')): [None, reason]}, label=label)


# ---- the operations ------------------------------------------------------------------------------
def _quantize(grams):
    return Decimal(grams).quantize(GRAMS, rounding=ROUND_HALF_UP)


def record_input(user, *, species, input_stage, origin, day, lines, supplier=None, supplier_batch_ref='',
                 strain='', name='', expected_harvest_date=None, notes='', ack=False, token=None):
    """A new batch stocked into one or several units: `lines` = [(unit, fish, average weight in g)].
    The batch has no count of its own: its input lines are the count (STK-05)."""
    units = [unit for unit, _count, _weight in lines]
    if len(set(units)) != len(units):
        raise ValidationError({'unit': _('Each unit can be listed once.')})
    entries = [Entry(unit, None, MovementKind.INPUT, count, avg_weight_g=_quantize(weight))
               for unit, count, weight in lines]
    batch = NewBatch({'species': species, 'input_stage': input_stage, 'origin': origin,
                      'supplier': supplier, 'supplier_batch_ref': supplier_batch_ref, 'strain': strain,
                      'name': name, 'expected_harvest_date': expected_harvest_date, 'notes': notes})
    return _commit(user, OperationKind.INPUT, day, entries, ack=ack, token=token, new_batch=batch)


def _needs_notes(reason, notes):
    if reason == 'other' and not notes.strip():
        raise ValidationError({'notes': _('Say what it was: the reason is “other”.')})


def record_mortality(user, *, unit, batch, day, count, cause, measured_weight_kg=None, notes='', health_event=None,
                     token=None):
    """Fish found dead. They leave the book at the share's average; their weighed weight, when given,
    is kept as a separate fact. `health_event`: the event they died under, if any."""
    _needs_notes(cause, notes)
    entry = Entry(unit, batch, MovementKind.MORTALITY, -count, reason=cause, measured_weight_kg=measured_weight_kg)
    return _commit(user, OperationKind.MORTALITY, day, [entry], notes=notes, token=token, health_event=health_event)


def record_cull(user, *, unit, batch, day, count, reason, notes='', health_event=None, token=None):
    """Fish taken out and killed (too small, deformed, sick), at the share's average. `health_event`: the
    event they were culled under, if any."""
    _needs_notes(reason, notes)
    entry = Entry(unit, batch, MovementKind.CULL, -count, reason=reason)
    return _commit(user, OperationKind.CULL, day, [entry], notes=notes, token=token, health_event=health_event)


def record_weighing(user, *, unit, batch, day, avg_weight_g=None, sample_count=None, sample_weight_kg=None,
                    notes='', token=None):
    """A sample weighed: the average of the fish of the batch in the unit, given directly or as a number
    of fish and their weight together (the usual bulk weighing, STK-42). From that day the share's
    biomass is its count times this average."""
    if sample_count is not None and sample_weight_kg is not None:
        if avg_weight_g is not None:
            raise ValidationError({'avg_weight_g': _('Give the average or the sample, not both.')})
        avg_weight_g = _quantize(sample_weight_kg * 1000 / sample_count)
    elif avg_weight_g is None or sample_count is not None or sample_weight_kg is not None:
        raise ValidationError({'avg_weight_g': _('Give the average weight, or the number of fish weighed and their '
                                                 'weight together.')})
    entry = Entry(unit, batch, MovementKind.WEIGHING, 0, avg_weight_g=_quantize(avg_weight_g),
                  sample_count=sample_count, sample_weight_kg=sample_weight_kg)
    return _commit(user, OperationKind.WEIGHING, day, [entry], notes=notes, token=token)


def _destinations(source, units):
    """The units fish move into: each once, none of them the source."""
    if not units:
        raise ValidationError({'destinations': _('Choose the unit the fish go into.')})
    if source in units:
        raise ValidationError({'destinations': _('The fish cannot move into the unit they leave.')})
    if len(set(units)) != len(units):
        raise ValidationError({'destinations': _('Each unit can be listed once.')})


def record_transfer(user, *, source, batch, day, legs, reason, notes='', ack=False, handling_ack=None,
                    plan_item=None, token=None):
    """Fish of one batch moved out of `source` into one or several units: `legs` = [(unit, fish)]. A
    split is a transfer into several. Each leg is a pair of lines, out of the source and into its unit,
    whose fish add up to 0; the fish leave at the batch's average in the source and arrive with exactly
    the grams that left, so biomass is conserved too. The batch stays the same (owner decision Q7)."""
    _destinations(source, [unit for unit, _count in legs])
    _needs_notes(reason, notes)
    entries = []
    for pair, (unit, count) in enumerate(legs, start=1):
        entries.append(Entry(source, batch, MovementKind.TRANSFER_OUT, -count, pair=pair, reason=reason))
        entries.append(Entry(unit, batch, MovementKind.TRANSFER_IN, count, pair=pair))
    return _commit(user, OperationKind.TRANSFER, day, entries, notes=notes, ack=ack, token=token,
                   handling_ack=handling_ack, plan_item=plan_item)


def record_grading(user, *, source, batch, day, outputs, remainder_avg_weight_g=None, notes='', ack=False,
                   handling_ack=None, token=None):
    """The fish of one batch in `source` graded by size: `outputs` = [(unit, fish, measured average in g,
    size class)], each moved with its measured weight. A grading weighs the whole lot: the fish that stay
    in the source get their own measured average (required when any stay), so the outputs never take
    more than the book holds and the remainder never falls toward 0 g (the source's STK-24). The batch
    stays the same, the size class is on the line (owner decision Q6). One transaction for all outputs."""
    _destinations(source, [unit for unit, _count, _weight, _size in outputs])
    with transaction.atomic():
        locked(Batch, {batch.pk})
        locked(Tank, {source.pk, *(unit.pk for unit, *_rest in outputs)})
        staying = read.share_on(source.pk, batch.pk, day).count - sum(count for _unit, count, *_rest in outputs)
        if staying > 0 and remainder_avg_weight_g is None:
            raise ValidationError({'avg_weight_g': _('%(count)s fish stay in %(unit)s: weigh them too.') % {
                'count': number(staying), 'unit': source.code}})
        entries = []
        for pair, (unit, count, weight, size_class) in enumerate(outputs, start=1):
            entries.append(Entry(source, batch, MovementKind.TRANSFER_OUT, -count, avg_weight_g=_quantize(weight),
                                 pair=pair, reason=TransferReason.GRADING, size_class=size_class))
            entries.append(Entry(unit, batch, MovementKind.TRANSFER_IN, count, pair=pair, size_class=size_class))
        if staying > 0:
            entries.append(Entry(source, batch, MovementKind.WEIGHING, 0,
                                 avg_weight_g=_quantize(remainder_avg_weight_g)))
        return _commit(user, OperationKind.GRADING, day, entries, notes=notes, ack=ack, token=token,
                       handling_ack=handling_ack)


def record_harvest(user, *, unit, batch, day, count, measured_weight_kg, facility, transport=None, vessel='',
                   everything=False, notes='', handling_ack=None, plan_item=None, token=None):
    """Fish harvested: their count and their round (live) kilos as weighed, a fact of their own beside the
    book. The book loses the fish at the batch's average in the unit, and the last fish take whatever it
    holds, so a harvest is never refused for weighing more than the book says (the source's STK-29); the
    difference is the book's error. `everything`: the harvest empties the unit of this batch, and fish
    the book holds beyond the count are an unaccounted loss (a count adjustment of the same operation,
    taken before the harvest so the harvest takes the rest of the book). Where the fish went is its
    HarvestRecord: the slaughter facility (required), the transport supplier and the wellboat or vehicle."""
    with transaction.atomic():
        locked(Batch, {batch.pk})
        locked(Tank, {unit.pk})
        book = read.share_on(unit.pk, batch.pk, day).count
        if count > book:
            raise ValidationError({'count': _('Only %(available)s fish of %(batch)s are in %(unit)s on %(date)s.') % {
                'available': number(book), 'batch': batch.code, 'unit': unit.code, 'date': shown_date(day)}})
        entries = []
        if everything and count < book:
            entries.append(Entry(unit, batch, MovementKind.ADJUSTMENT, count - book,
                                 reason=AdjustmentReason.UNACCOUNTED_LOSS))
        entries.append(Entry(unit, batch, MovementKind.HARVEST, -count, measured_weight_kg=measured_weight_kg))
        return _commit(user, OperationKind.HARVEST, day, entries, notes=notes, token=token,
                       handling_ack=handling_ack, plan_item=plan_item,
                       harvest={'facility': facility, 'transport': transport, 'vessel': vessel.strip()})


def void(user, operation, reason):
    """The undo: the operation stops counting, with its reason. Refused when later operations need its
    fish (the message names them), and for operations older than the backdating window. Voiding a
    stocking voids its batch too: the batch exists only through it."""
    with transaction.atomic():
        operation = StockOperation.all_objects.select_for_update().get(pk=operation.pk)
        lines = list(operation.movements.select_related('unit', 'batch'))
        batches = locked(Batch, {line.batch_id for line in lines})
        units = locked(Tank, {line.unit_id for line in lines})
        before = read.unit_counts(list(units))
        voided(user, operation, reason, units.values(), label(operation, lines),
               check=lambda: _validate(set(batches), set(units), operation.date))
        _follow_status(user, units, before)
        if operation.kind == OperationKind.INPUT:
            for batch in batches.values():
                batch.soft_delete(user)
                with audit.source_language():
                    audit.record_delete(user, batch)
        return operation

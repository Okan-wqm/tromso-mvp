"""The write path of an experiment's design, places and life: every operation is one function here, inside one
transaction, locking the experiment row (last: the batches and tanks a service touches are locked before it, in
primary-key order, as the stock service does), refusing a form that was built on an older version, and writing one row of
the activity log on the experiment (labelled "Design", "Places", "Status": the person asks what changed on this
experiment, not on which table). A failure raises `ValidationError` on NON_FIELD_ERRORS, as `protocols.save_table`, and
nothing is written.

- `save_design`: the factors, groups, levels and replicates of a draft, saved as a whole, the grid's rows matched to the
  stored ones by their id (a renamed group keeps its replicates and the tanks placed in them);
- `save_places`, `randomise`, `move_span`: the tanks of a draft's replicates and the days they are booked to them;
- `start`: fixes the design and applies the diet through the farm's own assignments;
- `copy`: a new draft (or a template) with the design of another, never its tanks, allocation or team;
- `release_unit`, `replace_unit`: a tank leaves a running experiment, or is replaced by another, with its reason."""
import itertools
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import NON_FIELD_ERRORS, PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext as _, gettext_lazy

from core import audit, softdelete
from core.codes import next_code
from core.models import AuditLog, EntryKey
from farm.feeding import assignments
from farm.handling import check
from farm.models import Batch, FeedingProtocol, ProtocolAssignment, System, Tank
from farm.models.feeding_protocol import ProtocolStatus
from farm.stock.dates import site_today
from farm.stock.read import batches_ever_in
from farm.stock.services import locked as stock_locked

from . import allocation, read, sealing
from . import design as design_module
from .models import (
    DETAIL_FIELDS, TRANSITIONS, AllocationMethod, Experiment, ExperimentGroup, Factor, FactorKind, GroupLevel, GroupRole, Level,
    ExperimentShare, Member, Replicate, ReplicateSystem, ReplicateUnit, Status,
)

DESIGN = gettext_lazy('Design')


# ---- what the grid gives ------------------------------------------------------------------------
@dataclass
class FactorRow:
    name: str
    kind: str = FactorKind.OTHER
    unit: str = ''
    id: object = None            # the stored factor this row is; None for a new one


@dataclass
class Cell:
    """The level a group has of one factor: a protocol (the diet) or a label and an optional number; empty: none."""
    protocol: object = None
    label: str = ''
    value: Decimal = None

    @property
    def empty(self):
        return self.protocol is None and not self.label and self.value is None


@dataclass
class GroupRow:
    name: str
    role: str = GroupRole.TEST
    replicates: int = 1
    cells: list = field(default_factory=list)      # one Cell per factor, in the order of the factors
    id: object = None            # the stored group this row is; None for a new one


def _refused(*messages):
    return ValidationError({NON_FIELD_ERRORS: list(messages)})


def locked_draft(experiment, version):
    """The experiment, locked for this transaction, when it is a draft and `version` is the one the person's form was
    built on. A started experiment's design is fixed; the database refuses a change too (migration 0002)."""
    locked = Experiment.objects.select_for_update().filter(pk=experiment.pk).first()
    if locked is None:
        raise _refused(_('This experiment was deleted meanwhile.'))
    if locked.status != Status.DRAFT:
        raise _refused(_('The experiment has started: its design is fixed. Copy it to change the design.'))
    if version != locked.version:
        raise _refused(_('Someone else changed this experiment while you were editing it. The page now shows their '
                         'version; make your changes again.'))
    return locked


# ---- the design -----------------------------------------------------------------------------------
def describe(experiment):
    """The design as the activity log keeps it, in English: one line for the factors, one per group."""
    design = design_module.load(experiment)
    lines = []
    if design.factors:
        lines.append('Factors: ' + '; '.join(
            f'{factor.name} ({factor.get_kind_display().lower()}{", " + factor.unit if factor.unit else ""})'
            for factor in design.factors))
    for group in design.groups:
        cells = ', '.join(f'{factor.name} = {_level_text(design.level_of(group, factor))}' for factor in design.factors)
        count = len(design.replicates.get(group.pk, []))
        lines.append(f'{group.name} ({group.get_role_display().lower()}): {cells + "; " if cells else ""}'
                     f'{count} replicate{"" if count == 1 else "s"}')
    return '\n'.join(lines) or None


def _level_text(level):
    if level is None:
        return '–'
    if level.protocol_id:
        return level.protocol.name
    return f'{level.label} ({level.value.normalize():f})' if level.value is not None else level.label


def _check(experiment, stored_factors, stored_groups, factors, groups):
    """The rows the grid gave, checked as the database and the design need them; every message at once."""
    errors = []
    names = {}
    for row in factors:
        row.name = row.name.strip()
        if not row.name:
            errors.append(_('Every factor has a name.'))
        elif len(row.name) > Factor._meta.get_field('name').max_length:
            errors.append(_('The factor name %(name)s is too long.') % {'name': row.name})
        if row.name.casefold() in names:
            errors.append(_('Two factors are called %(name)s.') % {'name': row.name})
        names[row.name.casefold()] = row
        if row.kind not in FactorKind.values:
            errors.append(_('The kind of factor %(name)s is not one of the two.') % {'name': row.name})
        if row.kind == FactorKind.DIET and row.unit.strip():
            errors.append(_('The diet has no unit: its levels are protocols.'))
        if row.id is not None and row.id not in stored_factors:
            errors.append(_('Factor %(name)s was removed meanwhile: reload the page.') % {'name': row.name})
    if sum(row.kind == FactorKind.DIET for row in factors) > 1:
        errors.append(_('An experiment has one diet factor.'))
    group_names = set()
    for row in groups:
        row.name = row.name.strip()
        if not row.name:
            errors.append(_('Every group has a name.'))
        elif len(row.name) > ExperimentGroup._meta.get_field('name').max_length:
            errors.append(_('The group name %(name)s is too long.') % {'name': row.name})
        if row.name.casefold() in group_names:
            errors.append(_('Two groups are called %(name)s.') % {'name': row.name})
        group_names.add(row.name.casefold())
        if row.role not in GroupRole.values:
            errors.append(_('The role of group %(name)s is not one of the four.') % {'name': row.name})
        if not 1 <= row.replicates <= 99:
            errors.append(_('Group %(name)s has between 1 and 99 replicates.') % {'name': row.name})
        if row.id is not None and row.id not in stored_groups:
            errors.append(_('Group %(name)s was removed meanwhile: reload the page.') % {'name': row.name})
        if len(row.cells) != len(factors):
            errors.append(_('Group %(name)s has a cell for each factor.') % {'name': row.name})
    if errors:
        return errors
    used = {level.protocol_id for level in Level.objects.filter(factor__experiment=experiment, protocol__isnull=False)}
    usable = set(FeedingProtocol.objects.filter(status=ProtocolStatus.ACTIVE, species=experiment.species)
                 .values_list('pk', flat=True)) | used
    for group in groups:
        for factor, cell in zip(factors, group.cells):
            if factor.kind == FactorKind.DIET:
                if cell.protocol is not None and cell.protocol.pk not in usable:
                    errors.append(_('Group %(group)s: the protocol %(protocol)s cannot be used, only an active feeding '
                                    'protocol of %(species)s can.') % {'group': group.name, 'protocol': cell.protocol,
                                                                         'species': experiment.species})
                if cell.label or cell.value is not None:
                    errors.append(_('Group %(group)s: the diet is a protocol, not a label.') % {'group': group.name})
            else:
                if cell.protocol is not None:
                    errors.append(_('Group %(group)s: %(factor)s takes a label, not a protocol.') % {
                        'group': group.name, 'factor': factor.name})
                if cell.value is not None and not cell.label.strip():
                    errors.append(_('Group %(group)s: a level of %(factor)s with a value needs a label.') % {
                        'group': group.name, 'factor': factor.name})
                if len(cell.label) > Level._meta.get_field('label').max_length:
                    errors.append(_('Group %(group)s: the label %(label)s is too long.') % {'group': group.name,
                                                                                          'label': cell.label})
    return errors


def _remove(user, record):
    """Deletes a part of the design through the delete plan (one log row each), refused on a blocker."""
    plan = softdelete.plan_delete(record)
    if not plan.can_delete:
        raise _refused(*plan.blockers)
    softdelete.execute(plan, user)


def _park(model, records):
    """Gives live rows a name nobody has, so that renames that swap two names pass the unique constraint."""
    for record in records:
        model.objects.filter(pk=record.pk).update(name=f'~{uuid.uuid4().hex[:12]}')


def _touch(model, record, user, **values):
    model.objects.filter(pk=record.pk).update(updated_by=user, updated_at=timezone.now(), **values)


def save_design(user, experiment, factors, groups, version):
    """Replaces a draft's design with the grid's rows (`FactorRow`s and `GroupRow`s, the cells in the factors' order):
    factors, their levels (made from the cells, never listed alone: a diet level is the protocol, another level its
    label), groups with their replicates, and each group's level of each factor. Rows are matched to the stored ones by
    id, so a rename keeps a group's replicates and their tanks; a factor whose kind changed is a new factor. The
    replicates of a group are made equal to its count (1 to its count): the highest are removed, and never one that
    holds a tank. Logged on the experiment as "Design", before and after; the deletes the plan makes are logged per
    record. Refused for a started experiment or a stale `version`."""
    with transaction.atomic():
        locked = locked_draft(experiment, version)
        stored_factors = {factor.pk: factor for factor in Factor.objects.filter(experiment=locked)}
        stored_groups = {group.pk: group for group in ExperimentGroup.objects.filter(experiment=locked)}
        errors = _check(locked, stored_factors, stored_groups, factors, groups)
        if errors:
            raise _refused(*errors)
        with audit.source_language():
            before = describe(locked)
            _apply(user, locked, stored_factors, stored_groups, factors, groups)
            after = describe(locked)
            if before != after:
                locked.version += 1
                locked.updated_by = user
                locked.save(update_fields=['version', 'updated_by', 'updated_at'])
                audit.record(user, AuditLog.Action.UPDATE, locked, {str(DESIGN): [before, after]})
        return locked


def _apply(user, experiment, stored_factors, stored_groups, factors, groups):
    GroupLevel.objects.filter(experiment=experiment).delete()           # rebuilt from the cells at the end
    # The factors: a stored one is kept by its id unless its kind changed; the others are removed.
    kept, removed = {}, dict(stored_factors)
    for index, row in enumerate(factors):
        factor = removed.get(row.id) if row.id is not None else None
        if factor is not None and factor.kind == row.kind:
            kept[index] = removed.pop(factor.pk)
    for factor in removed.values():
        _remove(user, factor)
    _park(Factor, [factor for index, factor in kept.items() if factors[index].name != factor.name])
    objects = {}
    for index, row in enumerate(factors):
        if index in kept:
            factor = kept[index]
            _touch(Factor, factor, user, name=row.name, unit=row.unit.strip(), position=index)
        else:
            factor = Factor.objects.create(experiment=experiment, name=row.name, kind=row.kind, unit=row.unit.strip(),
                                           position=index, created_by=user, updated_by=user)
        objects[index] = factor
    levels = {index: _levels_of(user, objects[index], factors[index], groups, index) for index in objects}
    # The groups: by id; a removed one must hold no tank.
    wanted = {row.id for row in groups if row.id is not None}
    for group in [group for pk, group in stored_groups.items() if pk not in wanted]:
        if ReplicateUnit.objects.filter(replicate__group=group).exists():
            raise _refused(_('Group %(group)s has tanks placed: take them out on the Places tab before removing '
                             'it.') % {'group': group.name})
        _remove(user, group)
    _park(ExperimentGroup, [stored_groups[row.id] for row in groups
                            if row.id is not None and stored_groups[row.id].name != row.name])
    for position, row in enumerate(groups):
        if row.id is not None:
            group = stored_groups[row.id]
            _touch(ExperimentGroup, group, user, name=row.name, role=row.role, position=position)
        else:
            group = ExperimentGroup.objects.create(experiment=experiment, name=row.name, role=row.role,
                                                   position=position, created_by=user, updated_by=user)
        _slots(user, group, row.replicates)
        rows = []
        for index, cell in enumerate(row.cells):
            level = levels[index].get(_cell_key(factors[index], cell))
            if level is not None:
                rows.append(GroupLevel(experiment=experiment, group=group, factor=objects[index], level=level))
        GroupLevel.objects.bulk_create(rows)


def _cell_key(factor, cell):
    """What makes two cells one level of a factor: the protocol of the diet, the label (in any case) of another."""
    if factor.kind == FactorKind.DIET:
        return cell.protocol.pk if cell.protocol is not None else None
    return cell.label.strip().casefold() or None


def _levels_of(user, factor, row, groups, index):
    """The levels the cells ask of a factor: {cell key: Level}, the stored ones kept (a label's case and number
    updated), the missing ones made, the ones no cell asks for removed."""
    asked = {}
    for group in groups:
        cell = group.cells[index]
        key = _cell_key(row, cell)
        if key is None:
            continue
        label, value = cell.label.strip(), cell.value
        if key in asked and asked[key][1] != value:
            raise _refused(_('The level %(label)s of %(factor)s has two different values.') % {
                'label': label, 'factor': row.name})
        asked.setdefault(key, (label, value, cell.protocol))
    found = {}
    for level in Level.objects.filter(factor=factor).select_related('protocol'):
        key = level.protocol_id if factor.kind == FactorKind.DIET else level.label.casefold()
        if key in asked:
            label, value, _protocol = asked[key]
            if factor.kind == FactorKind.OTHER and (level.label, level.value) != (label, value):
                _touch(Level, level, user, label=label, value=value)
            found[key] = level
        else:
            _remove(user, level)
    for key, (label, value, protocol) in asked.items():
        if key not in found:
            found[key] = Level.objects.create(factor=factor, label='' if protocol else label, protocol=protocol,
                                              value=None if protocol else value, created_by=user, updated_by=user)
    return found


def _slots(user, group, count):
    """The group's replicates are 1 to `count`: the missing ones are made, the highest are removed if they hold no tank."""
    stored = {replicate.number: replicate for replicate in Replicate.objects.filter(group=group)}
    for number in range(1, count + 1):
        if number not in stored:
            Replicate.objects.create(group=group, number=number, created_by=user, updated_by=user)
    for number in sorted((n for n in stored if n > count), reverse=True):
        if ReplicateUnit.objects.filter(replicate=stored[number]).exists():
            raise _refused(_('Replicate %(group)s R%(number)d holds tanks: take them out on the Places tab before '
                             'removing it.') % {'group': group.name, 'number': number})
        _remove(user, stored[number])


# ---- the places -----------------------------------------------------------------------------------
PLACES = gettext_lazy('Places')
ALLOCATION = gettext_lazy('Allocation')
SEED_LIMIT = 2 ** 63                       # the seed is a bigint


@dataclass
class Place:
    """The tanks of one replicate and the days they are booked to it (both included); no days: the whole span. `systems`:
    the systems booked whole (a system and each system nested in it, a booking each); their tanks are among `tanks`."""
    replicate: object
    tanks: list = field(default_factory=list)
    first: object = None
    last: object = None
    systems: list = field(default_factory=list)


def whole(system):
    """A system booked whole: itself and every system nested in it, each a booking of its own."""
    return [system, *system.descendants()]


def span_of(starts_on, duration_days):
    """(day 0, last day): the baseline weighing and the final one, on the site's clock; None without a day 0."""
    if starts_on is None or duration_days is None:
        return None
    return starts_on, starts_on + timedelta(days=duration_days)


def span(experiment):
    """The span of an experiment (`span_of` its day 0 and duration)."""
    return span_of(experiment.starts_on, experiment.duration_days)


def tanks_of(item):
    """The tanks of a pool item: a tank is itself, a system the live tanks of it and of every system nested in it (a
    system is only a shortcut: what is stored is its tanks, because `Tank.system` changes and keeps no history)."""
    if isinstance(item, Tank):
        return [item]
    systems = [item, *item.descendants()]
    return list(Tank.objects.filter(system__in=systems).select_related('production_department__site').order_by('code'))


def describe_places(experiment):
    """The placements as the activity log keeps them, in English: one line a replicate with tanks."""
    lines = []
    for replicate, rows in itertools.groupby(read.cells(experiment), key=lambda cell: cell.replicate):
        rows = list(rows)
        windows = {(row.first, row.last) for row in rows}
        days = f' ({rows[0].first.isoformat()} to {rows[0].last.isoformat()})' if len(windows) == 1 else ''
        tanks = ', '.join(row.unit.code if len(windows) == 1 else
                          f'{row.unit.code} ({row.first.isoformat()} to {row.last.isoformat()})' for row in rows)
        systems = ', '.join(booking.system.code for booking in ReplicateSystem.objects.filter(replicate=replicate)
                            .select_related('system').order_by('system__code'))
        whole_systems = f' (whole: {systems})' if systems else ''
        lines.append(f'{replicate.group.name} R{replicate.number}: {tanks}{days}{whole_systems}')
    return '\n'.join(lines) or None


def describe_allocation(experiment):
    if experiment.allocation_method == AllocationMethod.RANDOMISED:
        return f'Randomised, seed {experiment.allocation_seed}'
    if experiment.allocation_method == AllocationMethod.MANUAL:
        return f'Placed by hand: {experiment.allocation_note}'
    return None


def _wanted(experiment, places):
    """[(replicate, tank, first, last)] of the places, each checked: the replicate is the experiment's, the tank is
    live and on its site, the days are inside the span and in order, and no tank is in two places on one day. Every fault
    at once; the booking by another experiment is checked by `_check_booked`."""
    errors, wanted = [], []
    window = span(experiment)
    if window is None:
        raise _refused(_('Set day 0 on the Details tab first: a tank is booked for days.'))
    replicates = {replicate.pk: replicate for replicate in Replicate.objects.filter(group__experiment=experiment)}
    for place in places:
        replicate = replicates.get(place.replicate.pk)
        if replicate is None:
            errors.append(_('A replicate was removed meanwhile: reload the page.'))
            continue
        first, last = place.first or window[0], place.last or window[1]
        label = f'{replicate.group.name} R{replicate.number}'
        if first > last:
            errors.append(_('%(replicate)s: the last day comes on or after the first day.') % {'replicate': label})
        elif first < window[0] or last > window[1]:
            errors.append(_('%(replicate)s: the days are outside the experiment (%(first)s to %(last)s).') % {
                'replicate': label, 'first': window[0].isoformat(), 'last': window[1].isoformat()})
        for tank in place.tanks:
            if tank.is_deleted:
                errors.append(_('%(tank)s was deleted meanwhile.') % {'tank': tank.code})
            elif tank.production_department.site_id != experiment.site_id:
                errors.append(_('%(tank)s is not on the site of the experiment (%(site)s).') % {
                    'tank': tank.code, 'site': experiment.site.name})
            wanted.append((replicate, tank, first, last))
    seen = {}
    for replicate, tank, first, last in wanted:
        for other_first, other_last, other in seen.get(tank.pk, []):
            if first <= other_last and other_first <= last:
                errors.append(_('%(tank)s is placed twice on some of the same days (%(first)s, %(second)s).') % {
                    'tank': tank.code, 'first': other, 'second': f'{replicate.group.name} R{replicate.number}'})
        seen.setdefault(tank.pk, []).append((first, last, f'{replicate.group.name} R{replicate.number}'))
    if errors:
        raise _refused(*dict.fromkeys(errors))
    return wanted


def _check_booked(experiment, wanted, systems=()):
    """No tank and no whole system is booked to another experiment on a day it is asked for here, said with the days
    the other booking holds (read.booked_text, never which experiment); the exclusion constraints hold it for any
    writer."""
    errors = []
    for replicate, tank, first, last in wanted:
        days = read.booked([tank.pk], first, last, exclude=experiment).get(tank.pk)
        if days is not None:
            errors.append(read.booked_text(tank.code, days))
    for replicate, system, first, last in systems:
        days = read.booked_systems([system.pk], first, last, exclude=experiment).get(system.pk)
        if days is not None:
            errors.append(read.booked_text(system.code, days))
    if errors:
        raise _refused(*dict.fromkeys(errors))


def _wanted_systems(experiment, places):
    """[(replicate, system, first, last)]: the whole systems of the places, on the places' days (checked by `_wanted`)."""
    window = span(experiment)
    return [(place.replicate, system, place.first or window[0], place.last or window[1])
            for place in places for system in place.systems]


BOOKED_MEANWHILE = gettext_lazy('A tank or a system was booked by another experiment meanwhile: look at the places and '
                                'try again.')


def _write_places(user, experiment, wanted, systems=()):
    """Replaces the draft's placements and whole-system bookings with `wanted` and `systems`: those already there are
    kept, the others removed and the new ones made, and each placement of a tank of a booked system is tagged with its
    booking. A draft's placements are not evidence (the trigger lets a draft delete them): they are removed for good,
    and the change is the one "Places" row on the experiment."""
    placements = ReplicateUnit.objects.filter(replicate__group__experiment=experiment)
    bookings = ReplicateSystem.objects.filter(replicate__group__experiment=experiment)
    placements.update(booking=None)                     # tagged again below, once the bookings are what is asked
    current = {(row.replicate_id, row.unit_id, row.from_on, row.until_on): row for row in placements}
    keep = {(replicate.pk, tank.pk, first, last) for replicate, tank, first, last in wanted}
    ReplicateUnit.objects.filter(pk__in=[row.pk for key, row in current.items() if key not in keep]).delete()
    stored = {(row.replicate_id, row.system_id, row.from_on, row.until_on): row for row in bookings}
    asked = {(replicate.pk, system.pk, first, last) for replicate, system, first, last in systems}
    ReplicateSystem.objects.filter(pk__in=[row.pk for key, row in stored.items() if key not in asked]).delete()
    fresh = [ReplicateUnit(replicate=replicate, unit=tank, from_on=first, until_on=last, created_by=user,
                           updated_by=user)
             for replicate, tank, first, last in wanted if (replicate.pk, tank.pk, first, last) not in current]
    new_bookings = [ReplicateSystem(replicate=replicate, system=system, from_on=first, until_on=last, created_by=user,
                                    updated_by=user)
                    for replicate, system, first, last in systems if (replicate.pk, system.pk, first, last) not in stored]
    try:
        with transaction.atomic():
            ReplicateSystem.objects.bulk_create(new_bookings)
            ReplicateUnit.objects.bulk_create(fresh)
            _tag(experiment)
    except IntegrityError:
        raise _refused(BOOKED_MEANWHILE)


def _tag(experiment):
    """Tags each placement of a tank whose system is booked whole, by the same replicate on days that hold it, with that
    booking (the database checks the tag)."""
    bookings = ReplicateSystem.objects.filter(replicate__group__experiment=experiment)
    for booking in bookings:
        ReplicateUnit.objects.filter(replicate_id=booking.replicate_id, unit__system_id=booking.system_id,
                                     from_on__gte=booking.from_on, until_on__lte=booking.until_on).update(booking=booking)


def _lock_tanks(places):
    """The tanks of the places locked in primary-key order (the order of every writer: the stock service's), so that two
    experiments enrolling one tank take turns and the second is told whose it is; deleted ones too."""
    pks = {tank.pk for place in places for tank in place.tanks}
    locked = stock_locked(Tank, pks)
    for place in places:
        place.tanks = [locked.get(tank.pk, tank) for tank in place.tanks]
    return locked


def save_places(user, experiment, places, version, note=''):
    """Places the tanks of a draft: `places` are the `Place`s of its replicates (a replicate not named has none), saved as
    a whole. A system in the form is the tanks of it and of the systems nested in it (`tanks_of`), expanded before the
    call. The tanks and the experiment are locked (tanks first, in primary-key order, the experiment last), the sites,
    the span, the days and the bookings are checked and named, and the allocation becomes "placed by hand" with its
    reason `note`, which is needed (unless nothing changed, or nothing is placed). Logged on the experiment as "Places"
    and "Allocation", before and after."""
    with transaction.atomic():
        _lock_tanks(places)
        locked = locked_draft(experiment, version)
        if locked.is_template:
            raise _refused(_('A template has no tanks: it is a design to copy.'))
        wanted = _wanted(locked, places)
        systems = _wanted_systems(locked, places)
        _check_booked(locked, wanted, systems)
        note = note.strip()
        with audit.source_language():
            before, before_allocation = describe_places(locked), describe_allocation(locked)
            changed = {(r.pk, t.pk, f, l) for r, t, f, l in wanted} != {
                (row.replicate_id, row.unit_id, row.from_on, row.until_on)
                for row in ReplicateUnit.objects.filter(replicate__group__experiment=locked)} or {
                (r.pk, system.pk, f, l) for r, system, f, l in systems} != {
                (row.replicate_id, row.system_id, row.from_on, row.until_on)
                for row in ReplicateSystem.objects.filter(replicate__group__experiment=locked)}
            if changed and wanted and not note:
                raise _refused(_('Say why the tanks are placed by hand: a placement that is not randomised is '
                                 'registered with its reason.'))
            if changed:
                _write_places(user, locked, wanted, systems)
                _set_allocation(locked, AllocationMethod.MANUAL if wanted else AllocationMethod.NONE,
                                note=note if wanted else '')
            elif note and locked.allocation_method == AllocationMethod.MANUAL:
                _set_allocation(locked, AllocationMethod.MANUAL, note=note)          # the reason, put better
            return _log_places(user, locked, before, before_allocation)


def _set_allocation(experiment, method, seed=None, note=''):
    experiment.allocation_method, experiment.allocation_seed, experiment.allocation_note = method, seed, note


def _log_places(user, experiment, before, before_allocation):
    """Bumps the version and logs "Places" and "Allocation", when either changed; returns the experiment."""
    after, after_allocation = describe_places(experiment), describe_allocation(experiment)
    changes = {}
    if before != after:
        changes[str(PLACES)] = [before, after]
    if before_allocation != after_allocation:
        changes[str(ALLOCATION)] = [before_allocation, after_allocation]
    if changes:
        experiment.version += 1
        experiment.updated_by = user
        experiment.save(update_fields=['allocation_method', 'allocation_seed', 'allocation_note', 'version',
                                       'updated_by', 'updated_at'])
        audit.record(user, AuditLog.Action.UPDATE, experiment, changes)
    return experiment


def randomise(user, experiment, pool, seed, version):
    """Deals the tanks of `pool` (tanks and systems of the site) to the replicates of a draft by the seeded method
    `sha256_v1` (experiments/allocation.py): as many items as replicates, each item the tanks of a tank or a system,
    booked for the whole span; the method and the seed are stored with the placements, so the deal can be repeated and
    checked. The same checks and locks as `save_places`."""
    if not isinstance(seed, int) or not 0 <= seed < SEED_LIMIT:
        raise _refused(_('The seed is a whole number from 0 to %(top)d.') % {'top': SEED_LIMIT - 1})
    items = {}
    errors = []
    for item in pool:
        code = item.code
        if code in items:
            errors.append(_('Two items of the pool have the code %(code)s.') % {'code': code})
        items[code] = item
    if errors:
        raise _refused(*errors)
    tanks = {code: tanks_of(item) for code, item in items.items()}
    for code, found in tanks.items():
        if not found:
            errors.append(_('%(code)s has no tank.') % {'code': code})
    counted = [tank.pk for found in tanks.values() for tank in found]
    errors += [_('%(tank)s is in the pool twice (alone and through a system).') % {'tank': tank.code}
               for tank in {tank.pk: tank for found in tanks.values() for tank in found}.values()
               if counted.count(tank.pk) > 1]
    if errors:
        raise _refused(*errors)
    with transaction.atomic():
        places = [Place(None, found, systems=whole(items[code]) if isinstance(items[code], System) else [])
                  for code, found in tanks.items()]
        _lock_tanks(places)
        locked = locked_draft(experiment, version)
        if locked.is_template:
            raise _refused(_('A template has no tanks: it is a design to copy.'))
        slots = [(group, replicate) for group in ExperimentGroup.objects.filter(experiment=locked)
                 .order_by('position', 'name') for replicate in Replicate.objects.filter(group=group)
                 .order_by('number')]
        if not slots:
            raise _refused(_('The design has no replicate to place tanks in.'))
        if len(items) != len(slots):
            raise _refused(_('The pool has %(items)d items for %(slots)d replicates: choose as many tanks or systems as '
                             'there are replicates.') % {'items': len(items), 'slots': len(slots)})
        dealt = allocation.deal(list(items), [replicate for _group, replicate in slots], seed)
        by_code = {code: place for code, place in zip(tanks, places)}
        for replicate, code in dealt:
            by_code[code].replicate = replicate
        wanted = _wanted(locked, places)
        systems = _wanted_systems(locked, places)
        _check_booked(locked, wanted, systems)
        with audit.source_language():
            before, before_allocation = describe_places(locked), describe_allocation(locked)
            _write_places(user, locked, wanted, systems)
            _set_allocation(locked, AllocationMethod.RANDOMISED, seed=seed)
            return _log_places(user, locked, before, before_allocation)


def move_span(user, experiment, old_span):
    """After a draft's day 0 or duration changed (inside the saving transaction): the windows that equalled the old span
    move to the new one, the others stay (a window of its own days is the person's; the design says when it is outside the
    span). Logged on the experiment as "Places". `old_span` is (first, last) before the change, or None."""
    new = span(experiment)
    if old_span is None or new is None or old_span == new or experiment.status != Status.DRAFT:
        return
    rows = list(ReplicateUnit.objects.filter(replicate__group__experiment=experiment, from_on=old_span[0],
                                             until_on=old_span[1]))
    if not rows:
        return
    with audit.source_language():
        before = describe_places(experiment)
        ReplicateUnit.objects.filter(replicate__group__experiment=experiment).update(booking=None)
        ReplicateSystem.objects.filter(replicate__group__experiment=experiment, from_on=old_span[0],
                                       until_on=old_span[1]).update(from_on=new[0], until_on=new[1], updated_by=user,
                                                                    updated_at=timezone.now())
        ReplicateUnit.objects.filter(pk__in=[row.pk for row in rows]).update(
            from_on=new[0], until_on=new[1], updated_by=user, updated_at=timezone.now())
        _tag(experiment)
        audit.record(user, AuditLog.Action.UPDATE, experiment, {str(PLACES): [before, describe_places(experiment)]})


def clashes_when_moved(experiment, old_span, new):
    """{tank: (first, last) of the other booking} for the placements that would move with the span (they equal the old
    one) and meet another experiment's booking on the new days: what the form says on the field before it saves."""
    if old_span is None or new is None or old_span == new:
        return {}
    units = list(ReplicateUnit.objects.filter(replicate__group__experiment=experiment, from_on=old_span[0],
                                              until_on=old_span[1]).select_related('unit'))
    found = {}
    for row in units:
        other = read.booked([row.unit_id], new[0], new[1], exclude=experiment).get(row.unit_id)
        if other is not None:
            found[row.unit] = other
    return found


# ---- starting ------------------------------------------------------------------------------------
STATUS = gettext_lazy('Status')
ACKNOWLEDGED = gettext_lazy('Warnings acknowledged')


def _diet_rows(experiment):
    """The assignment rows the experiment's diet asks for (farm/feeding/assignments.py, the rows the dialog would write):
    for every group with a diet level, its protocol on each of its tanks, unit by unit, for the days the tank is booked.
    Every fault at once, a tank by its code."""
    design = design_module.load(experiment)
    diet = next((factor for factor in design.factors if factor.kind == FactorKind.DIET), None)
    made, errors = [], []
    if diet is None:
        return made
    for group in design.groups:
        level = design.level_of(group, diet)
        if level is None or level.protocol is None:
            continue
        by_days = {}
        for replicate in design.replicates.get(group.pk, []):
            for row in design.placements.get(replicate.pk, []):
                by_days.setdefault((row.from_on, row.until_on), []).append(row.unit)
        for (first, last), units in by_days.items():
            rows, found = assignments.rows(level.protocol, units, None, first, last,
                                           notes=f'{experiment.code} · {group.name}')
            made.extend(rows)
            errors.extend(f'{error.unit.code if error.unit else group.name}: {error.message}' for error in found)
    if errors:
        raise _refused(*dict.fromkeys(errors))
    return made


def start(user, experiment, seen, version):
    """Starts a draft: its design is fixed from now on (the triggers hold it for any writer), and the diet is applied.
    The experiment must have no error (`design.problems`, which includes a unit's own assignment that stands in the way:
    starting never ends another record), and the person must have acknowledged the warnings they were shown (`seen`, their
    fingerprint: a start whose warnings changed meanwhile is asked again, on the field `start_ack`). For every group with
    a diet level the farm's own assignment rows are written (unit scope, from the first to the last day of each placement,
    through `farm.feeding.assignments`, each logged as the dialog logs them), so the meal board follows the diet; they
    are found later by (unit, protocol, first day), with no link column. The batches the tanks held, the tanks and then
    the experiment are locked, in that order. Logged on the experiment as "Status", with the warnings acknowledged."""
    with transaction.atomic():
        unit_ids = set(ReplicateUnit.objects.filter(replicate__group__experiment=experiment)
                       .values_list('unit_id', flat=True))
        stock_locked(Batch, batches_ever_in(unit_ids))
        stock_locked(Tank, unit_ids)
        locked = locked_draft(experiment, version)
        if locked.is_template:
            raise _refused(_('A template is not started: copy it into an experiment.'))
        if Status.RUNNING not in TRANSITIONS[locked.status]:
            raise _refused(_('This experiment cannot be started.'))
        _may_seal_past(user, locked, locked.audience)
        assessment = design_module.assess(locked)
        if assessment.errors:
            raise _refused(*[finding.text for finding in assessment.errors])
        check.require_acknowledged(assessment, seen, field='start_ack', user=user)
        warned = []
        if assessment.warnings:
            with audit.source_language():                          # the log is English at rest
                warned = [finding.text for finding in design_module.assess(locked).warnings]
        rows = _diet_rows(locked)
        try:
            assignments.save(user, rows)
        except IntegrityError:
            raise _refused(_('Another protocol was assigned to these tanks meanwhile: look at the assignments and try '
                             'again.'))
        locked.status = Status.RUNNING
        locked.version += 1
        locked.updated_by = user
        locked.save(update_fields=['status', 'version', 'updated_by', 'updated_at'])
        with audit.source_language():
            changes = {str(STATUS): [audit.message(Status.DRAFT.label), audit.message(Status.RUNNING.label)]}
            if warned:
                changes[str(ACKNOWLEDGED)] = [None, '\n'.join(warned)]
            audit.record(user, AuditLog.Action.UPDATE, locked, changes)
        return locked


# ---- copying ------------------------------------------------------------------------------------
def copy(user, source, name, starts_on=None, as_template=False, token=None):
    """A new draft with the design of `source` (an experiment of any status, or a template): the factors, the levels (the
    same feeding-protocol rows, so a repeat of a started experiment feeds identically: an assigned protocol is frozen),
    the groups with their levels and as many empty replicates as they had; never the placements, the allocation or its
    seed, or the team, but the copier, who leads it. `as_template` makes a design to copy (no day 0); else `starts_on` is
    the new day 0, which may be left for later. `copied_from` says where it came from. The number comes from
    core.codes.next_code inside the transaction; a form sent twice (`token`) makes one copy. Logged as created, with
    its design, and the copier's team row as any other."""
    with transaction.atomic():
        # The source first, as every write path takes its locks before it looks the form's key up: the same form sent
        # twice at once waits here for the first sending and then finds its copy.
        source = Experiment.all_objects.select_for_update(of=('self',)).get(pk=source.pk)
        if token is not None:
            sent = EntryKey.record_of(token, Experiment)
            if sent is not None:
                return sent
        name = name.strip()
        if not name:
            raise _refused(_('The copy needs a name.'))
        if len(name) > Experiment._meta.get_field('name').max_length:
            raise _refused(_('The name of the copy is too long.'))
        if source.is_deleted:
            raise _refused(_('This experiment was deleted meanwhile.'))
        new = Experiment(
            code=next_code(Experiment, f'E-{site_today(source.site).year}-'), name=name, is_template=as_template,
            site=source.site, species=source.species, hypothesis=source.hypothesis,
            primary_endpoint=source.primary_endpoint, starts_on=None if as_template else starts_on,
            duration_days=source.duration_days, notes=source.notes, copied_from=source,
            created_by=user, updated_by=user)
        new.full_clean(exclude=['code'])
        new.save()
        if token is not None:
            EntryKey.note(token, new)
        factors, levels = {}, {}
        for factor in Factor.objects.filter(experiment=source):
            factors[factor.pk] = Factor.objects.create(
                experiment=new, name=factor.name, kind=factor.kind, unit=factor.unit, position=factor.position,
                created_by=user, updated_by=user)
            for level in Level.objects.filter(factor=factor):
                levels[level.pk] = Level.objects.create(
                    factor=factors[factor.pk], label=level.label, protocol=level.protocol, value=level.value,
                    created_by=user, updated_by=user)
        for group in ExperimentGroup.objects.filter(experiment=source):
            made = ExperimentGroup.objects.create(experiment=new, name=group.name, role=group.role,
                                                  position=group.position, created_by=user, updated_by=user)
            for replicate in Replicate.objects.filter(group=group):
                Replicate.objects.create(group=made, number=replicate.number, created_by=user, updated_by=user)
            GroupLevel.objects.bulk_create([
                GroupLevel(experiment=new, group=made, factor=factors[row.factor_id], level=levels[row.level_id])
                for row in GroupLevel.objects.filter(group=group)
                if row.factor_id in factors and row.level_id in levels])
        with audit.source_language():
            values = audit.snapshot(new, [*DETAIL_FIELDS, 'copied_from'])
            values[str(DESIGN)] = describe(new)
            audit.record_create(user, new, values)
        return new


# ---- amending a running experiment ---------------------------------------------------------------------
LEFT = gettext_lazy('Reason it left')


def _locked_running(experiment, version):
    """The experiment, locked for this transaction, when it is running and `version` is the one the person's form was built
    on. A running experiment's design is fixed, but a tank may leave or be replaced (the trigger lets a placement get
    shorter and a replacement come in, migration 0002)."""
    locked = Experiment.objects.select_for_update().filter(pk=experiment.pk).first()
    if locked is None:
        raise _refused(_('This experiment was deleted meanwhile.'))
    if locked.status != Status.RUNNING:
        raise _refused(_('The experiment is not running: only a running experiment has tanks to release or replace.'))
    if version != locked.version:
        raise _refused(_('Someone else changed this experiment while you were editing it. The page now shows their '
                         'version; make your changes again.'))
    return locked


def _the_placement(experiment, placement, reason):
    """The placement as it is now, with its group's diet protocol (None without a diet), checked to be the experiment's, live
    and still booked ahead; the reason, cut of its spaces, is needed."""
    reason = reason.strip()
    if not reason:
        raise _refused(_('Say why: a tank that leaves, or is replaced, is registered with its reason.'))
    if len(reason) > ReplicateUnit._meta.get_field('left_reason').max_length:
        raise _refused(_('The reason is too long.'))
    row = (ReplicateUnit.objects.select_related('replicate__group', 'unit__production_department__site')
           .filter(pk=placement.pk, replicate__group__experiment=experiment).first())
    if row is None:
        raise _refused(_('This placement was removed meanwhile: reload the page.'))
    diet = (GroupLevel.objects.filter(group=row.replicate.group, factor__kind=FactorKind.DIET)
            .select_related('level__protocol').first())
    return row, reason, diet.level.protocol if diet is not None else None


def _end_diet(user, row, protocol, last_day):
    """The assignment rows the start wrote for this placement (unit scope, its protocol, its first day: found by those, there
    is no link column) end on `last_day`."""
    if protocol is None:
        return
    for assignment in ProtocolAssignment.objects.filter(unit=row.unit, batch__isnull=True, protocol=protocol,
                                                        valid_from=row.from_on):
        assignments.end(user, assignment, last_day)


def _log_amendment(user, experiment, before, reason, unit):
    after = describe_places(experiment)
    experiment.version += 1
    experiment.updated_by = user
    experiment.save(update_fields=['version', 'updated_by', 'updated_at'])
    audit.record(user, AuditLog.Action.UPDATE, experiment, {
        str(PLACES): [before, after], str(LEFT): [None, f'{unit.code}: {reason}']})


def release_unit(user, placement, last_day, reason, version):
    """A tank leaves a running experiment: its placement ends on `last_day` (the last day it was in it; never later than
    it was, never before the placement began, and yesterday at the earliest, the farm's rule for ending a row that has
    started), with the `reason`, which is needed. The diet's assignment row for it ends the same day (the farm's own
    `assignments.end`, logged as an edit of the assignment). The replicate keeps its number, and what the tank gave up to
    its last day stays in its figures. Logged on the experiment as "Places" and "Reason it left"; the tank is locked before
    the experiment."""
    experiment = placement.replicate.group.experiment
    with transaction.atomic():
        stock_locked(Tank, {placement.unit_id})
        locked = _locked_running(experiment, version)
        row, reason, protocol = _the_placement(locked, placement, reason)
        yesterday = site_today(locked.site) - timedelta(days=1)
        if last_day < row.from_on:
            raise _refused(_('The last day comes on or after the first day (%(day)s).') % {'day': row.from_on.isoformat()})
        if last_day >= row.until_on:
            raise _refused(_('The tank is booked until %(day)s already: a placement is only ever shortened.') % {
                'day': row.until_on.isoformat()})
        if last_day < yesterday:
            raise _refused(_('The days before yesterday keep what happened in them: a tank leaves yesterday at the '
                             'earliest.'))
        with audit.source_language():
            before = describe_places(locked)
            ReplicateUnit.objects.filter(pk=row.pk).update(
                until_on=last_day, left_reason=reason, version=row.version + 1, updated_by=user,
                updated_at=timezone.now())
            _end_diet(user, row, protocol, last_day)
            _log_amendment(user, locked, before, reason, row.unit)
        return locked


def replace_unit(user, placement, new_unit, from_day, reason, version):
    """A tank in a running experiment is replaced by another: the placement ends the day before `from_day` (with the `reason`,
    which is needed) and `new_unit` takes its replicate's place from `from_day` to the day the old one was booked to,
    so the replicate keeps its number. `from_day` is today at the earliest (the old tank's last day is then yesterday at
    the earliest) and after the placement began. The new tank must be on the site and free of every booking for those
    days (another experiment's, named by its number, or this one's own), and its own feeding assignments must not stand
    in the way of the diet (`design.feeding_conflicts`); the diet's rows are ended for the old tank and written for
    the new one through the farm's own assignments. A replacement with no weighing at the move leaves a gap in the
    replicate's feed conversion window: the overview says so. Logged on the experiment as "Places" and "Reason it left";
    the batches the new tank held, the tanks and then the experiment are locked, in that order."""
    experiment = placement.replicate.group.experiment
    with transaction.atomic():
        stock_locked(Batch, batches_ever_in({new_unit.pk}))
        stock_locked(Tank, {placement.unit_id, new_unit.pk})
        locked = _locked_running(experiment, version)
        row, reason, protocol = _the_placement(locked, placement, reason)
        new_unit = Tank.objects.select_related('production_department__site').filter(pk=new_unit.pk).first()
        errors = []
        if new_unit is None:
            raise _refused(_('The new tank was deleted meanwhile.'))
        if new_unit.pk == row.unit_id:
            errors.append(_('The new tank is the one that leaves.'))
        if new_unit.production_department.site_id != locked.site_id:
            errors.append(_('%(tank)s is not on the site of the experiment (%(site)s).') % {
                'tank': new_unit.code, 'site': locked.site.name})
        today = site_today(locked.site)
        if from_day < today:
            errors.append(_('The new tank comes in today at the earliest.'))
        if from_day <= row.from_on:
            errors.append(_('The new tank comes in after the day the placement began (%(day)s).') % {
                'day': row.from_on.isoformat()})
        if from_day > row.until_on:
            errors.append(_('The new tank comes in on or before the last day of the placement (%(day)s).') % {
                'day': row.until_on.isoformat()})
        if errors:
            raise _refused(*dict.fromkeys(errors))
        held = read.booked([new_unit.pk], from_day, row.until_on).get(new_unit.pk)
        if held is not None:
            raise _refused(read.booked_text(new_unit.code, held))
        group = row.replicate.group
        rows = []
        if protocol is not None:
            conflicts = list(design_module.feeding_conflicts([(group.name, new_unit, from_day, row.until_on)]))
            if conflicts:
                raise _refused(*[finding.text for finding in conflicts])
            rows, found = assignments.rows(protocol, [new_unit], None, from_day, row.until_on,
                                           notes=f'{locked.code} · {group.name}')
            if found:
                raise _refused(*dict.fromkeys(f'{new_unit.code}: {error.message}' for error in found))
        with audit.source_language():
            before = describe_places(locked)
            ReplicateUnit.objects.filter(pk=row.pk).update(
                until_on=from_day - timedelta(days=1), left_reason=reason, version=row.version + 1, updated_by=user,
                updated_at=timezone.now())
            _end_diet(user, row, protocol, from_day - timedelta(days=1))
            try:
                with transaction.atomic():
                    ReplicateUnit.objects.create(replicate=row.replicate, unit=new_unit, from_on=from_day,
                                                 until_on=row.until_on, created_by=user, updated_by=user)
                    assignments.save(user, rows)
            except IntegrityError:
                raise _refused(BOOKED_MEANWHILE)
            _log_amendment(user, locked, before, reason, row.unit)
        return locked


# ---- who may read it: shares and the audience (the lead's) ----------------------------------------------------------
SHARES = gettext_lazy('Shares')
AUDIENCE = gettext_lazy('Who may read it')


def is_lead(user, experiment):
    """Whether `user` is the experiment's lead now (its window open)."""
    from .sealing import live
    return Member._base_manager.filter(live(), experiment=experiment, user=user, role=Member.Role.LEAD).exists()


def _lead_only(user, experiment):
    if not is_lead(user, experiment):
        raise PermissionDenied


def describe_share(share):
    """A share as the activity log keeps it, in English: who, which part, until when, why."""
    grantee = share.user.get_username() if share.user_id else f'role {share.group.name}'
    return f'{grantee}: {share.part} until {share.valid_until.date().isoformat()} ({share.reason})'


def share(user, experiment, grantee, parts, until, reason, group=None):
    """The lead gives `grantee` (a person, or with `group` a role) the `parts` of the experiment until `until`, for
    `reason`; a part the grantee holds already is renewed (the old row revoked, history kept). Logged once on the
    experiment ("Shares", the new rows). Returns the new rows."""
    _lead_only(user, experiment)
    reason = (reason or '').strip()
    if not reason or not parts or until is None:
        raise _refused(_('Say who, which parts, until when and why.'))
    now = timezone.now()
    made = []
    with transaction.atomic():
        Experiment.objects.select_for_update().get(pk=experiment.pk)
        target = {'group': group} if group is not None else {'user': grantee}
        for part in dict.fromkeys(parts):
            ExperimentShare.objects.filter(experiment=experiment, part=part, revoked_at__isnull=True, **target).update(
                revoked_at=now, revoked_by=user)
            try:
                with transaction.atomic():
                    made.append(ExperimentShare.objects.create(experiment=experiment, part=part, valid_from=now,
                                                               valid_until=until, reason=reason, created_by=user,
                                                               **target))
            except IntegrityError:
                raise _refused(_('A share lasts at most two years and ends after it begins.'))
        with audit.source_language():
            audit.record(user, AuditLog.Action.UPDATE, experiment,
                         {str(SHARES): [None, '; '.join(describe_share(row) for row in made)]})
    return made


def revoke(user, row):
    """The lead ends a share now (the row stays, with who ended it and when). Logged once on the experiment."""
    experiment = row.experiment
    _lead_only(user, experiment)
    with transaction.atomic():
        updated = ExperimentShare.objects.filter(pk=row.pk, revoked_at__isnull=True).update(
            revoked_at=timezone.now(), revoked_by=user)
        if updated:
            with audit.source_language():
                audit.record(user, AuditLog.Action.UPDATE, experiment,
                             {str(SHARES): [describe_share(row), None]})
    return row


def _may_seal_past(user, experiment, audience):
    """Refused unless `user` may seal the days of `experiment` already passed (the coordinator's decision of 2026-11-25
    on landing review W3): a draft seals nothing (experiment_cells holds a started experiment's cells), so a record of
    its tanks before it is started is the farm's own; starting a sealed or private experiment whose day 0 has passed,
    or sealing a started open one, makes those days' records the experiment's, and only a person who holds Oversee
    (who keeps every tank's fish) does that."""
    if (audience != Experiment.Audience.OPEN and experiment.starts_on is not None
            and experiment.starts_on < site_today(experiment.site) and not user.has_perm('.'.join(sealing.OVERSEE))):
        raise _refused(_('Day 0 has passed: this seals the records of its tanks since then, so a person who holds '
                         'Oversee does it.'))


def set_audience(user, experiment, audience):
    """The lead makes the experiment sealed (its team and shares) or open (everyone who reads experiments). Logged."""
    _lead_only(user, experiment)
    if audience not in Experiment.Audience.values:
        raise _refused(_('Choose who may read it.'))
    with transaction.atomic():
        locked = Experiment.objects.select_for_update().get(pk=experiment.pk)
        if locked.audience == audience:
            return locked
        if locked.status != Status.DRAFT and locked.audience == Experiment.Audience.OPEN:
            _may_seal_past(user, locked, audience)
        before = locked.get_audience_display()
        locked.audience = audience
        locked.version += 1
        locked.updated_by = user
        locked.save(update_fields=['audience', 'version', 'updated_by', 'updated_at'])
        with audit.source_language():
            audit.record(user, AuditLog.Action.UPDATE, locked,
                         {str(AUDIENCE): [audit.message(before), audit.message(locked.get_audience_display())]})
    return locked


def take_lead(user, experiment, reason):
    """The platform admin makes `user` the lead of an experiment that has no live lead (its lead left, or their window
    ended): the one way past the lead's own rule (review F3), for a superuser only, with a reason, logged on the
    experiment as a change of its team. The admin then shares or hands the lead on as any lead."""
    from .sealing import live
    reason = (reason or '').strip()
    if not user.is_superuser:
        raise PermissionDenied
    if not reason:
        raise _refused(_('Say why the experiment is taken over.'))
    with transaction.atomic():
        locked = Experiment.all_objects.select_for_update().get(pk=experiment.pk)
        if Member._base_manager.filter(live(), experiment=locked, role=Member.Role.LEAD).exists():
            raise _refused(_('The experiment has a lead: only the lead changes its team.'))
        before = '; '.join(f'{row.user.get_username()} ({row.role})'
                           for row in Member._base_manager.filter(experiment=locked).select_related('user'))
        Member._base_manager.filter(experiment=locked, role=Member.Role.LEAD).delete()     # a lead whose window ended
        Member._base_manager.filter(experiment=locked, user=user).delete()
        Member._base_manager.create(experiment=locked, user=user, role=Member.Role.LEAD, created_by=user)
        locked.version += 1
        locked.updated_by = user
        locked.save(update_fields=['version', 'updated_by', 'updated_at'])
        with audit.source_language():
            audit.record(user, AuditLog.Action.UPDATE, locked,
                         {'Team': [before or None, f'{user.get_username()} (lead), taken over: {reason}']})
    return locked


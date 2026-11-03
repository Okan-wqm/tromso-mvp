"""The write path of an experiment's design, places and life: every operation is one function here, inside one
transaction, locking the experiment row (last: the batches and tanks a service touches are locked before it, in
primary-key order, as the stock service does), refusing a form that was built on an older version, and writing one row of
the activity log on the experiment (labelled "Design", "Places", "Status": the person asks what changed on this
experiment, not on which table). A failure raises `ValidationError` on NON_FIELD_ERRORS, as `protocols.save_table`, and
nothing is written.

- `save_design`: the factors, groups, levels and replicates of a draft, saved as a whole, the grid's rows matched to the
  stored ones by their id (a renamed group keeps its replicates and the tanks placed in them);
- `save_places`, `randomise`, `move_span`: the tanks of a draft's replicates and the days they are booked to them."""
import itertools
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext as _, gettext_lazy

from core import audit, softdelete
from core.models import AuditLog
from farm.models import FeedingProtocol, Tank
from farm.models.feeding_protocol import ProtocolStatus
from farm.stock.services import locked as stock_locked

from . import allocation, read
from . import design as design_module
from .models import (
    AllocationMethod, Experiment, ExperimentGroup, Factor, FactorKind, GroupLevel, GroupRole, Level, Replicate,
    ReplicateUnit, Status,
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
    """The tanks of one replicate and the days they are booked to it (both included); no days: the whole span."""
    replicate: object
    tanks: list = field(default_factory=list)
    first: object = None
    last: object = None


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
        lines.append(f'{replicate.group.name} R{replicate.number}: {tanks}{days}')
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


def _check_booked(experiment, wanted):
    """No tank is booked to another experiment on a day it is asked for here (named by its number); the exclusion
    constraint holds it for any writer, this says which experiment."""
    errors = []
    for replicate, tank, first, last in wanted:
        other = read.booked([tank.pk], first, last, exclude=experiment).get(tank.pk)
        if other is not None:
            errors.append(_('%(tank)s is booked to %(experiment)s on some of these days.') % {
                'tank': tank.code, 'experiment': other.code})
    if errors:
        raise _refused(*dict.fromkeys(errors))


def _write_places(user, experiment, wanted):
    """Replaces the draft's placements with `wanted`: those already there are kept, the others removed and the new
    ones made. A draft's placements are not evidence (the trigger lets a draft delete them): they are removed for good,
    and the change is the one "Places" row on the experiment."""
    current = {(row.replicate_id, row.unit_id, row.from_on, row.until_on): row
               for row in ReplicateUnit.objects.filter(replicate__group__experiment=experiment)}
    keep = {(replicate.pk, tank.pk, first, last) for replicate, tank, first, last in wanted}
    ReplicateUnit.objects.filter(pk__in=[row.pk for key, row in current.items() if key not in keep]).delete()
    fresh = [ReplicateUnit(replicate=replicate, unit=tank, from_on=first, until_on=last, created_by=user,
                           updated_by=user)
             for replicate, tank, first, last in wanted if (replicate.pk, tank.pk, first, last) not in current]
    try:
        with transaction.atomic():
            ReplicateUnit.objects.bulk_create(fresh)
    except IntegrityError:
        raise _refused(_('A tank was booked to another experiment meanwhile: look at the places and try again.'))


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
        _check_booked(locked, wanted)
        note = note.strip()
        with audit.source_language():
            before, before_allocation = describe_places(locked), describe_allocation(locked)
            changed = {(r.pk, t.pk, f, l) for r, t, f, l in wanted} != {
                (row.replicate_id, row.unit_id, row.from_on, row.until_on)
                for row in ReplicateUnit.objects.filter(replicate__group__experiment=locked)}
            if changed and wanted and not note:
                raise _refused(_('Say why the tanks are placed by hand: a placement that is not randomised is '
                                 'registered with its reason.'))
            if changed:
                _write_places(user, locked, wanted)
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
        places = [Place(None, found) for found in tanks.values()]
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
        _check_booked(locked, wanted)
        with audit.source_language():
            before, before_allocation = describe_places(locked), describe_allocation(locked)
            _write_places(user, locked, wanted)
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
        ReplicateUnit.objects.filter(pk__in=[row.pk for row in rows]).update(
            from_on=new[0], until_on=new[1], updated_by=user, updated_at=timezone.now())
        audit.record(user, AuditLog.Action.UPDATE, experiment, {str(PLACES): [before, describe_places(experiment)]})


def clashes_when_moved(experiment, old_span, new):
    """{tank: the experiment that holds it} for the placements that would move with the span (they equal the old one) and
    meet another experiment's booking on the new days: what the form says on the field before it saves."""
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

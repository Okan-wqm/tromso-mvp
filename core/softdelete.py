"""Deleting a record that other records point at, as the links between them say.

Records are soft-deleted, so the database's own `on_delete` never runs. Instead of writing the
consequences per tab, this reads each link's `on_delete` and applies it to live records:

- CASCADE   the records that point at it are deleted with it, and so on down;
- SET_NULL  they stay, but lose the link (e.g. a deleted production department's systems); a restore does not
  link them again, what they pointed at is not kept;
- PROTECT / RESTRICT  they block the delete until they are dealt with;
- DO_NOTHING  they stay as they are, still pointing at it: history that outlives the record without
  holding it back (a deleted unit's feeding records and its sampling points, as its stock lines), shown again
  with it when it is restored. The database's own foreign key still refuses a hard delete. What they keep in
  turn is kept too (a unit's points keep their water samples). The
  confirmation counts them, each record once whatever links it, and says what becomes of them
  (the model's `kept_note`). Records that point at it this way but are only a plan, not history (a
  recurring task's planned tasks nobody has touched), are deleted with it all the same: their model
  says which (`AuditedModel.deleted_with`).

Records linked to it through a many-to-many link (the equipment serving a system) keep the link row:
the link only stops counting while the record is deleted, so restoring it brings the link back. The
confirmation lists them; nothing about them changes, so nothing is logged for them.

A model adds conditions that are not links by overriding `delete_blockers()` (fish still in a
tank). One plan serves both the confirmation (what will be affected) and the delete itself, and
every record it touches gets its own activity-log row, written in English like every audit row
(core.audit). Every record the delete takes along is stamped with the delete's moment, so a restore brings
back the record and what that delete took along (`restore`), never what was deleted on its own before.
"""
from dataclasses import dataclass, field

from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction
from django.utils import timezone
from django.utils.text import capfirst
from django.utils.translation import gettext as _, ngettext

from . import audit, sealing
from .models import AuditedModel, AuditLog, violated_constraint

# LOCK ORDER. The one order every write takes its locks on the farm's structure in: the fish first (batches, then
# units: the stock operations, the withdrawal guard's lock_fish), then the place going up (production departments, then
# sites: a unit's save, Tank._lock_place). A delete and a restore lock the records they take along the deepest first
# and what they delete or restore last; a record is never locked after one above it. Two writes that both follow it
# wait for each other; the database still fails one of a cycle no write can foresee (core.middleware.
# CrossedWritesMiddleware says "try again").


@dataclass
class DeletePlan:
    obj: AuditedModel
    blockers: list = field(default_factory=list)
    cascade: list = field(default_factory=list)   # deleted with obj; parents before their children
    detach: list = field(default_factory=list)    # (record, link) pairs whose link is cleared
    unlinked: list = field(default_factory=list)  # records linked many-to-many, whose link stops counting
    kept_records: dict = field(default_factory=dict)   # model -> the pks of its records that keep their link
    # (model, pk) of a record the plan takes along, or (model, pk, link) of one it detaches -> (the link it hangs by,
    # (model, pk) of what it points at)
    via: dict = field(default_factory=dict)
    hidden: set = field(default_factory=set)      # (model, pk) of the records the person may not see (core.sealing)

    @property
    def restricted(self):
        """How many records the delete reaches that the person may not see: never named, and never said as a count
        (the page says only that there are some)."""
        return len(self.hidden)

    def shown(self, record):
        return (type(record), record.pk) not in self.hidden

    @property
    def can_delete(self):
        return not self.blockers

    @staticmethod
    def _by_model(items, record_of=lambda item: item):
        groups = {}
        for item in items:
            record = record_of(item)
            groups.setdefault(type(record), []).append(item)
        return groups

    def deleted_groups(self):
        """[{'label': 'Systems', 'records': [...]}] for the confirmation."""
        return [
            {'label': capfirst(model._meta.verbose_name_plural), 'records': records}
            for model, records in self._by_model([record for record in self.cascade if self.shown(record)]).items()
        ]

    def detached_groups(self):
        """[{'label': 'Production departments', 'link': 'site', 'records': [...]}]: kept, but losing their link."""
        groups = []
        shown = [pair for pair in self.detach if self.shown(pair[0])]
        for model, pairs in self._by_model(shown, record_of=lambda pair: pair[0]).items():
            for link in dict.fromkeys(link for _record, link in pairs):
                groups.append({
                    'label': capfirst(model._meta.verbose_name_plural),
                    'link': str(model._meta.get_field(link).verbose_name).lower(),
                    'records': [record for record, name in pairs if name == link],
                })
        return groups

    @property
    def kept(self):
        """{model: how many of its records keep their link}, each record counted once."""
        counted = {model: len([pk for pk in pks if (model, pk) not in self.hidden])
                   for model, pks in self.kept_records.items()}
        return {model: count for model, count in counted.items() if count}

    def kept_groups(self):
        """[{'label': 'Water samples', 'count': 120, 'note': ...}]: kept as they are; the note says what
        becomes of them while it is deleted (the model's `kept_note`)."""
        return [{'label': capfirst(model._meta.verbose_name_plural), 'count': count, 'note': model.kept_note}
                for model, count in self.kept.items()]

    def unlinked_groups(self):
        """[{'label': 'Equipment', 'records': [...]}]: linked to a deleted record, keeping the link row."""
        return [
            {'label': capfirst(model._meta.verbose_name_plural), 'records': records}
            for model, records in self._by_model([record for record in self.unlinked if self.shown(record)]).items()
        ]


def plan_delete(obj):
    """What deleting `obj` would do, without doing it. Collected as the system (a delete reaches every record its links
    reach), then shown as the person: what they may not see is counted ("N restricted records"), never named, and a
    delete that reaches it is refused to them (core.sealing)."""
    plan = DeletePlan(obj)
    with sealing.system('the delete plan'):
        _collect(obj, plan, {(type(obj), obj.pk)})
    deleted = {(type(record), record.pk) for record in plan.cascade}
    plan.detach = [(record, link) for record, link in plan.detach if (type(record), record.pk) not in deleted]
    plan.unlinked = list({(type(record), record.pk): record for record in plan.unlinked
                          if (type(record), record.pk) not in deleted}.values())
    kept = {model: {pk for pk in pks if (model, pk) not in deleted} for model, pks in plan.kept_records.items()}
    plan.kept_records = {model: pks for model, pks in kept.items() if pks}
    _hide(plan)
    return plan


def _hide(plan):
    """Marks the records the viewer of the moment may not see, and refuses a delete that would change one of them."""
    reached = {}
    for record in [*plan.cascade, *(record for record, _link in plan.detach), *plan.unlinked]:
        reached.setdefault(type(record), set()).add(record.pk)
    for model, pks in plan.kept_records.items():
        reached.setdefault(model, set()).update(pks)
    for model, pks in reached.items():
        seen = set(model._default_manager.filter(pk__in=pks).values_list('pk', flat=True)) \
            if sealing.seal_of(model) else pks
        plan.hidden.update((model, pk) for pk in pks if pk not in seen)
    changed = {(type(record), record.pk) for record in [*plan.cascade, *(record for record, _link in plan.detach)]}
    if changed & plan.hidden:
        # Never how many (review F8): a count would say how much of a confidential experiment lies there.
        plan.blockers.append(_('It reaches records you may not see: ask the experiment’s lead, who may see them.'))


def _cascade(children, plan, seen, link, parent):
    for child in children:
        key = (type(child), child.pk)
        if key not in seen:
            seen.add(key)
            plan.cascade.append(child)
            plan.via[key] = (link, (type(parent), parent.pk))
            _collect(child, plan, seen)


def _collect(obj, plan, seen):
    plan.blockers.extend(obj.delete_blockers())
    for relation in obj._meta.related_objects:
        model = relation.related_model
        if relation.many_to_many and issubclass(model, AuditedModel):
            plan.unlinked.extend(model.objects.filter(**{relation.field.name: obj}))
            continue
        # Only links from other farm records; plain rows (a site's contacts) stay with their parent.
        if not relation.one_to_many or not issubclass(model, AuditedModel):
            continue
        link = relation.field.name
        action = relation.on_delete
        if action is models.DO_NOTHING:
            planned = list(model.deleted_with(link, obj))
            _cascade(planned, plan, seen, link, obj)
            pks = set(model.objects.filter(**{link: obj}).exclude(pk__in=[record.pk for record in planned])
                      .values_list('pk', flat=True))
            _keep(model, pks, plan)
            continue
        children = list(model.objects.filter(**{link: obj}))
        if not children:
            continue
        if action is models.CASCADE:
            _cascade(children, plan, seen, link, obj)
        elif action is models.SET_NULL:
            plan.detach.extend((child, link) for child in children)
            plan.via.update({(type(child), child.pk, link): (link, (type(obj), obj.pk)) for child in children})
        elif action in (models.PROTECT, models.RESTRICT):
            plan.blockers.append(protected(model, len(children)))


def _keep(model, pks, plan):
    """Notes the records of `model` with these pks as kept, and what they keep in turn: a deleted unit keeps its
    sampling points and they their water samples."""
    new = pks - plan.kept_records.get(model, set())
    if not new:
        return
    plan.kept_records.setdefault(model, set()).update(new)
    for relation in model._meta.related_objects:
        child = relation.related_model
        if relation.one_to_many and issubclass(child, AuditedModel) and relation.on_delete is models.DO_NOTHING:
            found = child.objects.filter(**{f'{relation.field.name}__in': new}).values_list('pk', flat=True)
            _keep(child, set(found), plan)


def protected(model, count):
    """Why a delete is blocked by `count` live records of `model` that point at it with PROTECT. A model
    whose PROTECT links come from records the plan does not follow (a plain row such as a harvest's record)
    says it in its own delete_blockers() with this sentence."""
    # Translators: %(name)s is the kind of record in the singular, %(plural)s in the plural.
    return ngettext('%(count)d %(name)s still belongs to it.', '%(count)d %(plural)s still belong to it.',
                    count) % {'count': count, 'name': model._meta.verbose_name,
                              'plural': model._meta.verbose_name_plural}


def execute(plan, user):
    """Carries the plan out, inside the caller's transaction, one log row per affected record. Every record it deletes
    is stamped with one moment, the delete's (AuditedModel.mark_deleted): a restore brings back what it took along.

    The plan was read before, unlocked (it is the confirmation's too), so the records it takes along or detaches are
    locked now and taken only as they still are (cross review F2): one moved to another parent meanwhile stays where
    it went, with what hangs under it, and one deleted on its own meanwhile keeps its own moment."""
    moment = timezone.now()
    rows = lock_along(plan)
    gone = {(type(plan.obj), plan.obj.pk)}
    taken = []
    for record in plan.cascade:                        # parents before their children
        key = (type(record), record.pk)
        if _still_under(rows.get(key), *plan.via[key], gone):
            gone.add(key)
            taken.append(rows[key])
    with audit.source_language():
        for record, link in plan.detach:
            key = (type(record), record.pk)
            row = rows.get(key)
            if key in gone or not _still_under(row, *plan.via[(*key, link)], gone):
                continue
            label = capfirst(record._meta.get_field(link).verbose_name)
            before = str(getattr(row, link))
            row.detach(link, user)
            audit.record(user, AuditLog.Action.UPDATE, row, {str(label): [before, None]})
        for record in reversed(taken):
            record.mark_deleted(user, moment)
            audit.record_delete(user, record)
        plan.obj.mark_deleted(user, moment)
        audit.record_delete(user, plan.obj)


def lock_along(plan):
    """Locks what the plan takes along or detaches, the deepest first, before what it deletes is locked (the delete view
    calls it first; execute again, a no-op then). One lock order for the farm's structure (LOCK ORDER above): from
    the fish and the leaves up to the site, so a unit's save (unit, department, site) and a delete (units, department)
    wait for each other instead of deadlocking (the merge review's finding 1). Returns {(model, pk): row}."""
    return _locked([*reversed(plan.cascade), *(record for record, _link in plan.detach)])


def _locked(records):
    """{(model, pk): row} of the records as they are now, each locked for the caller's transaction, model by model in
    the order the records come (the deepest first: LOCK ORDER above), each model's in primary-key order (a record
    deleted meanwhile is there too, marked so)."""
    pks = {}
    for record in records:
        pks.setdefault(type(record), set()).add(record.pk)
    found = {}
    for model, keys in pks.items():
        for row in model.all_objects.select_for_update(of=('self',)).filter(pk__in=keys).order_by('pk'):
            found[(model, row.pk)] = row
    return found


def _still_under(row, link, parent, gone):
    """Whether `row`, as locked now, is live and still points through `link` at `parent`, a record the delete takes."""
    if row is None or row.is_deleted or parent not in gone:
        return False
    return getattr(row, row._meta.get_field(link).attname) == parent[1]


def taken_with(record):
    """`record`, deleted, and what its delete took along: the records pointing at it that were deleted in the same
    moment (execute), and theirs in turn; parents before their children, as read (restore locks them, the deepest
    first). A record deleted on its own before is not among them, nor what was only detached (its link is not known
    any more)."""
    found, seen, frontier = [], set(), [record]
    while frontier:
        found.extend(frontier)
        seen.update((type(item), item.pk) for item in frontier)
        following = []
        for parent in frontier:
            for relation in parent._meta.related_objects:
                model = relation.related_model
                if not relation.one_to_many or not issubclass(model, AuditedModel):
                    continue
                children = (model.all_objects.order_by('pk')
                            .filter(**{relation.field.name: parent}, is_deleted=True, deleted_at=parent.deleted_at))
                following.extend(child for child in children if (model, child.pk) not in seen)
                seen.update((model, child.pk) for child in children)
        frontier = following
    return found


def restore(record, user):
    """Brings a deleted record back with what its delete took along (taken_with), each checked like a new one:
    refused when a record one of them points at is deleted and does not come back with them (bring that back first),
    when a code was taken meanwhile, or when another restore was first. They are locked the deepest first and the
    record last (LOCK ORDER above), so two restores take turns; it all comes back or nothing does. Each change is
    logged. A link the delete cleared (SET_NULL) stays cleared: what it pointed at is not kept."""
    model = type(record)
    with transaction.atomic():
        read = model.all_objects.filter(pk=record.pk).first() or record
        collected = taken_with(read) if read.is_deleted else [read]
        rows = _locked(list(reversed(collected)))
        record = rows.get((model, record.pk), record)
        if not record.is_deleted or record.deleted_at != read.deleted_at:
            raise ValidationError(_('“%(record)s” is not deleted.'), params={'record': record})
        # As locked, parents before their children: what is still deleted at the moment of this record's delete (a
        # restore meanwhile took it back).
        records = [row for row in (rows.get((type(item), item.pk)) for item in collected)
                   if row is not None and row.is_deleted and row.deleted_at == read.deleted_at]
        coming = {(type(item), item.pk) for item in records}
        for item in records:
            for link in item._meta.concrete_fields:
                target = getattr(item, link.name) if link.is_relation else None
                if isinstance(target, AuditedModel) and target.is_deleted and (type(target), target.pk) not in coming:
                    raise ValidationError(_('%(field)s “%(record)s” is deleted.'),
                                          params={'field': capfirst(link.verbose_name), 'record': target})
        for item in records:
            item.is_deleted, item.deleted_at, item.deleted_by = False, None, None
            item.updated_by = user
            item.version += 1
            # Re-checks the constraints among live records, e.g. a code taken meanwhile; the records coming back
            # together cannot clash with one another, they were live together.
            item.validate_unique()
            item.validate_constraints()
        for item in records:
            try:
                with transaction.atomic():
                    item.save()
            except IntegrityError as error:    # taken by a record committed after the check
                constraint = violated_constraint(type(item), error)
                if constraint is None:
                    raise
                raise ValidationError(constraint.violation_error_message) from None
        for item in records:
            item.clean_fields()
            item.clean()       # the model's own rules, with everything that comes back live again
            audit.record(user, AuditLog.Action.RESTORE, item)

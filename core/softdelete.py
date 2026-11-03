"""Deleting a record that other records point at, as the links between them say.

Records are soft-deleted, so the database's own `on_delete` never runs. Instead of writing the
consequences per tab, this reads each link's `on_delete` and applies it to live records:

- CASCADE   the records that point at it are deleted with it, and so on down;
- SET_NULL  they stay, but lose the link (e.g. a deleted site's production departments);
- PROTECT / RESTRICT  they block the delete until they are dealt with;
- DO_NOTHING  they stay as they are, still pointing at it: history that outlives the record without
  holding it back (a deleted unit's feeding records and its sampling points, as its stock lines), shown again
  with it when it is restored (restoring brings back only the record itself, so what must come back with it is
  kept, not deleted with it). The database's own foreign key still refuses a hard delete. What they keep in
  turn is kept too (a unit's points keep their water samples). The confirmation counts them all.

Records linked to it through a many-to-many link (the equipment serving a system) keep the link row:
the link only stops counting while the record is deleted, so restoring it brings the link back. The
confirmation lists them; nothing about them changes, so nothing is logged for them.

A model adds conditions that are not links by overriding `delete_blockers()` (fish still in a
tank). One plan serves both the confirmation (what will be affected) and the delete itself, and
every record it touches gets its own activity-log row, written in English like every audit row
(core.audit).
"""
from dataclasses import dataclass, field

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.text import capfirst
from django.utils.translation import gettext as _, ngettext

from . import audit
from .models import AuditedModel, AuditLog


@dataclass
class DeletePlan:
    obj: AuditedModel
    blockers: list = field(default_factory=list)
    cascade: list = field(default_factory=list)   # deleted with obj; parents before their children
    detach: list = field(default_factory=list)    # (record, link) pairs whose link is cleared
    unlinked: list = field(default_factory=list)  # records linked many-to-many, whose link stops counting
    kept: dict = field(default_factory=dict)      # model -> how many records keep their link, out of sight

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
            for model, records in self._by_model(self.cascade).items()
        ]

    def detached_groups(self):
        """[{'label': 'Production departments', 'link': 'site', 'records': [...]}]: kept, but losing their link."""
        groups = []
        for model, pairs in self._by_model(self.detach, record_of=lambda pair: pair[0]).items():
            for link in dict.fromkeys(link for _, link in pairs):
                groups.append({
                    'label': capfirst(model._meta.verbose_name_plural),
                    'link': str(model._meta.get_field(link).verbose_name).lower(),
                    'records': [record for record, name in pairs if name == link],
                })
        return groups

    def kept_groups(self):
        """[{'label': 'Water samples', 'count': 120}]: kept as they are, hidden while it is deleted."""
        return [{'label': capfirst(model._meta.verbose_name_plural), 'count': count}
                for model, count in self.kept.items()]

    def unlinked_groups(self):
        """[{'label': 'Equipment', 'records': [...]}]: linked to a deleted record, keeping the link row."""
        return [
            {'label': capfirst(model._meta.verbose_name_plural), 'records': records}
            for model, records in self._by_model(self.unlinked).items()
        ]


def plan_delete(obj):
    """What deleting `obj` would do, without doing it."""
    plan = DeletePlan(obj)
    _collect(obj, plan, {(type(obj), obj.pk)})
    deleted = {(type(record), record.pk) for record in plan.cascade}
    plan.detach = [(record, link) for record, link in plan.detach if (type(record), record.pk) not in deleted]
    plan.unlinked = list({(type(record), record.pk): record for record in plan.unlinked
                          if (type(record), record.pk) not in deleted}.values())
    return plan


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
            _keep(model, model.objects.filter(**{link: obj}), plan)
            continue
        children = list(model.objects.filter(**{link: obj}))
        if not children:
            continue
        if action is models.CASCADE:
            for child in children:
                if (model, child.pk) not in seen:
                    seen.add((model, child.pk))
                    plan.cascade.append(child)
                    _collect(child, plan, seen)
        elif action is models.SET_NULL:
            plan.detach.extend((child, link) for child in children)
        elif action in (models.PROTECT, models.RESTRICT):
            plan.blockers.append(protected(model, len(children)))


def _keeps_more(model):
    """The links through which other farm records point at this kind of record with DO_NOTHING."""
    return [relation for relation in model._meta.related_objects
            if relation.one_to_many and issubclass(relation.related_model, AuditedModel)
            and relation.on_delete is models.DO_NOTHING]


def _keep(model, rows, plan):
    """Counts the records of `rows` (a queryset) that stay as they are, out of sight, and what they keep in turn: a
    deleted unit keeps its sampling points and they their water samples. Only a kind that keeps something is read
    (a unit's points, a few); the rest are counted (a point's samples, thousands)."""
    links = _keeps_more(model)
    records = list(rows) if links else []
    count = len(records) if links else rows.count()
    if not count:
        return
    plan.kept[model] = plan.kept.get(model, 0) + count
    for relation in links:
        child = relation.related_model
        _keep(child, child.objects.filter(**{f'{relation.field.name}__in': records}), plan)


def protected(model, count):
    """Why a delete is blocked by `count` live records of `model` that point at it with PROTECT. A model
    whose PROTECT links come from records the plan does not follow (a plain row such as a harvest's record)
    says it in its own delete_blockers() with this sentence."""
    # Translators: %(name)s is the kind of record in the singular, %(plural)s in the plural.
    return ngettext('%(count)d %(name)s still belongs to it.', '%(count)d %(plural)s still belong to it.',
                    count) % {'count': count, 'name': model._meta.verbose_name,
                              'plural': model._meta.verbose_name_plural}


def execute(plan, user):
    """Carries the plan out, inside the caller's transaction, one log row per affected record."""
    with audit.source_language():
        for record, link in plan.detach:
            label = capfirst(record._meta.get_field(link).verbose_name)
            before = str(getattr(record, link))
            record.detach(link, user)
            audit.record(user, AuditLog.Action.UPDATE, record, {str(label): [before, None]})
        for record in reversed(plan.cascade):
            record.soft_delete(user)
            audit.record_delete(user, record)
        plan.obj.soft_delete(user)
        audit.record_delete(user, plan.obj)


def restore(record, user):
    """Brings a deleted record back, checked like a new one: refused when a record it points at is
    deleted too (bring that back first) or when its code was taken meanwhile. Only the record itself
    returns, not what was deleted with it. The change is logged."""
    for link in record._meta.concrete_fields:
        target = getattr(record, link.name) if link.is_relation else None
        if isinstance(target, AuditedModel) and target.is_deleted:
            raise ValidationError(_('%(field)s “%(record)s” is deleted.'),
                                  params={'field': capfirst(link.verbose_name), 'record': target})
    record.is_deleted, record.deleted_at, record.deleted_by = False, None, None
    record.updated_by = user
    record.version += 1
    record.full_clean()   # re-checks the constraints among live records, e.g. a code taken meanwhile
    record.save()
    audit.record(user, AuditLog.Action.RESTORE, record)

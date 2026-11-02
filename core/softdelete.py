"""Deleting a record that other records point at, as the links between them say.

Records are soft-deleted, so the database's own `on_delete` never runs. Instead of writing the
consequences per tab, this reads each link's `on_delete` and applies it to live records:

- CASCADE   the records that point at it are deleted with it, and so on down;
- SET_NULL  they stay, but lose the link (e.g. a deleted site's departments);
- PROTECT / RESTRICT  they block the delete until they are dealt with.

A model adds conditions that are not links by overriding `delete_blockers()` (fish still in a
tank). One plan serves both the confirmation (what will be affected) and the delete itself, and
every record it touches gets its own activity-log row.
"""
from dataclasses import dataclass, field

from django.db import models

from . import audit
from .models import AuditedModel, AuditLog


@dataclass
class DeletePlan:
    obj: AuditedModel
    blockers: list = field(default_factory=list)
    cascade: list = field(default_factory=list)   # deleted with obj; parents before their children
    detach: list = field(default_factory=list)    # (record, link) pairs whose link is cleared

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
        """[{'label': 'Departments', 'records': [...]}] for the confirmation."""
        return [
            {'label': str(model._meta.verbose_name_plural).capitalize(), 'records': records}
            for model, records in self._by_model(self.cascade).items()
        ]

    def detached_groups(self):
        """[{'label': 'Departments', 'link': 'site', 'records': [...]}]: kept, but losing their link."""
        groups = []
        for model, pairs in self._by_model(self.detach, record_of=lambda pair: pair[0]).items():
            for link in dict.fromkeys(link for _, link in pairs):
                groups.append({
                    'label': str(model._meta.verbose_name_plural).capitalize(),
                    'link': str(model._meta.get_field(link).verbose_name),
                    'records': [record for record, name in pairs if name == link],
                })
        return groups


def plan_delete(obj):
    """What deleting `obj` would do, without doing it."""
    plan = DeletePlan(obj)
    _collect(obj, plan, {(type(obj), obj.pk)})
    deleted = {(type(record), record.pk) for record in plan.cascade}
    plan.detach = [(record, link) for record, link in plan.detach if (type(record), record.pk) not in deleted]
    return plan


def _collect(obj, plan, seen):
    plan.blockers.extend(obj.delete_blockers())
    for relation in obj._meta.related_objects:
        model = relation.related_model
        # Only links from other farm records; plain rows (a site's contacts) stay with their parent.
        if not relation.one_to_many or not issubclass(model, AuditedModel):
            continue
        link = relation.field.name
        children = list(model.objects.filter(**{link: obj}))
        if not children:
            continue
        action = relation.on_delete
        if action is models.CASCADE:
            for child in children:
                if (model, child.pk) not in seen:
                    seen.add((model, child.pk))
                    plan.cascade.append(child)
                    _collect(child, plan, seen)
        elif action is models.SET_NULL:
            plan.detach.extend((child, link) for child in children)
        elif action in (models.PROTECT, models.RESTRICT):
            one = len(children) == 1
            noun = model._meta.verbose_name if one else model._meta.verbose_name_plural
            plan.blockers.append(f'{len(children)} {noun} still {"belongs" if one else "belong"} to it.')


def execute(plan, user):
    """Carries the plan out, inside the caller's transaction, one log row per affected record."""
    for record, link in plan.detach:
        label = str(record._meta.get_field(link).verbose_name).capitalize()
        before = str(getattr(record, link))
        record.detach(link, user)
        audit.record(user, AuditLog.Action.UPDATE, record, {label: [before, None]})
    for record in reversed(plan.cascade):
        record.soft_delete(user)
        audit.record_delete(user, record)
    plan.obj.soft_delete(user)
    audit.record_delete(user, plan.obj)

"""Writing the audit log. Call these inside the same transaction as the change they describe, so a
change is never stored without its log row (or the other way round)."""
from django.db import models

from .models import AuditLog


def _display(instance, field):
    if isinstance(field, models.ForeignKey):
        value = getattr(instance, field.name)
        return None if value is None else str(value)
    value = getattr(instance, field.attname)
    if field.choices and value not in (None, ''):
        return str(dict(field.flatchoices).get(value, value))
    if value in (None, ''):
        return None
    if isinstance(field, models.DecimalField):
        # The same amount must read the same whether it came from a form (100) or the database (100.00).
        return f'{value:.{field.decimal_places}f}'
    return str(value)


def snapshot(instance, field_names, labels=None):
    """{field label: display value} for the given fields, None for empty values. Labels come from
    `labels` (e.g. a form's Meta.labels) and default to the model field's verbose name."""
    labels = labels or {}
    result = {}
    for name in field_names:
        field = instance._meta.get_field(name)
        result[str(labels.get(name, field.verbose_name.capitalize()))] = _display(instance, field)
    return result


def diff(before, after):
    """{label: [old, new]} for the labels whose value changed between two snapshots."""
    return {label: [before.get(label), value] for label, value in after.items() if before.get(label) != value}


def record(user, action, instance, changes=None, entity_type=None, label=None):
    return AuditLog.objects.create(
        user=user if user and user.is_authenticated else None,
        user_name=user.get_username() if user and user.is_authenticated else 'system',
        action=action,
        entity_type=entity_type or instance._meta.verbose_name,
        entity_id=str(instance.pk),
        entity_label=label or str(instance),
        changes=changes or {},
    )


def record_create(user, instance, field_names, labels=None):
    values = {
        label: [None, value] for label, value in snapshot(instance, field_names, labels).items() if value is not None
    }
    return record(user, AuditLog.Action.CREATE, instance, values)


def record_update(user, instance, before, field_names, labels=None):
    """Logs the fields that changed since the `before` snapshot; logs nothing when none did."""
    changes = diff(before, snapshot(instance, field_names, labels))
    if changes:
        return record(user, AuditLog.Action.UPDATE, instance, changes)
    return None


def record_delete(user, instance):
    return record(user, AuditLog.Action.DELETE, instance)

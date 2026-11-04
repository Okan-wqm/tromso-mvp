"""Writing the audit log. Call these inside the same transaction as the change they describe, so a
change is never stored without its log row (or the other way round).

The log is language-neutral at rest: labels, record types and enumerated values are stored as their
English msgids whatever language the person who made the change was using, and shown translated
(AuditLog.shown_changes). Build every snapshot inside `source_language()` (core.crud does); a person's
own text (names, descriptions) is stored as written and never translated."""
import hashlib
import hmac

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.utils import translation
from django.utils.text import capfirst
from django.utils.translation import gettext_lazy as _

from .models import AuditLog


# Record types whose entries only some people may read in the activity log: {entity type: permission}. An app that
# keeps personal records (hr) registers them when it is ready; the log lists the others to everyone who may open it.
_restricted = {}


def restrict(entity_type, perm):
    """The log's entries about `entity_type` (its English name, `entity_type_of`) are shown only to people who
    hold `perm`: the activity log's list, its filters and its counts leave them out for everyone else."""
    _restricted[entity_type] = perm


def hidden_types(user):
    """The record types whose log entries `user` may not read."""
    return [entity_type for entity_type, perm in _restricted.items() if not user.has_perm(perm)]


def readable(user, entries=None):
    """The log entries `user` may read: every one but those of a restricted record type they lack the permission for."""
    entries = AuditLog.objects.all() if entries is None else entries
    hidden = hidden_types(user)
    return entries.exclude(entity_type__in=hidden) if hidden else entries


def source_language():
    """Text built inside this block comes out as the msgids themselves, ready to be stored."""
    return translation.override(settings.LANGUAGE_CODE)


def english(text):
    with source_language():
        return str(text)


def message(text):
    """An enumerated value (a choice, yes/no): stored as its msgid, shown translated. Only these are
    translated, so a site that happens to be called "Pond" keeps its name in every language."""
    return {'msgid': english(text)}


def _display(instance, field):
    if isinstance(field, models.ForeignKey):
        value = getattr(instance, field.name)
        return None if value is None else str(value)
    if isinstance(field, models.ManyToManyField):
        return ', '.join(sorted(str(item) for item in getattr(instance, field.name).all())) or None
    value = getattr(instance, field.attname)
    if isinstance(field, ArrayField) and field.base_field.choices:
        # Several choices (what a supplier supplies): each stored as its msgid, shown translated.
        labels = dict(field.base_field.flatchoices)
        return [message(labels.get(item, item)) for item in value or []] or None
    if isinstance(field, models.BooleanField):
        return message(_('Yes') if value else _('No'))
    if field.choices and value not in (None, ''):
        return message(dict(field.flatchoices).get(value, value))
    if value in (None, ''):
        return None
    if isinstance(field, models.DecimalField):
        # The same amount must read the same whether it came from a form (100) or the database (100.00).
        return f'{value:.{field.decimal_places}f}'
    return str(value)


def snapshot(instance, field_names, labels=None, private=()):
    """{field label: display value} for the given fields, None for empty values. Labels come from
    `labels` (e.g. a form's Meta.labels) and default to the model field's verbose name. A `private` field
    (a person's own words, Resource.private_fields) shows as the enumerated value "Private text" when it
    is filled and never as its text: the log says that it was set or cleared, not what it says."""
    labels = labels or {}
    result = {}
    for name in field_names:
        field = instance._meta.get_field(name)
        value = _display(instance, field)
        if name in private and value is not None:
            # The words are never stored. A short keyed digest is, so that replacing one text by another is a change the log
            # shows ("Private text" to "Private text") without saying anything about what they say.
            value = {**message(_('Private text')), 'rev': hmac.new(
                settings.SECRET_KEY.encode(), str(value).encode(), hashlib.sha256).hexdigest()[:8]}
        result[str(labels.get(name, capfirst(field.verbose_name)))] = value
    return result


def diff(before, after):
    """{label: [old, new]} for the labels whose value changed between two snapshots. A label only in
    `before` (a specification of the type a piece of equipment no longer has) changes to None."""
    changes = {label: [before.get(label), value] for label, value in after.items() if before.get(label) != value}
    changes.update({label: [value, None] for label, value in before.items() if label not in after and value is not None})
    return changes


def entity_type_of(model):
    """How the activity log names a kind of record (its English name, shown translated); the one
    definition for writing and searching it."""
    return english(model._meta.verbose_name)


def record(user, action, instance, changes=None, entity_type=None, label=None, severity=AuditLog.Severity.NORMAL):
    """One entry. `severity` critical marks someone going on past a warning that protects fish or food
    (farm/handling): the activity log shows it apart and the later alarms read it."""
    return AuditLog.objects.create(
        user=user if user and user.is_authenticated else None,
        user_name=user.get_username() if user and user.is_authenticated else 'system',
        action=action,
        entity_type=english(entity_type or entity_type_of(type(instance))),
        entity_id=str(instance.pk),
        # The record's name as English at rest like everything else: a name built from choices (a water limit's
        # parameter, a plan's kind) would otherwise be stored in the language of the person making the change.
        entity_label=label or english(instance),
        changes=changes or {},
        severity=severity,
    )


def record_create(user, instance, values, **kwargs):
    """Logs a new record with its non-empty values (a snapshot)."""
    changes = {label: [None, value] for label, value in values.items() if value is not None}
    return record(user, AuditLog.Action.CREATE, instance, changes, **kwargs)


def record_update(user, instance, before, after, **kwargs):
    """Logs what differs between two snapshots; logs nothing when nothing changed."""
    changes = diff(before, after)
    if changes:
        return record(user, AuditLog.Action.UPDATE, instance, changes, **kwargs)
    return None


def record_delete(user, instance, **kwargs):
    return record(user, AuditLog.Action.DELETE, instance, **kwargs)

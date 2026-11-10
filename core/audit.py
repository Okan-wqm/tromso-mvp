"""Writing the audit log. Call these inside the same transaction as the change they describe, so a
change is never stored without its log row (or the other way round).

The log is language-neutral at rest: labels, record types and enumerated values are stored as their
English msgids whatever language the person who made the change was using, and shown translated
(AuditLog.shown_changes). Build every snapshot inside `source_language()` (core.crud does); a person's
own text (names, descriptions) is stored as written and never translated."""
import hashlib
import hmac
from datetime import timedelta

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Max
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


def digest_key():
    """The key of the log's digests: its own (settings.AUDIT_DIGEST_KEY, DJANGO_AUDIT_DIGEST_KEY in the environment),
    the server's secret key when it has none. Its own, so that the secret key can be rotated (everyone is signed out)
    without the digests changing, and the digests' key rotated (every digest written before stops comparing with
    anything: the link to the old values is cut) without signing anyone out."""
    return settings.AUDIT_DIGEST_KEY or settings.SECRET_KEY


def digest(text):
    """The short keyed digest the log keeps of a private value instead of the value: eight hex digits of an HMAC-SHA256
    under `digest_key`. This is pseudonymisation, not erasure. Equal values give equal digests, so the log shows that
    a value changed; two equal digests say "probably the same value" (32 bits: sure enough for one change, not across
    a whole log). Whoever holds the key and the log can test a guess, and so recover a short value such as a phone
    number by trying them all; without the key that cannot be done from the stored rows, and no page prints a digest
    (AuditLog.shown_changes), so nobody tests a guess through the application either. The one digest of the log:
    whatever keeps a private value out of it calls this."""
    return hmac.new(digest_key().encode(), str(text).encode(), hashlib.sha256).hexdigest()[:8]


def private(text, of=None):
    """How the log keeps a private value (a person's own words, a contact's e-mail or phone): the enumerated value
    "Private text" with its `digest`, never the text. A page shows "Private text"; replacing one value by another is
    still a change the log shows ("Private text" to "Private text") without saying anything about what they say.
    `of` names what the value is when it stands among others (a contact's "Email" in the contact list): a msgid, shown
    as "Email: Private text". The digest is stored for comparing rows and is printed on no page
    (AuditLog.shown_changes): whoever could read it beside a value they typed themselves could test a guess."""
    value = {**message(_('Private text')), 'rev': digest(text)}
    return {**value, 'of': english(of)} if of else value


_kept_private = private       # `snapshot` takes the private field names under the function's own name


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
            value = _kept_private(value)
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


LABEL_LENGTH = AuditLog._meta.get_field('entity_label').max_length


def bounded(label):
    """A label that fits the log's column: longer ones are cut, with an ellipsis (a record's own label is written to be short
    and findable, a stock operation's shortens the units it lists first; this is what stops any other from failing the write)."""
    return label if len(label) <= LABEL_LENGTH else label[:LABEL_LENGTH - 1] + '…'


LATE_COMMIT = timedelta(minutes=5)


def revision():
    """A token that changes whenever the log gets a row: the newest entry's time and how many entries lie in the five
    minutes up to it. Every change to a farm record writes its entry in the same transaction (this module), so a
    page that shows records can ask "did anything change?" in two indexed queries (`created_at`) instead of
    reading them. The count catches an entry committed late with a stamp earlier than the newest one (the stamp is
    taken when the row is made, the row appears when its transaction commits). Read it BEFORE the data it stands
    for: a change that lands between the two reads then makes the next read differ, never the other way round."""
    newest = AuditLog.objects.aggregate(newest=Max('created_at'))['newest']
    if newest is None:
        return '0'
    recent = AuditLog.objects.filter(created_at__gte=newest - LATE_COMMIT, created_at__lte=newest).count()
    return f'{newest.isoformat()}/{recent}'


def record(user, action, instance, changes=None, entity_type=None, label=None, severity=AuditLog.Severity.NORMAL):
    """One entry. `severity` critical marks someone going on past a warning that protects fish or food
    (farm/handling): the activity log shows it apart and the later alarms read it."""
    found = entry(user, action, instance, changes, entity_type, label, severity)
    found.save()
    return found


def created(user, instance, values, **kwargs):
    """The entry of a new record with its non-empty values (a snapshot), not saved yet: for a writer that logs many
    records in one statement (AuditLog.objects.bulk_create, the alarms' pass)."""
    changes = {label: [None, value] for label, value in values.items() if value is not None}
    return entry(user, AuditLog.Action.CREATE, instance, changes, **kwargs)


def entry(user, action, instance, changes=None, entity_type=None, label=None, severity=AuditLog.Severity.NORMAL):
    """One entry as `record` writes it, not saved yet."""
    return AuditLog(
        user=user if user and user.is_authenticated else None,
        user_name=user.get_username() if user and user.is_authenticated else 'system',
        action=action,
        entity_type=english(entity_type or entity_type_of(type(instance))),
        entity_id=str(instance.pk),
        # The record's name as English at rest like everything else: a name built from choices (a water limit's
        # parameter, a plan's kind) would otherwise be stored in the language of the person making the change.
        entity_label=bounded(label or english(instance)),
        changes=changes or {},
        severity=severity,
    )


def record_create(user, instance, values, **kwargs):
    """Logs a new record with its non-empty values (a snapshot)."""
    found = created(user, instance, values, **kwargs)
    found.save()
    return found


def record_update(user, instance, before, after, **kwargs):
    """Logs what differs between two snapshots; logs nothing when nothing changed."""
    changes = diff(before, after)
    if changes:
        return record(user, AuditLog.Action.UPDATE, instance, changes, **kwargs)
    return None


def record_delete(user, instance, **kwargs):
    return record(user, AuditLog.Action.DELETE, instance, **kwargs)

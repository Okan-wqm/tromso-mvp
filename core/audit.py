"""Writing the audit log. Call these inside the same transaction as the change they describe, so a
change is never stored without its log row (or the other way round).

The log is language-neutral at rest: labels, record types and enumerated values are stored as their
English msgids whatever language the person who made the change was using, and shown translated
(AuditLog.shown_changes). Build every snapshot inside `source_language()` (core.crud does); a person's
own text (names, descriptions) is stored as written and never translated."""
import functools
import hashlib
import hmac
from datetime import timedelta

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Max
from django.db.models.functions import Cast
from django.utils import translation
from django.utils.text import capfirst
from django.utils.translation import gettext_lazy as _, gettext_noop

from . import sealing
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
    """The log entries `user` may read: every one but those of a restricted record type they lack the permission for,
    and those about a record the viewer of the moment may not see (core.sealing: a sealed cell's records, decided at
    read time from the same seals, and the works each entry was stamped with when written, `stamp`)."""
    entries = AuditLog.objects.all() if entries is None else entries
    hidden = hidden_types(user)
    # The rows about records the person may not see are left out by the log's own manager (AuditLogManager, the ABOUT
    # rule, `sealed_out`): every AuditLog queryset carries it.
    return entries.exclude(entity_type__in=hidden) if hidden else entries


def entity_types(model):
    """Every name a row about a record of `model` may give it: the log's (its own, and that of each tab that serves it)
    and the model's label (`app_label.model_name`, as the form keys name it: core.models.EntryKey, review L8), so the
    rule that hides such rows with their record matches them all."""
    from .crud import Resource
    return sorted({entity_type_of(model), model._meta.label_lower,
                   *(tab.entity_type() for tab in Resource.registry if tab.model is model)})


def sealed_out(entries):
    """`entries` without those about a record whoever is looking may not see (core.sealing's ABOUT rule: the activity
    log, the read log, the form keys). Decided when the statement is compiled, never when the queryset is built
    (`HiddenEntries`, as core.sealing.HiddenRows: landing review 2, N6): nothing is built for a reader from whom nothing
    is hidden, and a queryset built in one context and read in another is narrowed for its reader."""
    return entries.exclude(models.Q(HiddenEntries(entries.model)))


class HiddenEntries(models.Expression):
    """The rows of an ABOUT model (the activity log, the read log, the form keys) about a record hidden from whoever is
    looking, as a condition on the rows' own columns, built when the SQL is compiled: FALSE for the system and for a
    person from whom nothing is hidden; otherwise `_hidden_entries`, compiled in place (no join: the record type, the
    record's id and the stamp are the rows' own)."""

    contains_aggregate = False

    def __init__(self, model):
        super().__init__(output_field=models.BooleanField())
        self.model = model

    def __repr__(self):
        return f'HiddenEntries({self.model._meta.label})'

    def get_group_by_cols(self):
        return []

    def as_sql(self, compiler, connection):
        if sealing.who() is None:
            return 'FALSE', []
        found = sealing.reach()
        if not any(found.hidden.values()):
            return 'FALSE', []
        condition = _hidden_entries(self.model, found)
        if condition is None:
            return 'FALSE', []
        where = condition.resolve_expression(compiler.query, allow_joins=False)
        sql, params = compiler.compile(where)
        return (sql, params) if sql else ('FALSE', [])


def _hidden_entries(model, found):
    """The condition (a Q on `model`'s rows) of the rows about a record hidden from a person with the Reach `found`."""
    condition = None
    for seal in sealing.registry():
        if not seal.filters:
            continue
        # Every level of parents and children the seal follows (sealing.seal_depth): what an entry is about and the
        # records it hangs on, to the record sealed by its own cell (read when a person opens the log; the change token
        # reads the entries' stamps instead, `revision`).
        # An entry is hidden when its record is hidden for the record's part or for any part its entries hold
        # (`log_parts`: an experiment's entries hold its design and its places, review L6).
        for part in dict.fromkeys((seal.part, *seal.log_parts)):
            rows = sealing.hidden(seal, part, depth=sealing.seal_depth(seal.model))
            if rows is None:
                continue
            ids = sealing.unsealed(seal.model).filter(rows).annotate(log_id=Cast('pk', models.CharField())).values(
                'log_id')
            each = models.Q(entity_type__in=entity_types(seal.model), entity_id__in=ids)
            condition = each if condition is None else condition | each
    if model is AuditLog:
        # And those stamped, when they were written, with a work hidden from the person (`stamp`): an entry's text was
        # written once for everyone and may name what its record reached then (a transfer from an open tank into a
        # sealed one names both, while the operation itself stays visible with its open line).
        left_out = _left_out(found)
        if left_out is not None:
            condition = left_out if condition is None else condition | left_out
    return condition


@functools.cache
def _sealed_types():
    """{entity type: model} of every model whose rows a seal filters (core.sealing), by each name the log gives it."""
    return {entity_type: seal.model for seal in sealing.registry() if seal.filters
            for entity_type in entity_types(seal.model)}


def stamp(entries):
    """Gives each new entry about a sealed record the works its record lies in now (core.sealing.works_of: its own
    work, its cells, its parents' and children's), read as the system in one statement per kind of record and level.
    AuditLog.save and the log's bulk_create call it, so every entry written through the ORM is stamped when it is
    made; the stamp never changes after (the log is append-only). An entry about any other record keeps no work."""
    groups = {}
    for found in entries:
        model = _sealed_types().get(found.entity_type)
        if model is not None and not found.works:
            groups.setdefault(model, []).append(found)
    for model, group in groups.items():
        works = sealing.works_of(model, sorted({found.entity_id for found in group}))
        for found in group:
            found.works = sorted(works.get(found.entity_id, ()))


def _left_out(reach):
    """The condition on the log's entries that a person with this Reach may not see: an entry about a record of a kind
    some seal filters, stamped with a work hidden from them for a part that record is sealed with (or with UNKNOWN when
    anything is hidden), unless they hold Oversee and the record is a farm fact all the way down. None when nothing is
    hidden from them."""
    if not reach.hidden:
        return None
    by_works = {}
    for entity_type, model in _sealed_types().items():
        if reach.oversee and sealing.stamp_shows_overseer(model):
            continue
        works = set().union(*(reach.hidden.get(part, ()) for part in sealing.stamp_parts(model)))
        if works:
            by_works.setdefault(frozenset(works), []).append(entity_type)
    condition = None
    for works, types in by_works.items():
        each = models.Q(entity_type__in=sorted(types), works__overlap=sorted(works) + [sealing.UNKNOWN])
        condition = each if condition is None else condition | each
    return condition


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
    (AuditLog.shown_changes; the database viewer masks the log's `changes`), so nobody tests a guess through the
    application either: a digest is read only with direct access to the database. The one digest of the log:
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
    # Only the entries whoever is looking may read: a change to a record of work hidden from them never moves their
    # token, so its timing tells them nothing (review F8). Read from the works each entry was stamped with when it was
    # written (`stamp`) and what the person reads (core.sealing.reach, one statement a request): two indexed queries
    # still, the seal itself is never read here. A person from whom nothing is hidden reads the plain log.
    entries = AuditLog._base_manager.all()            # the stamps, never the seal: `_left_out` below
    left_out = _left_out(sealing.reach())
    if left_out is not None:
        entries = entries.exclude(left_out)
    newest = entries.aggregate(newest=Max('created_at'))['newest']
    if newest is None:
        return '0'
    recent = entries.filter(created_at__gte=newest - LATE_COMMIT, created_at__lte=newest).count()
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


# The words a data migration writes into the log (core/migrations/_private.py: the record type of the conversion's own
# row, the labels of its counts, what a contact's unsure part is called). The catalogs are not read from migrations,
# so they are marked here; core/tests_private_log.py holds the two lists together.
MIGRATION_WORDS = (
    gettext_noop('activity log'), gettext_noop('Entries converted'), gettext_noop('Values made private'),
    gettext_noop('Contact e-mails and phones made private, the contact kept'),
    gettext_noop('Roles made private with a phone they could not be told apart from'),
    gettext_noop('Contact lists made private whole'),
    gettext_noop('Entries whose contact list was made private whole'), gettext_noop('Role or phone'),
    # the label of the row the erasure procedure writes on a task (docs/erasure.md, step 6): not 'Note', which is
    # a private label of a task and would read as a plain value left behind (core.W004)
    gettext_noop('Erased on request'),
)


def values_before(model, ids, moment):
    """{record id: {label: value}} of these records of `model`: for each label a change logged after `moment` names,
    the value it had before the first such change, as the log keeps it (the display value of `snapshot`; a date as
    ISO, a foreign key as its record's name). What a record looked like at `moment` is its value now, overridden by
    these. Read as the person looking (the log's own sealing): a record hidden from them is hidden here too."""
    found = {}
    if not ids:
        return found
    entries = (AuditLog.objects.filter(entity_type=entity_type_of(model), entity_id__in=[str(pk) for pk in ids],
                                       action=AuditLog.Action.UPDATE, created_at__gt=moment)
               .order_by('created_at').values_list('entity_id', 'changes'))
    for entity_id, changes in entries:
        earlier = found.setdefault(entity_id, {})
        for label, pair in changes.items():
            if label not in earlier and isinstance(pair, list) and len(pair) == 2:
                earlier[label] = pair[0]
    return found

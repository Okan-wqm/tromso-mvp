"""What migration core/0011 does, and what `manage.py private_log_values` and the check core.W004 run again: the plain
values in the activity log that were decided private become private values (owner decision F-059 / F-061 / F-179 /
F-050, 2026-11-10; review R1 to R4). Written here once, as it is when the migration is made: the migration, the command
and the check all call this, so there is one conversion. It must never change with the table or with the code's idea
of a private value: an old database migrating later runs exactly this. Not a migration (the underscore).

- A plain value under one of the labels of PRIVATE becomes its private value (core.audit.private: the enumerated
  "Private text" with the short keyed digest).
- A contact list (CONTACTS) was one composed sentence, main's ContactList.describe: per contact `name` or
  `name (role?, email?, phone?, primary?)`, the contacts joined by "; ". It is taken apart and becomes exactly what the
  code writes now (one list of parts per contact: who it is in plain text, the e-mail and the phone as private values
  that say which they are), so only what was decided private is hidden and old and new rows compare. Nothing that
  stood in the e-mail or the phone field may come out plain, so what cannot be proved is made private, never left:
  a role and a phone that cannot be told apart become one private part beside the name (`part`), and a sentence that
  cannot be taken apart at all (a "; " or a bracket typed inside a field, two addresses) becomes one private value
  (`whole`). Both are counted, and the entries of the second kind are named in the log's row.

One-way: the words are not kept anywhere, which is the point. The only way back is a backup taken before."""
import hashlib
import hmac
import json
import re

from django.conf import settings

from ._log import system_entry

# (how the log names the kind of record, the label of the field), English at rest.
CONTACTS = (('site', 'Contacts'), ('supplier', 'Contacts'))
CONTACT_FIELDS = ('Email', 'Phone')           # what a contact's private parts are called (the fields' names)
UNSURE = 'Role or phone'
PRIVATE = (
    ('site', 'Contact email'), ('site', 'Contact phone'),
    ('regulatory report', 'Contact e-mail'), ('regulatory report', 'Contact telephone'),
    ('supplier', 'Email'), ('supplier', 'Phone'),
    ('task', 'Description'), ('recurring task', 'Description'),
    ('task', 'Note'), ('task', 'Completion note'), ('task', 'Reason for cancelling'),
)
RECORD = ('activity log', 'core.0011', 'Private values')      # the log's own row: record type, id, label
SAID = 'core 0011: contact e-mail and phone and people\'s free text written into the log before the owner decision ' \
       'of 2026-11-10 were made private values (a keyed digest instead of the text); who, when and which record are ' \
       'unchanged. One-way: the words are kept nowhere.'
COUNTS = {
    'rows': 'Entries converted',
    'values': 'Values made private',
    'contact_values': 'Contact e-mails and phones made private, the contact kept',
    'parts': 'Roles made private with a phone they could not be told apart from',
    'whole': 'Contact lists made private whole',
}
WHOLE_IDS = 'Entries whose contact list was made private whole'

ITEM = re.compile(r'^([^()]+?)(?: \(([^()]*)\))?$')
EMAIL = re.compile(r'^[^@\s,;()]+@[^@\s,;()]+\.[^@\s,;()]+$')
PHONE = re.compile(r'^\+?\d[\d\s./-]{3,}$')


def key():
    """core.audit.digest_key, as it is when this is made: the digests' own key, the secret key when it has none."""
    return getattr(settings, 'AUDIT_DIGEST_KEY', '') or settings.SECRET_KEY


def key_refusal():
    """Why real data is not converted under this key, or None. The conversion is one-way: the key in force when it runs
    is the key of every converted value for good, and whoever holds it can recover a short value (a phone number) from
    its digest by trying them all. So a key printed in the repository (the settings' fallback, anything Django marks
    insecure) is refused when DEBUG is off; a developer's own machine (DEBUG on) is let through."""
    if settings.DEBUG or not key().startswith('django-insecure-'):
        return None
    return ('core 0011 will not convert: the key of the digests is the fallback printed in the repository (or another '
            '"django-insecure-" key), and the conversion is one-way, so every converted value would keep it for good. '
            'Set DJANGO_AUDIT_DIGEST_KEY (or DJANGO_SECRET_KEY) to a secret of this server, the one the server runs '
            'with, and run it again.')


def private(text, of=None):
    """core.audit.private, as it is when this is made."""
    rev = hmac.new(key().encode(), str(text).encode(), hashlib.sha256).hexdigest()[:8]
    return {'msgid': 'Private text', 'rev': rev, **({'of': of} if of else {})}


def _contact(item):
    """One contact of an old sentence as (its parts, the values made private, whether a role went with a phone), or
    None when it cannot be taken apart."""
    found = ITEM.match(item)
    if not found:
        return None
    name, inside = found.groups()
    tokens = inside.split(', ') if inside else []
    primary = bool(tokens) and tokens[-1] == 'primary'
    tokens = tokens[:-1] if primary else tokens

    def who(role=''):
        details = ([role] if role else []) + (['primary'] if primary else [])
        return f'{name} ({", ".join(details)})' if details else name

    mails = [index for index, token in enumerate(tokens) if EMAIL.match(token)]
    if len(mails) > 1:
        return None
    if mails:                                   # the address anchors the split: the role before it, the phone after it
        role, phone = ', '.join(tokens[:mails[0]]), ', '.join(tokens[mails[0] + 1:])
        hidden = [private(tokens[mails[0]], CONTACT_FIELDS[0])] + ([private(phone, CONTACT_FIELDS[1])] if phone else [])
        return [who(role), *hidden], len(hidden), False
    if len(tokens) == 2 and PHONE.match(tokens[1]) and not PHONE.match(tokens[0]):
        return [who(tokens[0]), private(tokens[1], CONTACT_FIELDS[1])], 1, False
    if len(tokens) == 1 and PHONE.match(tokens[0]):
        return [who(), private(tokens[0], CONTACT_FIELDS[1])], 1, False
    if not tokens:
        return [who()], 0, False
    return [who(), private(', '.join(tokens), UNSURE)], 0, True      # a role, a phone or both: private together


def contacts(sentence):
    """(what an old contact-list sentence becomes, 'kept' | 'part' | 'whole')."""
    made = [_contact(item) for item in sentence.split('; ')]
    if any(contact is None for contact in made):
        return private(sentence), 'whole'
    return [parts for parts, _hidden, _unsure in made], 'part' if any(unsure for *_rest, unsure in made) else 'kept'


def plan(cursor):
    """([(id, record type, record label, created at, the changes as they will be)], the counts) of the rows that still
    hold a plain value under a private label. Reads only."""
    plain, lists = {}, {}
    for entity_type, label in PRIVATE:
        plain.setdefault(entity_type, []).append(label)
    for entity_type, label in CONTACTS:
        lists.setdefault(entity_type, []).append(label)
    counts = {'rows': 0, 'values': 0, 'contact_values': 0, 'parts': 0, 'whole': 0, 'whole_ids': []}
    found = []
    cursor.execute('SELECT id, entity_type, entity_label, created_at, changes FROM audit_log WHERE entity_type = ANY(%s) '
                   'ORDER BY created_at, id', [sorted({*plain, *lists})])
    for pk, entity_type, entity_label, created_at, changes in cursor.fetchall():
        changes = json.loads(changes) if isinstance(changes, str) else changes
        touched = whole = False
        for label in plain.get(entity_type, ()):
            pair = changes.get(label)
            if isinstance(pair, list) and any(isinstance(value, str) for value in pair):
                counts['values'] += sum(1 for value in pair if isinstance(value, str))
                changes[label] = [private(value) if isinstance(value, str) else value for value in pair]
                touched = True
        for label in lists.get(entity_type, ()):
            pair = changes.get(label)
            if not isinstance(pair, list) or not any(isinstance(value, str) for value in pair):
                continue
            after = []
            for value in pair:
                if isinstance(value, str):
                    value, kind = contacts(value)
                    if kind == 'whole':
                        counts['whole'] += 1
                        whole = True
                    else:
                        counts['contact_values'] += sum(1 for parts in value for part in parts[1:]
                                                        if part.get('of') in CONTACT_FIELDS)
                        counts['parts'] += sum(1 for parts in value for part in parts[1:] if part.get('of') == UNSURE)
                after.append(value)
            changes[label] = after
            touched = True
        if touched:
            counts['rows'] += 1
            found.append((str(pk), entity_type, entity_label, created_at, changes))
            if whole:
                counts['whole_ids'].append(str(pk))
    return found, counts


def convert(schema_editor):
    """Makes the plain values private and returns the counts. The log is append-only by a trigger (core/0003): it is
    set aside for these updates only, inside the caller's transaction, and set back; only `changes` is written. What
    was done is said in the log itself (one row by 'system') with the entries whose contact list could not be taken
    apart."""
    with schema_editor.connection.cursor() as cursor:
        # Before anything is read: writers wait from here to the commit, and this waits for the writers under way, so
        # no row is written between the read and the updates (a session that began before would be missed otherwise;
        # review R4). Readers go on. What a server still running the old code writes after the commit is not this
        # function's to stop: stop that server first; the check core.W004 finds what it left.
        cursor.execute('LOCK TABLE audit_log IN SHARE ROW EXCLUSIVE MODE')
        found, counts = plan(cursor)
        if found and key_refusal():
            raise RuntimeError(key_refusal())
        if found:
            cursor.execute('ALTER TABLE audit_log DISABLE TRIGGER trg_audit_log_append_only')
            for pk, _type, _label, _created, changes in found:
                cursor.execute('UPDATE audit_log SET changes = %s::jsonb WHERE id = %s', [json.dumps(changes), pk])
            cursor.execute('ALTER TABLE audit_log ENABLE TRIGGER trg_audit_log_append_only')
    if found:
        said = {words: [None, str(counts[key])] for key, words in COUNTS.items()}
        if counts['whole_ids']:
            said[WHOLE_IDS] = [None, ', '.join(counts['whole_ids'])]
        system_entry(schema_editor, RECORD[0], RECORD[1], RECORD[2], {**said, 'Note': [None, SAID]})
    return counts


def converted(cursor):
    """How many times the conversion has changed rows of this database (its own rows in the log)."""
    cursor.execute("SELECT count(*) FROM audit_log WHERE user_name = 'system' AND entity_type = %s AND entity_id = %s",
                   [RECORD[0], RECORD[1]])
    return cursor.fetchone()[0]


def report(found, counts):
    """The lines that say what a conversion does (or did): the counts, and the entries whose contact list cannot be
    taken apart by id, record type and record, never by their words."""
    if not counts['rows']:
        return ['No plain value under a private label: nothing to convert.']
    lines = [f"  {counts['values']} value(s) made private (a site's, a supplier's or a report's own e-mail or phone; "
             f"a person's free text on a task)",
             f'  {counts["contact_values"]} contact e-mail(s) and phone(s) made private, the contact (name, role, '
             f'primary) kept',
             f'  {counts["parts"]} role(s) made private together with a phone they could not be told apart from, the '
             f'name kept',
             f'  {counts["whole"]} contact list(s) made private whole: they could not be taken apart']
    by_id = {pk: (entity_type, entity_label) for pk, entity_type, entity_label, _created, _changes in found}
    lines += [f'    {pk}  {by_id[pk][0]}  {by_id[pk][1]}' for pk in counts['whole_ids']]
    return lines

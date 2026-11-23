"""What migration core/0011 does, and what `manage.py private_log_values` and the check core.W004 run again: the plain
values in the activity log that were decided private become private values (owner decision F-059 / F-061 / F-179 /
F-050, 2026-11-10; review R1 to R4). Written here once, as it is when the migration is made: the migration, the command
and the check all call this, so there is one conversion. It must never change with the table or with the code's idea
of a private value: an old database migrating later runs exactly this. Not a migration (the underscore).

Changed once since core/0011 was first applied (2026-11-11, review R24): a role typed as pieces of a number is judged as
a whole (`_contact`). A database converted before that change kept such a contact list as plain text inside its
converted parts, and nothing here finds it again (a converted list is not a string any more); the one database
converted before it, the development one, held no such row (the review's scan of its 6,755 rows). Every database that
runs core/0011 or the command from now on gets the rule as it is here.

- A plain value under one of the labels of PRIVATE becomes its private value (core.audit.private: the enumerated
  "Private text" with the short keyed digest).
- A contact list (CONTACTS) was one composed sentence, main's ContactList.describe: per contact `name` or
  `name (role?, email?, phone?, primary?)`, the contacts joined by "; ". It is taken apart and becomes exactly what the
  code writes now (one list of parts per contact: who it is in plain text, the e-mail and the phone as private values
  that say which they are), so only what was decided private is hidden and old and new rows compare. It is read with
  matched brackets (a bracket inside a role or a phone is part of it) and from the right-hand end, where the e-mail
  and the phone are known by their form. No e-mail address and no number of five digits or more may come out plain
  unless it is proved to be the role (the one field left of the e-mail): what cannot be told apart is made private,
  never left. A role and a phone that cannot be told apart become one private part beside the name (`part`); a
  sentence whose brackets do not balance, or with a name that holds an address or a number, becomes one private value
  (`whole`). Both are counted, and the entries of the second kind are named in the log's row. Chosen: a role that
  stands alone or beside a phone is kept, so words without a number typed into the phone box ("ask reception") stay
  in plain text as a role; they hold no number.

One-way: the words are not kept anywhere, which is the point. The only way back is a backup taken before."""
import hashlib
import hmac
import json
import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

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

PHONE = re.compile(r'^[+(]?\d[\d\s()./+-]*$')
NUMBER = 5            # this many digits make a number: a phone has them, a role ("24/7", "Shift 2") has fewer


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


def _digits(text):
    return sum(character.isdigit() for character in text)


def _telling(text):
    """Whether `text` holds what may not stay in plain text unless it is proved to be something else: an address
    (an "@") or a number (five digits or more)."""
    return '@' in text or _digits(text) >= NUMBER


def _phone(text):
    """Whether `text` has the form of a phone number: digits with spaces and + ( ) . / -, five digits or more."""
    return bool(PHONE.match(text)) and _digits(text) >= NUMBER


def is_email(text):
    """Whether `text` has the form of an e-mail address: the definition of the contact form's own e-mail field
    (Django's validate_email, which the model's EmailField and its form field call), so what the form accepted as an
    address is what is read as one here (`kari@localhost`, `"a,b"@example.com`), and nothing else is (review R20)."""
    try:
        validate_email(text)
    except ValidationError:
        return False
    return True


def _split(text, separator):
    """`text` split on `separator` where no bracket is open, or None when its brackets do not balance (one closes that
    was never opened, or one stays open). A separator inside brackets belongs to what the brackets hold."""
    parts, depth, start, index = [], 0, 0, 0
    while index < len(text):
        if text[index] == '(':
            depth += 1
        elif text[index] == ')':
            depth -= 1
            if depth < 0:
                return None
        elif depth == 0 and text.startswith(separator, index):
            parts.append(text[start:index])
            index += len(separator)
            start = index
            continue
        index += 1
    return None if depth else [*parts, text[start:]]


def _name_and_details(item):
    """(name, details) of one contact as main's describe wrote it, `name` or `name (details)`: the details are the last
    bracket group, found by matching brackets from the end, and the name is everything before it (it may hold balanced
    brackets of its own). (item, None) for a contact without details; (None, None) when the last group has no name
    before it. The brackets of `item` balance (the caller split on them)."""
    if not item.endswith(')'):
        return item, None
    depth = 0
    for index in range(len(item) - 1, -1, -1):
        depth += {')': 1, '(': -1}.get(item[index], 0)
        if depth == 0:
            if index < 2 or item[index - 1] != ' ':
                return None, None
            return item[:index - 1], item[index + 1:-1]
    return None, None


def _contact(item):
    """One contact of an old sentence as (its parts, whether its details went private together), or None when it cannot
    be taken apart safely.

    The details were written in a fixed order: role, e-mail, phone, then "primary". Read from the right-hand end:
    - a last "primary" is the flag;
    - exactly one detail in the form of an e-mail is the e-mail; everything left of it is the role (the role is the
      only field before the e-mail, so that is proved whatever the role looks like) and everything right of it is the
      phone, whatever its form;
    - no e-mail: the trailing details in the form of a phone number are the phone, and what stands left of them is the
      role, unless it holds an address or a number (`_telling`, of all of it together: a number typed in pieces,
      "55 12, 34 56" or "0532, 123, 4567", is split on its commas into details of fewer than five digits each, and
      judged one by one every piece passed as a role; review R24): then role and phone cannot be told apart and the
      details become one private part beside the name;
    - more than one detail in the form of an e-mail: the details become one private part beside the name.
    A name is never kept when it holds an address or a number, and a contact is never kept without a name."""
    name, inside = _name_and_details(item)
    if not name or _telling(name):
        return None
    tokens = _split(inside, ', ') if inside else []
    primary = bool(tokens) and tokens[-1] == 'primary'
    tokens = tokens[:-1] if primary else tokens

    def who(role=''):
        details = ([role] if role else []) + (['primary'] if primary else [])
        return f'{name} ({", ".join(details)})' if details else name

    mails = [index for index, token in enumerate(tokens) if is_email(token)]
    if len(mails) == 1:
        role, phone = ', '.join(tokens[:mails[0]]), ', '.join(tokens[mails[0] + 1:])
        hidden = [private(tokens[mails[0]], CONTACT_FIELDS[0])] + ([private(phone, CONTACT_FIELDS[1])] if phone else [])
        return [who(role), *hidden], False
    if not mails:
        cut = len(tokens)
        while cut and _phone(tokens[cut - 1]):
            cut -= 1
        if not _telling(', '.join(tokens[:cut])):
            phone = ', '.join(tokens[cut:])
            return [who(', '.join(tokens[:cut])), *([private(phone, CONTACT_FIELDS[1])] if phone else [])], False
    return [who(), private(', '.join(tokens), UNSURE)], True


def contacts(sentence):
    """(what an old contact-list sentence becomes, 'kept' | 'part' | 'whole'). The contacts are split on "; " where no
    bracket is open, so a bracket inside a role or a phone ("Service manager (24 h line)", "(0532) 123 45 67") is read
    as part of it. Whole, the sentence as one private value: its brackets do not balance, or a contact has no name or
    a name that holds an address or a number. (A phone such as `98 work); 99123456 (home` reads exactly like the end of
    one contact and the start of the next; the second "name" is a number, so the sentence is made private whole
    rather than a number kept as a name.)"""
    items = _split(sentence, '; ')
    made = [_contact(item) for item in items] if items is not None else [None]
    if any(contact is None for contact in made):
        return private(sentence), 'whole'
    return [parts for parts, _unsure in made], 'part' if any(unsure for _parts, unsure in made) else 'kept'


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
    lines += [f'    {pk}  {"  ".join(by_id.get(pk, ("", "")))}'.rstrip() for pk in counts['whole_ids']]
    return lines

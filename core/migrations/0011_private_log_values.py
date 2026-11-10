"""The personal data already in the activity log is made private (owner decision F-059 / F-061 / F-179 / F-050,
2026-11-10). From this migration on the code logs a contact's e-mail and phone and a task's free-text notes as private
values (core.audit.private: the enumerated "Private text" with a short keyed digest); the rows written before held them
in plain text, in a log nobody can erase from. This converts those values in the same way: each plain value under one
of the labels below becomes its private value, so the log still shows that the field changed and whether two values
were equal, never the value. An old contact list was one composed sentence ("Kari (Vet, kari@x.no, +47 …, primary)")
whose parts cannot be told apart reliably, so the whole sentence becomes one private value (the name and role in old
rows go with it; new rows keep them).

The log is append-only by a trigger (core/0003). The trigger is set aside for the updates only, inside this
migration's own transaction, and set back (as alarms/migrations/_reverse.py does for its table); nothing but `changes`
is written, so who did what to which record and when stays as it was. What was converted is counted, printed and said
in the log itself (one row by 'system').

The digest and the list are written here, as they are when this migration is made (a migration never reads live code;
core/tests_private_log.py holds both to the code). Going back changes nothing: the words are gone, which is the point,
and the code before this shows a private value as "Private text" too."""
import hashlib
import hmac
import json

from django.conf import settings
from django.db import migrations

from ._log import system_entry

# (how the log names the kind of record, the label of the field), English at rest.
PRIVATE = (
    ('site', 'Contacts'), ('supplier', 'Contacts'),
    ('site', 'Contact email'), ('site', 'Contact phone'),
    ('regulatory report', 'Contact e-mail'), ('regulatory report', 'Contact telephone'),
    ('task', 'Note'), ('task', 'Completion note'), ('task', 'Reason for cancelling'),
)
SAID = 'core 0011: contact e-mail and phone and task notes written into the log before the owner decision of ' \
       '2026-11-10 were made private values (a keyed digest instead of the text); who, when and which record are ' \
       'unchanged.'


def private(text):
    """core.audit.private, as it is when this migration is made."""
    rev = hmac.new(settings.SECRET_KEY.encode(), str(text).encode(), hashlib.sha256).hexdigest()[:8]
    return {'msgid': 'Private text', 'rev': rev}


def convert(apps, schema_editor):
    """Returns {'rows': the log rows changed, 'values': the plain values made private}."""
    labels = {}
    for entity_type, label in PRIVATE:
        labels.setdefault(entity_type, []).append(label)
    found, values = [], 0
    with schema_editor.connection.cursor() as cursor:
        cursor.execute('SELECT id, entity_type, changes FROM audit_log WHERE entity_type = ANY(%s) ORDER BY created_at',
                       [list(labels)])
        for pk, entity_type, changes in cursor.fetchall():
            changes = json.loads(changes) if isinstance(changes, str) else changes
            made = 0
            for label in labels[entity_type]:
                pair = changes.get(label)
                if isinstance(pair, list):
                    changes[label] = [private(value) if isinstance(value, str) else value for value in pair]
                    made += sum(1 for value in pair if isinstance(value, str))
            if made:
                found.append((pk, changes))
                values += made
        if found:
            cursor.execute('ALTER TABLE audit_log DISABLE TRIGGER trg_audit_log_append_only')
            for pk, changes in found:
                cursor.execute('UPDATE audit_log SET changes = %s::jsonb WHERE id = %s', [json.dumps(changes), pk])
            cursor.execute('ALTER TABLE audit_log ENABLE TRIGGER trg_audit_log_append_only')
    if found:
        system_entry(schema_editor, 'activity log', 'core.0011', 'Private values', {
            'Entries converted': [None, str(len(found))], 'Values made private': [None, str(values)],
            'Note': [None, SAID]})
        print(f'\n  core 0011: {values} plain value(s) in {len(found)} activity-log row(s) made private (logged).')
    return {'rows': len(found), 'values': values}


class Migration(migrations.Migration):
    dependencies = [('core', '0010_clock_tolerance')]

    operations = [migrations.RunPython(convert, migrations.RunPython.noop)]

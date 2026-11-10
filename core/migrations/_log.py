"""The activity log's row for something a data migration changed: by 'system', on the record, in the log's own shape
({label: [old, new]}, English at rest). Written in SQL because the log's columns are the database's now, whatever the
migration state says (as alarms/migrations/_reverse.py writes its rows). A migration that calls it depends on
('core', '0007_audit_severity'). Not a migration (the underscore)."""
import json

SYSTEM = 'system'


def system_entry(schema_editor, entity_type, entity_id, entity_label, changes, action='update'):
    """One row of the activity log, made by nobody signed in."""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO audit_log (id, created_at, user_name, action, entity_type, entity_id, entity_label, changes, "
            "severity) VALUES (gen_random_uuid(), clock_timestamp(), %s, %s, %s, %s, %s, %s::jsonb, 'normal')",
            [SYSTEM, action, entity_type, str(entity_id), str(entity_label)[:255], json.dumps(changes)])


def entries(schema_editor, entity_type):
    """[(record id, who, action, changes)] of the log's rows about a kind of record, oldest first: what a migration
    reads to tell what a person chose from what a migration did, and to go back over exactly what it did itself (`who`
    is SYSTEM for its own rows)."""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute('SELECT entity_id, user_name, action, changes FROM audit_log WHERE entity_type = %s '
                       'ORDER BY created_at, id', [entity_type])
        return [(found, who, action, json.loads(changes) if isinstance(changes, str) else changes)
                for found, who, action, changes in cursor.fetchall()]

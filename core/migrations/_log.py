"""The activity log's row for something a data migration changed: by 'system', on the record, in the log's own shape
({label: [old, new]}, English at rest). Written in SQL because the log's columns are the database's now, whatever the
migration state says (as alarms/migrations/_reverse.py writes its rows). A migration that calls it depends on
('core', '0007_audit_severity'). Not a migration (the underscore)."""
import json


def system_entry(schema_editor, entity_type, entity_id, entity_label, changes, action='update'):
    """One row of the activity log, made by nobody signed in."""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO audit_log (id, created_at, user_name, action, entity_type, entity_id, entity_label, changes, "
            "severity) VALUES (gen_random_uuid(), clock_timestamp(), 'system', %s, %s, %s, %s, %s::jsonb, 'normal')",
            [action, entity_type, str(entity_id), str(entity_label)[:255], json.dumps(changes)])


def system_entries(schema_editor, entity_type, entity_id=None):
    """[changes] of the rows `system_entry` wrote about a kind of record (or one record), oldest first: what a migration
    reads to go back over exactly what it did."""
    sql = "SELECT entity_id, changes FROM audit_log WHERE user_name = 'system' AND entity_type = %s"
    values = [entity_type]
    if entity_id is not None:
        sql += ' AND entity_id = %s'
        values.append(str(entity_id))
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(sql + ' ORDER BY created_at', values)
        return [(found, json.loads(changes) if isinstance(changes, str) else changes)
                for found, changes in cursor.fetchall()]

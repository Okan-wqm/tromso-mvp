"""What alarms 0007, 0009 and 0010 do going back with clearances of the causes they added (round-2 review N2). The
clearances are append-only (a trigger), so the trigger is set aside for the one statement, in the migration's own
transaction, and set back; each changed clearance is said in the activity log. Not a migration (the underscore)."""
import json

LABELS = {'structural': 'No longer judged (no fish or no limit)'}


def remap(apps, schema_editor, causes, migration):
    """Each clearance of a cause of `causes` ({new: the nearest older one}) gets the older one, logged per alarm (the
    activity log's row written in SQL: its columns are the database's now, whatever the migration state says)."""
    rows = list(apps.get_model('alarms', 'AlarmClearance').objects.filter(cause__in=causes).select_related('alarm'))
    if not rows:
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute('ALTER TABLE alarm_clearances DISABLE TRIGGER trg_alarm_clearances_append_only')
        for new, old in causes.items():
            cursor.execute('UPDATE alarm_clearances SET cause = %s WHERE cause = %s', [old, new])
        cursor.execute('ALTER TABLE alarm_clearances ENABLE TRIGGER trg_alarm_clearances_append_only')
        for row in rows:
            old = causes[row.cause]
            changes = {'Why': [row.cause, old],
                       'Note': [None, f'alarms {migration} reversed: the cause "{row.cause}" did not exist before it; '
                                      f'the nearest one, "{LABELS.get(old, old)}", stands in.']}
            cursor.execute(
                "INSERT INTO audit_log (id, created_at, user_name, action, entity_type, entity_id, entity_label, changes, "
                "severity) VALUES (gen_random_uuid(), now(), 'system', 'update', 'alarm', %s, %s, %s::jsonb, 'normal')",
                [str(row.alarm_id), row.alarm.summary[:255], json.dumps(changes)])


def refuse(apps, cause, migration, why):
    """Refuses to go back while a clearance of `cause` exists: no older cause says it honestly."""
    found = apps.get_model('alarms', 'AlarmClearance').objects.filter(cause=cause).count()
    if found:
        raise RuntimeError(f'alarms {migration} cannot be reversed: {found} alarm clearance(s) say {why}, which the '
                           f'alarms before it have no word for, and the clearances are append-only (never rewritten '
                           f'to a cause that is not true). Restore a backup taken before it instead.')

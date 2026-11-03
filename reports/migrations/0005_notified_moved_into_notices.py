"""A notice is about a health event (D-4): the disease notice's event, a welfare notice's optional one. That Mattilsynet
was told of a health event is the filing of such a notice, so the times recorded on the events (`authority_notified_at`,
which farm migration 0022 drops) become filed notices here, before the column goes:

- every event with a time, deleted ones too (the authority was told of it all the same), gets one: a disease notice for
  an event with a diagnosis, a welfare notice for one without, filed at that time, through "other", with no receipt;
- recorded by the person the activity log shows set the time, else the event's last editor or its creator; where none
  is known the migration stops and names the events (no user is invented);
- its content is the little the event held, in format 0 (the page says "recorded before notices existed" and never
  compares it with the records), with its hash, and its filing is written in the activity log as a filing is.

The reverse copies each filed notice's time back into its event's column (farm migration 0022's reverse brings the column
back first) and then undoes the move: the notices this migration made (the ones in format 0, whose only content is that
time) are deleted with their snapshots, the freezing triggers stepping aside for it, and the activity log keeps the
entries of the move. A notice filed by a person since is never touched: rolling back past reports 0004 with such a
notice present leaves it without its event, and applying 0004 again is then refused by its check."""

import hashlib
import json

from django.conf import settings
from django.db import migrations

NOTE = 'Recorded on the health event before notices existed.'
KIND_LABEL = {'disease': 'Disease', 'welfare': 'Welfare event'}


def notified(apps, schema_editor):
    HealthEvent = apps.get_model('farm', 'HealthEvent')
    Report = apps.get_model('reports', 'Report')
    Snapshot = apps.get_model('reports', 'ReportSnapshot')
    AuditLog = apps.get_model('core', 'AuditLog')
    User = apps.get_model(*settings.AUTH_USER_MODEL.split('.'))
    events = list(HealthEvent._base_manager.filter(authority_notified_at__isnull=False).order_by('date'))
    if not events:
        return
    who = {}
    for entry in AuditLog.objects.filter(entity_type='health event', entity_id__in=[str(e.pk) for e in events]
                                         ).order_by('created_at'):
        change = entry.changes.get('Mattilsynet notified at')
        if change and change[1] is not None and entry.user_id and str(entry.entity_id) not in who:
            who[str(entry.entity_id)] = entry.user_id
    people = {user.pk: user for user in User.objects.filter(pk__in={
        *who.values(), *(e.updated_by_id for e in events if e.updated_by_id),
        *(e.created_by_id for e in events if e.created_by_id)})}
    chosen, unknown = {}, []
    for event in events:
        for user_id in (who.get(str(event.pk)), event.updated_by_id, event.created_by_id):
            if user_id in people:
                chosen[event.pk] = people[user_id]
                break
        else:
            unknown.append(str(event.pk))
    if unknown:
        raise RuntimeError(
            'Health events %s have a "Mattilsynet notified at" time and no known person recorded it, so it cannot become '
            'a filed notice (a filing names who recorded it). Set the time aside or give the events an editor, then '
            'migrate again.' % ', '.join(unknown))
    for event in events:
        user = chosen[event.pk]
        name = user.username
        kind = 'disease' if event.diagnosis else 'welfare'
        report = Report.objects.create(
            kind=kind, site_id=event.site_id, health_event_id=event.pk, occurred_on=event.date, notes=NOTE,
            submitted_at=event.authority_notified_at, submitted_by_id=user.pk, channel='other', reference='',
            created_by_id=user.pk, updated_by_id=user.pk)
        content = {'kind': kind, 'health_event': str(event.pk), 'diagnosis': event.diagnosis or None,
                   'confirmation': event.confirmation or None, 'notified_at': event.authority_notified_at.isoformat()}
        digest = hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        Snapshot.objects.create(
            report=report, format_version=0, content=content, content_sha256=digest,
            sources_fingerprint=hashlib.sha256(f'health_events:{event.pk}:{event.version}'.encode()).hexdigest())
        AuditLog.objects.create(
            user_id=user.pk, user_name=name, action='update', entity_type='regulatory report',
            entity_id=str(report.pk),
            entity_label=f'{KIND_LABEL[kind]} · {event.date.isoformat()}',
            changes={
                'Status': [{'msgid': 'Draft'}, {'msgid': 'Filed'}],
                'Filed at': [None, event.authority_notified_at.isoformat()],
                'Recorded by': [None, name],
                'Filed through': [None, {'msgid': 'Other'}],
                'Content hash': [None, digest],
                'Recorded on the health event': [None, 'before notices existed'],
            })


FROZEN = (('regulatory_report_snapshots', 'trg_regulatory_report_snapshots_append_only'),
          ('regulatory_reports', 'trg_regulatory_reports_frozen'))


def told(apps, schema_editor):
    HealthEvent = apps.get_model('farm', 'HealthEvent')
    Report = apps.get_model('reports', 'Report')
    Snapshot = apps.get_model('reports', 'ReportSnapshot')
    for report in Report.objects.filter(health_event__isnull=False, submitted_at__isnull=False).order_by(
            'submitted_at'):
        HealthEvent._base_manager.filter(pk=report.health_event_id, authority_notified_at__isnull=True).update(
            authority_notified_at=report.submitted_at)
    moved = list(Snapshot.objects.filter(format_version=0).values_list('report_id', flat=True))
    if not moved:
        return
    for table, trigger in FROZEN:
        schema_editor.execute(f'ALTER TABLE {table} DISABLE TRIGGER {trigger}')
    Snapshot.objects.filter(report_id__in=moved).delete()
    Report.objects.filter(pk__in=moved).delete()
    schema_editor.execute('SET CONSTRAINTS ALL IMMEDIATE')       # the deletes' checks run before the triggers are back
    for table, trigger in FROZEN:
        schema_editor.execute(f'ALTER TABLE {table} ENABLE TRIGGER {trigger}')


class Migration(migrations.Migration):

    dependencies = [
        ('farm', '0021_reports_fields'),
        ('core', '0007_audit_severity'),
        ('reports', '0004_event_notices'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    # The column is read here before farm migration 0022 drops it (and written back here after its reverse).
    run_before = [('farm', '0022_health_notified_at_removed')]

    operations = [migrations.RunPython(notified, told)]

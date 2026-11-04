from django.contrib import admin

from core.admin import AuditedModelAdmin, ReadOnlyAdmin, register_audited

from .models import Report, ReportSnapshot

register_audited('reports')

admin.site.unregister([Report])


@admin.register(Report)
class ReportAdmin(AuditedModelAdmin):
    """Regulatory reports, discarded drafts too: a discarded draft can be restored here (the restore checks the
    constraints again, so not while another one of its period is live). A filed report is never deleted."""

    list_display = ['kind', 'site', 'facility', 'period_start', 'occurred_on', 'submitted_at', 'is_deleted']
    list_filter = ['is_deleted', 'kind']


@admin.register(ReportSnapshot)
class ReportSnapshotAdmin(ReadOnlyAdmin):
    """What was filed, frozen: to look at, never to change (a database trigger refuses it too)."""

    list_display = ['report', 'format_version', 'content_sha256', 'created_at']

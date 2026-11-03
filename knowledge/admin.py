from django.contrib import admin

from core.admin import AuditedModelAdmin

from .models import Document, KnowledgeEntry


@admin.register(Document)
class DocumentAdmin(AuditedModelAdmin):
    """Library documents, deleted ones too, to look at and restore (its file and pages were kept)."""

    list_display = ['__str__', 'year', 'text_status', 'is_deleted']
    search_fields = ['title', 'doi']


@admin.register(KnowledgeEntry)
class KnowledgeEntryAdmin(AuditedModelAdmin):
    """Knowledge entries, deleted ones too, to look at and restore (refused while the document it cites is
    deleted: core.softdelete.restore)."""

    list_display = ['__str__', 'source_kind', 'status', 'is_deleted']
    search_fields = ['statement']

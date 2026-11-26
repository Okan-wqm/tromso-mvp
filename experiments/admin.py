from django.contrib import admin
from django.core.exceptions import ValidationError

from core import sealing
from core.admin import AuditedModelAdmin

from .models import Experiment, ExperimentGroup, Factor, Level, Replicate, ReplicateSystem, ReplicateUnit


class ReadLoggedAdmin(AuditedModelAdmin):
    """The admin's pages read through the seal (the managers), and every read of confidential work outside the platform
    admin's team is in its read log, shown to the lead on Who looked (review F8)."""

    def changelist_view(self, request, extra_context=None):
        response = super().changelist_view(request, extra_context)
        sealing.note_reads(sealing.work_ids(self.get_queryset(request)), 'admin:changelist')
        return response

    def change_view(self, request, object_id, form_url='', extra_context=None):
        response = super().change_view(request, object_id, form_url, extra_context)
        try:
            shown = sealing.work_ids(self.get_queryset(request).filter(pk=object_id))
        except (ValueError, ValidationError):            # an address that names no record: nothing was shown
            shown = []
        sealing.note_reads(shown, 'admin:change')
        return response


@admin.register(Experiment)
class ExperimentAdmin(ReadLoggedAdmin):
    """Experiments, deleted drafts too, and their restore: only the experiment returns (its design is entered again)."""

    list_display = ['code', 'name', 'status', 'is_template', 'site', 'is_deleted']
    search_fields = ['code', 'name']


class DesignRecordAdmin(ReadLoggedAdmin):
    """A part of an experiment's design, deleted ones too, to look at. It is never restored alone: a part brought
    back by itself would skip the checks of the design (a restored draft is designed again)."""

    actions = []


for design_model in (Factor, Level, ExperimentGroup, Replicate, ReplicateUnit, ReplicateSystem):
    admin.site.register(design_model, type(f'{design_model.__name__}Admin', (DesignRecordAdmin,), {
        'list_display': ['__str__', 'is_deleted'],
    }))

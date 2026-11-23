from django.contrib import admin

from core.admin import AuditedModelAdmin

from .models import Experiment, ExperimentGroup, Factor, Level, Replicate, ReplicateSystem, ReplicateUnit


@admin.register(Experiment)
class ExperimentAdmin(AuditedModelAdmin):
    """Experiments, deleted drafts too, and their restore: only the experiment returns (its design is entered again)."""

    list_display = ['code', 'name', 'status', 'is_template', 'site', 'is_deleted']
    search_fields = ['code', 'name']


class DesignRecordAdmin(AuditedModelAdmin):
    """A part of an experiment's design, deleted ones too, to look at. It is never restored alone: a part brought
    back by itself would skip the checks of the design (a restored draft is designed again)."""

    actions = []


for design_model in (Factor, Level, ExperimentGroup, Replicate, ReplicateUnit, ReplicateSystem):
    admin.site.register(design_model, type(f'{design_model.__name__}Admin', (DesignRecordAdmin,), {
        'list_display': ['__str__', 'is_deleted'],
    }))

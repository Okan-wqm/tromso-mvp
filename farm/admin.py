from django.contrib import admin

from core.admin import AuditedModelAdmin, ReadOnlyAdmin, register_audited

from .models import Batch, EquipmentType, FeedingRecord, StockOperation, WaterMeasurement

register_audited('farm')


@admin.register(EquipmentType)
class EquipmentTypeAdmin(ReadOnlyAdmin):
    """The equipment type catalogue, to look at: migrations write it (farm/equipment_types.py)."""

    list_display = ['name', 'code', 'category', 'is_active']
    list_filter = ['category', 'is_active']
    search_fields = ['name', 'code']


class StockRecordAdmin(AuditedModelAdmin):
    """Stock operations, batches and feedings, voided ones too, to look at. A voided operation (and the
    batch of a voided stocking) or feeding does not come back by a restore, which would skip the checks
    (the timeline, the fish a feeding needs): it is entered again on its page, where they run."""

    actions = []


admin.site.unregister([Batch, FeedingRecord, StockOperation, WaterMeasurement])


@admin.register(Batch)
class BatchAdmin(StockRecordAdmin):
    list_display = ['code', 'species', 'input_stage', 'input_date', 'is_deleted']
    search_fields = ['code', 'name']


@admin.register(StockOperation)
class StockOperationAdmin(StockRecordAdmin):
    list_display = ['kind', 'date', 'created_by', 'is_deleted', 'void_reason']
    list_filter = ['is_deleted', 'kind']


@admin.register(FeedingRecord)
class FeedingRecordAdmin(StockRecordAdmin):
    list_display = ['date', 'unit', 'feed', 'amount_kg', 'created_by', 'is_deleted', 'void_reason']
    list_filter = ['is_deleted']
    search_fields = ['unit__code', 'feed__code', 'feed__name']


@admin.register(WaterMeasurement)
class WaterMeasurementAdmin(StockRecordAdmin):
    """Water samples, voided ones too, to look at. A voided sample is entered again on the Water chemistry
    page, like a stock operation: a restore would bring back a value someone said was wrong."""

    list_display = ['__str__', 'source', 'created_by', 'is_deleted', 'void_reason']
    list_filter = ['is_deleted', 'source']
    list_select_related = ['unit__production_department__site', 'system__site', 'created_by']

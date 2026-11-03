from django.contrib import admin

from core.admin import AuditedModelAdmin, ReadOnlyAdmin, register_audited

from .models import (
    Batch, EquipmentType, FeedingRecord, HealthEvent, LiceCount, StockOperation, Treatment, WaterMeasurement,
)

register_audited('farm')


@admin.register(EquipmentType)
class EquipmentTypeAdmin(ReadOnlyAdmin):
    """The equipment type catalogue, to look at: migrations write it (farm/equipment_types.py)."""

    list_display = ['name', 'code', 'category', 'is_active']
    list_filter = ['category', 'is_active']
    search_fields = ['name', 'code']


class StockRecordAdmin(AuditedModelAdmin):
    """Stock operations, batches, feedings and the health records, voided ones too, to look at. A voided
    operation (and the batch of a voided stocking), feeding or health record does not come back by a restore,
    which would skip the checks (the timeline, the fish a feeding needs): it is entered again on its page,
    where they run."""

    actions = []


admin.site.unregister([Batch, FeedingRecord, HealthEvent, LiceCount, StockOperation, Treatment, WaterMeasurement])


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
    list_select_related = ['point__unit__production_department__site', 'point__system__site',
                           'point__equipment__production_department__site', 'created_by']


@admin.register(Treatment)
class TreatmentAdmin(StockRecordAdmin):
    """Treatments, voided ones too, to look at. A voided treatment is recorded again on Operations › Treatments:
    a restore would skip its checks and put its withdrawal back unseen."""

    list_display = ['__str__', 'method', 'start_date', 'end_date', 'created_by', 'is_deleted', 'void_reason']
    list_filter = ['is_deleted', 'method']


@admin.register(HealthEvent)
class HealthEventAdmin(StockRecordAdmin):
    list_display = ['__str__', 'site', 'kind', 'created_by', 'is_deleted', 'void_reason']
    list_filter = ['is_deleted', 'kind']


@admin.register(LiceCount)
class LiceCountAdmin(StockRecordAdmin):
    list_display = ['__str__', 'fish_counted', 'adult_females', 'created_by', 'is_deleted', 'void_reason']
    list_filter = ['is_deleted']

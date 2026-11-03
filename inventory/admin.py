from django.contrib import admin

from core.admin import register_audited
from farm.admin import StockRecordAdmin

from .models import InventoryLot, InventoryOperation

register_audited('inventory')

admin.site.unregister([InventoryLot, InventoryOperation])


@admin.register(InventoryOperation)
class InventoryOperationAdmin(StockRecordAdmin):
    """The store's operations, voided ones too, to look at. A voided operation is entered again on the
    Storage page, where the checks run: a restore would skip them."""

    list_display = ['kind', 'date', 'supplier', 'created_by', 'is_deleted', 'void_reason']
    list_filter = ['is_deleted', 'kind']


@admin.register(InventoryLot)
class InventoryLotAdmin(StockRecordAdmin):
    """Lots, the ones voided with their last delivery too; a lot comes back by entering its delivery again."""

    list_display = ['number', 'item', 'expiry_date', 'is_deleted']
    search_fields = ['number']

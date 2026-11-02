from django.contrib import admin

from core.admin import ReadOnlyAdmin, register_audited

from .models import EquipmentType

register_audited('farm')


@admin.register(EquipmentType)
class EquipmentTypeAdmin(ReadOnlyAdmin):
    """The equipment type catalogue, to look at: migrations write it (farm/equipment_types.py)."""

    list_display = ['name', 'code', 'category', 'is_active']
    list_filter = ['category', 'is_active']
    search_fields = ['name', 'code']

from django.db.models import Count, Q
from django.utils.translation import gettext, gettext_lazy as _, ngettext_lazy

from core import audit
from core.crud import NONE, Resource, RowList, filter_by
from core.models import in_tree_order

from ..forms import EquipmentForm, FeederCalibrationFormSet
from ..models import Equipment, EquipmentType, ProductionDepartment, Site, System

# What the activity log compares for a piece of equipment, besides its type, systems and specifications.
LOGGED_FIELDS = [
    'status', 'production_department', 'parent', 'manufacturer', 'model', 'serial_number', 'purchase_date',
    'warranty_end_date', 'installation_date', 'description', 'notes',
]


class FeederCalibrations(RowList):
    """A feeder's feed calibrations, saved as a whole list on its Feed calibration tab (as the source does)."""

    key, tab, label = 'calibrations', 'calibration', _('Feed calibrations')
    formset = FeederCalibrationFormSet
    saved = ngettext_lazy('%(count)d calibration saved.', '%(count)d calibrations saved.', 'count')

    @classmethod
    def applies_to(cls, equipment):
        return equipment.equipment_type.takes_calibrations

    @classmethod
    def describe(cls, row):
        """e.g. "3.00 mm Starter: 25.00 g per shot, silo 250.00 kg (top up daily)", in English."""
        size = f'{row.feed_size_mm} mm {row.label}'.strip()
        text = gettext('%(size)s: %(grams)s g per shot, silo %(silo)s kg') % {
            'size': size, 'grams': row.grams_per_dispensing, 'silo': row.silo_capacity_kg}
        return f'{text} ({row.notes})' if row.notes else text


class EquipmentResource(Resource):
    model = Equipment
    form_class = EquipmentForm
    name, plural = _('equipment'), _('equipment')
    url_prefix = 'equipment'
    search_fields = ['name', 'code', 'serial_number']
    list_template = 'farm/equipment_list.html'
    form_template = 'farm/equipment_form.html'
    icon = 'wrench'
    row_lists = (FeederCalibrations,)

    @classmethod
    def queryset(cls):
        return super().queryset().select_related('production_department__site', 'equipment_type', 'parent')

    @classmethod
    def snapshot(cls, equipment):
        """The fields, the type (a catalogue name, shown translated), the systems as one line, and each
        specification of the type under its own label."""
        values = audit.snapshot(equipment, ['name', 'code'])
        values[str(_('Type'))] = audit.message(equipment.equipment_type.name)
        values.update(audit.snapshot(equipment, LOGGED_FIELDS))
        values[str(_('Systems'))] = '; '.join(cls._describe_link(link) for link in equipment.system_links.all()) or None
        values.update(equipment.equipment_type.schema.logged(equipment.specifications))
        return values

    @staticmethod
    def _describe_link(link):
        """e.g. "Smolt RAS 1 (R1): primary, main pump, criticality 4"; a deleted system says so."""
        details = [gettext('primary')] if link.is_primary else []
        details += [link.role] if link.role else []
        details.append(gettext('criticality %(level)d') % {'level': link.criticality})
        if link.system.is_deleted:
            details.append(gettext('deleted'))
        return f'{link.system}: {", ".join(details)}'

    @classmethod
    def filter_list(cls, request, objects):
        sites = Site.objects.all()
        departments = ProductionDepartment.objects.select_related('site').order_by('site__name', 'name')
        systems = System.objects.select_related('site').order_by('site__name', 'name')
        types = EquipmentType.objects.filter(Q(is_active=True) | Q(equipment__isnull=False)).distinct()
        unlinked = Equipment.objects.exclude(system_links__system__is_deleted=False)
        objects, chosen_site = filter_by(request, objects, 'site', sites, 'production_department__site_id')
        objects, chosen_department = filter_by(
            request, objects, 'production_department', departments, 'production_department_id')
        if request.GET.get('system') == NONE:
            objects, chosen_system = objects.filter(pk__in=unlinked), NONE
        else:
            objects, chosen_system = filter_by(request, objects, 'system', systems, 'system_links__system')
        objects, chosen_category = filter_by(
            request, objects, 'category', EquipmentType.Category.choices, 'equipment_type__category')
        objects, chosen_type = filter_by(request, objects, 'type', types, 'equipment_type_id')
        objects, chosen_status = filter_by(request, objects, 'status', Equipment.Status.choices, 'status')
        records = (Equipment.objects
                   .select_related('production_department__site', 'equipment_type', 'parent')
                   .prefetch_related('system_links__system')
                   .annotate(parts=Count('children', filter=Q(children__is_deleted=False)))
                   .order_by('production_department__site__name', 'name'))
        used = set(types.values_list('category', flat=True))
        return in_tree_order(records, objects), {
            'sites': sites, 'chosen_site': chosen_site,
            'departments': departments, 'chosen_department': chosen_department,
            'systems': systems, 'chosen_system': chosen_system, 'none_value': NONE,
            'categories': [(value, label) for value, label in EquipmentType.Category.choices if value in used],
            'chosen_category': chosen_category,
            'types': types, 'chosen_type': chosen_type,
            'statuses': Equipment.Status.choices, 'chosen_status': chosen_status,
            'unlinked': unlinked.count(),
        }

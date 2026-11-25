from django.db.models import Count, Q
from django.utils.translation import gettext, gettext_lazy as _, ngettext, ngettext_lazy

from core import audit, formpanels, listprops as L
from core.crud import NONE, Resource, RowList, filter_by
from core.models import in_tree_order

from ..forms import EquipmentForm, FeederCalibrationFormSet
from ..models import Equipment, EquipmentType, ProductionDepartment, Site, System

# What the activity log compares for a piece of equipment, besides its type, systems and specifications.
LOGGED_FIELDS = [
    'status', 'production_department', 'parent', 'manufacturer', 'model', 'serial_number', 'supplier',
    'purchase_date', 'warranty_end_date', 'installation_date', 'description', 'notes',
]


class FeederCalibrations(RowList):
    """A feeder's feed calibrations, saved as a whole list on its Feed calibration tab (as the source does)."""

    key, tab, label = 'calibrations', 'calibration', _('Feed calibrations')
    formset = FeederCalibrationFormSet
    # Its panel's words (farm/equipment_form.html).
    title = _('Feed calibration')
    help_text = _('For each feed size, how much feed one shot dispenses and how much the silo holds; at most 50 rows. They '
                  'are saved separately from the equipment details.')
    empty_text = _('No calibrations yet. Use “Add calibration” to add a row.')
    add_label, save_label = _('Add calibration'), _('Save calibrations')

    @classmethod
    def words(cls, equipment):
        """Before the list applies: a new piece of equipment, or one whose saved type takes no calibrations yet."""
        return {**super().words(equipment), 'pending': _(
            'Save the equipment with this feeder type first; then its calibrations can be added here.') if equipment
            else _('Calibrations can be added once the equipment is created.')}
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
    def next_panels(cls, view, form, obj, extra):
        """farm/equipment_form.html in the new look: the calibrations' tab when the chosen type takes them, or the piece
        has them."""
        chosen = getattr(form, 'chosen_type', None)
        if chosen is not None and chosen.takes_calibrations or extra.get(FeederCalibrations.key):
            return formpanels.row_list_panels(cls, view, obj, extra)
        return []

    @classmethod
    def queryset(cls):
        return super().queryset().select_related('production_department__site', 'equipment_type', 'parent',
                                                 'supplier')

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
                   .select_related('production_department__site', 'equipment_type', 'parent', 'supplier')
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

    # The list in the new look (core/listprops.py), in the classic list's words (farm/equipment_list.html).
    search_placeholder = _('Search by name, code or serial number')
    empty_text = _('Pumps, filters, feeders, sensors and generators of a production department, linked to the systems they '
                   'serve.')

    @classmethod
    def list_filters(cls, view, context):
        department = lambda each: f'{each.site.name} · {each.name}' if each.site else each.name   # noqa: E731
        return [
            L.choice('site', _('Site'), context['chosen_site'],
                     [('', _('All sites')), *((site.pk, site.name) for site in context['sites'])]),
            L.choice('production_department', _('Production department'), context['chosen_department'],
                     [('', _('All production departments')), *((each.pk, department(each)) for each in context['departments'])]),
            L.choice('system', _('System'), context['chosen_system'],
                     [('', _('All systems')), (context['none_value'], _('Not linked to any system')),
                      *((system.pk, f'{system.site.name} · {system.name}') for system in context['systems'])]),
            L.choice('category', _('Category'), context['chosen_category'], [('', _('All categories')), *context['categories']]),
            L.choice('type', _('Type'), context['chosen_type'],
                     [('', _('All types')), *((kind.pk, str(kind)) for kind in context['types'])]),
            L.choice('status', _('Status'), context['chosen_status'], [('', _('All statuses')), *context['statuses']]),
        ]

    @classmethod
    def list_rows(cls, view, objects, context):
        from django.urls import reverse
        from django.utils.http import urlencode

        from .system import _nested
        user = view.request.user

        def systems(equipment):
            links = equipment.live_links()
            if not links:
                return L.cell(chip=L.chip('warning', _('No system')))
            primary = [link.system.name for link in links if link.is_primary]
            return L.cell(', '.join(link.system.name for link in links),
                          sub=[f"{_('Primary system')}: {name}" for name in primary])

        def actions(equipment):
            done = []
            if user.has_perm('farm.view_samplingpoint'):
                done.append(L.link(f"{reverse('farm:samplingpoint_list')}?{urlencode({'equipment': equipment.pk})}",
                                   _('Sampling points of %(name)s') % {'name': equipment.name}, 'droplet'))
            return done + L.edit_delete(view, context, equipment, equipment.name)

        def department(equipment):
            place = equipment.production_department
            return L.cell(place.name, sub=[place.site.name]) if place.site else \
                L.cell(place.name, chips=[L.chip('warning', _('No site'))])

        notices = []
        if context['unlinked']:
            count = context['unlinked']
            notices.append(L.notice('unlinked', 'warning', ngettext(
                '%(count)s piece of equipment is not linked to any system.',
                '%(count)s pieces of equipment are not linked to any system.', count) % {'count': count},
                link=(f"?{urlencode({'system': context['none_value']})}", _('Show them'))))
        return {
            'columns': [L.column('equipment', _('Equipment')), L.column('type', _('Type')),
                        L.column('department', _('Production department')), L.column('systems', _('Systems')),
                        L.column('parts', _('Parts')), L.column('status', _('Status')),
                        L.column('make', _('Make and model')), L.column('supplier', _('Supplier'))],
            'notices': notices,
            'rows': [L.row(equipment.pk, {
                'equipment': L.title(view, context, equipment, _nested(equipment), sub=[' · '.join(
                    [equipment.code, *([_('part of %(code)s') % {'code': equipment.parent.code}] if equipment.parent
                                       else [])])]),
                'type': L.cell(str(equipment.equipment_type), sub=[equipment.equipment_type.get_category_display()]),
                'department': department(equipment),
                'systems': systems(equipment),
                'parts': L.cell(ngettext('%(count)s part', '%(count)s parts', equipment.parts) % {'count': equipment.parts}
                                if equipment.parts else '–'),
                'status': L.badge(equipment.status, equipment.get_status_display()),
                'make': L.cell(' · '.join(part for part in (equipment.manufacturer, equipment.model) if part) or '–'),
                'supplier': L.cell(equipment.supplier.name if equipment.supplier else '–'),
            }, actions(equipment)) for equipment in objects],
        }

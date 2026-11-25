from django.utils.translation import gettext_lazy as _

from core import audit, listprops as L
from core.crud import NONE, Resource, filter_by

from ..forms import TankForm
from ..models import ProductionDepartment, Site, System, Tank
from ..models.tank import KIND_FIELDS
from ..water import points
from .withdrawal_input import WithdrawalInput

# What the activity log compares for a unit: every field it is described by, the calculated volumes
# and max biomass (which a change of a measure or of the density moves), and the status with its reason.
LOGGED_FIELDS = [
    'name', 'code', 'kind', 'status', 'status_reason', 'water_type', 'regulatory_unit_id', 'production_department',
    'system', *(name for name in KIND_FIELDS if name != 'stated_volume_m3'), 'depth', 'max_density_kg_m3',
    'volume_m3', 'water_volume_m3', 'max_biomass_kg', 'installation_date', 'description', 'notes',
]


class TankResource(WithdrawalInput, Resource):
    model = Tank
    form_class = TankForm
    name, plural = _('unit'), _('units')
    url_prefix = 'tanks'
    search_fields = ['name', 'code', 'regulatory_unit_id']
    list_template = 'farm/tank_list.html'
    icon = 'cylinder'

    @classmethod
    def reached(cls, request, unit):
        """A unit's loop gives the water of a unit without a sample of its own (farm/water/read.py), so moving it into or
        out of a loop moves the degree-days of the withdrawals of every fish it ever held."""
        return {unit.pk}, None

    @classmethod
    def queryset(cls):
        return super().queryset().select_related('production_department__site', 'system')

    @classmethod
    def after_save(cls, request, unit, created):
        """A new unit starts with its sampling points (farm/water/points.py), logged with it."""
        if created:
            points.create_defaults(request.user, unit)

    @classmethod
    def snapshot(cls, unit):
        """The fields under their model labels. A shape of its own has its volume entered: the volume
        line shows it, so the entered one is not logged a second time."""
        return audit.snapshot(unit, LOGGED_FIELDS)

    @classmethod
    def filter_list(cls, request, objects):
        sites = Site.objects.all()
        departments = ProductionDepartment.objects.select_related('site').order_by('site__name', 'name')
        systems = System.objects.select_related('site').order_by('site__name', 'name')
        objects, chosen_site = filter_by(request, objects, 'site', sites, 'production_department__site_id')
        objects, chosen_department = filter_by(
            request, objects, 'production_department', departments, 'production_department_id')
        objects, chosen_system = filter_by(request, objects, 'system', systems, 'system_id', allow_none=True)
        objects, chosen_kind = filter_by(request, objects, 'kind', Tank.Kind.choices, 'kind')
        objects, chosen_status = filter_by(request, objects, 'status', Tank.Status.choices, 'status')
        objects, chosen_water = filter_by(request, objects, 'water_type', Tank.WaterType.choices, 'water_type')
        return objects.order_by('production_department__site__name', 'production_department__name', 'name'), {
            'sites': sites, 'chosen_site': chosen_site,
            'departments': departments, 'chosen_department': chosen_department,
            'systems': systems, 'chosen_system': chosen_system, 'none_value': NONE,
            'kinds': Tank.Kind.choices, 'chosen_kind': chosen_kind,
            'statuses': Tank.Status.choices, 'chosen_status': chosen_status,
            'water_types': Tank.WaterType.choices, 'chosen_water_type': chosen_water,
        }

    # The list in the new look (core/listprops.py), in the classic list's words (farm/tank_list.html).
    search_placeholder = _('Search by name, code or regulatory unit ID')
    empty_text = _('The tanks, ponds and cages fish are held in, each in a production department and, when it has one, a '
                   'system.')

    @classmethod
    def list_filters(cls, view, context):
        department = lambda each: f'{each.site.name} · {each.name}' if each.site else each.name   # noqa: E731
        return [
            L.choice('site', _('Site'), context['chosen_site'],
                     [('', _('All sites')), *((site.pk, site.name) for site in context['sites'])]),
            L.choice('production_department', _('Production department'), context['chosen_department'],
                     [('', _('All production departments')), *((each.pk, department(each)) for each in context['departments'])]),
            L.choice('system', _('System'), context['chosen_system'],
                     [('', _('All systems')), (context['none_value'], _('Not in a system')),
                      *((system.pk, f'{system.site.name} · {system.name}') for system in context['systems'])]),
            L.choice('kind', _('Kind'), context['chosen_kind'], [('', _('All kinds')), *context['kinds']]),
            L.choice('status', _('Status'), context['chosen_status'], [('', _('All statuses')), *context['statuses']]),
            L.choice('water_type', _('Water type'), context['chosen_water_type'],
                     [('', _('All water types')), *context['water_types']]),
        ]

    @classmethod
    def list_rows(cls, view, objects, context):
        from django.template.defaultfilters import floatformat
        from django.urls import reverse
        from django.utils.http import urlencode
        user = view.request.user

        def figure(value):
            return L.cell('–' if value is None else floatformat(value, '-2g'))

        def department(unit):
            place = unit.production_department
            return L.cell(place.name, sub=[place.site.name]) if place.site else \
                L.cell(place.name, chips=[L.chip('warning', _('No site'))])

        def actions(unit):
            done = []
            if user.has_perm('farm.view_samplingpoint'):
                done.append(L.link(f"{reverse('farm:samplingpoint_list')}?{urlencode({'unit': unit.pk})}",
                                   _('Sampling points of %(name)s') % {'name': unit.name}, 'droplet'))
            return done + L.edit_delete(view, context, unit, unit.name)

        return {
            'columns': [L.column('unit', _('Unit')), L.column('kind', _('Kind')),
                        L.column('department', _('Production department')), L.column('system', _('System')),
                        L.column('volume', _('Volume (m³)'), numeric=True),
                        L.column('water_volume', _('Water volume (m³)'), numeric=True),
                        L.column('density', _('Max density (kg/m³)'), numeric=True),
                        L.column('biomass', _('Max biomass (kg)'), numeric=True),
                        L.column('water_type', _('Water type')), L.column('status', _('Status'))],
            'rows': [L.row(unit.pk, {
                'unit': L.title(view, context, unit, unit.name, sub=[' · '.join(
                    part for part in (unit.code, unit.regulatory_unit_id) if part)]),
                'kind': L.cell(unit.get_kind_display(), sub=[unit.subtype()]),
                'department': department(unit),
                'system': L.cell(unit.system.name if unit.system else '–'),
                'volume': figure(unit.volume_m3),
                'water_volume': figure(unit.water_volume_m3),
                'density': figure(unit.max_density_kg_m3),
                'biomass': figure(unit.max_biomass_kg),
                'water_type': L.cell(unit.get_water_type_display()),
                'status': L.badge(unit.status, unit.get_status_display()),
            }, actions(unit)) for unit in objects],
        }

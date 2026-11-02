from django.utils.translation import gettext_lazy as _

from core import audit
from core.crud import NONE, Resource, filter_by

from ..forms import TankForm
from ..models import ProductionDepartment, Site, System, Tank
from ..models.tank import KIND_FIELDS

# What the activity log compares for a unit: every field it is described by, the calculated volumes
# and max biomass (which a change of a measure or of the density moves), and the status with its reason.
LOGGED_FIELDS = [
    'name', 'code', 'kind', 'status', 'status_reason', 'water_type', 'regulatory_unit_id', 'production_department',
    'system', *(name for name in KIND_FIELDS if name != 'stated_volume_m3'), 'depth', 'max_density_kg_m3',
    'volume_m3', 'water_volume_m3', 'max_biomass_kg', 'installation_date', 'description', 'notes',
]


class TankResource(Resource):
    model = Tank
    form_class = TankForm
    name, plural = _('unit'), _('units')
    url_prefix = 'tanks'
    search_fields = ['name', 'code', 'regulatory_unit_id']
    list_template = 'farm/tank_list.html'
    icon = 'cylinder'

    @classmethod
    def queryset(cls):
        return super().queryset().select_related('production_department__site', 'system')

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

from core.crud import NONE, Resource, filter_by

from ..forms import SystemForm
from ..models import ProductionDepartment, Site, System


class SystemResource(Resource):
    model = System
    form_class = SystemForm
    name, plural, group = 'system', 'systems', 'Facility'
    url_prefix = 'systems'
    search_fields = ['name', 'code']
    list_template = 'farm/system_list.html'
    icon = 'waves'

    @classmethod
    def queryset(cls):
        return super().queryset().select_related('site', 'production_department', 'parent')

    @classmethod
    def filter_list(cls, request, objects):
        sites, departments = Site.objects.all(), ProductionDepartment.objects.all()
        objects, chosen_site = filter_by(request, objects, 'site', sites, 'site_id')
        objects, chosen_department = filter_by(
            request, objects, 'production_department', departments, 'production_department_id', allow_none=True)
        return System.in_tree_order(objects), {
            'sites': sites, 'chosen_site': chosen_site,
            'departments': departments, 'chosen_department': chosen_department, 'none_value': NONE,
            'without_department': System.objects.filter(production_department__isnull=True).count(),
        }

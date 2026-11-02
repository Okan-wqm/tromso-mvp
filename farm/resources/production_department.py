from core.crud import NONE, Resource, filter_by

from ..forms import ProductionDepartmentForm
from ..models import ProductionDepartment, Site


class ProductionDepartmentResource(Resource):
    model = ProductionDepartment
    form_class = ProductionDepartmentForm
    name, plural, group = 'production department', 'production departments', 'Facility'
    url_prefix = 'production-departments'
    search_fields = ['name', 'code']
    list_template = 'farm/production_department_list.html'
    icon = 'layout-grid'

    @classmethod
    def queryset(cls):
        return super().queryset().select_related('site')

    @classmethod
    def filter_list(cls, request, objects):
        sites = Site.objects.all()
        objects, chosen = filter_by(request, objects, 'site', sites, 'site_id', allow_none=True)
        return objects, {
            'sites': sites, 'chosen_site': chosen, 'none_value': NONE,
            'without_site': ProductionDepartment.objects.filter(site__isnull=True).count(),
        }

from core.crud import NONE, Resource, filter_by

from ..forms import DepartmentForm
from ..models import Department, Site


class DepartmentResource(Resource):
    model = Department
    form_class = DepartmentForm
    name, plural, group = 'department', 'departments', 'Facility'
    url_prefix = 'departments'
    search_fields = ['name', 'code']
    list_template = 'farm/department_list.html'
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
            'without_site': Department.objects.filter(site__isnull=True).count(),
        }

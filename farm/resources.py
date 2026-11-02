"""The farm tabs, each declared once on top of core.crud."""
from core.crud import Resource

from .forms import DepartmentForm, SiteContactFormSet, SiteForm, SystemForm
from .models import Department, Site, System

NONE = 'none'   # a list filter's value for "records without one" (departments without a site)


def filter_by(request, objects, param, choices, lookup, allow_none=False):
    """Narrows `objects` to the record chosen in the `param` query parameter, or (`allow_none`) to
    those without one. Anything else, a stale or malformed value, shows everything.
    Returns the objects and the value the filter shows as chosen."""
    chosen = request.GET.get(param, '')
    if allow_none and chosen == NONE:
        return objects.filter(**{f'{lookup}__isnull': True}), chosen
    if chosen in {str(pk) for pk in choices.values_list('pk', flat=True)}:
        return objects.filter(**{lookup: chosen}), chosen
    return objects, ''


class SiteResource(Resource):
    model = Site
    form_class = SiteForm
    name, plural, group = 'site', 'sites', 'Facility'
    url_prefix = 'sites'
    search_fields = ['name', 'code', 'region']
    list_template = 'farm/site_list.html'
    form_template = 'farm/site_form.html'
    icon = 'building'

    @classmethod
    def edit_extras(cls, request, obj):
        return {'contacts': SiteContactFormSet(instance=obj, prefix='contacts')}


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
        return super().queryset().select_related('site', 'department', 'parent')

    @classmethod
    def filter_list(cls, request, objects):
        sites, departments = Site.objects.all(), Department.objects.all()
        objects, chosen_site = filter_by(request, objects, 'site', sites, 'site_id')
        objects, chosen_department = filter_by(
            request, objects, 'department', departments, 'department_id', allow_none=True)
        return System.in_tree_order(objects), {
            'sites': sites, 'chosen_site': chosen_site,
            'departments': departments, 'chosen_department': chosen_department, 'none_value': NONE,
            'without_department': System.objects.filter(department__isnull=True).count(),
        }

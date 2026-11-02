"""The farm tabs, each declared once on top of core.crud."""
from core.crud import Resource

from .forms import DepartmentForm, SiteContactFormSet, SiteForm
from .models import Department, Site

NO_SITE = 'none'   # the site filter value for departments without a site


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
        chosen = request.GET.get('site', '')
        sites = Site.objects.all()
        if chosen == NO_SITE:
            objects = objects.filter(site__isnull=True)
        elif chosen in {str(pk) for pk in sites.values_list('pk', flat=True)}:
            objects = objects.filter(site_id=chosen)
        else:
            chosen = ''   # unknown or malformed: show all
        return objects, {
            'sites': sites, 'chosen_site': chosen, 'no_site': NO_SITE,
            'without_site': Department.objects.filter(site__isnull=True).count(),
        }

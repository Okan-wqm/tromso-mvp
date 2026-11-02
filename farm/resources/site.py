from core.crud import Resource

from ..forms import SiteContactFormSet, SiteForm
from ..models import Site


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

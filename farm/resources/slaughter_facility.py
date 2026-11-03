from django.utils.translation import gettext_lazy as _

from core.crud import Resource, filter_by

from ..forms.harvest import SlaughterFacilityForm
from ..models import SlaughterFacility, Species


class SlaughterFacilityResource(Resource):
    """Setup › Harvest and logistics › Slaughter facilities: where harvested fish go."""

    model = SlaughterFacility
    form_class = SlaughterFacilityForm
    name, plural = _('slaughter facility'), _('slaughter facilities')
    url_prefix = 'slaughter-facilities'
    search_fields = ['name', 'approval_number', 'address', 'municipality', 'operator__name']
    list_template = 'farm/slaughter_facility_list.html'
    icon = 'factory'
    page_size = 50

    @classmethod
    def queryset(cls):
        return super().queryset().select_related('operator').prefetch_related('species')

    @classmethod
    def filter_list(cls, request, objects):
        objects, chosen_status = filter_by(request, objects, 'status', SlaughterFacility.Status.choices, 'status')
        species = Species.objects.filter(slaughter_facilities__is_deleted=False).distinct().order_by('common_name')
        objects, chosen_species = filter_by(request, objects, 'species', species, 'species')
        return objects.distinct(), {
            'statuses': SlaughterFacility.Status.choices, 'chosen_status': chosen_status,
            'species_list': species, 'chosen_species': chosen_species,
        }

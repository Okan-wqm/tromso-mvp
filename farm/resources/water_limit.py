from django.utils.translation import gettext_lazy as _

from core.crud import Resource, filter_by

from ..forms.water import WaterLimitForm
from ..models import Species, WaterLimit
from ..water import read as water_read
from ..water.parameters import LIMIT_CHOICES


class WaterLimitResource(Resource):
    """Setup › Reference data › Water limits: per species and parameter, the bounds a value is judged by; above them,
    what the fish kept today have no limit for (water.read.missing_limits), which their cards say as "No limit"."""

    model = WaterLimit
    form_class = WaterLimitForm
    name, plural = _('water limit'), _('water limits')
    url_prefix = 'water-limits'
    search_fields = ['species__common_name', 'species__local_name', 'species__code', 'reference']
    list_template = 'farm/water_limit_list.html'
    icon = 'gauge'
    page_size = 50

    @classmethod
    def queryset(cls):
        return super().queryset().select_related('species')

    @classmethod
    def filter_list(cls, request, objects):
        species = Species.objects.filter(water_limits__is_deleted=False).distinct().order_by('common_name')
        objects, chosen_species = filter_by(request, objects, 'species', species, 'species_id')
        objects, chosen_parameter = filter_by(request, objects, 'parameter', LIMIT_CHOICES, 'parameter')
        return objects, {
            'species_list': species, 'chosen_species': chosen_species,
            'parameters': LIMIT_CHOICES, 'chosen_parameter': chosen_parameter,
            'missing': water_read.missing_limits(),
        }

from django.utils.translation import gettext_lazy as _

from core.crud import NONE, Resource, filter_by

from ..forms.handling import HandlingRuleForm
from ..models import HandlingRule, Species


class HandlingRuleResource(Resource):
    """Setup › Harvest and logistics › Handling rules: the fast before each kind of handling, per species or for all."""

    model = HandlingRule
    form_class = HandlingRuleForm
    name, plural = _('handling rule'), _('handling rules')
    url_prefix = 'handling-rules'
    search_fields = ['species__common_name', 'species__local_name', 'species__code', 'note']
    list_template = 'farm/handling_rule_list.html'
    icon = 'timer'

    @classmethod
    def queryset(cls):
        return super().queryset().select_related('species')

    @classmethod
    def filter_list(cls, request, objects):
        objects, chosen_kind = filter_by(request, objects, 'kind', HandlingRule.Kind.choices, 'kind')
        species = Species.objects.filter(handling_rules__is_deleted=False).distinct().order_by('common_name')
        objects, chosen_species = filter_by(request, objects, 'species', species, 'species', allow_none=True)
        return objects, {
            'kinds': HandlingRule.Kind.choices, 'chosen_kind': chosen_kind,
            'species_list': species, 'chosen_species': chosen_species, 'none_value': NONE,
        }

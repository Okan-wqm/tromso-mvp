from django.utils.translation import gettext_lazy as _

from core import audit
from core.crud import NONE, Resource, filter_by

from ..forms.handling import HandlingRuleForm
from ..models import HandlingRule, Species


class HandlingRuleResource(Resource):
    """Setup › Reference data › Handling rules: the fast before each kind of handling, per species or for all."""

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
    def snapshot(cls, obj):
        """What the log compares: the model's columns. The form types the fast as an amount and a unit; what is stored,
        and logged, is the hours (and a harvest's degree-days)."""
        return audit.snapshot(obj, ['kind', 'species', 'min_fasting_hours', 'min_fasting_degree_days', 'note'], {})

    @classmethod
    def filter_list(cls, request, objects):
        objects, chosen_kind = filter_by(request, objects, 'kind', HandlingRule.Kind.choices, 'kind')
        species = Species.objects.filter(handling_rules__is_deleted=False).distinct().order_by('common_name')
        objects, chosen_species = filter_by(request, objects, 'species', species, 'species', allow_none=True)
        return objects, {
            'kinds': HandlingRule.Kind.choices, 'chosen_kind': chosen_kind,
            'species_list': species, 'chosen_species': chosen_species, 'none_value': NONE,
        }

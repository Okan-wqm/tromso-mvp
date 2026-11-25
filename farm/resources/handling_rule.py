from django.utils.translation import gettext_lazy as _, pgettext

from core import audit, listprops as L
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

    # The list in the new look (core/listprops.py), in the classic list's words (farm/handling_rule_list.html).
    search_placeholder = _('Search by species or source')
    empty_text = _('The fast before each kind of handling, per species or for every species. Without a rule the fast is not '
                   'checked.')

    @classmethod
    def list_filters(cls, view, context):
        return [
            L.choice('kind', _('Handling'), context['chosen_kind'], [('', _('Every handling')), *context['kinds']]),
            L.choice('species', pgettext('singular', 'Species'), context['chosen_species'],
                     [('', _('All rules')), (context['none_value'], _('Every species')),
                      *((each.pk, each.common_name) for each in context['species_list'])]),
        ]

    @classmethod
    def list_rows(cls, view, objects, context):
        from ..templatetags.harvest import rule_asks
        notices = [L.notice('fasting', 'info', _(
            'How long fish must have been without feed before they are harvested, transported, graded or treated, counted '
            'from their last feeding to the start of that day, in hours or days. A harvest can also ask for purging in '
            'degree-days: the fish are held without feed, in clean water, so that any off-flavour clears; both must be '
            'reached when both are given. A species’ own rule wins over the rule for every species; a grading takes the '
            'longer of its rule and the transport rule. Too short a fast is a warning, never a block: going on is recorded '
            'and logged as critical. These are the farm’s own rules: the starting values are to be checked with your '
            'veterinarian.'))]
        return {
            'columns': [L.column('kind', _('Handling')), L.column('species', pgettext('singular', 'Species')),
                        L.column('asks', _('Fasting before it')), L.column('note', _('Source of the value'))],
            'notices': notices,
            'rows': [L.row(rule.pk, {
                'kind': L.title(view, context, rule, rule.get_kind_display()),
                'species': L.cell(rule.species.common_name if rule.species else _('Every species')),
                'asks': L.cell(str(rule_asks(rule))),
                'note': L.cell(rule.note or '—'),
            }, L.edit_delete(view, context, rule, str(rule))) for rule in objects],
        }

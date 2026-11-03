"""Setup › Harvest and logistics › Handling rules: how long fish fast before a kind of handling, for a species or for
every species."""
from django import forms
from django.utils.translation import gettext_lazy as _

from core.crud import TabbedForm, tab_fields

from ..models import HandlingRule, Species
from ..models.handling import MAX_FASTING_HOURS

HANDLING_RULE_TABS = [('rule', _('Rule'), ['kind', 'species', 'min_fasting_hours', 'note'])]


class HandlingRuleForm(TabbedForm):
    tabs = HANDLING_RULE_TABS

    class Meta:
        model = HandlingRule
        fields = tab_fields(HANDLING_RULE_TABS)
        help_texts = {
            'kind': _('A transfer is a transport. A grading is checked against its own rule and the transport rule; '
                      'the longer applies.'),
            'species': _('Empty: the rule for every species. A species’ own rule wins over it.'),
            'min_fasting_hours': _('The fish must have had no feed for at least this long before the handling, '
                                   'counted to the start of its day. 0 to 720.'),
            'note': _('Where the value comes from, e.g. “the vet, November 2026”.'),
        }
        widgets = {'min_fasting_hours': forms.NumberInput(attrs={'min': 0, 'max': MAX_FASTING_HOURS}),
                   'note': forms.Textarea(attrs={'rows': 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['kind'].choices = [('', _('Select a handling'))] + list(HandlingRule.Kind.choices)
        self.fields['species'].queryset = Species.objects.order_by('common_name')
        self.fields['species'].empty_label = _('Every species')

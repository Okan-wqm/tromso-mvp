"""Setup › Reference data › Handling rules: how long fish fast before a kind of handling, for a species or for
every species."""
from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from core.crud import TabbedForm

from ..models import HandlingRule, Species

HOURS, DAYS = 'hours', 'days'
HANDLING_RULE_TABS = [('rule', _('Rule'), ['kind', 'species', 'fasting_amount', 'fasting_unit',
                                           'min_fasting_degree_days', 'note'])]


def amount_and_unit(hours):
    """A rule's hours as the form shows them: whole days when they divide by 24 ("5 days" for 120 h), else hours; a
    rule of 0 h is hours."""
    if hours and hours % 24 == 0:
        return hours // 24, DAYS
    return hours, HOURS


class HandlingRuleForm(TabbedForm):
    """A handling rule. The fast is typed as a number and a unit, hours or days, and stored in the one hours column
    (5 days is 120 hours); an existing rule of whole days is shown back as days. Degree-days (purging) are the harvest's
    own."""

    tabs = HANDLING_RULE_TABS
    fasting_amount = forms.IntegerField(label=_('Fasting before it'), required=False, min_value=0)
    fasting_unit = forms.ChoiceField(label=_('Unit'), choices=[(HOURS, _('hours')), (DAYS, _('days'))],
                                     initial=HOURS)

    class Meta:
        model = HandlingRule
        # The hours are the model's column, worked out from the amount and the unit; they are not on a tab.
        fields = ['kind', 'species', 'min_fasting_hours', 'min_fasting_degree_days', 'note']
        localized_fields = ['min_fasting_degree_days']
        help_texts = {
            'kind': _('A transfer is a transport. A grading is checked against its own rule and the transport rule; '
                      'the longer applies.'),
            'species': _('Empty: the rule for every species. A species’ own rule wins over it.'),
            'min_fasting_degree_days': _('Purging: the fish are held without feed, in clean water, so that any '
                                         'off-flavour clears, for this many degree-days (the daily mean water '
                                         'temperatures added up over the full days since the last feeding). Only for '
                                         'fish that are harvested and sent to the factory. Given with hours or days, '
                                         'both must be reached.'),
            'note': _('Where the value comes from, e.g. “the vet, November 2026”.'),
        }
        widgets = {'min_fasting_degree_days': forms.TextInput(attrs={'inputmode': 'decimal',
                                                                      'placeholder': _('e.g. 60')}),
                   'note': forms.Textarea(attrs={'rows': 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['kind'].choices = [('', _('Select a handling'))] + list(HandlingRule.Kind.choices)
        self.fields['species'].queryset = Species.objects.order_by('common_name')
        self.fields['species'].empty_label = _('Every species')
        self.fields['min_fasting_hours'].required = False
        self.fields['fasting_amount'].help_text = _(
            'The fish must have had no feed for at least this long before the handling, counted to the start of '
            'its day: hours or days (5 days is stored as 120 hours). 0 to 720 hours (30 days). For a harvest it can '
            'be left empty when the purging is given in degree-days.')
        if not self.is_bound and not self.instance._state.adding:
            self.initial['fasting_amount'], self.initial['fasting_unit'] = amount_and_unit(
                self.instance.min_fasting_hours)

    def clean(self):
        cleaned = super().clean()
        amount = cleaned.get('fasting_amount')
        cleaned['min_fasting_hours'] = None if amount is None else amount * (24 if cleaned.get(
            'fasting_unit') == DAYS else 1)
        return cleaned

    def add_error(self, field, error):
        """An error of the hours column (the model's rules and checks speak of it) is the amount's on the page."""
        if field is None and hasattr(error, 'error_dict') and 'min_fasting_hours' in error.error_dict:
            errors = dict(error.error_dict)
            errors['fasting_amount'] = errors.pop('min_fasting_hours')
            error = ValidationError(errors)
        elif field == 'min_fasting_hours':
            field = 'fasting_amount'
        super().add_error(field, error)

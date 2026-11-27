"""The forms of Operations › Feeding › Temperature profiles and Profile assignments: a profile's general fields (a tab of
core.crud), its points (a row list, core.crud.RowList) and the assignment dialogs (farm/forms/assignment.py, the
protocols' own)."""
from django import forms
from django.utils.translation import gettext_lazy as _, ngettext_lazy

from core.crud import CodedFormMixin, RowFormSet, TabbedForm, tab_fields

from ..models import Species, TemperatureProfile, TemperatureProfileAssignment, TemperatureProfilePoint
from ..models.temperature_profile import MAX_POINTS, BetweenBands, ProtocolStatus
from .assignment import HELP, AssignmentBase, NewAssignmentBase, SubjectChoice, edit_tabs, new_tabs

DECIMAL = {'inputmode': 'decimal'}
PROFILE_TABS = [('general', _('General'), ['name', 'species', 'status', 'temperature_between', 'notes'])]


class TemperatureProfileForm(CodedFormMixin, TabbedForm):
    """A profile's general fields. Its points are a list of their own (TemperaturePointList). Once it is assigned its
    species and rule are fixed and it cannot go back to draft (farm.models.assignment.Assignable says why)."""

    tabs = PROFILE_TABS

    class Meta:
        model = TemperatureProfile
        fields = tab_fields(PROFILE_TABS)
        widgets = {'notes': forms.Textarea(attrs={'rows': 3}),
                   'name': forms.TextInput(attrs={'placeholder': _('e.g. Salmon smolt, RAS hall A')})}
        help_texts = {
            'species': _('The species the profile is for: it is assigned only to fish of this species.'),
            'status': _('Draft: being built. Active: can be assigned. Retired: kept for the days it was read for, '
                        'assigned no more.'),
            'temperature_between': _('For fish between two points. Smooth: read in between, with no jump. Step: the '
                                     'point’s temperature from its weight on. Before the first point its temperature, '
                                     'after the last point the last one’s.'),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['species'].queryset = Species.objects.order_by('common_name')
        self.fields['species'].empty_label = _('Select a species')
        self.fields['temperature_between'].choices = BetweenBands.choices
        if self.instance.is_assigned():
            for name in TemperatureProfile.FIXED:
                self.fields[name].disabled = True
                self.fields[name].help_text = _('Fixed: the profile is assigned. Duplicate it to change it.')
            self.fields['status'].choices = [choice for choice in ProtocolStatus.choices
                                             if choice[0] != ProtocolStatus.DRAFT]
        elif self.instance._state.adding:
            self.fields['status'].choices = [(ProtocolStatus.DRAFT, ProtocolStatus.DRAFT.label)]
            self.fields['status'].help_text = _('A new profile is a draft: give its points, then set it active.')


class TemperaturePointForm(forms.ModelForm):
    class Meta:
        model = TemperatureProfilePoint
        fields = ['weight_g', 'temperature_c']
        localized_fields = ['weight_g', 'temperature_c']
        widgets = {'weight_g': forms.TextInput(attrs={**DECIMAL, 'placeholder': _('e.g. 50')}),
                   'temperature_c': forms.TextInput(attrs={**DECIMAL, 'placeholder': _('e.g. 12')})}

    def validate_constraints(self, *args, **kwargs):
        # One point per weight spans the whole list, saved as a full replace: the formset checks it, the database's
        # constraint backs it up.
        pass


class BaseTemperaturePointFormSet(RowFormSet):
    default_error_messages = {
        'too_many_forms': ngettext_lazy('A profile has at most %(num)d point.', 'A profile has at most %(num)d points.',
                                        'num'),
    }

    def get_unique_error_message(self, unique_check):
        return str(_('Each weight is a point once.'))


TemperaturePointFormSet = forms.inlineformset_factory(
    TemperatureProfile, TemperatureProfilePoint, form=TemperaturePointForm, formset=BaseTemperaturePointFormSet,
    extra=0, can_delete=True, max_num=MAX_POINTS, validate_max=True,
)


class NewProfileAssignmentForm(NewAssignmentBase):
    """Assigns an active temperature profile (farm/forms/assignment.py: the protocols' dialog)."""

    tabs = new_tabs('profile')
    select_label = _('Select an active profile')
    units_help = _('Units only: the profile applies to whatever is in them. With a batch: that batch in these units '
                   'only.')

    class Meta(NewAssignmentBase.Meta):
        model = TemperatureProfileAssignment
        fields = ['profile', *NewAssignmentBase.Meta.fields]
        field_classes = {**NewAssignmentBase.Meta.field_classes, 'profile': SubjectChoice}
        help_texts = {**HELP, 'valid_from': _('The first day it applies to, on the farm’s clock.'),
                      'batch': _('A batch alone: the profile follows it into every unit it is moved to.')}


class ProfileAssignmentForm(AssignmentBase):
    """One profile assignment row (farm/forms/assignment.py)."""

    tabs = edit_tabs('profile')

    class Meta(AssignmentBase.Meta):
        model = TemperatureProfileAssignment
        fields = tab_fields(edit_tabs('profile'))
        field_classes = {**AssignmentBase.Meta.field_classes, 'profile': SubjectChoice}
        help_texts = {**HELP, 'valid_from': _('The first day it applies to, on the farm’s clock.')}

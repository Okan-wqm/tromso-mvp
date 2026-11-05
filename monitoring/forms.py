"""The monitoring forms: a card template and its rules (Reference data), and the board's form: its name, description,
default template, card width and how often its screens ask; and its Units list, one row per card (a unit and its own
template), saved as a whole list (monitoring/resources.py). The templates
offered are the live ones (Reference data › Card templates), a built-in by its name in the person's language."""
from django import forms
from django.urls import reverse
from django.utils.translation import gettext_lazy as _, ngettext_lazy

from core.crud import RowFormSet, TabbedForm, tab_fields
from farm.models import Species, System, Tank

from .cards import catalogue, validate
from .models import (REFRESH_MAX, REFRESH_MIN, SCOPES, CardTemplate, CardTemplateAssignment, MonitorBoard,
                     MonitorBoardUnit)

BOARD_TABS = [
    ('general', _('General'), ['name', 'description', 'default_template', 'card_width', 'refresh_seconds']),
]


def templates(field, empty):
    """A template choice: the live templates by their shown names; empty means the next rung decides."""
    field.queryset = CardTemplate.objects.order_by('-is_builtin', 'name')
    field.empty_label = empty
    field.required = False


class MonitorBoardForm(TabbedForm):
    """A shared wall board. Its units come on their own tab, once the board exists."""

    tabs = BOARD_TABS

    class Meta:
        model = MonitorBoard
        fields = tab_fields(BOARD_TABS)
        help_texts = {
            'name': _('Shown in the board picker of the Monitoring page. Anyone who may read Monitoring may choose a board: '
                      'a board is configuration, not a record.'),
            'default_template': _('The template of a card that neither its row nor a rule names (Reference data › Card '
                                  'template rules). Empty: the global rule decides.'),
            'card_width': _('How wide the cards are at the least: compact fits more on a wall, comfortable is easier to '
                            'read from a distance.'),
            'refresh_seconds': _('Between 10 and 600. Empty uses the system’s 15 seconds.'),
        }
        widgets = {'name': forms.TextInput(attrs={'placeholder': _('e.g. Hall A wall')})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['refresh_seconds'].widget.attrs.update({'min': REFRESH_MIN, 'max': REFRESH_MAX})
        templates(self.fields['default_template'], _('As the rules say'))


class BoardUnitForm(forms.ModelForm):
    """A row of a board's Units list: a unit and how its card is drawn. Only live units are offered."""

    class Meta:
        model = MonitorBoardUnit
        fields = ['unit', 'template']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        unit = self.fields['unit']
        unit.queryset = Tank.objects.select_related('production_department__site').order_by('code')
        unit.empty_label = _('Select a unit')
        unit.required = True
        templates(self.fields['template'], _('As the board'))

    def validate_constraints(self):
        # One card per unit spans the whole list, saved as a full replace: the formset checks it.
        pass


class BaseBoardUnitFormSet(RowFormSet):
    default_error_messages = {
        'too_many_forms': ngettext_lazy('A board has at most %(num)d card.', 'A board has at most %(num)d cards.', 'num'),
    }

    def get_queryset(self):
        """The rows whose unit is live: a unit that was deleted keeps its row (its card returns with the unit), out of
        sight here, and saving the list drops it."""
        return super().get_queryset().filter(unit__is_deleted=False)

    # The formset's own check of the unique (board, unit), said in the project's words.
    def get_unique_error_message(self, unique_check):
        return _('One card per unit.')

    def get_form_error(self):
        return _('One card per unit.')


BoardUnitFormSet = forms.inlineformset_factory(
    MonitorBoard, MonitorBoardUnit, form=BoardUnitForm, formset=BaseBoardUnitFormSet,
    extra=0, can_delete=True, max_num=200, validate_max=True,
)


# ---- card templates and their rules (Reference data) -------------------------------------------------------------
TEMPLATE_TABS = [
    ('general', _('General'), ['name', 'description', 'expanded']),
    ('design', _('Design'), ['layout']),
]


class CardDesignerWidget(forms.Textarea):
    """The layout's textarea inside the card designer (templates/monitoring/widgets/_designer.html, frontend/designer.ts):
    with it the widget catalogue and the live units to preview on, as json_script, in the person's language."""

    template_name = 'monitoring/widgets/_designer.html'

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context['widget'].update(
            catalogue=catalogue.as_data(), preview_url=reverse('monitoring:cardtemplate_preview'),
            units=[{'value': str(pk), 'label': code} for pk, code in Tank.objects.order_by('code').values_list('pk', 'code')])
        return context


class LayoutField(forms.JSONField):
    """A card template's layout: JSON, checked by THE validator (monitoring/cards/validate.py); each error names its
    widget. The designer (frontend/designer.ts) fills it; without script it is the JSON itself."""

    def validate(self, value):
        super().validate(value)
        validate.clean(value)


class CardTemplateForm(TabbedForm):
    """A card template: its name, a description, the template its flip link shows and its layout. A built-in is shown,
    never saved (a trigger refuses it too): copy it to make one's own."""

    tabs = TEMPLATE_TABS

    class Meta:
        model = CardTemplate
        fields = tab_fields(TEMPLATE_TABS)
        field_classes = {'layout': LayoutField}
        widgets = {'layout': CardDesignerWidget(attrs={'rows': 12, 'spellcheck': 'false', 'class': 'mono'})}
        help_texts = {
            'name': _('Shown in the template choices of boards and rules.'),
            'expanded': _('The template a card’s flip link shows (Simple flips to Detailed). Empty: no flip link.'),
            'layout': _('Where each widget sits on the card’s 12 columns. The frame of a card (the unit, its state and '
                        'why, the withdrawal) is always shown and is not part of the layout.'),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        expanded = self.fields['expanded']
        expanded.queryset = CardTemplate.objects.exclude(pk=self.instance.pk).order_by('-is_builtin', 'name')
        expanded.empty_label = _('No flip link')
        if self.instance._state.adding and not self.is_bound:
            self.initial.setdefault('layout', {'schema': catalogue.SCHEMA_VERSION, 'widgets': []})

    def _get_validation_exclusions(self):
        # The layout's own database rules (shape, count, size, version stamp) are what the validator checks more
        # strictly above; the database still refuses a writer that passes the form.
        return {*super()._get_validation_exclusions(), 'layout'}

    def clean(self):
        cleaned = super().clean()
        if not self.instance._state.adding and self.instance.is_builtin:
            raise forms.ValidationError(_('A built-in template cannot be changed; copy it to make one of your own.'))
        return cleaned

    def save(self, commit=True):
        layout = self.cleaned_data.get('layout')
        if isinstance(layout, dict):
            self.instance.schema_version = layout.get('schema', catalogue.SCHEMA_VERSION)
        return super().save(commit)


RULE_TABS = [
    ('general', _('General'), ['template', 'unit', 'system', 'system_type', 'species', 'kind']),
]
ONE_SCOPE = _('A rule is for one unit, system, system type, species or kind, or for every unit.')


class CardTemplateAssignmentForm(TabbedForm):
    """A rule: a template and at most one scope (none: every unit, the one global rule). The database holds one scope
    per rule and one live rule per scope; the global rule stays global (every unit must get a template)."""

    tabs = RULE_TABS

    class Meta:
        model = CardTemplateAssignment
        fields = tab_fields(RULE_TABS)
        help_texts = {
            'unit': _('Choose one of unit, system, system type, species or kind, or none for every unit. The most '
                      'specific rule wins: a unit’s own, then its system’s, its system type’s, its species’, its kind’s; '
                      'a board’s card and default come before and after the rules.'),
            'system_type': _('Hatchery and nursery systems are reached here.'),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['template'].queryset = CardTemplate.objects.order_by('-is_builtin', 'name')
        self.fields['unit'].queryset = Tank.objects.order_by('code')
        self.fields['system'].queryset = System.objects.order_by('name')
        self.fields['species'].queryset = Species.objects.order_by('common_name')
        for name in SCOPES:
            self.fields[name].required = False

    def clean(self):
        cleaned = super().clean()
        given = [name for name in SCOPES if cleaned.get(name) not in (None, '')]
        if len(given) > 1:
            raise forms.ValidationError(ONE_SCOPE)
        if not self.instance._state.adding and self.instance.is_global and given:
            raise forms.ValidationError(_('The global rule stays for every unit: change its template only.'))
        return cleaned

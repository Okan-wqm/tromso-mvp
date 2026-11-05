"""The monitoring board's form: its name, description, how its cards are drawn and how often its screens ask; and its Units
list, one row per card (a unit and its own template), saved as a whole list (monitoring/resources.py). The templates
offered are the live ones (Reference data › Card templates), a built-in by its name in the person's language."""
from django import forms
from django.utils.translation import gettext_lazy as _, ngettext_lazy

from core.crud import RowFormSet, TabbedForm, tab_fields
from farm.models import Tank

from .models import REFRESH_MAX, REFRESH_MIN, CardTemplate, MonitorBoard, MonitorBoardUnit

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

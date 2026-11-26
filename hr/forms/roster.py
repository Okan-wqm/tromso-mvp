from django import forms
from django.utils.translation import gettext_lazy as _

from core.crud import TabbedForm, tab_fields
from core.widgets import DayInput

from .. import scope
from ..models import Employee, Shift, ShiftAssignment

TABS = [('details', _('Details'), ['employee', 'day', 'shift', 'note'])]


class ShiftAssignmentForm(TabbedForm):
    """One cell of the roster: a person's plan for a day. The person is chosen among the people of the user's team (so a
    forged id fails the ordinary choice check); no shift is planned off. The form reads what was typed: the plan is
    hr.services.plan_day's, the one write path of the roster with the batch plan (`plan_shifts`), which checks the day is
    the user's to plan, never their own, and runs the rules on the plan as it would be after the save: a blocking finding
    is an error on the form, a warning is told after the save. A cleared cell is a delete (logged)."""

    tabs = TABS
    fixed_after_creation = ('employee', 'day')

    class Meta:
        model = ShiftAssignment
        fields = tab_fields(TABS)
        help_texts = {
            'shift': _('The shift the person starts on this day; none means planned off.'),
            'note': _('A remark for the lead’s own planning; it is not shown in the log.'),
        }
        widgets = {
            'day': DayInput(),
            'note': forms.TextInput(),
        }

    def __init__(self, *args, user=None, realm=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        # a new record's person is chosen among the team in the panel's realm (an existing one keeps its person)
        chosen_in = realm if self.instance._state.adding else None
        employees = scope.team(user, realm=chosen_in) if user is not None else Employee.objects.none()
        self.fields['employee'].queryset = employees.select_related('user')
        self.fields['employee'].label_from_instance = lambda employee: employee.full_name
        self.fields['shift'].queryset = Shift.objects.filter(status='active')
        self.fields['shift'].empty_label = _('Planned off')
        self.fields['shift'].required = False

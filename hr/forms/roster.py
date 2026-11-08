from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from core.crud import TabbedForm, tab_fields
from core.widgets import DayInput

from .. import rules, scope, services
from ..models import Employee, Shift, ShiftAssignment

TABS = [('details', _('Details'), ['employee', 'day', 'shift', 'note'])]


class ShiftAssignmentForm(TabbedForm):
    """One cell of the roster: a person's plan for a day. The person is chosen among the people of the user's team (so a
    forged id fails the ordinary choice check) and, for the day chosen, the team of that day (`scope.can_reach`); no shift
    is planned off. The rules run on the plan as it would be after the save: a blocking finding is an error on the form, a
    warning is told after the save. A cleared cell is a delete (logged)."""

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
        self.warnings = []
        # a new record's person is chosen among the team in the panel's realm (an existing one keeps its person)
        chosen_in = realm if self.instance._state.adding else None
        employees = scope.team(user, realm=chosen_in) if user is not None else Employee.objects.none()
        self.fields['employee'].queryset = employees.select_related('user')
        self.fields['employee'].label_from_instance = lambda employee: employee.full_name
        self.fields['shift'].queryset = Shift.objects.filter(status='active')
        self.fields['shift'].empty_label = _('Planned off')
        self.fields['shift'].required = False

    def clean(self):
        cleaned = super().clean()
        employee, day, shift = (cleaned.get(name) for name in ('employee', 'day', 'shift'))
        if not self.instance._state.adding:
            employee, day = self.instance.employee, self.instance.day
        if employee is None or day is None or self.errors:
            return cleaned
        if not scope.can_reach(self.user, employee, day):
            raise ValidationError(_('You do not plan this person on this day.'))
        if services.self_plan(self.user, employee):
            raise ValidationError(_('You do not plan your own days.'))
        found = services.evaluate(employee, {day: shift})
        blocking = [item for item in found if item.blocks]
        if blocking:
            raise ValidationError([rules.text(item) for item in blocking])
        self.warnings = [item for item in found if not item.blocks]
        self.instance.warnings = self.warnings
        return cleaned

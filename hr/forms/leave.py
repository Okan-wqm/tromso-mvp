from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from core import navigation
from core.crud import CodedFormMixin, TabbedForm, tab_fields
from core.widgets import DayInput

from .. import scope, services
from ..models import Employee, LeaveRequest, LeaveType

TYPE_TABS = [('details', _('Details'), ['name', 'code', 'annual_days', 'needs_approval', 'status'])]
REQUEST_TABS = [('request', _('Request'), ['employee', 'leave_type', 'first_day', 'last_day', 'reason'])]


class LeaveTypeForm(CodedFormMixin, TabbedForm):
    tabs = TYPE_TABS

    class Meta:
        model = LeaveType
        fields = tab_fields(TYPE_TABS)
        help_texts = {
            'annual_days': _('The days a person may take of this type in a year; empty for no limit.'),
            'needs_approval': _('Off: a request of this type is granted the moment it is filed, with no decider.'),
            'status': _('Inactive: kept on the old requests, not offered for new ones.'),
        }
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': _('e.g. Annual leave')}),
            'code': forms.TextInput(attrs={'placeholder': _('e.g. ANNUAL'), 'data-uppercase': ''}),
            'annual_days': forms.TextInput(attrs={'inputmode': 'decimal'}),
        }
        localized_fields = ['annual_days']


class LeaveRequestForm(TabbedForm):
    """A request for leave: for oneself, or by a lead for a person of their team. It is filed pending (or granted at once
    for a type that needs no approval) and decided by someone else (hr.services.decide_leave), so the status and the decision
    are not here. The reason is the person's own words: the form shows it to them and to the holders of Everyone only
    (hr.scope.sees_reason). A request can be changed while it is pending; the person is chosen once. The form reads what
    was typed and says the days out of order on their field; what a request must keep (inside the employment, a day
    charged, the yearly allowance, pending to be changed, a reason only its person writes) is hr.services.file_leave's
    and change_leave's, the one write path the tab hands its save to."""

    tabs = REQUEST_TABS
    fixed_after_creation = ('employee',)

    class Meta:
        model = LeaveRequest
        fields = tab_fields(REQUEST_TABS)
        help_texts = {
            'first_day': _('The first day away.'),
            'last_day': _('The last day away; the days charged are counted without weekends and holidays.'),
            'reason': _('Only you and the people who see every employee can read this.'),
        }
        widgets = {
            'first_day': DayInput(),
            'last_day': DayInput(),
            'reason': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, user=None, realm=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        # a new record's person is chosen among the team in the panel's realm (an existing one keeps its person)
        chosen_in = realm if self.instance._state.adding else None
        employees = scope.team(user, realm=chosen_in) if user is not None else Employee.objects.none()
        self.fields['employee'].queryset = employees.select_related('user')
        self.fields['employee'].label_from_instance = lambda employee: employee.full_name
        own = Employee.objects.filter(user=user).first() if user is not None else None
        if self.instance._state.adding and own is not None and not self.is_bound:
            self.initial.setdefault('employee', own.pk)
        self.fields['leave_type'].queryset = LeaveType.objects.filter(status='active')
        if not self.fields['leave_type'].queryset.exists():
            # An empty list with no word of why was a dead end (flow fault B-03): say what is missing and where it is.
            # Where: by the menu's own names (core.navigation.trail, as the correction window's refusal says its page,
            # B-07), so the sentence follows the menu; Leave types has no menu line, it is a part of Scheduling settings.
            self.fields['leave_type'].help_text = _(
                'There is no active leave type yet, so a request cannot be filed. Leave types are added in '
                '%(where)s › %(types)s, by a person whose role may.') % {
                'where': navigation.trail('hr.view_schedulingsettings', _('Scheduling settings')),
                'types': _('Leave types')}
        if not self.instance._state.adding and not scope.sees_reason(user, self.instance.employee):
            del self.fields['reason']          # the person's own words: not for a lead

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('first_day') is not None and cleaned.get('last_day') is not None:
            # The days in order, on their field before the table's check answers in its place (the service again).
            try:
                services.check_days(cleaned['first_day'], cleaned['last_day'])
            except ValidationError as error:
                for field, messages in error.message_dict.items():
                    self.add_error(field, messages)
        return cleaned

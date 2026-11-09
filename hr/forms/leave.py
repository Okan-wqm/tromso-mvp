from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.crud import CodedFormMixin, TabbedForm, tab_fields
from core.widgets import DayInput

from .. import leave, read, scope, services
from ..models import Employee, LeaveRequest, LeaveType
from ..models.leave import LeaveStatus

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
    are not here. The reason is the person's own words: it is shown to them and to the holders of Everyone only, and the form
    drops it for anyone else. A request can be changed while it is pending; the person and the type are chosen once."""

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
        employee = own if self.instance._state.adding else self.instance.employee
        if not self.instance._state.adding and employee.user_id != getattr(user, 'pk', None) \
                and not user.has_perm(scope.ALL):
            del self.fields['reason']          # the person's own words: not for a lead

    def clean(self):
        cleaned = super().clean()
        if self.errors:
            return cleaned
        adding = self.instance._state.adding
        if not adding and self.instance.status != LeaveStatus.PENDING:
            raise ValidationError(_('Only a pending request can be changed.'))
        employee = cleaned.get('employee') or self.instance.employee
        first, last, kind = cleaned['first_day'], cleaned['last_day'], cleaned['leave_type']
        if last < first:
            self.add_error('last_day', _('The last day cannot be before the first.'))
            return cleaned
        services.check_employed(employee, first, last)
        if adding and 'reason' in self.fields and employee.user_id != getattr(self.user, 'pk', None):
            cleaned['reason'] = ''
            self.instance.reason = ''
        site = read.site_on(employee, first)
        charged = leave.charged_by_year(first, last, site)
        if not charged:
            self.add_error('last_day', _('These days are all weekends or holidays: nothing would be charged.'))
            return cleaned
        if kind.annual_days is not None:
            for year, days in charged.items():
                used = leave.used(employee, kind, year, site, exclude=None if adding else self.instance)
                if used + days > kind.annual_days:
                    self.add_error('leave_type', _('This is %(days)s days of %(kind)s in %(year)s and %(left)s are left.')
                                   % {'days': days, 'kind': kind.name, 'year': year, 'left': kind.annual_days - used})
                    break
        if adding and not kind.needs_approval:
            self.instance.status = LeaveStatus.APPROVED
            self.instance.decided_at = timezone.now()
        return cleaned

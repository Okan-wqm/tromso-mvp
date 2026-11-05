from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import Exists, OuterRef, Q
from django.utils.translation import gettext_lazy as _

from core.crud import TabbedForm, tab_fields
from farm.stock.dates import site_today

from .. import read, scope, units
from ..models import Employee

PLACEMENT_FIELDS = ('department', 'title', 'from_day')
TABS = [
    ('person', _('Person'), ['employee_number', 'user', 'first_name', 'last_name', 'employment_type']),
    ('employment', _('Employment'), ['joined_on', 'left_on']),
    ('placement', _('Placement'), list(PLACEMENT_FIELDS)),
]


class DepartmentField(forms.ChoiceField):
    """The department chooser: production departments and office departments in one grouped list, answered as the
    department row itself (hr.units)."""

    def clean(self, value):
        value = super().clean(value)
        if not value:
            return None
        found = units.find(value)
        if found is None:
            raise ValidationError(_('Select a department.'), code='invalid_choice')
        return found


class EmployeeForm(TabbedForm):
    """A person. Where they work is a dated placement, not a column: this form shows their current one and, when it
    is changed, `hr.services.move` closes it the day before the date given and opens the next (the resource's
    `after_save`; the choice travels on the instance as `placement`). There is no pay, bank, address or number of
    identity here, on purpose."""

    tabs = TABS
    department = DepartmentField(label=_('Department'), required=False)
    title = forms.CharField(label=_('Title'), max_length=100, required=False)
    from_day = forms.DateField(label=_('From'), required=False,
                               widget=forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'))

    class Meta:
        model = Employee
        fields = [name for name in tab_fields(TABS) if name not in PLACEMENT_FIELDS]
        help_texts = {
            'employee_number': _('The number the company knows the person by.'),
            'user': _('The account the person signs in with. Their name is then the account’s; leave it empty for '
                      'someone who never signs in (a student, a visiting researcher).'),
            'first_name': _('Only for a person without an account.'),
            'last_name': _('Required for a person without an account.'),
            'joined_on': _('The first day of employment.'),
            'left_on': _('The last day of employment; the placement then ends with it. Empty while they work here.'),
        }
        widgets = {
            'employee_number': forms.TextInput(attrs={'placeholder': _('e.g. E-1042')}),
            'joined_on': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'left_on': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
        }

    def __init__(self, *args, editor=None, **kwargs):
        super().__init__(*args, **kwargs)
        adding = self.instance._state.adding
        self.today = site_today(None)
        self.current = None if adding else read.placement_on(self.instance, self.today)
        accounts = get_user_model().objects.filter(is_active=True).filter(
            ~Exists(Employee.objects.filter(user=OuterRef('pk'))) | Q(pk=self.instance.user_id or 0)).order_by('username')
        self.fields['user'].queryset = accounts
        self.fields['user'].empty_label = _('No account')
        # Who a person's account is decides who reads their private words (a leave reason is the account's own): only the
        # holders of Everyone link or unlink one.
        if editor is None or not editor.has_perm(scope.ALL):
            self.fields['user'].disabled = True
            self.fields['user'].queryset = accounts.filter(pk=self.instance.user_id or 0)
        self.fields['department'].choices = [('', _('Select a department'))] + units.choices(
            include=[self.current.department] if self.current else [])
        self.fields['department'].required = adding
        self.fields['from_day'].help_text = _('The day the new placement starts; the old one ends the day before. '
                                              'For a new person: their first day.')
        if self.current is not None and not self.is_bound:
            self.initial.setdefault('department', units.token(self.current.department))
            self.initial.setdefault('title', self.current.title)
            self.initial.setdefault('from_day', self.current.valid_from)
        if self.instance.left_on and not adding:
            for name in PLACEMENT_FIELDS:
                self.fields[name].disabled = True

    def clean(self):
        cleaned = super().clean()
        adding = self.instance._state.adding
        if cleaned.get('user') is not None:
            cleaned['first_name'] = cleaned['last_name'] = ''
            self.instance.first_name = self.instance.last_name = ''
        elif not cleaned.get('last_name') and 'last_name' not in self.errors:
            self.add_error('last_name', _('A person without an account needs a last name.'))
        joined, left = cleaned.get('joined_on'), cleaned.get('left_on')
        if joined and left and left < joined:
            self.add_error('left_on', _('A person cannot leave before they joined.'))
        self.instance.placement = None
        if all(self.fields[name].disabled for name in PLACEMENT_FIELDS):
            return cleaned
        department, title, day = cleaned.get('department'), (cleaned.get('title') or '').strip(), cleaned.get('from_day')
        was = self.current
        changed = department is not None and (was is None or department != was.department or title != was.title)
        if adding and department is not None:
            day = day or joined
            if day is None and 'joined_on' not in self.errors:
                self.add_error('from_day', _('Say from which day the person is placed.'))
            if day and joined and day < joined:
                self.add_error('from_day', _('A person cannot be placed before they joined.'))
        elif changed:
            if day is None:
                self.add_error('from_day', _('Say from which day the change counts.'))
            elif was is not None and day < was.valid_from:
                self.add_error('from_day', _('The change cannot start before the current placement did (%(day)s).')
                               % {'day': was.valid_from})
            elif left and day > left:
                self.add_error('from_day', _('A person who has left cannot be placed after their last day.'))
        if changed and not self.errors:
            self.instance.placement = (department, title, day)
        return cleaned

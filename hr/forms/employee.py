from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import Exists, OuterRef, Q
from django.utils.translation import gettext_lazy as _

from core.crud import TabbedForm, tab_fields
from farm.stock.dates import site_today
from core.widgets import DayInput

from .. import read, scope, services, units
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
    is changed, `hr.services.move` closes it the day before the date given and opens the next (`placement`, which the
    tab hands to hr.services.add_employee or change_employee with the person's columns: the one write path, whose rules
    are the first and last day, the records they would leave outside, the account and the move). There is no pay, bank,
    address or number of identity here, on purpose. A new person is placed in a department of the panel the form is
    opened in (`realm`: Production › Team in a production department, Company › HR in an office one), so they are in that
    panel once saved; a move offers every department (a person changes sides by a dated move, hr.services.move). The
    form reads what was typed: a name for a person without an account, and the day a new placement starts."""

    tabs = TABS
    department = DepartmentField(label=_('Department'), required=False)
    title = forms.CharField(label=_('Title'), max_length=100, required=False)
    from_day = forms.DateField(label=_('From'), required=False,
                               widget=DayInput())

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
            'joined_on': DayInput(),
            'left_on': DayInput(),
        }

    def __init__(self, *args, editor=None, realm=None, **kwargs):
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
            include=[self.current.department] if self.current else [], kinds=[realm] if realm and adding else None,
            allowed=None if editor is None else scope.placeable(editor))
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
        if cleaned.get('user') is not None:       # a person with an account is named by it: the name boxes are not read
            cleaned['first_name'] = cleaned['last_name'] = ''
            self.instance.first_name = self.instance.last_name = ''
        elif not cleaned.get('last_name') and 'last_name' not in self.errors:
            self.add_error('last_name', _('A person without an account needs a last name.'))
        if cleaned.get('joined_on') is not None:
            # The rule of the two days, on its field before the table's check answers in its place (the service again).
            try:
                services.check_bounds(cleaned['joined_on'], cleaned.get('left_on'))
            except ValidationError as error:
                for field, messages in error.message_dict.items():
                    self.add_error(field, messages)
        self.placement = None
        if all(self.fields[name].disabled for name in PLACEMENT_FIELDS):
            return cleaned
        department, title, day = cleaned.get('department'), (cleaned.get('title') or '').strip(), cleaned.get('from_day')
        was = self.current
        changed = department is not None and (was is None or department != was.department or title != was.title)
        if adding and department is not None:
            day = day or cleaned.get('joined_on')
            if day is None and 'joined_on' not in self.errors:
                self.add_error('from_day', _('Say from which day the person is placed.'))
        elif changed and day is None:
            self.add_error('from_day', _('Say from which day the change counts.'))
        if changed and not self.errors:
            self.placement = (department, title, day)
        return cleaned

    def values(self):
        """The person's own columns as typed, for hr.services (the placement is `placement`)."""
        return {name: self.cleaned_data[name] for name in (*services.PERSON_FIELDS, 'left_on') if name in self.cleaned_data}

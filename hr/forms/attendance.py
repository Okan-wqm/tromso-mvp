from datetime import timezone as utc

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.crud import TabbedForm, tab_fields
from farm.forms.water import SiteClockField

from .. import read, scope, services
from ..models import AttendanceRecord, Employee

TABS = [('record', _('Record'), ['employee', 'clock_in', 'clock_out', 'note'])]


class AttendanceRecordForm(TabbedForm):
    """A stretch of presence typed by hand: the person (among the user's team), the times on the site's clock, and the
    reason. The same form corrects a punch and a punch is voided by deleting it. The form only reads what was typed: the
    times as the instants they stand for, and the rule of the two times themselves, said on their fields
    (hr.services.check_times). Whether this lead may enter or correct this person's presence on that day, whether the
    reason is needed and how the stretch was made are hr.services.enter_presence's and correct_presence's, the one write
    path (the tab hands them its save). A stretch never overlaps another of the same person and at most one is open: the
    database refuses the rest."""

    tabs = TABS
    fixed_after_creation = ('employee',)
    clock_in = SiteClockField(label=_('Clock in'), help_text=_('Date and time on the site’s clock.'))
    clock_out = SiteClockField(label=_('Clock out'), required=False,
                               help_text=_('Empty while the person is still in.'))

    class Meta:
        model = AttendanceRecord
        fields = tab_fields(TABS)
        help_texts = {'note': _('Why the time was entered or corrected: it is not shown in the log.')}
        widgets = {'note': forms.TextInput()}

    def __init__(self, *args, user=None, realm=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        # a new record's person is chosen among the team in the panel's realm (an existing one keeps its person)
        chosen_in = realm if self.instance._state.adding else None
        employees = scope.team(user, realm=chosen_in) if user is not None else Employee.objects.none()
        self.fields['employee'].queryset = employees.select_related('user')
        self.fields['employee'].label_from_instance = lambda employee: employee.full_name
        if not self.instance._state.adding and not self.is_bound:
            for name in ('clock_in', 'clock_out'):
                moment = getattr(self.instance, name)
                if moment is not None:
                    self.initial[name] = self.shown(moment)

    def shown(self, moment):
        """A stored moment as the form shows it: on the clock that governs it (hr.read.governing), to the minute."""
        zone = read.governing(self.instance.employee, moment).zone
        return timezone.localtime(moment, zone).replace(second=0, microsecond=0, tzinfo=None)

    def kept_or_made(self, name, typed, employee):
        """The moment typed (hr.read.typed_moment); the stored one when the field was not changed (the form shows minutes:
        a punch at 08:00:45 is not rewritten as 08:00:00 by an edit that touched something else)."""
        stored = None if self.instance._state.adding else getattr(self.instance, name)
        if stored is not None and self.shown(stored) == typed:
            return stored
        return read.typed_moment(employee, typed)

    def instants(self, cleaned):
        """The typed times (naive, on the person's site's clock) as the instants they stand for, written into `cleaned`
        as UTC before anything reads them: the overlap check of core.crud and the model's validation then see what the
        database will store (and logs), never a site's time read as UTC. Times that cannot be placed (a field not valid)
        are taken out. Returns (clock in, clock out) or None."""
        employee = cleaned.get('employee') if self.instance._state.adding else self.instance.employee
        naive_in, naive_out = cleaned.get('clock_in'), cleaned.get('clock_out')
        if self.errors or employee is None or naive_in is None:
            cleaned.pop('clock_in', None)
            cleaned.pop('clock_out', None)
            return None
        started = self.kept_or_made('clock_in', naive_in, employee)
        ended = self.kept_or_made('clock_out', naive_out, employee) if naive_out is not None else None
        cleaned['clock_in'] = started.astimezone(utc.utc)
        cleaned['clock_out'] = ended.astimezone(utc.utc) if ended is not None else None
        return started, ended

    def clean(self):
        placed = self.instants(self.cleaned_data)
        if placed is not None:
            # The rule of the two times themselves (the out after the in, neither later than now), before the table's
            # overlap check answers in its place: a clock-out typed before the clock-in is told as that (review R18).
            try:
                services.check_times(*placed)
            except ValidationError as error:
                for field, messages in error.message_dict.items():
                    self.add_error(field, messages)       # which also takes the time out of what is checked next
        return super().clean()

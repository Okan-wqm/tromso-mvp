from datetime import timezone as utc

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.crud import TabbedForm, tab_fields
from farm.forms.water import SiteClockField
from farm.models.site import zone_of

from .. import read, scope, services
from ..models import AttendanceRecord, Employee

TABS = [('record', _('Record'), ['employee', 'clock_in', 'clock_out', 'note'])]


class AttendanceRecordForm(TabbedForm):
    """A stretch of presence typed by hand: for a person of the user's team (checked for the day), the times on the site's
    clock, and the reason (required: this is the lead's entry, not the person's own clock-in). The same form corrects a
    punch (the change is logged with what it was before) and a punch is voided by deleting it. A correction that
    changes a time of a stretch the person clocked themselves makes it an entered one, with its reason: so a forgotten
    clock-out is closed here, with the real time and why. A stretch never overlaps another of the same person and at
    most one is open: the database refuses the rest."""

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
            _day, zone = read.local_day(self.instance.employee, self.instance.clock_in)   # the site's day, never UTC's
            for name in ('clock_in', 'clock_out'):
                moment = getattr(self.instance, name)
                if moment is not None:
                    self.initial[name] = timezone.localtime(moment, zone).replace(second=0, microsecond=0, tzinfo=None)

    @staticmethod
    def zone(employee, day):
        """The clock the person's times are typed on: the site of the department they are placed in that day."""
        return zone_of(read.site_on(employee, day))

    def kept_or_made(self, name, naive, zone):
        """The moment typed, on the site's clock; the stored one when the field was not changed (the form shows minutes: a
        punch at 08:00:45 is not rewritten as 08:00:00 by an edit that touched something else)."""
        stored = None if self.instance._state.adding else getattr(self.instance, name)
        if stored is not None and timezone.localtime(stored, zone).replace(second=0, microsecond=0,
                                                                         tzinfo=None) == naive:
            return stored
        return timezone.make_aware(naive, zone)

    def instants(self, cleaned):
        """The typed times (naive, on the person's site's clock) as the instants they stand for, written into `cleaned`
        as UTC before anything reads them: the overlap check of core.crud and the model's validation then see what the
        database will store (and logs), never a site's time read as UTC. Times that cannot be placed (a field not valid)
        are taken out. Returns (person, zone, clock in, clock out) or None."""
        adding = self.instance._state.adding
        employee = cleaned.get('employee') if adding else self.instance.employee
        naive_in, naive_out = cleaned.get('clock_in'), cleaned.get('clock_out')
        if self.errors or employee is None or naive_in is None:
            cleaned.pop('clock_in', None)
            cleaned.pop('clock_out', None)
            return None
        zone = self.zone(employee, naive_in.date())
        started = self.kept_or_made('clock_in', naive_in, zone)
        ended = self.kept_or_made('clock_out', naive_out, zone) if naive_out is not None else None
        cleaned['clock_in'] = started.astimezone(utc.utc)
        cleaned['clock_out'] = ended.astimezone(utc.utc) if ended is not None else None
        return employee, zone, started, ended

    def clean(self):
        placed = self.instants(self.cleaned_data)
        if placed is not None:
            # The rule of the two times themselves (the out after the in, neither later than now), before the table's
            # overlap check answers in its place: a clock-out typed before the clock-in is told as that (review R18).
            try:
                services.check_times(placed[2], placed[3])
            except ValidationError as error:
                for field, messages in error.message_dict.items():
                    self.add_error(field, messages)       # which also takes the time out of what is checked next
        cleaned = super().clean()
        if self.errors:
            return cleaned
        adding = self.instance._state.adding
        employee, zone, started, ended = placed
        if not scope.can_reach(self.user, employee, started.astimezone(zone).date()):
            raise ValidationError(_('You do not see this person on this day.'))
        if services.own_record(self.user, employee):
            raise ValidationError(_('You do not enter or correct your own attendance.'))
        services.check_employed(employee, started.astimezone(zone).date(),
                                ended.astimezone(zone).date() if ended is not None else None)
        # A time typed by hand is an entered time, whoever clocked in: a new stretch, and a stretch whose clock-in or
        # clock-out this edit changes (a forgotten clock-out closed by a lead, hr.rules.forgotten). An edit that leaves
        # both times as they are leaves the person's own stretch their own.
        typed = adding or started != self.instance.clock_in or ended != self.instance.clock_out
        if (typed or self.instance.via == AttendanceRecord.Via.ENTERED) and not (cleaned.get('note') or '').strip():
            self.add_error('note', _('Say why the time was entered by hand.'))
            return cleaned
        if typed:
            self.instance.via = AttendanceRecord.Via.ENTERED
        return cleaned

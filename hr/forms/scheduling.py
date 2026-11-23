from django import forms
from django.utils.translation import gettext_lazy as _

from core.crud import CodedFormMixin, TabbedForm, tab_fields
from farm.models import Site
from core.widgets import DayInput

from ..models import Holiday, SchedulingSettings, Shift
from ..models.scheduling import FORGOTTEN_RANGE, MAX_FORGOTTEN_HOURS, MIN_FORGOTTEN_HOURS, span_minutes

SHIFT_TABS = [('details', _('Details'), ['name', 'code', 'starts_at', 'ends_at', 'break_minutes', 'grace_minutes',
                                         'tone', 'status'])]
HOLIDAY_TABS = [('details', _('Details'), ['day', 'name', 'site'])]
SETTINGS_TABS = [
    ('limits', _('Limits'), ['standard_week_minutes', 'min_rest_minutes', 'max_consecutive_days', 'rest_rule']),
    ('days', _('Days and punches'), ['working_weekdays', 'punch_window_minutes', 'absent_after_minutes',
                                     'forgotten_after_hours']),
]


class ShiftForm(CodedFormMixin, TabbedForm):
    tabs = SHIFT_TABS

    class Meta:
        model = Shift
        fields = tab_fields(SHIFT_TABS)
        help_texts = {
            'starts_at': _('Wall-clock time on the site. A shift that ends at or before its start ends the next day.'),
            'break_minutes': _('Unpaid: it is taken off the planned hours. At most 240, shorter than the shift.'),
            'grace_minutes': _('Minutes after the start before an arrival counts as late (at most 120).'),
            'tone': _('Which of the eight colours of the schedule the shift is shown in, 1 to 8.'),
            'status': _('Inactive: kept on the old plans, not offered for new ones.'),
        }
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': _('e.g. Morning')}),
            'code': forms.TextInput(attrs={'placeholder': _('e.g. MORN'), 'data-uppercase': ''}),
            'starts_at': forms.TimeInput(attrs={'type': 'time'}, format='%H:%M'),
            'ends_at': forms.TimeInput(attrs={'type': 'time'}, format='%H:%M'),
        }

    def clean(self):
        """An active shift, with the punch window a person may clock in before it, is never longer than the hours after
        which a clock-in counts as forgotten (Scheduling settings): a person on it could not clock out at its end. The
        settings form holds the other side."""
        cleaned = super().clean()
        start, end = cleaned.get('starts_at'), cleaned.get('ends_at')
        if start and end and start != end and cleaned.get('status') == Shift.Status.ACTIVE:
            settings = SchedulingSettings.get()
            if span_minutes(start, end) + settings.punch_window_minutes > settings.forgotten_after_hours * 60:
                self.add_error('ends_at', _(
                    'This shift and the %(window)s minutes a person may clock in before it are longer than the '
                    '%(hours)s hours after which a clock-in counts as forgotten (Scheduling settings): raise that '
                    'limit first.') % {'window': settings.punch_window_minutes, 'hours': settings.forgotten_after_hours})
        return cleaned


class HolidayForm(TabbedForm):
    tabs = HOLIDAY_TABS

    class Meta:
        model = Holiday
        fields = tab_fields(HOLIDAY_TABS)
        help_texts = {'site': _('Leave it empty for a day that is a holiday on every site.')}
        widgets = {
            'day': DayInput(),
            'name': forms.TextInput(attrs={'placeholder': _('e.g. Christmas Day')}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['site'].queryset = Site.objects.all()
        self.fields['site'].empty_label = _('Every site')

    def clean_name(self):
        return self.cleaned_data['name'].strip()


class SchedulingSettingsForm(TabbedForm):
    tabs = SETTINGS_TABS
    # Declared so that a blank and an absurd value are each refused with one sentence that says why (the model's field
    # would add Django's own for a negative number); the range and the shifts are checked in its clean method.
    forgotten_after_hours = forms.IntegerField(
        label=SchedulingSettings._meta.get_field('forgotten_after_hours').verbose_name,
        help_text=_('A clock-in still open after this many hours counts as a forgotten clock-out: the board says so '
                    'instead of present, the person is told to ask their lead, and the lead closes it on the '
                    'Attendance page with the real time and a reason. Default 16 hours; 1 to 168, and not shorter '
                    'than the longest active shift with the punch window before it.'),
        error_messages={'required': _('Say after how many hours an open clock-in counts as a forgotten clock-out.')})

    class Meta:
        model = SchedulingSettings
        fields = tab_fields(SETTINGS_TABS)
        help_texts = {
            'standard_week_minutes': _('The week the Team overview compares planned hours with. Default 40 hours; '
                                       'a default, not the law: confirm it with the company’s agreements.'),
            'min_rest_minutes': _('The shortest rest between two shifts of one person. Default 11 hours; a default, '
                                  'not the law: set it only stricter than the statute.'),
            'max_consecutive_days': _('The most days in a row one person is planned. Default 6.'),
            'rest_rule': _('Warn: the plan is saved with a notice. Block: the plan is refused.'),
            'working_weekdays': _('The days a leave request is charged for (public holidays are taken out). '
                                  'Default Monday to Friday.'),
            'punch_window_minutes': _('How long before a shift starts a clock-in counts for it. Default 2 hours.'),
            'absent_after_minutes': _('Minutes after the start with no clock-in before a person is shown as absent. '
                                      'Default 30.'),
        }

    def clean_working_weekdays(self):
        days = self.cleaned_data['working_weekdays']
        if not days:
            raise forms.ValidationError(_('Tick at least one weekday.'))
        return days

    def clean_forgotten_after_hours(self):
        hours = self.cleaned_data['forgotten_after_hours']
        if not MIN_FORGOTTEN_HOURS <= hours <= MAX_FORGOTTEN_HOURS:
            raise forms.ValidationError(FORGOTTEN_RANGE)
        return hours

    def clean(self):
        """The limit is never shorter than an active shift and the punch window before it: a stretch begins at the
        clock-in, which may come the whole window before the shift, so a person on the shift would count as forgotten
        before it ends and could not clock out (the shift form holds the other side: `ShiftForm.clean`). Both values
        are this form's, so a wider window alone is held to it too."""
        cleaned = super().clean()
        hours, window = cleaned.get('forgotten_after_hours'), cleaned.get('punch_window_minutes')
        if hours is None or window is None:
            return cleaned
        longest = max(Shift.objects.filter(status=Shift.Status.ACTIVE), key=lambda shift: shift.span_minutes,
                      default=None)
        if longest is not None and longest.span_minutes + window > hours * 60:
            self.add_error('forgotten_after_hours', _(
                'The shift %(shift)s and the %(window)s minutes a person may clock in before it are longer than '
                '%(hours)s hours: a person on it would count as forgotten before it ends.')
                % {'shift': longest, 'window': window, 'hours': hours})
        return cleaned

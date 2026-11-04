from django import forms
from django.utils.translation import gettext_lazy as _

from core.crud import CodedFormMixin, TabbedForm, tab_fields
from farm.models import Site

from ..models import Holiday, SchedulingSettings, Shift

SHIFT_TABS = [('details', _('Details'), ['name', 'code', 'starts_at', 'ends_at', 'break_minutes', 'grace_minutes',
                                         'tone', 'status'])]
HOLIDAY_TABS = [('details', _('Details'), ['day', 'name', 'site'])]
SETTINGS_TABS = [
    ('limits', _('Limits'), ['standard_week_minutes', 'min_rest_minutes', 'max_consecutive_days', 'rest_rule']),
    ('days', _('Days and punches'), ['working_weekdays', 'punch_window_minutes', 'absent_after_minutes']),
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


class HolidayForm(TabbedForm):
    tabs = HOLIDAY_TABS

    class Meta:
        model = Holiday
        fields = tab_fields(HOLIDAY_TABS)
        help_texts = {'site': _('Leave it empty for a day that is a holiday on every site.')}
        widgets = {
            'day': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
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

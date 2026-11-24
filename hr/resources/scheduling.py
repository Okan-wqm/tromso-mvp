from django.utils import dateformat, formats
from django.utils.translation import gettext_lazy as _

from core import listprops as L
from core.crud import Resource

from ..forms.scheduling import HolidayForm, SchedulingSettingsForm, ShiftForm
from ..models import Holiday, LeaveType, SchedulingSettings, Shift


class ShiftResource(Resource):
    """The shift patterns of the roster (a hidden menu entry: reached from Scheduling settings)."""

    model = Shift
    form_class = ShiftForm
    name, plural = _('shift'), _('shifts')
    url_prefix = 'hr/settings/shifts'
    search_fields = ['name', 'code']
    list_template = 'hr/shift_list.html'
    icon = 'timer'
    search_placeholder = _('Search by name or code')
    empty_text = _('A shift is a start and an end on the wall clock of the site, with a break. Add the shifts the roster uses.')

    @classmethod
    def list_rows(cls, view, objects, context):
        hour = lambda moment: formats.time_format(moment, 'TIME_FORMAT')   # noqa: E731
        return {'columns': [L.column('shift', _('Shift')), L.column('hours', _('Hours')),
                            L.column('break', _('Break (minutes)'), numeric=True),
                            L.column('grace', _('Grace (minutes)'), numeric=True), L.column('status', _('Status'))],
                'rows': [L.row(shift.pk, {
                    'shift': {**L.title(view, context, shift, shift.name), 'chips': [L.chip('note', shift.code)]},
                    'hours': L.cell(f'{hour(shift.starts_at)}–{hour(shift.ends_at)}',
                                    sub=[_('next day')] if shift.ends_at <= shift.starts_at else []),
                    'break': L.cell(shift.break_minutes), 'grace': L.cell(shift.grace_minutes),
                    'status': L.cell(chip=L.chip(L.STATUS_CHIP.get(shift.status, 'neutral'), shift.get_status_display())),
                }, L.edit_delete(view, context, shift, shift.name)) for shift in objects]}


class HolidayResource(Resource):
    """The days that are not working days, typed in by HR (a hidden menu entry)."""

    model = Holiday
    form_class = HolidayForm
    name, plural = _('holiday'), _('holidays')
    url_prefix = 'hr/settings/holidays'
    search_fields = ['name']
    list_template = 'hr/holiday_list.html'
    icon = 'calendar'
    page_size = 50
    search_placeholder = _('Search by name')
    empty_text = _('Add the public holidays and other days off of the company; a leave request is not charged for them.')

    @classmethod
    def list_rows(cls, view, objects, context):
        return {'columns': [L.column('day', _('Day')), L.column('holiday', _('Holiday')), L.column('site', _('Site'))],
                'rows': [L.row(holiday.pk, {
                    'day': L.cell(formats.date_format(holiday.day, 'DATE_FORMAT'), sub=[dateformat.format(holiday.day, 'l')]),
                    'holiday': L.title(view, context, holiday, holiday.name),
                    'site': L.cell(holiday.site.name if holiday.site else _('Every site')),
                }, L.edit_delete(view, context, holiday, holiday.name)) for holiday in objects]}

    @classmethod
    def queryset(cls):
        return super().queryset().select_related('site')


class SchedulingSettingsResource(Resource):
    """The one row of scheduling limits: it is changed, never added or deleted. The page shows it with the lists it
    leads to."""

    model = SchedulingSettings
    form_class = SchedulingSettingsForm
    name, plural = _('scheduling settings'), _('scheduling settings')
    url_prefix = 'hr/settings/scheduling'
    actions = ('change',)
    list_template = 'hr/settings_list.html'
    icon = 'settings'

    @classmethod
    def list_queryset(cls, request):
        SchedulingSettings.get()          # the row exists even if a restore left none
        return super().list_queryset(request)

    @classmethod
    def filter_list(cls, request, objects):
        return objects, {'shifts': Shift.objects.all(), 'holidays': Holiday.objects.select_related('site')[:10],
                         'leave_types': LeaveType.objects.all()}

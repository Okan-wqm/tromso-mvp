from django.utils.translation import gettext_lazy as _

from core.crud import Resource

from ..forms.scheduling import HolidayForm, SchedulingSettingsForm, ShiftForm
from ..models import Holiday, SchedulingSettings, Shift


class ShiftResource(Resource):
    """The shift patterns of the roster (a hidden menu entry: reached from Scheduling settings)."""

    model = Shift
    form_class = ShiftForm
    name, plural = _('shift'), _('shifts')
    url_prefix = 'hr/settings/shifts'
    search_fields = ['name', 'code']
    list_template = 'hr/shift_list.html'
    icon = 'timer'


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
        return objects, {'shifts': Shift.objects.all(), 'holidays': Holiday.objects.select_related('site')[:10]}

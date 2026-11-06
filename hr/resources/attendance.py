from datetime import timedelta

from django.db.models import OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce, TruncDate
from django.utils.translation import gettext_lazy as _

from core import navigation
from core.crud import Mount, Resource
from core.dates import read_day
from farm.models.site import zone_of
from farm.stock.dates import site_today

from .. import clock, scope, services
from ..forms.attendance import AttendanceRecordForm
from ..models import AttendanceRecord, Posting


class AttendanceRecordResource(Resource):
    """The Attendance page: the stretches of presence of the viewer's team, newest first, over the last days or the days
    asked for. Typed by a lead (Create, with a reason), corrected (Edit, logged with before and after) or voided (Delete);
    a person's own clock-in and clock-out are on the Today page. The same read permission opens Today and this page, so the
    page heading is the menu entry's, not the first entry that shares the permission."""

    model = AttendanceRecord
    form_class = AttendanceRecordForm
    name, plural = _('attendance record'), _('attendance records')
    url_prefix = 'hr/time/attendance'
    mounts = (Mount(scope.PRODUCTION, 'production/team/attendance'),)
    list_template = 'hr/attendance_list.html'
    page_size = 50
    icon = 'user-check'
    private_fields = ('note',)
    DAYS = 14

    @classmethod
    def menu_place(cls, mount=None):
        return navigation.page(cls.url_name('list', mount))

    @classmethod
    def queryset(cls):
        return super().queryset().select_related('employee__user')

    @classmethod
    def scoped(cls, request, objects):
        return scope.by_day(request.user, objects.annotate(clocked_day=TruncDate('clock_in')), 'employee', 'clocked_day',
                            scope.realm_for(request))

    @classmethod
    def allowed(cls, request, obj, action):
        return not services.self_plan(request.user, obj.employee)

    @classmethod
    def form(cls, request, *args, **kwargs):
        kwargs.setdefault('user', request.user)
        kwargs.setdefault('realm', scope.realm_for(request))
        return cls.form_class(*args, **kwargs)

    @classmethod
    def search(cls, objects, query):
        return objects.filter(Q(employee__employee_number__icontains=query) | Q(employee__first_name__icontains=query)
                              | Q(employee__last_name__icontains=query) | Q(employee__user__username__icontains=query))

    @classmethod
    def filter_list(cls, request, objects):
        today = site_today(None)
        first = read_day(request.GET.get('from', '')) or today - timedelta(days=cls.DAYS)
        last = read_day(request.GET.get('to', '')) or today
        # whole days on the company's clock: the list is a log of stretches, not a day's roster
        zone = zone_of(None)
        objects = objects.filter(clock_in__gte=clock.start_of_day(first, zone),
                                 clock_in__lt=clock.start_of_day(last + timedelta(days=1), zone))
        # each record carries the time zone of the site its person was placed on that day (one query: a subquery), so the page
        # shows the times on the site's clock
        placement = Posting.objects.filter(scope.covering(OuterRef('day')), employee=OuterRef('employee'))
        objects = objects.annotate(day=TruncDate('clock_in')).annotate(zone_name=Coalesce(
            Subquery(placement.values('production_department__site__timezone')[:1]),
            Subquery(placement.values('office_department__site__timezone')[:1]), Value('')))
        return objects, {'first': first, 'last': last}

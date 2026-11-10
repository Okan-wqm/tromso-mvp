from datetime import timedelta

from django.db.models import BooleanField, ExpressionWrapper, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core import audit, navigation
from core.crud import Mount, Resource
from core.dates import company_zone, read_day
from farm.models.site import zone_of
from farm.stock.dates import site_today

from .. import clock, rules, scope, services
from ..forms.attendance import AttendanceRecordForm
from ..models import AttendanceRecord, Posting, SchedulingSettings


class AttendanceRecordResource(services.PersonFirst, Resource):
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
    private_fields = tuple(services.PRIVATE_PUNCH)
    DAYS = 14

    @classmethod
    def menu_place(cls, mount=None):
        return navigation.page(cls.url_name('list', mount))

    @classmethod
    def queryset(cls):
        return super().queryset().select_related('employee__user')

    @classmethod
    def scoped(cls, request, objects):
        # the day that decides who sees a stretch is the company's (a site's clock per person would need its posting first;
        # the company's zone is the farm's, and never the server's UTC: a stretch from 00:30 is that day's)
        day = TruncDate('clock_in', tzinfo=company_zone())
        return scope.by_day(request.user, objects.annotate(clocked_day=day), 'employee', 'clocked_day',
                            scope.realm_for(request))

    @classmethod
    def snapshot(cls, record):
        """What the log keeps of a stretch: what the person's own clock-in keeps (services.PUNCH_FIELDS), so also who
        made it (`via`, which the form sets and never shows: a stretch a lead closed by hand says so in the log)."""
        return audit.snapshot(record, services.PUNCH_FIELDS, private=services.PRIVATE_PUNCH)

    @classmethod
    def after_save(cls, request, record, created):
        """The employment rule again under the person's lock (the form checked it before any lock)."""
        services.lock_employed(record.employee, services.punch_day(record.employee, record.clock_in),
                               services.punch_day(record.employee, record.clock_out) if record.clock_out else None)

    @classmethod
    def allowed(cls, request, obj, action):
        return not services.own_record(request.user, obj.employee)

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
        first = read_day(request.GET.get('from', ''), request) or today - timedelta(days=cls.DAYS)
        last = read_day(request.GET.get('to', ''), request) or today
        # whole days on the company's clock: the list is a log of stretches, not a day's roster. A stretch still open
        # runs on through the days asked for, so it is listed whenever it began: a forgotten clock-out is closed here,
        # however old it is (the page says which they are, by the one rule: hr.rules.forgotten_before).
        zone = zone_of(None)
        objects = objects.filter(Q(clock_in__gte=clock.start_of_day(first, zone)) | Q(clock_out__isnull=True),
                                 clock_in__lt=clock.start_of_day(last + timedelta(days=1), zone))
        too_old = rules.forgotten_before(timezone.now(), SchedulingSettings.get().forgotten_after_hours)
        objects = objects.annotate(forgotten=ExpressionWrapper(Q(clock_out__isnull=True, clock_in__lt=too_old),
                                                               output_field=BooleanField()))
        # each record carries the time zone of the site its person was placed on that day (one query: a subquery), so the page
        # shows the times on the site's clock
        placement = Posting.objects.filter(scope.covering(OuterRef('day')), employee=OuterRef('employee'))
        objects = objects.annotate(day=TruncDate('clock_in', tzinfo=company_zone())).annotate(zone_name=Coalesce(
            Subquery(placement.values('production_department__site__timezone')[:1]),
            Subquery(placement.values('office_department__site__timezone')[:1]), Value('')))
        return objects, {'first': first, 'last': last}

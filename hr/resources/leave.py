from datetime import timedelta

from django.db.models import Case, Q, Value, When
from django.utils.translation import gettext_lazy as _

from core.crud import Mount, Resource
from farm.stock.dates import site_today

from .. import leave, read, scope, services
from ..forms.leave import LeaveRequestForm, LeaveTypeForm
from ..models import LeaveRequest, LeaveType, SchedulingSettings
from ..models.leave import LeaveStatus

TABS = [('pending', _('Pending')), ('approved', _('Approved')), ('rejected', _('Rejected')), ('all', _('All'))]


class LeaveTypeResource(Resource):
    """The kinds of leave (a hidden menu entry, reached from Scheduling settings): owner data, none seeded."""

    model = LeaveType
    form_class = LeaveTypeForm
    name, plural = _('leave type'), _('leave types')
    url_prefix = 'hr/settings/leave-types'
    search_fields = ['name', 'code']
    list_template = 'hr/leave_type_list.html'
    icon = 'calendar-off'


class LeaveRequestResource(Resource):
    """Leave requests. Everyone with Read sees their own team's requests (`scoped`); a request's person and dates are the
    team lead's to see, its type only the person's, a decider's (Edit) and Everyone's, its reason only the person's and the
    holders of Everyone's. Edit also approves, rejects and cancels
    (the matrix has no extra column): the decision is `hr.services.decide_leave`, never the form. Nobody deletes a request:
    a wrong one is cancelled."""

    model = LeaveRequest
    form_class = LeaveRequestForm
    name, plural = _('leave request'), _('leave requests')
    url_prefix = 'hr/leave'
    mounts = (Mount(scope.PRODUCTION, 'production/team/leave'),)
    actions = ('add', 'change')
    list_template = 'hr/leave_list.html'
    detail_template = 'hr/leave_detail.html'
    icon = 'calendar-off'
    private_fields = ('reason', 'decision_note')

    @classmethod
    def queryset(cls):
        return super().queryset().select_related('employee__user', 'leave_type', 'decided_by')

    @classmethod
    def after_save(cls, request, item, created):
        """The employment rule again under the person's lock (the form checked it before any lock)."""
        services.lock_employed(item.employee, item.first_day, item.last_day)

    @classmethod
    def scoped(cls, request, objects):
        """The team's requests, each marked with whether the viewer may read its type (`type_shown`): the search reads the
        mark, so a search for a type finds only the requests whose type the viewer sees."""
        objects = scope.by_day(request.user, objects, 'employee', 'first_day', scope.realm_for(request))
        if cls.sees_every_type(request.user):
            return objects.annotate(type_shown=Value(True))
        return objects.annotate(type_shown=Case(When(employee__user=request.user, then=Value(True)), default=Value(False)))

    @classmethod
    def sees_every_type(cls, user):
        """Whether the user may read the type (sick, annual) of every request they reach: a holder of Everyone, or who may
        decide them (Edit), to replace a shift. Anyone else reads only the type of their own requests: a type is health
        data when it says sick, and a reader without the right to decide has no need of it."""
        return user.has_perm(scope.ALL) or user.has_perm(cls.perm('change'))

    @classmethod
    def form(cls, request, *args, **kwargs):
        kwargs.setdefault('user', request.user)
        kwargs.setdefault('realm', scope.realm_for(request))
        return cls.form_class(*args, **kwargs)

    @classmethod
    def search(cls, objects, query):
        return objects.filter(Q(employee__employee_number__icontains=query) | Q(employee__first_name__icontains=query)
                              | Q(employee__last_name__icontains=query) | Q(employee__user__username__icontains=query)
                              | Q(leave_type__name__icontains=query, type_shown=True))

    LIMIT = 200       # the requests of a tab shown at once; the page says how many there are

    @classmethod
    def filter_list(cls, request, objects):
        tab = request.GET.get('tab', 'pending')
        if tab not in dict(TABS):
            tab = 'pending'
        everything = objects
        if tab != 'all':
            objects = objects.filter(status=tab)
        total = objects.count()
        shown = list(objects.order_by('first_day', 'employee__last_name')[:cls.LIMIT])
        counts = {name: everything.filter(status=name).count() for name in ('pending', 'approved', 'rejected')}
        return cls.shown(request, shown), {'tabs': TABS, 'tab': tab, 'counts': counts, 'total': total,
                                           'limit': cls.LIMIT, 'all_count': sum(counts.values()) +
                                           everything.filter(status='cancelled').count()}

    @classmethod
    def shown(cls, request, requests):
        """Each request with what the viewer may do and see, in a fixed number of queries: the charge in days (the holidays
        and the people's sites read once), the reason (the person's and Everyone's only) and the buttons. The requests are
        the viewer's team's already (`scoped`), so the team is not asked again per row."""
        everyone = request.user.has_perm(scope.ALL)
        sees_types = cls.sees_every_type(request.user)
        sites = read.sites_of([(item.employee_id, item.first_day) for item in requests])
        holidays = leave.holiday_table([item.first_day for item in requests], [item.last_day for item in requests])
        weekdays = SchedulingSettings.get().working_weekdays
        can_edit = request.user.has_perm('hr.change_leaverequest')
        rows = []
        for item in requests:
            own = item.employee.user_id == request.user.pk
            rows.append({
                'request': item,
                'days': leave.leave_days(item.first_day, item.last_day, sites[(item.employee_id, item.first_day)],
                                         weekdays, holidays),
                'show_reason': own or everyone,
                'show_type': own or sees_types,
                'can_decide': can_edit and not own and item.status == LeaveStatus.PENDING,
                'can_cancel': services.can_cancel(request.user, item, listed=True,
                                                  today=site_today(sites[(item.employee_id, item.first_day)])),
                'can_shorten': item.first_day < item.last_day and services.can_correct(request.user, item, listed=True),
                'shorten_to': item.last_day - timedelta(days=1),          # the latest new last day the service takes
            })
        return rows

    @classmethod
    def detail_extras(cls, request, item):
        return {'row': cls.shown(request, [item])[0]}

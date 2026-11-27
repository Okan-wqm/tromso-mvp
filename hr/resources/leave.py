from datetime import timedelta

from django.db.models import Case, Q, Value, When
from django.utils.translation import gettext_lazy as _

from django.template.defaultfilters import floatformat

from core import listprops as L
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
    search_placeholder = _('Search by name or code')
    empty_text = _('A leave type is a kind of leave, such as annual or parental leave. Add the types the company uses.')

    @classmethod
    def list_rows(cls, view, objects, context):
        return {'columns': [L.column('type', _('Leave type')), L.column('days', _('Days a year'), numeric=True),
                            L.column('approval', _('Needs approval')), L.column('status', _('Status'))],
                'rows': [L.row(kind.pk, {
                    'type': L.title(view, context, kind, kind.name, sub=[kind.code]),
                    'days': L.cell(floatformat(kind.annual_days, '-2') if kind.annual_days is not None else _('No limit')),
                    'approval': L.cell(_('Yes') if kind.needs_approval else _('No')),
                    'status': L.cell(chip=L.chip(L.STATUS_CHIP.get(kind.status, 'neutral'), kind.get_status_display())),
                }, L.edit_delete(view, context, kind, kind.name)) for kind in objects]}


class LeaveRequestResource(services.PersonFirst, Resource):
    """Leave requests. Everyone with Read sees their own team's requests (`scoped`); a request's person and dates are the
    team lead's to see, its type only the person's, a decider's (Edit) and Everyone's, its reason only the person's and the
    holders of Everyone's. Edit also approves, rejects and cancels
    (the matrix has no extra column): the decision is `hr.services.decide_leave`, never the form. Nobody deletes a request:
    a wrong one is cancelled. Every write is hr.services' (file_leave, change_leave and the decisions): the tab reads the
    form and hands it over."""

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
    service_writes = True

    @classmethod
    def queryset(cls):
        return super().queryset().select_related('employee__user', 'leave_type', 'decided_by')

    @classmethod
    def create_record(cls, request, form):
        values = form.cleaned_data
        return services.file_leave(request.user, values['employee'], values['leave_type'], values['first_day'],
                                   values['last_day'], values.get('reason', ''))

    @classmethod
    def change_record(cls, request, form, current):
        values = form.cleaned_data
        return services.change_leave(request.user, current, values['leave_type'], values['first_day'], values['last_day'],
                                     values['reason'] if 'reason' in form.fields else services.KEEP)

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
        the viewer's team's already (`scoped`), and which of them the viewer decides is asked once, by the one rule
        (hr.services.deciders_of), and handed to the questions of each row."""
        sees_types = cls.sees_every_type(request.user)
        decided_here = services.deciders_of(request.user, requests)
        holidays = leave.holiday_table([item.first_day for item in requests], [item.last_day for item in requests])
        placed = read.placements({item.employee_id for item in requests}, min(
            (item.first_day for item in requests), default=None), max((item.last_day for item in requests), default=None)
        ) if requests else {}
        weekdays = SchedulingSettings.get().working_weekdays
        rows = []
        for item in requests:
            own = item.employee.user_id == request.user.pk
            rows.append({
                'request': item,
                'days': leave.leave_days(item.first_day, item.last_day, placed[item.employee_id], weekdays, holidays),
                'show_reason': scope.sees_reason(request.user, item.employee),
                'show_type': own or sees_types,
                'can_decide': services.can_decide(request.user, item, decider=item.pk in decided_here),
                'can_cancel': services.can_cancel(
                    request.user, item, decider=item.pk in decided_here,
                    today=site_today(read.site_of_day(placed[item.employee_id], item.first_day))),
                'can_shorten': item.first_day < item.last_day and services.can_correct(
                    request.user, item, decider=item.pk in decided_here),
                'shorten_to': item.last_day - timedelta(days=1),          # the latest new last day the service takes
            })
        return rows

    @classmethod
    def detail_extras(cls, request, item):
        return {'row': cls.shown(request, [item])[0]}

    # --- the list in the new look (core/listprops.py), the words of hr/leave_list.html ------------------------------
    search_placeholder = _('Search by name or type')
    empty_text = _('Requests for leave of your team appear here, with who may approve them.')
    STATUS_CHIPS = {LeaveStatus.PENDING: 'hold', LeaveStatus.APPROVED: 'ok', LeaveStatus.REJECTED: 'critical'}

    @classmethod
    def list_rows(cls, view, objects, context):
        from django.urls import reverse
        from django.utils import formats
        from django.utils.text import Truncator

        from core.crud import mount_of, mounted_name
        request = view.request
        route = lambda name, pk: reverse(mounted_name(f'hr:leaverequest_{name}', mount_of(request)), args=[pk])  # noqa: E731
        day = lambda value: formats.date_format(value, 'DATE_FORMAT')     # noqa: E731
        counts = {**context['counts'], 'all': context['all_count']}
        rows = []
        for row in objects:
            item = row['request']
            decided = (item.decided_by.get_full_name() or item.decided_by.get_username()) if item.decided_by                 else _('Granted at once') if item.decided_at else '–'
            actions = []
            if row['can_decide']:
                actions += [L.link(route('approve', item.pk), _('Approve'), 'user-check'),
                            L.link(route('reject', item.pk), _('Reject'), 'x', danger=True)]
            if row['can_cancel']:
                actions.append(L.post(route('cancel', item.pk), _('Cancel the request'), 'calendar-off',
                                      [('next', request.get_full_path())], danger=True))
            rows.append(L.row(item.pk, {
                'employee': L.cell(item.employee.full_name, href=route('detail', item.pk), strong=True,
                                   sub=[Truncator(item.reason).chars(80)] if row['show_reason'] and item.reason else []),
                'type': L.cell(item.leave_type.name if row['show_type'] else '–'),
                'days': L.cell(f'{day(item.first_day)} – {day(item.last_day)}'),
                'charged': L.cell(floatformat(row['days'], '-2')),
                'status': L.cell(chip=L.chip(cls.STATUS_CHIPS.get(item.status, 'neutral'), item.get_status_display())),
                'decided': L.cell(decided),
            }, actions))
        return {
            'tabs': L.tabs(_('Status'), [(f'?tab={key}', label, counts[key], context['tab'] == key)
                                         for key, label in context['tabs']]),
            'lines': [_('Showing %(limit)s of %(total)s requests.') % {'limit': context['limit'], 'total': context['total']}]
            if context['total'] > context['limit'] else [],
            'columns': [L.column('employee', _('Employee')), L.column('type', _('Leave type')), L.column('days', _('Days')),
                        L.column('charged', _('Charged'), numeric=True), L.column('status', _('Status')),
                        L.column('decided', _('Decided by'))],
            'rows': rows}

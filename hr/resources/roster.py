from datetime import date

from django.contrib import messages
from django.utils.translation import gettext_lazy as _

from core import audit
from core.crud import Mount, Resource
from farm.stock.dates import site_today

from .. import read, rules, scope, services, units
from ..forms.roster import ShiftAssignmentForm
from ..models import ShiftAssignment


def parse_day(value):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


class ShiftAssignmentResource(Resource):
    """The Shift schedule: a week of the team as a table, one cell per person and day. A cell opens the plan of that
    person and day (a dialog; the list's create route takes `?employee=&day=` for an empty one). The rows are the people
    the viewer reaches (`scoped`, and per day for the week read, hr.scope.visible_days); the rules run on every save
    (hr.rules, through hr.services.evaluate)."""

    model = ShiftAssignment
    form_class = ShiftAssignmentForm
    name, plural = _('plan'), _('plans')
    url_prefix = 'hr/schedule'
    mounts = (Mount(scope.PRODUCTION, 'production/team/schedule'),)
    list_template = 'hr/roster.html'
    icon = 'calendar'
    private_fields = ('note',)

    @classmethod
    def queryset(cls):
        return super().queryset().select_related('employee__user', 'shift')

    @classmethod
    def scoped(cls, request, objects):
        return scope.by_day(request.user, objects, 'employee', 'day', scope.realm_for(request))

    @classmethod
    def allowed(cls, request, obj, action):
        return not services.self_plan(request.user, obj.employee)

    @classmethod
    def form(cls, request, *args, **kwargs):
        kwargs.setdefault('user', request.user)
        kwargs.setdefault('realm', scope.realm_for(request))
        if not args and kwargs.get('instance') is None and request.method == 'GET':
            kwargs.setdefault('initial', {key: request.GET[key] for key in ('employee', 'day') if key in request.GET})
        return cls.form_class(*args, **kwargs)

    @classmethod
    def list_queryset(cls, request):
        start = parse_day(request.GET.get('week')) or site_today(None)
        department = units.find(request.GET.get('department', ''))
        try:
            page = int(request.GET.get('page', '1'))
        except ValueError:
            page = 1
        return read.week(request.user, start, department, page, query=request.GET.get('q', '').strip(),
                         realm=scope.realm_for(request))

    @classmethod
    def search(cls, objects, query):
        return objects          # the search is part of the week's read (it narrows the people)

    @classmethod
    def filter_list(cls, request, objects):
        week = objects
        return week.rows, {'week': week, 'departments': units.choices(kinds=[scope.realm_for(request)]),
                           'chosen_department': request.GET.get('department', ''),
                           'shifts': cls.shifts(), 'crew': cls.crew(request, week)}

    CREW = 'hr.crew_shiftassignment'

    @classmethod
    def crew(cls, request, week):
        """The Crew block under the viewer's own week: in Production › Team, for a holder of Crew (hr.read.crew_week)."""
        if scope.realm_for(request) != scope.PRODUCTION or not request.user.has_perm(cls.CREW):
            return None
        return read.crew_week(request.user, week.start)

    @classmethod
    def shifts(cls):
        from ..models import Shift
        return Shift.objects.filter(status='active')

    @classmethod
    def snapshot(cls, assignment):
        """The cell, and the warnings the plan was saved with (their codes, as the rules name them): a lead who goes on past
        a warning leaves it in the log."""
        values = super().snapshot(assignment)
        warnings = getattr(assignment, 'warnings', [])
        if warnings:
            values['Warnings'] = [audit.message(rules.TEXT[code]) for code in sorted({w.code for w in warnings})]
        return values

    @classmethod
    def after_save(cls, request, assignment, created):
        for finding in getattr(assignment, 'warnings', []):
            messages.warning(request, rules.text(finding))

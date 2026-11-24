from django.contrib import messages
from django.utils.translation import gettext_lazy as _

from core import audit, listprops, query
from core.crud import Mount, Resource
from core.dates import read_day
from farm.stock.dates import site_today

from .. import read, rules, scope, services, units
from ..forms.roster import ShiftAssignmentForm
from ..models import Employee, ShiftAssignment


class ShiftAssignmentResource(services.PersonFirst, Resource):
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
        return not services.own_record(request.user, obj.employee)

    @classmethod
    def form(cls, request, *args, **kwargs):
        kwargs.setdefault('user', request.user)
        kwargs.setdefault('realm', scope.realm_for(request))
        if not args and kwargs.get('instance') is None and request.method == 'GET':
            kwargs.setdefault('initial', {key: request.GET[key] for key in ('employee', 'day') if key in request.GET})
        return cls.form_class(*args, **kwargs)

    @classmethod
    def list_queryset(cls, request):
        start = read_day(request.GET.get('week'), request) or site_today(None)
        department = units.find(request.GET.get('department', ''))
        page = query.number(request.GET.get('page', ''), least=1) or 1
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
        """The Crew block under the viewer's own week: in Production › Team, for a holder of Crew who is a worker (has an
        employee record: a crew is a worker's, so the platform admin gets none) (hr.read.crew_week)."""
        if scope.realm_for(request) != scope.PRODUCTION or not request.user.has_perm(cls.CREW):
            return None
        if not Employee.objects.filter(user=request.user).exists():
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
        services.lock_employed(assignment.employee, assignment.day)       # the employment rule under the person's lock
        for finding in getattr(assignment, 'warnings', []):
            messages.warning(request, rules.text(finding))

    # --- the new look (core.crud.ListView: list_template_next, list_next_props), the words of hr/roster.html ----------
    list_template_next = 'hr/roster_next.html'
    search_placeholder = _('Search by name or number')
    empty_text = _('The people of your team appear here with their plan for the week.')

    @classmethod
    def list_next_props(cls, view, objects, context):
        """The Shift schedule's island props (frontend/islands/pages/Roster.tsx): the week the classic page reads, its cells
        and words; a cell's plan and the empty day's "Plan this day" open the record's own page, not a dialog."""
        from django.middleware.csrf import get_token
        from django.template.defaultfilters import date as date_format, floatformat
        from django.urls import reverse
        from django.utils.http import urlencode
        from django.utils.translation import gettext as words

        from core.crud import mount_of, mounted_name
        request, week, L = view.request, context['week'], listprops

        def mounted(name, *args):
            return reverse(mounted_name(name, mount_of(request)), args=args)

        def hour(moment):
            return date_format(moment, 'TIME_FORMAT')

        def day_head(day):
            return {'key': day.isoformat(), 'head': date_format(day, 'D'), 'sub': date_format(day, 'MONTH_DAY_FORMAT')}

        chosen = context['chosen_department']
        tail = '&' + urlencode({'department': chosen}) if chosen else ''

        def cell(row, item):
            if not item.visible:
                return {'key': None}
            chip = None
            if item.state == 'leave':
                chip = {'kind': 'note', 'text': words('On leave'), 'title': (
                    words('%(shift)s planned: to be covered') % {'shift': item.shift.code}) if item.shift else None}
            elif item.state == 'shift':
                chip = {'kind': 'note', 'text': item.shift.code,
                        'title': f'{item.shift.name} {hour(item.shift.starts_at)}–{hour(item.shift.ends_at)}'}
            elif item.state == 'off':
                chip = {'kind': 'neutral', 'text': words('Off'), 'title': None}
            found = {'key': f'{row.employee.pk}:{item.day.isoformat()}', 'chip': chip, 'href': None, 'add': None,
                     'holiday': item.holiday.name if item.holiday else None,
                     'finding': item.finding_text or None, 'blocks': bool(item.blocks)}
            if item.assignment is not None and context['can_change'] and cls.allowed(request, item.assignment, 'change'):
                found['href'] = mounted('hr:shiftassignment_edit', item.assignment.pk)
            elif chip is None and context['can_add']:
                found['add'] = {'href': f"{mounted('hr:shiftassignment_create')}?employee={row.employee.pk}"
                                        f"&day={item.day.isoformat()}", 'label': words('Plan this day')}
            return found

        rows = [{'key': str(row.employee.pk), 'name': row.employee.full_name,
                 'sub': row.department.name if row.department else words('Not placed'),
                 'hours': floatformat(row.planned_hours, '-1'),
                 'hoursFinding': words('More than the standard week') if row.week_findings else None,
                 'cells': [cell(row, item) for item in row.cells]} for row in objects]
        paint = None
        if context['can_add'] or context['can_change'] or context['can_delete']:
            choices = [{'value': str(shift.pk), 'label': shift.code, 'title': shift.name} for shift in context['shifts']]
            choices.append({'value': 'off', 'label': words('Off'), 'title': None})
            if context['can_delete']:
                choices.append({'value': 'clear', 'label': words('Clear'), 'title': None})
            paint = {'action': mounted('hr:roster_plan'), 'csrfToken': get_token(request), 'next': request.get_full_path(),
                     'label': words('Paint'), 'choices': choices, 'clearSelection': words('Clear selection'),
                     'apply': words('Apply to the selected days')}
        text = words('%(shown)s of %(total)s people') % {'shown': week.shown, 'total': week.total}
        links = []
        if week.pages > 1:
            text = f"{text} · {words('Page')} {week.page}/{week.pages}"
            here = f'?week={week.start.isoformat()}'
            if week.page > 1:
                links.append({'href': f'{here}&page={week.page - 1}{tail}', 'label': words('Previous')})
            if week.page < week.pages:
                links.append({'href': f'{here}&page={week.page + 1}{tail}', 'label': words('Next')})
        crew = context.get('crew')
        crew_props = None
        if crew is not None:
            crew_props = {
                'title': words('Crew this week'), 'head': words('Colleague'), 'days': [day_head(day) for day in crew.days],
                'rows': [{'key': str(index), 'name': each.name, 'sub': str(each.department),
                          'cells': [{'kind': 'note', 'text': item.shift_code, 'sub': f'{hour(item.starts_at)}–{hour(item.ends_at)}'}
                                    if item else None for item in each.cells]} for index, each in enumerate(crew.rows)],
                'text': None if crew.rows else (words('Nobody else is placed in your department this week.') if crew.placed
                                                else words('You are not placed in a production department this week, '
                                                           'so you have no crew.'))}
        nothing = L.empty(view, context)
        return {
            'week': {'label': words('Week'),
                     'title': f"{date_format(week.start, 'DATE_FORMAT')} – {date_format(week.end, 'DATE_FORMAT')}",
                     'previous': {'href': f'?week={week.previous.isoformat()}{tail}', 'label': words('Previous week')},
                     'next': {'href': f'?week={week.next.isoformat()}{tail}', 'label': words('Next week')},
                     'print': words('Print')},
            'toolbar': L.toolbar(view, context, [L.choice('department', words('Department'), chosen,
                                                          [('', words('All departments'))], groups=context['departments'])],
                                 keep=[('week', week.start.isoformat())]),
            'line': {'text': text, 'links': links},
            'grid': {'label': str(cls.title(view.mount)), 'employeeHead': words('Employee'), 'hoursHead': words('Planned (h)'),
                     'days': [day_head(day) for day in week.days], 'rows': rows, 'paint': paint},
            'empty': None if rows else {'title': nothing['title'], 'text': nothing['text']},
            'crew': crew_props,
        }

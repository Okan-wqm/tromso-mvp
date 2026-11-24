"""The HR pages that are not a tab: the roster's batch plan (several cells at once), the decisions on a leave request, Today, the
team overview and the organisation chart. Each is served in Company › HR and again under Production › Team (core.crud.Mount):
the request carries the mount, the reads take its realm, and every link and return stays in it."""
import uuid

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _, ngettext
from django.views.decorators.http import require_POST

from core import navigation, query, stack
from core.crud import done, mount_of, mounted_name, render_page
from core.dates import read_day
from core.ui import is_next
from farm.models.site import zone_of
from farm.stock.dates import site_today

from . import read, rules, scope, services, units
from .models import Shift

OFF, CLEAR = 'off', 'clear'


def _here(request, url_name, *args):
    """The address of an HR route under the mount the request came by."""
    return reverse(mounted_name(url_name, mount_of(request)), args=args)


def _return(request, default):
    """Where a post goes back to: the page that sent it (`next`, an address of this site), else `default`. A foreign or
    malformed `next` is ignored."""
    back = request.POST.get('next', '')
    if back and url_has_allowed_host_and_scheme(back, allowed_hosts={request.get_host()},
                                                require_https=request.is_secure()):
        return back
    return default


def parse_cells(values):
    """[(employee id, day)] from 'employee id:YYYY-MM-DD' strings; None when one is malformed."""
    cells = []
    for value in values:
        employee, _separator, text = value.partition(':')
        day = read_day(text)                         # the one day parser: ISO, inside the window of dates
        try:
            cells.append((uuid.UUID(employee), day))
        except ValueError:
            return None
        if day is None:
            return None
    return cells


@require_POST
def plan(request):
    """Sets one shift, planned off or nothing on every cell sent (`cells`, repeated; `shift`: a shift's id, `off` or
    `clear`), all or none. A person the user does not reach (a forged id) is a 404 and writes nothing; a blocking finding
    refuses the batch with its first conflicts; warnings are told after the save. Someone with no right to plan is
    refused before the request is read."""
    if not services.can_plan(request.user):
        raise PermissionDenied
    cells = parse_cells(request.POST.getlist('cells'))
    if not cells:
        return HttpResponseBadRequest()
    choice = request.POST.get('shift', '')
    if choice == OFF:
        shift = None
    elif choice == CLEAR:
        shift = services.CLEAR
    else:
        try:
            shift = Shift.objects.get(pk=choice, status='active')
        except (Shift.DoesNotExist, ValueError, ValidationError):
            return HttpResponseBadRequest()
    reachable = {employee.pk: employee for employee in scope.team(request.user).filter(pk__in=[pk for pk, _day in cells])}
    if any(pk not in reachable for pk, _day in cells):
        raise Http404
    target = _return(request, _here(request, 'hr:shiftassignment_list'))
    try:
        warnings = services.plan_shifts(request.user, [(reachable[pk], day) for pk, day in cells], shift)
    except PermissionDenied:
        raise
    except ValidationError as error:
        for message in error.messages:
            messages.error(request, message)
        return redirect(target)
    except IntegrityError:
        messages.error(request, _('Someone planned one of these days at the same time. Look at the week again.'))
        return redirect(target)
    messages.success(request, ngettext('%(count)d day planned.', '%(count)d days planned.', len(cells))
                     % {'count': len(cells)})
    for employee, finding in warnings:
        messages.warning(request, f'{employee}: {rules.text(finding)}')
    return redirect(target)


# ---- leave: decide and cancel -------------------------------------------------------------------------------------
def leave_request(request, pk):
    """The request, if it is in the viewer's team: any other is a 404 (the same scope as every page of the tab)."""
    from .resources.leave import LeaveRequestResource
    if not request.user.has_perm('hr.view_leaverequest'):
        raise PermissionDenied
    return get_object_or_404(LeaveRequestResource.visible(request), pk=pk)


def _back(request):
    return done(request, _return(request, _here(request, 'hr:leaverequest_list')))


def _run(request, call, done_message):
    try:
        call()
    except ValidationError as error:
        messages.error(request, ' '.join(error.messages))
    except PermissionDenied:
        raise
    else:
        messages.success(request, done_message)
    return _back(request)


def approve(request, pk):
    """GET: the dialog that lists the person's planned shifts inside the request (hr.read.leave_impact), to replace them;
    POST: approves the request. The shifts never block the approval."""
    item = leave_request(request, pk)
    if request.method == 'POST':
        return _run(request, lambda: services.decide_leave(request.user, item, True, request.POST.get('note', '')),
                    _('The request was approved.'))
    if not services.can_decide(request.user, item):
        raise PermissionDenied
    return render_page(request, 'hr/leave_approve.html', {'object': item, 'title': _('Approve the request'),
                                                          'group': _('Leave requests'),
                                                          'impact': read.leave_impact(request.user, item)})


def reject(request, pk):
    """GET: the dialog asking for a note; POST: rejects the request with it."""
    item = leave_request(request, pk)
    if request.method == 'POST':
        return _run(request, lambda: services.decide_leave(request.user, item, False, request.POST.get('note', '')),
                    _('The request was rejected.'))
    if not services.can_decide(request.user, item):
        raise PermissionDenied
    return render_page(request, 'hr/leave_reject.html', {'object': item, 'title': _('Reject the request'),
                                                         'group': _('Leave requests')})


@require_POST
def shorten(request, pk):
    """A decider ends an approved leave earlier (hr.services.shorten_leave): `last_day`, the new last day, typed in the
    shared day box (core.dates.read_day says a text that is no day back to the person; nothing changes)."""
    item = leave_request(request, pk)
    last_day = read_day(request.POST.get('last_day', ''), request)
    if last_day is None:
        return _back(request)
    return _run(request, lambda: services.shorten_leave(request.user, item, last_day), _('The leave was shortened.'))


@require_POST
def cancel(request, pk):
    item = leave_request(request, pk)
    return _run(request, lambda: services.cancel_leave(request.user, item), _('The request was cancelled.'))


# ---- today & attendance -------------------------------------------------------------------------------------------
def _today_context(request):
    """The board, the person's own open stretch and, when it is a forgotten clock-out, what they are told instead of the
    buttons (services.forgotten_refusal); a forgotten row carries the address of its stretch for who may correct it."""
    own = services.own_employee(request.user)
    open_punch = services.open_stretch(own) if own else None
    open_zone = zone_of(read.site_on(own, site_today(None))) if open_punch else None
    refusal = services.forgotten_refusal(open_punch)
    board = read.board(request.user, realm=scope.realm_for(request))
    if request.user.has_perm('hr.change_attendancerecord'):
        for row in board.rows:
            if row.open_record is not None and not services.own_record(request.user, row.employee):
                row.close_url = _here(request, 'hr:attendancerecord_edit', row.open_record)
    return {'board': board, 'own': own, 'open_punch': open_punch, 'open_zone': open_zone,
            'forgotten': ' '.join(refusal.messages) if refusal is not None else '',
            'can_enter': request.user.has_perm('hr.add_attendancerecord'), 'states': rules.STATES}


# The board's tiles as the parts of the people planned today (each such person in exactly one: read.TILES), in the new
# look's stacked bar: their words (the tiles' msgids) and tones.
PLANNED_PARTS = (('upcoming', 'hold'), ('here', 'ok'), ('not_in', 'warning'), ('absent', 'critical'),
                 ('on_leave', 'note'), ('done', 'neutral'), ('forgotten', 'warning'))


def _tile_words():
    return {'upcoming': _('Upcoming'), 'here': _('Here now'), 'not_in': _('Not in yet'), 'absent': _('Absent'),
            'on_leave': _('On leave'), 'done': _('Done'), 'forgotten': _('Clock-out forgotten')}


def _today_next(request, context):
    """The new look's board (hr/_board_next.html): the classic board's context and the people planned today as a stacked
    bar of the board's own tiles, which add up to Planned today."""
    counts, words = {tile.key: tile.count for tile in context['board'].tiles}, _tile_words()
    tones = dict(PLANNED_PARTS)
    return {**context, 'planned_stack': stack.stack(
        _('Planned today'), [stack.part(key, words[key], counts.get(key, 0), tones[key]) for key, _tone in PLANNED_PARTS])}


def today(request):
    """Today & attendance: who is where now, worked out on each site's clock, with the person's own clock in and out. The
    new look (core.ui.is_next) is drawn by the server too (hr/today_next.html), so the one poll draws its board again."""
    if not request.user.has_perm('hr.view_attendancerecord'):
        raise PermissionDenied
    place = navigation.page(mounted_name('hr:today', mount_of(request)))
    context = {'title': place.entry.label, 'eyebrow': place.heading, 'base_template': 'app_base.html',
               **_today_context(request)}
    if is_next(request):
        return render(request, 'hr/today_next.html', _today_next(request, context))
    return render(request, 'hr/today.html', context)


def today_board(request):
    """The board alone, as the page polls it (frontend/poll.ts): the server draws every figure again, in the look the page
    is in (the cookie the poll sends)."""
    if not request.user.has_perm('hr.view_attendancerecord'):
        raise PermissionDenied
    if is_next(request):
        return render(request, 'hr/_board_next.html', _today_next(request, _today_context(request)))
    return render(request, 'hr/_board.html', _today_context(request))


@require_POST
def punch(request, direction):
    """The person's own clock in or clock out, at the server's time."""
    if direction not in ('in', 'out'):
        raise Http404
    call = services.clock_in if direction == 'in' else services.clock_out
    try:
        call(request.user)
    except ValidationError as error:
        messages.error(request, ' '.join(error.messages))
    else:
        messages.success(request, _('You are clocked in.') if direction == 'in' else _('You are clocked out.'))
    return redirect(_return(request, _here(request, 'hr:today')))


# ---- the team overview and the organisation chart ---------------------------------------------------------------
def team_overview(request):
    """Team overview: the viewer's people and their week in numbers (`?week=`, `?department=`, `?q=`, `?page=`)."""
    if not request.user.has_perm('hr.view_shiftassignment'):
        raise PermissionDenied
    start = read_day(request.GET.get('week'), request) or site_today(None)
    department = units.find(request.GET.get('department', ''))
    page = query.number(request.GET.get('page', ''), least=1) or 1
    searched = request.GET.get('q', '').strip()
    place = navigation.page(mounted_name('hr:overview', mount_of(request)))
    return render(request, 'hr/overview_next.html' if is_next(request) else 'hr/overview.html', {
        'title': place.entry.label, 'eyebrow': place.heading, 'base_template': 'app_base.html', 'query': searched,
        'overview': read.overview(request.user, start, department, page, query=searched, realm=scope.realm_for(request)),
        'departments': units.choices(kinds=[scope.realm_for(request)]),
        'chosen_department': units.token(department)})


def organisation_chart(request):
    """Organisation chart of the panel: Production's sites with their production departments, or Company's office departments
    with one Production box (hr.read.org_tree), nested, with managers and head counts the viewer may see. It is read with the
    permission of its menu entry: the office departments' in Company, the people's (hr.view_employee) in Production; the
    Production box links to Production's chart only for who may open it."""
    place = navigation.page(mounted_name('hr:orgchart', mount_of(request)))
    if not request.user.has_perm(place.entry.perm):
        raise PermissionDenied
    root = read.org_tree(request.user, scope.realm_for(request))
    production_chart = request.user.has_perm(navigation.page('hr:production_orgchart').entry.perm)
    context = {'title': place.entry.label, 'eyebrow': place.heading, 'base_template': 'app_base.html', 'root': root,
               'production_chart': production_chart}
    if is_next(request):
        return render(request, 'hr/orgchart_next.html', {**context, 'props': _org_props(root, production_chart)})
    return render(request, 'hr/orgchart.html', context)


def _org_node(node, production_chart, path):
    """One box of the organisation chart in words (hr/_org_node.html's), for the island's OrgTree."""
    kinds = {'site': _('Site'), 'production': _('Production'), 'production_root': _('Production'), 'office': _('Office')}
    if node.kind in ('site', 'production_root'):
        count = ngettext('%(total)s person', '%(total)s people', node.total) % {'total': node.total}
    else:
        count = ngettext('%(direct)s person', '%(direct)s people', node.direct) % {'direct': node.direct}
        if node.children:
            count = f"{count} · {_('%(total)s in all') % {'total': node.total}}"
    manager = None
    if node.manager is not None:
        manager = {'label': f"{_('Manager')}:", 'name': node.manager.get_full_name() or node.manager.get_username(),
                   'title': node.manager_title or None}
    key = f'{path}.{node.kind}:{getattr(node.obj, "pk", "") or node.label}'
    return {
        'key': key, 'kind': node.kind, 'kindLabel': str(kinds.get(node.kind, _('Office'))),
        'name': _('No site') if node.kind == 'site' and not node.label else str(node.label),
        'href': reverse('hr:production_orgchart') if node.kind == 'production_root' and production_chart else None,
        'manager': manager, 'count': count,
        'people': {'summary': ngettext('Show %(people)s person', 'Show %(people)s people', len(node.people))
                   % {'people': len(node.people)},
                   'list': [{'key': f'{key}.{index}', 'name': person.name, 'title': person.title or None}
                            for index, person in enumerate(node.people)]} if node.people else None,
        'children': [_org_node(child, production_chart, key) for child in node.children],
    }


def _org_props(root, production_chart):
    """The organisation chart's island props (frontend/islands/pages/OrgChart.tsx): the classic page's words."""
    return {
        'summary': _('%(total)s people you may see in the company.') % {'total': root.total},
        'print': _('Print'), 'cue': _('A wide chart scrolls sideways inside its frame.'), 'label': _('Organization chart'),
        'nodes': [_org_node(node, production_chart, '') for node in root.children],
        'empty': None if root.children else {'title': _('Nothing to show yet'),
                                             'text': _('Sites, production departments and office departments appear here.')},
    }

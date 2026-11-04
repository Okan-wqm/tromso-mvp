"""The HR pages that are not a tab: the roster's batch plan (several cells at once) and the decisions on a leave request."""
import uuid
from datetime import date

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _, ngettext
from django.views.decorators.http import require_POST

from core.crud import done, render_page

from . import rules, scope, services
from .models import Shift

OFF, CLEAR = 'off', 'clear'


def parse_cells(values):
    """[(employee id, day)] from 'employee id:YYYY-MM-DD' strings; None when one is malformed."""
    cells = []
    for value in values:
        employee, _separator, day = value.partition(':')
        try:
            cells.append((uuid.UUID(employee), date.fromisoformat(day)))
        except ValueError:
            return None
    return cells


@require_POST
def plan(request):
    """Sets one shift, planned off or nothing on every cell sent (`cells`, repeated; `shift`: a shift's id, `off` or
    `clear`), all or none. A person the user does not reach (a forged id) is a 404 and writes nothing; a blocking finding
    refuses the batch with its first conflicts; warnings are told after the save."""
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
    back = request.POST.get('next', '')
    target = back if url_has_allowed_host_and_scheme(back, allowed_hosts={request.get_host()}) \
        else reverse('hr:shiftassignment_list')
    try:
        warnings = services.plan_shifts(request.user, [(reachable[pk], day) for pk, day in cells], shift)
    except PermissionDenied:
        raise
    except ValidationError as error:
        for message in error.messages:
            messages.error(request, message)
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
    return done(request, reverse('hr:leaverequest_list'))


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


@require_POST
def approve(request, pk):
    item = leave_request(request, pk)
    return _run(request, lambda: services.decide_leave(request.user, item, True, request.POST.get('note', '')),
                _('The request was approved.'))


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
def cancel(request, pk):
    item = leave_request(request, pk)
    return _run(request, lambda: services.cancel_leave(request.user, item), _('The request was cancelled.'))

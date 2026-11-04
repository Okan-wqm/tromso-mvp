"""The HR pages that are not a tab: for now the roster's batch plan (several cells at once)."""
import uuid
from datetime import date

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _, ngettext
from django.views.decorators.http import require_POST

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

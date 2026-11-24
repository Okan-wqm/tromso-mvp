"""Company › Alarms › Alarms: every alarm, open ones first, with what happened to it (opened, notified, delivered or waiting,
escalated, acknowledged, cleared), and the console's Acknowledge. The pages say plainly that nothing is sent while no
transport is connected."""
import logging

from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from core import navigation
from core.crud import render_page
from core.dbgrid import PAGE_SIZE

from . import read, services
from .models import Alarm

READ = 'alarms.view_alarm'
STATES = ('open', 'all')
logger = logging.getLogger(__name__)


def _context(**extra):
    place = navigation.place(READ)
    return {'title': place.entry.label, 'eyebrow': place.heading,
            'connected': read.connected(), **extra}


def units_note(user):
    """What the Alarms page says of the units that need a look on the Monitoring screen, from the strip's own reading
    (alarms.read.attention, in core.ui.attention_words: no second judgement), so a person who comes from a red strip
    never finds an empty page: {'text', 'status', 'url' (Monitoring, '' for a person who may not open it), 'none_open'
    (no alarm is open at all, so none is open for them yet)}; {'failed': True} when the reading fails (logged); None
    when no unit needs a look."""
    from core import ui
    try:
        found = read.attention()
    except Exception:
        logger.exception('The units that need a look could not be read for the Alarms page.')
        return {'failed': True, 'url': reverse(ui.MONITORING) if ui.may_open(user, ui.MONITORING) else ''}
    words = [text for what, text in ui.attention_words(found) if what == ui.UNITS]
    if not words:
        return None
    return {'text': ' · '.join(words), 'status': 'critical' if found.critical else 'warning', 'none_open': not found.alarms,
            'url': reverse(ui.MONITORING) if ui.may_open(user, ui.MONITORING) else ''}


@permission_required(READ, raise_exception=True)
def alarm_list(request):
    state = request.GET.get('state', 'open')
    state = state if state in STATES else 'open'
    page = Paginator(read.listing(state), PAGE_SIZE).get_page(request.GET.get('page'))
    return render_page(request, 'alarms/alarm_list.html', _context(page=page, alarms=page.object_list, state=state,
                                                                   pager_query=f'state={state}',
                                                                   units_note=units_note(request.user)))


@permission_required(READ, raise_exception=True)
def alarm_detail(request, pk):
    alarm = get_object_or_404(Alarm.objects.select_related('site', 'production_department', 'point', 'sensor_event'),
                              pk=pk)
    events = read.history(alarm)
    mine = alarm.acknowledgements.filter(user=request.user).exists()
    return render_page(request, 'alarms/alarm_detail.html', _context(
        alarm=alarm, events=events, is_open=read.is_open(alarm), level=read.level(alarm),
        nobody=read.nobody_notified(alarm),
        can_acknowledge=not mine and read.may_acknowledge(request.user, alarm)))


@require_POST
@permission_required(READ, raise_exception=True)
def alarm_acknowledge(request, pk):
    """The console's acknowledgement (app 'console', no device): who holds Alarms: Edit, or a person it was sent to."""
    alarm = get_object_or_404(Alarm, pk=pk)
    if not read.may_acknowledge(request.user, alarm):
        raise PermissionDenied
    notification = alarm.notifications.filter(recipient=request.user).order_by('-level').first()
    try:
        services.acknowledge(alarm, request.user, app='console', notification=notification)
    except ValidationError as error:
        messages.error(request, ' '.join(error.messages))
    else:
        messages.success(request, _('Alarm acknowledged.'))
    return redirect(reverse('alarms:alarm_detail', args=[alarm.pk]))

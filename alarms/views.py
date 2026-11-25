"""Company › Alarms › Alarms: every alarm, open ones first, with what happened to it (opened, notified, delivered or waiting,
escalated, acknowledged, snoozed, cleared), the console's Acknowledge and Snooze; Company › Alarms › Alarm snoozes: every
snooze, newest first, and whether it is in force. The pages say plainly that nothing is sent while no transport is
connected."""
import logging
from datetime import timedelta
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.conf import settings
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from core import navigation
from core.crud import render_page
from core.dbgrid import PAGE_SIZE
from farm.stock.views import VIEW as MONITORING          # the monitoring wall's right: its live notice

from . import floods, read, services, watch
from .templatetags.alarm_watch import notice
from .rules import current as current_rules
from .models import Alarm, AlarmShelve

READ = 'alarms.view_alarm'
SNOOZES = 'alarms.view_alarmshelve'
STATES = ('open', 'all')
logger = logging.getLogger(__name__)


def _context(**extra):
    place = navigation.place(READ)
    return {'title': place.entry.label, 'eyebrow': place.heading,
            'connected': read.connected(), **extra}


def units_note(user):
    """What the Alarms page says of the units that need a look on the Monitoring screen, from the strip's own reading
    (alarms.read.attention, in core.ui.attention_words: no second judgement), so a person who comes from a red strip
    never finds an empty page: {'text', 'status', 'url' (Monitoring, '' for a person who may not open it), 'unalarmed'
    (how many of them have critical or warning water and no open water alarm at their own points: Attention.unalarmed;
    nothing is said of the rungs the engine never raises an alarm for)}; {'failed': True} when the reading fails
    (logged); None when no unit needs a look."""
    from core import ui
    try:
        found = read.attention()
    except Exception:
        logger.exception('The units that need a look could not be read for the Alarms page.')
        return {'failed': True, 'url': reverse(ui.MONITORING) if ui.may_open(user, ui.MONITORING) else ''}
    words = [text for what, text in ui.attention_words(found) if what == ui.UNITS]
    if not words:
        return None
    return {'text': ' · '.join(words), 'status': 'critical' if found.critical else 'warning', 'unalarmed': found.unalarmed,
            'url': reverse(ui.MONITORING) if ui.may_open(user, ui.MONITORING) else ''}


@permission_required(READ, raise_exception=True)
def alarm_list(request):
    state = request.GET.get('state', 'open')
    state = state if state in STATES else 'open'
    page = Paginator(read.listing(state), PAGE_SIZE).get_page(request.GET.get('page'))
    return render_page(request, 'alarms/alarm_list.html', _context(page=page, alarms=page.object_list, state=state,
                                                                   pager_query=f'state={state}',
                                                                   units_note=units_note(request.user),
                                                                   floods=floods.open_floods(current_rules()),
                                                                   worker=watch.state(), timings=settings.ALARM_WORKER))


@permission_required(READ, raise_exception=True)
def alarm_detail(request, pk):
    alarm = get_object_or_404(Alarm.objects.select_related('site', 'production_department', 'point', 'sensor_event'),
                              pk=pk)
    events = read.history(alarm)
    mine = alarm.acknowledgements.filter(user=request.user).exists()
    now = timezone.now()
    return render_page(request, 'alarms/alarm_detail.html', _context(
        alarm=alarm, events=events, is_open=read.is_open(alarm), level=read.level(alarm),
        nobody=read.nobody_notified(alarm),
        can_acknowledge=not mine and read.may_acknowledge(request.user, alarm),
        snooze=read.snoozes([alarm.pk], now).get(alarm.pk), can_snooze=request.user.has_perm(read.SHELVE),
        may_snooze=read.may_snooze(request.user, alarm, now),
        longest_snooze=current_rules().shelve_max(alarm.severity) // timedelta(minutes=1),
        water_url=_water_around(request, alarm)))


def _water_around(request, alarm):
    """In the new look, the water of the alarm's unit 12 hours each side of its opening (Tank › Water,
    `farm:tank_water?around=` the opening moment on the site's clock, dd.mm.yyyy HH:MM as the date box writes it), for a
    person who may read the water; '' for an alarm at no unit (a loop's, a device's) and in the classic look."""
    from django.utils import formats, timezone

    from core import ui
    from farm.models.site import zone_of
    from farm.models.water_point import site_of

    if not ui.is_next(request) or not request.user.has_perm('farm.view_watermeasurement'):
        return ''
    point = alarm.point or getattr(getattr(alarm.sensor_event, 'binding', None), 'point', None)
    if point is None or not point.unit_id:
        return ''
    opened = timezone.localtime(alarm.opened_at, zone_of(site_of(point.unit))).replace(tzinfo=None)
    return f"{reverse('farm:tank_water', args=[point.unit_id])}?{urlencode({'around': formats.localize_input(opened)})}"


@require_POST
@permission_required(READ, raise_exception=True)
def alarm_acknowledge(request, pk):
    """The console's acknowledgement (app 'console', no device): who holds Alarms: Edit, or a person it was sent to."""
    alarm = get_object_or_404(Alarm, pk=pk)
    try:
        services.acknowledge(alarm, request.user, app='console')
    except ValidationError as error:
        messages.error(request, ' '.join(error.messages))
    else:
        messages.success(request, _('Alarm acknowledged.'))
    return redirect(reverse('alarms:alarm_detail', args=[alarm.pk]))


@require_POST
@permission_required(read.SHELVE, raise_exception=True)
def alarm_snooze(request, pk):
    """Snoozes an open alarm for the minutes asked, saying why (alarms.services.shelve: its rules)."""
    alarm = get_object_or_404(Alarm, pk=pk)
    try:
        minutes = int(request.POST.get('minutes', ''))
    except ValueError:
        minutes = None
    try:
        services.shelve(alarm, request.user, minutes, request.POST.get('reason', ''))
    except ValidationError as error:
        messages.error(request, ' '.join(error.messages))
    else:
        messages.success(request, _('Alarm snoozed.'))
    return redirect(reverse('alarms:alarm_detail', args=[alarm.pk]))


@require_POST
@permission_required(read.SHELVE, raise_exception=True)
def alarm_snooze_end(request, pk):
    """Ends an alarm's snooze before its time."""
    alarm = get_object_or_404(Alarm, pk=pk)
    try:
        services.unshelve(alarm, request.user)
    except ValidationError as error:
        messages.error(request, ' '.join(error.messages))
    else:
        messages.success(request, _('Snooze ended: the alarm is notified and escalated again.'))
    return redirect(reverse('alarms:alarm_detail', args=[alarm.pk]))


@permission_required(SNOOZES, raise_exception=True)
def alarm_snoozes(request):
    """Every snooze, newest first, each with its alarm, who, until when, why, and whether it is in force."""
    place = navigation.place(SNOOZES)
    rows = AlarmShelve.objects.select_related('alarm', 'alarm__site', 'user', 'end', 'end__user')
    page = Paginator(rows, PAGE_SIZE).get_page(request.GET.get('page'))
    in_force = read.snoozes([row.alarm_id for row in page.object_list], timezone.now())
    return render_page(request, 'alarms/alarm_snoozes.html', {
        'title': place.entry.label, 'eyebrow': place.heading, 'page': page, 'snoozes': page.object_list,
        'in_force': {row.pk for row in in_force.values()}})


@permission_required(MONITORING, raise_exception=True)
def alarm_watch_notice(request):
    """The notice of whether the alarms are checked and sent (alarms/_watch_notice.html), asked for again by the
    monitoring wall (frontend/poll.ts), so a worker that stops is said there without a reload."""
    return render(request, 'alarms/_watch_notice.html', notice(sent_note=request.GET.get('sent_note') == '1'))


"""Company › Alarms › Alarms: every alarm, open ones first, with what happened to it (opened, notified, delivered or waiting,
escalated, acknowledged, snoozed, cleared), the console's Acknowledge and Snooze; Company › Alarms › Alarm snoozes: every
snooze, newest first, and whether it is in force. The pages say plainly that nothing is sent while no transport is
connected."""
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from core import navigation
from core.crud import render_page
from core.dbgrid import PAGE_SIZE

from . import floods, read, services
from .rules import current as current_rules
from .models import Alarm, AlarmShelve

READ = 'alarms.view_alarm'
SNOOZES = 'alarms.view_alarmshelve'
STATES = ('open', 'all')


def _context(**extra):
    place = navigation.place(READ)
    return {'title': place.entry.label, 'eyebrow': place.heading,
            'connected': read.connected(), **extra}


@permission_required(READ, raise_exception=True)
def alarm_list(request):
    state = request.GET.get('state', 'open')
    state = state if state in STATES else 'open'
    page = Paginator(read.listing(state), PAGE_SIZE).get_page(request.GET.get('page'))
    return render_page(request, 'alarms/alarm_list.html', _context(page=page, alarms=page.object_list, state=state,
                                                                   pager_query=f'state={state}',
                                                                   floods=floods.open_floods(current_rules())))


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
        longest_snooze=current_rules().shelve_max(alarm.severity) // timedelta(minutes=1)))


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

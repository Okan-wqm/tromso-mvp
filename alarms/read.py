"""Reading the alarms: whether one is open, acknowledged, at which level, whether anyone could be notified, a
notification's state, whether a transport is connected, who may acknowledge, and an alarm's history in time order. Every
state is read from the append-only rows, never stored. `attention`: what needs a look now, alarms and water together."""
from dataclasses import dataclass

from django.db.models import Count, Exists, Max, OuterRef, Q

from .models import (Acknowledgement, Alarm, AlarmClearance, Channel, DeliveryAttempt, Escalation, Notification,
                     Outcome)
from .rules import current as current_rules
from .transports import transport_for

ACKNOWLEDGE = 'alarms.change_alarm'
QUEUED, SENT, FAILED = 'queued', 'sent', 'failed'


def is_open(alarm):
    return not AlarmClearance.objects.filter(alarm=alarm).exists()


def acknowledged(alarm):
    return Acknowledgement.objects.filter(alarm=alarm).exists()


def level(alarm):
    """The level the alarm is at: 0, or the last level it was escalated to."""
    return Escalation.objects.filter(alarm=alarm).aggregate(top=Max('level'))['top'] or 0


def nobody_notified(alarm):
    """Whether no notification was queued for it at all: nobody to notify (no recipient rule reaches it)."""
    return not Notification.objects.filter(alarm=alarm).exists()


def status(notification):
    """'sent' once a transport took it, 'failed' after its severity's delivery attempts failed, else 'queued'."""
    attempts = DeliveryAttempt.objects.filter(notification=notification)
    if attempts.filter(outcome=Outcome.SENT).exists():
        return SENT
    failed = attempts.filter(outcome=Outcome.FAILED).count()
    return FAILED if failed >= current_rules().delivery_attempts(notification.alarm.severity) else QUEUED


def pending(rules):
    """The notifications still to be sent: none sent, fewer failures than their severity's delivery attempts."""
    waiting = (Notification.objects.annotate(sent=Exists(DeliveryAttempt.objects.filter(
        notification=OuterRef('pk'), outcome=Outcome.SENT)), failures=Count('attempts', filter=Q(
            attempts__outcome=Outcome.FAILED))).filter(sent=False)
        .select_related('alarm', 'recipient').order_by('queued_at', 'id'))
    return [notification for notification in waiting
            if notification.failures < rules.delivery_attempts(notification.alarm.severity)]


def transport_connected(channel):
    return transport_for(channel) is not None


def connected():
    """{channel: whether a transport is connected for it}, for the pages' notice that nothing is sent."""
    return {channel.value: transport_connected(channel.value) for channel in Channel}


def may_acknowledge(user, alarm):
    """Who may say they saw an alarm: who holds Alarms: Edit, or a person one of its notifications went to."""
    return user.has_perm(ACKNOWLEDGE) or Notification.objects.filter(alarm=alarm, recipient=user).exists()


def listing(state='open'):
    """The alarms for the page, open ones first, each with its state annotated; `state` 'open' or 'all'."""
    alarms = Alarm.objects.select_related('site', 'production_department', 'point', 'clearance').annotate(
        is_cleared=Exists(AlarmClearance.objects.filter(alarm=OuterRef('pk'))),
        acknowledgements_count=Count('acknowledgements', distinct=True),
        notifications_count=Count('notifications', distinct=True),
        top_level=Max('escalations__level'))
    if state == 'open':
        alarms = alarms.filter(is_cleared=False)
    return alarms.order_by('is_cleared', '-opened_at', '-id')


@dataclass(frozen=True)
class Event:
    at: object
    kind: str            # opened, notified, delivered, escalated, acknowledged, cleared
    row: object
    state: str = ''      # a notification's: queued, sent or failed


def history(alarm):
    """Everything that happened to an alarm, in time order."""
    events = [Event(alarm.opened_at, 'opened', alarm)]
    for notification in alarm.notifications.select_related('recipient', 'rule').prefetch_related('attempts'):
        events.append(Event(notification.queued_at, 'notified', notification, status(notification)))
        events += [Event(attempt.attempted_at, 'delivered', attempt) for attempt in notification.attempts.all()]
    events += [Event(escalation.escalated_at, 'escalated', escalation) for escalation in alarm.escalations.all()]
    events += [Event(ack.acknowledged_at, 'acknowledged', ack)
               for ack in alarm.acknowledgements.select_related('user', 'notification')]
    clearance = AlarmClearance.objects.filter(alarm=alarm).first()
    if clearance is not None:
        events.append(Event(clearance.cleared_at, 'cleared', clearance))
    order = ['opened', 'notified', 'delivered', 'escalated', 'acknowledged', 'cleared']
    return sorted(events, key=lambda event: (event.at, order.index(event.kind)))


@dataclass(frozen=True)
class Attention:
    """What needs a look now, for the new look's status strip (core/ui.py): the open alarms, and the live units' water as
    the alarm engine and the monitoring cards judge it this moment (farm/water/read.py `unit_water`, the one judge), so
    the strip never says "no open alarms" while a unit is critical but its alarm has not been raised yet (its on-delay, or
    no engine pass since). `blind`: units with fish whose water cannot be judged now (old values only, a value the chemistry
    core refuses, or no value at all in the window), only where there are fish; `unreadable`: the live values cannot be
    read."""
    alarms: int
    alarms_critical: int
    critical: int
    warning: int
    blind: int
    unreadable: bool

    @property
    def status(self):
        if self.alarms_critical or self.critical:
            return 'critical'
        if self.alarms or self.warning or self.blind or self.unreadable:
            return 'warning'
        return ''


def _attention_parts(now):
    """One read of everything `attention` counts: the open alarms (with their site), and every live unit's water as the
    alarm engine judges it (unit_water), the units with fish, and each unit's site."""
    from farm.models import Tank
    from farm.stock import read as stock_read
    from farm.water import read as water_read

    alarms = list(listing('open').values_list('site_id', 'severity'))
    units = list(Tank.objects.select_related('production_department'))
    found = water_read.unit_water(units, now)
    judged = {unit_id: water for unit_id, water in found.items() if water is not None and water.point is not None}
    # blind only where there are fish: an empty unit's old values put nobody at risk
    stocked = {pk for pk, fish in stock_read.unit_counts(list(judged)).items() if fish > 0} if judged else set()
    site_of = {unit.pk: unit.production_department.site_id if unit.production_department_id else None for unit in units}
    return alarms, found, judged, stocked, site_of


def _count(alarms, found, judged, stocked, keep=lambda _site: True, site_of=None):
    from farm.water.evaluate import Status

    site_of = site_of or {}
    mine = {unit_id: water for unit_id, water in judged.items() if keep(site_of.get(unit_id))}
    statuses = [water.status for water in mine.values()]
    open_here = [severity for site_id, severity in alarms if keep(site_id)]
    return Attention(alarms=len(open_here), alarms_critical=open_here.count('critical'),
                     critical=statuses.count(Status.CRITICAL), warning=statuses.count(Status.WARNING),
                     blind=sum(1 for unit_id, water in mine.items()
                               if unit_id in stocked and water.status in (Status.STALE, Status.UNEVALUATED, Status.NOT_MEASURED)),
                     unreadable=any(water.sensors_failed for unit_id, water in found.items()
                                    if water is not None and keep(site_of.get(unit_id))))


def attention(now=None, site=None):
    """What needs a look now (Attention), on every site or on `site` (a Site or its id): the open alarms there and the
    water of its live units as the alarm engine judges it now. The one reader of "open alarms" for the new look's strip,
    an overview's Open alarms tile and a site's count: never a second count of them."""
    alarms, found, judged, stocked, site_of = _attention_parts(now)
    if site is None:
        return _count(alarms, found, judged, stocked)
    site_id = getattr(site, 'pk', site)
    return _count(alarms, found, judged, stocked, keep=lambda each: each == site_id, site_of=site_of)


def attention_by_site(now=None):
    """{site id: Attention} of every site with a live unit or an open alarm, from one read (`attention` per site, for a
    list of sites); an alarm or a unit without a site is under None."""
    alarms, found, judged, stocked, site_of = _attention_parts(now)
    sites = {*site_of.values(), *(site_id for site_id, _severity in alarms)}
    return {site_id: _count(alarms, found, judged, stocked, keep=lambda each, wanted=site_id: each == wanted, site_of=site_of)
            for site_id in sites}

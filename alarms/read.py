"""Reading the alarms: whether one is open, acknowledged, at which level, whether anyone could be notified, a
notification's state, whether a transport is connected, who may acknowledge, and an alarm's history in time order. Every
state is read from the append-only rows, never stored. `attention`: what needs a look now, alarms and water together."""
import logging
from dataclasses import dataclass

from django.db.models import Count, Exists, Max, OuterRef, Q

from .models import (Acknowledgement, Alarm, AlarmClearance, Channel, DeliveryAttempt, Escalation, Notification,
                     Outcome)
from .rules import current as current_rules
from .transports import transport_for

ACKNOWLEDGE = 'alarms.change_alarm'
QUEUED, SENT, FAILED = 'queued', 'sent', 'failed'
logger = logging.getLogger(__name__)


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
    """What needs a look now, for the new look's status strip (core/ui.py) and a page's open-alarms figure, on every site
    or on one: the open alarms and every stocked unit's water on the monitoring cards' own ladder (monitoring.read
    water_rungs, rungs 1 to 4: the cards and this never disagree), so it never says "no open alarms" while a unit is
    critical whose alarm is not raised yet, or a stocked unit is blind (an old or missing temperature or oxygen, no
    point at all) or unjudged (no limit for its fish).
    `farm_wide`: the open alarms that belong to no site (the live values cannot be read, an alarm step failed, the rules
    incomplete); a site's count holds them too, as they are about every site. `unreadable`: units whose water could not
    be read at all (each read on its own, as the engine does), never counted as fine. `units`: (unit id, rung) of each
    stocked unit, for a caller (and the tests) to compare with the cards."""
    alarms: int = 0
    alarms_critical: int = 0
    farm_wide: int = 0
    critical: int = 0
    warning: int = 0
    blind: int = 0
    unjudged: int = 0
    unreadable: int = 0
    units: tuple = ()

    @property
    def status(self):
        if self.alarms_critical or self.critical:
            return 'critical'
        if self.alarms or self.warning or self.blind or self.unjudged or self.unreadable:
            return 'warning'
        return ''

    @property
    def quiet(self):
        """Nothing open, and every stocked unit OK or a note on the cards: the only case "No open alarms" may be said."""
        return not self.status


UNREADABLE = 'unreadable'
CACHE_KEY = 'alarms.read.attention'


def open_alarms():
    """[(site id or None, severity)] of the open alarms (not cleared: listing('open')'s rule, without its annotations)."""
    return list(Alarm.objects.filter(~Exists(AlarmClearance.objects.filter(alarm=OuterRef('pk'))))
                .values_list('site_id', 'severity'))


def _unit_water(units, now):
    """{unit id: [PointWater]} of the units' points (the middle one first), and [the ids of the units that could not be
    read]: one read for all of them; when it fails, each unit on its own (a savepoint each), so one unit that cannot be
    read never hides the others (as alarms/sources.py `_read` does for the engine)."""
    from django.db import transaction

    from farm.water import read as water_read
    try:
        with transaction.atomic():
            return water_read.points_water(units, now, middle_only=[unit.pk for unit in units]), []
    except Exception:
        logger.exception('The water of the units could not be read at once; each unit is read on its own.')
    found, failed = {}, []
    for unit in units:
        try:
            with transaction.atomic():
                found.update(water_read.points_water([unit], now, middle_only=[unit.pk]))
        except Exception:
            logger.exception('The water of unit %s could not be read.', unit)
            failed.append(unit.pk)
    return found, failed


def snapshot(now=None):
    """(open alarms, [(unit id, site id, rung)] of every stocked unit): what `attention` counts, read once. Without `now`
    it is kept for settings.ATTENTION_CACHE_SECONDS (the same for every viewer: it depends on no one's rights), so a
    farm's open pages ask the database once in that time, not once each."""
    from django.conf import settings
    from django.core.cache import cache

    seconds = settings.ATTENTION_CACHE_SECONDS
    if now is None and seconds:
        kept = cache.get(CACHE_KEY)
        if kept is not None:
            return kept
    found = _snapshot(now)
    if now is None and seconds:
        cache.set(CACHE_KEY, found, seconds)
    return found


def _snapshot(now):
    from django.utils import timezone

    from farm.models import Tank
    from farm.stock import read as stock_read
    from monitoring import read as monitoring_read

    now = now or timezone.now()
    units = list(Tank.objects.select_related('production_department'))
    held = stock_read.stock_of(units) if units else {}
    stocked = [unit for unit in units if unit.pk in held]
    water, failed = _unit_water(stocked, now) if stocked else ({}, [])
    rungs = []
    for unit in stocked:
        site = unit.production_department.site_id if unit.production_department_id else None
        if unit.pk in failed:
            rungs.append((unit.pk, site, UNREADABLE))
            continue
        middle = monitoring_read.middle_of(water.get(unit.pk, ()))
        rungs.append((unit.pk, site, monitoring_read.water_rungs(middle, now).key))
    return open_alarms(), rungs


def _count(alarms, rungs, site=None, every=True):
    keep = (lambda each: True) if every else (lambda each: each == site)
    here = [severity for each, severity in alarms if keep(each) or each is None]
    mine = [(unit, rung) for unit, each, rung in rungs if keep(each)]
    keys = [rung for _unit, rung in mine]
    return Attention(alarms=len(here), alarms_critical=here.count('critical'),
                     farm_wide=sum(1 for each, _severity in alarms if each is None),
                     critical=keys.count('critical'), warning=keys.count('warning'), blind=keys.count('blind'),
                     unjudged=keys.count('unjudged'), unreadable=keys.count(UNREADABLE), units=tuple(mine))


def attention_all(now=None):
    """(the farm's Attention, {site id: Attention}) from ONE reading of the water (`snapshot`, kept for every viewer): what
    a page that shows the farm and its sites (the company overview) asks once. Each site's count holds the farm-wide
    alarms too (`farm_wide` says how many of its alarms they are); a site with no stocked unit and no alarm of its own is
    not listed (`attention(site=...)` gives it, the farm-wide alarms only). A unit or an alarm on no site is in the farm's
    figure only."""
    alarms, rungs = snapshot(now)
    sites = {each for _unit, each, _rung in rungs if each is not None} | {each for each, _severity in alarms if each is not None}
    return _count(alarms, rungs), {each: _count(alarms, rungs, each, every=False) for each in sites}


def attention(now=None, site=None):
    """What needs a look now (Attention), on every site, or on `site` (a Site or its id): the open alarms there, the
    farm-wide ones with them, and its stocked units on the cards' ladder. The one reader of the open alarms for the new
    look's strip, a page's open-alarms figure and a site's count."""
    if site is None:
        return attention_all(now)[0]
    alarms, rungs = snapshot(now)
    return _count(alarms, rungs, getattr(site, 'pk', site), every=False)


def attention_by_site(now=None):
    """{site id: Attention} of every site with a stocked unit or an open alarm (`attention_all`'s second half)."""
    return attention_all(now)[1]


def opened_at(points, start, end, system=None):
    """The alarms opened from `start` to before `end` at these sampling points: a water limit's at the point, a sensor
    rule's on a channel bound there, and with `system` a rule's on a channel bound to the system itself; oldest first.
    The alarms a unit's or a system's water history marks (Tank › Water, System › Water)."""
    here = Q(point__in=points) | Q(sensor_event__binding__point__in=points)
    if system is not None:
        here |= Q(sensor_event__binding__system=system)
    return Alarm.objects.filter(here, opened_at__gte=start, opened_at__lt=end).order_by('opened_at')

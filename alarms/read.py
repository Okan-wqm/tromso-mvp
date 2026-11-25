"""Reading the alarms: whether one is open, acknowledged, at which level, whether anyone could be notified, a
notification's state, whether a transport is connected, who may acknowledge, and an alarm's history in time order. Every
state is read from the append-only rows, never stored. `attention`: what needs a look now, alarms and water together."""
import logging
from dataclasses import dataclass

from django.db.models import Count, Exists, Max, OuterRef, Q, Subquery
from django.utils import timezone

from .models import (Acknowledgement, Alarm, AlarmClearance, AlarmShelve, Channel, DeliveryAttempt, Escalation,
                     Notification, OutboxEntry,
                     Outcome)
from .rules import current as current_rules
from .transports import transport_for

ACKNOWLEDGE = 'alarms.change_alarm'
SHELVE = 'alarms.add_alarmshelve'
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
    """'sent' once a transport took it (or a flood message covered it); 'failed' once its severity's delivery attempts
    failed, for a critical alarm's only once the alarm is acknowledged or cleared (alarms/outbox.py: until then it is
    tried again); else 'queued'."""
    attempts = DeliveryAttempt.objects.filter(notification=notification)
    if attempts.filter(outcome__in=[Outcome.SENT, Outcome.GROUPED]).exists():
        return SENT
    if not OutboxEntry.objects.filter(notification=notification).exists():
        return FAILED                          # given up: its attempts used up, or its alarm cleared before the first
    failed = attempts.filter(outcome=Outcome.FAILED).count()
    alarm = notification.alarm
    persists = alarm.severity == 'critical' and is_open(alarm) and not acknowledged(alarm)
    return FAILED if failed >= current_rules().delivery_attempts(alarm.severity) and not persists else QUEUED


def transport_connected(channel):
    return transport_for(channel) is not None


def connected():
    """{channel: whether a transport is connected for it}, for the pages' notice that nothing is sent."""
    return {channel.value: transport_connected(channel.value) for channel in Channel}


def may_acknowledge(user, alarm):
    """Who may say they saw an alarm: who holds Alarms: Edit, or a person one of its notifications went to."""
    return user.has_perm(ACKNOWLEDGE) or Notification.objects.filter(alarm=alarm, recipient=user).exists()


def _in_force(now):
    """The snoozes in force at `now`: begun, not past their `until`, not ended by then."""
    return (Q(shelved_at__lte=now, until__gt=now)
            & ~Q(pk__in=AlarmShelve.objects.filter(end__ended_at__lte=now).values('pk')))


def snoozes(alarm_ids, now):
    """{alarm id: its snooze in force at `now`}."""
    return {row.alarm_id: row for row in AlarmShelve.objects.filter(_in_force(now), alarm__in=alarm_ids)
            .select_related('user')}


def ended(alarm_ids, now):
    """{alarm id: its last snooze that has ended by `now`} (its time out, or ended early)."""
    found = {}
    for row in AlarmShelve.objects.filter(alarm__in=alarm_ids, shelved_at__lte=now).select_related('end'):
        if row.ends_at() <= now and (row.alarm_id not in found or row.ends_at() > found[row.alarm_id].ends_at()):
            found[row.alarm_id] = row
    return found


def resumed(alarm_ids, now):
    """{alarm id: when its last snooze ended}, for the alarms a snooze of which has ended by `now`: their escalation
    time is counted again from then."""
    return {alarm_id: row.ends_at() for alarm_id, row in ended(alarm_ids, now).items()}


def may_snooze(user, alarm, now=None):
    """Whether `user` may snooze the alarm now (Alarm snoozes: Create; an open alarm with none in force)."""
    from .health import OWN_HEALTH
    return (user.has_perm(SHELVE) and is_open(alarm) and not (alarm.source == 'system' and alarm.parameter in OWN_HEALTH)
            and alarm.pk not in snoozes([alarm.pk], now or timezone.now()))


def listing(state='open', now=None):
    """The alarms for the page, open ones first, each with its state annotated (and until when it is snoozed, if it
    is); `state` 'open' or 'all'."""
    now = now or timezone.now()
    alarms = Alarm.objects.select_related('site', 'production_department', 'point', 'clearance').annotate(
        is_cleared=Exists(AlarmClearance.objects.filter(alarm=OuterRef('pk'))),
        acknowledgements_count=Count('acknowledgements', distinct=True),
        notifications_count=Count('notifications', distinct=True),
        top_level=Max('escalations__level'),
        snoozed_until=Subquery(AlarmShelve.objects.filter(_in_force(now), alarm=OuterRef('pk')).values('until')[:1]))
    if state == 'open':
        alarms = alarms.filter(is_cleared=False)
    return alarms.order_by('is_cleared', '-opened_at', '-id')


@dataclass(frozen=True)
class Event:
    at: object
    kind: str            # opened, notified, delivered, escalated, acknowledged, snoozed, snooze_ended, cleared
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
    for shelve in alarm.shelves.select_related('user', 'end', 'end__user'):
        events.append(Event(shelve.shelved_at, 'snoozed', shelve))
        if getattr(shelve, 'end', None) is not None:
            events.append(Event(shelve.end.ended_at, 'snooze_ended', shelve.end))
    clearance = AlarmClearance.objects.filter(alarm=alarm).first()
    if clearance is not None:
        events.append(Event(clearance.cleared_at, 'cleared', clearance))
    order = ['opened', 'notified', 'delivered', 'escalated', 'acknowledged', 'snoozed', 'snooze_ended', 'cleared']
    return sorted(events, key=lambda event: (event.at, order.index(event.kind)))


@dataclass(frozen=True)
class Attention:
    """What needs a look now, for the new look's status strip (core/ui.py) and a page's open-alarms figure, on every site
    or on one: the open alarms, and every stocked unit on rungs 1 to 4 of the monitoring cards' own ladder by the one
    rule the cards apply (monitoring.read.upper_state: its water, its stock over capacity, an estimate that says weigh
    now), so it never says "no open alarms" while a unit is critical whose alarm is not raised yet, over capacity, due to
    be weighed now, blind (an old or missing temperature or oxygen, no point at all) or unjudged (no limit for its fish).
    It is worked out with every section shown, as a card is for a person who may read them all (a person who may not
    read the water sees no blind or unjudged card); the notes (a withdrawal, weigh soon, an open health event) are not
    counted.
    `farm_wide`: the open alarms that belong to no site (the live values cannot be read, an alarm step failed, the rules
    incomplete); a site's count holds them too, as they are about every site. `unreadable`: units whose water could not
    be read at all (each read on its own, as the engine does), whose feeding could not be read (unless their water is
    critical), or whose state could not be worked out: never counted as fine. `units`: (unit id, rung) of each
    stocked unit, for a caller (and the tests) to compare with the cards. `unalarmed`: the stocked units whose water is
    critical or past a warning (the rungs the engine raises a water alarm for) with no open water alarm at their own
    points; nothing is said of a rung the engine never raises an alarm for (blind, no limit, over capacity, weigh now)."""
    alarms: int = 0
    alarms_critical: int = 0
    farm_wide: int = 0
    critical: int = 0
    warning: int = 0
    blind: int = 0
    unjudged: int = 0
    unreadable: int = 0
    units: tuple = ()
    unalarmed: int = 0

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
    """[(site id or None, severity, unit id of its point or None)] of the open alarms (not cleared: listing('open')'s rule,
    without its annotations). A water alarm's point is the unit's own middle point (alarms/sources.py), so its unit is
    the unit it is about."""
    return list(Alarm.objects.filter(~Exists(AlarmClearance.objects.filter(alarm=OuterRef('pk'))))
                .values_list('site_id', 'severity', 'point__unit_id'))


def _each(what, units, read):
    """({unit id: what `read(units)` says of it}, [the ids of the units it could not be read for]): one read for all of
    them; when it fails, each unit on its own (a savepoint each), so one unit that cannot be read never hides the others
    (as alarms/sources.py `_read` does for the engine). `what` names it in the log."""
    from django.db import transaction

    try:
        with transaction.atomic():
            return read(units), []
    except Exception:
        logger.exception('The %s of the units could not be read at once; each unit is read on its own.', what)
    found, failed = {}, []
    for unit in units:
        try:
            with transaction.atomic():
                found.update(read([unit]))
        except Exception:
            logger.exception('The %s of unit %s could not be read.', what, unit)
            failed.append(unit.pk)
    return found, failed


def _unit_water(units, now):
    """{unit id: [PointWater]} of the units' points (the middle one first), and [the ids of the units that could not be
    read] (`_each`)."""
    from farm.water import read as water_read
    return _each('water', units, lambda some: water_read.points_water(some, now, middle_only=[unit.pk for unit in some]))


def _unit_feeding(units, held):
    """{unit id: UnitFeeding with today's ration} (farm.feeding.read.figures, as the cards read it), and [the ids of the
    units it could not be read for] (`_each`): what says whether a unit's estimate needs weighing now."""
    from farm.feeding import read as feeding_read
    return _each('feeding', units, lambda some: feeding_read.figures({unit.pk: held[unit.pk] for unit in some},
                                                                       ration=True))


def snapshot(now=None):
    """(open alarms, [(unit id, site id, rung, whether its water is critical or past a warning)] of every stocked unit): what `attention` counts, read once. Without `now`
    it is kept for settings.ATTENTION_CACHE_SECONDS, so a farm's open pages ask the database once in that time, not
    once each. It is read through the sealed managers (the units, the alarms), so it is kept per what the person reads
    (core.sealing.reach_key: one copy for everyone from whom nothing is hidden, one per set of hidden work): a count
    made for a lead is never served to an outsider, nor an outsider's to the people who keep the fish (review L3)."""
    from django.conf import settings
    from django.core.cache import cache

    from core import sealing

    seconds = settings.ATTENTION_CACHE_SECONDS
    key = ':'.join(filter(None, (CACHE_KEY, sealing.reach_key())))
    if now is None and seconds:
        kept = cache.get(key)
        if kept is not None:
            return kept
    found = _snapshot(now)
    if now is None and seconds:
        cache.set(key, found, seconds)
    return found


def _snapshot(now):
    from django.utils import timezone

    from farm.models import Tank
    from farm.stock import read as stock_read

    now = now or timezone.now()
    units = list(Tank.objects.select_related('production_department__site'))
    held = stock_read.stock_of(units) if units else {}
    stocked = [unit for unit in units if unit.pk in held]
    water, failed = _unit_water(stocked, now) if stocked else ({}, [])
    feeding, unfed = _unit_feeding(stocked, held) if stocked else ({}, [])
    rungs = []
    for unit in stocked:
        site = unit.production_department.site_id if unit.production_department_id else None
        rungs.append((unit.pk, site, *_rung(unit, held[unit.pk], water, feeding, failed, unfed, now)))
    return open_alarms(), rungs


def _rung(unit, own, water, feeding, failed, unfed, now):
    """(the rung of one stocked unit, whether its water is critical or past a warning: what the engine raises a water alarm
    for). The rung is monitoring.read.upper_state's, OK below it, or UNREADABLE: its water could not be read, its feeding
    could not be read and its water is not critical, or working it out raised (logged). Each unit on its own, so one never
    hides the others and the strip never answers 500 for one."""
    from farm.stock.dates import local_today
    from monitoring import read as monitoring_read

    if unit.pk in failed:
        return UNREADABLE, False
    try:
        rungs = monitoring_read.water_rungs(monitoring_read.middle_of(water.get(unit.pk, ())), now)
        watered = bool(rungs.critical or rungs.warning)
        if unit.pk in unfed and not rungs.critical:
            return UNREADABLE, watered
        drift = monitoring_read.weigh(monitoring_read.lines_of(own, feeding.get(unit.pk), local_today(unit)))
        state = monitoring_read.upper_state(rungs, own.over_capacity, drift)
    except Exception:
        logger.exception('The state of unit %s could not be worked out.', unit)
        return UNREADABLE, False
    return (state.key if state is not None else monitoring_read.OK), watered


def _count(alarms, rungs, site=None, every=True):
    keep = (lambda each: True) if every else (lambda each: each == site)
    here = [severity for each, severity, _unit in alarms if keep(each) or each is None]
    mine = [(unit, rung) for unit, each, rung, _watered in rungs if keep(each)]
    keys = [rung for _unit, rung in mine]
    alarmed = {unit for _each, _severity, unit in alarms if unit is not None}
    return Attention(alarms=len(here), alarms_critical=here.count('critical'),
                     farm_wide=sum(1 for each, _severity, _unit in alarms if each is None),
                     unalarmed=sum(1 for unit, each, _rung, watered in rungs
                                   if keep(each) and watered and unit not in alarmed),
                     critical=keys.count('critical'), warning=keys.count('warning'), blind=keys.count('blind'),
                     unjudged=keys.count('unjudged'), unreadable=keys.count(UNREADABLE), units=tuple(mine))


def attention_all(now=None):
    """(the farm's Attention, {site id: Attention}) from ONE reading of the water (`snapshot`, kept for every viewer): what
    a page that shows the farm and its sites (the company overview) asks once. Each site's count holds the farm-wide
    alarms too (`farm_wide` says how many of its alarms they are); a site with no stocked unit and no alarm of its own is
    not listed (`attention(site=...)` gives it, the farm-wide alarms only). A unit or an alarm on no site is in the farm's
    figure only."""
    alarms, rungs = snapshot(now)
    sites = ({each for _unit, each, _rung, _watered in rungs if each is not None}
             | {each for each, _severity, _unit in alarms if each is not None})
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

"""Alarm floods (ISA-18.2's alarm flood; the owner's burst requirement: many alarms at once must not become as many
messages to one person). Grouping happens in the outbox only (alarms/outbox.py): every alarm is still raised in its own
pass, kept, listed, acknowledged and escalated on its own, so grouping changes how many messages a person gets, never
whether or when an alarm opens.

- **The kind of an alarm** (`key`): its site, its severity, and what it is about: a water quantity (the dissolved oxygen
  in mg/L and in % one), a sensor alarm rule, or a check of the alarm system (each failed step a check of its own). 24 tanks of one site losing oxygen at
  once are one kind; a pH alarm beside them is another.
- **For one person, one channel** (`plan`), per kind in a round of the outbox: when its due notifications, with the ones
  of that kind already sent to that person within the severity's flood window, are at least the severity's flood count
  (Alarm severity rules: 3 within 120 s by default), they go out as ONE flood message (the transport is given the
  first with `flood`: how many alarms, since when, an example) and each is written sent or failed as part of it
  (`flood_size`). Within the window after a flood message, the next of that kind for that person is covered by it:
  written "grouped", never sent on its own nor again. After the window the count starts again.
- **The pages** show a flood of open alarms above the list (`open_floods`): at least the flood count of one kind, each
  opened within the flood window of the one before."""
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from .models import Alarm, AlarmClearance, DeliveryAttempt, Outcome, Source
from .sources import STEP_FAILED, slot_of

EACH, FLOOD, COVERED = 'each', 'flood', 'covered'


def key(alarm):
    """The kind of an alarm: site, severity and what it is about (a sensor rule's alarm needs its event loaded)."""
    if alarm.source == Source.WATER_LIMIT:
        about = f'water:{slot_of(alarm.parameter)}'
    elif alarm.source == Source.SENSOR_RULE:
        about = f'rule:{alarm.sensor_event.rule_id}'
    elif alarm.parameter == STEP_FAILED:
        about = f'system:{alarm.parameter}:{alarm.summary}'          # each failed step its own kind (its name says it)
    else:
        about = f'system:{alarm.parameter}'
    return f'{alarm.site_id or "-"}|{alarm.severity}|{about}'


@dataclass(frozen=True)
class Recent:
    """What a person got of one kind within its window: how many notifications, and the last flood message's time."""

    count: int = 0
    last_flood_at: datetime | None = None


def recent(groups, now, rules):
    """{(recipient id, channel, key): Recent} for the groups of a round ({(recipient id, channel, key): [notifications]}):
    one query, the attempts of those people sent or covered within the longest window, each group counted in its own
    severity's window."""
    if not groups:
        return {}
    windows = {group: rules.flood_window(members[0].alarm.severity) for group, members in groups.items()}
    earliest = now - max(windows.values())
    counted = defaultdict(set)
    last = {}
    for recipient, channel, kind, notification, at, size, outcome in DeliveryAttempt.objects.filter(
            outcome__in=[Outcome.SENT, Outcome.GROUPED], attempted_at__gte=earliest, attempted_at__lte=now,
            notification__recipient__in={group[0] for group in groups}).values_list(
            'notification__recipient', 'notification__channel', 'flood_key', 'notification', 'attempted_at',
            'flood_size', 'outcome'):
        group = (recipient, channel, kind)
        if group not in windows or now - at > windows[group]:
            continue
        counted[group].add(notification)
        if size is not None and outcome == Outcome.SENT:
            last[group] = max(at, last.get(group, at))
    return {group: Recent(len(counted[group]), last.get(group)) for group in groups}


def plan(members, found, now, rules):
    """How a group's due notifications go out this round: EACH on its own, as one FLOOD message, or COVERED by the
    flood message sent to that person within the window."""
    severity = members[0].alarm.severity
    if found.last_flood_at is not None and now - found.last_flood_at < rules.flood_window(severity):
        return COVERED
    if found.count + len(members) >= rules.flood_count(severity):
        return FLOOD
    return EACH


@dataclass(frozen=True)
class OpenFlood:
    """A flood of open alarms of one kind, for the pages."""

    size: int
    since: datetime
    alarms: list


def open_floods(rules):
    """The floods among the open alarms, largest first: runs of at least the flood count of one kind, each opened
    within the flood window of the one before."""
    by_kind = defaultdict(list)
    for alarm in (Alarm.objects.exclude(pk__in=AlarmClearance.objects.values('alarm'))
                  .select_related('sensor_event', 'site').order_by('opened_at', 'id')):
        by_kind[key(alarm)].append(alarm)
    found = []
    for alarms in by_kind.values():
        severity = alarms[0].severity
        run = [alarms[0]]
        for alarm in alarms[1:] + [None]:
            if alarm is not None and alarm.opened_at - run[-1].opened_at <= rules.flood_window(severity):
                run.append(alarm)
                continue
            if len(run) >= rules.flood_count(severity):
                found.append(OpenFlood(len(run), run[0].opened_at, run))
            run = [alarm]
    return sorted(found, key=lambda flood: (-flood.size, flood.since))

"""Alarm floods (ISA-18.2's alarm flood; the owner's burst requirement: many alarms at once must not become as many
messages to one person). Grouping happens in the outbox only (alarms/outbox.py): every alarm is still raised in its own
pass, kept, listed, acknowledged and escalated on its own, so grouping changes how many messages a person gets, never
whether or when an alarm opens.

- **The kind of an alarm** (`key`): its site, its severity, and what it is about: a water quantity (the dissolved oxygen
  in mg/L and in % one), a sensor alarm rule, or a check of the alarm system (each failed step a check of its own). 24 tanks of one site losing oxygen at
  once are one kind; a pH alarm beside them is another.
- **A warning, for one person, one channel** (`plan`), per kind in a round of the outbox: when its due notifications,
  with the ones of that kind already sent to that person within the warning's flood window, are at least the flood count
  (Alarm severity rules: 3 within 120 s by default), they go out as ONE flood message (the transport is given the first
  with `flood`: how many alarms, since when, an example) and each is written sent or failed as part of it
  (`flood_size`). Within the window after a flood message of open alarms, the next warning of that kind for that person
  is covered by it: written "grouped", never sent on its own nor again. A flood message that said its alarms had cleared
  covers nothing. After the window the count starts again.
- **A critical is batched, never covered** (the coordinator's bar on the last recheck, 2026-11-24: no known way to drop or
  delay an open or newly cleared critical). The first critical of a kind for a person goes at once, on its own. The
  next ones of that kind for that person are collected while a message of the kind went to them less than the
  critical rule's follow-up time ago (Alarm severity rules: "Follow-up after", 5 s by default, at most 8 s), and then go
  as ONE follow-up message that names every one of them (its summary names the unit) and says how many of them are open
  now (`Flood.listed`); one alone goes with its own text. So each reaches the person at most the follow-up time after it
  was queued, and a person gets at most one message of a kind in that time. Ones that are due in the same round as the
  first go with it: the first on its own, the rest as one follow-up message.
- **The pages** show a flood of open alarms above the list (`open_floods`): at least the flood count of one kind, each
  opened within the flood window of the one before."""
import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from sensors.models.alarm import Severity

from .models import OPEN, Alarm, DeliveryAttempt, Outcome, Source
from .sources import STEP_FAILED, slot_of


def _digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def key(alarm):
    """The kind of an alarm: site, severity and what it is about (a sensor rule's alarm needs its event loaded)."""
    if alarm.source == Source.WATER_LIMIT:
        about = f'water:{slot_of(alarm.parameter)}'
    elif alarm.source == Source.SENSOR_RULE:
        about = f'rule:{alarm.sensor_event.rule_id}'
    elif alarm.parameter == STEP_FAILED:                              # each failed step its own kind (its name says it),
        about = f'system:{alarm.parameter}:{_digest(alarm.summary)}'  # a digest, so the stored key is never cut (R6)
    else:
        about = f'system:{alarm.parameter}'
    return f'{alarm.site_id or "-"}|{alarm.severity}|{about}'


@dataclass(frozen=True)
class Recent:
    """What a person got of one kind lately: how many notifications within its severity's window, the last flood
    message's time (a warning's covers the next ones), and the last time a message of the kind was sent to them (a
    critical's next ones wait the follow-up time after it)."""

    count: int = 0
    last_flood_at: datetime | None = None
    last_sent_at: datetime | None = None


def recent(groups, now, rules):
    """{(recipient id, channel, key): Recent} for the groups of a round ({(recipient id, channel, key): [notifications]}):
    one query, the attempts of those people sent or covered within the longest window (or the critical follow-up time,
    if longer), each group counted in its own severity's window."""
    if not groups:
        return {}
    windows = {group: rules.flood_window(members[0].alarm.severity) for group, members in groups.items()}
    earliest = now - max(max(windows.values()), rules.follow_up(Severity.CRITICAL))
    counted = defaultdict(set)
    last, sent = {}, {}
    for recipient, channel, kind, notification, at, size, outcome, cleared_at in DeliveryAttempt.objects.filter(
            outcome__in=[Outcome.SENT, Outcome.GROUPED], attempted_at__gte=earliest, attempted_at__lte=now,
            notification__recipient__in={group[0] for group in groups}).values_list(
            'notification__recipient', 'notification__channel', 'flood_key', 'notification', 'attempted_at',
            'flood_size', 'outcome', 'notification__alarm__clearance__cleared_at'):
        group = (recipient, channel, kind)
        if group not in windows:
            continue
        if outcome == Outcome.SENT:
            sent[group] = max(at, sent.get(group, at))
        if now - at > windows[group]:
            continue
        counted[group].add(notification)
        # Only a flood message about open alarms covers the next ones: one that said "cleared" (its alarm cleared by
        # then) never does, so the next real alarm of the kind is sent (N1, probe T17).
        if size is not None and outcome == Outcome.SENT and (cleared_at is None or cleared_at > at):
            last[group] = max(at, last.get(group, at))
    return {group: Recent(len(counted[group]), last.get(group), sent.get(group)) for group in groups}


@dataclass(frozen=True)
class Plan:
    """How a group's due notifications go out this round: `each` on its own, `flood` as one message (a warnings' flood
    message, or a criticals' follow-up naming each), `covered` by the flood message sent within the window (warnings
    only), `held` for the follow-up (criticals only: never longer than the follow-up time after the last message)."""

    each: list = field(default_factory=list)
    flood: list = field(default_factory=list)
    covered: list = field(default_factory=list)
    held: list = field(default_factory=list)


def plan(members, found, now, rules):
    """The Plan of a group's due notifications (in the backlog's order: an open critical first), given what the person
    got of that kind lately (`found`, a Recent)."""
    severity = members[0].alarm.severity
    if severity == Severity.CRITICAL:
        if found.last_sent_at is not None and now - found.last_sent_at < rules.follow_up(severity):
            return Plan(held=list(members))
        first, rest = ([], list(members)) if found.count else (list(members[:1]), list(members[1:]))
        return Plan(each=first + rest) if len(rest) < 2 else Plan(each=first, flood=rest)
    if found.last_flood_at is not None and now - found.last_flood_at < rules.flood_window(severity):
        return Plan(covered=list(members))
    if found.count + len(members) >= rules.flood_count(severity):
        return Plan(flood=list(members))
    return Plan(each=list(members))


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
    for alarm in Alarm.objects.filter(OPEN).select_related('sensor_event', 'site').order_by('opened_at', 'id'):
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

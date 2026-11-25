"""The outbox's delivery (alarms.Notification, alarms.DeliveryAttempt): each queued notification handed to its channel's
transport (alarms/transports.py), outside any alarm pass, transaction or lock, so a slow or failing transport never
delays an alarm: the alarm worker's sender thread goes through the outbox every tick (alarms/worker.py), and
manage.py run_alarms after its one pass.

- **What, in which order.** The outbox's queue (alarms.OutboxEntry: what is still to be sent, written with each
  notification and removed once it is sent, covered or given up, so a round reads what waits, never the whole history):
  the critical ones first, then the oldest queued.
- **What is said.** Each notification goes with its `text`, in the person's language: the severity and the summary; a
  critical alarm that has cleared by the time it is sent (it came and went while the transport was down or failing: an
  oxygen crash, a power cut) says it was critical and has cleared, when it opened and when it cleared. A warning whose
  alarm cleared before it was ever tried is given up instead, its attempt saying why.
- **A critical is never given up until someone has seen it** (the review of the worker, F1; N7 of the last recheck). A
  critical alarm's notification is tried again until it is sent or its alarm is acknowledged: clearing does not end its
  retries (a critical that came and went while the push service failed is exactly what the people on call must hear
  afterwards). The wait doubles from its severity's "Retry after" up to its severity's escalation time. Once its alarm
  is acknowledged it has its severity's delivery attempts like a warning's. A warning's has its attempts, its "Retry
  after" apart, then it is failed and its alarm's page says so (read.status). Given-up ones leave the queue
  (services.give_up).
- **Said when it cannot be delivered.** A critical notification of an unacknowledged alarm (open or cleared) that has
  failed and waited longer than its severity's escalation time is undeliverable: the round counts them
  (`Delivery.undeliverable`,
  on the worker's row), the pages' notice and the health check say so (alarms/watch.py), and the pass raises a critical
  alarm of the alarm system (`undeliverable`, sources.supervise).
- **A critical is never behind a round of warnings** (F5). A round sends the criticals' groups first, then the summaries
  of old cleared criticals (D8c), then the warnings' groups. It ends at its deadline (`round_seconds`), and before each
  warning's group it looks whether a critical was queued since it began: then it ends, and the next round, a tick
  later, starts with the critical. At worst a critical waits for the one send under way (`timeout`).
- **Snoozed.** A notification of an alarm that is snoozed waits, and goes out once the snooze ends; the word that it was
  snoozed goes out at once.
- **Floods.** The due warnings of one kind of alarm for one person go out as one flood message once they are a flood,
  and the next ones within the flood window are covered by it. A critical is never covered: the first of a kind goes at
  once, the next ones as one follow-up message naming each, at most the critical rule's follow-up time later
  (alarms/floods.py).
  Words about a snooze go out each on its own.
- **Never lost; at worst twice.** A restart, a crash or a database outage finds the queue as it was and sends it. A
  process that dies after the transport took one and before its attempt was written sends it again when it runs again:
  at least once, never lost (the transport has the notification's id for the push service's collapse key, so a phone
  shows it once). A notification is never written "sent" twice (a unique constraint), and two senders (an operator's
  run_alarms beside the worker) never send one at the same moment: each claims it with an advisory lock and looks again
  whether it went before sending.
- **An error of its own.** A notification whose handling raises (its text, its kind, its due check, its group's plan)
  gets a failed attempt, at most one per its severity's "Retry after" (never one a tick), so it is retried, used up and
  said undeliverable like any failure; one that went before the error gets none.
- **Bounded.** A send has `timeout` seconds (settings.ALARM_WORKER send_timeout for the worker); a transport that has
  not answered by then is a failed attempt ("no answer in N s"), tried again like any other. A transport that raises
  is a failed attempt with its error. A transport must not use the database (it runs on a thread of its own).
- **Channels.** Each notification goes to the transport of its own channel (settings.ALARM_TRANSPORTS); a second
  channel (e-mail, SMS) joins as a Channel value and a transport, and its notifications are queued, retried, grouped and
  given up by the same rules."""
import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from django.conf import settings
from django.db import connection
from django.db.models import Count, Exists, Max, Min, OuterRef, Q, Subquery
from django.utils import timezone, translation
from django.utils.translation import gettext as _

from sensors.models.alarm import Severity

from . import floods, read, rules as alarm_rules, services
from .models import (RANK, Acknowledgement, AlarmClearance, Channel, DeliveryAttempt, Notification, NotificationKind,
                     Outcome, OutboxEntry)
from .transports import Failed, Flood, Sent, transport_for

logger = logging.getLogger(__name__)
CLAIM = 426_160_720           # the advisory lock class of a notification being sent (with its id): an identity
# How many cleared warnings a round gives up, after its sending, each chunk one transaction: about 100 ms of work, so a
# backlog of them never delays a critical (the next round, a tick later, takes what is left).
GIVE_UP_CHUNK = 100
# A critical alarm that cleared this long before a transport could first send it (the first connection of a channel, or
# a long outage) is not told on its own: all of them go to the person as one summary, "see the alarm log" (the
# coordinator's decision on the recheck, 2026-11-24).
SUMMARY_AFTER = timedelta(hours=24)
FIRST_TRY = 'not sent: its alarm had cleared before the first attempt'
STALE_WORD = 'not sent: its alarm has cleared, so the word about its snooze is no longer true'


@dataclass
class Delivery:
    """What one round through the outbox did."""

    sent: int = 0
    failed: int = 0
    waiting: int = 0            # no transport is connected for their channel
    retrying: int = 0           # failed before, tried again once their retry time has passed
    busy: int = 0               # another sender was sending them
    snoozed: int = 0            # their alarm is snoozed: they wait until the snooze ends
    grouped: int = 0            # covered by a flood message sent to the same person within the window
    floods: int = 0             # flood messages handed to a transport (each counts its notifications as sent or failed)
    held: int = 0               # criticals collected for their kind's follow-up message (alarms/floods.py)
    given_up: int = 0           # left the queue unsent: their attempts used up
    deferred: int = 0           # left for the next round: its deadline came, or a critical was queued meanwhile
    backlog: int = 0            # all the notifications still to be sent when the round began
    oldest: datetime | None = field(default=None)
    undeliverable: int = 0      # critical ones of open, unacknowledged alarms failing longer than the escalation time
    undeliverable_since: datetime | None = field(default=None)

    def __str__(self):
        text = f'{self.sent} sent, {self.failed} failed'
        if self.floods or self.grouped:
            text += f' ({self.floods} flood messages, {self.grouped} covered by one)'
        if self.held:
            text += f', {self.held} critical held for a follow-up message'
        if self.retrying:
            text += f', {self.retrying} to be tried again'
        if self.given_up:
            text += f', {self.given_up} given up'
        if self.undeliverable:
            text += f'; {self.undeliverable} critical cannot be delivered'
        if self.waiting:
            text += f'; {self.waiting} waiting, nothing sent: no transport is connected for their channel'
        return text


def _connected():
    """The channels a transport is connected for (settings.ALARM_TRANSPORTS)."""
    return [channel for channel in Channel.values if transport_for(channel) is not None]


def _queued(channels=None):
    """The outbox's queue (entries that already have a sent or covered attempt left out: R2), only `channels` if given."""
    rows = Notification.objects.filter(pk__in=OutboxEntry.objects.values('notification')).exclude(
        Exists(DeliveryAttempt.objects.filter(notification=OuterRef('pk'), outcome__in=[Outcome.SENT, Outcome.GROUPED])))
    return rows if channels is None else rows.filter(channel__in=channels)


def _late_warnings():
    """The queue's non-critical alarm notifications whose alarm cleared before they were ever tried (a critical one is
    still sent, saying it cleared: `text`)."""
    return _queued().filter(Exists(AlarmClearance.objects.filter(alarm=OuterRef('alarm'))),
                            kind=NotificationKind.ALARM).exclude(
        Exists(DeliveryAttempt.objects.filter(notification=OuterRef('pk')))).exclude(alarm__severity=Severity.CRITICAL)


def _stale_words():
    """The queue's words about a snooze whose alarm has cleared since: "snoozed" or "still open" is no longer true (N4)."""
    return _queued().filter(Exists(AlarmClearance.objects.filter(alarm=OuterRef('alarm')))).exclude(
        kind=NotificationKind.ALARM)


def _late():
    """Both: given up, said why, a chunk a round after the round's sending."""
    return _queued().filter(Q(pk__in=_late_warnings().values('pk')) | Q(pk__in=_stale_words().values('pk')))


def _open_critical(row):
    """A critical notification of an open, unacknowledged alarm: the backlog's first."""
    return row.alarm.severity == Severity.CRITICAL and not row.cleared and not row.acknowledged


def _annotated(rows):
    return list(rows.annotate(
        failures=Count('attempts', filter=Q(attempts__outcome=Outcome.FAILED)),
        last_failed_at=Max('attempts__attempted_at', filter=Q(attempts__outcome=Outcome.FAILED)),
        cleared=Exists(AlarmClearance.objects.filter(alarm=OuterRef('alarm'))),
        cleared_at=Subquery(AlarmClearance.objects.filter(alarm=OuterRef('alarm')).values('cleared_at')[:1]),
        acknowledged=Exists(Acknowledgement.objects.filter(alarm=OuterRef('alarm'))))
        .select_related('alarm', 'alarm__sensor_event', 'recipient'))


def backlog(channels=None):
    """The notifications in the outbox's queue (of `channels`, if given: a channel without a transport is left out in the
    database, so a queue that grows while nothing is connected costs a round nothing), the critical ones first, then the
    oldest queued: the criticals of open, unacknowledged alarms first, then the other criticals (cleared or acknowledged),
    then the rest by severity (N3: a fresh open critical is never behind a backlog of cleared ones). Each carries
    `failures`, `last_failed_at`, `cleared`, `cleared_at` and `acknowledged`."""
    rows = _annotated(_queued(channels).exclude(pk__in=_late().values('pk')))
    return sorted(rows, key=lambda row: (0 if _open_critical(row) else 1 if row.alarm.severity == Severity.CRITICAL else 2,
                                         -RANK[row.alarm.severity], row.queued_at, row.pk))


def _persists(notification):
    """A critical alarm's notification while nobody has acknowledged its alarm, open or cleared (N7: clearing does not
    end it): never given up."""
    return notification.alarm.severity == Severity.CRITICAL and not notification.acknowledged


def exhausted(notification, rules):
    """Whether its attempts are used up (never while it persists: a critical of an unacknowledged alarm)."""
    return not _persists(notification) and notification.failures >= rules.delivery_attempts(notification.alarm.severity)


def retry_wait(notification, rules):
    """How long after its last failure it is tried again: its severity's retry time; a persisting critical's doubles
    with each failure, up to its severity's escalation time (never shorter than the retry time). Doubled step by step
    and stopped at the cap, so no count of failures overflows it (R1)."""
    wait = rules.retry_after(notification.alarm.severity)
    if not _persists(notification):
        return wait
    cap = max(wait, rules.escalation_after(notification.alarm.severity))
    for _failure in range(notification.failures - 1):
        if wait >= cap:
            break
        wait = min(cap, wait * 2)
    return wait


def is_due(notification, rules, now):
    """Whether a notification of the backlog is tried now: never tried, or its retry wait has passed since it failed."""
    return notification.last_failed_at is None or now - notification.last_failed_at >= retry_wait(notification, rules)


def undeliverable(rows, rules, now, snoozed=()):
    """The critical notifications of unacknowledged, unsnoozed alarms (open or cleared) that have failed and waited longer
    than their severity's escalation time (nobody is reached about them, nor would the next level be)."""
    return [row for row in rows if _persists(row) and row.failures and row.alarm_id not in snoozed
            and now - row.queued_at > rules.escalation_after(row.alarm.severity)]


def stuck(rules, now):
    """`undeliverable` read on its own, for the pass's supervision: only the critical notifications of the queue that
    have failed and wait longer than the escalation time are read, however long the queue (R4, R5)."""
    since = now - rules.escalation_after(Severity.CRITICAL)
    rows = _annotated(_queued().filter(alarm__severity=Severity.CRITICAL, queued_at__lt=since).filter(
        Exists(DeliveryAttempt.objects.filter(notification=OuterRef('pk'), outcome=Outcome.FAILED))))
    return undeliverable(rows, rules, now, read.snoozes({row.alarm_id for row in rows}, now))


def _claim(notification):
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_try_advisory_lock(%s, hashtext(%s))', [CLAIM, str(notification.pk)])
        return cursor.fetchone()[0]


def _release(notification):
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_advisory_unlock(%s, hashtext(%s))', [CLAIM, str(notification.pk)])


def _summary_due(row, began):
    """A critical alarm's own notification never tried, its alarm cleared more than SUMMARY_AFTER before the round."""
    return (row.alarm.severity == Severity.CRITICAL and row.kind == NotificationKind.ALARM and row.cleared_at is not None
            and not row.failures and began - row.cleared_at > SUMMARY_AFTER)


CUT = '…'


def _bytes(said):
    """How long a text is as a transport counts it: its UTF-8 bytes (a push payload's limit is in bytes; a Norwegian or
    Turkish letter is two)."""
    return len(said.encode('utf-8'))


def _within(said, limit):
    """`said` in at most `limit` UTF-8 bytes (None: as it is): the whole characters that fit with the mark "…", cut back
    to the last space, so a letter, a word or a number is never cut in half (only a single word longer than the limit
    can be)."""
    if limit is None or _bytes(said) <= limit:
        return said
    cut = said.encode('utf-8')[:max(0, limit - _bytes(CUT))].decode('utf-8', 'ignore')
    if said[len(cut):len(cut) + 1] != ' ' and ' ' in cut:
        cut = cut[:cut.rindex(' ')]
    return cut.rstrip(' ;,:') + CUT


def _listing(flood, limit, moment):
    """The criticals' follow-up within `limit` bytes: how many, since when, how many are open now, then the names that fit,
    the open ones first (the order of `flood.listed`), each whole; "and K more, see the alarm list" for the rest, or
    "see the alarm list" when no name fits."""
    names = [summary if cleared is None else _('%(summary)s (cleared %(cleared)s)') % {
        'summary': summary, 'cleared': moment(cleared)} for summary, cleared in flood.listed]

    def said(shown):
        if shown == len(names):
            alarms = '; '.join(names)
        elif shown:
            alarms = _('%(alarms)s; and %(more)d more, see the alarm list') % {
                'alarms': '; '.join(names[:shown]), 'more': len(names) - shown}
        else:
            alarms = _('see the alarm list')
        return _('%(count)d more critical alarms of one kind since %(since)s, %(open)d open now: %(alarms)s') % {
            'count': len(names), 'since': moment(flood.since), 'open': flood.open, 'alarms': alarms}
    if limit is None:
        return said(len(names))
    best, used = said(0), 0
    for shown in range(1, len(names) + 1):         # the names alone past the limit: no more can fit
        used += _bytes(names[shown - 1]) + (_bytes('; ') if shown > 1 else 0)
        if used > limit:
            break
        each = said(shown)
        if _bytes(each) <= limit:
            best = each
    return best


def text(notification, flood=None, limit=None):
    """What the person is told, in their language (their profile's, else the platform's), on the site's clock, in at
    most `limit` UTF-8 bytes (the transport's `max_bytes`; F-A: a message over a push service's or an SMS gateway's
    payload limit is refused for ever): the alarm's severity and summary; a critical alarm that has cleared by the time
    it is sent says it was critical and has cleared, when it opened and when it cleared (the decision of 2026-11-24: a
    critical that came and went while the transport was down is still said); a word about a snooze says so. With `flood` (alarms/floods.py): the follow-up
    message of criticals names each (its summary, and when it cleared if it has) and says how many of them are open
    now; a warnings' flood message says how many alarms, of which severity, since when, an example; the summary of old
    cleared criticals says how many, the first opening and the last clearing, "see the alarm log". The follow-up names
    what fits, the open ones first, and counts the rest; anything else too long is cut between two words (`_within`)."""
    from core.templatetags.dates import on, zone_for
    alarm = notification.alarm
    language = getattr(getattr(notification.recipient, 'profile', None), 'language', '') or settings.LANGUAGE_CODE
    clearance = AlarmClearance.objects.filter(alarm=alarm).first()
    moment = (lambda at: on(at, zone_for(alarm.site)).strftime('%d.%m.%Y %H:%M'))
    with translation.override(language):
        return _within(_listing(flood, limit, moment) if flood is not None and flood.listed else _said(
            notification, flood, clearance, moment), limit)


def _said(notification, flood, clearance, moment):
    """`text` at any length, in the language in force, but the criticals' follow-up (`_listing`)."""
    alarm = notification.alarm
    if flood is not None and flood.summary:
        return _('%(count)d critical alarms happened and cleared while no message could be sent; see the alarm log. '
                 'The first opened %(opened)s, the last cleared %(cleared)s.') % {
            'count': flood.size, 'opened': moment(flood.since), 'cleared': moment(flood.last_cleared)}
    if flood is not None:
        return _('%(count)d %(severity)s alarms of one kind since %(since)s. For example: %(summary)s') % {
            'count': flood.size, 'severity': alarm.get_severity_display().lower(), 'since': moment(flood.since),
            'summary': flood.example}
    if notification.kind == NotificationKind.SNOOZED:
        return _('Snoozed: %(summary)s') % {'summary': alarm.summary}
    if notification.kind == NotificationKind.RESUMED:
        return _('Still open after its snooze: %(summary)s') % {'summary': alarm.summary}
    if alarm.severity == Severity.CRITICAL and clearance is not None:
        return _('Critical, now cleared: %(summary)s. Opened %(opened)s, cleared %(cleared)s.') % {
            'summary': alarm.summary, 'opened': moment(alarm.opened_at), 'cleared': moment(clearance.cleared_at)}
    return _('%(severity)s: %(summary)s') % {'severity': alarm.get_severity_display(), 'summary': alarm.summary}


def _call(transport, notification, timeout, flood=None):
    """The transport's answer, within `timeout` seconds (None: as long as it takes); a raise is a Failed. `flood`: the
    notification is the first of a flood message (alarms/floods.py). The notification carries its `text`, within the
    transport's `max_bytes`; a transport that declares none is a failed attempt, said why (never an unbounded text)."""
    answer = {}
    limit = getattr(transport, 'max_bytes', None)
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        logger.error('The %s transport declares no max_bytes; notification %s is not sent.', notification.channel,
                     notification.pk)
        return Failed(f'not sent: the {notification.channel} transport declares no max_bytes')
    try:
        notification.text = text(notification, flood, limit)
    except Exception as error:                    # its own handling failed: a failed attempt, retried and counted (N5)
        logger.exception('The text of notification %s could not be made.', notification.pk)
        return Failed(f'not sent: {type(error).__name__}: {error}')

    def send():
        try:
            answer['result'] = transport.send(notification, flood=flood) if flood else transport.send(notification)
        except Exception as error:
            logger.exception('The %s transport raised for notification %s.', notification.channel, notification.pk)
            answer['result'] = Failed(f'{type(error).__name__}: {error}')
    if timeout is None:
        send()
        return answer['result']
    thread = threading.Thread(target=send, name=f'alarm-send-{notification.pk}', daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        logger.error('The %s transport gave no answer for notification %s in %s s.', notification.channel,
                     notification.pk, timeout)
        return Failed(f'no answer in {timeout:g} s')
    return answer['result']


def _sendable(notification):
    """Claimed for this sender and not sent (or covered) by another since the round read the outbox."""
    if not _claim(notification):
        return False
    if DeliveryAttempt.objects.filter(notification=notification, outcome__in=[Outcome.SENT, Outcome.GROUPED]).exists():
        _release(notification)
        return False
    return True


def _count(delivery, rows):
    for row in rows:
        if row.outcome == Outcome.SENT:
            delivery.sent += 1
        elif row.outcome == Outcome.GROUPED:
            delivery.grouped += 1
        else:
            delivery.failed += 1


def _person_kind(group):
    """(recipient, channel, kind of alarm) of a round's group key (recipient, channel, kind, its own id or 0)."""
    recipient, channel, kind, _apart = group
    return recipient, channel, kind


def _critical_since(seen, channels):
    """Whether a critical notification of `channels` joined the queue since the round read it (`seen`: the ids it read),
    whatever time it is stamped with: a pass stamps its notifications with its start and commits them at its end (R3)."""
    return OutboxEntry.objects.filter(notification__alarm__severity=Severity.CRITICAL,
                                      notification__channel__in=channels).exclude(notification_id__in=seen).exists()


def send_due(now=None, timeout=None, stop=None, round_seconds=None, clock=time.monotonic):
    """One round through the outbox: every notification that is due is handed to its transport (on its own, in a flood
    message, or covered by one: alarms/floods.py), its attempt written; what is used up leaves the queue. `now` is the
    round's moment for the tests (each attempt is stamped with it); by default each attempt's own. `stop()` true ends the
    round before the next group (the worker is stopping); so does `round_seconds` passed on `clock`, or a critical
    queued since the round began, before a warning's group. One notification that cannot be handled (an error of its
    own) is logged and left for the next round; the others go on (R1)."""
    rules = alarm_rules.current()
    moment = (lambda: now) if now is not None else timezone.now
    began, started = moment(), clock()
    services.drop_delivered()
    channels = _connected()
    unsent = _queued()
    elsewhere = unsent.exclude(channel__in=channels).exclude(pk__in=_late().values('pk')).aggregate(
        count=Count('pk'), oldest=Min('queued_at'))
    queue = backlog(channels)
    seen = [row.pk for row in queue if row.alarm.severity == Severity.CRITICAL]
    spent, live = [], []
    for row in queue:
        try:
            (spent if exhausted(row, rules) else live).append(row)
        except Exception:
            logger.exception('Notification %s could not be judged in this round; it waits for the next.', row.pk)
    if spent:
        services.give_up(spent)
    snoozed = read.snoozes({row.alarm_id for row in live}, began)
    stuck_rows = undeliverable(live, rules, began, snoozed)
    summaries = defaultdict(list)
    for row in [row for row in live if _summary_due(row, began)]:
        summaries[(row.recipient_id, row.channel)].append(row)
    live = [row for row in live if not _summary_due(row, began)]
    delivery = Delivery(backlog=len(live) + elsewhere['count'], waiting=elsewhere['count'],
                        oldest=min([row.queued_at for row in live] + ([elsewhere['oldest']] if elsewhere['oldest'] else []),
                                   default=None),
                        given_up=len(spent), undeliverable=len(stuck_rows),
                        undeliverable_since=min((row.queued_at for row in stuck_rows), default=None))
    groups, transports = defaultdict(list), {}
    for notification in live:
        try:
            if notification.alarm_id in snoozed and notification.kind == NotificationKind.ALARM:
                delivery.snoozed += 1                 # a word about the snooze goes out at once
            elif not is_due(notification, rules, moment()):
                delivery.retrying += 1
            else:
                transports.setdefault(notification.channel, transport_for(notification.channel))
                kind = floods.key(notification.alarm)
                apart = notification.kind != NotificationKind.ALARM
                groups[(notification.recipient_id, notification.channel, kind, notification.pk if apart else 0)].append(
                    notification)
        except Exception as error:
            logger.exception('Notification %s could not be judged in this round; it is tried again.', notification.pk)
            _failed(notification, error, rules, moment())
    found = floods.recent({_person_kind(group): members for group, members in groups.items() if not group[-1]},
                          moment(), rules)
    # The criticals' groups, then the summaries of old cleared criticals (D8c: never ahead of a fresh critical), then the
    # warnings' groups.
    work = ([(group, members) for group, members in groups.items() if members[0].alarm.severity == Severity.CRITICAL]
            + [(None, members) for members in summaries.values()]
            + [(group, members) for group, members in groups.items() if members[0].alarm.severity != Severity.CRITICAL])
    for index, (group, members) in enumerate(work):
        warning = members[0].alarm.severity != Severity.CRITICAL
        if ((stop is not None and stop()) or (round_seconds is not None and clock() - started >= round_seconds)
                or (warning and _critical_since(seen, channels))):
            delivery.deferred += sum(len(rest) for _group, rest in work[index:])
            break
        try:
            if group is None:
                _send_summary(delivery, members, transports.setdefault(
                    members[0].channel, transport_for(members[0].channel)), moment, timeout)
            else:
                _send_group(delivery, group, members, transports, found, rules, moment, timeout)
        except Exception as error:
            logger.exception('The notifications %s could not be sent in this round; they are tried again.',
                             [notification.pk for notification in members])
            for notification in members:
                _failed(notification, error, rules, moment())
    if stop is None or not stop():
        # After the sending, never before it: one chunk of the warnings whose alarm cleared before they were ever
        # tried (R4), so a backlog of them never delays a critical; the next round takes the next chunk.
        for rows, why in ((_late_warnings(), FIRST_TRY), (_stale_words(), STALE_WORD)):
            late = list(rows.select_related('alarm', 'recipient').order_by('pk')[:GIVE_UP_CHUNK])
            if late:
                services.give_up_said(late, why, moment())
                delivery.given_up += len(late)
    return delivery


def _failed(notification, error, rules, now):
    """A failed attempt for a notification whose own handling raised (N5), so its retry, its attempts and the
    undeliverable count apply as to any failure: never for one that went (sent or covered) before the error, and at most
    one per its severity's retry time, so an error that comes back every round, even in the due check itself, is not an
    attempt a tick (T3c). A database that cannot write it leaves it for the next round."""
    try:
        attempts = DeliveryAttempt.objects.filter(notification=notification)
        if attempts.filter(outcome__in=[Outcome.SENT, Outcome.GROUPED]).exists():
            return
        last = attempts.filter(outcome=Outcome.FAILED).aggregate(at=Max('attempted_at'))['at']
        if last is None or now - last >= rules.retry_after(notification.alarm.severity):
            services.attempt(notification, Failed(f'not sent: {type(error).__name__}: {error}'), now)
    except Exception:
        logger.exception('The failure of notification %s could not be written.', notification.pk)


def _send_summary(delivery, members, transport, moment, timeout):
    """One message to a person for their critical alarms that cleared more than SUMMARY_AFTER before they could be
    sent: how many, the first opening and the last clearing, "see the alarm log"; each one's own notification is
    covered by it (grouped, said why), or each fails with it and is tried again."""
    mine = [notification for notification in members if _sendable(notification)]
    delivery.busy += len(members) - len(mine)
    if not mine:
        return
    try:
        flood = Flood(len(mine), min(row.alarm.opened_at for row in mine), mine[0].alarm.summary, cleared=True,
                      last_cleared=max(row.cleared_at for row in mine), summary=True)
        result = _call(transport, mine[0], timeout, flood)
        delivery.floods += 1
        if isinstance(result, Sent):
            note = Failed(f'covered by the summary of {len(mine)} critical alarms that cleared while no message could be '
                          f'sent')
            _count(delivery, [services.attempt(row, note, moment(), flood_key=floods.key(row.alarm), grouped=True)
                              for row in mine])
        else:
            _count(delivery, [services.attempt(row, result, moment(), flood_key=floods.key(row.alarm))
                              for row in mine])
    finally:
        for row in mine:
            _release(row)


def _send_group(delivery, group, members, transports, found, rules, moment, timeout):
    """One group's due notifications (one person, channel and kind; or one word about a snooze), as floods.plan says:
    each on its own, as one message, covered (warnings), or held for the follow-up (criticals)."""
    transport, kind = transports[group[1]], group[2]
    how = floods.plan(members, found[_person_kind(group)], moment(), rules) if not group[-1] else floods.Plan(
        each=list(members))
    delivery.held += len(how.held)
    held = {notification.pk for notification in how.held}
    mine = [notification for notification in members if notification.pk not in held and _sendable(notification)]
    delivery.busy += len(members) - len(held) - len(mine)
    claimed = {notification.pk for notification in mine}
    try:
        covered = [notification for notification in how.covered if notification.pk in claimed]
        if covered:
            note = Failed(f'covered by the flood message sent at {found[_person_kind(group)].last_flood_at:%H:%M:%S} UTC')
            _count(delivery, [services.attempt(notification, note, moment(), flood_key=kind, grouped=True)
                              for notification in covered])
        alone = [notification for notification in how.each if notification.pk in claimed]
        together = [notification for notification in how.flood if notification.pk in claimed]
        if len(together) == 1 and together[0].alarm.severity == Severity.CRITICAL:
            alone, together = alone + together, []      # the others went with another sender: its own text
        for notification in alone:
            _count(delivery, [services.attempt(notification, _call(transport, notification, timeout), moment(),
                                               flood_key=kind)])
        if together:
            _send_flood(delivery, together, transport, found[_person_kind(group)], kind, moment, timeout)
    finally:
        for notification in mine:
            _release(notification)


def _send_flood(delivery, mine, transport, found, kind, moment, timeout):
    """One message for several notifications of one kind to one person, each written sent or failed as part of it: the
    criticals' follow-up names each and how many of them are open now; a warnings' flood message counts them with the
    ones of its kind sent within the window (only its own when every one has cleared: N2)."""
    cleared = dict(AlarmClearance.objects.filter(alarm__in=[notification.alarm_id for notification in mine])
                   .values_list('alarm', 'cleared_at'))
    since = min(notification.alarm.opened_at for notification in mine)
    if mine[0].alarm.severity == Severity.CRITICAL:
        mine = sorted(mine, key=lambda notification: notification.alarm_id in cleared)    # the open ones named first
        size = len(mine)
        flood = Flood(size, since, mine[0].alarm.summary, listed=tuple(
            (notification.alarm.summary, cleared.get(notification.alarm_id)) for notification in mine),
            open=sum(1 for notification in mine if notification.alarm_id not in cleared))
    else:
        all_cleared = len(cleared) == len({notification.alarm_id for notification in mine})
        size = len(mine) if all_cleared else found.count + len(mine)
        flood = Flood(size, since, mine[0].alarm.summary, cleared=all_cleared,
                      last_cleared=max(cleared.values(), default=None))
    result = _call(transport, mine[0], timeout, flood)
    delivery.floods += 1
    _count(delivery, [services.attempt(notification, result, moment(), flood_key=kind, flood_size=size)
                      for notification in mine])

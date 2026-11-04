"""Checking the alarm rules (manage.py check_sensors): from the channels' state and their clean readings only, never a
page. Shown, not sent (owner question 1): an event is a row the Sensors overview and the Alarm events page show; nobody is
notified until a delivery path exists.

Per active rule and each channel it covers (its channel, or every active channel of its quantity on an active device):
- no data: no fresh value for `for_s` seconds past the channel's freshness;
- device offline: the channel's device sent nothing for three of its intervals;
- above / below: every clean value of the last `for_s` seconds (and the current one) past the threshold; the event
  closes when the value is back past the threshold by the hysteresis;
- rate: the value moved more than the threshold since the value `for_s` seconds ago.
An event opens once per rule and channel (a unique index), keeps its furthest value, and closes when the rule no longer
holds."""
from datetime import timedelta

from django.db import connection, transaction
from django.utils import timezone

from . import read
from .models import AlarmEvent, AlarmKind, AlarmRule, Channel, ChannelStatus
from .quality import BAD_MASK


def _channels(rule):
    if rule.channel_id:
        return [rule.channel] if rule.channel.state == ChannelStatus.ACTIVE else []
    return list(Channel.objects.filter(quantity=rule.quantity, state=ChannelStatus.ACTIVE, device__is_active=True)
                .select_related('device'))


def _extremes(channel_no, since):
    """(lowest, highest) of the clean readings since a moment; (None, None) without one."""
    with connection.cursor() as cursor:
        cursor.execute(f'SELECT min(value), max(value) FROM sensors_reading WHERE channel_no = %s AND ts >= %s '
                       f'AND (quality & {BAD_MASK}) = 0', [channel_no, since])
        return cursor.fetchone()


def _holds(rule, channel, state, online, now, opened):
    """(holds, value): whether the rule holds for the channel now (an open event closes only past the hysteresis)."""
    value = state.value
    if rule.kind == AlarmKind.NO_DATA:
        if state.good_at is None:
            return True, None
        return now - state.good_at > timedelta(seconds=state.fresh_s + rule.for_s), value
    if rule.kind == AlarmKind.DEVICE_OFFLINE:
        return not online, value
    if value is None or not state.fresh:
        return opened, value                    # nothing new to judge: an open event stays as it is
    if rule.kind == AlarmKind.RATE:
        before = read.value_at(channel.channel_no, now - timedelta(seconds=rule.for_s))
        return before is not None and abs(value - before[1]) > rule.threshold, value
    high = rule.kind == AlarmKind.HIGH
    if opened:
        limit = rule.threshold - rule.hysteresis if high else rule.threshold + rule.hysteresis
        return (value > limit) if high else (value < limit), value
    past = value > rule.threshold if high else value < rule.threshold
    if past and rule.for_s:
        low, top = _extremes(channel.channel_no, now - timedelta(seconds=rule.for_s))
        past = (low is not None and low > rule.threshold) if high else (top is not None and top < rule.threshold)
    return past, value


def _further(rule, peak, value):
    if value is None:
        return peak
    if peak is None:
        return value
    return min(peak, value) if rule.kind == AlarmKind.LOW else max(peak, value)


def evaluate(now=None):
    """Checks every active rule now; returns how many events opened and closed."""
    now = now or timezone.now()
    opened_count = closed_count = 0
    for rule in AlarmRule.objects.filter(is_active=True).select_related('channel__device'):
        channels = _channels(rule)
        if not channels:
            continue
        states = read.latest([channel.channel_no for channel in channels], now)
        online = read.device_status({channel.device for channel in channels}, now)
        with transaction.atomic():
            open_events = {event.channel_no: event for event in AlarmEvent.objects.select_for_update()
                           .filter(rule=rule, closed_at__isnull=True)}
            for channel in channels:
                event = open_events.get(channel.channel_no)
                holds, value = _holds(rule, channel, states[channel.channel_no], online[channel.device_id].online, now,
                                      event is not None)
                if holds and event is None:
                    AlarmEvent.objects.create(rule=rule, channel_no=channel.channel_no, opened_at=now, peak=value)
                    opened_count += 1
                elif holds:
                    event.peak = _further(rule, event.peak, value)
                    event.save(update_fields=['peak'])
                elif event is not None:
                    event.closed_at = now
                    event.save(update_fields=['closed_at'])
                    closed_count += 1
    return opened_count, closed_count


def open_events(site=None):
    """The open events (newest first), of one site's devices when given: for the overview, the Monitoring strip later."""
    events = AlarmEvent.objects.filter(closed_at__isnull=True).select_related('rule').order_by('-opened_at')
    if site is not None:
        numbers = Channel.all_objects.filter(device__site=site).values('channel_no')
        events = events.filter(channel_no__in=numbers)
    return list(events)

"""Checking the alarm rules (manage.py check_sensors, and every pass of manage.py run_alarms): from the channels' state and
their clean readings only, never a page. An event is a row the Sensors overview and the Alarm events page show; the alarms
app makes each one an alarm and notifies its recipients (Company › Alarms; nothing is sent until a transport is connected).

Per active rule and each channel it covers (its channel, or every active channel of its quantity on an active device):
- no data: no fresh value for `for_s` seconds past the channel's freshness;
- device offline: the channel's device sent nothing for three of its intervals;
- above / below: every clean value of the last `for_s` seconds (and the current one) past the threshold; the event
  closes when the value is back past the threshold by the hysteresis;
- rate: the value moved more than the threshold since the value `for_s` seconds ago.
An event opens once per rule and channel (a unique index), keeps its furthest value, and closes when the rule no longer
holds.

An alarm belongs to the place (owner rule A1, portable sensors): only a channel bound now is checked, and with what it
measured while bound there (`Binding.took`): a value from its previous place or from while it was out of the water does
not count, the no-data clock starts when it was placed, a time above or a rate reads only the readings taken there. An
event is tied to the binding it opened under; a move or taking the device out closes it then (sensors/bindings.py), and
one whose binding no longer holds is closed here. A site's open events are its places' (`open_events`)."""
from dataclasses import replace
from datetime import timedelta

from django.db import connection, transaction
from django.utils import timezone

from . import read
from .models import AlarmEvent, AlarmKind, AlarmRule, Binding, Channel, ChannelStatus
from .models.binding import place_site
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


def _there(state, binding):
    """The channel's state as its place sees it: emptied when its value was not measured while the binding held."""
    if binding.took(state.at):
        return state
    return replace(state, value=None, at=None, good_at=None, quality=None)


def _holds(rule, channel, state, online, now, opened, binding):
    """(holds, value): whether the rule holds for the channel at its place now (an open event closes only past the
    hysteresis). `state` is already the place's (`_there`)."""
    value = state.value
    if rule.kind == AlarmKind.NO_DATA:
        last = state.good_at or binding.valid_from                # nothing since it came: counted from then
        return now - last > timedelta(seconds=state.fresh_s + rule.for_s), value
    if rule.kind == AlarmKind.DEVICE_OFFLINE:
        return not online, value
    if value is None or not state.fresh:
        return opened, value                    # nothing new to judge: an open event stays as it is
    if rule.kind == AlarmKind.RATE:
        before = read.value_at(channel.channel_no, now - timedelta(seconds=rule.for_s))
        return before is not None and binding.took(before[0]) and abs(value - before[1]) > rule.threshold, value
    high = rule.kind == AlarmKind.HIGH
    if opened:
        limit = rule.threshold - rule.hysteresis if high else rule.threshold + rule.hysteresis
        return (value > limit) if high else (value < limit), value
    past = value > rule.threshold if high else value < rule.threshold
    if past and rule.for_s:
        low, top = _extremes(channel.channel_no, max(now - timedelta(seconds=rule.for_s), binding.valid_from))
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
        covered = _channels(rule)
        places = {binding.channel_id: binding for binding in Binding.objects.visible().at(now)
                  .filter(channel__in=[channel.pk for channel in covered])}
        channels = [channel for channel in covered if channel.pk in places]                # bound now only
        states = read.latest([channel.channel_no for channel in channels], now)
        online = read.device_status({channel.device for channel in channels}, now)
        with transaction.atomic():
            open_events = {event.channel_no: event for event in AlarmEvent.objects.select_for_update(of=('self',))
                           .filter(rule=rule, closed_at__isnull=True).select_related('binding')}
            by_number = {channel.channel_no: channel for channel in channels}
            for number, event in list(open_events.items()):
                channel = by_number.get(number)
                if channel is None or event.binding_id != places[channel.pk].pk:
                    # Its place no longer holds the channel (an edited end, a deleted place, an older event).
                    ended = event.binding.valid_to if event.binding is not None and event.binding.valid_to else now
                    close(event, ended)
                    closed_count += 1
                    del open_events[number]
            for channel in channels:
                binding = places[channel.pk]
                event = open_events.get(channel.channel_no)
                state = _there(states[channel.channel_no], binding)
                holds, value = _holds(rule, channel, state, online[channel.device_id].online, now, event is not None,
                                      binding)
                if holds and event is None:
                    AlarmEvent.objects.create(rule=rule, channel_no=channel.channel_no, binding=binding, opened_at=now,
                                              peak=value)
                    opened_count += 1
                elif holds:
                    event.peak = _further(rule, event.peak, value)
                    event.save(update_fields=['peak'])
                elif event is not None:
                    close(event, now)
                    closed_count += 1
    return opened_count, closed_count


def close(event, at):
    """Closes an open event at `at` (never before it opened)."""
    event.closed_at = max(at, event.opened_at)
    event.save(update_fields=['closed_at'])


def close_at_place(binding, at):
    """Closes the open events opened under `binding` at `at`: the channel left that place (a move, taken out)."""
    for event in AlarmEvent.objects.select_for_update(of=('self',)).filter(binding=binding, closed_at__isnull=True):
        close(event, at)


def open_events(site=None):
    """The open events (newest first), of one site's places when given (the site of the place each opened at, whatever
    the device's site is now): for the overview, the Monitoring strip later."""
    events = (AlarmEvent.objects.filter(closed_at__isnull=True).select_related('rule', 'binding')
              .order_by('-opened_at'))
    if site is not None:
        events = events.annotate(place_site=place_site('binding__')).filter(place_site=site.pk)
    return list(events)

"""Checking the alarm rules (manage.py check_sensors, and every pass of manage.py run_alarms): from the channels' state and
their clean readings only, never a page. An event is a row the Sensors overview and the Alarm events page show; the alarms
app makes each one an alarm and notifies its recipients (Company › Alarms; nothing is sent until a transport is connected).

Per active rule and each channel it covers (its channel, or every active channel of its quantity on an active device):
- no data: no fresh value for `for_s` seconds past the channel's freshness, counted as the page counts it (the older
  of the value's device time and its receipt, read.State.fresh_from); the default rule of each quantity the water
  limits judge (AlarmRule.is_default) holds at the freshness itself, so a probe that stops sending is warned of the
  moment its place shows "no recent data", whatever its pH scale, and only where its place's water concerns fish
  (owner decision of 2026-11-23: a fallow or empty unit raises no alarm; farm.water.read.with_fish);
- device offline: the channel's device sent nothing for three of its intervals;
- above / below: every clean value of the last `for_s` seconds (and the current one) past the threshold; the event
  closes when the value is back past the threshold by the hysteresis;
- rate: the value moved more than the threshold since the value `for_s` seconds ago.
A pH channel's readings from before its pH scale was changed (`Channel.ph_scale_from`) are on another scale: a rate does
not compare a value with one of them, and a time above or below does not read them (the review of the water-chemistry
audit of 2026-11-19, C1: the same water, 7.95 total then 8.08 NBS, read as a move of 0.13).
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

from farm.water import parameters as water_parameters, read as water_read, sources as water_sources
from farm.water.parameters import PH

from . import quantities, read
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
        # Counted from where the value's freshness is (State.fresh_from), so a backlog replayed at a reconnect, received
        # now but measured long ago, keeps the rule holding as the page keeps saying "no recent data"; nothing since
        # the channel came: from then.
        last = state.fresh_from or binding.valid_from
        return now - last > timedelta(seconds=state.fresh_s + rule.for_s), value
    if rule.kind == AlarmKind.DEVICE_OFFLINE:
        return not online, value
    if value is None or not state.fresh:
        return opened, value                    # nothing new to judge: an open event stays as it is
    scale_from = channel.ph_scale_from if channel.quantity == PH else None
    if rule.kind == AlarmKind.RATE:
        before = read.value_at(channel.channel_no, now - timedelta(seconds=rule.for_s))
        if before is not None and scale_from is not None and before[0] < scale_from:
            before = None                       # on the scale before the change: no change of the water to compare
        return before is not None and binding.took(before[0]) and abs(value - before[1]) > rule.threshold, value
    high = rule.kind == AlarmKind.HIGH
    if opened:
        limit = rule.threshold - rule.hysteresis if high else rule.threshold + rule.hysteresis
        return (value > limit) if high else (value < limit), value
    past = value > rule.threshold if high else value < rule.threshold
    if past and rule.for_s:
        low, top = _extremes(channel.channel_no, max(filter(None, (now - timedelta(seconds=rule.for_s),
                                                                   binding.valid_from, scale_from))))
        past = (low is not None and low > rule.threshold) if high else (top is not None and top < rule.threshold)
    return past, value


def _further(rule, peak, value):
    if value is None:
        return peak
    if peak is None:
        return value
    return min(peak, value) if rule.kind == AlarmKind.LOW else max(peak, value)


def _aside():
    """(quantities, channel ids) where the default "No fresh value" rule stands aside: a farm's own active "No fresh
    value" rule covers them, of the whole quantity or of the channel (the review of 2026-11-23, F4: one silent probe is
    one alarm, the farm's own rule's)."""
    own = AlarmRule.objects.filter(kind=AlarmKind.NO_DATA, is_active=True, is_default=False)
    return (set(own.filter(channel__isnull=True).values_list('quantity', flat=True)),
            set(own.filter(channel__isnull=False).values_list('channel_id', flat=True)))


def close_switched_off(now):
    """Closes at `now` the open events of a rule that is switched off or deleted (the review of 2026-11-23, F5): no pass
    visits such a rule, so its alarm would stay open for ever, even after the probe sends again. Never an event of an
    active rule. Their alarms clear with the rule's state said in the activity log (alarms/sources.py
    `sensor_events`). Returns how many it closed."""
    found = list(AlarmEvent.objects.select_for_update(of=('self',)).filter(closed_at__isnull=True)
                 .exclude(rule__in=AlarmRule.objects.filter(is_active=True)))
    for event in found:
        close(event, now)
    return len(found)


def evaluate(now=None):
    """Checks every active rule now, after closing the events of the rules switched off (`close_switched_off`); returns
    how many events opened and closed."""
    now = now or timezone.now()
    opened_count = 0
    with transaction.atomic():
        closed_count = close_switched_off(now)
    aside_quantities, aside_channels = _aside()
    for rule in AlarmRule.objects.filter(is_active=True).select_related('channel__device'):
        covered = _channels(rule)
        if rule.is_default:
            # The farm's own rule speaks for these (F4); an open event of the default there closes below.
            covered = [] if rule.quantity in aside_quantities else [
                channel for channel in covered if channel.pk not in aside_channels]
        places = {binding.channel_id: binding for binding in Binding.objects.visible().at(now)
                  .filter(channel__in=[channel.pk for channel in covered])}
        channels = [channel for channel in covered if channel.pk in places]                # bound now only
        states = read.latest([channel.channel_no for channel in channels], now)
        online = read.device_status({channel.device for channel in channels}, now)
        # A default rule holds only where its place's water concerns fish (owner decision of 2026-11-23): one ask for
        # every place of the rule's channels; an open event of a place whose fish are gone closes.
        fished = (water_read.with_fish({place_of(places[channel.pk]) for channel in channels}, now)
                  if rule.is_default and channels else None)
        # A default oxygen rule's silent probe where the place's oxygen is fresh all the same (a typed sample, another
        # probe): the alarm system's warning says it, not this rule's critical (review 2 of the branch, R3 p3); once
        # nothing else is fresh, the rule holds again.
        known = None
        if rule.is_default and rule.quantity in OXYGEN and channels:
            silent = {place_of(places[channel.pk]) for channel in channels
                      if _silent(channel, states[channel.channel_no], places[channel.pk], now)}
            known = water_read.oxygen_known(silent, now) if silent else set()
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
                holds = holds and (fished is None or place_of(binding) in fished) and (
                    known is None or place_of(binding) not in known)
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


# The dissolved oxygen, one quantity in two units.
OXYGEN = (water_parameters.OXYGEN_MG_L, water_parameters.OXYGEN_PCT)


def _silent(channel, state, binding, now):
    """Whether the channel sent no fresh value at its place for its freshness: what a default "No fresh value" rule
    holds on (`_holds`, at the freshness itself)."""
    last = _there(state, binding).fresh_from or binding.valid_from
    return now - last > timedelta(seconds=state.fresh_s)


def silent_probes(codes, now=None):
    """{place (`place_of`): [Binding, its channel loaded]} of the channels of `codes` an active default "No fresh
    value" rule covers (not standing aside for a farm's own rule: `_aside`), active on an active device, bound now, that
    sent no fresh value there (`_silent`): the probes whose silence the alarm system says as a warning where the place's
    oxygen is fresh all the same (alarms/sources.py; review 2 of the branch, R3 p3). Five queries."""
    now = now or timezone.now()
    defaults = set(AlarmRule.objects.filter(is_default=True, is_active=True, quantity__in=list(codes))
                   .values_list('quantity', flat=True))
    aside_quantities, aside_channels = _aside()
    channels = [channel for channel in Channel.objects.filter(
        quantity__in=defaults - aside_quantities, state=ChannelStatus.ACTIVE, device__is_active=True)
        .select_related('device') if channel.pk not in aside_channels]
    places = {binding.channel_id: binding for binding in Binding.objects.visible().at(now)
              .filter(channel__in=[channel.pk for channel in channels])
              .select_related('point__unit', 'point__system', 'point__equipment', 'system', 'equipment')}
    channels = [channel for channel in channels if channel.pk in places]
    states = read.latest([channel.channel_no for channel in channels], now)
    found = {}
    for channel in channels:
        binding = places[channel.pk]
        if _silent(channel, states[channel.channel_no], binding, now):
            binding.channel = channel                       # (its device loaded: the alarm's site)
            found.setdefault(place_of(binding), []).append(binding)
    return found


def place_of(binding):
    """The place a binding holds its channel at, as the water read names it (farm.water.read.with_fish)."""
    if binding.point_id:
        return (water_sources.POINT, binding.point_id)
    if binding.system_id:
        return (water_sources.SYSTEM, binding.system_id)
    return (water_read.EQUIPMENT, binding.equipment_id)


def watched(codes, now=None):
    """The places (`place_of`) where an active channel of a quantity of `codes` on an active device is bound now and an
    active "No fresh value" rule covers it (the channel's own or its quantity's): a probe there that stops sending is
    the sensor rules' to say, so the alarm system raises no second alarm for the unit's water beside it
    (alarms/sources.py, the oxygen of a unit with fish that has no fresh value). Three queries."""
    now = now or timezone.now()
    rules = AlarmRule.objects.filter(kind=AlarmKind.NO_DATA, is_active=True)
    by_quantity = set(rules.filter(channel__isnull=True).values_list('quantity', flat=True))
    by_channel = set(rules.filter(channel__isnull=False).values_list('channel_id', flat=True))
    return {place_of(binding) for binding in Binding.objects.visible().at(now).filter(
                channel__quantity__in=list(codes), channel__state=ChannelStatus.ACTIVE, channel__device__is_active=True)
            .select_related('channel')
            if binding.channel.quantity in by_quantity or binding.channel_id in by_channel}


def close(event, at):
    """Closes an open event at `at` (never before it opened)."""
    event.closed_at = max(at, event.opened_at)
    event.save(update_fields=['closed_at'])


def close_at_place(binding, at):
    """Closes the open events opened under `binding` at `at`: the channel left that place (a move, taken out)."""
    for event in AlarmEvent.objects.select_for_update(of=('self',)).filter(binding=binding, closed_at__isnull=True):
        close(event, at)


def uncovered():
    """The active channels on an active device of a quantity the water limits judge (quantities.JUDGED_CODES) that no
    active "No fresh value" rule covers, its own or its quantity's (a default rule switched off, with its reason): a probe
    of theirs that stops sending raises no alarm of its own. The dissolved oxygen's are not listed: where such a probe
    stops, a unit with fish whose oxygen then has no fresh value is a critical alarm of the alarm system all the same
    (alarms/sources.py; review 2 of the branch, R5). The system check sensors.W001 and the Alarm rules page list them.
    Two queries."""
    rules = AlarmRule.objects.filter(kind=AlarmKind.NO_DATA, is_active=True)
    quantities_covered = set(rules.filter(channel__isnull=True).values_list('quantity', flat=True))
    return list(Channel.objects.filter(quantity__in=[code for code in quantities.JUDGED_CODES if code not in OXYGEN],
                                       state=ChannelStatus.ACTIVE, device__is_active=True)
                .exclude(quantity__in=quantities_covered)
                .exclude(pk__in=rules.filter(channel__isnull=False).values('channel_id'))
                .select_related('device').order_by('device__code', 'code'))


def open_events(site=None):
    """The open events (newest first), of one site's places when given (the site of the place each opened at, whatever
    the device's site is now): for the overview, the Monitoring strip later."""
    events = (AlarmEvent.objects.filter(closed_at__isnull=True).select_related('rule', 'binding')
              .order_by('-opened_at'))
    if site is not None:
        events = events.annotate(place_site=place_site('binding__')).filter(place_site=site.pk)
    return list(events)

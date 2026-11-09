"""How far each device's clock is from the platform's, measured from what the ingest already stores (sensors/CONTRACT.md,
`sensors_channel_state`): for a channel's newest good value, `last_value_ts` is the device's time of it and
`last_good_at` the time the platform received it. Their difference is the skew: positive when the device's clock is
ahead, negative when it is behind (a value is received after it is taken, so "behind" also holds the network's and the
broker's delay: seconds, against limits of a minute and more). Nothing is judged here: the limits are the alarm rules'
(alarms/clock.py).

- A message without a device time (quality `receive_time`) measures nothing: its time is the receipt.
- A device time the ingest replaced because it was further ahead than the contract allows (quality `clock_suspect`) is
  ahead by more than `sensors_contract.future_skew_s`: measured as that, `at_least`.
- A channel whose newest good value was received longer ago than the channel's freshness (`fresh_s`) measures nothing
  now: an old skew is not this moment's.
A device's skew is that of its channel furthest off, either way. `draining`: the ingest reports messages waiting for
the device's connection (`sensors_ingest_status.queue_depth`), so a value received now may have been taken long ago."""
from dataclasses import dataclass
from datetime import datetime, timedelta

from .models import Channel, ChannelState, ChannelStatus, Contract, IngestStatus
from .quality import CLOCK_SUSPECT, RECEIVE_TIME


@dataclass(frozen=True)
class Skew:
    device_id: object
    seconds: float              # the device's time minus the receipt: > 0 ahead, < 0 behind
    at_least: bool              # the device's time was replaced: ahead by more than `seconds`
    received_at: datetime
    draining: bool = False      # the ingest says messages wait for the device's connection (a backlog)


def skews(now, device_ids=None):
    """{device id: Skew} of the active devices' active channels with a recent good value (three queries)."""
    channels = Channel.objects.filter(state=ChannelStatus.ACTIVE, device__is_active=True, device__is_deleted=False)
    if device_ids is not None:
        channels = channels.filter(device__in=list(device_ids))
    channels = {channel.channel_no: channel
                for channel in channels.only('channel_no', 'device_id', 'device__connection_id', 'heartbeat_s', 'fresh_s')
                .select_related('device')}
    if not channels:
        return {}
    waiting = set(IngestStatus.objects.filter(queue_depth__gt=0).values_list('connection_id', flat=True))
    contract = Contract.objects.first()
    allowed = contract.future_skew_s if contract is not None else None
    found = {}
    for state in ChannelState.objects.filter(channel_no__in=list(channels), last_good_at__isnull=False,
                                             last_value_ts__isnull=False):
        channel = channels[state.channel_no]
        if now - state.last_good_at > timedelta(seconds=channel.fresh_s):
            continue
        quality = state.last_quality or 0
        if quality & CLOCK_SUSPECT:
            if allowed is None:
                continue
            skew = Skew(channel.device_id, float(allowed), True, state.last_good_at,
                        channel.device.connection_id in waiting)
        elif quality & RECEIVE_TIME:
            continue
        else:
            skew = Skew(channel.device_id, (state.last_value_ts - state.last_good_at).total_seconds(), False,
                        state.last_good_at, channel.device.connection_id in waiting)
        held = found.get(channel.device_id)
        if held is None or abs(skew.seconds) > abs(held.seconds):
            found[channel.device_id] = skew
    return found

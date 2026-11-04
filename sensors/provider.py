"""The sensors as a source of the water (farm/water/sources.py), registered in SensorsConfig.ready(). It answers for
sampling points and systems with the water channels bound there; which targets count for a unit and in which order is
decided by farm/water/read.py, never here.

- `latest`: the channels bound now (binding live, target live, holding at `now`), active (a channel in maintenance or
  retired is skipped, so the next source counts), of a water quantity, with a value in `sensors_channel_state`: its last
  GOOD value at the device time it was measured, fresh for the channel's `fresh_s`. Never the hypertable.
- `value_at`: the channels bound there at any time up to the moment, and for each the newest clean reading at or before
  it taken while the binding held (a sensor moved away keeps its earlier values with the place it was in, and gives none
  to the place it moved to before it came). One indexed row per binding."""
from django.db import connection
from django.db.models import Q

from farm.water import sources

from . import quantities
from .models import Binding, ChannelState, ChannelStatus
from .quality import BAD_MASK

TARGET_FIELDS = {sources.POINT: 'point_id', sources.SYSTEM: 'system_id'}


def _bindings(targets):
    """The visible bindings of water channels to the targets, with their channels."""
    condition = Q(pk__in=[])
    for kind, field in TARGET_FIELDS.items():
        ids = [pk for target_kind, pk in targets if target_kind == kind]
        if ids:
            condition |= Q(**{f'{field}__in': ids})
    return (Binding.objects.visible().filter(condition, channel__quantity__in=quantities.WATER_CODES)
            .select_related('channel'))


def _target(binding):
    return (sources.POINT, binding.point_id) if binding.point_id else (sources.SYSTEM, binding.system_id)


class SensorSource:
    def __repr__(self):
        return 'sensors'

    def latest(self, targets, now):
        bindings = [binding for binding in _bindings(targets).at(now)
                    if binding.channel.state == ChannelStatus.ACTIVE]
        states = ChannelState.objects.in_bulk([binding.channel.channel_no for binding in bindings])
        found = {}
        for binding in bindings:
            state = states.get(binding.channel.channel_no)
            if state is None or state.last_value is None or state.last_value_ts is None:
                continue
            channel = binding.channel
            found.setdefault(_target(binding), {}).setdefault(channel.quantity, []).append(sources.SensorValue(
                code=channel.quantity, value=state.last_value, at=state.last_value_ts, fresh_for=channel.fresh_s,
                role=binding.role, channel_no=channel.channel_no))
        return found

    def value_at(self, targets, code, moment):
        """Per target, each channel's newest clean reading at or before `moment` taken while it was bound there."""
        newest = {}
        bindings = _bindings(targets).filter(channel__quantity=code, valid_from__lte=moment)
        with connection.cursor() as cursor:
            for binding in bindings:
                cursor.execute(
                    f'SELECT ts, value FROM sensors_reading WHERE channel_no = %s AND ts >= %s AND ts <= %s '
                    f'AND (%s::timestamptz IS NULL OR ts < %s) AND (quality & {BAD_MASK}) = 0 ORDER BY ts DESC LIMIT 1',
                    [binding.channel.channel_no, binding.valid_from, moment, binding.valid_to, binding.valid_to])
                row = cursor.fetchone()
                key = (_target(binding), binding.channel.channel_no)
                if row is not None and (key not in newest or row[0] > newest[key].at):
                    newest[key] = sources.SensorValue(code=code, value=row[1], at=row[0],
                                                      fresh_for=binding.channel.fresh_s, role=binding.role,
                                                      channel_no=binding.channel.channel_no)
        found = {}
        for (target, _channel_no), value in newest.items():
            found.setdefault(target, []).append(value)
        return found


PROVIDER = SensorSource()

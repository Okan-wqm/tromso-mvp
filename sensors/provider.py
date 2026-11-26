"""The sensors as a source of the water (farm/water/sources.py), registered in SensorsConfig.ready(). It answers for
sampling points and systems with the water channels bound there; which targets count for a unit and in which order is
decided by farm/water/read.py, never here.

- `latest`: the channels bound now (binding live, target live, holding at `now`), active (a channel in maintenance or
  retired is skipped, so the next source counts), of a water quantity, with a value in `sensors_channel_state`: its last
  GOOD value at the device time it was measured, fresh for the channel's `fresh_s`, and only when it was measured while
  the binding held (a probe moved here gives this place nothing until its first value here). Never the hypertable.
- `value_at`: the channels bound there at any time up to the moment, and for each the newest clean reading at or before
  it taken while the binding held (a sensor moved away keeps its earlier values with the place it was in, and gives none
  to the place it moved to before it came). One indexed row per binding; `values_at` asks for several moments in the
  same two queries.
- `covered`: for each span asked at a target (a farm-local day), each channel's time-weighted mean of its clean
  readings taken while it was bound there, the seconds they cover, the hours of the span that hold a clean reading and
  the number of clean readings. A clean reading holds from its time until the channel's NEXT STORED ROW, clean or not
  (a bad or maintenance row ends the hold: the value is not usable from then), at most the hold bound the asker gives
  and never longer than the channel's own `fresh_s`, and never past the binding's end or the span's. The reading before
  the span counts from the span's start for what is left of its hold. It also says whether the channel has a range
  set (a channel without one flags nothing out of range: the asker does not take it as a food-safety source). Two
  queries whatever the spans; the only read of the hypertable for the degree-days, made when a day is closed
  (farm/water/services.py), never by a page.
- A pH value says its channel's pH scale and since when it holds (`_scale`): the farm puts it on the NBS scale."""
from django.db import connection
from django.db.models import Q

from farm.models.water import NBS
from farm.water import sources
from farm.water.parameters import PH

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


def _scale(channel):
    """What a value of the channel says of its pH scale (sources.SensorValue): the channel's scale ('' for NBS) and since
    when it holds. The farm puts the value on the NBS scale (farm/water/read.py), never here."""
    if channel.quantity != PH:
        return {}
    return {'ph_scale': '' if channel.ph_scale == NBS else channel.ph_scale, 'ph_scale_from': channel.ph_scale_from}


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
            if not binding.took(state.last_value_ts):
                continue                        # measured before the channel came here: never this place's
            channel = binding.channel
            found.setdefault(_target(binding), {}).setdefault(channel.quantity, []).append(sources.SensorValue(
                code=channel.quantity, value=state.last_value, at=state.last_value_ts, fresh_for=channel.fresh_s,
                role=binding.role, channel_no=channel.channel_no, **_scale(channel)))
        return found

    def bound(self, targets, code, since, until):
        """The targets with a channel of `code` bound there at some time between since and until (one query)."""
        found = (_bindings(targets).filter(channel__quantity=code, valid_from__lte=until)
                 .filter(Q(valid_to__isnull=True) | Q(valid_to__gt=since)).values_list('point_id', 'system_id'))
        return {(sources.POINT, point) if point else (sources.SYSTEM, system) for point, system in found}

    def value_at(self, targets, code, moment):
        """Per target, each channel's newest clean reading at or before `moment` taken while it was bound there."""
        return self.values_at(targets, code, [moment])[0]

    def values_at(self, targets, code, moments):
        """`value_at` at each of `moments`, in their order. Two queries whatever the number of bindings and moments: the
        bindings, then for each binding and each moment it had begun by, its newest clean reading at or before the
        moment in ONE statement (a LATERAL lookup on the hypertable's (channel_no, ts) key), never a query per binding
        or per moment."""
        moments = list(moments)
        if not moments:
            return []
        bindings = list(_bindings(targets).filter(channel__quantity=code, valid_from__lte=max(moments)))
        if not bindings:
            return [{} for _moment in moments]
        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT b.id, m.n, r.ts, r.value FROM unnest(%s::uuid[], %s::integer[], %s::timestamptz[], '
                '%s::timestamptz[]) AS b(id, channel_no, valid_from, valid_to) '
                'CROSS JOIN unnest(%s::timestamptz[]) WITH ORDINALITY AS m(moment, n) '
                'CROSS JOIN LATERAL (SELECT ts, value FROM sensors_reading WHERE channel_no = b.channel_no '
                'AND ts >= b.valid_from AND ts <= m.moment AND (b.valid_to IS NULL OR ts < b.valid_to) '
                f'AND (quality & {BAD_MASK}) = 0 ORDER BY ts DESC LIMIT 1) r WHERE b.valid_from <= m.moment',
                [[binding.pk for binding in bindings], [binding.channel.channel_no for binding in bindings],
                 [binding.valid_from for binding in bindings], [binding.valid_to for binding in bindings], moments])
            rows = {(binding_id, n - 1): (ts, value) for binding_id, n, ts, value in cursor.fetchall()}
        answers = []
        for index, moment in enumerate(moments):
            newest = {}
            for binding in bindings:                # in the bindings' own order, as when each was read on its own
                row = rows.get((binding.pk, index))
                if binding.valid_from > moment or row is None:
                    continue
                key = (_target(binding), binding.channel.channel_no)
                if key not in newest or row[0] > newest[key].at:
                    newest[key] = sources.SensorValue(code=code, value=row[1], at=row[0],
                                                      fresh_for=binding.channel.fresh_s, role=binding.role,
                                                      channel_no=binding.channel.channel_no, **_scale(binding.channel))
            found = {}
            for (target, _channel_no), value in newest.items():
                found.setdefault(target, []).append(value)
            answers.append(found)
        return answers

    def covered(self, asks, code, hold):
        """{index of the ask: [sources.Covered]}: each (target, start, end) of `asks`, every channel of `code` bound at
        the target during the span (module docstring); `hold`: the seconds a reading stands for at most. The bindings
        in one query, the spans in one statement (a LATERAL window over the hypertable's (channel_no, ts) key)."""
        asks = list(asks)
        if not asks:
            return {}
        since, until = min(start for _target, start, _end in asks), max(end for _target, _start, end in asks)
        bound = {}
        for binding in (_bindings({target for target, _start, _end in asks}).filter(channel__quantity=code,
                                                                                     valid_from__lt=until)
                        .filter(Q(valid_to__isnull=True) | Q(valid_to__gt=since))):
            bound.setdefault(_target(binding), []).append(binding)
        spans, channels = [], {}
        for index, (target, start, end) in enumerate(asks):
            for binding in bound.get(target, ()):
                low = max(start, binding.valid_from)
                high = end if binding.valid_to is None else min(end, binding.valid_to)
                if low < high:
                    channel = binding.channel
                    spans.append((index, channel.channel_no, low, high, binding.valid_from, start,
                                  min(int(hold), channel.fresh_s)))
                    channels[(index, channel.channel_no)] = (binding.role, channel)
        if not spans:
            return {}
        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT w.i, w.channel_no, sum(r.value * r.held) FILTER (WHERE r.good AND r.held > 0), '
                'sum(r.held) FILTER (WHERE r.good AND r.held > 0), '
                'count(DISTINCT r.hour) FILTER (WHERE r.good AND r.inside), count(*) FILTER (WHERE r.good AND r.inside) '
                'FROM unnest(%s::integer[], %s::integer[], %s::timestamptz[], %s::timestamptz[], %s::timestamptz[], '
                '%s::timestamptz[], %s::integer[]) AS w(i, channel_no, low, high, bound_from, day_start, hold_s) '
                f'CROSS JOIN LATERAL (SELECT value, (quality & {BAD_MASK}) = 0 AS good, ts >= w.low AS inside, '
                'floor(extract(epoch FROM ts - w.day_start) / 3600) AS hour, '
                'extract(epoch FROM least(lead(ts) OVER (ORDER BY ts), '
                "ts + w.hold_s * interval '1 second', w.high) - greatest(ts, w.low))::float8 AS held "
                'FROM sensors_reading WHERE channel_no = w.channel_no '
                "AND ts >= greatest(w.low - w.hold_s * interval '1 second', w.bound_from) AND ts < w.high) r "
                'GROUP BY w.i, w.channel_no',
                [list(column) for column in zip(*spans)])
            rows = cursor.fetchall()
        found, merged = {}, {}
        for index, channel_no, weighted, seconds, hours, readings in rows:
            if not seconds:
                continue
            # two bindings of one channel to one place in a span: one answer (their hours may overlap: the larger)
            slot = merged.setdefault((index, channel_no), [0.0, 0.0, 0, 0])
            slot[0] += float(weighted)
            slot[1] += float(seconds)
            slot[2] = max(slot[2], int(hours))
            slot[3] += int(readings)
        for (index, channel_no), (weighted, seconds, hours, readings) in merged.items():
            role, channel = channels[(index, channel_no)]
            found.setdefault(index, []).append(sources.Covered(
                channel_no, role, weighted / seconds, seconds, hours, readings,
                channel.range_min is not None and channel.range_max is not None))
        return found


PROVIDER = SensorSource()

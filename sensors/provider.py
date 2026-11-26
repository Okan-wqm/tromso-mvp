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

    def steady_until(self, targets, code, start, until, value, band):
        """When the targets' clean readings of `code` (the channels bound there, while bound) stopped confirming `value`:
        the reading in force at `start` (the newest at or before it, within its channel's freshness) and every later one
        up to `until`, in time order across the channels; the first one further than `band` from `value` ends it at its
        own time, a gap longer than the channel's freshness (or the last reading's freshness running out) at that
        reading's time plus its freshness. None when no reading was in force at `start`. One statement, on the
        hypertable's (channel_no, ts) key (farm/water/sources.py, freshness.temperature_until)."""
        bindings = list(_bindings(targets).filter(channel__quantity=code, valid_from__lte=until)
                        .filter(Q(valid_to__isnull=True) | Q(valid_to__gt=start)))
        if not bindings:
            return None
        with connection.cursor() as cursor:
            cursor.execute(
                'WITH b AS (SELECT * FROM unnest(%(channels)s::integer[], %(froms)s::timestamptz[], '
                '%(tos)s::timestamptz[], %(fresh)s::integer[]) AS b(channel_no, valid_from, valid_to, fresh_s)), '
                'r AS (SELECT r.ts, r.value, b.fresh_s FROM b JOIN sensors_reading r ON r.channel_no = b.channel_no '
                'AND r.ts >= greatest(b.valid_from, %(start)s::timestamptz - make_interval(secs => b.fresh_s)) '
                'AND r.ts <= %(until)s AND (b.valid_to IS NULL OR r.ts < b.valid_to) '
                f'AND (r.quality & {BAD_MASK}) = 0), '
                'f AS (SELECT ts FROM r WHERE ts <= %(start)s ORDER BY ts DESC LIMIT 1), '
                'o AS (SELECT ts, value, fresh_s, lead(ts) OVER (ORDER BY ts) AS next FROM r) '
                'SELECT min(CASE WHEN abs(o.value - %(value)s) > %(band)s THEN o.ts '
                'WHEN o.next IS NULL OR o.next - o.ts > make_interval(secs => o.fresh_s) '
                'THEN o.ts + make_interval(secs => o.fresh_s) END) FROM o, f WHERE o.ts >= f.ts',
                {'channels': [binding.channel.channel_no for binding in bindings],
                 'froms': [binding.valid_from for binding in bindings], 'tos': [binding.valid_to for binding in bindings],
                 'fresh': [binding.channel.fresh_s for binding in bindings], 'start': start, 'until': until,
                 'value': float(value), 'band': float(band)})
            found = cursor.fetchone()
        return found[0] if found else None


PROVIDER = SensorSource()

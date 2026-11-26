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
# The band check's memory (review 4 of the branch, M4): {ask: {"final": (moment, kind, value) or None, "through": the last
# reading confirmed}}, per process; emptied whole past STEADY_KEPT asks. ROWS_READ: the probe rows it has read, a test's
# measure of its cost.
_STEADY = {}
STEADY_KEPT = 20000
ROWS_READ = [0]


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
        return self.values_for(code, [(targets, moment)])[0]

    def values_at(self, targets, code, moments):
        """`value_at` at each of `moments`, in their order: `values_for` with the same targets at every moment, the one
        lookup (review 4 of the branch, L2)."""
        return self.values_for(code, [(targets, moment) for moment in moments])

    def values_for(self, code, asks):
        """`value_at` for each ask (targets, moment) of its own: each binding paired only with the asks whose targets it
        is bound to, so the lookups grow with the samples, never with bindings times moments (review 3 of the branch,
        H2). Two queries for all the asks: the bindings, then each pair's newest clean reading at or before its moment
        in ONE statement (a LATERAL lookup on the hypertable's (channel_no, ts) key). THE lookup of a value at a moment."""
        everything = {target for targets, _moment in asks for target in targets}
        bindings = list(_bindings(everything).filter(channel__quantity=code)) if asks else []
        pairs = [(index, binding) for index, (targets, moment) in enumerate(asks) for binding in bindings
                 if _target(binding) in targets and binding.valid_from <= moment]
        answers = [{} for _ask in asks]
        if not pairs:
            return answers
        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT p.n, r.ts, r.value FROM unnest(%s::integer[], %s::integer[], %s::timestamptz[], '
                '%s::timestamptz[], %s::timestamptz[]) WITH ORDINALITY AS p(ask, channel_no, valid_from, valid_to, '
                'moment, n) CROSS JOIN LATERAL (SELECT ts, value FROM sensors_reading WHERE channel_no = p.channel_no '
                'AND ts >= p.valid_from AND ts <= p.moment AND (p.valid_to IS NULL OR ts < p.valid_to) '
                f'AND (quality & {BAD_MASK}) = 0 ORDER BY ts DESC LIMIT 1) r',
                [[index for index, _binding in pairs], [binding.channel.channel_no for _index, binding in pairs],
                 [binding.valid_from for _index, binding in pairs], [binding.valid_to for _index, binding in pairs],
                 [asks[index][1] for index, _binding in pairs]])
            rows = {n - 1: (ts, value) for n, ts, value in cursor.fetchall()}
        newest = [{} for _ask in asks]
        for position, (index, binding) in enumerate(pairs):     # in the bindings' own order
            row = rows.get(position)
            if row is None:
                continue
            key = (_target(binding), binding.channel.channel_no)
            if key not in newest[index] or row[0] > newest[index][key].at:
                newest[index][key] = sources.SensorValue(code=code, value=row[1], at=row[0],
                                                         fresh_for=binding.channel.fresh_s, role=binding.role,
                                                         channel_no=binding.channel.channel_no,
                                                         **_scale(binding.channel))
        for index, found in enumerate(newest):
            for (target, _channel_no), value in found.items():
                answers[index].setdefault(target, []).append(value)
        return answers

    def steady_until(self, code, band, tolerance, asks):
        """For each ask (targets, start, value, until): when the targets' clean readings of `code` (the channels bound
        there, while bound) stopped confirming `value`, as (moment, kind, the reading's value) or None.

        - The reading in force at `start` is the newest at or before it within its channel's freshness, else the first at
          most `tolerance` after it (the clock tolerance the look-up of the value takes too, review 3, L2).
        - From it, every later reading up to the ask's `until`, in time order across the ask's channels:
          - the first one further than `band` from `value`, compared unrounded in numeric (review 4, L4), ends it at its
            own time ('band', with that reading's value);
          - a gap longer than the channel's freshness ends it at the reading before the gap plus its freshness ('gap');
          - otherwise it holds until the last reading's freshness runs out ('last': for now, the probe may send more).
        - None when no reading was in force at `start`.

        The check keeps what it confirmed (review 4, M4): a final end ('band', 'gap') is never asked again, and an
        unfinished one is asked again only from its last confirmed reading on (`_STEADY`), so a later read reads only
        the rows after it (ROWS_READ counts them). Two statements for all the asks: the bindings, and one on the
        hypertable's (channel_no, ts) key (farm/water/sources.py, freshness.temperature_until)."""
        everything = {target for targets, _start, _value, _until in asks for target in targets}
        bindings = list(_bindings(everything).filter(channel__quantity=code)) if asks else []
        found, rows, keys = [None] * len(asks), [], {}
        for index, (targets, start, value, until) in enumerate(asks):
            paired = [binding for binding in bindings if _target(binding) in targets and binding.valid_from <= until
                      and (binding.valid_to is None or binding.valid_to > start)]
            if not paired:
                continue
            key = (code, tuple(sorted((binding.channel.channel_no, binding.valid_from, binding.valid_to,
                                       binding.channel.fresh_s) for binding in paired)),
                   start, str(value), str(band), tolerance)
            kept = _STEADY.get(key)
            if kept is not None and kept['final'] is not None:
                found[index] = kept['final']
                continue
            keys[index] = key
            through = kept['through'] if kept is not None else None
            rows += [(index, binding.channel.channel_no, binding.valid_from, binding.valid_to, binding.channel.fresh_s,
                      start, str(value), until, through) for binding in paired]
        if not rows:
            return found
        columns = list(zip(*rows))
        with connection.cursor() as cursor:
            cursor.execute(
                'WITH q AS (SELECT * FROM unnest(%(asks)s::integer[], %(channels)s::integer[], %(froms)s::timestamptz[], '
                '%(tos)s::timestamptz[], %(fresh)s::integer[], %(starts)s::timestamptz[], %(values)s::numeric[], '
                '%(untils)s::timestamptz[], %(throughs)s::timestamptz[]) '
                'AS q(ask, channel_no, valid_from, valid_to, fresh_s, start, wanted, until, through)), '
                'r AS (SELECT q.ask, q.start, q.wanted, q.fresh_s, q.through, r.ts, r.value FROM q '
                'JOIN sensors_reading r ON r.channel_no = q.channel_no '
                'AND r.ts >= greatest(q.valid_from, coalesce(q.through, q.start - make_interval(secs => q.fresh_s))) '
                'AND r.ts <= q.until AND (q.valid_to IS NULL OR r.ts < q.valid_to) '
                f'AND (r.quality & {BAD_MASK}) = 0), '
                'f AS (SELECT ask, CASE WHEN bool_or(through IS NOT NULL) THEN min(ts) '
                'ELSE coalesce(max(ts) FILTER (WHERE ts <= start), '
                'min(ts) FILTER (WHERE ts > start AND ts <= start + %(tolerance)s)) END AS first FROM r GROUP BY ask), '
                'o AS (SELECT r.*, lead(r.ts) OVER (PARTITION BY r.ask ORDER BY r.ts) AS next FROM r '
                'JOIN f ON f.ask = r.ask WHERE f.first IS NOT NULL AND r.ts >= f.first), '
                'e AS (SELECT ask, value, CASE WHEN abs(value::numeric - wanted) > %(band)s::numeric THEN ts '
                'ELSE ts + make_interval(secs => fresh_s) END AS ends, '
                "CASE WHEN abs(value::numeric - wanted) > %(band)s::numeric THEN 'band' "
                "WHEN next IS NULL THEN 'last' ELSE 'gap' END AS kind FROM o "
                'WHERE abs(value::numeric - wanted) > %(band)s::numeric OR next IS NULL '
                'OR next - ts > make_interval(secs => fresh_s)), '
                'c AS (SELECT ask, count(*) AS n, max(ts) AS last FROM o GROUP BY ask) '
                'SELECT DISTINCT ON (e.ask) e.ask, e.ends, e.kind, e.value, c.n, c.last FROM e JOIN c ON c.ask = e.ask '
                'ORDER BY e.ask, e.ends',
                {'asks': list(columns[0]), 'channels': list(columns[1]), 'froms': list(columns[2]),
                 'tos': list(columns[3]), 'fresh': list(columns[4]), 'starts': list(columns[5]),
                 'values': list(columns[6]), 'untils': list(columns[7]), 'throughs': list(columns[8]),
                 'tolerance': tolerance, 'band': str(band)})
            answered = cursor.fetchall()
        if len(_STEADY) > STEADY_KEPT:
            _STEADY.clear()
        for index, ends, kind, value, count, last in answered:
            ROWS_READ[0] += count
            found[index] = (ends, kind, value)
            _STEADY[keys[index]] = ({'final': found[index], 'through': None} if kind != 'last'
                                    else {'final': None, 'through': last})
        return found


PROVIDER = SensorSource()

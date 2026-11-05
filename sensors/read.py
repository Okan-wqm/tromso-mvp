"""THE read API of the sensor values. Nothing here writes; nothing else reads the readings, the rollups or the state.

- `latest(channel_nos, now)`: each channel's last good value from `sensors_channel_state` (never the hypertable), fresh
  for the channel's `fresh_s` (three heartbeats) after it was received;
- `value_at(channel_no, moment)`: the newest clean reading at or before a moment, never one from after it (a stored value
  stands until the next one: the deadband stores a value when it moves);
- `segments(target, quantity, start, end)`: the channels bound to a target over a window, each clipped to the time it was
  there, in the order they count (A1: the point's own, primary then backup, then the system's); a moved sensor gives one
  segment per place;
- `series(target, quantity, start, end)`: the buckets a chart draws. The bucket width is the window over `max_points`
  snapped up to the LADDER (each width a multiple of the one before, so regrouping is exact); below an hour the clean
  readings themselves are bucketed (no minute rollup: the plan's gate removed it, migration 0003), up to a day the hour
  rollup, and days and weeks are the site's local days built from the hours (a day the clocks go back has 25 hours). Every bucket's mean is
  sum(sum)/sum(n) and its range the runs' extremes: exact, never a mean of means. Per bucket the first segment in order
  that has data is drawn; a backup or the system's channel only where the ones before it have none, and the bucket says
  which. A gap is a spacing between two drawn values longer than the channel's freshness: it is shown, never filled;
- `gaps(buckets, start, end, now)`: those gaps;
- `device_status(devices, now)`: online while a message came within three times the device's interval.

A unit's chart reads its middle point's channels, then its system's; a system's, the system's and its loop's; a point's,
its own (and the system's when it is a system's middle point); a piece of equipment's, its own. Bucket boundaries are on
the tier's grid: a sensor moved in the middle of an hour is counted in the hour rollup at the place its hour began."""
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone as dt_timezone

from django.db import connection
from django.db.models import Q
from django.utils import timezone

from farm.models import Equipment, SamplingPoint, System, Tank, WaterMeasurement
from farm.models.site import zone_of
from farm.models.water_point import PointKind, site_of
from farm.water import deffeyes, parameters
from farm.water.evaluate import is_fresh
from farm.water.read import WINDOW, Series as WaterSeries, assumed_salinity

from . import quantities
from .models import Binding, Calibration, Channel, ChannelState, DeviceState, Reduction
from .quality import BAD_MASK

MAX_POINTS, CAP = 600, 1500
SECOND, MINUTE, HOUR, DAY = timedelta(seconds=1), timedelta(minutes=1), timedelta(hours=1), timedelta(days=1)
LADDER = [SECOND, 5 * SECOND, 15 * SECOND, 30 * SECOND, MINUTE, 5 * MINUTE, 15 * MINUTE, 30 * MINUTE, HOUR, 3 * HOUR,
          6 * HOUR, 12 * HOUR, DAY, 7 * DAY]
RAW, ROLLUP_1H, LOCAL_DAY = 'raw', '1h', 'day'
# Where a segment's channel is bound, in the order the places count (A1).
SENSOR, SYSTEM_SENSOR, EQUIPMENT_SENSOR = 'sensor', 'system_sensor', 'equipment_sensor'
ORIGIN_RANK = {SENSOR: 0, SYSTEM_SENSOR: 1, EQUIPMENT_SENSOR: 0}
ROLE_RANK = {'primary': 0, 'backup': 1}
DEVICE_OFFLINE_INTERVALS = 3


# ---- latest and a moment -------------------------------------------------------------------------------------
@dataclass(frozen=True)
class State:
    channel_no: int
    value: float | None
    at: datetime | None            # the device time of the value
    good_at: datetime | None       # when the last good value was received
    seen_at: datetime | None
    quality: int | None
    fresh_s: int
    now: datetime

    @property
    def fresh(self):
        """Fresh while both the device time of the value and its receipt are within the channel's freshness: a gateway
        replaying an old backlog delivers values received now but measured long ago, which are not fresh."""
        if self.good_at is None or self.at is None:
            return False
        return self.now - min(self.good_at, self.at) <= timedelta(seconds=self.fresh_s)


def latest(channel_nos, now=None):
    """{channel_no: State} of the channels given (a channel the ingest has not written yet has no value)."""
    now = now or timezone.now()
    channel_nos = list(channel_nos)
    fresh = dict(Channel.all_objects.filter(channel_no__in=channel_nos).values_list('channel_no', 'fresh_s'))
    states = ChannelState.objects.in_bulk(channel_nos)
    found = {}
    for number in channel_nos:
        state = states.get(number)
        found[number] = State(number, getattr(state, 'last_value', None), getattr(state, 'last_value_ts', None),
                              getattr(state, 'last_good_at', None), getattr(state, 'last_seen_at', None),
                              getattr(state, 'last_quality', None), fresh.get(number, 0), now)
    return found


def value_at(channel_no, moment):
    """(ts, value) of the channel's newest clean reading at or before `moment`; None when it has none."""
    with connection.cursor() as cursor:
        cursor.execute(f'SELECT ts, value FROM sensors_reading WHERE channel_no = %s AND ts <= %s '
                       f'AND (quality & {BAD_MASK}) = 0 ORDER BY ts DESC LIMIT 1', [channel_no, moment])
        row = cursor.fetchone()
    return (row[0], row[1]) if row else None


# ---- where a target's values come from ------------------------------------------------------------------------
@dataclass(frozen=True)
class Segment:
    channel_no: int
    start: datetime
    end: datetime
    role: str
    origin: str
    fresh_s: int
    reduced: bool                 # deadband: a stored row may stand for messages up to a heartbeat before it
    moved_in: bool                # the binding started inside the window (a move or a first binding)


def places(target):
    """[(Q over bindings, origin)] of a target, in the order they count, and the sampling points whose manual samples
    belong on its chart."""
    if isinstance(target, Tank):
        point = SamplingPoint.objects.filter(unit=target, kind=PointKind.MIDDLE, is_active=True).first()
        found = [(Q(point=point), SENSOR)] if point else []
        if target.system_id:
            found.append((Q(system_id=target.system_id), SYSTEM_SENSOR))
        return found, [point] if point else []
    if isinstance(target, SamplingPoint):
        found = [(Q(point=target), SENSOR)]
        if target.kind == PointKind.MIDDLE and target.system_id:
            found.append((Q(system_id=target.system_id), SYSTEM_SENSOR))
        return found, [target]
    if isinstance(target, System):
        loop = SamplingPoint.objects.filter(system=target, kind=PointKind.MIDDLE, is_active=True).first()
        found = [(Q(system=target), SYSTEM_SENSOR)]
        if loop:
            found.append((Q(point=loop), SENSOR))
        return found, [loop] if loop else []
    if isinstance(target, Equipment):
        return [(Q(equipment=target), EQUIPMENT_SENSOR)], []
    raise TypeError(f'No sensor values for {type(target).__name__}')


def segments(target, quantity, start, end):
    """[Segment] of the channels of `quantity` bound to the target between start and end, in the order they count."""
    found = []
    for rank, (condition, origin) in enumerate(places(target)[0]):
        bindings = (Binding.objects.visible().filter(condition, channel__quantity=quantity, valid_from__lt=end)
                    .filter(Q(valid_to__isnull=True) | Q(valid_to__gt=start)).select_related('channel'))
        for binding in bindings:
            found.append((rank, ROLE_RANK.get(binding.role, 2), Segment(
                binding.channel.channel_no, max(binding.valid_from, start), min(binding.valid_to or end, end),
                binding.role, origin, binding.channel.fresh_s, binding.channel.reduction == Reduction.DEADBAND,
                binding.valid_from > start)))
    found.sort(key=lambda item: (item[0], item[1], item[2].start))
    return [segment for _rank, _role, segment in found]


# ---- the series -----------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Bucket:
    start: datetime
    end: datetime
    avg: float
    vmin: float
    vmax: float
    n: int
    first_ts: datetime
    last_ts: datetime
    channel_no: int
    role: str
    origin: str
    fresh_s: int


@dataclass(frozen=True)
class Marker:
    at: datetime
    kind: str                    # 'move' or 'calibration'
    channel_no: int


@dataclass
class Chart:
    target: object
    quantity: quantities.Quantity
    start: datetime
    end: datetime
    width: timedelta
    tier: str
    zone: object
    buckets: list = field(default_factory=list)
    gaps: list = field(default_factory=list)
    samples: list = field(default_factory=list)     # [(at, value)] of the manual and lab samples
    markers: list = field(default_factory=list)
    reduced: bool = False
    segments: list = field(default_factory=list)

    @property
    def empty(self):
        return not self.buckets


def width_for(start, end, max_points=MAX_POINTS):
    """The ladder's narrowest width that draws the window in at most `max_points` buckets (capped at CAP)."""
    wanted = (end - start) / min(max(max_points, 1), CAP)
    return next((width for width in LADDER if width >= wanted), LADDER[-1])


def tier_of(width):
    return RAW if width < HOUR else ROLLUP_1H if width < DAY else LOCAL_DAY


def chart_rows(segment, width, tier, zone):
    """The segment's buckets: (start, n, sum, min, max, first, last), clean values only."""
    if tier == RAW:
        sql = (f'SELECT time_bucket(%s, ts) AS b, sum(n)::bigint, sum(coalesce(run_sum, value)), '
               f'min(coalesce(run_min, value)), max(coalesce(run_max, value)), min(ts), max(ts) FROM sensors_reading '
               f'WHERE channel_no = %s AND ts >= %s AND ts < %s AND (quality & {BAD_MASK}) = 0 GROUP BY b ORDER BY b')
        params = [width, segment.channel_no, segment.start, segment.end]
    else:
        bucket = 'time_bucket(%s, bucket, %s)' if tier == LOCAL_DAY else 'time_bucket(%s, bucket)'
        sql = (f'SELECT {bucket} AS b, sum(n)::bigint, sum(sum_v), min(vmin), max(vmax), min(first_ts), max(last_ts) '
               f'FROM sensors_rollup_1h '
               f'WHERE channel_no = %s AND bucket >= %s AND bucket < %s GROUP BY b ORDER BY b')
        params = [width, *([zone.key] if tier == LOCAL_DAY else []), segment.channel_no, segment.start, segment.end]
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall()


def _bucket_end(start, width, tier, zone):
    if tier != LOCAL_DAY:
        return start + width
    local = start.astimezone(zone)
    days = width // DAY
    return datetime.combine(local.date() + timedelta(days=days), local.time(), tzinfo=zone).astimezone(dt_timezone.utc)


def zone_for(target):
    """The clock of the target's site (the company's for a department without a site)."""
    return zone_of(site_of(target))


def series(target, quantity, start, end, *, max_points=MAX_POINTS, now=None):
    """The Chart of a target's `quantity` between start and end (end after start)."""
    if end <= start:
        raise ValueError('The end comes after the start.')
    now = now or timezone.now()
    zone = zone_for(target)
    width = width_for(start, end, max_points)
    tier = tier_of(width)
    found = segments(target, quantity, start, end)
    chosen = {}
    for segment in found:
        for row in chart_rows(segment, width, tier, zone):
            begin, n, total, low, high, first, last = row
            if begin in chosen or not n:
                continue
            chosen[begin] = Bucket(begin, _bucket_end(begin, width, tier, zone), total / n, low, high, int(n), first,
                                   last, segment.channel_no, segment.role, segment.origin, segment.fresh_s)
    buckets = [chosen[begin] for begin in sorted(chosen)]
    chart = Chart(target, quantities.get(quantity), start, end, width, tier, zone, buckets,
                  gaps(buckets, start, end, now), segments=found, reduced=any(s.reduced for s in found))
    chart.samples = _samples(target, quantity, start, end)
    channel_nos = {segment.channel_no for segment in found}
    chart.markers = sorted(
        [Marker(segment.start, 'move', segment.channel_no) for segment in found if segment.moved_in]
        + [Marker(at, 'calibration', number) for at, number in Calibration.objects.filter(
            channel__channel_no__in=channel_nos, valid_from__gt=start, valid_from__lt=end)
           .values_list('valid_from', 'channel__channel_no')], key=lambda marker: marker.at)
    return chart


def gaps(buckets, start, end, now):
    """[(from, to)]: spacings between drawn values longer than the channel's freshness, and before the first and after the
    last one inside the window (up to now). Never filled."""
    if not buckets:
        return []
    found = []
    limit = min(end, now)
    if buckets[0].first_ts - start > timedelta(seconds=buckets[0].fresh_s):
        found.append((start, buckets[0].first_ts))
    for before, after in zip(buckets, buckets[1:]):
        if after.first_ts - before.last_ts > timedelta(seconds=before.fresh_s):
            found.append((before.last_ts, after.first_ts))
    if limit - buckets[-1].last_ts > timedelta(seconds=buckets[-1].fresh_s):
        found.append((buckets[-1].last_ts, limit))
    return found


def _samples(target, quantity, start, end):
    """[(at, value)] of the manual and lab samples of a water quantity at the target's points."""
    if quantity not in parameters.COLUMNS:
        return []
    points = [point for point in places(target)[1] if point is not None]
    if not points:
        return []
    return list(WaterMeasurement.objects.filter(point__in=points, measured_at__gte=start, measured_at__lt=end,
                                                **{f'{quantity}__isnull': False})
                .order_by('measured_at').values_list('measured_at', quantity))


def bound_quantities(target, start, end):
    """The quantities of the channels bound to the target in the window, in the catalogue's order."""
    found = set()
    for condition, _origin in places(target)[0]:
        found |= set(Binding.objects.visible().filter(condition, valid_from__lt=end)
                     .filter(Q(valid_to__isnull=True) | Q(valid_to__gt=start)).values_list('channel__quantity', flat=True))
    return [code for code in quantities.CODES if code in found]


# ---- devices ---------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class DeviceStatus:
    online: bool
    last_message_at: datetime | None
    last_seq: int | None


def device_status(devices, now=None):
    """{device id: DeviceStatus}: online while its last message is at most three expected intervals old."""
    now = now or timezone.now()
    devices = list(devices)
    states = DeviceState.objects.in_bulk([device.pk for device in devices])
    intervals = dict(type(devices[0]).all_objects.filter(pk__in=[d.pk for d in devices])
                     .values_list('pk', 'expected_interval_s')) if devices else {}
    found = {}
    for device in devices:
        state = states.get(device.pk)
        last = state.last_message_at if state else None
        limit = timedelta(seconds=DEVICE_OFFLINE_INTERVALS * intervals.get(device.pk, device.expected_interval_s))
        found[device.pk] = DeviceStatus(last is not None and now - last <= limit, last, state.last_seq if state else None)
    return found


# ---- the Deffeyes replay (owner amendment A6) ------------------------------------------------------------------
FRAMES_CAP = 2000
REPLAY_INPUTS = (parameters.TEMPERATURE, parameters.PH, 'alkalinity_mg_l', parameters.SALINITY)
MANUAL, ASSUMED = 'manual', 'assumed'
# How far before the range a carried value may come from: the longest heartbeat's freshness (three days).
CARRY = timedelta(days=3)


@dataclass(frozen=True)
class FrameInput:
    value: float
    origin: str                   # 'sensor', 'system_sensor', 'manual', 'assumed'
    age_s: float                  # seconds between its measurement and the frame
    channel_no: int | None = None


@dataclass(frozen=True)
class FramePoint:
    dic: float                    # mmol/L
    alkalinity_meq: float
    ph: float
    co2_mg_l: float


@dataclass(frozen=True)
class Frame:
    at: datetime
    inputs: dict                  # code -> FrameInput
    point: FramePoint | None
    missing: tuple = ()           # the codes without a usable value at that moment


@dataclass
class Frames:
    target: object
    start: datetime
    end: datetime
    step: timedelta
    tier: str
    frames: list = field(default_factory=list)


def replay_step(start, end, step):
    """The ladder's narrowest width at least `step` that gives at most FRAMES_CAP frames."""
    wanted = max(step, (end - start) / FRAMES_CAP)
    return next((width for width in LADDER if width >= wanted), LADDER[-1])


def replay_rows(found, moments, tier):
    """{(segment index, moment): (ts, value)}: each segment's newest clean value at or before each moment taken while
    it was bound there. ONE query for every segment and moment: below an hour a step-after lookup of the readings per
    segment and moment (the primary key's index); above, the hours of the range read once and each moment given the last
    value of the newest hour ENDED by it (never an hour still running at the moment)."""
    if not found or not moments:
        return {}
    numbers = [segment.channel_no for segment in found]
    starts = [segment.start for segment in found]
    ends = [segment.end for segment in found]
    if tier == RAW:
        sql = (f'SELECT s.ord, m.at, r.ts, r.value FROM unnest(%s::timestamptz[]) AS m(at) '
               f'CROSS JOIN unnest(%s::int[], %s::timestamptz[], %s::timestamptz[]) WITH ORDINALITY '
               f'AS s(channel_no, valid_from, valid_to, ord) CROSS JOIN LATERAL ('
               f'SELECT ts, value FROM sensors_reading WHERE channel_no = s.channel_no AND ts <= m.at '
               f'AND ts >= s.valid_from AND ts < s.valid_to AND (quality & {BAD_MASK}) = 0 ORDER BY ts DESC LIMIT 1) r')
        with connection.cursor() as cursor:
            cursor.execute(sql, [moments, numbers, starts, ends])
            return {(int(ordinal) - 1, at): (ts, value) for ordinal, at, ts, value in cursor.fetchall()}
    with connection.cursor() as cursor:
        cursor.execute('SELECT channel_no, bucket, last_ts, vlast FROM sensors_rollup_1h WHERE channel_no = ANY(%s) '
                       'AND bucket >= %s AND bucket < %s ORDER BY channel_no, bucket',
                       [list(set(numbers)), min(starts), max(moments)])
        hours = {}
        for number, bucket, last_ts, value in cursor.fetchall():
            hours.setdefault(number, []).append((bucket, last_ts, value))
    found_rows = {}
    for index, segment in enumerate(found):
        rows = [row for row in hours.get(segment.channel_no, []) if segment.start <= row[0] < segment.end]
        ended = [row[0] + HOUR for row in rows]
        for at in moments:
            position = bisect_right(ended, at) - 1
            if position >= 0:
                found_rows[(index, at)] = (rows[position][1], rows[position][2])
    return found_rows


def _water_types(target):
    """The water types a target's water is in: a unit's own, a system's units' (none: nothing is assumed)."""
    if isinstance(target, Tank):
        return {target.water_type}
    if isinstance(target, System):
        return set(Tank.objects.filter(system=target).values_list('water_type', flat=True)) or {None}
    return {None}


def deffeyes_frames(target, start, end, step):
    """The Frames of a unit's or a system's water from start to end (end not included) every `step` (snapped to the
    ladder, at most FRAMES_CAP frames): per frame and input, in the A1 order, the first segment's clean value at or
    before the frame and no older than its channel's freshness, else a fresh manual or lab sample, else (salinity only)
    the fresh-water assumption, else missing; the point on the diagram from farm/water/deffeyes.py when every input is
    there. Never a value from after the frame, never one carried past its freshness, never one in between."""
    if end <= start:
        raise ValueError('The end comes after the start.')
    step = replay_step(start, end, step)
    tier = RAW if step < HOUR else ROLLUP_1H
    moments = []
    moment = start
    while moment < end:
        moments.append(moment)
        moment += step
    by_code = {code: segments(target, code, start - CARRY, end) for code in REPLAY_INPUTS}
    flat = [(code, segment) for code in REPLAY_INPUTS for segment in by_code[code]]
    rows = replay_rows([segment for _code, segment in flat], moments, tier)
    points = [point for point in places(target)[1] if point is not None]
    manual = {code: WaterSeries(points, code, start - WINDOW, end) for code in REPLAY_INPUTS}
    assumed = assumed_salinity(_water_types(target))
    found = Frames(target, start, end, step, tier)
    for at in moments:
        inputs, missing = {}, []
        for code in REPLAY_INPUTS:
            chosen = None
            for index, (each, segment) in enumerate(flat):
                if each != code or (index, at) not in rows:
                    continue
                ts, value = rows[(index, at)]
                if at - ts <= timedelta(seconds=segment.fresh_s):
                    chosen = FrameInput(value, segment.origin, (at - ts).total_seconds(), segment.channel_no)
                    break
            if chosen is None:
                sample = next((each for each in (manual[code].latest(point.pk, at, WINDOW) for point in points)
                               if each is not None and is_fresh(parameters.get(code), each.at, at)), None)
                if sample is not None:
                    chosen = FrameInput(float(sample.value), MANUAL, (at - sample.at).total_seconds())
                elif code == parameters.SALINITY and assumed is not None:
                    chosen = FrameInput(float(assumed), ASSUMED, 0.0)
            if chosen is None:
                missing.append(code)
            else:
                inputs[code] = chosen
        point = None
        if not missing:
            analysis = deffeyes.analyse(deffeyes.Water(
                temperature_c=inputs[parameters.TEMPERATURE].value, salinity_ppt=inputs[parameters.SALINITY].value,
                ph=inputs[parameters.PH].value, alkalinity_mg_l=inputs['alkalinity_mg_l'].value))
            point = FramePoint(analysis.dic, analysis.alkalinity_meq, inputs[parameters.PH].value, analysis.co2_mg_l)
        found.frames.append(Frame(at, inputs, point, tuple(missing)))
    return found

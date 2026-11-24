"""THE read API of the sensor values. Nothing here writes; nothing else reads the readings, the rollups or the state.

- `latest(channel_nos, now)`: each channel's last good value from `sensors_channel_state` (never the hypertable), fresh
  while both its device time and its receipt are at most the channel's `fresh_s` old (its heartbeat times its own
  `fresh_heartbeats`: 3 unless the farm set another, 1 to 20);
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
its own (and the system's when it is a system's middle point); a piece of equipment's, its own. A place has exactly the
readings taken while a channel was bound there, at every tier: on the hour tiers the whole hours of a binding come from
the rollup and the parts of an hour it only partly holds (a move, a device taken out, a window's edge) from the readings
(`hours_of`), so an hour that holds a move is shared by the two places."""
from bisect import bisect_right
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone as dt_timezone

from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from farm.models import Equipment, SamplingPoint, System, Tank, WaterMeasurement
from farm.models.site import zone_of
from farm.models.water_point import PointKind, site_of
from farm.models.water import NBS
from farm.water import calculation, deffeyes, messages, parameters
from farm.water.evaluate import is_fresh
from farm.water.parameters import PH
from farm.water.read import (OWN_WATER_KINDS, WINDOW, Series as WaterSeries, as_parameter, assumed_salinity, choose,
                             ph_on_nbs)

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
    ph_scale: str = ''            # a pH channel's scale when not NBS (sensors.Channel.ph_scale), else ''
    ph_scale_from: datetime | None = None    # when that pH channel's scale changed (its values from before: none)


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


def tiers(target):
    """[([(Q over bindings, origin)], [SamplingPoint])]: the tiers of owner rule A9 (`farm.water.read.choose`) for a
    target's water, in the order they count, each with the bindings and the points whose samples are in it, exactly
    the places the live view reads (farm/water/read.py `_places`): a unit's own-water points (middle first; never the
    inlet), then its system's (the system's sensors, those on its loop point, the loop's samples); a system's loop and
    its sensors; any other point or a piece of equipment its own alone."""
    if isinstance(target, SamplingPoint) and target.unit_id and target.kind == PointKind.MIDDLE:
        target = target.unit
    if isinstance(target, Tank):
        own = list(SamplingPoint.objects.filter(unit=target, is_active=True,
                                                kind__in=[PointKind.MIDDLE, *OWN_WATER_KINDS]).with_owners())
        own.sort(key=lambda point: (point.kind != PointKind.MIDDLE, point.name))
        found = [([(Q(point__in=own), SENSOR)] if own else [], own)]
        if target.system_id:
            loop = SamplingPoint.objects.filter(system_id=target.system_id, kind=PointKind.MIDDLE,
                                                is_active=True).with_owners().first()
            found.append(([(Q(system_id=target.system_id), SYSTEM_SENSOR),
                           *([(Q(point=loop), SYSTEM_SENSOR)] if loop else [])], [loop] if loop else []))
        return found
    return [places(target)]


def segments(target, quantity, start, end):
    """[Segment] of the channels of `quantity` bound to the target between start and end, in the order they count."""
    return segments_for(places(target)[0], quantity, start, end)


def segments_for(conditions, quantity, start, end):
    """[Segment] of the channels of `quantity` bound by `conditions` ([(Q over bindings, origin)]) between start and
    end, in the order they count (`segments_and_cuts`)."""
    return segments_and_cuts(conditions, quantity, start, end)[0]


def segments_and_cuts(conditions, quantity, start, end):
    """([Segment], [(channel number, the change)]): the segments of `segments_for` and the pH channels whose values in the
    window from before their last change of pH scale were left out, each once (a chart says it even when nothing is
    left to draw: the review of the water-chemistry audit, C4). A pH channel's segment starts no earlier than its last
    change of pH scale (`Channel.ph_scale_from`): what it measured before is on a scale not known any more, and is
    drawn and used nowhere (the water-chemistry audit of 2026-11-19, F1); it says its scale when not NBS
    (`Segment.ph_scale`)."""
    found, cuts = [], {}
    for rank, (condition, origin) in enumerate(conditions):
        bindings = (Binding.objects.visible().filter(condition, channel__quantity=quantity, valid_from__lt=end)
                    .filter(Q(valid_to__isnull=True) | Q(valid_to__gt=start)).select_related('channel'))
        for binding in bindings:
            channel = binding.channel
            begin, finish = max(binding.valid_from, start), min(binding.valid_to or end, end)
            scale, since = '', None
            if channel.quantity == PH:
                scale, since = ('' if channel.ph_scale == NBS else channel.ph_scale), channel.ph_scale_from
                if since is not None and since > begin:
                    cuts[channel.channel_no, since] = None          # some of its time here is before the change
                    begin = since
            if begin >= finish:
                continue
            found.append((rank, ROLE_RANK.get(binding.role, 2), Segment(
                channel.channel_no, begin, finish, binding.role, origin, channel.fresh_s,
                channel.reduction == Reduction.DEADBAND, binding.valid_from > start, scale, since)))
    found.sort(key=lambda item: (item[0], item[1], item[2].start))
    return [segment for _rank, _role, segment in found], list(cuts)


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
    kind: str                    # 'move', 'calibration' or 'ph_scale' (a pH channel's scale changed)
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
    samples: list = field(default_factory=list)     # [(at, value, source)] of the manual and lab samples
    markers: list = field(default_factory=list)
    reduced: bool = False
    segments: list = field(default_factory=list)
    cuts: list = field(default_factory=list)        # [(channel number, its pH scale's change)]: values left out before it

    @property
    def empty(self):
        return not self.buckets


def width_for(start, end, max_points=MAX_POINTS):
    """The ladder's narrowest width that draws the window in at most `max_points` buckets (capped at CAP)."""
    wanted = (end - start) / min(max(max_points, 1), CAP)
    return next((width for width in LADDER if width >= wanted), LADDER[-1])


def tier_of(width):
    return RAW if width < HOUR else ROLLUP_1H if width < DAY else LOCAL_DAY


def _hour(moment):
    """The start of the UTC hour `moment` is in (the hour rollup's bucket)."""
    return moment.astimezone(dt_timezone.utc).replace(minute=0, second=0, microsecond=0)


def hours_of(segment):
    """((first, last), [(from, to)]): the whole hours inside the segment, which the hour rollup gives exactly, and the
    parts of the hours it only partly holds (where a binding began or ended inside an hour: a move, a window's edge),
    read from the raw readings, so an hour that holds a move is shared by the two places, never given whole to one.
    Each part lies inside one hour (the replay keys it by that hour, which ends after every reading in it)."""
    first = _hour(segment.start)
    if first < segment.start:
        first += HOUR
    last = _hour(segment.end)
    if last <= first:
        # No whole hour: the stay is inside one hour, or crosses one boundary (01:30-02:20): one part per hour.
        cut = min(first, segment.end)
        return (first, first), [(start, end) for start, end in ((segment.start, cut), (cut, segment.end)) if start < end]
    return (first, last), [(start, end) for start, end in ((segment.start, first), (last, segment.end)) if start < end]


def chart_rows(segment, width, tier, zone):
    """The segment's buckets: (start, n, sum, min, max, first, last), clean values only. On the hour tiers the whole
    hours come from the rollup and the parts of hours from the readings (`hours_of`). Each sum adds its rows in time
    order: a float sum in whatever order the database meets the rows (parallel workers) differed in its last digit
    from one read to the next, so the same chart and its CSV were not the same twice."""
    clean = f'(quality & {BAD_MASK}) = 0'
    if tier == RAW:
        sql = (f'SELECT time_bucket(%s, ts) AS b, sum(n)::bigint, sum(coalesce(run_sum, value) ORDER BY ts), '
               f'min(coalesce(run_min, value)), max(coalesce(run_max, value)), min(ts), max(ts) FROM sensors_reading '
               f'WHERE channel_no = %s AND ts >= %s AND ts < %s AND {clean} GROUP BY b ORDER BY b')
        params = [width, segment.channel_no, segment.start, segment.end]
    else:
        local = [zone.key] if tier == LOCAL_DAY else []
        on = ', %s' if tier == LOCAL_DAY else ''
        (first, last), parts = hours_of(segment)
        parts = (parts + [(segment.start, segment.start)] * 2)[:2]
        sql = (f'SELECT b, sum(n)::bigint, sum(s ORDER BY f, s), min(lo), max(hi), min(f), max(l) FROM ('
               f'SELECT time_bucket(%s, bucket{on}) AS b, n, sum_v AS s, vmin AS lo, vmax AS hi, first_ts AS f, '
               f'last_ts AS l FROM sensors_rollup_1h WHERE channel_no = %s AND bucket >= %s AND bucket < %s '
               f'UNION ALL SELECT time_bucket(%s, ts{on}), n, coalesce(run_sum, value), coalesce(run_min, value), '
               f'coalesce(run_max, value), ts, ts FROM sensors_reading WHERE channel_no = %s AND {clean} '
               f'AND ((ts >= %s AND ts < %s) OR (ts >= %s AND ts < %s))) parts GROUP BY b ORDER BY b')
        params = [width, *local, segment.channel_no, first, last, width, *local, segment.channel_no,
                  *parts[0], *parts[1]]
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
    found, cuts = segments_and_cuts(places(target)[0], quantity, start, end)
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
                  gaps(buckets, start, end, now), segments=found, reduced=any(s.reduced for s in found), cuts=cuts)
    chart.samples = _samples(target, quantity, start, end)
    channel_nos = {segment.channel_no for segment in found}
    scale_changes = {(segment.ph_scale_from, segment.channel_no) for segment in found
                     if segment.ph_scale_from is not None and start < segment.ph_scale_from < end}
    chart.markers = sorted(
        [Marker(segment.start, 'move', segment.channel_no) for segment in found if segment.moved_in]
        + [Marker(at, 'calibration', number) for at, number in Calibration.objects.filter(
            channel__channel_no__in=channel_nos, valid_from__gt=start, valid_from__lt=end)
           .values_list('valid_from', 'channel__channel_no')]
        + [Marker(at, 'ph_scale', number) for at, number in scale_changes], key=lambda marker: marker.at)
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
    """[(at, value, source)] of the manual and lab samples of a water quantity at the target's points (source: 'manual'
    or 'lab', farm.WaterMeasurement.Source)."""
    if quantity not in parameters.COLUMNS:
        return []
    points = [point for point in places(target)[1] if point is not None]
    if not points:
        return []
    return list(WaterMeasurement.objects.filter(point__in=points, measured_at__gte=start, measured_at__lt=end,
                                                **{f'{quantity}__isnull': False})
                .order_by('measured_at').values_list('measured_at', quantity, 'source'))


def bound_quantities(target, start, end):
    """The quantities of the channels bound to the target in the window, in the catalogue's order."""
    found = set()
    for condition, _origin in places(target)[0]:
        found |= set(Binding.objects.visible().filter(condition, valid_from__lt=end)
                     .filter(Q(valid_to__isnull=True) | Q(valid_to__gt=start)).values_list('channel__quantity', flat=True))
    return [code for code in quantities.CODES if code in found]


# ---- a place's water history (Tank › Water, System › Water) ------------------------------------------------------
BANDS = (('critical_low', max), ('warning_low', max), ('warning_high', min), ('critical_high', min))
WORKED = (parameters.NH3_N.code,)       # worked out from each sample by the water read, never measured


@dataclass(frozen=True)
class Worked:
    """A value worked out from one sample (its NH₃-N from its TAN, pH and temperature): the value with its status, or
    None with the reason it could not be worked out (the water read's own words)."""
    at: datetime
    value: float | None
    status: str
    note: str


@dataclass
class History:
    """The water of a place over a window: one Chart per parameter on ONE time axis (`series`: the sensors' buckets and
    gaps, the manual samples, the moves and calibrations), the values worked out from the samples (`worked`, by code),
    and the fish's limits today as bands (`bands`: {code: {bound: float}}, the strictest bound of the species' rows, as
    a value is judged against every row; a code with no row has no band: "no limit", never an assumed one)."""
    target: object
    start: datetime
    end: datetime
    zone: object
    charts: list
    worked: dict
    bands: dict
    judged: dict = field(default_factory=dict)   # {code: {measured_at: status}}: each live sample's value judged


def sampled_codes(target, start, end):
    """The measured parameters with a live manual or lab sample at the target's points (`places`) in the window."""
    points = [point for point in places(target)[1] if point is not None]
    if not points:
        return []
    found = WaterMeasurement.objects.filter(point__in=points, measured_at__gte=start, measured_at__lt=end)
    return [code for code in parameters.COLUMNS if found.filter(**{f'{code}__isnull': False}).exists()]


def bands_of(limits):
    """{code: {bound: float}} of the fish's limit rows ({code: [WaterLimit]}, farm.water.read.limits_now): per bound the
    strictest of the rows that set it (the highest low, the lowest high); a bound no row sets is left out."""
    found = {}
    for code, rows in limits.items():
        bounds = {}
        for bound, pick in BANDS:
            values = [getattr(row, bound) for row in rows if getattr(row, bound) is not None]
            if values:
                bounds[bound] = float(pick(values))
        if bounds:
            found[code] = bounds
    return found


def water_history(target, start, end, *, now=None, max_points=MAX_POINTS):
    """The History of a unit's, a system's or a point's water between start and end: every quantity bound there in the
    window and every parameter sampled there, in the catalogue's order, each the `series` of the same window (the
    charts share one time axis); the NH₃-N worked out from each live sample with a TAN (farm.water.read.history: the
    sample's own pH and temperature, judged as the history page judges it); every live sample's value judged as the
    history page judges it (`judged`: {code: {measured_at: status}}, for the fish of its day); the fish's limits as
    bands."""
    from farm.water import read as water_read

    if end <= start:
        raise ValueError('The end comes after the start.')
    now = now or timezone.now()
    codes = set(bound_quantities(target, start, end)) | set(sampled_codes(target, start, end))
    charts = [series(target, code, start, end, max_points=max_points, now=now)
              for code in quantities.CODES if code in codes]
    worked, judged = {}, {}
    points = [point for point in places(target)[1] if point is not None]
    if points:
        samples = [sample for sample in water_read.samples_of(points=points, since=start, before=end) if not sample.is_deleted]
        for row in reversed(water_read.history(samples)):            # samples_of is newest first: oldest first here
            for code, reading in row.readings.items():
                if code not in WORKED and reading.value is not None:
                    judged.setdefault(code, {})[row.sample.measured_at] = str(reading.status)
            if row.sample.tan_mg_l is None:
                continue
            for code in WORKED:
                reading = row.readings.get(code)
                if reading is not None:
                    worked.setdefault(code, []).append(Worked(
                        row.sample.measured_at, None if reading.value is None else float(reading.value),
                        str(reading.status), str(reading.note or '')))
    place = target.unit if isinstance(target, SamplingPoint) and target.unit_id else target
    return History(target, start, end, zone_for(target), charts, worked, bands_of(water_read.limits_now(place)), judged)


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


# ---- the Deffeyes replay (owner amendments A6, A7, A8) ---------------------------------------------------------
PAGE = 2000                   # frames at most in one page
# What a frame reads: what a unit's chart is drawn from (farm/water/calculation.py), the required first.
REPLAY_INPUTS = (*calculation.REQUIRED, *calculation.OPTIONAL)
MANUAL, ASSUMED = 'manual', 'assumed'
# How far before the range a carried value may come from: the longest heartbeat's freshness (three days).
CARRY = timedelta(days=3)


@dataclass(frozen=True)
class FrameInput:
    value: float
    origin: str                   # 'sensor', 'system_sensor', 'manual', 'assumed'
    age_s: float                  # seconds between its measurement and the frame
    channel_no: int | None = None
    ph_scale: str = ''            # a pH from a channel on another scale: that scale (`value` is then on NBS)
    as_measured: float | None = None    # such a pH as the probe measured it


@dataclass(frozen=True)
class Candidate:
    """A value one source gave for a frame (`read.choose` reads its `at`)."""
    at: datetime
    input: FrameInput


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
    missing: tuple = ()           # the required codes without a usable value at that moment
    impossible: str = ''          # why the pH and the alkalinity cannot go together (deffeyes.why_impossible)
    figure: int | None = None     # the index of its diagram in Frames.figures


@dataclass
class Frames:
    """One page of a replay: frames `cursor` to `next` (None: the last page) of `total`."""
    target: object
    start: datetime
    end: datetime
    step: timedelta
    tier: str
    total: int
    cursor: int
    next: int | None
    frames: list = field(default_factory=list)
    figures: list = field(default_factory=list)   # deffeyes.figure of each different water of the page


def replay_step(step):
    """The ladder's narrowest width at least `step` (the user's step is kept, never widened to fit a cap: A7)."""
    return next((width for width in LADDER if width >= step), LADDER[-1])


def replay_rows(found, first, step, count, tier):
    """{(segment index, frame index): (ts, value)}: each segment's value at each of `count` moments from `first` every
    `step`, taken while it was bound there. ONE query for every segment and moment. Below an hour the live view's rule
    (`value_at`, sensors/provider.py): the newest clean reading at or before the moment, given only when it is no older
    than the channel's freshness (a staler one is never used); above, the hours of the span read once and each moment
    given the last value of the newest hour ENDED by it (never an hour still running at the moment), an hour a segment
    only partly holds giving the last reading of its part (`hours_of`)."""
    if not found or count < 1:
        return {}
    numbers = [segment.channel_no for segment in found]
    starts = [segment.start for segment in found]
    ends = [segment.end for segment in found]
    fresh = [segment.fresh_s for segment in found]
    last = first + (count - 1) * step
    if tier == RAW:
        return _raw_rows(numbers, starts, ends, fresh, first, last, step, count)
    rows = {}
    reach = timedelta(seconds=max(fresh)) + HOUR
    # The parts of hours a segment only partly holds (`hours_of`): each its last clean reading, in the same query.
    spans = [hours_of(segment) for segment in found]
    parts = [(index, _hour(start), start, end) for index, (_whole, edges) in enumerate(spans) for start, end in edges]
    with connection.cursor() as cursor:
        cursor.execute(
            f'SELECT 0, channel_no, bucket, last_ts, vlast FROM sensors_rollup_1h WHERE channel_no = ANY(%s) '
            f'AND bucket >= %s AND bucket < %s '
            f'UNION ALL SELECT e.ord, e.channel_no, e.hour, r.ts, r.value FROM unnest(%s::int[], %s::timestamptz[], '
            f'%s::timestamptz[], %s::timestamptz[]) WITH ORDINALITY AS e(channel_no, hour, lo, hi, ord) '
            f'CROSS JOIN LATERAL (SELECT ts, value FROM sensors_reading WHERE channel_no = e.channel_no '
            f'AND ts >= e.lo AND ts < e.hi AND (quality & {BAD_MASK}) = 0 ORDER BY ts DESC LIMIT 1) r',
            [list(set(numbers)), max(min(starts), first - reach), last,
             [numbers[index] for index, *_rest in parts], [hour for _index, hour, *_rest in parts],
             [start for *_rest, start, _end in parts], [end for *_rest, end in parts]])
        for ordinal, number, bucket, last_ts, value in cursor.fetchall():
            key = ('part', parts[int(ordinal) - 1][0]) if ordinal else number
            rows.setdefault(key, []).append((bucket, last_ts, value))
    found_rows = {}
    for index, segment in enumerate(found):
        (whole_from, whole_to), _edges = spans[index]
        hours = sorted([row for row in rows.get(segment.channel_no, []) if whole_from <= row[0] < whole_to]
                       + rows.get(('part', index), []))
        ended = [row[0] + HOUR for row in hours]
        for slot in range(count):
            position = bisect_right(ended, first + slot * step) - 1
            if position >= 0:
                found_rows[(index, slot)] = (hours[position][1], hours[position][2])
    return found_rows


# A raw page reads its readings in one of two ways, the same values either way (sensors/tests/test_replay.py
# ValueAtTests): at a step this short or shorter every reading of the span, the last of each step kept (about as many
# readings as frames at 1 Hz); at a longer one a look-up per frame and segment, which reads about one reading per frame
# however dense the readings are. Measured read only on the development data (about 1 Hz, nine segments, 2000 frames):
# at 1 s the span's readings 0.3 s, the look-ups 0.6 to 1.2 s; at 60 s the span's readings (sorted) 7 to 9 s, the
# look-ups 0.65 to 0.95 s.
SPAN_STEP = timedelta(seconds=5)
RUNTIME_EXCLUSION = 'timescaledb.enable_runtime_exclusion'


def _raw_rows(numbers, starts, ends, fresh, first, last, step, count):
    """`replay_rows` below an hour (the live view's rule at each moment, `SPAN_STEP` says which way it is read). The
    page's own bounds are constants, so TimescaleDB leaves out the chunks outside them when it plans."""
    since = first - timedelta(seconds=max(fresh))
    segments = ('WITH s AS (SELECT * FROM unnest(%s::int[], %s::timestamptz[], %s::timestamptz[], %s::int[]) '
                'WITH ORDINALITY AS s(channel_no, valid_from, valid_to, fresh_s, ord))')
    # The newest clean reading of a segment at or before a moment `at`, no older than the channel's freshness.
    newest = ('SELECT ts, value FROM sensors_reading WHERE channel_no = s.channel_no AND ts <= {at} '
              'AND ts >= greatest(s.valid_from, {at} - make_interval(secs => s.fresh_s)) AND ts < s.valid_to '
              f'AND ts >= %s AND ts <= %s AND (quality & {BAD_MASK}) = 0 ORDER BY ts DESC LIMIT 1')
    if step <= SPAN_STEP:
        # The newest before the first moment, then per segment and step the last clean reading of the step (the one at
        # or before the moment that ends it), carried to the next moments while it is fresh.
        before = newest.format(at="%s::timestamptz")
        sql = (f'{segments} SELECT s.ord, 0, r.ts, r.value FROM s CROSS JOIN LATERAL ({before}) r '
               f'UNION ALL SELECT s.ord, ceil(extract(epoch FROM r.ts - %s) / %s::numeric)::int AS slot, max(r.ts), '
               f'last(r.value, r.ts) FROM s JOIN sensors_reading r ON r.channel_no = s.channel_no AND r.ts > %s '
               f'AND r.ts <= %s AND r.ts >= s.valid_from AND r.ts < s.valid_to AND (r.quality & {BAD_MASK}) = 0 '
               f'GROUP BY s.ord, slot')
        with connection.cursor() as cursor:
            cursor.execute(sql, [numbers, starts, ends, fresh, first, first, since, first, first,
                                 step.total_seconds(), first, last])
            stepped = {}
            for ordinal, slot, ts, value in cursor.fetchall():
                stepped.setdefault(int(ordinal) - 1, {})[slot] = (ts, value)
        rows = {}
        for index, slots in stepped.items():
            carried, fresh_for = None, timedelta(seconds=fresh[index])
            for slot in range(count):
                carried = slots.get(slot, carried)
                if carried is not None and first + slot * step - carried[0] <= fresh_for:
                    rows[(index, slot)] = carried
        return rows
    # One indexed look-up per segment and moment (the primary key (channel_no, ts) read backwards, one row). The
    # runtime exclusion of TimescaleDB, which would only find again the chunks left out when planning, is switched off
    # for this one query and then set back to what it was (a caller's enclosing transaction keeps its own setting): it
    # cost about 60 µs on every look-up (0.8 s instead of 0.2 s for 10 000 of them on the development data).
    sql = (f'{segments}, m AS (SELECT * FROM unnest(%s::timestamptz[]) WITH ORDINALITY AS m(at, slot)) '
           f'SELECT s.ord, m.slot, r.ts, r.value FROM s CROSS JOIN m CROSS JOIN LATERAL ({newest.format(at="m.at")}) r')
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(f"SELECT current_setting('{RUNTIME_EXCLUSION}'), set_config('{RUNTIME_EXCLUSION}', 'off', true)")
        previous = cursor.fetchone()[0]
        cursor.execute(sql, [numbers, starts, ends, fresh, [first + slot * step for slot in range(count)], since, last])
        found = {(int(ordinal) - 1, int(slot) - 1): (ts, value) for ordinal, slot, ts, value in cursor.fetchall()}
        cursor.execute(f"SELECT set_config('{RUNTIME_EXCLUSION}', %s, true)", [previous])
        return found


def _water_types(target):
    """The water types a target's water is in: a unit's own, a system's units' (none: nothing is assumed)."""
    if isinstance(target, Tank):
        return {target.water_type}
    if isinstance(target, System):
        return set(Tank.objects.filter(system=target).values_list('water_type', flat=True)) or {None}
    return {None}


def deffeyes_frames(target, start, end, step, cursor=0, size=PAGE):
    """A page of the Frames of a unit's or a system's water from start to end (end not included) every `step` (snapped
    up to the ladder): frames `cursor` on, at most `size`. Per frame and input, by owner rule A9 through the live
    view's one function (`farm.water.read.choose`, over the `tiers` of the target): the newest of the fresh values of the
    unit's own places (each channel's clean value at or before the frame and no older than its freshness, each point's
    fresh manual or lab sample), else of its system's, else (salinity only) the fresh-water assumption, else missing; never a value from after the frame, never one carried
    past its freshness, never one in between. A frame with every required input has the whole diagram of that water
    (A8: farm/water/deffeyes.py's figure with the fish's limits, as the unit's chart draws it), in one box for the page
    (it holds every point of the page); frames whose diagram reads exactly the same values share one figure. A pH from
    a channel on another scale than NBS is put on the NBS scale with the frame's own temperature and salinity, as the
    live view does (`_on_nbs`); where it cannot be, the frame has no pH and no diagram, and `impossible` says why."""
    if end <= start:
        raise ValueError('The end comes after the start.')
    step = replay_step(step)
    total = -(-(end - start) // step)
    if not 0 <= cursor < total or size < 1:
        raise ValueError('The cursor is a frame of the range.')
    count = min(size, total - cursor)
    first = start + cursor * step
    tier = RAW if step < HOUR else ROLLUP_1H
    page_end = first + count * step
    tiered = tiers(target)
    flat = [(code, rank, segment) for code in REPLAY_INPUTS for rank, (conditions, _points) in enumerate(tiered)
            for segment in segments_for(conditions, code, first - CARRY, page_end)]
    rows = replay_rows([segment for _code, _rank, segment in flat], first, step, count, tier)
    points = list({point.pk: point for _conditions, found in tiered for point in found}.values())
    manual = {code: WaterSeries(points, code, first - WINDOW, page_end) for code in REPLAY_INPUTS}
    assumed = assumed_salinity(_water_types(target))
    limits = {name: float(offer.value) for name, offer in calculation.chart_limits(calculation.fish_limits(target)).items()}
    water_origin = calculation.origin_of(target)  # one a page, as the unit's chart (round 2, R1)
    ph_origin = calculation.scale_origin_of(target)    # whether a pH on another scale is taken (read.scale_origin)
    found = Frames(target, start, end, step, tier, total, cursor, cursor + count if cursor + count < total else None)
    waters = []
    for slot in range(count):
        at = first + slot * step
        inputs, missing = {}, []
        for code in REPLAY_INPUTS:
            # Owner rule A9 at the frame, by the live view's one function (farm.water.read.choose): the newest FRESH
            # value of the first tier that has one, a sensor's before a sample's at one time; a frame is drawn from fresh
            # values only (A9.3), so a stale one is missing, never shown.
            candidates = [[] for _tier in tiered]
            for index, (each, rank, segment) in enumerate(flat):
                if each != code or (index, slot) not in rows:
                    continue
                ts, value = rows[(index, slot)]
                if at - ts <= timedelta(seconds=segment.fresh_s):
                    candidates[rank].append(Candidate(ts, FrameInput(
                        float(as_parameter(code, value)), segment.origin, (at - ts).total_seconds(), segment.channel_no,
                        segment.ph_scale)))
            for rank, (_conditions, tier_points) in enumerate(tiered):
                for point in tier_points:
                    sample = manual[code].latest(point.pk, at, WINDOW)
                    if sample is not None and is_fresh(parameters.get(code), sample.at, at):
                        candidates[rank].append(Candidate(sample.at, FrameInput(
                            float(sample.value), MANUAL, (at - sample.at).total_seconds())))
            picked = choose(candidates, at, lambda candidate: True)
            chosen = picked.input if picked is not None else None
            if chosen is None and code == parameters.SALINITY and assumed is not None:
                chosen = FrameInput(float(assumed), ASSUMED, 0.0)
            if chosen is not None:
                inputs[code] = chosen
            elif code in calculation.REQUIRED:
                missing.append(code)
        analysis, impossible = None, ''
        if inputs.get(PH) is not None and inputs[PH].ph_scale:
            # A pH on another scale than NBS, put on it with the frame's own temperature and salinity, as the live
            # view does (farm/water/read.py Context.sensor_ph); where it cannot be, no diagram and the reason, never the
            # unconverted number.
            converted, impossible = _on_nbs(inputs[PH], inputs, ph_origin)
            if converted is None:
                del inputs[PH]
            else:
                inputs[PH] = converted
        if not missing and not impossible:
            analysis, impossible = frame_analysis(
                {**{code: item.value for code, item in inputs.items()}, 'water_origin': water_origin}, limits)
        waters.append((at, inputs, tuple(missing), impossible, analysis))
    analyses = [analysis for *_rest, analysis in waters]
    found.figures, indexes = page_figures(analyses)
    for (at, inputs, missing, impossible, analysis), index in zip(waters, indexes):
        point = None if analysis is None else FramePoint(analysis.dic, analysis.alkalinity_meq, analysis.water.ph,
                                                         analysis.co2_mg_l)
        found.frames.append(Frame(at, inputs, point, missing, impossible, index))
    return found


def _on_nbs(found, inputs, origin):
    """(FrameInput of the pH on the NBS scale, '') of a frame's pH from a channel on another scale (`found.ph_scale`),
    put on it with the frame's own temperature and salinity (`inputs`) by the one conversion (farm.water.read.ph_on_nbs);
    (None, why) where it cannot be: no temperature or salinity at the frame, water that takes no such pH, or water the
    core cannot work out (its own reason)."""
    temperature, salinity = inputs.get(parameters.TEMPERATURE), inputs.get(parameters.SALINITY)
    why = 'temperature' if temperature is None else 'salinity' if salinity is None else ''
    if why:
        return None, str(messages.unevaluated_ph(messages.ph_sensor_refused(why, found.ph_scale)))
    converted = ph_on_nbs(found.value, found.ph_scale, temperature.value, salinity.value, origin)
    if converted.value is None:
        return None, str(messages.unevaluated_ph(converted.said(found.ph_scale)))
    return replace(found, value=float(converted.value), as_measured=found.value), ''


def frame_analysis(values, limits):
    """(analysis, '') of a frame's water (`values` by calculator field, its water origin among them, `limits` the fish's by
    field, floats), as a unit's chart works it out; (None, why) when its pH and alkalinity cannot go together."""
    impossible = deffeyes.why_impossible(values[parameters.TEMPERATURE], values[parameters.SALINITY],
                                         values[parameters.PH], values['alkalinity_mg_l'], **calculation.ions_of(values))
    if impossible:
        return None, impossible
    made = calculation.inputs_from({**values, **limits})
    return deffeyes.analyse(made['water'], made['limits'], made['target'], made['pressure']), ''


def page_figures(analyses):
    """([figure], [index or None]) of a page's analyses (None: no diagram): the whole diagram of each, in one box that
    holds every point of the page (its largest DIC and alkalinity, worked out once), worked out once for each different
    diagram. The diagram reads the water's alkalinity only through its equilibria (formula 3: its ionic strength), and
    never its pH or its oxygen, only where its point sits (sensors/tests/test_page_share.py proves it on random waters),
    so frames equal but for those, with the same equilibria, share one figure, its point left out (None): every frame
    carries its own point in its columns."""
    points = [(analysis.dic, analysis.alkalinity_meq) for analysis in analyses if analysis is not None]
    # The box reads only the largest DIC and the largest alkalinity of the points it holds (deffeyes.box_of), so the
    # page's extent is that one point, worked out once (every point on every figure was O(N^2)).
    extent = [(max(dic for dic, _alkalinity in points), max(alkalinity for _dic, alkalinity in points))] if points else []
    figures, shared, indexes = [], {}, []
    for analysis in analyses:
        index = None
        if analysis is not None:
            key = (replace(analysis.water, ph=0.0, alkalinity_mg_l=0.0, oxygen_mg_l=None), analysis.limits,
                   analysis.target, analysis.equilibria)
            index = shared.get(key)
            if index is None:
                index = shared[key] = len(figures)
                figures.append({**deffeyes.figure(analysis, deffeyes.geometry(analysis, extent=extent)), 'point': None})
        indexes.append(index)
    return figures, indexes


# The ingest is alive while each active connection's heartbeat is this recent (it beats every 10 s): the overview's
# tile and the alarm worker's dead man read it here.
INGEST_DEAD_AFTER = timedelta(seconds=90)


def ingest_alive(now):
    """Whether the ingest is alive: None when no connection is active (nothing to ingest), else whether every active
    connection's heartbeat is within INGEST_DEAD_AFTER of `now` (a connection without one is not)."""
    from .models import Connection, IngestStatus
    active = list(Connection.objects.filter(is_active=True).values_list('pk', flat=True))
    if not active:
        return None
    beats = dict(IngestStatus.objects.filter(connection_id__in=active).values_list('connection_id', 'heartbeat_at'))
    return all(beats.get(pk) is not None and now - beats[pk] <= INGEST_DEAD_AFTER for pk in active)


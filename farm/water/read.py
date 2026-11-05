"""Reading the water samples: the latest value of every parameter per sampling point with its status, and a
sample's values in the history, each with the values worked out from it (farm/water/chemistry.py) and
judged against the limits as they are now (farm/water/evaluate.py). Nothing here writes. THE read API of the
water: the rations, the withdrawal, the pages and the calculator read samples only through it.

The functions, by what they answer:
- `latest(points)`: {point id: PointWater}, the latest value of each parameter at each point;
- `middle_points(owners)`: {owner id: its active middle point}, the point that stands for the owner's own
  water (a unit's bulk, a system's loop, the inside of a piece of equipment): the one definition of it;
- `unit_water(units)`: {unit id: PointWater} of the unit's middle point, what the Production units page, its
  drawer and the overview show;
- `points_of(units, middle_only=...)`: {unit id: [SamplingPoint]}, every active point of each unit (its middle point
  first), or its middle point alone for the units of `middle_only`; `points_water` reads them all in one `latest()`:
  what a wall of monitoring cards shows;
- `assumed_salinity(water_types)`: the salinity assumed where none was measured (the one rule: 0 in fresh water);
- `water_sources(units, nested=...)`: {unit id: [Source]}, where a unit's temperature is read from: its middle
  point, then the loop point of its system (with `nested`, of the systems that system is nested in too, nearest
  first). The feeding temperature (farm/feeding/temperature.py) and the withdrawal's daily mean
  (farm/health/withdrawal.py) both start here, and `Series` is the lookup they share;
- `samples_of(...)`: the live samples of live points in a time window, newest first, for the history of a point,
  of an owner (all its points) or of a site; `history(samples)`: those samples with their readings, judged;
- `limits_now(point)`: the limits that would judge a value at the point today.

- The latest value is per parameter, not per sample: a later sample without DO never hides a critical
  DO (the source read the newest row, WQ-04). One grouped query finds, per point, the newest live sample
  of each parameter within WINDOW; a second fetches those samples. Oxygen in mg/L and in % are one
  reading: the newest sample with either gives both, one entered and the other worked out.
- A unit's water is its middle point's, and only that: a unit's DO, pH or nitrogen are never taken from its
  loop (the source's rule too: it passes on only what is the same all round a loop). Its temperature is the one
  value read from the loop when the unit has none of its own, by `water_sources`.
- Un-ionised ammonia needs the pH and the temperature of the TAN sample itself; the salinity is the
  sample's, else the point's latest within WINDOW before it, else its owner's middle point's, else 0 where
  every unit it concerns is in fresh water; otherwise it is not worked out and the reason is shown. The
  oxygen saturation needs the sample's temperature, the same salinity and the site's altitude (sea-level
  pressure when it has none, said so).
- The fish a value is judged for are the species in its unit on the day it was measured, at any time of
  that day (SpeciesBook, from the stock ledger); a loop's sample is judged for every unit of the loop, and a
  piece of equipment's for every unit of the systems it serves. The latest values are judged for today's fish.

Live values (farm/water/sources.py: the sensors) join the samples here and nowhere else. A value of any source is an
`Observation`: where (a point), when, from what (`Origin`: manual, lab, a sensor on the point, the system's sensor) and,
for a live value, how long it stays fresh. `latest` picks per point and per parameter, each on its own, in the owner's
order (A1): a fresh value of a sensor on the point (primary, then backup); for a middle point, a fresh value of a sensor
on the system (the unit's system, or the system whose loop it is); a fresh manual or lab value; else the newest of all,
which is then stale. A sensor value enters as the parameter's Decimal at its decimals, exactly as a typed value, and is
judged by the same limits. Derived values follow their base value's source: a sensor TAN gives NH3 only with fresh sensor
pH and temperature, a sensor oxygen gives the other unit only with a fresh sensor temperature, at the oldest input's time;
a manual TAN only with its own sample's pH and temperature. `Series` answers "the value at a moment" from the samples and
the sensors alike (each sensor value at or before the moment, never after it)."""
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from django.contrib.postgres.aggregates import ArrayAgg
from django.db import models
from django.db.models import Func, Q, UUIDField
from django.utils import timezone
from django.utils.translation import gettext as _, gettext_lazy

from farm.models import Batch, EquipmentSystem, SamplingPoint, System, Tank, WaterLimit, WaterMeasurement
from farm.models.water import LIVE_POINT
from farm.models.water_point import PointKind, local_time, owner_type_of, site_of
from farm.stock.read import Presence

from . import chemistry, parameters, sources
from .evaluate import Limits, Status, is_fresh, worst
from .parameters import NH3_N, NH4_N, OXYGEN_MG_L, OXYGEN_PCT, TAN

# How far back the latest values, and a salinity for a sample without one, are looked for.
WINDOW = timedelta(days=30)
OXYGEN = 'oxygen'
# A reading per parameter, except oxygen: one reading of mg/L and % together.
SLOTS = {code: Q(**{f'{code}__isnull': False}) for code in parameters.COLUMNS if code not in (OXYGEN_MG_L, OXYGEN_PCT)}
SLOTS[OXYGEN] = Q(oxygen_mg_l__isnull=False) | Q(oxygen_saturation_pct__isnull=False)
# Entered oxygen in mg/L and in % may differ by this share before the page says so.
OXYGEN_TOLERANCE = Decimal('0.10')
LIMITED = {parameter.code for parameter in parameters.LIMITED}
# What a sample's label, clock and fish need loaded: its point, the owner of it and the owner's site.
POINT_RELATED = ('point__unit__production_department__site', 'point__system__site',
                 'point__equipment__production_department__site')
# Where a unit's water is read from (Source.via).
UNIT, SYSTEM = 'unit', 'system'


def assumed_salinity(water_types):
    """The salinity (ppt) to use where none was measured: 0 when every unit concerned (`water_types`: their
    Tank.WaterType values) is in fresh water, else None, never a guess: the value is then not worked out."""
    return Decimal(0) if set(water_types) == {Tank.WaterType.FRESHWATER} else None


class First(Func):
    """The first element of an array, e.g. of an ordered ARRAY_AGG."""
    template = '(%(expressions)s)[1]'


# ---- the points of a unit's water ------------------------------------------------------------------------
def middle_points(owners):
    """{owner id: its active middle point} for the units, systems and pieces of equipment given: the one
    definition of the point that stands for an owner's own water. An owner without one (a piece of equipment
    has none unless its points were added) is not in the result."""
    wanted = defaultdict(list)
    for owner in owners:
        wanted[owner_type_of(owner)].append(owner.pk)
    if not wanted:
        return {}
    condition = Q()
    for owner_type, ids in wanted.items():
        condition |= Q(**{f'{owner_type}__in': ids})
    points = SamplingPoint.objects.filter(condition, kind=PointKind.MIDDLE, is_active=True).with_owners()
    return {point.owner.pk: point for point in points}


@dataclass(frozen=True)
class Source:
    """One place a unit's water is read from: the unit's own middle point (`via` UNIT) or the loop point of a
    system it is in (`via` SYSTEM)."""
    point: SamplingPoint
    via: str

    @property
    def owner(self):
        """The unit, or the system whose loop it is."""
        return self.point.owner


def system_chain(unit, systems):
    """The unit's system and the systems it is nested in, nearest first (`systems`: id -> System)."""
    found, seen = [], set()
    node = systems.get(unit.system_id)
    while node is not None and node.pk not in seen:
        seen.add(node.pk)
        found.append(node)
        node = systems.get(node.parent_id)
    return found


def water_sources(units, *, nested):
    """{unit id: [Source]}: the places the water of each unit is read from, in the order they count: the unit's
    own middle point, then the loop point of its system and, when `nested`, of the systems that system is nested
    in, nearest first. A point is a source while it is active and its owner live; an owner with no middle point
    gives none. The feeding temperature reads `nested` (a ration may be sized on a parent loop's water); the
    withdrawal's degree-days do not (a day without a temperature of its own counts as 0 °C and says so, the
    safe side)."""
    units = list(units)
    systems = System.objects.in_bulk() if any(unit.system_id for unit in units) else {}
    chains = {unit.pk: system_chain(unit, systems) if nested else
              [systems[unit.system_id]] if unit.system_id in systems else [] for unit in units}
    loops = {system.pk: system for chain in chains.values() for system in chain}
    middles = middle_points([*units, *loops.values()])
    found = {}
    for unit in units:
        sources = [Source(middles[unit.pk], UNIT)] if unit.pk in middles else []
        sources += [Source(middles[system.pk], SYSTEM) for system in chains[unit.pk] if system.pk in middles]
        found[unit.pk] = sources
    return found


# ---- where a value comes from ----------------------------------------------------------------------------
class Origin(models.TextChoices):
    """Where a value comes from, as the pages name it beside its age."""
    MANUAL = 'manual', gettext_lazy('manual')
    LAB = 'lab', gettext_lazy('lab')
    SENSOR = 'sensor', gettext_lazy('sensor')                       # bound to the point itself
    SYSTEM_SENSOR = 'system_sensor', gettext_lazy('system sensor')  # bound to the system, for its middle points


LIVE = (Origin.SENSOR, Origin.SYSTEM_SENSOR)
# How a sensor on the point is named, by the kind of owner the point is on.
SENSOR_LABELS = {'unit': gettext_lazy('unit sensor'), 'system': gettext_lazy('system sensor'),
                 'equipment': gettext_lazy('equipment sensor')}


@dataclass(frozen=True)
class Observation:
    """The values one source gave at a point at one moment: a sample (manual or lab: `sample` is the WaterMeasurement), a
    sensor channel's value, or the set of sensor values a derived value was worked out from (`at` then the oldest).
    `fresh_for` is the seconds a live value stays fresh (None: the parameter's own hours)."""
    point: SamplingPoint
    at: datetime
    origin: str
    measured: dict                     # code -> Decimal
    channel_no: int | None = None
    role: str = ''
    fresh_for: int | None = None
    is_deleted: bool = False
    sample: WaterMeasurement | None = None

    @classmethod
    def of_sample(cls, sample):
        return cls(sample.point, sample.measured_at, Origin.LAB if sample.source == 'lab' else Origin.MANUAL,
                   sample.values(), is_deleted=sample.is_deleted, sample=sample)

    @classmethod
    def of_sensor(cls, point, value, origin):
        """A sensor's value (sources.SensorValue) as the water parameter's Decimal, at its decimals."""
        step = parameters.get(value.code).step
        return cls(point, value.at, origin, {value.code: Decimal(repr(float(value.value))).quantize(step)},
                   channel_no=value.channel_no, role=value.role, fresh_for=value.fresh_for)

    @classmethod
    def combined(cls, observations):
        """The sensor values a derived value is worked out from: their values together, at the oldest one's time, from
        the first one's point and origin, fresh as long as the least fresh of them."""
        first = observations[0]
        measured = {}
        for each in observations:
            measured.update(each.measured)
        oldest = min(observations, key=lambda each: each.at)
        ends = [each.at + timedelta(seconds=each.fresh_for) for each in observations if each.fresh_for is not None]
        fresh_for = int((min(ends) - oldest.at).total_seconds()) if ends else None
        return cls(first.point, oldest.at, first.origin, measured, fresh_for=fresh_for)

    @property
    def measured_at(self):
        return self.at

    @property
    def live(self):
        return self.origin in LIVE

    @property
    def origin_label(self):
        """'unit sensor', 'system sensor', 'manual', 'lab'."""
        if self.origin == Origin.SENSOR:
            return SENSOR_LABELS[self.point.owner_type]
        return Origin(self.origin).label

    def values(self):
        return self.measured

    def get(self, code):
        return self.measured.get(code)


def observe(value):
    """An Observation of a sample, or the Observation given."""
    return Observation.of_sample(value) if isinstance(value, WaterMeasurement) else value


def sensor_targets(point, system_tier):
    """[(target, origin)] of a point's live values, in the order they count: the point's own sensors, then, for a middle
    point, the system's: always for a system's own middle point (its loop), and for a unit's with `system_tier` (the
    unit's system; owner rule A1)."""
    found = [((sources.POINT, point.pk), Origin.SENSOR)]
    if point.kind == PointKind.MIDDLE:
        system_id = point.system_id or (point.unit.system_id if system_tier and point.unit_id else None)
        if system_id:
            found.append(((sources.SYSTEM, system_id), Origin.SYSTEM_SENSOR))
    return found


@dataclass(frozen=True)
class Found:
    """A value found at a moment (Series.latest): when it was measured, the value, how long it stays fresh (seconds, None
    for a sample: the parameter's hours) and where it came from."""
    at: datetime
    value: Decimal
    fresh_for: int | None = None
    origin: str = Origin.MANUAL


class Series:
    """One parameter's values over time at a set of points, read in one query: what "the latest value at a
    moment" is looked up in, for a sample without a salinity here and for a unit's temperature on the day of its
    ration (farm/feeding/temperature.py). Live samples of live points only; with `live`, the sensors too (asked once
    per point and moment; a system's middle point has the system's sensors as its own). A sample's own workings never
    take a live value (its salinity series is not live)."""

    def __init__(self, points, code, since, until=None, live=False):
        self.code, self.live = code, live
        self.points = {point.pk: point for point in points}
        self.moments = defaultdict(list)    # point id -> [measured at], in time order
        self.values = defaultdict(list)     # point id -> [value], in the same order
        self.asked = {}                     # moment -> {point id: [Found]} of the sensors
        self.bound = set()                  # the sensor targets with a channel of the parameter bound in the range
        chosen = list(self.points)
        if chosen:
            rows = WaterMeasurement.objects.filter(point__in=chosen, measured_at__gte=since,
                                                   **{f'{code}__isnull': False})
            if until is not None:
                rows = rows.filter(measured_at__lte=until)
            for point_id, moment, value in rows.order_by('measured_at').values_list('point_id', 'measured_at', code):
                self.moments[point_id].append(moment)
                self.values[point_id].append(value)
        if live and self.points:
            wanted = [target for point in self.points.values() for target, _origin in sensor_targets(point, False)]
            self.bound = sources.bound(wanted, code, since, until or timezone.now())

    def _live(self, point_id, moment, window):
        """The sensors' values of the point at the moment (Found, primary first), at most `window` old. One ask of the
        live sources per moment for every point of the series, so the queries do not grow with the points."""
        if moment not in self.asked:
            targets = {pk: [(target, origin) for target, origin in sensor_targets(point, system_tier=False)
                            if target in self.bound] for pk, point in self.points.items()}
            if not any(targets.values()):
                self.asked[moment] = {}
                return []
            answer = sources.value_at([target for found in targets.values() for target, _origin in found], self.code,
                                      moment)
            by_point = {}
            for pk, found in targets.items():
                values = []
                for target, origin in found:
                    for value in sources.ordered(answer.values.get(target, [])):
                        if value.at <= moment:
                            observed = Observation.of_sensor(self.points[pk], value, origin)
                            values.append(Found(value.at, observed.get(self.code), value.fresh_for, origin))
                by_point[pk] = values
            self.asked[moment] = by_point
        return [found for found in self.asked[moment].get(point_id, []) if moment - found.at <= window]

    def latest(self, point_id, moment, window):
        """The point's value at `moment` (Found): a fresh sensor value (a live series), else the newest value at or before
        `moment` and at most `window` older than it, sample or sensor, a fresh sample before a stale sensor (A1); None when
        there is none."""
        moments = self.moments.get(point_id, [])
        index = bisect_right(moments, moment) - 1
        sample = None
        if index >= 0 and moment - moments[index] <= window:
            sample = Found(moments[index], self.values[point_id][index])
        live = self._live(point_id, moment, window) if self.live else []
        parameter = parameters.get(self.code)
        fresh = next((found for found in live if is_fresh(parameter, found.at, moment, found.fresh_for)), None)
        if fresh is not None:
            return fresh
        if sample is not None and is_fresh(parameter, sample.at, moment):
            return sample
        return max([found for found in (sample, *live) if found is not None], key=lambda found: found.at, default=None)


# ---- what a reading is -----------------------------------------------------------------------------------
@dataclass
class Reading:
    """One parameter's value from one Observation (a sample, a sensor's value, or the sensor values a derived value is
    worked out from): entered or measured, or worked out (`derived`); None when it could not be worked out, `note`
    saying why. `status` and the limit rows that judged it come from evaluate."""
    parameter: parameters.Parameter
    value: Decimal
    sample: Observation
    derived: bool = False
    note: str = ''
    status: str = Status.NOT_MEASURED
    limits: list = field(default_factory=list)

    @property
    def at(self):
        return self.sample.at

    @property
    def code(self):
        return self.parameter.code

    @property
    def point(self):
        """Where the value was taken."""
        return self.sample.point

    @property
    def origin(self):
        return self.sample.origin

    def age(self, now=None):
        return (now or timezone.now()) - self.at

    def fresh(self, now):
        """Whether it still says something about the water now (evaluate.is_fresh, the one rule)."""
        return is_fresh(self.parameter, self.at, now, self.sample.fresh_for)


@dataclass
class PointWater:
    """The latest readings of one sampling point, by parameter code; `point` is None for a unit that has no
    middle point (unit_water), which has no readings. `sensors_failed`: a live source could not be read, so what is
    shown comes from the samples alone (the pages say so)."""
    point: object
    readings: dict = field(default_factory=dict)
    sensors_failed: bool = False

    @property
    def status(self):
        """The worst status of its fresh values; stale when nothing is fresh (evaluate)."""
        return worst(reading.status for reading in self.readings.values() if reading.code in LIMITED)

    @property
    def alerts(self):
        return [reading for reading in self.readings.values() if reading.status in (Status.CRITICAL, Status.WARNING)]

    def get(self, code):
        return self.readings.get(code)


# ---- the fish in a unit on a day ----------------------------------------------------------------------------
class SpeciesBook:
    """Which species were in which unit on which day, from the live stock lines: the species of the batches
    present that day (farm.stock.read.Presence: fish stocked or harvested that day count)."""

    def __init__(self, unit_ids):
        self.presence = Presence.of_units(unit_ids)
        batch_ids = {batch_id for batches in self.presence.batches.values() for batch_id in batches}
        self.species = dict(Batch.all_objects.filter(pk__in=batch_ids).values_list('pk', 'species_id'))

    def on(self, unit_id, day):
        """The species ids in the unit on `day`."""
        return {self.species[batch_id] for batch_id in self.presence.batches_in(unit_id, day)}


# ---- everything a set of points needs, read once ----------------------------------------------------------
class Context:
    """The points' units, the fish in them, their salinity over time and the limits."""

    def __init__(self, points, since):
        points = list(points)
        self.served = self._served(points)                # point id -> the live units its water concerns
        self.book = SpeciesBook({unit.pk for units in self.served.values() for unit in units})
        species = set(self.book.species.values())
        self.limits = Limits(WaterLimit.objects.filter(species_id__in=species, species__is_deleted=False))
        self.middles = middle_points({point.owner.pk: point.owner for point in points}.values())
        self.salinity = Series([*points, *self.middles.values()], parameters.SALINITY, since - WINDOW)

    @staticmethod
    def _served(points):
        """{point id: [unit]}: the units a point's water is judged for. A unit's point: the unit; a loop's: the
        units of the system; a piece of equipment's: the units of the systems it serves."""
        system_ids = {point.system_id for point in points if point.system_id}
        equipment_ids = {point.equipment_id for point in points if point.equipment_id}
        serves = defaultdict(set)                          # equipment id -> the ids of the systems it serves
        if equipment_ids:
            links = EquipmentSystem.objects.filter(equipment__in=equipment_ids, system__is_deleted=False)
            for equipment_id, system_id in links.values_list('equipment_id', 'system_id'):
                serves[equipment_id].add(system_id)
                system_ids.add(system_id)
        units_of = defaultdict(list)                       # system id -> its live units
        if system_ids:
            for unit in Tank.objects.filter(system__in=system_ids).order_by('code'):
                units_of[unit.system_id].append(unit)
        served = {}
        for point in points:
            if point.unit_id:
                served[point.pk] = [point.unit]
            elif point.system_id:
                served[point.pk] = units_of.get(point.system_id, [])
            else:
                found = {unit.pk: unit for system_id in serves.get(point.equipment_id, ())
                         for unit in units_of.get(system_id, [])}
                served[point.pk] = sorted(found.values(), key=lambda unit: unit.code)
        return served

    # -- the water a sample was taken in --
    def water_types(self, point):
        return {unit.water_type for unit in self.served[point.pk]}

    def exposures(self, point, day):
        """[(species id, water type)] a value at this point on `day` is judged for."""
        return [(species_id, unit.water_type) for unit in self.served[point.pk]
                for species_id in self.book.on(unit.pk, day)]

    def salinity_for(self, observation):
        """The observation's salinity, else its point's latest sample within WINDOW before it, else its owner's middle
        point's, else 0 where every unit it concerns is in fresh water."""
        observation = observe(observation)
        if observation.get(parameters.SALINITY) is not None:
            return observation.get(parameters.SALINITY)
        point = observation.point
        for where in (point, self.middles.get(point.owner.pk)):
            found = None if where is None else self.salinity.latest(where.pk, observation.at, WINDOW)
            if found is not None:
                return found.value
        return assumed_salinity(self.water_types(point))

    # -- one observation's readings --
    def readings(self, observation):
        """{code: Reading} of a sample or an Observation: what was measured and what follows from it."""
        observation = observe(observation)
        found = {code: Reading(parameters.get(code), value, observation) for code, value in observation.values().items()}
        salinity = self.salinity_for(observation)
        if observation.get(TAN) is not None:
            found.update(self._ammonia(observation, salinity))
        if observation.get(OXYGEN_MG_L) is not None or observation.get(OXYGEN_PCT) is not None:
            found.update(self._oxygen(observation, observation.get(parameters.TEMPERATURE), salinity))
        return found

    @staticmethod
    def _salinity_missing():
        return _('Needs the salinity: none was recorded here in the 30 days before.')

    @staticmethod
    def _same_source_missing(observation):
        if observation.live:
            return _('Needs a fresh pH and temperature from the sensors with the sensor’s TAN.')
        return _('Needs the pH and the temperature of the same sample.')

    def _ammonia(self, observation, salinity):
        ph, temperature, tan = (observation.get(code) for code in (parameters.PH, parameters.TEMPERATURE, TAN))
        if ph is None or temperature is None:
            return {NH3_N.code: Reading(NH3_N, None, observation, True, self._same_source_missing(observation))}
        if salinity is None:
            return {NH3_N.code: Reading(NH3_N, None, observation, True, self._salinity_missing())}
        share = Decimal(chemistry.nh3_fraction(float(ph), float(temperature), float(salinity)))
        nh3 = (tan * share).quantize(NH3_N.step)
        return {NH3_N.code: Reading(NH3_N, nh3, observation, True),
                NH4_N.code: Reading(NH4_N, (tan - nh3).quantize(NH4_N.step), observation, True)}

    def _oxygen(self, observation, temperature, salinity):
        mg_l, percent = observation.get(OXYGEN_MG_L), observation.get(OXYGEN_PCT)
        missing = OXYGEN_PCT if percent is None else OXYGEN_MG_L if mg_l is None else None
        if temperature is None or salinity is None:
            if missing is None:
                return {}
            why = ((_('Needs a fresh temperature from the sensors with the sensor’s oxygen.') if observation.live
                    else _('Needs the temperature of the same sample.')) if temperature is None
                   else self._salinity_missing())
            return {missing: Reading(parameters.get(missing), None, observation, True, why)}
        site = site_of(observation.point)
        altitude = site.altitude if site is not None else None
        pressure = chemistry.pressure_atm(float(altitude)) if altitude is not None else 1.0
        solubility = Decimal(chemistry.oxygen_solubility(float(temperature), float(salinity), pressure))
        note = '' if altitude is not None else _('At sea-level pressure: the site has no altitude.')
        if missing == OXYGEN_PCT:
            value = (100 * mg_l / solubility).quantize(parameters.get(OXYGEN_PCT).step)
            return {OXYGEN_PCT: Reading(parameters.get(OXYGEN_PCT), value, observation, True, note)}
        if missing == OXYGEN_MG_L:
            value = (percent * solubility / 100).quantize(parameters.get(OXYGEN_MG_L).step)
            return {OXYGEN_MG_L: Reading(parameters.get(OXYGEN_MG_L), value, observation, True, note)}
        expected = percent * solubility / 100
        if expected and abs(mg_l - expected) / expected > OXYGEN_TOLERANCE:
            note = _('The mg/L and the % disagree by more than 10 % at this temperature and salinity: check the '
                     'meter’s settings.')
            return {code: Reading(parameters.get(code), observation.get(code), observation, False, note)
                    for code in (OXYGEN_MG_L, OXYGEN_PCT)}
        return {}

    # -- judging --
    def judge(self, reading, day, now=None):
        """Sets the reading's status and limit rows, for the fish of `day`; stale when `now` is given and the
        value is no longer fresh (Reading.fresh)."""
        if reading.code not in LIMITED or reading.value is None:
            reading.status = Status.NOT_MEASURED if reading.value is None else Status.NO_LIMIT
            return reading
        reading.status, reading.limits = self.limits.assess(reading.code, reading.value,
                                                            self.exposures(reading.sample.point, day))
        if now is not None and not reading.fresh(now):
            reading.status = Status.STALE
        return reading


def _local_day(sample):
    return local_time(sample.measured_at, sample.point).date()


# ---- the latest values ------------------------------------------------------------------------------------
def _newest_ids(points, since, until=None):
    """{point id: {slot: sample id}}: per point, the newest live sample of each slot within the window (up to `until`)."""
    found = {}
    if not points:
        return found
    rows = WaterMeasurement.objects.filter(point__in=[point.pk for point in points], measured_at__gte=since)
    if until is not None:
        rows = rows.filter(measured_at__lte=until)
    rows = (rows.values('point_id')
            .annotate(**{f'newest_{slot}': First(ArrayAgg('id', filter=condition,
                                                           order_by=('-measured_at', '-created_at')),
                                                  output_field=UUIDField())
                         for slot, condition in SLOTS.items()}))
    for row in rows:
        found[row['point_id']] = {slot: row[f'newest_{slot}'] for slot in SLOTS if row[f'newest_{slot}']}
    return found


def _manual(point, newest, samples, context):
    """{code: Reading} of the point's latest samples: each slot's newest sample with what follows from it."""
    found = {}
    for slot, sample_id in newest.get(point.pk, {}).items():
        readings = context.readings(samples[sample_id])
        codes = {OXYGEN: (OXYGEN_MG_L, OXYGEN_PCT), TAN: (TAN, NH3_N.code, NH4_N.code)}.get(slot, (slot,))
        for code in codes:
            if code in readings:
                found[code] = readings[code]
    return found


def _live(point, targets, answer):
    """{code: [Observation]} of the point's live values, in the order they count (sensor_targets, then primary first)."""
    found = defaultdict(list)
    for target, origin in targets:
        for code, values in answer.values.get(target, {}).items():
            if code in parameters.COLUMNS:
                found[code].extend(Observation.of_sensor(point, value, origin) for value in sources.ordered(values))
    return found


def _resolve(point, manual, live, context, now):
    """{code: Reading} of one point in the owner's order (A1), each parameter on its own: a fresh live value, else a
    fresh one worked out from fresh live values (the other oxygen unit), else a fresh manual or lab value, else the
    newest of all, stale. A derived value follows the source of its base: NH3 and NH4 a live TAN's (worked out from live
    values only) or the sample's."""
    fresh_live = {code: next((each for each in observations if is_fresh(parameters.get(code), each.at, now,
                                                                          each.fresh_for)), None)
                  for code, observations in live.items()}
    chosen = {}
    for code in parameters.COLUMNS:
        parameter = parameters.get(code)
        if fresh_live.get(code) is not None:
            chosen[code] = Reading(parameter, fresh_live[code].get(code), fresh_live[code])
            continue
        other = {OXYGEN_MG_L: OXYGEN_PCT, OXYGEN_PCT: OXYGEN_MG_L}.get(code)
        if other and fresh_live.get(other) is not None and fresh_live.get(parameters.TEMPERATURE) is not None:
            worked = context.readings(Observation.combined([fresh_live[other], fresh_live[parameters.TEMPERATURE],
                                                            *([fresh_live[parameters.SALINITY]]
                                                              if fresh_live.get(parameters.SALINITY) else [])]))
            if worked.get(code) is not None and worked[code].value is not None:
                chosen[code] = worked[code]
                continue
        sample = manual.get(code)
        if sample is not None and sample.fresh(now):
            chosen[code] = sample
            continue
        candidates = [Reading(parameter, each.get(code), each) for each in live.get(code, [])]
        if sample is not None:
            candidates.append(sample)
        if candidates:
            chosen[code] = max(candidates, key=lambda reading: reading.at)
    tan = chosen.get(TAN)
    if tan is not None and tan.sample.live:
        inputs = [tan.sample, *(fresh_live[code] for code in (parameters.PH, parameters.TEMPERATURE, parameters.SALINITY)
                                if fresh_live.get(code) is not None)]
        if tan.fresh(now):
            together = Observation.combined(inputs)
            chosen.update(context._ammonia(together, context.salinity_for(together)))
        else:
            chosen[NH3_N.code] = Reading(NH3_N, None, tan.sample, True, context._same_source_missing(tan.sample))
    elif tan is not None:
        chosen.update({code: manual[code] for code in (NH3_N.code, NH4_N.code) if code in manual})
    return chosen


def latest(points, now=None, at=None):
    """{point id: PointWater} of every sampling point given: per parameter, its value in the owner's order (`_resolve`),
    judged for the fish in it that day; values no longer fresh are stale. One query for the samples, one ask of the live
    sources for every point. With `at` (a past moment, owner amendment A4), the water as it was then: the samples taken
    up to that moment, each sensor's value at it (sources.value_at: the channels bound there then), fresh and judged
    relative to it; nothing from after it."""
    moment = at or now or timezone.now()
    since = moment - WINDOW
    points = list(points)
    newest = _newest_ids(points, since, until=at)
    ids = {sample_id for slots in newest.values() for sample_id in slots.values()}
    samples = WaterMeasurement.objects.select_related(*POINT_RELATED).in_bulk(ids)
    context = Context(points, since)
    targets = {point.pk: sensor_targets(point, system_tier=True) for point in points}
    wanted = [target for found in targets.values() for target, _origin in found]
    answer = sources.latest(wanted, moment) if at is None else _values_at(wanted, at)
    water = {}
    for point in points:
        point_water = water[point.pk] = PointWater(point, sensors_failed=answer.failed)
        day = local_time(moment, point).date()
        resolved = _resolve(point, _manual(point, newest, samples, context), _live(point, targets[point.pk], answer),
                            context, moment)
        for code, reading in resolved.items():
            point_water.readings[code] = context.judge(reading, day, moment)
    return water


def _values_at(targets, moment):
    """The live sources' values of every measured parameter at a past moment, as one answer (sources.Answer)."""
    merged, failed = {}, False
    for code in parameters.COLUMNS:
        answer = sources.value_at(targets, code, moment)
        failed = failed or answer.failed
        for target, values in answer.values.items():
            merged.setdefault(target, {})[code] = values
    return sources.Answer(merged, failed)


def owner_water(owners, now=None):
    """{owner id: PointWater} of each unit's, loop's or equipment's water: its middle point's latest values
    (`middle_points`), nothing for an owner that has none. What Production units, its drawer and the overview show
    for units (`unit_water`), and what the calculator takes a unit's or a loop's values from."""
    owners = list(owners)
    middles = middle_points(owners)
    water = latest(list(middles.values()), now)
    return {owner.pk: water[middles[owner.pk].pk] if owner.pk in middles else PointWater(None) for owner in owners}


def unit_water(units, now=None):
    """{unit id: PointWater} of each unit's water (`owner_water`)."""
    return owner_water(units, now)


MIDDLE = PointKind.MIDDLE


def points_of(units, middle_only=()):
    """{unit id: [SamplingPoint]} of every unit given: its active points, the middle point first (`middle_points`, the
    one definition of it), the others by name; for the units of `middle_only` (ids) the middle point alone. A unit
    without a middle point has only its others (or none): nothing stands in for it."""
    units = list(units)
    middles = middle_points(units)
    narrow = set(middle_only)
    wide = [unit.pk for unit in units if unit.pk not in narrow]
    others = defaultdict(list)
    if wide:
        for point in (SamplingPoint.objects.filter(unit__in=wide, is_active=True).exclude(kind=MIDDLE)
                      .with_owners()):
            others[point.unit_id].append(point)
    return {unit.pk: [*([middles[unit.pk]] if unit.pk in middles else []),
                      *sorted(others[unit.pk], key=lambda point: point.name)] for unit in units}


def points_water(units, now=None, middle_only=()):
    """{unit id: [PointWater]} of every unit given: the readings of each of its `points_of`, all read by ONE `latest()`."""
    chosen = points_of(units, middle_only)
    water = latest([point for points in chosen.values() for point in points], now)
    return {unit_id: [water[point.pk] for point in points] for unit_id, points in chosen.items()}


# ---- the history ------------------------------------------------------------------------------------------
@dataclass
class HistoryRow:
    sample: WaterMeasurement
    readings: dict

    @property
    def status(self):
        return worst(reading.status for reading in self.readings.values() if reading.code in LIMITED)


def samples_of(*, points=None, owner=None, site=None, since=None, before=None):
    """The samples of live points of live owners, voided ones too, newest first, with their point, its owner and
    the people loaded; `since` and `before` bound the time (a moment, `before` not included). Narrowed to
    `points` (SamplingPoints), to an `owner` (a unit, system or piece of equipment: every point of it) or to a
    `site` (every owner on it). The history of a point, of an owner and of a site are this one query."""
    found = WaterMeasurement.all_objects.filter(LIVE_POINT).select_related(*POINT_RELATED, 'created_by', 'deleted_by')
    if since is not None:
        found = found.filter(measured_at__gte=since)
    if before is not None:
        found = found.filter(measured_at__lt=before)
    if points is not None:
        found = found.filter(point__in=list(points))
    if owner is not None:
        found = found.filter(**{f'point__{owner_type_of(owner)}': owner})
    if site is not None:
        found = found.filter(Q(point__unit__production_department__site=site) | Q(point__system__site=site)
                             | Q(point__equipment__production_department__site=site))
    return found.order_by('-measured_at', '-created_at')


def history(samples):
    """[HistoryRow] of the samples (with their points loaded, `samples_of`), in their order, each value judged
    for the fish of its day by the limits as they are now (owner decision 2). Voided samples are shown without a
    status."""
    if not samples:
        return []
    points = list({sample.point_id: sample.point for sample in samples}.values())
    context = Context(points, min(sample.measured_at for sample in samples))
    rows = []
    for sample in samples:
        readings = context.readings(sample)
        if not sample.is_deleted:
            day = _local_day(sample)
            for reading in readings.values():
                context.judge(reading, day)
        rows.append(HistoryRow(sample, readings))
    return rows


def limits_now(place):
    """{code: [WaterLimit]} for the fish at a point, or in a unit, loop or piece of equipment, today: what a value
    there would be judged against."""
    now = timezone.now()
    point = place if isinstance(place, SamplingPoint) else SamplingPoint(**{owner_type_of(place): place})
    context = Context([point], now)
    exposures = context.exposures(point, local_time(now, point).date())
    found = {}
    for parameter in parameters.LIMITED:
        rows = []
        for species_id, water_type in exposures:
            row = context.limits.applying(species_id, parameter.code, water_type)
            if row is not None and row not in rows:
                rows.append(row)
        if rows:
            found[parameter.code] = rows
    return found

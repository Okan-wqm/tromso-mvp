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
  piece of equipment's for every unit of the systems it serves. The latest values are judged for today's fish."""
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from django.contrib.postgres.aggregates import ArrayAgg
from django.db.models import Func, Q, UUIDField
from django.utils import timezone
from django.utils.translation import gettext as _

from farm.models import Batch, EquipmentSystem, SamplingPoint, System, Tank, WaterLimit, WaterMeasurement
from farm.models.water import LIVE_POINT
from farm.models.water_point import PointKind, local_time, owner_type_of, site_of
from farm.stock.read import Presence

from . import chemistry, parameters
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


class Series:
    """One parameter's values over time at a set of points, read in one query: what "the latest value at a
    moment" is looked up in, for a sample without a salinity here and for a unit's temperature on the day of its
    ration (farm/feeding/temperature.py). Live samples of live points only."""

    def __init__(self, points, code, since, until=None):
        self.moments = defaultdict(list)    # point id -> [measured at], in time order
        self.values = defaultdict(list)     # point id -> [value], in the same order
        chosen = list({point.pk for point in points})
        if chosen:
            rows = WaterMeasurement.objects.filter(point__in=chosen, measured_at__gte=since,
                                                   **{f'{code}__isnull': False})
            if until is not None:
                rows = rows.filter(measured_at__lte=until)
            for point_id, moment, value in rows.order_by('measured_at').values_list('point_id', 'measured_at', code):
                self.moments[point_id].append(moment)
                self.values[point_id].append(value)

    def latest(self, point_id, moment, window):
        """(measured at, value) of the point's newest value at or before `moment` and at most `window` older than
        it; None when there is none."""
        moments = self.moments.get(point_id, [])
        index = bisect_right(moments, moment) - 1
        if index >= 0 and moment - moments[index] <= window:
            return moments[index], self.values[point_id][index]
        return None


# ---- what a reading is -----------------------------------------------------------------------------------
@dataclass
class Reading:
    """One parameter's value from one sample: entered, or worked out (`derived`); None when it could not be
    worked out, `note` saying why. `status` and the limit rows that judged it come from evaluate."""
    parameter: parameters.Parameter
    value: Decimal
    sample: WaterMeasurement
    derived: bool = False
    note: str = ''
    status: str = Status.NOT_MEASURED
    limits: list = field(default_factory=list)

    @property
    def at(self):
        return self.sample.measured_at

    @property
    def code(self):
        return self.parameter.code

    @property
    def point(self):
        """Where the value was taken."""
        return self.sample.point

    def age(self, now=None):
        return (now or timezone.now()) - self.at


@dataclass
class PointWater:
    """The latest readings of one sampling point, by parameter code; `point` is None for a unit that has no
    middle point (unit_water), which has no readings."""
    point: object
    readings: dict = field(default_factory=dict)

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

    def salinity_for(self, sample):
        """The sample's salinity, else its point's latest within WINDOW before it, else its owner's middle
        point's, else 0 where every unit it concerns is in fresh water."""
        if sample.salinity_ppt is not None:
            return sample.salinity_ppt
        point = sample.point
        for where in (point, self.middles.get(point.owner.pk)):
            found = None if where is None else self.salinity.latest(where.pk, sample.measured_at, WINDOW)
            if found is not None:
                return found[1]
        if self.water_types(point) == {Tank.WaterType.FRESHWATER}:
            return Decimal(0)
        return None

    # -- one sample's readings --
    def readings(self, sample):
        """{code: Reading} of a sample: what was entered and what follows from it."""
        found = {code: Reading(parameters.get(code), value, sample) for code, value in sample.values().items()}
        salinity = self.salinity_for(sample)
        temperature = sample.temperature_c
        if sample.tan_mg_l is not None:
            found.update(self._ammonia(sample, salinity))
        if sample.oxygen_mg_l is not None or sample.oxygen_saturation_pct is not None:
            found.update(self._oxygen(sample, temperature, salinity))
        return found

    @staticmethod
    def _salinity_missing():
        return _('Needs the salinity: none was recorded here in the 30 days before.')

    def _ammonia(self, sample, salinity):
        if sample.ph is None or sample.temperature_c is None:
            return {NH3_N.code: Reading(NH3_N, None, sample, True,
                                        _('Needs the pH and the temperature of the same sample.'))}
        if salinity is None:
            return {NH3_N.code: Reading(NH3_N, None, sample, True, self._salinity_missing())}
        share = Decimal(chemistry.nh3_fraction(float(sample.ph), float(sample.temperature_c), float(salinity)))
        nh3 = (sample.tan_mg_l * share).quantize(NH3_N.step)
        return {NH3_N.code: Reading(NH3_N, nh3, sample, True),
                NH4_N.code: Reading(NH4_N, (sample.tan_mg_l - nh3).quantize(NH4_N.step), sample, True)}

    def _oxygen(self, sample, temperature, salinity):
        mg_l, percent = sample.oxygen_mg_l, sample.oxygen_saturation_pct
        missing = OXYGEN_PCT if percent is None else OXYGEN_MG_L if mg_l is None else None
        if temperature is None or salinity is None:
            if missing is None:
                return {}
            why = (_('Needs the temperature of the same sample.') if temperature is None
                   else self._salinity_missing())
            return {missing: Reading(parameters.get(missing), None, sample, True, why)}
        site = site_of(sample.point)
        altitude = site.altitude if site is not None else None
        pressure = chemistry.pressure_atm(float(altitude)) if altitude is not None else 1.0
        solubility = Decimal(chemistry.oxygen_solubility(float(temperature), float(salinity), pressure))
        note = '' if altitude is not None else _('At sea-level pressure: the site has no altitude.')
        if missing == OXYGEN_PCT:
            value = (100 * mg_l / solubility).quantize(parameters.get(OXYGEN_PCT).step)
            return {OXYGEN_PCT: Reading(parameters.get(OXYGEN_PCT), value, sample, True, note)}
        if missing == OXYGEN_MG_L:
            value = (percent * solubility / 100).quantize(parameters.get(OXYGEN_MG_L).step)
            return {OXYGEN_MG_L: Reading(parameters.get(OXYGEN_MG_L), value, sample, True, note)}
        expected = percent * solubility / 100
        if expected and abs(mg_l - expected) / expected > OXYGEN_TOLERANCE:
            note = _('The mg/L and the % disagree by more than 10 % at this temperature and salinity: check the '
                     'meter’s settings.')
            return {code: Reading(parameters.get(code), getattr(sample, code), sample, False, note)
                    for code in (OXYGEN_MG_L, OXYGEN_PCT)}
        return {}

    # -- judging --
    def judge(self, reading, day, now=None):
        """Sets the reading's status and limit rows, for the fish of `day`; stale when `now` is given and the
        value is older than its parameter's freshness."""
        if reading.code not in LIMITED or reading.value is None:
            reading.status = Status.NOT_MEASURED if reading.value is None else Status.NO_LIMIT
            return reading
        reading.status, reading.limits = self.limits.assess(reading.code, reading.value,
                                                            self.exposures(reading.sample.point, day))
        if now is not None and not is_fresh(reading.parameter, reading.at, now):
            reading.status = Status.STALE
        return reading


def _local_day(sample):
    return local_time(sample.measured_at, sample.point).date()


# ---- the latest values ------------------------------------------------------------------------------------
def _newest_ids(points, since):
    """{point id: {slot: sample id}}: per point, the newest live sample of each slot within the window."""
    found = {}
    if not points:
        return found
    rows = (WaterMeasurement.objects.filter(point__in=[point.pk for point in points], measured_at__gte=since)
            .values('point_id')
            .annotate(**{f'newest_{slot}': First(ArrayAgg('id', filter=condition,
                                                           order_by=('-measured_at', '-created_at')),
                                                  output_field=UUIDField())
                         for slot, condition in SLOTS.items()}))
    for row in rows:
        found[row['point_id']] = {slot: row[f'newest_{slot}'] for slot in SLOTS if row[f'newest_{slot}']}
    return found


def latest(points, now=None):
    """{point id: PointWater} of every sampling point given, with the latest reading of each parameter measured
    in the WINDOW, judged for the fish in it today; values older than their freshness are stale."""
    now = now or timezone.now()
    since = now - WINDOW
    points = list(points)
    newest = _newest_ids(points, since)
    ids = {sample_id for slots in newest.values() for sample_id in slots.values()}
    samples = WaterMeasurement.objects.select_related(*POINT_RELATED).in_bulk(ids)
    context = Context(points, since)
    water = {}
    for point in points:
        point_water = water[point.pk] = PointWater(point)
        today = local_time(now, point).date()
        for slot, sample_id in newest.get(point.pk, {}).items():
            readings = context.readings(samples[sample_id])
            codes = {OXYGEN: (OXYGEN_MG_L, OXYGEN_PCT), TAN: (TAN, NH3_N.code, NH4_N.code)}.get(slot, (slot,))
            for code in codes:
                if code in readings:
                    point_water.readings[code] = context.judge(readings[code], today, now)
    return water


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

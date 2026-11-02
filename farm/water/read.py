"""Reading the water samples: the latest value of every parameter per unit or loop with its status, and a
sample's values in the history, each with the values worked out from it (farm/water/chemistry.py) and
judged against the limits as they are now (farm/water/evaluate.py). Nothing here writes.

- The latest value is per parameter, not per sample: a later sample without DO never hides a critical
  DO (the source read the newest row, WQ-04). One grouped query finds, per point, the newest live sample
  of each parameter within WINDOW; a second fetches those samples. Oxygen in mg/L and in % are one
  reading: the newest sample with either gives both, one entered and the other worked out.
- Un-ionised ammonia needs the pH and the temperature of the TAN sample itself; the salinity is the
  sample's, else the point's latest within WINDOW before it, else 0 where every unit is in fresh water;
  otherwise it is not worked out and the reason is shown. The oxygen saturation needs the sample's
  temperature, the same salinity and the site's altitude (sea-level pressure when it has none, said so).
- The fish a value is judged for are the species in its unit on the day it was measured, at any time of
  that day (SpeciesBook, from the stock ledger); a loop's sample is judged for every unit of the loop.
  The latest values are judged for today's fish."""
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from django.contrib.postgres.aggregates import ArrayAgg
from django.db.models import Func, Q, UUIDField
from django.utils import timezone
from django.utils.translation import gettext as _

from farm.models import StockMovement, System, Tank, WaterLimit, WaterMeasurement
from farm.models.water import local_time, site_of

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


class First(Func):
    """The first element of an array, e.g. of an ordered ARRAY_AGG."""
    template = '(%(expressions)s)[1]'


def key(point):
    """('tank', id) or ('system', id): units and systems in one dict."""
    return point._meta.model_name, point.pk


class Series:
    """One parameter's values over time at a set of points (units and loops), read in one query per kind of point:
    what "the latest value at a moment" is looked up in, for a sample without a salinity here and for a unit's
    temperature on the day of its ration (farm/feeding/temperature.py). Live samples of live points only."""

    def __init__(self, points, code, since, until=None):
        self.moments = defaultdict(list)    # point key -> [measured at], in time order
        self.values = defaultdict(list)     # point key -> [value], in the same order
        for field_name, model in (('unit', Tank), ('system', System)):
            chosen = [point.pk for point in points if isinstance(point, model)]
            if not chosen:
                continue
            rows = WaterMeasurement.objects.filter(**{f'{field_name}__in': chosen, f'{code}__isnull': False},
                                                   measured_at__gte=since)
            if until is not None:
                rows = rows.filter(measured_at__lte=until)
            for point_id, moment, value in rows.order_by('measured_at').values_list(f'{field_name}_id', 'measured_at',
                                                                                    code):
                self.moments[(model._meta.model_name, point_id)].append(moment)
                self.values[(model._meta.model_name, point_id)].append(value)

    def latest(self, point_key, moment, window):
        """(measured at, value) of the point's newest value at or before `moment` and at most `window` older than
        it; None when there is none."""
        moments = self.moments.get(point_key, [])
        index = bisect_right(moments, moment) - 1
        if index >= 0 and moment - moments[index] <= window:
            return moments[index], self.values[point_key][index]
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

    def age(self, now=None):
        return (now or timezone.now()) - self.at


@dataclass
class PointWater:
    """The latest readings of one unit or loop, by parameter code."""
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
    """Which species were in which unit on which day, from the live stock lines: a batch counts on a day
    when it had fish there at the end of that day or of the day before (fish stocked or harvested that
    day count)."""

    def __init__(self, unit_ids):
        changes, self.species = defaultdict(lambda: defaultdict(int)), {}
        rows = (StockMovement.objects.filter(unit_id__in=unit_ids, operation__is_deleted=False)
                .values_list('unit_id', 'batch_id', 'batch__species_id', 'operation__date', 'count_delta'))
        for unit_id, batch_id, species_id, day, delta in rows:
            changes[(unit_id, batch_id)][day] += delta
            self.species[batch_id] = species_id
        self.timelines = defaultdict(dict)    # unit -> batch -> (days, fish at the end of each)
        for (unit_id, batch_id), by_day in changes.items():
            days, counts, running = [], [], 0
            for day in sorted(by_day):
                running += by_day[day]
                days.append(day)
                counts.append(running)
            self.timelines[unit_id][batch_id] = (days, counts)

    @staticmethod
    def _at_end(timeline, day):
        days, counts = timeline
        index = bisect_right(days, day) - 1
        return counts[index] if index >= 0 else 0

    def on(self, unit_id, day):
        """The species ids in the unit on `day`."""
        return {self.species[batch_id] for batch_id, timeline in self.timelines.get(unit_id, {}).items()
                if self._at_end(timeline, day) > 0 or self._at_end(timeline, day - timedelta(days=1)) > 0}


# ---- everything a set of points needs, read once ----------------------------------------------------------
class Context:
    """The points' units and loops, the fish in them, their salinity over time and the limits."""

    def __init__(self, points, since):
        self.units_of = {}                        # system id -> its live units
        units = [point for point in points if isinstance(point, Tank)]
        systems = [point for point in points if isinstance(point, System)]
        for unit in Tank.objects.filter(system__in=systems) if systems else []:
            self.units_of.setdefault(unit.system_id, []).append(unit)
        all_units = units + [unit for members in self.units_of.values() for unit in members]
        self.book = SpeciesBook({unit.pk for unit in all_units})
        species = set(self.book.species.values())
        self.limits = Limits(WaterLimit.objects.filter(species_id__in=species, species__is_deleted=False))
        self.salinity = Series(points, parameters.SALINITY, since - WINDOW)

    # -- the water a sample was taken in --
    def water_types(self, point):
        if isinstance(point, System):
            return {unit.water_type for unit in self.units_of.get(point.pk, [])}
        return {point.water_type}

    def exposures(self, point, day):
        """[(species id, water type)] a value of this point on `day` is judged for."""
        units = self.units_of.get(point.pk, []) if isinstance(point, System) else [point]
        return [(species_id, unit.water_type) for unit in units for species_id in self.book.on(unit.pk, day)]

    def salinity_for(self, sample):
        """The sample's salinity, else the point's latest within WINDOW before it, else 0 in fresh water."""
        if sample.salinity_ppt is not None:
            return sample.salinity_ppt
        found = self.salinity.latest(key(sample.point), sample.measured_at, WINDOW)
        if found is not None:
            return found[1]
        if self.water_types(sample.point) == {Tank.WaterType.FRESHWATER}:
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
    """{point key: {slot: sample id}}: per point, the newest live sample of each slot within the window."""
    found = defaultdict(dict)
    for field_name, model in (('unit', Tank), ('system', System)):
        chosen = [point.pk for point in points if isinstance(point, model)]
        if not chosen:
            continue
        rows = (WaterMeasurement.objects.filter(**{f'{field_name}__in': chosen}, measured_at__gte=since)
                .values(f'{field_name}_id')
                .annotate(**{f'newest_{slot}': First(ArrayAgg('id', filter=condition,
                                                               order_by=('-measured_at', '-created_at')),
                                                      output_field=UUIDField())
                             for slot, condition in SLOTS.items()}))
        for row in rows:
            point = (model._meta.model_name, row[f'{field_name}_id'])
            found[point] = {slot: row[f'newest_{slot}'] for slot in SLOTS if row[f'newest_{slot}']}
    return found


def latest(points, now=None):
    """{point key: PointWater} of every point given, with the latest reading of each parameter measured in
    the WINDOW, judged for the fish in it today; values older than their freshness are stale."""
    now = now or timezone.now()
    since = now - WINDOW
    newest = _newest_ids(points, since)
    ids = {sample_id for slots in newest.values() for sample_id in slots.values()}
    samples = WaterMeasurement.objects.select_related('unit__production_department__site', 'system__site').in_bulk(ids)
    context = Context(points, since)
    water = {}
    for point in points:
        point_water = water[key(point)] = PointWater(point)
        today = local_time(now, point).date()
        for slot, sample_id in newest.get(key(point), {}).items():
            readings = context.readings(samples[sample_id])
            codes = {OXYGEN: (OXYGEN_MG_L, OXYGEN_PCT), TAN: (TAN, NH3_N.code, NH4_N.code)}.get(slot, (slot,))
            for code in codes:
                if code in readings:
                    point_water.readings[code] = context.judge(readings[code], today, now)
    return water


# ---- the history ------------------------------------------------------------------------------------------
@dataclass
class HistoryRow:
    sample: WaterMeasurement
    readings: dict

    @property
    def status(self):
        return worst(reading.status for reading in self.readings.values() if reading.code in LIMITED)


def history(samples):
    """[HistoryRow] of the samples, in their order, each value judged for the fish of its day by the limits
    as they are now (owner decision 2). Voided samples are shown without a status."""
    if not samples:
        return []
    points = list({key(sample.point): sample.point for sample in samples}.values())
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


def limits_now(point):
    """{code: [WaterLimit]} for the fish in the point today: what a value would be judged against."""
    context = Context([point], timezone.now())
    exposures = context.exposures(point, local_time(timezone.now(), point).date())
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


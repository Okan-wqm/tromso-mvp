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
  what a wall of monitoring cards shows; `own_water(unit ids)`, the units' own-water points, which `anchors` and
  `latest` work from, read once and handed on;
- `assumed_salinity(water_types)`: the salinity assumed where none was measured (the one rule: 0 in fresh water);
- `tiers(units, nested=...)`: {unit id: [Tier]}, owner rule A9's tiers of a unit, the one resolver of where its water
  is read: its own-water points, then its system's loop point or the system's own sensors (with `nested`, the loops of
  the systems that system is nested in too, nearest first). The water page (`_places`), the feeding temperature
  (farm/feeding/temperature.py), the degree-days (farm/water/degree_days.py) and the closing of probe days all start
  here, and `Series` is the lookup they share;
- `samples_of(...)`: the live samples of live points in a time window, newest first, for the history of a point,
  of an owner (all its points) or of a site; `history(samples)`: those samples with their readings, judged;
- `limits_now(point)`: the limits that would judge a value at the point today; `limits_of(places)`: the same for
  many places in one read.

- The latest value is per parameter, not per sample: a later sample without DO never hides a critical
  DO (the source read the newest row, WQ-04). One grouped query finds, per point, the newest live sample
  of each parameter within WINDOW; a second fetches those samples. Oxygen in mg/L and in % are one
  reading: the newest sample with either gives both, one entered and the other worked out.
- A unit's water is its middle point's: its own values first; only when it has no fresh value of a parameter of its
  own does its system's fresh value stand in (owner rule A9: the system's sensor or a sample of its loop). Its
  temperature for the rations and the withdrawal is read the same way, by `tiers`.
- Un-ionised ammonia needs the pH and the temperature of the TAN sample itself; the salinity is the
  sample's, else the point's latest within WINDOW before it, else its owner's middle point's, else 0 where
  every unit it concerns is in fresh water; otherwise it is not worked out and the reason is shown. Its ionic
  strength (formula 3, chemcore/findings/I2-comparison.md) is the water's: the alkalinity, the conductivity at 25 °C
  and the hardness each the sample's, else the point's latest fresh at the sample's time, else its owner's middle
  point's, as the salinity (none of them: an ionic strength of 0, formula 1's ideal water, the safe side). Every
  worked-out value says the formula version it was worked out by (`Reading.provenance`); nothing worked out is stored,
  so a past sample is shown by the formula of today and says so. The
  oxygen saturation needs the sample's temperature, the same salinity and the site's altitude (sea-level
  pressure when it has none, said so).
- The fish a value is judged for are the species in its unit on the day it was measured, at any time of
  that day (SpeciesBook, from the stock ledger); a loop's sample is judged for every unit of the loop, and a
  piece of equipment's for every unit of the systems it serves. The latest values are judged for today's fish.

Live values (farm/water/sources.py: the sensors) join the samples here and nowhere else. A value of any source is an
`Observation`: where (a point), when, from what (`Origin`: manual, lab, a sensor on the point, the system's sensor) and,
for a live value, how long it stays fresh. `latest` picks per point and per parameter, each on its own, in the owner's
order (A9, which replaced A1): the newest of the point's OWN fresh values, a sensor's on the point (the primary before a
backup at one measurement time) or a manual or lab sample's, whatever its origin; for a unit's middle point with nothing
fresh of its own, the newest fresh value of its system (the system's sensor, a sensor on its loop point, a sample of its
loop); else the newest of its own, else of its system's, which is then stale and enters no calculation. The rule is one
function, `choose`, that `latest`, `Series.latest` and the ration's temperature all pick through. A sensor value enters as the parameter's Decimal at its decimals, exactly as a typed value, and is
judged by the same limits. Derived values follow their base value's source: a sensor TAN gives NH3 only with fresh sensor
pH and temperature, a sensor oxygen gives the other unit only with a fresh sensor temperature, at the oldest input's time;
a manual TAN only with its own sample's pH and temperature. A worked-out value is never fresher than its oldest input:
it stops being fresh when the first value it was worked out with does (`Reading.fresh_until`, freshness.derived_until;
the coordinator's decision of 2026-11-26), so an NH₃ of a sample goes stale with the sample's temperature.
`Series` answers "the value at a moment" from the samples and the sensors alike (each sensor value at or before the moment, never after it)."""
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from decimal import Decimal
from functools import partial

from django.contrib.postgres.aggregates import ArrayAgg
from django.db import models
from django.db.models import Count, F, Func, Q, UUIDField, Window
from django.db.models.functions import RowNumber
from django.utils import timezone
from django.utils.formats import number_format
from django.utils.translation import gettext as _, gettext_lazy

from farm.models import Batch, EquipmentSystem, SamplingPoint, Species, System, Tank, WaterLimit, WaterMeasurement
from farm.models.water import BASIS, BASIS_VALUE, LIVE_POINT, BasisSource
from farm.models.water_point import FlowRole, PointKind, kinds_with, local_time, owner_type_of, site_of
from farm.stock.dates import local_today
from farm.stock.read import Presence

from . import chemistry, judge, messages, parameters, sources
from . import freshness
from .evaluate import ALERTS, MAX_AHEAD, RANK, Limits, Status, ahead, crossed as bound_crossed, is_fresh, worst
from .parameters import NH3_N, NH4_N, OXYGEN_MG_L, OXYGEN_PCT, TAN

# The water's ionic-strength inputs of a TAN sample's ammonia (formula 3): looked up as its salinity is.
IONIC_INPUTS = parameters.AMMONIA_UNCOUNTED
# How far back the latest values, and a salinity for a sample without one, are looked for.
WINDOW = timedelta(days=30)
# The one order of a point's values in the database, newest first: the judge's ORDER_FIELDS, and nothing else (the parity
# of the two is tested, farm/tests/test_derived_fresh.py).
ORDER = tuple(F(name).desc() for name in judge.ORDER_FIELDS)
ORDER_BY = tuple(f'-{name}' for name in judge.ORDER_FIELDS)
# The late results of a point: at most LATE_READ are read and judged (the newest; the read counts the rest), the
# LATE_SAID worst of them are said one by one and the others as "and N more" (review 7, M1: a cap that says it cut).
LATE_READ, LATE_SAID = 50, 5
# What a stored sample must hold ITSELF for its ammonia to give a value (parameters.AMMONIA_OWN: the salinity may be found
# elsewhere): THE one definition (review 7, M7), for the derivation (`gives_value`) and for the look-back's two streams
# (CAN_GIVE, CANNOT_GIVE, of the samples with a TAN: HAS_TAN). A branch that lets a sample without one of them give a
# value changes it HERE, and the guard test (farm/tests/test_derived_fresh.py) holds the two together.
OWN_INPUTS = parameters.AMMONIA_OWN
HAS_TAN = Q(**{f'{TAN}__isnull': False})
CAN_GIVE = Q(**{f'{code}__isnull': False for code in OWN_INPUTS})
CANNOT_GIVE = HAS_TAN & ~CAN_GIVE


def gives_value(get):
    """Whether the values `get(code)` gives hold what an ammonia needs of its own sample (OWN_INPUTS)."""
    return all(get(code) is not None for code in OWN_INPUTS)
OXYGEN = 'oxygen'
# A reading per parameter, except oxygen: one reading of mg/L and % together.
SLOTS = {code: Q(**{f'{code}__isnull': False}) for code in parameters.COLUMNS if code not in (OXYGEN_MG_L, OXYGEN_PCT)}
SLOTS[OXYGEN] = Q(oxygen_mg_l__isnull=False) | Q(oxygen_saturation_pct__isnull=False)
# Entered oxygen in mg/L and in % may differ by this share before the page says so.
OXYGEN_TOLERANCE = Decimal('0.10')
LIMITED = {parameter.code for parameter in parameters.LIMITED}
# Every limited quantity, a measured column or a derived one (NH3-N), goes through the worst fresh value (owner, A10.1;
# third cross review): `latest` judges every fresh candidate of each of them.
WORST_FRESH_CODES = frozenset(LIMITED)
DERIVED = parameters.DERIVED      # the worked-out codes, each never fresher than its oldest input
# What a sample's label, clock and fish need loaded: its point, the owner of it and the owner's site.
POINT_RELATED = ('point__unit__production_department__site', 'point__system__site',
                 'point__equipment__production_department__site')
# Where a unit's water is read from (Source.via).
UNIT, SYSTEM = 'unit', 'system'
# The other points of a unit that measure its own water (owner rule A9.1, owner 2026-11-08): within it or leaving it (a
# depth point, an outlet, a drain); never an inlet, which measures the supply stream, not the unit's water.
OWN_WATER_KINDS = [kind for kind in kinds_with(FlowRole.WITHIN, FlowRole.OUT) if kind != PointKind.MIDDLE]


def assumed_salinity(water_types):
    """The salinity (ppt) to use where none was measured: 0 when every unit concerned (`water_types`: their
    Tank.WaterType values) is in fresh water, else None, never a guess: the value is then not worked out."""
    return Decimal(0) if set(water_types) == {Tank.WaterType.FRESHWATER} else None


def common_origin(units):
    """The water origin of units (Tank.water_origin; cross review F3): theirs when they all say the same, else '' (not
    said: a salinity of 1 to 5 permil is taken as diluted sea water). What the constants of a water are worked out
    with; whether a pH on a seawater scale is taken is `scale_origin`'s."""
    origins = {unit.water_origin for unit in units}
    return origins.pop() if len(origins) == 1 else ''


def scale_origin(units):
    """The water origin of units for the pH-scale rule (a pH on the total, the seawater or the free scale is taken for
    sea water only, never for fresh water with salt added: chemcore/core/src/scale.rs): salt added as soon as ONE unit
    of their water says so (`one_water`: they and every live unit of their systems), whatever the others say or leave
    unsaid; else `common_origin` of them. One water: salt added to a part of a loop is in all of it, so every point of
    that water answers alike, the loop's, each unit's middle point and its other own points (the verification of
    2026-11-18, V-C, and its re-check RC-1: a loop of a salt-added unit and one that says nothing took a total-scale
    7.95 as 8.09, first at the loop point, then at the other unit's own point), and "not said" is the side that
    converts. THE place it is decided: the sample door and the round (services.on_nbs) and the calculator loaded from
    a unit, a loop or a point (calculation.scale_origin_of). The constants themselves stay `common_origin`'s: no
    worked-out number moves."""
    if any(unit.water_origin == Tank.WaterOrigin.SALT_ADDED for unit in one_water(units)):
        return Tank.WaterOrigin.SALT_ADDED.value
    return common_origin(units)


def one_water(units):
    """The units whose water `units` are part of: they and every live unit of the systems they are in (a loop's water is
    one water, whichever of its points it is sampled at). A unit in no system is its own water. One query at most."""
    units = list(units)
    systems = {unit.system_id for unit in units if getattr(unit, 'system_id', None)}
    if not systems:
        return units
    given = {unit.pk for unit in units}
    return [*units, *(unit for unit in Tank.objects.filter(system__in=systems).order_by('code') if unit.pk not in given)]


def assumed_salinities(points):
    """{point id: the salinity assumed there}: 0 when every unit its water concerns (Context._served: the unit, the
    units of a loop or of the systems a piece of equipment serves) is in fresh water, else None. One read for all."""
    served = Context._served(list(points))
    return {pk: assumed_salinity(unit.water_type for unit in units) if units else None for pk, units in served.items()}


def assumed_salinity_at(point):
    """The salinity assumed at one sampling point (`assumed_salinities`)."""
    return assumed_salinities([point])[point.pk]


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


def system_chain(unit, systems):
    """The unit's system and the systems it is nested in, nearest first (`systems`: id -> System)."""
    found, seen = [], set()
    node = systems.get(unit.system_id)
    while node is not None and node.pk not in seen:
        seen.add(node.pk)
        found.append(node)
        node = systems.get(node.parent_id)
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


def origin_text(reading):
    """Where a latest value comes from, as every page says it (owner rule A1): 'unit sensor #12', 'system sensor #3', 'manual',
    'lab'; a live value names the channel that feeds it."""
    observation = reading.sample
    if observation.channel_no is not None:
        return f'{observation.origin_label} #{observation.channel_no}'
    return str(observation.origin_label)


def as_parameter(code, value):
    """A live value as the water parameter's Decimal at its decimals, exactly as a typed value: the unit's chart, the
    water pages and the replay read a sensor's value so."""
    return Decimal(repr(float(value))).quantize(parameters.get(code).step)


@dataclass(frozen=True)
class OnNbs:
    """What `ph_on_nbs` gives: the pH on the NBS scale at the pH column's decimals (`value`) and the formula version it
    was put on it by; or no value and why not (`refused`, a key of messages.PH_SENSOR_REFUSED): 'not_sea' where the
    core takes no pH on that scale (fresh water, salt added, below 5 ‰: Equilibria.takes_ph_scale), 'core' where it
    cannot work the water out at all, its own reason in `error` (the review of the water-chemistry audit, C5: such a
    water was said to be "not sea water")."""
    value: Decimal | None = None
    formula: int | None = None
    refused: str = ''
    error: str = ''

    def said(self, scale):
        """Why a pH on `scale` was not put on the NBS scale, in the words after "cannot be evaluated:"."""
        return messages.ph_sensor_refused(self.refused, scale, self.error)


def ph_on_nbs(ph, scale, temperature, salinity, origin):
    """The OnNbs of a pH measured on `scale` (a PhScale code) in water of this temperature and salinity, its salt from
    `origin` (`scale_origin`): its value on the NBS scale, or why there is none. THE conversion of every pH: a typed
    sample's (services.on_nbs), a sensor's (Context.sensor_ph), a replay frame's and a trail hour's."""
    try:
        equilibria = chemistry.water_equilibria(float(temperature), float(salinity), water_origin=origin)
        if not equilibria.takes_ph_scale(scale):
            return OnNbs(refused='not_sea')
        converted = equilibria.ph_nbs(float(ph), scale)
    except (ValueError, ArithmeticError) as error:      # a water the core cannot work out: its own reason
        return OnNbs(refused='core', error=str(error))
    return OnNbs(Decimal(repr(converted)).quantize(parameters.get(parameters.PH).step), equilibria.formula)


@dataclass(frozen=True)
class SensorPh:
    """A sensor's pH whose channel is on another scale than NBS, or whose scale changed (owner decision 1 of 2026-11-17;
    the water-chemistry audit of 2026-11-19, F1): what the probe gave (`as_measured`), on which scale ('' NBS) and since
    when that scale holds; once put on the NBS scale (`Context.sensor_ph`) the temperature, the salinity and the formula
    it was converted with; else why it was not (`refused`). Until it is converted its Observation holds no pH at all:
    the unconverted number is never a value."""
    scale: str
    as_measured: Decimal
    since: datetime | None = None
    temperature: Decimal | None = None
    salinity: Decimal | None = None
    formula: int | None = None
    refused: str = ''
    # Where the temperature it was converted with came from when not a fresh sensor's: 'manual, 19.11.2026 10:00'
    # (Basis.said; the review of the water-chemistry audit, C2), else ''.
    temperature_from: str = ''
    # When the temperature it was converted with stops being fresh: an NH₃ worked out from this pH is never fresher
    # (Context._ammonia records it with the pH's own end; review 3 of the branch, L4).
    temperature_until: datetime | None = None

    @property
    def converted(self):
        return self.formula is not None


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
    basis: dict = field(default_factory=dict)     # code -> Basis: what a sample's oxygen is worked out with
    ph: SensorPh | None = None                    # a sensor's pH not on the NBS scale as sent (SensorPh)
    # Combined from several (`combined`): {code: the moment the value of that code it holds stops being fresh}, each its
    # own source's, so a value worked out from them is never fresher than the oldest of them (`until`).
    ends: dict = field(default_factory=dict)

    @classmethod
    def of_sample(cls, sample):
        return cls(sample.point, sample.measured_at, Origin.LAB if sample.source == 'lab' else Origin.MANUAL,
                   sample.values(), is_deleted=sample.is_deleted, sample=sample, basis=Basis.of_sample(sample))

    @classmethod
    def of_sensor(cls, point, value, origin):
        """A sensor's value (sources.SensorValue) as the water parameter's Decimal, at its decimals. A pH from a channel
        on another scale than NBS holds no pH until `Context.sensor_ph` puts it on the NBS scale; one measured before its
        channel's scale changed holds none at all (its scale is not known): `ph` says which and why."""
        found = as_parameter(value.code, value.value)
        ph = None
        if value.code == parameters.PH and (value.ph_scale or value.ph_scale_from is not None):
            if value.ph_scale_from is not None and value.at < value.ph_scale_from:
                ph = SensorPh(value.ph_scale, found, value.ph_scale_from, refused=str(messages.ph_scale_changed(
                    local_time(value.ph_scale_from, point))))
            elif value.ph_scale:
                ph = SensorPh(value.ph_scale, found, value.ph_scale_from,
                              refused=str(messages.ph_sensor_refused('unconverted', value.ph_scale)))
            if ph is not None:
                found = None
        return cls(point, value.at, origin, {value.code: found}, channel_no=value.channel_no, role=value.role,
                   fresh_for=value.fresh_for, ph=ph)

    @classmethod
    def combined(cls, observations):
        """The sensor values a derived value is worked out from: their values together, at the oldest one's time, from
        the first one's point and origin, fresh as long as the least fresh of them, with the pH's conversion (`ph`) of
        the one that has it, and each value's own end (`ends`, `until`)."""
        first = observations[0]
        measured, ends_of = {}, {}
        for each in observations:
            measured.update(each.measured)
            ends_of.update({code: each.until(code) for code in each.measured})
        oldest = min(observations, key=lambda each: each.at)
        ends = [each.at + timedelta(seconds=each.fresh_for) for each in observations if each.fresh_for is not None]
        fresh_for = int((min(ends) - oldest.at).total_seconds()) if ends else None
        ph = next((each.ph for each in observations if each.ph is not None), None)
        return cls(first.point, oldest.at, first.origin, measured, fresh_for=fresh_for, ph=ph, ends=ends_of)

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

    def until(self, code):
        """The moment its value of `code` stops being fresh: the one kept for it where it was combined from several
        (`ends`), else its time plus its channel's seconds or the parameter's hours (freshness.fresh_until)."""
        found = self.ends.get(code)
        return found if found is not None else freshness.fresh_until(code, self.at, self.fresh_for)


@dataclass
class Worked:
    """What the shell fetched of a point's worked-out values for the judge (farm/water/judge.py): `found`, [(sample,
    {code: Reading})] of its samples that can give a value (CAN_GIVE), newest first in ORDER, down to the point's
    evidence value and its minute (`judge.settled`), `complete` False when it stopped at the judge's ceiling without
    evidence; `lacking`, its newest sample that cannot give one; `late`, the newest LATE_READ measured before the stored
    evidence's minute and entered after it, and `late_more`, how many more there are. The judge alone says what they
    mean (`Context.verdict`)."""
    found: list = field(default_factory=list)
    lacking: list = field(default_factory=list)
    late: list = field(default_factory=list)
    late_more: int = 0
    complete: bool = True


class Manual(dict):
    """A point's latest readings ({code: Reading}, `_manual`), and `worked`: {worked-out code: [Reading]} of every value
    the judge judges at the point, the place's candidates of it (`_resolve`)."""

    def __init__(self, readings, worked):
        super().__init__(readings)
        self.worked = worked


@dataclass(frozen=True)
class SampleTemperature:
    """The temperature an NH₃ is worked out with (Context.temperature_of): the value (None: none) and when it stops being
    fresh."""
    value: Decimal | None
    until: datetime | None = None


@dataclass(frozen=True)
class Basis:
    """What an oxygen entered without its own temperature or salinity is worked out with (second cross review,
    finding 1): the value found fresh at the sample's point and time when it was written, where it came from (an Origin
    value, or 'fresh_water' for fresh water's 0), the sensor's channel and when it was measured. Provenance of the
    conversion, never a measurement: read only by the oxygen's conversion (Context), never as the point's value."""
    value: Decimal
    source: str
    channel_no: int | None = None
    at: datetime | None = None

    @staticmethod
    def of_sample(sample):
        found = {}
        for code, prefix in BASIS.items():
            value = getattr(sample, BASIS_VALUE[code], None)
            if value is not None:
                found[code] = Basis(value, getattr(sample, f'{prefix}_source'), getattr(sample, f'{prefix}_channel'),
                                    getattr(sample, f'{prefix}_at'))
        return found

    def fields(self, code):
        """{model field: value} of this basis for `code` on a sample."""
        prefix = BASIS[code]
        return {BASIS_VALUE[code]: self.value, f'{prefix}_source': self.source, f'{prefix}_channel': self.channel_no,
                f'{prefix}_at': self.at}

    def said(self, point):
        """Where it came from, as a note says it: 'system sensor #3, 08.11.2026 10:00', 'manual, 08.11.2026 09:12'."""
        label = str(BasisSource(self.source).label)
        if self.channel_no is not None:
            label = f'{label} #{self.channel_no}'
        return f'{label}, {local_time(self.at, point):%d.%m.%Y %H:%M}' if self.at is not None else label


def observe(value):
    """An Observation of a sample, or the Observation given."""
    return Observation.of_sample(value) if isinstance(value, WaterMeasurement) else value


def SYSTEM_KEY(system_id):
    """The key a Series reads a system's own sensors under (a system without a loop point)."""
    return (sources.SYSTEM, system_id)


def sensor_targets(point):
    """[(target, origin)] of a point's OWN live values, in the order a tie goes: the sensors bound to the point, then, for
    a system's middle point (its loop), the sensors bound to the system, which are the loop's own. A unit's middle point
    reads its system's as the system's tier (`_places`)."""
    found = [((sources.POINT, point.pk), Origin.SENSOR)]
    if point.kind == PointKind.MIDDLE and point.system_id:
        found.append(((sources.SYSTEM, point.system_id), Origin.SYSTEM_SENSOR))
    return found


@dataclass(frozen=True)
class Tier:
    """One tier of owner rule A9 for a unit: the places whose values count together, the unit's OWN (`via` UNIT: its
    own-water points) or one SYSTEM's (`via` SYSTEM, `owner` the system: its loop point, or with no loop point the
    system's own sensors). `points`: the sampling points whose samples count; `targets`: [(live target, origin)] of
    the sensors that count, in the order a tie goes; `keys`: what a Series of them is read under (a point's id, or
    SYSTEM_KEY for a system without a loop point)."""
    via: str
    owner: object
    points: tuple
    targets: tuple
    keys: tuple


def tiers(units, *, nested, own=None, sites=True):
    """{unit id: [Tier]}: owner rule A9's tiers of each unit, nearest first: THE resolver of where a unit's water is
    read, for every reader of it (the water page's `_places`, the ration's temperature in farm/feeding/temperature.py,
    the degree-days' day in farm/water/degree_days.py, the closing of probe days in farm/water/services.py, and the
    sensors' trail and a unit's chart, sensors/read.py `tiers` and `places`). The unit's own-water points (`own_water`: the middle point first, never the inlet), then its system (its loop point, or
    the system's own sensors when it has no loop point, as the water page reads them), then, when `nested`, the loop
    points of the systems that one is nested in. Which tier wins and how is each reader's (the newest fresh value; the
    lowest of a day); where a unit's water is read is not.

    `own`: the units' `own_water` when the caller has read it (not read again). `sites`: a system without a loop point
    is read with its site (its clock, one query); without, it is a System holding its id only. One query for the loops
    of the systems, and for `nested` one for the systems."""
    units = list(units)
    if own is None or not {unit.pk for unit in units} <= set(own):
        own = own_water([unit.pk for unit in units])
    if nested and any(unit.system_id for unit in units):
        known = System.objects.select_related('site').in_bulk()
        chains = {unit.pk: system_chain(unit, known) for unit in units}
    else:
        chains = {unit.pk: [System(pk=unit.system_id)] if unit.system_id else [] for unit in units}
    loops = middle_points({system.pk: system for chain in chains.values() for system in chain}.values())
    bare = {unit.system_id for unit in units if unit.system_id and unit.system_id not in loops}
    systems = {}
    if bare:
        systems = ({pk: system for pk, system in known.items() if pk in bare} if nested and sites
                   else System.objects.select_related('site').in_bulk(bare) if sites
                   else {pk: System(pk=pk) for pk in bare})
    found = {}
    for unit in units:
        points = own.get(unit.pk, [])
        made = []
        if points:
            made.append(Tier(UNIT, unit, tuple(points),
                             tuple(target for point in points for target in sensor_targets(point)),
                             tuple(point.pk for point in points)))
        chain = chains[unit.pk]
        if chain and chain[0].pk in systems:
            system = systems[chain[0].pk]
            made.append(Tier(SYSTEM, system, (), (((sources.SYSTEM, system.pk), Origin.SYSTEM_SENSOR),),
                             (SYSTEM_KEY(system.pk),)))
        made += [Tier(SYSTEM, loops[system.pk].owner, (loops[system.pk],), tuple(sensor_targets(loops[system.pk])),
                      (loops[system.pk].pk,)) for system in chain if system.pk in loops]
        found[unit.pk] = made
    return found


@dataclass(frozen=True)
class Found:
    """A value found at a moment (Series.latest): when it was measured, the value, how long it stays fresh (seconds, None
    for a sample: the parameter's hours), where it came from and the point it was measured at."""
    at: datetime
    value: Decimal
    fresh_for: int | None = None
    origin: str = Origin.MANUAL
    point: object = None


class Series:
    """One parameter's values over time at a set of points, read in one query: what "the latest value at a
    moment" is looked up in, for a sample without a salinity here and for a unit's temperature on the day of its
    ration (farm/feeding/temperature.py). Live samples of live points only; with `live`, the sensors too (asked once
    per point and moment; a system's middle point has the system's sensors as its own). A sample's own workings never
    take a live value (its salinity series is not live). With `carry`, each point's newest sample before `since` is read
    too (one more query), so the newest value is found however old (owner amendment A11: the ration). `systems`: the
    ids of systems without a loop point whose sensors are read too, under the key SYSTEM_KEY(id), with no point (the
    ration's system tier where the water page reads the system's sensors)."""

    def __init__(self, points, code, since, until=None, live=False, carry=False, systems=()):
        self.code, self.live = code, live
        self.points = {point.pk: point for point in points}
        self.targets = {point.pk: sensor_targets(point) for point in points}
        for system_id in systems:
            key = SYSTEM_KEY(system_id)
            self.points[key] = None
            self.targets[key] = [((sources.SYSTEM, system_id), Origin.SYSTEM_SENSOR)]
        self.moments = defaultdict(list)    # point id -> [measured at], in time order
        self.values = defaultdict(list)     # point id -> [value], in the same order
        self.asked = {}                     # moment -> {point id: [Found]} of the sensors
        self.bound = set()                  # the sensor targets with a channel of the parameter bound in the range
        chosen = [pk for pk, point in self.points.items() if point is not None]
        if chosen:
            measured = {f'{code}__isnull': False}
            rows = WaterMeasurement.objects.filter(point__in=chosen, measured_at__gte=since, **measured)
            if until is not None:
                rows = rows.filter(measured_at__lte=until)
            found = list(rows.order_by('measured_at').values_list('point_id', 'measured_at', code))
            if carry:
                before = (WaterMeasurement.objects.filter(point__in=chosen, measured_at__lt=since, **measured)
                          .order_by('point_id', '-measured_at').distinct('point_id')
                          .values_list('point_id', 'measured_at', code))
                found = [*before, *found]
            for point_id, moment, value in found:
                self.moments[point_id].append(moment)
                self.values[point_id].append(value)
        if live and self.points:
            wanted = [target for targets in self.targets.values() for target, _origin in targets]
            self.bound = sources.bound(wanted, code, since, until or timezone.now())

    def prefetch(self, moments):
        """Asks the live sources ONCE for every moment of `moments` not asked yet (sources.values_at), for every point of
        the series: a reader that knows the moments it will look up (the ration's days, farm/feeding/read.py) costs the
        same queries for one moment or a hundred. What a moment's lookup finds is the same either way.

        One failing ask fails every moment of it together, so an answer that says a source failed is NOT kept: each of
        those moments is asked on its own when it is looked up (`_live`, `sources.value_at`: the way it always was), and
        a failure costs only the moments it really hits (one that was only that ask's costs none)."""
        if not self.live:
            return
        moments = [moment for moment in dict.fromkeys(moments) if moment not in self.asked]
        if not moments:
            return
        targets = self._bound_targets()
        if not any(targets.values()):
            self.asked.update({moment: {} for moment in moments})
            return
        answers = sources.values_at([target for found in targets.values() for target, _origin in found], self.code,
                                    moments)
        for moment, answer in zip(moments, answers):
            if not answer.failed:
                self._keep(moment, answer, targets)

    def _bound_targets(self):
        """{point id: [(target, origin)]}: each point's sensor targets that had a channel of the parameter bound."""
        return {pk: [(target, origin) for target, origin in found if target in self.bound]
                for pk, found in self.targets.items()}

    def _keep(self, moment, answer, targets):
        """Keeps the sensors' answer for `moment`: each point's values (Found, in sensor_targets' order, primary first)
        at or before it."""
        by_point = {}
        for pk, found in targets.items():
            values = []
            for target, origin in found:
                for value in sources.ordered(answer.values.get(target, [])):
                    if value.at <= moment:
                        observed = Observation.of_sensor(self.points[pk], value, origin)
                        values.append(Found(value.at, observed.get(self.code), value.fresh_for, origin,
                                            self.points[pk]))
            by_point[pk] = values
        self.asked[moment] = by_point

    def _live(self, point_id, moment, window):
        """The sensors' values of the point at the moment (Found, in sensor_targets' order, primary first), at most
        `window` old. One ask of the live sources per moment for every point of the series (`sources.value_at`), unless
        `prefetch` was given the moment, so the queries do not grow with the points. An answer is kept even when a source
        failed in it: a failing source is asked once per moment, as it always was."""
        if moment not in self.asked:
            targets = self._bound_targets()
            if not any(targets.values()):
                self.asked[moment] = {}
                return []
            self._keep(moment, sources.value_at([target for found in targets.values() for target, _origin in found],
                                                self.code, moment), targets)
        return [found for found in self.asked[moment].get(point_id, []) if window is None or moment - found.at <= window]

    def candidates(self, point_id, moment, window):
        """The point's values at `moment` (Found) at or before it and at most `window` older, in the order a tie at one
        measurement time goes (`choose`): its sensors' (primary first), then its newest sample's."""
        found = list(self._live(point_id, moment, window)) if self.live else []
        moments = self.moments.get(point_id, [])
        index = bisect_right(moments, moment) - 1
        if index >= 0 and (window is None or moment - moments[index] <= window):
            found.append(Found(moments[index], self.values[point_id][index], point=self.points[point_id]))
        return found

    def fresh(self, found, moment):
        """Whether a Found is fresh at `moment` (evaluate.is_fresh, the one rule)."""
        return is_fresh(parameters.get(self.code), found.at, moment, found.fresh_for)

    def latest(self, point_id, moment, window):
        """The point's value at `moment` (Found), picked by `choose` (owner rule A9) from its `candidates`: the newest
        fresh, a sensor's or a sample's; else the newest at most `window` older, stale; None when there is none."""
        return choose([self.candidates(point_id, moment, window)], moment, lambda found: self.fresh(found, moment))


# ---- what a reading is -----------------------------------------------------------------------------------
@dataclass
class Reading:
    """One parameter's value from one Observation (a sample, a sensor's value, or the sensor values a derived value is
    worked out from): entered or measured, or worked out (`derived`); None when it could not be worked out, `note`
    saying why. `status` and the limit rows that judged it come from evaluate: `status` is what a page shows (stale once
    the value is old), `judged` what the limits say of the value whatever its age, so an old critical value is never
    forgotten (a card stays critical and says the value is old)."""
    parameter: parameters.Parameter
    value: Decimal
    sample: Observation
    derived: bool = False
    note: str = ''
    status: str = Status.NOT_MEASURED
    limits: list = field(default_factory=list)
    judged: str = Status.NOT_MEASURED
    uncovered: tuple = ()          # the species it concerns that no limit row judges it for
    worse: object = None           # the worse fresh value that decided its status (worst_fresh), else None
    # The place's other values that take part in its status (latest: fresh, or ahead of the clock within the ingest
    # contract's hour), each judged for its fish: what an alarm on the reading clears only past (alarms/sources.py).
    deciding: tuple = ()
    through: object = None         # the Reading in the other oxygen unit it was judged as (Context.judge), else None
    why_no_limit: str = ''      # with status No limit: no fish in the unit that day, or no limit for their species
    provenance: str = ''        # a worked-out value: the formula version (and ionic strength) it was worked out by
    # A value stored converted (a pH measured on another scale than NBS): what was measured, in the few words every page
    # prints visibly beside the stored number (farm/_water_value.html; review R6); the whole sentence is `provenance`.
    # A refused NH₃ judged on the limits' basis alone says so the same way ("at least: the limits' basis", RC-3).
    measured: str = ''
    # A worked-out value the chemistry core REFUSED to work out (its own reason, in its words; '' otherwise). Where the
    # fish have a limit for it (`limits`, set by Context.judge) it is "cannot be evaluated", never "not measured": the
    # unit's state says so and the alarm source raises a warning for the unit (the verification of 2026-11-18, V-A).
    # Its `value`, when it has one, is the limits' basis alone, at least the judged value (Context._ammonia_on_basis):
    # judged past a limit it is that limit's status, else "cannot be evaluated"; it is never evidence that an alarm is
    # over (alarms/sources.py clear_evidence).
    refused: str = ''
    # The unit's own last value of the parameter, stale and judged critical or a warning, where the value shown stands in
    # from its system (`last_own`; decision of 2026-11-19 on the verification's F3-9): it keeps the status, and the page,
    # the card and the alarm say "last own value …, measure this unit".
    last_own: object = None
    # A worked-out value as it was worked out, before `value` was rounded to the parameter's decimals for display: what
    # the limits judge (`judged_value`; the water-chemistry audit of 2026-11-19, F3: a true 0.01034 mg/L NH₃-N read
    # 0.0103 and was OK against a limit of 0.0103). None for a measured value, which is judged as entered.
    exact: Decimal | None = None
    # A worked-out value: {input code: the moment it stops being fresh} of EVERY input its derivation used, recorded where
    # it read them (Context._ammonia): its observation's own (`Observation.until`), a salinity found at the point or its
    # owner's middle point, the place's sensor temperature; None for an input with no measured value (fresh water's 0,
    # one missing so nothing was worked out). What `fresh_until` takes, and nothing else.
    inputs_until: dict = field(default_factory=dict)

    @property
    def judged_value(self):
        """The value the limits judge: the unrounded one where it was worked out (`exact`), else `value`."""
        return self.exact if self.exact is not None else self.value

    @property
    def unevaluated(self):
        """Whether the limits would judge this value and the core refused to work it out."""
        return bool(self.refused and self.limits)

    @property
    def last_own_said(self):
        """The visible words beside the value of a status the unit's own stale value keeps (`last_own`), else ''."""
        return messages.last_own(self.last_own) if self.last_own is not None else ''

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
    def decided_at(self):
        """The point whose value decided this reading's judgement: the worse fresh value's (`worst_fresh`), else its own."""
        return (self.worse or self).point

    @property
    def origin(self):
        return self.sample.origin

    def age(self, now=None):
        return (now or timezone.now()) - self.at

    @property
    def old_alert(self):
        """What the limits said of a value that is no longer fresh when it was critical or a warning, else '': the pages
        show such a value as old and as what it was, never as only "stale" (F-244)."""
        return self.judged if self.status == Status.STALE and self.judged in ALERTS else ''

    @property
    def fresh_until(self):
        """The moment it stops saying something about the water now: a measured value its time plus its sensor's seconds
        or its parameter's hours (freshness.fresh_until); a worked-out one (a parameter with `inputs`) when the first
        value it was worked out with stops (freshness.derived_until: never fresher than its oldest input), from the inputs
        its derivation recorded as used (`inputs_until`): an input it used and the parameter does not declare, or one
        declared and not recorded, is refused (ValueError), never guessed. THE answer every reader takes: the pages, the
        cards, the alarms (`fresh`)."""
        if not self.parameter.inputs:
            return freshness.fresh_until(self.code, self.at, self.sample.fresh_for)
        return freshness.derived_until(self.code, self.at, self.inputs_until)

    def fresh(self, now):
        """Whether it still says something about the water now (evaluate.is_fresh, the one rule, to `fresh_until`)."""
        return is_fresh(self.parameter, self.at, now, self.sample.fresh_for, self.fresh_until)


def reading_of(code, observation):
    """The Reading of one measured value of an observation, saying what was measured where it was put on another scale
    or unit: a sample's pH measured on another scale than NBS, a sample's phosphate entered as PO₄, a sensor's pH put on
    the NBS scale (`Observation.ph`). A sensor's pH that could not be put on it has no value and keeps the reason
    (`refused`): where the fish have a pH limit it cannot be evaluated (Context.judge), never shown unconverted."""
    reading = Reading(parameters.get(code), observation.get(code), observation)
    sample = observation.sample
    if code == parameters.PH and sample is not None and sample.ph_scale:
        # A pH measured on another scale is stored on the NBS scale; the reading says what was measured.
        reading.provenance = str(messages.ph_measured(sample))
        reading.measured = str(messages.ph_measured_short(sample))
    elif code == parameters.PH and observation.ph is not None:
        ph = observation.ph
        if ph.converted:
            reading.provenance = str(messages.ph_sensor_converted(ph))
            reading.measured = str(messages.ph_measured_words(ph.as_measured, ph.scale))
        else:
            reading.note = str(messages.ph_not_converted(ph.refused))
            reading.refused = ph.refused
    if code == parameters.PHOSPHATE and sample is not None and sample.phosphate_unit:
        # A phosphate entered as PO₄ is stored as P; the reading says what was entered.
        reading.provenance = str(messages.phosphate_measured(sample))
        reading.measured = str(messages.phosphate_measured_short(sample))
    return reading


@dataclass(frozen=True)
class Silence:
    """A unit that holds fish whose oxygen has no fresh value (owner decision of 2026-11-23): `reading`, its newest
    oxygen value (mg/L, else %) with its age at `now`, or None when it has none in the window."""
    reading: object
    now: datetime

    @property
    def since(self):
        """When the oxygen stopped being fresh: its newest value's `Reading.fresh_until` (`now` when it has none)."""
        if self.reading is None:
            return self.now
        return min(self.now, self.reading.fresh_until)


@dataclass
class PointWater:
    """The latest readings of one sampling point, by parameter code; `point` is None for a unit that has no
    middle point (unit_water), which has no readings. `sensors_failed`: a live source could not be read, so what is
    shown comes from the samples alone (the pages say so).

    Two statuses, kept apart on purpose (owner, 2026-11-08):
    - `status` is COMPUTED FOR THE PLACE the point stands for: for a unit's middle point, the unit (its other own-water
      points' values and its system's stand in, A9.1, and the worst fresh value decides, P2): what its card, its alarm
      and its row show;
    - `point_status` is what was MEASURED AT THE POINT itself (`measured`: each value taken there, judged before any
      other point's value decided): what a count of critical points counts, so one physical problem is counted once."""
    point: object
    readings: dict = field(default_factory=dict)
    sensors_failed: bool = False
    measured: list = field(default_factory=list)     # [(status, judged)] of the limited values taken at the point
    for_unit: bool = False      # the point stands for its unit (its middle point, or its anchor without one)
    future: list = field(default_factory=list)       # readings stamped more than MAX_AHEAD ahead: a data error
    holds_fish: bool = False    # a point that stands for its unit: the unit holds fish on its own day (`latest`)
    silent_oxygen: object = None    # Silence: the unit holds fish and its oxygen has no fresh value (`latest`)
    targets: frozenset = frozenset()    # the sensor targets its place reads (own, then its system's)
    system_point: object = None     # a unit without a point of its own: its system's loop point it is read at, if any
    standing_place: object = None   # a unit without a point of its own: where it is read (its loop point, else system)
    # {code: Reading}: an own point's sample newer than its newest worked-out value that the core refused to work out
    # (judged for the place's fish). Never the value shown (review 4 of the branch, L5), but never silent: it is
    # "cannot be evaluated" on the pages and in the alarm system's warning (V-A; `unevaluated`).
    refused_newer: dict = field(default_factory=dict)

    @staticmethod
    def _rolled_up(counted):
        """The one rule of a point's status over [status as counted]: an old critical or warning value still counts
        ("critical, no recent data": never hidden by a fresh OK of another parameter, never "No limit"); else the worst
        fresh judgement; Stale when a value with a limit grew old and nothing fresh is judged; else No limit or Not
        measured."""
        judged = [status for status in counted
                  if status in (Status.CRITICAL, Status.WARNING, Status.UNEVALUATED, Status.OK)]
        if judged:
            return worst(judged)
        return Status.STALE if Status.STALE in counted else worst(counted)

    @staticmethod
    def _as_counted(status, judged):
        """A value's status as a point counts it: an old critical or warning value keeps its judgement, and so does an
        old one that cannot be evaluated (never OK behind a fresh value of another parameter)."""
        return judged if status == Status.STALE and judged in (*ALERTS, Status.UNEVALUATED) else status

    def _counted(self):
        silent = [Status.CRITICAL] if self.silent_oxygen is not None else []
        return [self._as_counted(reading.status, reading.judged) for reading in self.readings.values()
                if reading.code in LIMITED] + silent

    @property
    def status(self):
        """The worst of its values, computed for the place the point stands for (`_rolled_up`)."""
        return self._rolled_up(self._counted())

    @property
    def point_status(self):
        """The worst of the values measured at the point itself (`measured`), by the same rule."""
        silent = [Status.CRITICAL] if self.silent_oxygen is not None else []
        return self._rolled_up([self._as_counted(status, judged) for status, judged in self.measured] + silent)

    @property
    def old_alert(self):
        """Whether the point's critical or warning comes only from old values: the page adds "no recent data"."""
        status = self.status
        return status in ALERTS and not any(reading.status == status for reading in self.readings.values()
                                            if reading.code in LIMITED)

    @property
    def why_no_limit(self):
        """Why the point's values have no limit, when that is its status."""
        if self.status != Status.NO_LIMIT:
            return ''
        return next((reading.why_no_limit for reading in self.readings.values() if reading.why_no_limit), '')

    @property
    def unjudged(self):
        """The values that some of the fish they concern have no limit row for (`Reading.uncovered`: "no limit", the
        owner has set none for them), fresh or old, in reading order; the oxygen is one quantity, judged through either
        unit's rows where it can be worked out (Context.judge_oxygen), so a value that stays here could not be. Where
        there are no fish nothing is judged, so the caller asks only where there are fish."""
        return [reading for reading in self.readings.values()
                if reading.code in LIMITED and reading.value is not None and reading.uncovered]

    @property
    def unevaluated(self):
        """The values the limits would judge that the chemistry core refused to work out (`Reading.unevaluated`), fresh
        or old, in reading order: what the water page, the card, the overview and the alarm say cannot be evaluated."""
        return [*(reading for reading in self.readings.values() if reading.code in LIMITED and reading.unevaluated),
                *(reading for code, reading in self.refused_newer.items()
                  if reading.unevaluated and not (self.readings.get(code) is not None
                                                  and self.readings[code].unevaluated))]

    @property
    def why_unevaluated(self):
        """[sentence] of `unevaluated`: 'NH₃ … cannot be evaluated: <the core's reason>.' (messages.unevaluated)."""
        return [messages.unevaluated(reading) for reading in self.unevaluated]

    @property
    def why_last_own(self):
        """['<label>: last own value … measure this unit'] of the values whose status the unit's own stale value keeps
        (`Reading.last_own`): what the card says beside the status."""
        return [f'{reading.parameter.label}: {messages.last_own(reading.last_own)}' for reading in self.readings.values()
                if reading.last_own is not None]

    @property
    def standing_said(self):
        """'From its system, RAS 1 › Middle: the unit has no sampling point of its own.' for a unit read at its system
        (`latest`, `units`), else '': what its values say, the drawer and the card's water table say it above them."""
        return str(messages.from_system(self.standing_place)) if self.standing_place is not None else ''

    @property
    def why_silent(self):
        """['O₂ (mg/L): no recent data, 3 hours old'] when the unit holds fish and its oxygen has no fresh value
        (`silent_oxygen`, critical: owner decision of 2026-11-23): what the card, the band and the alarm say."""
        return [messages.no_fresh_oxygen(self.silent_oxygen)] if self.silent_oxygen is not None else []

    @property
    def alerts(self):
        """Each value of the point with a critical or warning judgement as the point counts it (`_counted`: an old one
        keeps its judgement), as (reading, status, old): one rule for the water page, the unit drawer and the card."""
        found = []
        for reading in self.readings.values():
            if reading.status in ALERTS:
                found.append((reading, reading.status, False))
            elif reading.status == Status.STALE and reading.judged in ALERTS and reading.code in LIMITED:
                found.append((reading, reading.judged, True))
        return found

    @property
    def worst_alert(self):
        """The one alert of `alerts` the point says first when it says one (a site's line on the company overview): a
        critical before a warning, a fresh value before an old one, else in reading order; only a value of its own (a
        reading without one is judged through another and said there). None when it has none."""
        found = [alert for alert in self.alerts if alert[0].value is not None]
        return min(found, key=lambda alert: (alert[1] != Status.CRITICAL, alert[2]), default=None)

    @property
    def newest_at(self):
        """When the newest of its values was taken, or None (what "no recent data" is counted from)."""
        return max((reading.at for reading in self.readings.values() if reading.at is not None), default=None)

    def get(self, code):
        return self.readings.get(code)


# ---- the fish in a unit on a day ----------------------------------------------------------------------------
def holds(presence, unit_id, day):
    """Whether the unit holds fish after the operations of `day` (farm.stock.read.Presence): SpeciesBook.holds."""
    return any(presence.count_at_end(unit_id, batch_id, day) > 0 for batch_id in presence.batches.get(unit_id, ()))


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

    def holds(self, unit_id, day):
        """Whether the unit holds fish NOW, on `day` (its own day): after that day's operations (an operation has a day,
        not a time), so a unit harvested or emptied earlier today holds none any more while one stocked today does.
        THE rule of "a unit with fish" for its oxygen (owner decision of 2026-11-23; review 2 of the branch, R1): the
        card's and the water pages' judgement (`_silence`), the alarm system's oxygen alarm and the sensors' default
        rules (`with_fish`). The limits judge a day's values for every fish of that day (`on`), harvested ones too."""
        return holds(self.presence, unit_id, day)


# ---- everything a set of points needs, read once ----------------------------------------------------------
class Context:
    """The points' units, the fish in them, their salinity over time and the limits. With `since` None, the fish and the
    limits alone (`limits_of`: no value is read there, so neither the middle points nor the salinity are)."""

    def __init__(self, points, since, units=()):
        points = list(points)
        self.served = self._served(points)                # point id -> the live units its water concerns
        self.served.update({unit.pk: [unit] for unit in units})     # a unit read without a point (`latest`, `units`)
        self.until = None                        # a read of the past: the samples up to that moment (`latest`)
        self._worked, self._newest = {}, {}      # a sample's readings; a point's worked-out values (`worked_at`)
        self._samples = {}                        # sample id -> the one object of it in this Context (`_derived`)
        self.since = since                        # the read's window starts here (`latest`: its moment less WINDOW)
        self.book = SpeciesBook({unit.pk for units in self.served.values() for unit in units})
        species = set(self.book.species.values())
        self.limits = Limits(WaterLimit.objects.filter(species_id__in=species, species__is_deleted=False))
        if since is None:
            self.middles, self.salinity = {}, None
            self._series_points, self._since, self._ionic = [], None, {}
            return
        self.middles = middle_points({point.owner.pk: point.owner for point in points}.values())
        self.salinity = Series([*points, *self.middles.values()], parameters.SALINITY, since - WINDOW)
        self._series_points, self._since = [*points, *self.middles.values()], since - WINDOW
        self._ionic = {}                                   # code -> Series, read once, when an ammonia needs it

    @staticmethod
    def _served(points):
        """{point id: [unit]}: the units a point's water is judged for (`units_served`)."""
        return units_served(points)[0]

    # -- the water a sample was taken in --
    def water_types(self, point):
        return {unit.water_type for unit in self.served[point.pk]}

    def water_origin(self, point):
        """Where the salt of the water at a point comes from (Tank.water_origin; cross review F3): its units' origin when
        they all say the same, else '' (not said: a salinity of 1 to 5 permil is taken as diluted sea water)."""
        return common_origin(self.served[point.pk])

    @staticmethod
    def _why_no_limit(exposures):
        """Why a value has no limit: no fish where it was taken that day, or no limit row for the fish there. The species
        is not named: a page that may read the water need not be one that may read the stock."""
        if not exposures:
            return _('No fish in the unit: nothing to judge the water against.')
        return _('No water limit is set for the fish in the unit.')

    def holds_fish(self, point, day):
        """Whether a unit the point's water concerns holds fish now, on `day` (SpeciesBook.holds)."""
        return any(self.book.holds(unit.pk, day) for unit in self.served[point.pk])

    def exposures(self, point, day):
        """[(species id, water type)] a value at this point on `day` is judged for."""
        return [(species_id, unit.water_type) for unit in self.served[point.pk]
                for species_id in self.book.on(unit.pk, day)]

    def _ionic_series(self, code):
        if code not in self._ionic:
            self._ionic[code] = Series(self._series_points, code, self._since)
        return self._ionic[code]

    def ionic_inputs_for(self, observation):
        """{code: float or None} of the alkalinity, the conductivity at 25 °C and the hardness a TAN sample's ammonia is
        worked out with (formula 3's ionic strength): each the observation's own, else its point's latest sample fresh
        at its time (a stale value never enters, PLAN A9.3), else its owner's middle point's; None when there is none;
        and 'water_origin', its units' (`water_origin`)."""
        observation = observe(observation)
        found = {}
        for code in IONIC_INPUTS:
            value = observation.get(code)
            if value is None:
                fresh = freshness.fresh_for(code)
                for where in (observation.point, self.middles.get(observation.point.owner.pk)):
                    hit = None if where is None else self._ionic_series(code).latest(where.pk, observation.at, fresh)
                    if hit is not None and self._ionic_series(code).fresh(hit, observation.at):
                        value = hit.value
                        break
            found[code] = None if value is None else float(value)
        found['water_origin'] = self.water_origin(observation.point)
        return found

    def salinity_for(self, observation):
        """The observation's salinity, else its point's latest sample fresh at its time (at or before it, within the
        salinity's freshness: a stale salinity never enters a calculation, PLAN A9.3), else its owner's middle point's,
        else 0 where every unit it concerns is in fresh water; None when there is none."""
        return self.salinity_found(observation)[0]

    def salinity_found(self, observation):
        """(`salinity_for`'s salinity, the moment it stops being fresh): what a value worked out with it takes as that
        input's end (Reading.inputs_until). The observation's own value its own end (`Observation.until`); its oxygen's
        basis, the basis's time plus the salinity's hours (fresh water's 0: None); the point's or the middle point's
        value, its own end; fresh water's 0 assumed, or none: None (no measured value entered)."""
        observation = observe(observation)
        if observation.get(parameters.SALINITY) is not None:
            return observation.get(parameters.SALINITY), observation.until(parameters.SALINITY)
        if parameters.SALINITY in observation.basis:
            basis = observation.basis[parameters.SALINITY]
            if basis.source == BasisSource.FRESH_WATER:
                return basis.value, None
            return basis.value, freshness.fresh_until(parameters.SALINITY, basis.at or observation.at)
        point = observation.point
        fresh = freshness.fresh_for(parameters.SALINITY)
        for where in (point, self.middles.get(point.owner.pk)):
            found = None if where is None else self.salinity.latest(where.pk, observation.at, fresh)
            if found is not None and self.salinity.fresh(found, observation.at):
                return found.value, freshness.fresh_until(parameters.SALINITY, found.at, found.fresh_for)
        return assumed_salinity(self.water_types(point)), None

    # -- a sensor's pH on another scale --
    def sensor_ph(self, observation, fresh_live, now, temperature=None, at_moment=None):
        """A sensor's pH observation put on the NBS scale (owner decision 1 of 2026-11-17; the water-chemistry audit of
        2026-11-19, F1), exactly as a typed sample's (`ph_on_nbs`): with the place's fresh temperature from the sensors
        (`fresh_live`, {code: the newest fresh live Observation}, as a sensor's TAN takes its pH and temperature), else
        the place's chosen `temperature` (a Reading: a sample's, or a sensor's no longer fresh now) where it is fresh AT
        the pH's own time (`fresh_at`, as the oxygen's other unit takes the point's temperature, `_in_other_unit`; the
        replay and the trail convert with a sample's temperature too: the review of the audit, C2), and the salinity of
        the same moment (`salinity_for`: a fresh sensor's, else the point's fresh sample's, else 0 in fresh water), for
        sea water of 5 ‰ or more only (`scale_origin`). A pH no longer fresh at `now` is put on it the same way at its
        own moment, with the place's sensor values fresh THEN (`at_moment(its time)`, {code: Observation}) instead of
        now's, and is shown stale as an NBS one is (owner decision of 2026-11-20: one behaviour for every scale; that its
        probe stopped is the channel's default "No fresh value" rule's to say, sensors.AlarmRule.is_default). Otherwise
        the observation keeps no pH and says why (`SensorPh.refused`). An observation that needs nothing is returned as
        it is."""
        ph = observation.ph
        if ph is None or ph.converted or not ph.scale or observation.get(parameters.PH) is not None \
                or (ph.since is not None and observation.at < ph.since):
            return observation

        def refused(why, error=''):
            return replace(observation, ph=replace(ph, refused=str(messages.ph_sensor_refused(why, ph.scale, error))))

        if not is_fresh(parameters.get(parameters.PH), observation.at, now, observation.fresh_for):
            fresh_live = at_moment(observation.at) if at_moment is not None else {}
        sensed, said = fresh_live.get(parameters.TEMPERATURE), ''
        if sensed is None or sensed.get(parameters.TEMPERATURE) is None:
            if temperature is None or temperature.value is None or not fresh_at(temperature, observation.at):
                return refused('temperature')
            # The place's temperature fresh at the pH's time, alone (never the rest of its sample), saying where from.
            sensed = replace(temperature.sample, measured={parameters.TEMPERATURE: temperature.value})
            said = Basis(temperature.value, temperature.origin, temperature.sample.channel_no,
                         temperature.at).said(observation.point)
            temperature_until = temperature.fresh_until
        else:
            temperature_until = sensed.until(parameters.TEMPERATURE)
        salinity_observation = fresh_live.get(parameters.SALINITY)
        together = Observation.combined([observation, sensed, *([salinity_observation]
                                                               if salinity_observation is not None else [])])
        salinity = self.salinity_for(together)
        if salinity is None:
            return refused('salinity')
        temperature = sensed.get(parameters.TEMPERATURE)
        served = self.served.get(observation.point.pk)
        origin = scale_origin(served if served is not None else Context._served([observation.point])[observation.point.pk])
        found = ph_on_nbs(ph.as_measured, ph.scale, temperature, salinity, origin)
        if found.value is None:
            return refused(found.refused, found.error)
        return replace(observation, measured={parameters.PH: found.value},
                       ph=replace(ph, temperature=temperature, salinity=salinity, formula=found.formula, refused='',
                                  temperature_from=said, temperature_until=temperature_until))

    # -- one observation's readings --
    def readings(self, observation):
        """{code: Reading} of a sample or an Observation: what was measured and what follows from it. A stored sample's
        readings are worked out once per Context (`_worked`): a read that meets it again (another slot, the look-back of
        `newest_worked`) asks nothing again."""
        if isinstance(observation, WaterMeasurement):
            held = self._worked.get(observation.pk)
            if held is None:
                sample = self._samples.setdefault(observation.pk, observation)
                held = self._worked[observation.pk] = self._readings(observe(sample))
            return held
        return self._readings(observe(observation))

    def _readings(self, observation):
        found = {code: reading_of(code, observation) for code in observation.values()}
        salinity, salinity_until = self.salinity_found(observation)
        if observation.get(TAN) is not None:
            found.update(self._ammonia(observation, salinity, salinity_until, self.temperature_of(observation)))
        if observation.get(OXYGEN_MG_L) is not None or observation.get(OXYGEN_PCT) is not None:
            found.update(self._oxygen(observation, self._oxygen_temperature(observation), salinity))
        return found

    @staticmethod
    def _oxygen_temperature(observation):
        """The temperature a sample's oxygen is converted with: its own, else the basis stored with it when it was written
        (so a conversion never moves). The oxygen's alone: the NH₃ never takes another sample's temperature
        (`temperature_of`; review 4 of the branch, H3)."""
        if observation.get(parameters.TEMPERATURE) is not None:
            return observation.get(parameters.TEMPERATURE)
        basis = observation.basis.get(parameters.TEMPERATURE)
        return basis.value if basis is not None else None

    @staticmethod
    def _salinity_missing():
        return _('Needs the salinity: none was measured here in the %(days)d days before.') % {
            'days': freshness.fresh_for(parameters.SALINITY).days}

    @staticmethod
    def _same_source_missing(observation):
        if observation.live:
            return _('Needs a fresh pH and temperature from the sensors with the sensor’s TAN.')
        return _('Needs the pH and the temperature of the same sample.')

    @staticmethod
    def _ph_scale_said(observation):
        """What an NH₃ worked out from a pH measured on another scale than NBS says beside it (the audit of 2026-11-19,
        F11: judged on the NBS scale, the safe side): a typed sample's or a sensor's; '' for an NBS pH."""
        if observation.sample is not None and observation.sample.ph_scale:
            return messages.judged_on_nbs(observation.sample.ph_scale)
        if observation.ph is not None and observation.ph.converted:
            return messages.judged_on_nbs(observation.ph.scale)
        return ''

    def _ammonia(self, observation, salinity, salinity_until, temperature):
        """{code: Reading} of the NH₃-N and the NH₄-N worked out from an observation's TAN and pH, its temperature
        (`temperature_of`, THE rule of a sample's temperature) and `salinity` (`salinity_found`). Every input the
        derivation uses is read HERE, once, and recorded as used with the moment it stops being fresh
        (`Reading.inputs_until`; the review of 2026-11-26, F2): the derivation gets the values from this record and
        nothing else, so an input it reads is an input it records, and `Reading.fresh_until` refuses a record that
        differs from the inputs the parameter declares. None for an input with no measured value. A pH a sensor gave
        on another scale ends no later than the temperature it was put on the NBS scale with (`SensorPh`, L4)."""
        ph = observation.get(parameters.PH)
        used = {TAN: (observation.get(TAN), observation.until(TAN)),
                parameters.PH: (ph, self._ph_until(observation) if ph is not None else None),
                parameters.TEMPERATURE: (temperature.value, temperature.until),
                parameters.SALINITY: (salinity, salinity_until)}
        found = self._ammonia_of(observation, {code: value for code, (value, _end) in used.items()})
        ends = {code: end if value is not None else None for code, (value, end) in used.items()}
        for reading in found.values():
            reading.inputs_until = dict(ends)
        return found

    @staticmethod
    def _ph_until(observation):
        """When an observation's pH stops being fresh: its own end, and no later than the temperature a sensor's pH was
        put on the NBS scale with (`SensorPh.temperature_until`)."""
        ends = [observation.until(parameters.PH)]
        if observation.ph is not None and observation.ph.temperature_until is not None:
            ends.append(observation.ph.temperature_until)
        return min(ends)

    @staticmethod
    def temperature_of(observation):
        """The temperature an NH₃ is worked out with: the observation's own (a sample's typed one; a sensor TAN's, the
        fresh sensor temperature it was combined with), ending as that value does (`Observation.until`). Never another
        sample's (the oxygen's stored basis is the oxygen's alone, `_oxygen_temperature`). A sample without one gives no
        NH₃, and says so."""
        own = observation.get(parameters.TEMPERATURE)
        return SampleTemperature(own, observation.until(parameters.TEMPERATURE) if own is not None else None)

    # -- a point's worked-out values: the shell of the judge (farm/water/judge.py) --
    def worked_at(self, point):
        """What the shell fetched of a point's worked-out values (a Worked). Batched (`prefetch_newest_worked`)."""
        if point.pk not in self._newest:
            self.prefetch_newest_worked([point])
        return self._newest[point.pk]

    def records(self, point, code, now=None, status_of=None, live=(), more=()):
        """[Record] of `code` at `point`: every sample the shell fetched there (`worked_at`), the `live` worked-out
        readings that belong to the point (a TAN analyser bound there: evidence as a sample is) and `more` readings of
        samples of the point the caller holds (the entered ones, a history page's), each through THE one builder
        (`record_of`), a sample once."""
        worked = self.worked_at(point)
        readings = {id(found[code].sample.sample): found[code]
                    for _sample, found in (*worked.found, *worked.lacking, *worked.late) if found.get(code) is not None}
        for reading in more:
            readings.setdefault(id(reading.sample.sample), reading)
        return [record_of(reading, now, status_of(reading) if status_of else None)
                for reading in (*readings.values(), *live)]

    def verdict(self, point, code, now=None, status_of=None, live=(), more=()):
        """The judge's PointVerdict of `code` at `point` (judge.point_verdict), complete unless the look-back stopped at
        the ceiling."""
        return judge.point_verdict(self.records(point, code, now, status_of, live, more),
                                   complete=self.worked_at(point).complete)

    def readings_of(self, point, reading):
        """{code: Reading} of the stored sample at `point` a worked-out `reading` (a Record's key) is of."""
        worked = self.worked_at(point)
        return next((found for _sample, found in (*worked.found, *worked.lacking, *worked.late)
                     if any(each is reading for each in found.values())), {})

    def _window(self, point_ids):
        """The samples with a TAN of the points in the read's window (up to its moment for a read of the past)."""
        rows = WaterMeasurement.objects.filter(HAS_TAN, point__in=point_ids, measured_at__gte=self.since)
        return rows.filter(measured_at__lte=self.until) if self.until is not None else rows

    @staticmethod
    def _ranked(rows, offset, size):
        """`rows` ranked per point in ORDER, those ranked offset+1 to offset+size: bounded in the database."""
        rows = (rows.annotate(rank=Window(RowNumber(), partition_by=[F('point_id')], order_by=list(ORDER)))
                .filter(rank__gt=offset, rank__lte=offset + size).select_related(*POINT_RELATED))
        return sorted(rows, key=lambda sample: (str(sample.point_id), sample.rank))

    def _fetch(self, rows):
        """The one door of the look-back's rows (a test counts them here)."""
        return list(rows)

    def _derived(self, sample):
        """(sample, {code: Reading} of its worked-out codes), the sample's own object kept: a sample is one object in a
        Context (`_samples`), so a sample met twice is one record."""
        sample = self._samples.setdefault(sample.pk, sample)
        return sample, {code: found for code, found in self.readings(sample).items() if code in DERIVED}

    def prefetch_newest_worked(self, points, late=True):
        """`worked_at` for many points at once, bounded in rows and statements:
        - the CANDIDATES (CAN_GIVE: only they can give a value), newest first in ORDER, in rounds of two, four, eight … a
          point (a window function), one query each, until the judge says a point is settled (`judge.settled`: its
          evidence value and a candidate of an older minute, or none left) or past its ceiling (`judge.over_ceiling`:
          judge.CEILING candidates and no evidence; the point is then not `complete`, and the judge never takes what was
          fetched for the whole). A sample that cannot give a value never costs a call of the chemistry core;
        - ONE query for every point's newest sample that cannot give a value (what is said of it);
        - with `late`, ONE query for the late results of every point with evidence (`_late_results`)."""
        points = [point for point in points if point.pk not in self._newest]
        if not points:
            return
        for point in points:
            self._newest[point.pk] = Worked()
        ids = [point.pk for point in points]
        candidates = self._window(ids).filter(CAN_GIVE)
        pending, offset, size = ids, 0, 2
        while pending:
            rows = self._fetch(self._ranked(candidates.filter(point__in=pending), offset, size))
            by_point = defaultdict(list)
            for sample in rows:
                by_point[sample.point_id].append(sample)
            still = []
            for pk in pending:
                got = by_point.get(pk, [])
                worked = self._newest[pk]
                worked.found += [self._derived(sample) for sample in got]
                records = [record_of(found[NH3_N.code]) for _sample, found in worked.found if NH3_N.code in found]
                if judge.settled(records, exhausted=len(got) < size):
                    continue
                if judge.over_ceiling(records, judge.CEILING):
                    worked.complete = False
                    continue
                still.append(pk)
            # Rounds double (2, 4, … 256) and the one that reaches judge.CEILING is cut to it, so a point without
            # evidence stops at EXACTLY CEILING candidates (512, not the next doubling's 1022: review 8, N4). A point
            # past it WITH evidence (only peers of its minute so far) keeps doubling until it is settled.
            offset += size
            size = min(size * 2, judge.CEILING - offset) if offset < judge.CEILING else size * 2
            pending = still
        for sample in self._fetch(self._ranked(self._window(ids).filter(CANNOT_GIVE), 0, 1)):
            self._newest[sample.point_id].lacking.append(self._derived(sample))
        if late:
            self._late_results(points)

    def _late_results(self, points):
        """The owner's decision on review 5: a worked-out value measured before the minute of a point's stored evidence but
        entered after it is a late result (the judge says it: `PointVerdict.late`): never a candidate, never an alarm,
        said on the point (`latest`). ONE query for every point with evidence: the newest LATE_READ a point, never a
        sample already fetched, and how many there are in all (`Worked.late_more`: what the read did not judge is counted
        and said, never cut silently; review 7, M1)."""
        condition, fetched = Q(), []
        for point in points:
            evidence = self.verdict(point, NH3_N.code).superseded_by
            if evidence is not None:
                condition |= Q(point_id=point.pk, measured_at__lt=judge.minute(evidence.measured_at),
                               created_at__gt=evidence.created_at)
                fetched += [sample.pk for sample, _found in self._newest[point.pk].found]
        if not condition:
            return
        rows = (self._window([point.pk for point in points]).filter(condition, CAN_GIVE).exclude(pk__in=fetched)
                .annotate(total=Window(Count('pk'), partition_by=[F('point_id')])))
        for sample in self._fetch(self._ranked(rows, 0, LATE_READ)):
            worked = self._newest[sample.point_id]
            worked.late.append(self._derived(sample))
            worked.late_more = max(sample.total - LATE_READ, 0)

    def _ammonia_of(self, observation, used):
        """The readings of `_ammonia`, from the values it recorded as used (`used`, {code: value}) and nothing else of
        the water's (the ionic-strength inputs, `parameters.AMMONIA_UNCOUNTED`, only move the best estimate)."""
        tan, ph, temperature, salinity = (used[code] for code in (TAN, parameters.PH, parameters.TEMPERATURE,
                                                                  parameters.SALINITY))
        if ph is None and observation.ph is not None and observation.ph.refused:
            # The sensor's pH could not be put on the NBS scale: the NH₃ is not known, and where the fish have an NH₃
            # limit it cannot be evaluated (the reason said), never worked out from the unconverted number.
            return {NH3_N.code: Reading(NH3_N, None, observation, True, str(messages.nh3_ph_not_converted(
                observation.ph.refused)), refused=observation.ph.refused)}
        if not gives_value(used.get):               # THE one definition of what its own sample must hold (OWN_INPUTS)
            return {NH3_N.code: Reading(NH3_N, None, observation, True, self._same_source_missing(observation))}
        if salinity is None:
            return {NH3_N.code: Reading(NH3_N, None, observation, True, self._salinity_missing())}
        inputs = self.ionic_inputs_for(observation)
        try:
            equilibria = chemistry.water_equilibria(float(temperature), float(salinity), **inputs)
        except (ValueError, ArithmeticError) as error:      # what the gate catches (deffeyes.unworkable): e.g. a
            # conductivity beyond the fresh path's range (Davies, I > 0.5), a division by zero, an overflow
            return {NH3_N.code: self._ammonia_on_basis(observation, error, tan, ph, temperature, salinity,
                                                       inputs.get('water_origin') or '')}
        # The judged share: the larger of the safe side (formula 4's Rule S) and the best estimate (cross review F1);
        # the best estimate's NH3-N is said beside it, never judged.
        share = Decimal(equilibria.nh3_share(float(ph)))
        # Judged unrounded, shown at four decimals (`Reading.exact`; the audit of 2026-11-19, F3).
        exact = tan * share
        nh3 = exact.quantize(NH3_N.step)
        corrected = (tan * Decimal(equilibria.nh3_share_corrected(float(ph)))).quantize(NH3_N.step)
        said = ' '.join(filter(None, (str(messages.provenance(equilibria)),
                                      messages.judged('nh3', equilibria.nh3_basis, corrected, equilibria),
                                      self._ph_scale_said(observation))))
        return {NH3_N.code: Reading(NH3_N, nh3, observation, True, provenance=said, exact=exact),
                NH4_N.code: Reading(NH4_N, (tan - exact).quantize(NH4_N.step), observation, True, provenance=said,
                                    exact=tan - exact)}

    @staticmethod
    def nh3_basis_share(temperature, salinity, ph, water_origin):
        """The NH₃ share on the safe-side basis alone, or None when the core cannot give it either. The basis is a
        function of the temperature, the salinity and the water's origin only (chemcore/core/src/formula4.rs
        `limits_basis`: the ideal water, the sea path's best estimate at the pH + 0.03, or their blend by the salinity), never of the
        conductivity, the alkalinity or the hardness, so it is worked out without them (farm/tests/test_core_refusal.py
        holds it equal to the basis of the same water with them, wherever the core works that water out)."""
        try:
            return Decimal(chemistry.water_equilibria(float(temperature), float(salinity), water_origin=water_origin)
                           .nh3_share_limits(float(ph)))
        except (ValueError, ArithmeticError):
            return None

    def _ammonia_on_basis(self, observation, error, tan, ph, temperature, salinity, water_origin):
        """The NH₃ of a TAN sample whose water the core refuses to work out (`error`, its reason: e.g. a conductivity past
        the Davies range). The judged NH₃ is the larger of the safe-side basis and the best estimate (cross
        review F1), so it is never below the basis, which needs no conductivity (`nh3_basis_share`): the reading is the
        basis's NH₃-N, at least the judged value, judged by the limits as any value is (Context.judge: past a limit it
        is that, critical past the critical one; else it cannot be evaluated) and it keeps the refusal (`refused`), so the
        unit says beside it that the corrected value cannot be worked out (the re-check of 2026-11-18, RC-3: a water
        known to be past the critical limit on its basis was alarmed a warning). Without a basis either: no value,
        refused."""
        share = self.nh3_basis_share(temperature, salinity, ph, water_origin)
        if share is None:
            return Reading(NH3_N, None, observation, True, messages.refused(error), refused=str(error))
        return Reading(NH3_N, (tan * share).quantize(NH3_N.step), observation, True,
                       f'{messages.refused(error)} {messages.ON_BASIS}', measured=str(messages.BASIS_ONLY),
                       refused=str(error), exact=tan * share)

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
        # What the value was worked out from, said beside it (owner, 2026-11-07): the temperature, salinity and pressure.
        note = _('Worked out from %(temperature)s °C, %(salinity)s ‰ and %(pressure)s atm.') % {
            'temperature': number_format(temperature, 1), 'salinity': number_format(salinity, 1),
            'pressure': number_format(pressure, 3)}
        if altitude is None:
            note = f'{note} {_("At sea-level pressure: the site has no altitude.")}'
        note = ' '.join([note, *self._basis_said(observation)])
        said = _('Formula %(formula)d.') % {'formula': chemistry.FORMULA_VERSION}
        # Judged unrounded, shown at the parameter's decimals (`Reading.exact`; the audit of 2026-11-19, F3).
        if missing == OXYGEN_PCT:
            exact = 100 * mg_l / solubility
            return {OXYGEN_PCT: Reading(parameters.get(OXYGEN_PCT), exact.quantize(parameters.get(OXYGEN_PCT).step),
                                        observation, True, note, provenance=said, exact=exact)}
        if missing == OXYGEN_MG_L:
            exact = percent * solubility / 100
            return {OXYGEN_MG_L: Reading(parameters.get(OXYGEN_MG_L), exact.quantize(parameters.get(OXYGEN_MG_L).step),
                                         observation, True, note, provenance=said, exact=exact)}
        expected = percent * solubility / 100
        if expected and abs(mg_l - expected) / expected > OXYGEN_TOLERANCE:
            note = _('The mg/L and the % disagree by more than 10 % at this temperature and salinity: check the '
                     'meter’s settings.')
            return {code: Reading(parameters.get(code), observation.get(code), observation, False, note)
                    for code in (OXYGEN_MG_L, OXYGEN_PCT)}
        return {}

    # -- judging --
    def judge(self, reading, day, now=None, temperature=None, for_point=None):
        """Sets the reading's judgement, its limit rows and the species no row judges it for (`uncovered`), for the fish
        of `day`, and its status: the judgement, or stale when `now` is given and the value is no longer fresh
        (Reading.fresh); the judgement stays. The dissolved oxygen is one quantity (owner, 2026-11-07): for the fish
        with no row in the reading's own unit but one in the other (mg/L or %), the value is worked out in the other
        unit (`_in_other_unit`) and judged by that row; where it cannot be, those fish stay uncovered ("no limit").
        `for_point`: the point whose water the value stands for (a loop's value standing in for a unit is judged for the
        unit's fish), else the point it was measured at."""
        if reading.code not in LIMITED or reading.value is None:
            reading.status = reading.judged = Status.NOT_MEASURED if reading.value is None else Status.NO_LIMIT
            if reading.refused and reading.code in LIMITED:
                # The core refused to work it out, its basis too: where a limit row would judge it, it cannot be
                # evaluated (V-A), fresh or old (the last word there is about the water); with no fish or no row
                # nothing is judged.
                rows = []
                exposures = self.exposures(for_point or reading.sample.point, day)
                for species_id, water_type in exposures:
                    row = self.limits.applying(species_id, reading.code, water_type)
                    if row is not None and row not in rows:
                        rows.append(row)
                # The fish no row judges it for: a limit removed ends its "cannot be evaluated" warning with that
                # cause (alarms/sources.py `_unjudged`), as it ends a judged value's levels.
                reading.uncovered = self.limits.uncovered(reading.code, exposures)
                if rows:
                    reading.limits, reading.status, reading.judged = rows, Status.UNEVALUATED, Status.UNEVALUATED
                    if now is not None and not reading.fresh(now):
                        reading.status = Status.STALE
            return reading
        exposures = self.exposures(for_point or reading.sample.point, day)
        reading.judged, reading.limits = self.limits.assess(reading.code, reading.judged_value, exposures)
        reading.uncovered = self.limits.uncovered(reading.code, exposures)
        other = parameters.SAME_QUANTITY.get(reading.code)
        through = [(species_id, water_type) for species_id, water_type in exposures
                   if species_id in reading.uncovered and self.limits.applying(species_id, other, water_type)] \
            if other else []
        converted = self._in_other_unit(reading, temperature) if through else None
        if converted is not None:
            status, rows = self.limits.assess(other, converted.judged_value, through)
            converted.limits, converted.judged = rows, status
            reading.through = converted
            reading.judged = status if reading.judged == Status.NO_LIMIT else worst([reading.judged, status])
            judged_for = {species_id for species_id, _water_type in through}
            reading.uncovered = tuple(each for each in reading.uncovered if each not in judged_for)
            if converted.derived:               # said only where a conversion was made, not the sample's own value
                said = self._judged_through(converted)
                reading.note = f'{reading.note} {said}' if reading.note else said
        if reading.refused and reading.limits and reading.judged not in ALERTS:
            # Refused, its value the limits' basis alone (`_ammonia_on_basis`): the judged value is never below it, so
            # past a limit it is that limit's status (critical past the critical one, the re-check's RC-3); inside
            # them what it is for the fish is not known: it cannot be evaluated, never OK.
            reading.judged = Status.UNEVALUATED
        reading.status = reading.judged
        if reading.judged == Status.NO_LIMIT:
            reading.why_no_limit = self._why_no_limit(exposures)
        if now is not None and not reading.fresh(now):
            reading.status = Status.STALE
            self._say_ended(reading)
        return reading

    @staticmethod
    def _say_ended(reading):
        """A worked-out value no longer fresh because an input ended before its own row's hours says which (review 4 of
        the branch, M5): "Stale since 26.11.2026 10:12: its temperature ended." Nothing for a measured value or one stale
        by its own hours."""
        if not reading.parameter.inputs or not reading.inputs_until:
            return
        ends = {code: end for code, end in reading.inputs_until.items() if end is not None}
        if not ends:
            return
        code = min(ends, key=ends.get)
        if ends[code] >= freshness.fresh_until(reading.code, reading.at):
            return
        said = str(messages.ended_by(code, ends[code], reading.point))
        if said not in reading.note:
            reading.note = f'{reading.note} {said}' if reading.note else said

    def _in_other_unit(self, reading, temperature):
        """An oxygen value in its other unit (mg/L <-> %): the other value of its own observation when that has one,
        else worked out as a sample's is (`_oxygen`: the solubility at the temperature, the salinity and the site's
        pressure) with the observation's own temperature or the point's fresh `temperature` (a Reading); None when it
        cannot be worked out. Never a second formula. The point's `temperature` is taken only when it is fresh AT the
        value's own time (`fresh_at`): a stale value is never converted with today's temperature (PLAN A9.3, P8).
        Returns the Reading in the other unit (its note says what it was worked out from), or None."""
        other = parameters.SAME_QUANTITY[reading.code]
        observation = reading.sample
        if observation.get(other) is not None:
            return Reading(parameters.get(other), observation.get(other), observation)
        if self._oxygen_temperature(observation) is None:
            if temperature is None or temperature.value is None or not fresh_at(temperature, reading.at):
                return None
            alone = replace(temperature.sample, measured={parameters.TEMPERATURE: temperature.value})
            observation = Observation.combined([replace(observation, measured={reading.code: reading.value}), alone])
        worked = self._oxygen(observation, self._oxygen_temperature(observation), self.salinity_for(observation))
        found = worked.get(other)
        return found if found is not None and found.value is not None and found.derived else None

    @staticmethod
    def _basis_said(observation):
        """[sentence] of where a sample's oxygen basis came from: the temperature and the salinity not its own."""
        said = []
        temperature = observation.basis.get(parameters.TEMPERATURE)
        if temperature is not None and observation.get(parameters.TEMPERATURE) is None:
            said.append(_('The temperature is %(source)s.') % {'source': temperature.said(observation.point)})
        salinity = observation.basis.get(parameters.SALINITY)
        if salinity is not None and observation.get(parameters.SALINITY) is None:
            said.append(_('The salinity is fresh water’s.') if salinity.source == BasisSource.FRESH_WATER else
                        _('The salinity is %(source)s.') % {'source': salinity.said(observation.point)})
        return said

    @staticmethod
    def _judged_through(converted):
        """What a value judged through its other unit says: the value it was judged as, what that was worked out from and
        the limits that judged it (second cross review, finding 5). The value is judged unrounded, so past a limit it is
        said with the decimals that show the side it is on (`said_value`), as the card's reason says it."""
        from farm.templatetags.water import limit_text      # the one way a limit is said; it imports this module
        unit = 'mg/L' if converted.code == OXYGEN_MG_L else '%'
        said = _('Judged as %(value)s %(unit)s.') % {'value': said_value(converted), 'unit': unit}
        parts = [said, str(converted.note or '')]
        if converted.limits:
            parts.append(_('Limit: %(limits)s.') % {'limits': '; '.join(str(limit_text(row))
                                                                          for row in converted.limits)})
        return ' '.join(part for part in parts if part)


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
                                                           order_by=ORDER_BY),
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
    # The worked-out codes are the judge's (farm/water/judge.py): the readings of the sample its verdict SHOWS at the point
    # (the shell picks nothing), and every value it judges there, the place's candidates (`Manual.worked`).
    for code in DERIVED:
        found.pop(code, None)
    verdicts = {code: context.verdict(point, code) for code in DERIVED}
    shown = verdicts[NH3_N.code].shown
    if shown is not None:
        found.update(context.readings_of(point, shown.key))
    return Manual(found, {code: [record.key for record in verdicts[code].judged] for code in DERIVED})


def _live(targets, answer):
    """{code: [Observation]} of the live values of `targets` ([(target, origin, the point it is observed at)]), in the
    order they are given and, per target, primary first."""
    found = defaultdict(list)
    for target, origin, point in targets:
        for code, values in answer.values.get(target, {}).items():
            if code in parameters.COLUMNS:
                found[code].extend(Observation.of_sensor(point, value, origin) for value in sources.ordered(values))
    return found


def newest(found):
    """The newest of `found` (anything with `at`), the first of them at the same time: given in the order they count
    (sources.ordered: the primary channel first; a sensor before a sample), a tie goes to the first."""
    best = None
    for each in found:
        if best is None or each.at > best.at:
            best = each
    return best


def fresh_at(reading, moment):
    """Whether a reading can stand for the water at `moment` in a calculation (PLAN A9.3): measured at or before it (or
    within the clock tolerance after it, freshness.tolerance: one moment for two clocks) and still fresh then."""
    return reading.at <= moment + freshness.tolerance() and reading.fresh(moment)


def newest_shown(found, now):
    """The newest of `found` when none is fresh, shown stale: one stamped further ahead of `now` than the clock's skew
    (evaluate.ahead) only when there is nothing else, so a device whose clock runs fast never hides the others; the first
    at one time; None for none."""
    return max(found, key=lambda each: (not ahead(each.at, now), each.at), default=None)


def choose(tiers, now, fresh):
    """Owner rule A9, the ONE place it is decided, for the latest values (`latest`), a value at a moment (`Series`) and
    the ration's temperature (farm/feeding/temperature.py). `tiers`: the candidates (anything with `at`) of the unit's own
    places, then of its system's (then, for the ration, of the systems that one is nested in), each in the order a tie at
    one measurement time goes (a sensor before a sample, the primary channel before the backup); `fresh(candidate)`
    whether it is fresh at `now`. The newest fresh candidate of the first tier that has one; else the newest of the first
    tier that has any, shown stale (`newest_shown`); None when there is none."""
    tiers = [list(tier) for tier in tiers]
    for tier in tiers:
        found = newest(each for each in tier if fresh(each))
        if found is not None:
            return found
    for tier in tiers:
        found = newest_shown(tier, now)
        if found is not None:
            return found
    return None


def _fresh_live(live, now):
    """{code: the newest fresh Observation} of live values (`newest`: the primary first at the same time)."""
    return {code: newest(each for each in observations if is_fresh(parameters.get(code), each.at, now, each.fresh_for))
            for code, observations in live.items()}


def _candidates(code, live, fresh_live, manuals, context):
    """[Reading] of `code` in one tier, in the order a tie goes: its sensors' values (`live`), the value worked out from
    the tier's fresh sensor values (the other oxygen unit: only from fresh ones), and its points' latest samples
    (`manuals`, one {code: Reading} per point)."""
    found = [reading_of(code, each) for each in live.get(code, [])]
    other = parameters.SAME_QUANTITY.get(code)
    if other and fresh_live.get(other) is not None and fresh_live.get(parameters.TEMPERATURE) is not None:
        worked = context.readings(Observation.combined([fresh_live[other], fresh_live[parameters.TEMPERATURE],
                                                        *([fresh_live[parameters.SALINITY]]
                                                          if fresh_live.get(parameters.SALINITY) else [])]))
        if worked.get(code) is not None and worked[code].value is not None:
            found.append(worked[code])
    found += [manual[code] for manual in manuals if manual.get(code) is not None]
    return found


def _resolve(own_live, own_manual, system_live, system_manual, context, now, at_moment=None, worked=None):
    """{code: Reading} of one place's water, each parameter on its own, by owner rule A9 (`choose`): the newest of its OWN
    fresh values (`own_live`, its points' sensors, and `own_manual`, its points' latest samples, whatever the origin);
    only when it has none, the newest fresh value of its system (`system_live`, the system's sensors and those on its loop
    point, and `system_manual`, the loop's samples); else the newest of its own values, stale, else the system's, stale
    (shown with its age, never used as fresh). A worked-out value (NH3, NH4) the same way among every point's newest
    worked-out value and the one worked out from a tier's fresh live TAN (review 4 of the branch). Returns (chosen, {code: every candidate of both
    tiers, fresh, stale or ahead of the clock, derived ones too}): what the worst fresh value and the point's own status
    read. `at_moment(moment)` gives the place's sensor values fresh at a past moment (`_at_moment`), what a sensor pH no
    longer fresh is put on the NBS scale with."""
    fresh_own, fresh_system = _fresh_live(own_live, now), _fresh_live(system_live, now)
    fresh_live = {code: fresh_own.get(code) or fresh_system.get(code) for code in {*own_live, *system_live}}
    if any(each.ph is not None for live in (own_live, system_live) for each in live.get(parameters.PH, [])):
        # A sensor pH on another scale than NBS, put on it with the place's fresh temperature and salinity (F1), before
        # anything reads it: the pH shown and judged, and the pH a sensor's TAN is worked out with. Without a fresh
        # sensor temperature, the place's temperature chosen as every value is (A9), where fresh at the pH's time (C2).
        # One no longer fresh, with the place's sensor values of its own moment (owner decision of 2026-11-20).
        temperature = choose([_candidates(parameters.TEMPERATURE, own_live, fresh_own, own_manual, context),
                              _candidates(parameters.TEMPERATURE, system_live, fresh_system, system_manual, context)],
                             now, lambda reading: reading.fresh(now))
        own_live, system_live = ({**live, parameters.PH: [context.sensor_ph(each, fresh_live, now, temperature, at_moment)
                                                          for each in live.get(parameters.PH, [])]}
                                 for live in (own_live, system_live))
        fresh_own, fresh_system = _fresh_live(own_live, now), _fresh_live(system_live, now)
        fresh_live = {code: fresh_own.get(code) or fresh_system.get(code) for code in {*own_live, *system_live}}
    chosen, candidates = {}, {}
    for code in parameters.COLUMNS:
        tiers = [_candidates(code, own_live, fresh_own, own_manual, context),
                 _candidates(code, system_live, fresh_system, system_manual, context)]
        found = choose(tiers, now, lambda reading: reading.fresh(now))
        if found is not None:
            chosen[code] = found
            candidates[code] = [each for tier in tiers for each in tier]
    # The worked-out values (review 4 of the branch, H1, H2): in each tier, every point's NEWEST WORKED-OUT value (its
    # manual readings, `_manual`) and the value worked out from the tier's fresh live TAN. Chosen by A9 as every value
    # is; every worked-out candidate of both tiers takes part in the worst fresh value (third cross review, N1/N2).
    live_worked = {}
    for tier, fresh_tier in enumerate((fresh_own, fresh_system) if worked is None else ()):
        if fresh_tier.get(TAN) is not None:
            together = Observation.combined([fresh_tier[TAN], *(fresh_live[code] for code in (
                parameters.PH, parameters.TEMPERATURE, parameters.SALINITY) if fresh_live.get(code) is not None)])
            live_worked[tier] = context._ammonia(together, *context.salinity_found(together),
                                                 context.temperature_of(together))
    if worked is not None:
        # A unit's own-water point read on its own (an outlet's page): its live worked-out values are the ones its
        # unit's standing place works out and files at it (`_standing_worked`; the coordinator's decision on review 11,
        # N5: one rule for the unit's page, the point's page, the log and the history).
        live_worked = {0: worked}
    for code in DERIVED:
        tiers = [[*(found[code] for found in [live_worked.get(tier, {})] if found.get(code) is not None),
                  *(each for manual in manuals for each in manual.worked[code])]
                 for tier, manuals in enumerate((own_manual, system_manual))]
        tiers = [[each for each in tier if each.value is not None] for tier in tiers]
        found = choose(tiers, now, lambda reading: reading.fresh(now))
        if found is not None:
            chosen[code] = found
            candidates[code] = [each for tier in tiers for each in tier]
    tan = chosen.get(TAN)
    if NH3_N.code not in chosen and tan is not None:
        # Nothing worked out in any tier: the TAN shown says why.
        if tan.sample.live and tan.fresh(now):
            # The live NH₃ already worked out from that TAN's tier (`live_worked`, once: review 5, L2).
            if worked is not None:
                # Its unit's place works out the TAN of another of its points, the newest (A9): said, never silent.
                chosen[NH3_N.code] = Reading(NH3_N, None, tan.sample, True, str(messages.WORKED_AT_UNIT),
                                             inputs_until={**dict.fromkeys(NH3_N.inputs), TAN: tan.fresh_until})
            else:
                chosen.update(next((live_worked[tier] for tier, fresh_tier in enumerate((fresh_own, fresh_system))
                                    if tier in live_worked and fresh_tier.get(TAN) is tan.sample), {}))
        elif tan.sample.live:
            # Its one input used, the TAN, ended (`inputs_until`, the others none).
            chosen[NH3_N.code] = Reading(NH3_N, None, tan.sample, True, _('Not worked out: the TAN is no longer fresh.'),
                                         inputs_until={**dict.fromkeys(NH3_N.inputs), TAN: tan.fresh_until})
        else:
            # A sample's: the judge names the value-less record the place shows (judge.shown_without_value), which says
            # why it has no value.
            shown = judge.shown_without_value([[record_of(manual[NH3_N.code]) for manual in manuals
                                                if manual.get(NH3_N.code) is not None]
                                               for manuals in (own_manual, system_manual)])
            if shown is not None:
                chosen[NH3_N.code] = shown.key
    return chosen, candidates


@dataclass
class Places:
    """Where one point's water is read from (owner rule A9): its own points, then its system's, and the live targets on
    each ([(target, origin, the point a value of it is observed at)]). A unit's middle point stands for the unit: its own
    points are every active point measuring its own water (A9.1, OWN_WATER_KINDS: never an inlet), the middle first;
    its system's are the
    loop point of the unit's system with the sensors on it and on the system. Any other point is its own alone, with no
    system tier (a loop's middle point has the system's sensors as its own)."""
    own: list
    own_targets: list
    system: list = field(default_factory=list)
    system_targets: list = field(default_factory=list)
    for_unit: bool = False          # the point stands for its unit: its middle, or its anchor without one (`anchors`)


def _observed(point, origin=None):
    """The live targets of a point's own values, observed at the point (sensor_targets); `origin` names them all (a loop
    point's probe in a unit's system tier is a system sensor)."""
    return [(target, origin or each, point) for target, each in sensor_targets(point)]


def _own_water_order(point):
    """The order a unit's own-water points count in: the middle first, then the others by kind and name."""
    return point.kind != PointKind.MIDDLE, list(PointKind.values).index(point.kind), point.name


def own_water(unit_ids):
    """{unit id: [SamplingPoint]}: the units' active points of their own water (the middle point and OWN_WATER_KINDS: never
    an inlet), in the order they count (`_own_water_order`: the middle first). One query; every unit asked is in it.
    What `anchors` and a point's `Places` are worked out from: a reader that has it hands it on (`latest(own=...)`), so
    one request reads it once."""
    found = {unit_id: [] for unit_id in unit_ids}
    if found:
        for point in sorted(SamplingPoint.objects.filter(unit__in=list(found), is_active=True)
                            .filter(Q(kind=PointKind.MIDDLE) | Q(kind__in=OWN_WATER_KINDS)).with_owners(),
                            key=_own_water_order):
            found[point.unit_id].append(point)
    return found


def anchors(units, own=None):
    """{unit id: the point that stands for the unit's water}: its active middle point (`middle_points`), else, for a unit
    without one, its first active own-water point (OWN_WATER_KINDS: never an inlet), so its outlets and its system still
    give it a status (coordinator, third cross review B5). A unit without either is not in the result. One query, none
    when the caller hands in the units' `own_water`."""
    units = list(units)
    own = own_water([unit.pk for unit in units]) if own is None else own
    return {unit.pk: own[unit.pk][0] for unit in units if own.get(unit.pk)}


def _places(points, own=None, units=()):
    """{point id: Places} of the points given: one query for the other points of their units (none when the caller hands
    in their `own_water`), one for their loops. A point stands for its unit (`for_unit`) when it is the unit's middle
    point, or, for a unit without one, the unit's anchor (`anchors`): it then reads the unit's tiers (`tiers`, the one
    resolver of owner rule A9), its own-water points and its system's."""
    unit_ids = {point.unit_id for point in points if point.unit_id}
    if own is None or not unit_ids <= set(own):         # a unit the caller did not read: read them all here
        own = own_water(unit_ids)
    standing = {unit_id: own[unit_id][0].pk for unit_id in unit_ids if own[unit_id]}
    unit_points = [point for point in points if point.unit_id and standing.get(point.unit_id) == point.pk]
    unit_tiers = tiers([point.unit for point in unit_points], nested=False, own=own, sites=False) if unit_points else {}
    found = {}
    for point in points:
        if point not in unit_points:
            found[point.pk] = Places([point], _observed(point))
            continue
        found[point.pk] = _places_of_tiers(unit_tiers[point.unit_id], point)
    # A unit with no point of its own (`units`): nothing of its own, its system's tier as a unit point's (A9), keyed by
    # the unit, the system's sensors observed at the unit where the system has no loop point.
    units = list(units)
    if units:
        bare_tiers = tiers(units, nested=False, own={unit.pk: [] for unit in units}, sites=False)
        for unit in units:
            found[unit.pk] = _places_of_tiers(bare_tiers[unit.pk], unit)
    return found


def _places_of_tiers(unit_tiers, standing):
    """A unit's Places from its tiers (`tiers`): its own points and their targets, then its system's tier: the loop point
    with the sensors on it and on the system (observed as system sensors), or the system's own sensors observed at
    `standing` (the unit's point, or the unit itself) when it has no loop point."""
    places = Places([], [], for_unit=True)
    for tier in unit_tiers:
        if tier.via == UNIT:
            places.own = list(tier.points)
            places.own_targets = [target for each in tier.points for target in _observed(each)]
        elif tier.points:
            places.system = [tier.points[0]]
            places.system_targets = _observed(tier.points[0], Origin.SYSTEM_SENSOR)
            break
        else:
            places.system_targets = [((sources.SYSTEM, tier.owner.pk), Origin.SYSTEM_SENSOR, standing)]
            break
    return places


def latest(points, now=None, at=None, own=None, units=()):
    """{point id: PointWater} of every sampling point given: per parameter, its value in the owner's order (`_resolve`,
    from the point's `Places`), judged for the fish of the point's own water that day (a value standing in from the
    system is judged for the unit's fish, as the unit's own value would be); values no longer fresh are stale. One query
    for the samples, one ask of the live sources for every point. With `at` (a past moment, owner amendment A4), the
    water as it was then: the samples taken up to that moment, each sensor's value at it (sources.value_at: the channels
    bound there then), fresh and judged relative to it; nothing from after it. `own`: the `own_water` of the points'
    units when the caller has read it (not read again).

    `units`: units with no point of their own to read their water at (`unanchored`), each read in the same pass, keyed by
    its own id: its system's tier (A9: the loop point's samples and probes, or the system's probes) judged for its own
    fish as a unit point's system tier is, each value saying it is its system's (`messages.from_system`); with no
    system, nothing (its oxygen then has no fresh value: critical where it holds fish, `_silence`; review 4 of the
    branch, L1: one water read, the card, the pages and the alarms read it there)."""
    moment = at or now or timezone.now()
    since = moment - WINDOW
    points = list(points)
    # (their clocks and systems with them, whatever the caller read: one query for all of them)
    units = list(Tank.objects.filter(pk__in=[unit.pk for unit in units])
                 .select_related('production_department__site', 'system')) if units else []
    places, standing, everything = reading_places(points, own, units)
    ids = _newest_ids(everything, since, until=at)
    samples = WaterMeasurement.objects.select_related(*POINT_RELATED).in_bulk(
        {sample_id for slots in ids.values() for sample_id in slots.values()})
    context = Context(everything, since, units)
    # Every point's worked-out values, looked back at in batches for the judge (Context.prefetch_newest_worked).
    context.until = at
    context.prefetch_newest_worked(everything)
    wanted = [target for each in places.values()
              for target, _origin, _point in (*each.own_targets, *each.system_targets)]
    answer = sources.latest(wanted, moment) if at is None else _values_at(wanted, at)
    manuals = {}

    def manual(point):
        if point.pk not in manuals:
            manuals[point.pk] = _manual(point, ids, samples, context)
        return manuals[point.pk]

    stood = {}

    def worked_here(point):
        """A unit's own-water point read on its own: the live worked-out values its unit's standing place files at it,
        worked out once a standing place (`_standing_worked`); None for any other point."""
        anchor = standing.get(point.pk)
        if anchor is None:
            return None
        if anchor.pk not in stood:
            stood[anchor.pk] = _standing_worked(places[anchor.pk], answer, context, moment)
        return stood[anchor.pk].get(point.pk, {})

    water = {}
    for point, place in [*((point, point) for point in points), *((None, unit) for unit in units)]:
        # `place`: the point, or a unit without one (its water's clock and fish; keyed by its id)
        where = places[place.pk]
        point_water = water[place.pk] = PointWater(point, sensors_failed=answer.failed, for_unit=where.for_unit,
                                                   system_point=where.system[0] if point is None and where.system
                                                   else None,
                                                   standing_place=_system_place(where, place) if point is None
                                                   else None)
        own_ids = {each.pk for each in where.own}
        day = local_time(moment, place).date()
        resolved, candidates = _resolve(_live(where.own_targets, answer), [manual(each) for each in where.own],
                                        _live(where.system_targets, answer), [manual(each) for each in where.system],
                                        context, moment, partial(_at_moment, where),
                                        worked=worked_here(point) if point is not None else None)
        temperature = resolved.get(parameters.TEMPERATURE)          # what an oxygen value is worked out with
        temperature = temperature if temperature is not None and temperature.fresh(moment) else None

        def judged(reading):
            # Each judged on its own copy: a loop's reading stands in for several units, each with its own fish.
            return context.judge(replace(reading), day, moment, temperature, for_point=place)

        for code, reading in resolved.items():
            reading = judged(reading)
            if code in WORST_FRESH_CODES:
                found = [each for each in candidates.get(code, []) if each is not resolved[code]]
                if code in DERIVED:
                    # The judge's verdicts of the place's points (and of its system's own sensors), each value judged
                    # for the place's fish. Every candidate still takes part in the worst fresh value: a point's newest
                    # stored value, fresh, counts beside a newer analyser's value (review 3, N1), even where the judge
                    # also says it as a late result.
                    verdicts, judged_of = _verdicts(code, resolved[code], found, where, context, judged, moment)
                point_water.future += [judged(each) for each in found if each.at - moment > MAX_AHEAD]
                # Fresh, or ahead of the clock within the ingest contract's hour: they take part in the status.
                deciding = [judged(each) for each in found
                            if each.fresh(moment) or freshness.tolerance() < each.at - moment <= MAX_AHEAD]
                # MEASURED AT THE POINT: the point's own newest value of the code, and its fresh others, each judged
                # before another point's value decides (the point's own old critical stays).
                if code in DERIVED:                 # the point's OWN status is its verdict's worst (review 7, M5)
                    worst = verdicts[point.pk].worst if point is not None and point.pk in verdicts else None
                    if worst is not None:
                        point_water.measured.append((judged_of(worst.key).status, judged_of(worst.key).judged))
                else:
                    here = [each for each in (resolved[code], *found) if each.value is not None and point is not None
                            and each.point is not None and each.point.pk == point.pk and each.at - moment <= MAX_AHEAD]
                    shown_here = choose([here], moment, lambda each: each.fresh(moment))
                    if shown_here is not None:
                        point_water.measured += [(each.status, each.judged) for each in map(judged, [
                            shown_here, *(each for each in here if each is not shown_here and each.fresh(moment))])]
                reading.deciding = tuple(deciding)
                worst_fresh(reading, deciding, moment)    # COMPUTED FOR THE PLACE the point stands for
                if where.for_unit and code not in DERIVED and reading.point is not None and reading.point.pk not in own_ids:
                    last_own(reading, [judged(each) for each in found if each.value is not None and each.point is not None
                                       and each.point.pk in own_ids], moment)
                if code in DERIVED:                 # the judge alone holds a worked-out value
                    _worked_said(reading, resolved[code], verdicts, judged_of, where, own_ids, point_water, context,
                                 moment)
            if point is None:                       # a unit without a point: every value is its system's
                said = point_water.standing_said
                reading.note = f'{reading.note} {said}' if reading.note else said
            point_water.readings[code] = reading
        point_water.targets = frozenset(target for target, _origin, _point in (*where.own_targets,
                                                                                 *where.system_targets))
        if where.for_unit:
            _silence(point_water, context.holds_fish(place, day), moment)
    return water


def _system_place(where, unit):
    """How a unit without a point names the place its water is read at: its system's loop point, else its system;
    None for a unit in no system (it is read nowhere)."""
    return where.system[0] if where.system else unit.system


def unanchored(units, anchored):
    """The units of `units` that have no point to read their own water at (none in `anchored`, {unit id: point}):
    what `latest` reads at their system (`units`)."""
    return [unit for unit in units if unit.pk not in anchored]


def _silence(point_water, holds_fish, moment):
    """Owner decision of 2026-11-23 (it reverses the "never red" of 2026-11-04 for the oxygen alone): a unit that holds
    fish now (`holds_fish`: SpeciesBook.holds, after its day's operations) whose oxygen, in mg/L or in %, has no fresh
    value for the place (A9: its own, else its system's; a unit with no point of its own its system's alone) is
    CRITICAL, on every page and in the alarms (`PointWater.silent_oxygen`, counted in its status). A unit without fish
    stays as it was: an old or missing oxygen is "no recent data", never red. Only the point that stands for its unit
    is asked (`for_unit`), a unit without a point of its own included (`latest`, `units`)."""
    point_water.holds_fish = holds_fish
    if not point_water.holds_fish:
        return
    oxygen = [point_water.readings.get(code) for code in (OXYGEN_MG_L, OXYGEN_PCT)]
    oxygen = [reading for reading in oxygen if reading is not None and reading.value is not None]
    if any(reading.fresh(moment) for reading in oxygen):
        return
    newest = max(oxygen, key=lambda reading: (reading.at, reading.code == OXYGEN_MG_L), default=None)
    point_water.silent_oxygen = Silence(newest, moment)


def oxygen_basis(rows, moment):
    """What the oxygen of each row ([(point, values)], one moment: a sample, a round) is worked out with where the row
    has none of its own: ({index: {code: Basis}}, {index: [code missing]}). The one resolver (`latest`, as the water was
    at `moment`, or within the clock's skew after it: nothing measured later) gives the point's temperature and salinity
    fresh AT that moment (`fresh_at`);
    a salinity with none is fresh water's 0 where every unit the point's water concerns is in fresh water. A row without
    an oxygen needs none. One read for every row."""
    wanted = {index: [code for code in BASIS if values.get(code) is None]
              for index, (point, values) in enumerate(rows)
              if values.get(OXYGEN_MG_L) is not None or values.get(OXYGEN_PCT) is not None}
    wanted = {index: codes for index, codes in wanted.items() if codes}
    if not wanted:
        return {}, {}
    points = list({rows[index][0].pk: rows[index][0] for index in wanted}.values())
    water = latest(points, at=min(moment + freshness.tolerance(), timezone.now()))     # one moment for two clocks (fresh_at)
    assumed = assumed_salinities(points)
    found, missing = defaultdict(dict), defaultdict(list)
    for index, codes in wanted.items():
        point = rows[index][0]
        for code in codes:
            reading = water[point.pk].get(code)
            if reading is not None and reading.value is not None and not reading.derived and fresh_at(reading, moment):
                found[index][code] = Basis(reading.value, reading.origin, reading.sample.channel_no, reading.at)
            elif code == parameters.SALINITY and assumed.get(point.pk) is not None:
                found[index][code] = Basis(assumed[point.pk], BasisSource.FRESH_WATER)
            else:
                missing[index].append(code)
    return dict(found), dict(missing)


def last_own(reading, own, now):
    """Decision of 2026-11-19 on the verification of FIX3, F3-9: a value judged critical or a warning that was MEASURED ON
    THE UNIT is confirmed over only by measuring the unit again. Where the value shown stands in from the unit's system
    (A9: the unit has no fresh value of its own) and the unit's own newest value (`own`, judged for its fish) is stale
    and worse, the reading keeps that judgement (so the page, the card and the alarm stay at it: alarms/sources.py, a
    level the unit's own value holds) and says it: `last_own`, `worse` (the value that decides), and the note "last own
    value …, no recent data: measure this unit" (messages.last_own). A fresh own value ends it (A9 shows it)."""
    newest_own = max(own, key=lambda each: each.at, default=None)
    if (newest_own is None or newest_own.fresh(now) or newest_own.judged not in ALERTS
            or RANK[newest_own.judged] >= RANK[reading.judged]):
        return reading
    reading.judged = reading.status = newest_own.judged
    reading.worse = reading.last_own = newest_own
    said = str(messages.last_own(newest_own))
    reading.note = f'{reading.note} {said}' if reading.note else said
    return reading


def bound_at(reading):
    """Where a value BELONGS, the key the judge files it under (review 7, H1): a sample's point; a live value's where its
    sensor is BOUND, never where it is observed. A system's own sensor (origin system sensor) observed at a unit's point
    (or at a unit without one), where the system has no loop point, is the system's: (sources.SYSTEM, its id). Observed
    at the system's loop point it is the loop's own (`sensor_targets`), as a probe bound to that point is."""
    point = reading.point
    if reading.sample.live and reading.sample.origin == Origin.SYSTEM_SENSOR:
        if isinstance(point, SamplingPoint) and point.system_id and point.kind == PointKind.MIDDLE:
            return point.pk
        return (sources.SYSTEM, point.unit.system_id if isinstance(point, SamplingPoint) else point.system_id)
    return point.pk


def record_of(reading, now=None, status=None):
    """THE one builder of the judge's Records, for a stored sample's worked-out reading and a live one, for the point
    verdicts, the value shown and the alarms' clear alike: where it belongs (`bound_at`), its order (measured_at,
    created_at, id: a live value is created at its own moment and its id says it is live and where), whether it is a
    stored sample's, whether it has a value, whether the core refused it, whether it was fresh at its own time, whether it
    is fresh `now` by its OWN freshness (None with no `now`: the judge refuses to read it), and its judgement for the
    place's fish (`status`; not measured where the caller judges nothing)."""
    sample = reading.sample.sample
    where = bound_at(reading)
    return judge.Record(key=reading, point=where, measured_at=reading.at,
                        created_at=sample.created_at if sample is not None else reading.at,
                        id=str(sample.pk) if sample is not None else f'live:{where}', stored=sample is not None,
                        value=reading.value is not None, refused=bool(reading.refused),
                        fresh_at_own_time=reading.fresh_until > reading.at,
                        fresh_now=reading.fresh(now) if now is not None else None,
                        status=status if status is not None else Status.NOT_MEASURED)


def _verdicts(code, shown, found, where, context, judged, moment):
    """({where a value belongs: PointVerdict}, judged_of) of a place's worked-out `code`: the judge's verdict of each of
    its points, own and system, from the samples the shell fetched there and the live values bound there; and of its
    system's own sensors, where they are observed at the unit (`bound_at`). `judged_of(reading)`: the reading judged for
    the place's fish, once."""
    judgements = {}

    def judged_of(reading):
        if id(reading) not in judgements:
            judgements[id(reading)] = judged(reading)
        return judgements[id(reading)]

    def status_of(reading):
        return judged_of(reading).judged

    live = defaultdict(list)
    for each in (shown, *found):
        if each.sample.live:
            live[bound_at(each)].append(each)
    verdicts = {point.pk: context.verdict(point, code, moment, status_of, live.pop(point.pk, ()))
                for point in (*where.own, *where.system)}
    for key, readings in live.items():
        verdicts[key] = judge.point_verdict([record_of(each, moment, status_of(each)) for each in readings])
    return verdicts, judged_of


def _worked_said(reading, shown, verdicts, judged_of, where, own_ids, point_water, context, moment):
    """Applies the judge's verdict of a place (judge.place_verdict) to its worked-out reading `reading` (`shown` judged).
    The shell decides nothing of it:
    - the value HELD and its ONE sentence: the unit's own value behind its system's value shown is the reading's
      `last_own`, said as every last own value is ("last own value …, measure this unit"); any other held value is said
      by its point ("Last value at Outlet …: measure there");
    - the newer samples that give no value; the refused sample of the tier read ("cannot be evaluated",
      `PointWater.refused_newer`, its warning: V-A);
    - the late results, the LATE_SAID worst one by one and the rest counted ("And N more late results");
    - the system's stale alerts older than the value shown; the points past the judge's ceiling;
    - the attention an own sample without its inputs asks, and a point past its ceiling: an OK becomes "cannot be
      evaluated"."""
    code = reading.code
    shown_record = record_of(shown, moment, reading.judged)
    points = {point.pk: point for point in (*where.own, *where.system)}
    late = entered_late({points[key]: verdict for key, verdict in verdicts.items() if key in points})
    verdict = judge.place_verdict(shown_record, verdicts, own_ids, lambda record: late.get(id(record.key), False))
    if verdict.held is not None:
        held = judged_of(verdict.held.key)
        reading.judged = reading.status = held.judged
        reading.worse = held
        if shown_record.point not in own_ids and verdict.held.point in own_ids:
            reading.last_own = held
            _say(reading, messages.last_own(held))
        else:
            _say(reading, messages.last_at_point(held))
    for record in verdict.said:
        _say(reading, messages.lacking_newer(record.key))
    if verdict.refused is not None and code not in point_water.refused_newer:
        point_water.refused_newer[code] = judged_of(verdict.refused.key)
    for record, newer in (*verdict.counted, *verdict.late[:LATE_SAID]):    # the judge's word each (judge.said_as)
        _say(reading, messages.result_said(verdict.words[id(record)], judged_of(record.key), newer.key))
    if verdict.late[LATE_SAID:]:                 # late alerts judged and not said one by one: counted exactly
        _say(reading, messages.late_more(len(verdict.late[LATE_SAID:])))
    unread = sum(context.worked_at(point).late_more for point in (*where.own, *where.system))
    if unread:                                   # late results past LATE_READ: never judged, so said as not read
        _say(reading, messages.late_unread(unread))
    for record in verdict.older:
        _say(reading, messages.older_at_system(judged_of(record.key), shown))
    names = {point.pk: point.name for point in (*where.own, *where.system)}
    for key in verdict.ceiling:
        _say(reading, messages.look_back_ceiling(names[key], judge.CEILING))
    if (verdict.attention or verdict.ceiling) and reading.judged == Status.OK:
        reading.judged = Status.UNEVALUATED
        if reading.status != Status.STALE:
            reading.status = Status.UNEVALUATED


def _say(reading, said):
    said = str(said)
    if said not in reading.note:
        reading.note = f'{reading.note} {said}' if reading.note else said


def late_results_of(samples):
    """{sample id: the words of its late result}, for the activity log when samples are entered and for a history page's
    rows (the owner's decision on review 5): each of `samples` the judge calls late against its point's stored evidence
    (measured before its minute, entered after it) whose NH₃ is critical or a warning for the fish of its day. The
    samples themselves are judged against their point's evidence (`records`, `more`): no cap can cut one (review 7, M1),
    and the words do not depend on what else was entered. ONE read for all of them (the look-back of their points, no
    late query). The words are in the language in force (the caller's: the log's source language, a page's own)."""
    samples = [sample for sample in samples if gives_value(lambda code, sample=sample: getattr(sample, code))]
    if not samples:
        return {}
    now = timezone.now()
    points = list({sample.point_id: sample.point for sample in samples}.values())
    places, standing, everything = reading_places(points)
    context = Context(everything, now - WINDOW)
    context.prefetch_newest_worked(points, late=False)
    live = live_worked_at(points, places, standing, context, now)
    found = {}
    for point in points:
        mine = {str(sample.pk): sample for sample in samples if sample.point_id == point.pk}

        def status_of(reading):
            day = _local_day(reading.sample.sample) if reading.sample.sample is not None else local_time(
                reading.at, point).date()
            return context.judge(replace(reading), day).judged

        more = [context._derived(sample)[1][NH3_N.code] for sample in mine.values()]
        verdict = context.verdict(point, NH3_N.code, now, status_of, live.get(point.pk, ()), more)
        late = entered_late({point: verdict})
        for record in verdict.late:
            if record.id in mine and record.status in ALERTS:
                value = context.judge(replace(record.key), _local_day(mine[record.id]))
                word = verdict.said_as(record, late.get(id(record.key), False))
                found[mine[record.id].pk] = str(messages.result_said(word, value, verdict.superseded(record).key))
    return found


def entered_late(verdicts):
    """{id of a Record's key: True, False or None} of the superseded alerts whose wording needs it
    (`PointVerdict.asks_history`: behind a LIVE value, no longer counted; nothing else is asked, review 10, F2): whether
    each was entered after the analyser at its point had a reading newer than its minute, from the analyser's history at
    its entry (sources.values_at of the TAN at the point's own targets, one ask a point); None where the history could
    not be read (`judge.UNCHECKED`: never taken for on time). `verdicts`: {point: PointVerdict}."""
    found = {}
    for point, verdict in verdicts.items():
        behind = [record for record in verdict.late if verdict.asks_history(record)]
        if not behind:
            continue
        targets = [target for target, _origin, _at in _observed(point)]
        answers = sources.values_at(targets, TAN, [record.created_at for record in behind])
        for record, answer in zip(behind, answers):
            proved = any(judge.minute(value.at) > record.minute for values in answer.values.values() for value in values)
            found[id(record.key)] = True if proved else None if answer.failed else False    # (review 11, N4)
    return found


def reading_places(points, own=None, units=()):
    """(places, standing, everything): THE one way a read of water builds what it reads, for `latest` and for
    `late_results_of` (review 11, N1). `places`: {id: Places} of the points (and `units`) given and of the standing
    point of each unit one of them is an own-water point of (`anchors`: its middle, else its first own-water point),
    every one through `_places`, so through the one tier resolver read.tiers; `standing`: {point id: its unit's standing
    point} of the given points that are a unit's own-water point but not its standing one (an outlet, a depth: read on
    their own, their live worked-out values worked out in their unit's place, `_standing_worked`); `everything`: every
    point of every place, the given ones first, what a Context of the read is built over."""
    points = list(points)
    unit_ids = {point.unit_id for point in points if point.unit_id}
    if own is None or not unit_ids <= set(own):
        own = own_water(unit_ids)
    stands = anchors([point.unit for point in points if point.unit_id], own)
    standing = {point.pk: stands[point.unit_id] for point in points
                if point.unit_id in stands and stands[point.unit_id].pk != point.pk
                and any(each.pk == point.pk for each in own[point.unit_id])}
    read = {point.pk: point for point in points}
    for anchor in standing.values():
        read.setdefault(anchor.pk, anchor)
    places = _places(list(read.values()), own, units)
    everything = dict(read)
    for each in places.values():
        everything.update({point.pk: point for point in (*each.own, *each.system) if point.pk not in everything})
    return places, standing, list(everything.values())


def _standing_worked(where, answer, context, now):
    """{point id: {worked-out code: Reading}} of the live worked-out values a place works out (`_resolve`: the place's
    newest fresh TAN with the pH, temperature and salinity fresh in its own tier, else its system's), each filed where its
    sensor is bound (`bound_at`). What a unit's own-water point read on its own takes as its own (`latest`) and what a
    result entered at a point is judged against (`live_worked_at`)."""
    _chosen, candidates = _resolve(_live(where.own_targets, answer), [], _live(where.system_targets, answer), [],
                                   context, now, partial(_at_moment, where))
    found = defaultdict(dict)
    for code in DERIVED:
        for reading in candidates.get(code, []):
            if reading.sample.live and reading.value is not None:
                found[bound_at(reading)].setdefault(code, reading)
    return found


def live_worked_at(points, places, standing, context, now):
    """{point id: [Reading]} of the fresh live NH₃ BOUND at each point now, worked out as every page works it (reviews
    9, P6, 10, F1 and 11, N5): a unit's own-water point inside its unit's standing place, any other point inside its own
    place (`reading_places`, `_standing_worked`). So the activity log and a history row say of a sample what the pages
    say. One read of the sensors for all of them."""
    answer = sources.latest([target for where in places.values()
                             for target, _origin, _at in (*where.own_targets, *where.system_targets)], now)
    worked = {}
    found = {}
    for point in points:
        anchor = standing.get(point.pk, point)
        if anchor.pk not in worked:
            worked[anchor.pk] = _standing_worked(places[anchor.pk], answer, context, now)
        reading = worked[anchor.pk].get(point.pk, {}).get(NH3_N.code)
        found[point.pk] = [reading] if reading is not None and reading.fresh(now) else []
    return found

def worst_fresh(reading, others, now=None):
    """Owner decision 2026-11-08 (the second cross review's P2): the value shown is A9's choice, but the status, and so
    the alarm, is the worst of every fresh value the place has (`others`: its own points' and its system's, judged for its
    fish). When another fresh value is worse, the reading takes its judgement and says which value decided it, so danger
    is never hidden behind a newer or nearer OK value."""
    worse = min((each for each in others if each.judged in ALERTS and RANK[each.judged] < RANK[reading.judged]),
                key=lambda each: RANK[each.judged], default=None)
    if worse is None:
        return reading
    source = origin_text(worse)
    if not worse.sample.live:
        source = _('%(origin)s at %(point)s') % {'origin': source, 'point': worse.point}
    said = _('%(source)s reads %(value)s (%(time)s): the worst fresh value decides the status.') % {
        'source': source, 'value': said_value(worse),
        'time': local_time(worse.at, worse.point).strftime('%d.%m.%Y %H:%M')}
    if now is not None and ahead(worse.at, now):
        said = '{} {}'.format(said, _('The device clock is ahead by %(minutes)d min.') % {
            'minutes': int((worse.at - now).total_seconds() // 60)})
    reading.judged = reading.status = worse.judged
    reading.worse = worse
    reading.note = f'{reading.note} {said}' if reading.note else said
    return reading


def crossed(reading):
    """Which value is past which bound, for a reading the limits judge critical or a warning: (the Reading whose value
    it is, the bound's name, the bound), or None when no one bound says it. The value is the worse fresh one when that
    decided the status (`worst_fresh`), the value in its other unit when a row on that unit judged it (the oxygen,
    `Context.judge`), else the reading's own; the bound is the one `evaluate.judge` judged it by (evaluate.crossed), on
    the value the limits judged (`Reading.judged_value`: a worked-out value unrounded, as `Context.judge` judges it).
    For a short sentence beside the full reason (a monitoring card's one line, the band's chip): never a judgement."""
    source = reading.worse or reading
    for each in (source, source.through):
        if each is None or each.value is None:
            continue
        for row in each.limits:
            found = bound_crossed(each.judged_value, row)
            if found is not None and found[0].startswith(str(reading.judged)):
                return (each, *found)
    return None


def past_bound(reading):
    """(the bound's name, the bound) the reading's OWN value was judged past, or None: the nearest of them where its limit
    rows (one per species) give several, so a figure that proves it past that one proves it past the rest on its side.
    On the value the limits judged (`Reading.judged_value`: a worked-out value unrounded), by the bound `evaluate.judge`
    judged it by, whatever the reading's status is (a value another value decides is not the value this one is past).
    What `farm.templatetags.water.proof_of` proves a figure against; never a judgement."""
    value = reading.judged_value
    found = [each for each in (bound_crossed(value, row) for row in reading.limits) if each is not None]
    return min(found, key=lambda each: abs(each[1] - value), default=None)


def said_value(reading):
    """The reading's own value as a note beside the limits that judged it says it ("… reads 59.99 …", "last own value
    59.99 critical …", "Judged as 59.99 %."). A worked-out value is judged unrounded and shown rounded, so past a bound it
    is said with the decimals that show the side it is on (`farm.templatetags.water.figure_past`: never "reads 60.0"
    beside "critical below 60.0"); any other value at its parameter's decimals, as it always was. Display only."""
    from farm.templatetags.water import figure_past      # it imports this module
    return figure_past(reading) or number_format(reading.value, reading.parameter.decimals)


def _values_at(targets, moment, codes=parameters.COLUMNS):
    """The live sources' values of every measured parameter (or of `codes`) at a past moment, as one answer
    (sources.Answer)."""
    merged, failed = {}, False
    for code in codes:
        answer = sources.value_at(targets, code, moment)
        failed = failed or answer.failed
        for target, values in answer.values.items():
            merged.setdefault(target, {})[code] = values
    return sources.Answer(merged, failed)


# What a sensor pH on another scale than NBS is put on the NBS scale with (Context.sensor_ph).
PH_INPUTS = (parameters.TEMPERATURE, parameters.SALINITY)


def _at_moment(where, moment):
    """{code: Observation} of the place's (`where`, a Places) sensor temperature and salinity fresh AT `moment`, each
    channel's value at it (sources.value_at), its own tier's before its system's (A9) as `_resolve` takes them now: what a
    sensor pH no longer fresh is put on the NBS scale with at its own moment (owner decision of 2026-11-20). Asked only
    for such a pH (one ask per input)."""
    answer = _values_at([target for target, _origin, _point in (*where.own_targets, *where.system_targets)], moment,
                        PH_INPUTS)
    own, system = (_fresh_live(_live(targets, answer), moment) for targets in (where.own_targets, where.system_targets))
    return {code: own.get(code) or system.get(code) for code in PH_INPUTS if own.get(code) or system.get(code)}


# A place a sensor is bound to, beside sources.POINT and sources.SYSTEM: a piece of equipment (its water is the systems'
# it serves).
EQUIPMENT = 'equipment'


def units_served(points, system_ids=(), equipment_ids=()):
    """The units a place's water is judged for, the one definition: ({point id: [unit]}, {system id: [unit]},
    {equipment id: [unit]}). A unit's point: the unit; a loop's point or a system: the system's live units; a piece of
    equipment, or its point: the units of the systems it serves (each once, by code). Two queries at most."""
    system_ids, equipment_ids = set(system_ids), set(equipment_ids)
    system_ids |= {point.system_id for point in points if point.system_id}
    asked_equipment = equipment_ids | {point.equipment_id for point in points if point.equipment_id}
    serves = defaultdict(set)                          # equipment id -> the ids of the systems it serves
    if asked_equipment:
        links = EquipmentSystem.objects.filter(equipment__in=asked_equipment, system__is_deleted=False)
        for equipment_id, system_id in links.values_list('equipment_id', 'system_id'):
            serves[equipment_id].add(system_id)
            system_ids.add(system_id)
    units_of = defaultdict(list)                       # system id -> its live units
    if system_ids:
        for unit in (Tank.objects.filter(system__in=system_ids).select_related('production_department__site')
                     .order_by('code')):
            units_of[unit.system_id].append(unit)

    def of_equipment(equipment_id):
        found = {unit.pk: unit for system_id in serves.get(equipment_id, ()) for unit in units_of.get(system_id, [])}
        return sorted(found.values(), key=lambda unit: unit.code)

    by_point = {}
    for point in points:
        if point.unit_id:
            by_point[point.pk] = [point.unit]
        elif point.system_id:
            by_point[point.pk] = units_of.get(point.system_id, [])
        else:
            by_point[point.pk] = of_equipment(point.equipment_id)
    return (by_point, {system_id: units_of.get(system_id, []) for system_id in system_ids},
            {equipment_id: of_equipment(equipment_id) for equipment_id in equipment_ids})


def _fished(places, now):
    """{place: [the units holding fish now (SpeciesBook.holds)]} of the places given ((sources.POINT, point id),
    (sources.SYSTEM, system id) or (EQUIPMENT, equipment id)), among the units the place's water is judged for
    (`units_served`, the one definition the water read's Context uses too). Four queries at most."""
    places = set(places)
    point_ids = [pk for kind, pk in places if kind == sources.POINT]
    points = list(SamplingPoint.objects.filter(pk__in=point_ids).with_owners()) if point_ids else []
    by_point, by_system, by_equipment = units_served(
        points, {pk for kind, pk in places if kind == sources.SYSTEM}, {pk for kind, pk in places if kind == EQUIPMENT})
    served = {**{(sources.POINT, pk): units for pk, units in by_point.items()},
              **{(sources.SYSTEM, pk): units for pk, units in by_system.items()
                 if (sources.SYSTEM, pk) in places},
              **{(EQUIPMENT, pk): units for pk, units in by_equipment.items()}}
    book = SpeciesBook({unit.pk for units in served.values() for unit in units})
    return {place: [unit for unit in units if book.holds(unit.pk, local_time(now, unit).date())]
            for place, units in served.items()}


def with_fish(places, now=None):
    """The places given (`_fished`) whose water concerns a unit holding fish now: what the sensors' default "No fresh
    value" rules hold for (owner decision of 2026-11-23: a fallow or empty unit, or one emptied earlier today, raises
    no alarm; SpeciesBook.holds; sensors/alarms.py)."""
    return {place for place, units in _fished(places, now or timezone.now()).items() if units}


def oxygen_known(places, now=None):
    """The places given (`_fished`) whose water concerns fish and where every unit holding fish has a fresh oxygen all
    the same (`PointWater.silent_oxygen` None: a typed sample, or another probe). A silent oxygen probe there is then a
    warning, not the critical its default rule says when nothing else is known (review 2 of the branch, R3 p3; the
    card follows the fresh value): sensors/alarms.py. One read of those units' water."""
    now = now or timezone.now()
    fished = _fished(places, now)
    units = {unit.pk: unit for found in fished.values() for unit in found}
    water = unit_water(list(units.values()), now) if units else {}
    return {place for place, found in fished.items()
            if found and all(water[unit.pk].silent_oxygen is None for unit in found)}


def owner_water(owners, now=None):
    """{owner id: PointWater} of each unit's, loop's or equipment's water: its middle point's latest values
    (`middle_points`), nothing for an owner that has none. What Production units, its drawer and the overview show
    for units (`unit_water`), and what the calculator takes a unit's or a loop's values from."""
    owners = list(owners)
    units = [owner for owner in owners if owner_type_of(owner) == 'unit']
    own = own_water([unit.pk for unit in units])
    anchored = anchors(units, own)
    middles = {**middle_points([owner for owner in owners if owner_type_of(owner) != 'unit']), **anchored}
    water = latest(list(middles.values()), now, own=own, units=unanchored(units, anchored))
    return {owner.pk: water[middles[owner.pk].pk] if owner.pk in middles else water.get(owner.pk, PointWater(None))
            for owner in owners}


def unit_water(units, now=None):
    """{unit id: PointWater} of each unit's water (`owner_water`)."""
    return owner_water(units, now)


MIDDLE = PointKind.MIDDLE


def points_of(units, middle_only=(), own=None):
    """{unit id: [SamplingPoint]} of every unit given: its active points, the middle point first (`middle_points`, the
    one definition of it), the others by name; for the units of `middle_only` (ids) the middle point alone. A unit
    without a middle point has only its others (or none): nothing stands in for it. `own`: the units' `own_water`, when
    the caller has read it."""
    units = list(units)
    middles = anchors(units, own)              # the middle point, else the point that stands for the unit
    narrow = set(middle_only)
    wide = [unit.pk for unit in units if unit.pk not in narrow]
    others = defaultdict(list)
    if wide:
        for point in (SamplingPoint.objects.filter(unit__in=wide, is_active=True)
                      .exclude(pk__in=[point.pk for point in middles.values()]).with_owners()):
            others[point.unit_id].append(point)
    return {unit.pk: [*([middles[unit.pk]] if unit.pk in middles else []),
                      *sorted(others[unit.pk], key=lambda point: point.name)] for unit in units}


def points_water(units, now=None, middle_only=()):
    """{unit id: [PointWater]} of every unit given: the readings of each of its `points_of`, all read by ONE `latest()`.
    The units' own-water points are read once, for both (`own_water`)."""
    units = list(units)
    own = own_water([unit.pk for unit in units])
    anchored = anchors(units, own)
    chosen = points_of(units, middle_only, own)
    bare = unanchored(units, anchored)
    water = latest([point for points in chosen.values() for point in points], now, own=own, units=bare)
    found = {unit_id: [water[point.pk] for point in points] for unit_id, points in chosen.items()}
    # A unit with no point to read its own water at: its water read at its system (`latest`, `units`), first, where it
    # says something (a value, or fish whose oxygen it judges); else none, as before.
    for unit in bare:
        standing = water[unit.pk]
        if standing.readings or standing.holds_fish:
            found[unit.pk] = [standing, *found[unit.pk]]
    return found


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


def measured(points, code, start, end):
    """[(at, value, source)] of the live samples at `points` (SamplingPoints) with a value of the parameter `code` in
    [start, end), oldest first; source 'manual' or 'lab' (farm.WaterMeasurement.Source): the values a place's chart
    draws beside its sensors' (sensors.read.water_history)."""
    return list(WaterMeasurement.objects.filter(point__in=list(points), measured_at__gte=start, measured_at__lt=end,
                                                **{f'{code}__isnull': False})
                .order_by('measured_at').values_list('measured_at', code, 'source'))


def sampled(points, start, end, codes):
    """The parameters of `codes` with a value in a live sample at `points` in [start, end), in the order given: one
    query (each column's count of values)."""
    points = list(points)
    if not points or not codes:
        return []
    counts = WaterMeasurement.objects.filter(point__in=points, measured_at__gte=start, measured_at__lt=end).aggregate(
        **{code: models.Count(code) for code in codes})
    return [code for code in codes if counts[code]]


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
    # The judge (farm/water/judge.py) on each point's look-back, as the latest read asks it, whatever the page holds
    # (review 6, L6): a late result says so on its row, with what superseded it.
    late = late_results_of([row.sample for row in rows if not row.sample.is_deleted])
    for row in rows:
        if row.sample.pk in late and NH3_N.code in row.readings:
            _say(row.readings[NH3_N.code], late[row.sample.pk])
    return rows


def limits_of(places):
    """{place id: {code: [WaterLimit]}} for the fish at each point, or in each unit, loop or piece of equipment, today:
    what a value there would be judged against. ONE read of the fish and of the limits for all the places (a wall of
    cards asks for every unit at once): the queries do not grow with the places."""
    now = timezone.now()
    points = {place.pk: place if isinstance(place, SamplingPoint) else SamplingPoint(**{owner_type_of(place): place})
              for place in places}
    context = Context(points.values(), None)
    found = {}
    for pk, point in points.items():
        exposures = context.exposures(point, local_time(now, point).date())
        limits = found[pk] = {}
        for parameter in parameters.LIMITED:
            rows = []
            for species_id, water_type in exposures:
                row = context.limits.applying(species_id, parameter.code, water_type)
                if row is not None and row not in rows:
                    rows.append(row)
            if rows:
                limits[parameter.code] = rows
    return found


def limits_now(place):
    """{code: [WaterLimit]} for the fish at a point, or in a unit, loop or piece of equipment, today (`limits_of`)."""
    return limits_of([place])[place.pk]


@dataclass(frozen=True)
class Missing:
    """A species kept in a water type today, and the parameters no limit row judges for it there."""
    species: object
    water_type: str
    parameters: list

    @property
    def water_type_label(self):
        return Tank.WaterType(self.water_type).label


def missing_limits():
    """[Missing] of the fish kept today: per species and the water type of each live unit it is in (SpeciesBook, on the
    unit's own day), the limitable parameters that no row judges there (`Limits.applying`: the water type's row, else
    the row for any water), the oxygen once (a row on mg/L or on % judges it, parameters.SAME_QUANTITY: the parameter
    named is the mg/L). In the order of the species' name and the water type. Where this is empty every value of every
    stocked unit is judged; a card says the rest ("no limit", monitoring/read.py)."""
    units = list(Tank.objects.select_related('production_department__site'))
    book = SpeciesBook({unit.pk for unit in units})
    exposures = set()
    for unit in units:
        exposures |= {(species_id, unit.water_type) for species_id in book.on(unit.pk, local_today(unit))}
    if not exposures:
        return []
    # A deleted species whose fish are still kept is named too: its rows judge nothing (Context), so nothing does.
    species = Species.all_objects.in_bulk({species_id for species_id, _water_type in exposures})
    limits = Limits(WaterLimit.objects.filter(species_id__in=species, species__is_deleted=False))
    found = []
    for species_id, water_type in exposures:
        missing = []
        for parameter in parameters.LIMITED:
            other = parameters.SAME_QUANTITY.get(parameter.code)
            if limits.applying(species_id, parameter.code, water_type) is not None or \
                    (other and limits.applying(species_id, other, water_type) is not None):
                continue
            if other and parameter.code == parameters.OXYGEN_PCT:
                continue                                            # the oxygen is named once, as mg/L
            missing.append(parameter)
        if missing:
            found.append(Missing(species[species_id], water_type, missing))
    return sorted(found, key=lambda entry: (entry.species.common_name, entry.water_type))


def history_events(user, owner, start, end):
    """[{at, until, all_day, when, kind, label, url, severity?}] of what happened to a unit's fish in the window, each
    read by its own area's reader and only for a person who may read that area: the feedings (farm.feeding.read
    `fed_in`: a record's moment), the treatments (farm.health.read `treatments_on`: first to last day), the harvests
    (farm.stock.read `harvests_on`: the operation's day) and the alarms opened at its points (alarms.read `opened_at`; a
    system's own channels too). A day-dated record (a treatment, a harvest) is a day, never a time of day: `all_day`, and
    `when` says the day or the days ("18.11.2026", "18.11.2026 – 20.11.2026"); a timed one says its moment on the site's
    clock. `at` and `until` are clipped to the window (where the marks stand), `when` is the record's own. A water
    exchange has no record in this product yet: none is shown. A system's are its alarms only."""
    from django.urls import reverse
    from django.utils import formats

    from alarms import read as alarm_read
    from farm.feeding.read import fed_in
    from farm.health.read import treatments_on
    from farm.models.site import zone_of
    from farm.stock.dates import end_of, start_of
    from farm.stock.read import harvests_on

    from .calculation import points_for

    zone = zone_of(site_of(owner))
    first, last = start.astimezone(zone).date(), end.astimezone(zone).date()

    def day(value):
        return formats.date_format(value, 'DATE_FORMAT')

    def moment(value):
        return formats.date_format(timezone.localtime(value, zone), 'DATETIME_FORMAT')

    found = []
    if isinstance(owner, Tank):
        if user.has_perm('farm.view_feedingrecord'):
            for at, record in fed_in(owner, start, end):
                found.append({'at': at, 'until': None, 'all_day': False, 'when': moment(at), 'kind': 'feeding',
                              'label': _('Fed %(kg)s kg of %(feed)s') % {'kg': formats.localize(record.amount_kg),
                                                                        'feed': record.feed},
                              'url': reverse('farm:feeding_records')})
        if user.has_perm('farm.view_treatment'):
            for treatment in treatments_on(owner, first, last):
                ends = treatment.end_date
                when = (day(treatment.start_date) if ends == treatment.start_date
                        else f'{day(treatment.start_date)} – {day(ends) if ends else "…"}')
                found.append({'at': max(start_of(treatment.start_date, owner), start),
                              'until': min(end_of(ends, owner), end) if ends else None, 'all_day': True, 'when': when,
                              'kind': 'treatment', 'label': _('Treatment: %(method)s') % {
                                  'method': treatment.get_method_display()},
                              'url': reverse('farm:treatments')})
        if user.has_perm('farm.view_stockoperation'):
            for operation in harvests_on(owner, first, last):
                found.append({'at': max(start_of(operation.date, owner), start), 'until': None, 'all_day': True,
                              'when': day(operation.date), 'kind': 'harvest', 'label': _('Harvest'),
                              'url': reverse('farm:harvests')})
    if user.has_perm('alarms.view_alarm'):
        for alarm in alarm_read.opened_at(points_for(owner), start, end, system=owner if isinstance(owner, System) else None):
            found.append({'at': alarm.opened_at, 'until': None, 'all_day': False, 'when': moment(alarm.opened_at),
                          'kind': 'alarm', 'severity': alarm.severity, 'label': alarm.summary,
                          'url': reverse('alarms:alarm_detail', args=[alarm.pk])})
    found.sort(key=lambda event: event['at'])
    return [{**event, 'at': int(event['at'].timestamp()),
             'until': int(event['until'].timestamp()) if event['until'] else None, 'label': str(event['label']),
             'when': str(event['when'])}
            for event in found]


def live_samples_at(unit_ids, system_ids):
    """The live water samples taken at these units' own points or these systems' (an experiment's raw data,
    experiments/rawdata.py), with their point, read through the sealed manager (`samples_of` reads voided ones too)."""
    return WaterMeasurement.objects.filter(Q(point__unit__in=unit_ids) | Q(point__system__in=system_ids)).select_related(
        'point')

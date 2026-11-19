"""The trail of a unit's (or a system's) water on the Deffeyes diagram (owner amendment A4): where its point was hour by
hour over a range. Each hour takes, per input, by owner rule A9 (`farm.water.read.choose`, as the live view): the newest
fresh value of the owner's own places (the hour's mean of the sensors bound there, from the hour rollup, or a manual or
lab sample fresh at the hour's end), else of its system's, else (salinity only) the assumption for fresh water. An hour
without one of the four inputs is listed as
missing, never filled; an hour whose pH and alkalinity cannot go together (the pH's hydroxide alone is more alkalinity
than the water has: the core refuses such a water, chemistry.ImpossibleWaterError) is listed as impossible, never drawn;
an hour whose water the core refuses itself (a conductivity past the fresh path's range) is listed as unworkable with
the core's reason (deffeyes.unworkable, the gate a unit's chart asks; review R1: the whole trail raised).
The point is the diagram's: the dissolved inorganic carbon and the alkalinity
(farm/water/chemistry.py, the chart's own equilibria: formula 3, with the conductivity at 25 °C and the hardness of the
hour when there, IONS)."""
from dataclasses import dataclass, field
from datetime import timedelta

from farm.water import chemistry, deffeyes, parameters, read as water_read

from . import read

HOUR = timedelta(hours=1)
INPUTS = (parameters.TEMPERATURE, parameters.PH, 'alkalinity_mg_l', parameters.SALINITY)
# Read when there, never required: the ions besides the alkalinity that give the water's ionic strength (formula 3).
IONS = ('conductivity_25_us_cm', 'hardness_mg_l', 'phosphate_p_mg_l')


@dataclass(frozen=True)
class TrailPoint:
    at: object                   # the hour's start
    temperature_c: float
    ph: float
    alkalinity_mg_l: float
    salinity_ppt: float
    dic: float                   # mmol/L
    alkalinity_meq: float        # meq/L


@dataclass
class Trail:
    owner: object
    start: object
    end: object
    points: list = field(default_factory=list)
    missing: list = field(default_factory=list)        # the hours without every input
    impossible: list = field(default_factory=list)     # the hours whose pH and alkalinity cannot go together
    unworkable: list = field(default_factory=list)     # (hour, why) of the hours whose water the core refuses


def _hourly(owner, conditions, code, start, end):
    """{hour start: (mean, the hour's last reading's time)} of the sensors bound by `conditions` (one tier's) for one
    quantity, from the hour tier: the first segment, in the order they count, with readings in that hour."""
    zone, chosen = read.zone_for(owner), {}
    for segment in read.segments_for(conditions, code, start, end):
        for begin, n, total, _low, _high, _first, last in read.chart_rows(segment, HOUR, read.tier_of(HOUR), zone):
            if begin not in chosen and n:
                chosen[begin] = (total / n, last)
    return chosen


@dataclass(frozen=True)
class Candidate:
    """A value of an hour for `water_read.choose`: when it was measured and the value."""
    at: object
    value: float


def trail(owner, start, end):
    """The Trail of the owner's water from `start` (a whole hour) to `end`. Each input of an hour is picked by owner rule
    A9 through the live view's one function (`farm.water.read.choose`) at the hour's end, over the owner's tiers
    (`sensors.read.tiers`): the newest fresh value of its own places (an hour's sensor mean, at its last reading; a
    sample fresh then), else of its system's; else (salinity only) the fresh-water assumption; else the hour is missing.
    A stale sample never enters (PLAN A9.3)."""
    start = start.replace(minute=0, second=0, microsecond=0)
    hours = max(int((end - start) / HOUR), 1)
    end = start + hours * HOUR
    tiered = read.tiers(owner)
    sensed = [{code: _hourly(owner, conditions, code, start, end) for code in (*INPUTS, *IONS)}
              for conditions, _points in tiered]
    points = list({point.pk: point for _conditions, found in tiered for point in found}.values())
    series = {code: water_read.Series(points, code, start - water_read.WINDOW, end) for code in (*INPUTS, *IONS)}
    units = [owner] if hasattr(owner, 'water_type') else list(owner.tanks.all())
    water_types = {unit.water_type for unit in units}
    origin = water_read.common_origin(units)
    found = Trail(owner, start, end)
    for index in range(hours):
        at = start + index * HOUR
        moment = at + HOUR
        values = {}
        for code in (*INPUTS, *IONS):
            candidates = []
            for rank, (_conditions, tier_points) in enumerate(tiered):
                tier = []
                if at in sensed[rank][code]:
                    mean, last = sensed[rank][code][at]
                    tier.append(Candidate(last, float(mean)))
                for point in tier_points:
                    sample = series[code].latest(point.pk, moment, water_read.WINDOW)
                    if sample is not None and series[code].fresh(sample, moment):
                        tier.append(Candidate(sample.at, float(sample.value)))
                candidates.append(tier)
            picked = water_read.choose(candidates, moment, lambda candidate: True)
            if picked is not None:
                values[code] = picked.value
            elif code == parameters.SALINITY and water_read.assumed_salinity(water_types) is not None:
                values[code] = float(water_read.assumed_salinity(water_types))
        if any(code not in values for code in INPUTS):
            found.missing.append(at)
            continue
        water = (values[parameters.TEMPERATURE], values[parameters.SALINITY], values['alkalinity_mg_l'])
        ions = {**{code: values.get(code) for code in IONS}, 'water_origin': origin}
        try:
            equilibria = chemistry.water_equilibria(*water, **ions)
        except (ValueError, ArithmeticError):       # the core refuses the water: the gate's words for it
            found.unworkable.append((at, deffeyes.unworkable(*water, **ions)))
            continue
        alkalinity = values['alkalinity_mg_l'] / chemistry.MG_CACO3_PER_MEQ
        try:
            dic = equilibria.dic(alkalinity, values[parameters.PH])
        except chemistry.ImpossibleWaterError:      # the core's one rule, the one deffeyes.why_impossible asks
            found.impossible.append(at)
            continue
        found.points.append(TrailPoint(at, values[parameters.TEMPERATURE], values[parameters.PH],
                                       values['alkalinity_mg_l'], values[parameters.SALINITY], dic, alkalinity))
    return found

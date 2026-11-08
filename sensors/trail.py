"""The trail of a unit's (or a system's) water on the Deffeyes diagram (owner amendment A4): where its point was hour by
hour over a range. Each hour takes, per input, the hour's mean of the sensors bound there (the hour rollup, in the A1
order of sensors/read.py: the point's own, then the system's), else the newest manual or lab sample at or before the
hour's end, else (salinity only) the assumption for fresh water. An hour without one of the four inputs is listed as
missing, never filled. The point is the diagram's: the dissolved inorganic carbon and the alkalinity
(farm/water/chemistry.py, the chart's own equilibria)."""
from dataclasses import dataclass, field
from datetime import timedelta

from farm.water import chemistry, parameters, read as water_read

from . import read

HOUR = timedelta(hours=1)
INPUTS = (parameters.TEMPERATURE, parameters.PH, 'alkalinity_mg_l', parameters.SALINITY)


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


def _hourly(owner, code, start, end, hours):
    """{hour start: mean} of the sensors' hour buckets of one quantity (the series is exactly one bucket an hour)."""
    found = read.series(owner, code, start, end, max_points=hours)
    if found.width != HOUR:
        raise ValueError('A trail is drawn from whole hours.')
    return {bucket.start: bucket.avg for bucket in found.buckets}


def trail(owner, start, end):
    """The Trail of the owner's water from `start` (a whole hour) to `end`."""
    start = start.replace(minute=0, second=0, microsecond=0)
    hours = max(int((end - start) / HOUR), 1)
    end = start + hours * HOUR
    points = [point for point in read.places(owner)[1] if point is not None]
    sensed = {code: _hourly(owner, code, start, end, hours) for code in INPUTS}
    series = {code: water_read.Series(points, code, start - water_read.WINDOW, end) for code in INPUTS}
    water_types = {owner.water_type} if hasattr(owner, 'water_type') else {unit.water_type for unit in owner.tanks.all()}
    found = Trail(owner, start, end)
    for index in range(hours):
        at = start + index * HOUR
        values = {}
        for code in INPUTS:
            if at in sensed[code]:
                values[code] = sensed[code][at]
                continue
            sample = next((each for each in (series[code].latest(point.pk, at + HOUR, water_read.WINDOW)
                                             for point in points) if each is not None), None)
            if sample is not None:
                values[code] = float(sample.value)
            elif code == parameters.SALINITY and water_read.assumed_salinity(water_types) is not None:
                values[code] = float(water_read.assumed_salinity(water_types))
        if len(values) < len(INPUTS):
            found.missing.append(at)
            continue
        equilibria = chemistry.equilibria(values[parameters.TEMPERATURE], values[parameters.SALINITY])
        alkalinity = values['alkalinity_mg_l'] / chemistry.MG_CACO3_PER_MEQ
        found.points.append(TrailPoint(at, values[parameters.TEMPERATURE], values[parameters.PH],
                                       values['alkalinity_mg_l'], values[parameters.SALINITY],
                                       equilibria.dic(alkalinity, values[parameters.PH]), alkalinity))
    return found

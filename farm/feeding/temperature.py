"""The water temperature a ration is read at, picked by the water's one rule (owner rule A9, `farm.water.read.choose`)
from the places a unit's water is read from (`water_sources`, the points of the unit's own water, then its system's
loop, then the loops of the systems that system is nested in) and the lookup in them, `Series`, which takes the sensors
too (a sensor value counts as fresh for its channel's three heartbeats). The ration only ever sees a Temperature.

- The candidates are the values with a temperature at the unit's own-water points (its sensors and its samples), at
  the loop point of its system and of that system's parents (the sensors on the loop point and on the system, and the
  loop's samples; a system without a loop point: its sensors, as the water page reads them), measured at or before the
  moment asked.
- The newest fresh value of the unit's own points wins; else the newest fresh value of the nearest system that has one;
  with nothing fresh, the newest of the unit's own, else of the nearest system's, marked stale: exactly what the unit's
  water shows (`farm.water.read.latest`). Fresh is the temperature parameter's freshness (24 h,
  farm/water/parameters.py).
- **However old, the newest temperature gives the ration** (owner amendment A11, 2026-11-08, the one explicit exception
  to A9.3 "a stale value never enters a calculation"; it replaced the 7-day cut-off of decision Q5): a stale one says
  so, "Based on the temperature from dd.mm.yyyy HH:MM (5 days old)" (`Temperature.warning`).
- No temperature ever recorded: no ration, and the page says so. Never a default temperature (the source fed the full
  ration at an unknown temperature, FP-02).

The moment is now for the meal board and today, and the end of the day for a past day (farm/feeding/ration.py)."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from django.utils.translation import ngettext

from farm.models import System
from farm.models.site import zone_of
from farm.models.water_point import local_time
from farm.water import parameters, read
from farm.water.read import SYSTEM, SYSTEM_KEY, UNIT, Series, water_sources

TEMPERATURE = parameters.get(parameters.TEMPERATURE)
# The days the samples of a ration's range are read for at once; an older one is found by Series' `carry`.
READ_DAYS = timedelta(days=7)


@dataclass(frozen=True)
class Temperature:
    """A temperature for a unit at a moment: its value, when and where it was measured (the unit, or the system named
    by `point`; `sampling_point` the point itself, None for a system's own sensor), how old it was at that moment and
    whether it was still fresh."""
    value_c: Decimal
    measured_at: datetime
    point: object
    via: str
    age: timedelta
    fresh: bool
    sampling_point: object = None

    @property
    def warning(self):
        """'' for a fresh temperature; else what the ration is based on and how old it is (owner amendment A11)."""
        if self.fresh:
            return ''
        if self.sampling_point is not None:
            when = local_time(self.measured_at, self.sampling_point)
        else:
            when = self.measured_at.astimezone(zone_of(getattr(self.point, 'site', None)))
        days = int(self.age / timedelta(days=1))
        return ngettext('Based on the temperature from %(when)s (%(days)d day old)',
                        'Based on the temperature from %(when)s (%(days)d days old)', days) % {
            'when': f'{when:%d.%m.%Y %H:%M}', 'days': days}


class TemperatureBook:
    """The temperatures of a set of units between two moments, read once (one query for all their points, one for the
    newest before them); `at(unit, moment)` is the lookup."""

    def __init__(self, units, since, until):
        units = list(units)
        self.sources = water_sources(units, nested=True, every_point=True)
        points = {source.point.pk: source.point for sources in self.sources.values() for source in sources}
        # A system without a loop point stands in through its own sensors, as on the water page (read._places).
        looped = {source.owner.pk for sources in self.sources.values() for source in sources if source.via == SYSTEM}
        bare = {unit.system_id for unit in units if unit.system_id and unit.system_id not in looped}
        self.systems = System.objects.select_related('site').in_bulk(bare) if bare else {}
        self.series = Series(points.values(), TEMPERATURE.code, since - READ_DAYS, until, live=True, carry=True,
                             systems=list(self.systems))

    def tiers(self, unit):
        """[[(key, owner, via)]]: the unit's own points, then its system (its loop, or its own sensors without one),
        then each parent system's loop, nearest first: the tiers `choose` reads."""
        tiers = []
        for source in self.sources.get(unit.pk, []):
            place = (source.point.pk, source.owner, source.via)
            if source.via == UNIT and tiers and tiers[-1][0][2] == UNIT:
                tiers[-1].append(place)
            else:
                tiers.append([place])
        if unit.system_id in self.systems:
            first = 1 if tiers and tiers[0][0][2] == UNIT else 0
            tiers.insert(first, [(SYSTEM_KEY(unit.system_id), self.systems[unit.system_id], SYSTEM)])
        return tiers

    def at(self, unit, moment):
        """The Temperature the unit's ration reads at `moment`, or None when none was ever recorded there."""
        where, candidates = {}, []
        for tier in self.tiers(unit):
            candidates.append([])
            for key, owner, via in tier:
                for found in self.series.candidates(key, moment, None):
                    where[id(found)] = (owner, via)
                    candidates[-1].append(found)
        found = read.choose(candidates, moment, lambda each: self.series.fresh(each, moment))
        if found is not None and not self.series.fresh(found, moment):
            # A11 (owner, 2026-11-08): with nothing fresh, the MOST RECENTLY entered temperature across every tier
            found = read.newest_shown([each for tier in candidates for each in tier], moment)
        if found is None:
            return None
        owner, via = where[id(found)]
        return Temperature(found.value, found.at, owner, via, moment - found.at, self.series.fresh(found, moment),
                           found.point)


def temperature_for(units, at):
    """{unit id: Temperature or None} of the units at the moment `at`."""
    book = TemperatureBook(units, at, at)
    return {unit.pk: book.at(unit, at) for unit in units}

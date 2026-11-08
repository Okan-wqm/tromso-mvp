"""The water temperature a ration is read at, picked by the water's one rule (owner rule A9, `farm.water.read.choose`)
from the places a unit's water is read from (`water_sources`, every point of the unit, then its system's loop, then the
loops of the systems that system is nested in) and the lookup in them, `Series`, which takes the sensors too (a sensor
value counts as fresh for its channel's three heartbeats). The ration only ever sees a Temperature.

- The candidates are the values with a temperature at the unit's own points (its sensors and its samples), at the loop
  point of its system and of that system's parents (the sensors on the loop point and on the system, and the loop's
  samples), measured at or before the moment asked and at most TEMPERATURE_USABLE_DAYS (7) before it (owner decision
  Q5).
- The newest fresh value of the unit's own points wins; else the newest fresh value of the nearest system that has one;
  with nothing fresh, the newest of the unit's own, else of the nearest system's, marked stale: exactly what the unit's
  water shows (`farm.water.read.latest`). Fresh is the temperature parameter's freshness (24 h,
  farm/water/parameters.py).
- Nothing within the window: no temperature, so no ration, and the page says so. Never a default temperature
  (the source fed the full ration at an unknown temperature, FP-02).

The moment is now for the meal board and today, and the end of the day for a past day (farm/feeding/ration.py)."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from django.conf import settings

from farm.water import parameters, read
from farm.water.read import UNIT, Series, water_sources

TEMPERATURE = parameters.get(parameters.TEMPERATURE)


def usable():
    """How old a temperature may be and still give a ration (marked stale after its freshness)."""
    return timedelta(days=settings.TEMPERATURE_USABLE_DAYS)


@dataclass(frozen=True)
class Temperature:
    """A temperature for a unit at a moment: its value, when and where it was measured (the unit, or the loop of
    the system named by `point`; `sampling_point` the point itself), how old it was at that moment and whether it was
    still fresh."""
    value_c: Decimal
    measured_at: datetime
    point: object
    via: str
    age: timedelta
    fresh: bool
    sampling_point: object = None


class TemperatureBook:
    """The temperatures of a set of units between two moments, read once (one query for all their points);
    `at(unit, moment)` is the lookup."""

    def __init__(self, units, since, until):
        self.sources = water_sources(units, nested=True)
        points = {source.point.pk: source.point for sources in self.sources.values() for source in sources}
        self.series = Series(points.values(), TEMPERATURE.code, since - usable(), until, live=True)

    def tiers(self, unit):
        """[[Source]]: the unit's own points, then each system's loop, nearest first: the tiers `choose` reads."""
        tiers = []
        for source in self.sources.get(unit.pk, []):
            if source.via == UNIT and tiers and tiers[-1][0].via == UNIT:
                tiers[-1].append(source)
            else:
                tiers.append([source])
        return tiers

    def at(self, unit, moment):
        """The Temperature the unit's ration reads at `moment`, or None."""
        tiers = self.tiers(unit)
        where = {source.point.pk: source for tier in tiers for source in tier}
        found = read.choose([[found for source in tier
                              for found in self.series.candidates(source.point.pk, moment, usable())] for tier in tiers],
                            moment, lambda each: self.series.fresh(each, moment))
        if found is None:
            return None
        source = where[found.point.pk]
        return Temperature(found.value, found.at, source.owner, source.via, moment - found.at,
                           self.series.fresh(found, moment), found.point)


def temperature_for(units, at):
    """{unit id: Temperature or None} of the units at the moment `at`."""
    book = TemperatureBook(units, at, at)
    return {unit.pk: book.at(unit, at) for unit in units}

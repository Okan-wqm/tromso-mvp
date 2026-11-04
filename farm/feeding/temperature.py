"""The water temperature a ration is read at: the unit's own manual sample, else its system's loop, then the
loops of the systems that system is nested in, read from the water samples (farm/water/read.py: the places the
unit's water is read from, `water_sources`, and the lookup in them, `Series`, which takes the sensors too: a fresh
sensor value at the moment wins at its point, and a sensor value counts as fresh for its channel's three heartbeats).
The ration only ever sees a Temperature.

- The candidates are the live samples with a temperature at the unit's middle point, at the loop point of its
  system and of that system's parents, measured at or before the moment asked and at most
  TEMPERATURE_USABLE_DAYS (7) before it (owner decision Q5).
- The unit's own fresh value wins; else the nearest system's fresh value; with nothing fresh, the newest of the
  stale ones, marked stale. Fresh is the temperature parameter's freshness (24 h, farm/water/parameters.py).
- Nothing within the window: no temperature, so no ration, and the page says so. Never a default temperature
  (the source fed the full ration at an unknown temperature, FP-02).

The moment is now for the meal board and today, and the end of the day for a past day (farm/feeding/ration.py)."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from django.conf import settings

from farm.water import parameters
from farm.water.evaluate import is_fresh
from farm.water.read import SYSTEM, UNIT, Series, water_sources

TEMPERATURE = parameters.get(parameters.TEMPERATURE)


def usable():
    """How old a temperature may be and still give a ration (marked stale after its freshness)."""
    return timedelta(days=settings.TEMPERATURE_USABLE_DAYS)


@dataclass(frozen=True)
class Temperature:
    """A temperature for a unit at a moment: its value, when and where it was measured (the unit, or the loop of
    the system named by `point`), how old it was at that moment and whether it was still fresh."""
    value_c: Decimal
    measured_at: datetime
    point: object
    via: str
    age: timedelta
    fresh: bool


class TemperatureBook:
    """The temperatures of a set of units between two moments, read once (one query for all their points);
    `at(unit, moment)` is the lookup."""

    def __init__(self, units, since, until):
        self.sources = water_sources(units, nested=True)
        points = [source.point for sources in self.sources.values() for source in sources]
        self.series = Series(points, TEMPERATURE.code, since - usable(), until, live=True)

    def at(self, unit, moment):
        """The Temperature the unit's ration reads at `moment`, or None."""
        candidates = []
        for source in self.sources.get(unit.pk, []):
            found = self.series.latest(source.point.pk, moment, usable())
            if found is not None:
                candidates.append(Temperature(found.value, found.at, source.owner, source.via, moment - found.at,
                                              is_fresh(TEMPERATURE, found.at, moment, found.fresh_for)))
        fresh = [candidate for candidate in candidates if candidate.fresh]
        if fresh:
            return fresh[0]           # the unit's own, else the nearest loop's
        return max(candidates, key=lambda candidate: candidate.measured_at, default=None)


def temperature_for(units, at):
    """{unit id: Temperature or None} of the units at the moment `at`."""
    book = TemperatureBook(units, at, at)
    return {unit.pk: book.at(unit, at) for unit in units}

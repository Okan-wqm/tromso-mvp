"""The water temperature a ration is read at: the unit's own manual sample, else its system's loop, then the
loops of the systems that system is nested in, read from the water samples (farm/water/read.py, Series). Sensors
will be one more source of the same lookup; the ration only ever sees a Temperature.

- The candidates are the live samples with a temperature of the unit, of its system and of that system's parents,
  measured at or before the moment asked and at most TEMPERATURE_USABLE_DAYS (7) before it (owner decision Q5).
- The unit's own fresh value wins; else the nearest system's fresh value; with nothing fresh, the newest of the
  stale ones, marked stale. Fresh is the temperature parameter's freshness (24 h, farm/water/parameters.py).
- Nothing within the window: no temperature, so no ration, and the page says so. Never a default temperature
  (the source fed the full ration at an unknown temperature, FP-02).

The moment is now for the meal board and today, and the end of the day for a past day (farm/feeding/ration.py)."""
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.conf import settings

from farm.models import System
from farm.models.site import zone_of
from farm.water import parameters
from farm.water.evaluate import is_fresh
from farm.water.read import Series, key

TEMPERATURE = parameters.get(parameters.TEMPERATURE)
UNIT, SYSTEM = 'unit', 'system'


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


def end_of(day, unit):
    """The last moment of `day` on the clock of the unit's site."""
    zone = zone_of(unit.production_department.site)
    return datetime.combine(day + timedelta(days=1), time.min, tzinfo=zone) - timedelta(microseconds=1)


def chain(unit, systems):
    """The unit's system and the systems it is nested in, nearest first (`systems`: id -> System)."""
    found, seen = [], set()
    node = systems.get(unit.system_id)
    while node is not None and node.pk not in seen:
        seen.add(node.pk)
        found.append(node)
        node = systems.get(node.parent_id)
    return found


class TemperatureBook:
    """The temperatures of a set of units between two moments, read once (one query per kind of point); `at(unit,
    moment)` is the lookup."""

    def __init__(self, units, since, until):
        systems = System.objects.in_bulk()
        self.chains = {unit.pk: chain(unit, systems) for unit in units}
        points = list(units) + list({system.pk: system for found in self.chains.values() for system in found}.values())
        self.series = Series(points, TEMPERATURE.code, since - usable(), until)

    def at(self, unit, moment):
        """The Temperature the unit's ration reads at `moment`, or None."""
        candidates = []
        for point, via in [(unit, UNIT)] + [(system, SYSTEM) for system in self.chains.get(unit.pk, [])]:
            found = self.series.latest(key(point), moment, usable())
            if found is not None:
                measured_at, value = found
                candidates.append(Temperature(value, measured_at, point, via, moment - measured_at,
                                              is_fresh(TEMPERATURE, measured_at, moment)))
        fresh = [candidate for candidate in candidates if candidate.fresh]
        if fresh:
            return fresh[0]           # the unit's own, else the nearest loop's
        return max(candidates, key=lambda candidate: candidate.measured_at, default=None)


def temperature_for(units, at):
    """{unit id: Temperature or None} of the units at the moment `at`."""
    book = TemperatureBook(units, at, at)
    return {unit.pk: book.at(unit, at) for unit in units}

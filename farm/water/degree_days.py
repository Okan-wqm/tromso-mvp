"""The water a batch lived in, day by day, and what it adds up to in degree-days: one definition for every reader, the
medicine withdrawal (farm/health/withdrawal.py) and the purging fast before a harvest (farm/handling/fasting.py).

- **A day's temperature** is, per farm-local day, the lowest daily mean of the live samples at the unit's own-water
  points (middle, depth, outlets, drain; never the inlet: owner, 2026-11-08, the conservative side, a longer
  withdrawal), else at its system's loop point (the places are farm/water/read.py's `water_sources`, the one definition
  of where a unit's water is read; a sample's day is on the clock of its point's site). A batch in several units that
  day takes the lowest.
- **A past day without a measured temperature counts at the batch species' assumed water temperature**
  (`Species.withdrawal_temperature_c`, Setup › Reference data › Species: the farm's own assumption, a low value the
  conservative one), **and as 0 °C when the species has none**: never as unknown. A day that is not over, or still to
  come, without a measurement is not counted: it is projected.
- **A projection** is the mean of the batch's last 7 days with a temperature within 30 days of today; with none
  measured, the species' assumed temperature; with neither, nothing (the callers say so).

`BatchWater` reads everything it needs for a set of batches at once (their presence in the units, the units, their
species, the samples): its questions never query per batch."""
from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.utils import formats
from django.utils.translation import gettext as _, ngettext

from farm.models import Batch, Tank
from farm.models.water_point import local_time
from farm.stock.dates import end_of, start_of
from farm.stock.read import Presence

from . import parameters
from .read import UNIT, Series, water_sources

DAY = timedelta(days=1)
TEMPERATURE = parameters.TEMPERATURE
ZERO = Decimal(0)
PROJECTION_DAYS = 7     # the days with a temperature a projection takes the mean of
LOOKBACK_DAYS = 30      # how far back from today they are looked for (the water's window)

# How a day was counted.
MEASURED, ASSUMED, NOTHING, PENDING = 'measured', 'assumed', 'zero', 'pending'


class Temperatures:
    """The daily mean water temperature of units from `first` to `last`: a unit's own middle point's live
    samples of that farm-local day, else its system loop's (a sample's day is on the clock of its point's site)."""

    def __init__(self, units, first, last):
        self.first, self.last = first, last
        self.sources = water_sources(units, nested=False, every_point=True)
        points = {source.point.pk: source.point for sources in self.sources.values() for source in sources}
        values = defaultdict(list)
        if points and first <= last:
            series = Series(points.values(), TEMPERATURE, *span(units, first, last))
            for point_id, point in points.items():
                for moment, value in zip(series.moments[point_id], series.values[point_id]):
                    day = local_time(moment, point).date()
                    if first <= day <= last:
                        values[(point_id, day)].append(value)
        self.means = {key: sum(found, ZERO) / len(found) for key, found in values.items()}

    def of(self, unit_id, day):
        """The unit's daily mean on `day`: the lowest of its own-water points' that were measured (owner, 2026-11-08: the
        conservative side, a longer withdrawal; never the inlet), else its system's loop's; None when neither was."""
        own = [mean for mean in (self.means.get((source.point.pk, day)) for source in self.sources.get(unit_id, [])
                                 if source.via == UNIT) if mean is not None]
        if own:
            return min(own)
        for source in self.sources.get(unit_id, []):
            mean = self.means.get((source.point.pk, day))
            if mean is not None:
                return mean
        return None


def span(units, first, last):
    """(start, end): the moments a Temperatures of these units reads its samples between, from the first moment of
    `first` to the last of `last`, the earliest and the latest on the clocks of the units' sites; None without units.
    A sample counts on the day of its point's clock, so a point on a site of another clock (a system's loop point) can
    have samples of `first` before the start: what is read depends on the units' clocks (`BatchWater.of_each`)."""
    units = list(units)
    if not units:
        return None
    return min(start_of(first, unit) for unit in units), max(end_of(last, unit) for unit in units)


@dataclass(frozen=True)
class Counted:
    """What one day counts for: its degrees and how it was found. `value` is None for a day that is not over (or still
    to come) and has no measurement: the caller projects it."""
    value: Decimal | None
    how: str

    @property
    def missing(self):
        """A past day counted without a measurement: at the species' assumed temperature, or as 0 °C."""
        return self.how in (ASSUMED, NOTHING)


@dataclass
class Accrual:
    """The degree-days of a run of days: `total`, how many past days were counted without a measurement (`missing`, at
    `assumed` °C, or as 0 °C when that is None), how many were projected (`projected`, at the assumed temperature when
    `projected_at_assumed`), and `unknown` when a day ahead had nothing to be projected at (the total then counts only
    the days that could be)."""
    total: Decimal = ZERO
    missing: int = 0
    assumed: Decimal | None = None
    projected: int = 0
    projected_at_assumed: bool = False
    unknown: bool = False


class BatchWater:
    """The water of a set of batches on the farm's `today`, with the samples read from `first` (and the 30 days before
    today, whichever is earlier). `presence` (farm.stock.read
    .Presence of the batches) can be handed in by a caller that has it already."""

    def __init__(self, batch_ids, today, first, presence=None):
        self.batch_ids, self.today = set(batch_ids), today
        self.presence = presence if presence is not None else Presence.of_batches(self.batch_ids)
        unit_ids = {unit_id for units in self.presence.units.values() for unit_id in units}
        self.units = Tank.all_objects.select_related('production_department__site').in_bulk(unit_ids)
        # The batches' species in one query: the assumed temperature of a day without a measured one.
        self.batches = Batch.all_objects.select_related('species').in_bulk(self.batch_ids)
        self.temperatures = Temperatures(list(self.units.values()), self.first_day(today, first), today)
        self._projections = {}

    @staticmethod
    def first_day(today, first):
        """The first day the samples are read for: `first`, and at least LOOKBACK_DAYS back (a projection takes the
        last measured days within them)."""
        return min(first, today - LOOKBACK_DAYS * DAY)

    @classmethod
    def of_each(cls, asked):
        """{(batch id, today, first): BatchWater} of every (batch id, today, first) asked: one whose every answer about
        that batch is what `BatchWater({batch id}, today, first)` gives, the batch read alone, with the batches whose
        reads are the same read together (a page of fifty rows reads the water about once, not fifty times).

        Batches share one only when they share the day, the first day read and `span`, the moments their samples are
        read between on the clocks of the units each batch was ever in. Everything else a BatchWater holds is each
        batch's own: its presence, its species, the sources of each unit (a unit's own points and its system's loop
        point), and a point's daily means, which are its samples between those moments of a day on its own clock. A
        batch beside batches of other clocks would read a wider span, and a loop point on a site of a third clock
        could then count a sample on `first` that the batch alone does not: a different mean, a different date
        (verification of wip/plans-perf, finding 2)."""
        asked = set(asked)
        if not asked:
            return {}
        presence = Presence.of_batches({batch_id for batch_id, _today, _first in asked})
        units = Tank.all_objects.select_related('production_department__site').in_bulk(
            {unit_id for unit_ids in presence.units.values() for unit_id in unit_ids})
        keys = {}
        for batch_id, today, first in asked:
            first_day = cls.first_day(today, first)
            read = span([units[unit_id] for unit_id in presence.units.get(batch_id, ())], first_day, today)
            keys[(batch_id, today, first)] = (today, first_day, read)
        groups = defaultdict(set)
        for (batch_id, _today, _first), key in keys.items():
            groups[key].add(batch_id)
        # One group holds every batch asked: the presence read above is the one it would read.
        waters = {key: cls(batch_ids, key[0], key[1], presence=presence if len(groups) == 1 else None)
                  for key, batch_ids in groups.items()}
        return {each: waters[key] for each, key in keys.items()}

    def assumed(self, batch_id):
        """The batch species' assumed water temperature; None when it has none."""
        return self.batches[batch_id].species.withdrawal_temperature_c

    def measured(self, batch_id, day):
        """The batch's daily mean on `day`: the lowest of its units' that were measured; None when none was."""
        found = [mean for mean in (self.temperatures.of(unit_id, day)
                                   for unit_id in self.presence.units_of(batch_id, day)) if mean is not None]
        return min(found) if found else None

    def day(self, batch_id, day):
        """What `day` counts for the batch (see the module's docstring)."""
        value = self.measured(batch_id, day)
        if value is not None:
            return Counted(value, MEASURED)
        if day >= self.today:
            return Counted(None, PENDING)
        assumed = self.assumed(batch_id)
        return Counted(ZERO, NOTHING) if assumed is None else Counted(assumed, ASSUMED)

    def projection(self, batch_id):
        """(the temperature a day ahead is projected at, whether it is the species' assumed one): the mean of the batch's
        last PROJECTION_DAYS days with a temperature, within LOOKBACK_DAYS of today; with none measured the assumed
        temperature; (None, False) with neither."""
        if batch_id not in self._projections:
            found, day = [], self.today
            while day > self.today - LOOKBACK_DAYS * DAY and len(found) < PROJECTION_DAYS:
                value = self.measured(batch_id, day)
                if value is not None:
                    found.append(value)
                day -= DAY
            if found:
                self._projections[batch_id] = (sum(found, ZERO) / len(found), False)
            else:
                assumed = self.assumed(batch_id)
                self._projections[batch_id] = (assumed, assumed is not None)
        return self._projections[batch_id]

    def accrue(self, batch_id, first, last):
        """The degree-days of the days from `first` to `last` (both counted) for the batch: a day's measured mean, a
        past day without one at the assumed temperature or 0, a day not over or still to come without one at the
        projection. Nothing to project at leaves `unknown` set and the day uncounted."""
        accrual = Accrual(assumed=self.assumed(batch_id))
        mean, at_assumed = self.projection(batch_id)
        day = first
        while day <= last:
            counted = self.day(batch_id, day)
            if counted.how == PENDING:
                if mean is None:
                    accrual.unknown = True
                else:
                    accrual.projected += 1
                    accrual.projected_at_assumed = at_assumed
                    accrual.total += mean
            else:
                accrual.missing += counted.missing
                accrual.total += counted.value
            day += DAY
        return accrual


def _plain(value):
    """8.0 as the language writes it, one decimal."""
    return formats.number_format(value, 1)


def degree_days_text(value):
    """150 degree-days, 12.5 degree-days: a value as the pages say it (a decimal only when it has one)."""
    value = Decimal(value)
    count = formats.number_format(value, decimal_pos=0 if value == value.to_integral_value() else 1)
    return ngettext('%(count)s degree-day', '%(count)s degree-days', 1 if value == 1 else 2) % {'count': count}


def missing_sentence(count, assumed):
    """The sentence that says how many past days had no measured water temperature and what they were counted at: the
    species' assumed temperature, or 0 °C with the way to set one. Said by every reader that adds degrees up."""
    params = {'count': count}
    if assumed is not None:
        params['temperature'] = _plain(assumed)
        return ngettext(
            '%(count)d day without a measured water temperature is counted at the assumed %(temperature)s °C '
            '(the species’ setting in Reference data).',
            '%(count)d days without a measured water temperature are counted at the assumed %(temperature)s °C '
            '(the species’ setting in Reference data).', count) % params
    return ngettext(
        '%(count)d day without a measured water temperature is counted as 0 °C: set the species’ assumed '
        'temperature in Reference data › Species.',
        '%(count)d days without a measured water temperature are counted as 0 °C: set the species’ assumed '
        'temperature in Reference data › Species.', count) % params


def projected_sentence(assumed):
    """The sentence that says a projection was made at the species' assumed temperature, nothing having been
    measured lately."""
    return _('Projected at the assumed %(temperature)s °C (the species’ setting in Reference data): no water '
             'temperature was measured in the last %(days)d days.') % {'temperature': _plain(assumed),
                                                                       'days': LOOKBACK_DAYS}

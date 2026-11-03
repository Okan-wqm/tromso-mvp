"""What a feeding table gives a batch in a unit on a day (feeding-protocols §6.4, §6.7). Pure: the read layer
(farm/feeding/read.py) loads the assignments, the tables and the temperatures once into a Policy, and the feeding
walk (farm/feeding/fold.py) asks it at every feeding, so the projected growth and the rations come from one place.

- The protocol: the row in force that day for the batch in this unit, else the unit's row, else the whole batch's
  row (owner decision Q8). A unit's row for another species is skipped, with the reason kept: a unit's row
  outlives the fish in it. None: no ration, "no protocol".
- The band: the one with lower weight ≤ W < upper weight, W the fish's estimated average (owner decision Q7).
  None: the fish are outside the protocol, no ration (the source fed the first or last band, FP-03).
- The temperature: farm/feeding/temperature.py. None: no ration.
- The SFR: the band's cell at that temperature; between two columns c1 < T < c2 it is interpolated,
  SFR(c1) + (SFR(c2) − SFR(c1)) × (T − c1) / (c2 − c1); outside the first and last column there is none (no
  extrapolation, owner decision Q1): a cold or a hot unit is not fed at the edge's rate.
- The day's ration R = projected biomass × SFR / 100 (kg a day), a meal R / meals a day, at full precision.
- The expected FCR: the band's, else the protocol's (owner decision a), with its source.
Weight is banded because a band carries the pellet and the meals, which change in steps; temperature is
interpolated because a step makes the ration jump by 15–20 % when a reading crosses a column by 0.1 °C."""
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from django.conf import settings
from django.utils.translation import gettext as _

from farm.templatetags.stock import grams, number

HUNDRED = Decimal(100)


@dataclass(frozen=True)
class Cell:
    temperature_c: Decimal
    sfr_pct: Decimal


@dataclass(frozen=True)
class Band:
    """A band of a table as the ration reads it; `cells` in temperature order."""
    id: int
    min_weight_g: Decimal
    max_weight_g: Decimal
    feed: object
    meals: int
    fcr: Decimal
    cells: tuple

    def contains(self, weight_g):
        return weight_g >= self.min_weight_g and (self.max_weight_g is None or weight_g < self.max_weight_g)


@dataclass(frozen=True)
class Table:
    """A protocol and its bands in weight order."""
    protocol: object
    bands: tuple

    def band_for(self, weight_g):
        return next((band for band in self.bands if band.contains(weight_g)), None)


@dataclass(frozen=True)
class Sfr:
    """An SFR read off a band at a temperature: the cell itself (`low` is `high`), or between two cells."""
    value: Decimal
    temperature_c: Decimal
    low: Cell
    high: Cell

    @property
    def interpolated(self):
        return self.low != self.high


def sfr_at(cells, temperature_c):
    """The SFR of a band's cells (in temperature order) at a temperature, or None outside the first and last."""
    if not cells or temperature_c < cells[0].temperature_c or temperature_c > cells[-1].temperature_c:
        return None
    for low, high in zip(cells, cells[1:]):
        if low.temperature_c <= temperature_c <= high.temperature_c:
            if temperature_c == low.temperature_c:
                return Sfr(low.sfr_pct, temperature_c, low, low)
            if temperature_c == high.temperature_c:
                return Sfr(high.sfr_pct, temperature_c, high, high)
            share = (temperature_c - low.temperature_c) / (high.temperature_c - low.temperature_c)
            return Sfr(low.sfr_pct + (high.sfr_pct - low.sfr_pct) * share, temperature_c, low, high)
    return Sfr(cells[0].sfr_pct, temperature_c, cells[0], cells[0])      # a table of one column


# Why a share has no ration (Basis.missing); Basis.why() says it in the person's language.
NO_PROTOCOL, SPECIES, OUTSIDE_BANDS, NO_TEMPERATURE, OUTSIDE_TABLE = (
    'no_protocol', 'species', 'outside_bands', 'no_temperature', 'outside_table')


@dataclass(frozen=True)
class Basis:
    """What a batch's ration in a unit on a day rests on: the protocol and the assignment row (its scope), the band
    at the fish's weight, the temperature and the SFR there. `missing` says what stops the ration; the expected
    FCR needs the band only, so the projection still credits growth on a day without a temperature."""
    weight_g: Decimal
    table: Table = None
    assignment: object = None
    band: Band = None
    temperature: object = None
    sfr: Sfr = None
    missing: str = ''
    skipped: object = None        # a unit's row for another species, read past

    @property
    def protocol(self):
        return self.table.protocol if self.table else None

    @property
    def scope(self):
        return self.assignment.scope if self.assignment else ''

    @property
    def fcr(self):
        """The expected FCR: the band's, else the protocol's; None without a band."""
        if self.band is None:
            return None
        return self.band.fcr if self.band.fcr is not None else self.table.protocol.expected_fcr

    @property
    def fcr_source(self):
        return 'band' if self.band is not None and self.band.fcr is not None else 'protocol'

    @property
    def meals(self):
        return self.band.meals if self.band else None

    @property
    def has_ration(self):
        return self.sfr is not None

    def ration_kg(self, biomass_kg):
        """The day's ration of fish weighing `biomass_kg` together."""
        return biomass_kg * self.sfr.value / HUNDRED

    def why(self, batch=None):
        """Why there is no ration, as the page says it; '' when there is one."""
        if self.missing == NO_PROTOCOL:
            if self.skipped is not None:
                protocol = self.skipped.protocol
                return _('%(protocol)s, assigned to %(unit)s, is for %(protocol_species)s; these fish are '
                         '%(species)s.') % {'protocol': protocol, 'unit': self.skipped.unit.code,
                                            'protocol_species': protocol.species,
                                            'species': batch.species if batch is not None else '—'}
            return _('No protocol is assigned to these fish.')
        if self.missing == OUTSIDE_BANDS:
            bands = self.table.bands
            upper = bands[-1].max_weight_g
            return _('%(weight)s is outside %(protocol)s (%(range)s).') % {
                'weight': grams(self.weight_g), 'protocol': self.table.protocol,
                'range': band_range(bands[0].min_weight_g, upper)}
        if self.missing == NO_TEMPERATURE:
            return _('No temperature in the last %(days)d days: record one.') % {
                'days': settings.TEMPERATURE_USABLE_DAYS}
        if self.missing == OUTSIDE_TABLE:
            cells = self.band.cells
            return _('%(temperature)s °C is outside this table (%(low)s–%(high)s °C).') % {
                'temperature': number(self.temperature.value_c, 1), 'low': number(cells[0].temperature_c, 1),
                'high': number(cells[-1].temperature_c, 1)}
        return ''


def band_range(lower, upper):
    """50–100 g, or from 500 g for a band without an upper end."""
    if upper is None:
        return _('from %(weight)s g') % {'weight': number(lower, 2 if lower % 1 else 0)}
    return _('%(low)s–%(high)s g') % {'low': number(lower, 2 if lower % 1 else 0),
                                     'high': number(upper, 2 if upper % 1 else 0)}


@dataclass
class Policy:
    """The assignments, tables and temperatures a walk reads, loaded once (read.policy). `temperature(unit id,
    day)` gives the Temperature of a unit for the ration of that day."""
    assignments: list
    tables: dict                  # protocol id -> Table
    species: dict                 # batch id -> species id
    temperature: object
    _rows: dict = field(default_factory=lambda: defaultdict(list))
    _resolved: dict = field(default_factory=dict)

    def __post_init__(self):
        for row in self.assignments:
            self._rows[(row.unit_id, row.batch_id)].append(row)

    def _in_force(self, unit_id, batch_id, day):
        return next((row for row in self._rows.get((unit_id, batch_id), ()) if row.covers(day)), None)

    def resolve(self, unit_id, batch_id, day):
        """(the assignment row in force, a unit's row of another species read past): batch in unit, then the
        unit, then the whole batch (owner decision Q8)."""
        cached = self._resolved.get((unit_id, batch_id, day))
        if cached is not None:
            return cached
        skipped = None
        found = self._in_force(unit_id, batch_id, day)
        if found is None:
            found = self._in_force(unit_id, None, day)
            if found is not None and self.tables[found.protocol_id].protocol.species_id != self.species.get(batch_id):
                skipped, found = found, None
        if found is None:
            found = self._in_force(None, batch_id, day)
        self._resolved[(unit_id, batch_id, day)] = result = (found, skipped)
        return result

    def basis(self, unit_id, batch_id, day, weight_g):
        """The Basis of the batch's ration in the unit on `day`, for fish of `weight_g` on average."""
        assignment, skipped = self.resolve(unit_id, batch_id, day)
        if assignment is None:
            return Basis(weight_g, missing=NO_PROTOCOL, skipped=skipped)
        table = self.tables[assignment.protocol_id]
        band = table.band_for(weight_g)
        if band is None:
            return Basis(weight_g, table, assignment, missing=OUTSIDE_BANDS)
        temperature = self.temperature(unit_id, day)
        if temperature is None:
            return Basis(weight_g, table, assignment, band, missing=NO_TEMPERATURE)
        sfr = sfr_at(band.cells, temperature.value_c)
        if sfr is None:
            return Basis(weight_g, table, assignment, band, temperature, missing=OUTSIDE_TABLE)
        return Basis(weight_g, table, assignment, band, temperature, sfr)

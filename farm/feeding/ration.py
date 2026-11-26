"""What a feeding table gives a batch in a unit on a day (feeding-protocols §6.4, §6.7). Pure: the read layer
(farm/feeding/read.py) loads the assignments, the tables and the temperatures once into a Policy, and the feeding
walk (farm/feeding/fold.py) asks it at every feeding, so the projected growth and the rations come from one place.

- The protocol: the row in force that day for the batch in this unit, else the unit's row, else the whole batch's
  row (owner decision Q8). A unit's row for another species is skipped, with the reason kept: a unit's row
  outlives the fish in it. None: no ration, "no protocol". Cleaner fish (D-1) have no feeding table of their own as
  a rule: when no row applies to them (a unit's row of the production species is read past as for any batch) and
  they share the unit with production fish, they have no ration and no warning, "cleaner fish"; a row for their
  species, of their batch or of their unit, is read as any batch's. Cleaner fish alone in a unit (a hatchery's tank of
  lumpfish) are its production fish: no protocol is a gap, said as for any fish.
- The band: the one with lower weight ≤ W < upper weight, W the fish's estimated average (owner decision Q7).
  None: the fish are outside the protocol, no ration (the source fed the first or last band, FP-03).
- The temperature: farm/feeding/temperature.py. None: no ration.
- The SFR at a temperature: the band's cell there; between two columns c1 < T < c2 it is interpolated,
  SFR(c1) + (SFR(c2) − SFR(c1)) × (T − c1) / (c2 − c1); outside the first and last column there is none (no
  extrapolation, owner decision Q1): a cold or a hot unit is not fed at the edge's rate.
- The day's ration R = projected biomass × SFR / 100 (kg a day), a meal R / meals a day, at full precision.
- The expected FCR, the uneaten share of the feed and the SFR over the fish's weight follow the protocol's
  between-band rule for each (owner decisions 13 and 14 of 2026-11-26). `smooth` (a new protocol's): each band's
  value (its own, else the protocol's: owner decision a) sits at the band's anchor weight and is read between two
  anchors without a jump, constant before the first and after the last (farm/feeding/growth.py, `interpolate`: the
  one place). `step`: the fish's own band's value, with a step at the band's edge (what every protocol did before,
  and what the protocols that existed then keep: migration farm 0053).
- The expected mortality (% a month, for the plan ahead only): the band's, else the protocol's, else none.
The feed (its pellet) and the meals a day are the band's own: they change in steps. The SFR is read between two
temperature columns because a step makes the ration jump by 15–20 % when a reading crosses a column by 0.1 °C, and
between two bands (when the rule is smooth) for the same reason at a band's edge."""
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from django.utils.translation import gettext as _

from farm.templatetags.stock import grams, number

from . import growth

HUNDRED = Decimal(100)
# A protocol's between-band rules (FeedingProtocol.fcr_between, uneaten_between, sfr_between; BetweenBands' values).
SMOOTH, STEP = 'smooth', 'step'
ZERO = Decimal(0)


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
    uneaten_pct: Decimal = None          # the band's own; None: the protocol's
    mortality_pct_month: Decimal = None  # the band's own; None: the protocol's

    def contains(self, weight_g):
        return weight_g >= self.min_weight_g and (self.max_weight_g is None or weight_g < self.max_weight_g)


@dataclass(frozen=True)
class Table:
    """A protocol and its bands in weight order."""
    protocol: object
    bands: tuple

    def band_for(self, weight_g):
        return next((band for band in self.bands if band.contains(weight_g)), None)

    def fcr_of(self, band):
        """A band's expected FCR: its own, else the protocol's."""
        return band.fcr if band.fcr is not None else self.protocol.expected_fcr

    def uneaten_of(self, band):
        """A band's uneaten share in %: its own, else the protocol's, else none of the feed."""
        if band.uneaten_pct is not None:
            return band.uneaten_pct
        return self.protocol.uneaten_pct if self.protocol.uneaten_pct is not None else ZERO

    def mortality_of(self, band):
        """A band's expected mortality in % a month: its own, else the protocol's; None: none expected."""
        return band.mortality_pct_month if band.mortality_pct_month is not None else self.protocol.mortality_pct_month

    def _between(self, weight_g, value_of, rule):
        """A value at `weight_g` by the protocol's between-band rule for it: the fish's own band's value (`step`), or
        the bands' values at their anchor weights read in between (`smooth`, growth.interpolate: the one place).
        None outside the bands."""
        band = self.band_for(weight_g)
        if band is None:
            return None
        if rule == STEP:
            return value_of(band)
        return growth.interpolate(tuple((growth.anchor(each.min_weight_g, each.max_weight_g), value_of(each))
                                        for each in self.bands), weight_g)

    def fcr_at(self, weight_g):
        """The expected FCR of fish of `weight_g`; None outside the bands."""
        return self._between(weight_g, self.fcr_of, self.protocol.fcr_between)

    def uneaten_at(self, weight_g):
        """The uneaten share (%) of the feed given to fish of `weight_g`; None outside the bands."""
        return self._between(weight_g, self.uneaten_of, self.protocol.uneaten_between)

    def sfr_at(self, weight_g, temperature_c):
        """The Sfr of fish of `weight_g` at a temperature: each band's SFR there (read between its two columns, never
        outside the first and last: `sfr_at`) and, over the weight, the between-band rule of the SFR. `low` and `high`
        are the cells of the fish's own band; `banded` its own band's SFR there. None outside the bands or the columns."""
        band = self.band_for(weight_g)
        own = sfr_at(band.cells, temperature_c) if band is not None else None
        if own is None:
            return None
        value = self._between(weight_g, lambda each: sfr_at(each.cells, temperature_c).value,
                              self.protocol.sfr_between)
        return Sfr(value, temperature_c, own.low, own.high, own.value)

    def columns(self):
        """The temperature columns of the table (every band has them all)."""
        return tuple(cell.temperature_c for cell in self.bands[0].cells) if self.bands else ()

    def used(self):
        """The values the table actually gives over the fish's weight, for a person to see (the protocol's page) and a
        test to hold against the plan: a Used at every band's lower weight and at every band's anchor weight (where
        the value entered for the band sits), in weight order. Read by the very functions the ration and the growth
        read (`fcr_at`, `uneaten_at`, `sfr_at`), so the page cannot show another rule."""
        anchors = {growth.anchor(band.min_weight_g, band.max_weight_g): band for band in self.bands}
        weights = sorted({band.min_weight_g for band in self.bands} | set(anchors))
        return [Used(weight, self.band_for(weight), anchors.get(weight) is self.band_for(weight), self.fcr_at(weight),
                     self.uneaten_at(weight),
                     tuple(self.sfr_at(weight, temperature_c).value for temperature_c in self.columns()))
                for weight in weights]


@dataclass(frozen=True)
class Used:
    """What a table gives fish of `weight_g`: the FCR, the uneaten share (%) and the SFR at each temperature column.
    `anchor`: the weight is where its band's entered values sit, so these are the values entered."""
    weight_g: Decimal
    band: Band
    anchor: bool
    fcr: Decimal
    uneaten_pct: Decimal
    sfr: tuple


@dataclass(frozen=True)
class Sfr:
    """An SFR read off a band at a temperature: the cell itself (`low` is `high`), or between two cells."""
    value: Decimal
    temperature_c: Decimal
    low: Cell
    high: Cell
    banded: Decimal = None        # the fish's own band's SFR there, when the value was read between the bands

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
    # Only a table of one column (stored before a table needed two, F-080) gets here: its temperature exactly.
    return Sfr(cells[0].sfr_pct, temperature_c, cells[0], cells[0])


# Why a share has no ration (Basis.missing); Basis.why() says it in the person's language. CLEANER_FISH is no fault:
# cleaner fish without a feeding table of their own, which the pages mark as cleaner fish and never warn about.
NO_PROTOCOL, SPECIES, OUTSIDE_BANDS, NO_TEMPERATURE, OUTSIDE_TABLE, FASTING, CLEANER_FISH = (
    'no_protocol', 'species', 'outside_bands', 'no_temperature', 'outside_table', 'fasting', 'cleaner_fish')


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
    fast: object = None           # the fast a planned harvest or transport asks for (farm.handling.fasting.Fast)

    @property
    def protocol(self):
        return self.table.protocol if self.table else None

    @property
    def scope(self):
        return self.assignment.scope if self.assignment else ''

    @property
    def fcr(self):
        """The expected (biological) FCR at the fish's weight (Table.fcr_at); None without a band."""
        return self.table.fcr_at(self.weight_g) if self.band is not None else None

    @property
    def uneaten_pct(self):
        """The share (%) of the feed given that is not eaten, at the fish's weight; None without a band."""
        return self.table.uneaten_at(self.weight_g) if self.band is not None else None

    @property
    def economic_fcr(self):
        """Feed given per growth: the expected FCR ÷ the share eaten; None without a band."""
        return growth.economic_fcr(self.fcr, self.uneaten_pct) if self.band is not None else None

    @property
    def mortality_pct_month(self):
        """The expected mortality (% a month) of the fish's band; None: none expected, or no band."""
        return self.table.mortality_of(self.band) if self.band is not None else None

    @property
    def meals(self):
        return self.band.meals if self.band else None

    @property
    def has_ration(self):
        return self.sfr is not None

    @property
    def cleaner_fish(self):
        """Cleaner fish without a feeding table of their own: no ration, and nothing wrong (D-1)."""
        return self.missing == CLEANER_FISH

    def ration_kg(self, biomass_kg):
        """The day's ration of fish weighing `biomass_kg` together."""
        return biomass_kg * self.sfr.value / HUNDRED

    def why(self, batch=None):
        """Why there is no ration, as the page says it; '' when there is one, and for cleaner fish without a table of
        their own (`cleaner_fish`), which is no fault: a page tells those apart by `cleaner_fish`, never by an empty
        why alone."""
        if self.missing == NO_PROTOCOL:
            if self.skipped is not None:
                protocol = self.skipped.protocol
                return _('%(protocol)s, assigned to %(unit)s, is for %(protocol_species)s; these fish are '
                         '%(species)s.') % {'protocol': protocol, 'unit': self.skipped.unit.code,
                                            'protocol_species': protocol.species,
                                            'species': batch.species if batch is not None else '—'}
            return _('No protocol is assigned to these fish.')
        if self.missing == FASTING:
            return self.fast.why()
        if self.missing == OUTSIDE_BANDS:
            bands = self.table.bands
            upper = bands[-1].max_weight_g
            return _('%(weight)s is outside %(protocol)s (%(range)s).') % {
                'weight': grams(self.weight_g), 'protocol': self.table.protocol,
                'range': band_range(bands[0].min_weight_g, upper)}
        if self.missing == NO_TEMPERATURE:
            return _('No temperature recorded here yet: record one.')
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


READ = object()     # Policy.basis: read the unit's own temperature of the day


@dataclass(frozen=True)
class PlannedTemperature:
    """A temperature a day ahead is planned at, not measured: the site's value for that month (Setup › Sites)."""
    value_c: Decimal


@dataclass
class Policy:
    """The assignments, tables and temperatures a walk reads, loaded once (read.policy). `temperature(unit id,
    day)` gives the Temperature of a unit for the ration of that day."""
    assignments: list
    tables: dict                  # protocol id -> Table
    species: dict                 # batch id -> species id
    temperature: object
    fasting: object = None        # (unit id, day) -> the Fast of a planned harvest or transport, or None
    cleaner: frozenset = frozenset()   # the ids of the batches of a cleaner-fish species
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

    def basis(self, unit_id, batch_id, day, weight_g, beside=False, temperature=READ):
        """The Basis of the batch's ration in the unit on `day`, for fish of `weight_g` on average. `beside`: the unit
        holds production fish that day, so cleaner fish there are cleaning them (D-1); cleaner fish without production
        fish (a hatchery tank of lumpfish) are that unit's production fish, and a missing table is a gap. `temperature`: the one to read the SFR at
        instead of the unit's own (the plan ahead: a temperature held, or the site's planned one for that month)."""
        assignment, skipped = self.resolve(unit_id, batch_id, day)
        if assignment is None:
            if batch_id in self.cleaner and beside:
                # No table of their own (the unit's row, if any, is the production fish's): no ration, no warning.
                return Basis(weight_g, missing=CLEANER_FISH)
            return Basis(weight_g, missing=NO_PROTOCOL, skipped=skipped)
        table = self.tables[assignment.protocol_id]
        band = table.band_for(weight_g)
        if band is None:
            return Basis(weight_g, table, assignment, missing=OUTSIDE_BANDS)
        if temperature is READ:
            temperature = self.temperature(unit_id, day)
        # A fasting day before a planned harvest or transport has no ration; the band stays, so a feeding given
        # anyway is still credited at the band's expected FCR, and the water's temperature stays on the line
        # (the board's Water column reads it from here: a fasting unit still has water to watch).
        fast = self.fasting(unit_id, day) if self.fasting is not None else None
        if fast is not None:
            return Basis(weight_g, table, assignment, band, temperature, missing=FASTING, fast=fast)
        if temperature is None:
            return Basis(weight_g, table, assignment, band, missing=NO_TEMPERATURE)
        sfr = table.sfr_at(weight_g, temperature.value_c)
        if sfr is None:
            return Basis(weight_g, table, assignment, band, temperature, missing=OUTSIDE_TABLE)
        return Basis(weight_g, table, assignment, band, temperature, sfr)

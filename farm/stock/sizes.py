"""The sizes in a unit: lots, and the species' size limit (Species.max_weight_ratio; the owner, 2026-11-09: fish of very
different weights of the same species must not be in the same tank).

A batch's share in a unit is one count and one biomass (farm/stock/fold.py), so two size classes of one batch put back
together (a grading keeps the batch) would read as one average. The lots keep them apart, along the same fold (its
`before` and `on_line` hooks), never changing it:
- a stocking brings a lot at its measured weight, a graded transfer one at the size class's measured weight, and a plain
  transfer the lots of the source as they were (their share of the fish, each at its own average);
- fish that leave (deaths, culls, harvest, delivery, escape, a plain transfer) leave every lot of the share in proportion
  to its fish, at its own average;
- a weighing measures the share's average, not its spread: every lot keeps its share of the spread and the whole matches
  the measured biomass; a grading weighs the fish that stay after the sorting, which makes them one lot;
- the lots always add up to the share (fish and grams): when they would not, they are the share as one lot.
Each lot keeps the day its weight was measured and how (stocked, weighed), carried along with its fish.

A unit holds a size mix of a species with a limit when its heaviest lot weighs more than the limit times its lightest
(exactly the limit is within it). Lots are compared with their own species only, so cleaner fish never with the salmon
they clean (D-1). The weights compared are the lots' measured averages, or the feeding walk's estimate where feed was
credited since the measured point (`factors`: the estimate over the measured average of the batch in the unit), the
weight the meal board shows."""
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_CEILING, Decimal

from django.utils.translation import gettext as _

from farm.models.stock import MovementKind, OperationKind

ZERO = Decimal(0)
STOCKED, WEIGHED = 'stocked', 'weighed'


@dataclass
class Lot:
    fish: int
    grams: Decimal
    measured_on: date
    how: str                     # STOCKED or WEIGHED

    @property
    def avg_g(self):
        return self.grams / self.fish


def _apportion(lots, take):
    """How many of `take` fish each lot gives, in proportion to its fish (largest remainders first)."""
    total = sum(lot.fish for lot in lots)
    quotas = [Decimal(lot.fish) * take / total for lot in lots]
    given = [int(quota) for quota in quotas]
    left = take - sum(given)
    for index in sorted(range(len(lots)), key=lambda i: (quotas[i] - given[i], lots[i].fish), reverse=True)[:left]:
        given[index] += 1
    return given


def _scaled(lots, grams):
    """The lots with their grams scaled to add up to `grams`."""
    total = sum((lot.grams for lot in lots), ZERO)
    if not lots or total <= 0:
        return lots
    return [Lot(lot.fish, lot.grams * grams / total, lot.measured_on, lot.how) for lot in lots]


class Lots:
    """The lots of every (unit id, batch id), kept along a fold: pass `before` and `line` to farm.stock.fold.fold (or
    `wrap` another fold's hooks)."""

    def __init__(self):
        self.of = {}
        self._op = None
        self._moved = {}

    def before(self, op, shares):
        self._op, self._moved = op, {}

    def line(self, line, share, grams):
        key = (line.unit_id, line.batch_id)
        lots = self.of.get(key, [])
        op, k = self._op, line.count_delta
        if k < 0:
            taken = []
            if lots and sum(lot.fish for lot in lots) >= -k:
                given = _apportion(lots, -k)
                kept = []
                for lot, out in zip(lots, given):
                    if out:
                        taken.append(Lot(out, lot.avg_g * out, lot.measured_on, lot.how))
                    if lot.fish - out:
                        kept.append(Lot(lot.fish - out, lot.avg_g * (lot.fish - out), lot.measured_on, lot.how))
                lots = kept
            if line.kind == MovementKind.TRANSFER_OUT:
                if op.kind == OperationKind.GRADING and line.avg_weight_g is not None:
                    self._moved[line.pair] = [Lot(-k, grams, op.date, WEIGHED)]
                else:
                    self._moved[line.pair] = _scaled(taken, grams) if taken else [Lot(-k, grams, op.date, STOCKED)]
        elif line.kind == MovementKind.WEIGHING:
            if op.kind == OperationKind.GRADING:
                lots = [Lot(share.count, share.grams, op.date, WEIGHED)]
            else:
                lots = [Lot(lot.fish, lot.grams, op.date, WEIGHED) for lot in lots]
        elif line.kind == MovementKind.TRANSFER_IN and line.pair in self._moved:
            lots = lots + [Lot(lot.fish, lot.grams, lot.measured_on, lot.how) for lot in self._moved[line.pair]]
        else:
            lots = lots + [Lot(k, grams, op.date, STOCKED)]
        self.of[key] = self._reconciled(lots, share, op)

    @staticmethod
    def _reconciled(lots, share, op):
        """The lots matching the share: fish of lots of one weight together, grams scaled to the share's."""
        if not share.count:
            return []
        merged = []
        for lot in lots:
            if lot.fish <= 0:
                continue
            same = next((other for other in merged if other.grams * lot.fish == lot.grams * other.fish
                         and other.measured_on == lot.measured_on and other.how == lot.how), None)
            if same is None:
                merged.append(Lot(lot.fish, lot.grams, lot.measured_on, lot.how))
            else:
                same.fish += lot.fish
                same.grams += lot.grams
        if sum(lot.fish for lot in merged) != share.count or not merged:
            when = share.last_weighed or share.since or op.date
            return [Lot(share.count, share.grams, when, WEIGHED if share.last_weighed else STOCKED)]
        return _scaled(merged, share.grams)


@dataclass(frozen=True)
class Weight:
    """A lot's weight as compared and shown: the estimate (`estimated`), or the measured weight with its day."""
    batch: object
    grams: Decimal
    estimated: bool
    measured_on: date
    how: str

    @property
    def text(self):
        from farm.templatetags.stock import grams
        from .dates import shown_date
        if self.estimated:
            return _('%(weight)s est.') % {'weight': grams(self.grams)}
        if self.how == WEIGHED:
            return _('%(weight)s weighed %(date)s') % {'weight': grams(self.grams), 'date': shown_date(self.measured_on)}
        return _('%(weight)s as stocked %(date)s') % {'weight': grams(self.grams), 'date': shown_date(self.measured_on)}


@dataclass(frozen=True)
class SizeMix:
    """Lots of one species in one unit further apart in weight than the species' size limit: the heaviest and the
    lightest (Weight), and the limit."""
    species: object
    heaviest: Weight
    lightest: Weight
    limit: Decimal

    @property
    def heavy(self):
        return self.heaviest.batch

    @property
    def light(self):
        return self.lightest.batch

    @property
    def heavy_g(self):
        return self.heaviest.grams

    @property
    def light_g(self):
        return self.lightest.grams

    @property
    def ratio(self):
        return self.heavy_g / self.light_g

    @property
    def ratio_shown(self):
        """The ratio rounded up to 0.01, so it never reads as the limit (two decimals at most) it is above."""
        return self.ratio.quantize(Decimal('0.01'), rounding=ROUND_CEILING)


def size_mixes(lots_of, batches, factors=None):
    """[SizeMix] of one unit: `lots_of` {batch id: [Lot]}, `batches` {batch id: Batch with its species}, `factors`
    {batch id: the estimate over the measured average} where the feeding walk credited feed since the measured point.
    Per species with a limit, the heaviest lot against the lightest; ordered by the species' name."""
    factors = factors or {}
    by_species = {}
    for batch_id, lots in lots_of.items():
        batch = batches[batch_id]
        factor = factors.get(batch_id)
        for lot in lots:
            if lot.fish <= 0:
                continue
            weight = Weight(batch, lot.avg_g * factor if factor else lot.avg_g, bool(factor), lot.measured_on, lot.how)
            by_species.setdefault(batch.species_id, (batch.species, []))[1].append(weight)
    found = []
    for species, weights in by_species.values():
        limit = species.max_weight_ratio
        if limit is None or len(weights) < 2:
            continue
        heaviest = max(weights, key=lambda weight: (weight.grams, weight.batch.code))
        lightest = min(weights, key=lambda weight: (weight.grams, weight.batch.code))
        if lightest.grams > 0 and heaviest.grams > limit * lightest.grams:
            found.append(SizeMix(species, heaviest, lightest, limit))
    return sorted(found, key=lambda mix: str(mix.species))

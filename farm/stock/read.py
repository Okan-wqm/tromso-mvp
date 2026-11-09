"""Reading the stock: the live lines out of the database, folded (farm/stock/fold.py), and what the
Production units page and the overview show per unit. Every figure is computed on read from the
ledger, so none can go stale (the source's density, capacity, FCR, SGR, last fed and days stocked
were stored and went wrong, STK-43 to STK-49).

Definitions (stock-db §4), for a unit u today:
- fish N = the sum of its live lines; biomass B = the fold's grams / 1000 (kg); average = B × 1000 / N (g);
- density = B / V, V the water volume, else the volume (m³); capacity = 100 × B / max biomass (%);
- days stocked = today − the start of the current stay of its batches (the earliest);
- survival = 100 × (1 − deaths / fish in), losses = deaths + culls, both over the current stay
  (owner decision Q2: survival counts deaths only);
- last weighing = the latest weighing of the current stay.
FCR, the last feeding and the feed rate are read from the feeding records with the same ledger
(farm/feeding/read.py)."""
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import NamedTuple

from django.db.models import Q, Sum

from farm.models import Batch, Site, StockMovement, Tank
from farm.models.feeding import FeedTarget

from .fold import Line, Op, Share, fold
from .sizes import Lots, size_mixes

HUNDRED = Decimal(100)
DAY = timedelta(days=1)


def ledger(batch_ids, include_op=None):
    """The live lines of these batches, as the fold reads them. Every operation belongs to one batch,
    so the lines of an operation all come with its batch. `include_op`: an operation whose lines count although it is
    voided (the timeline before its void, farm/stock/services.py)."""
    live = Q(operation__is_deleted=False) | Q(operation_id=include_op) if include_op else Q(operation__is_deleted=False)
    rows = list(StockMovement.objects.filter(live, batch_id__in=batch_ids).values_list(
        'id', 'operation_id', 'operation__kind', 'operation__date', 'unit_id', 'batch_id', 'kind', 'count_delta',
        'avg_weight_g', 'pair', 'measured_weight_kg', 'reason', 'batch__species__cleaner_fish_type'))
    first = {}
    for row in rows:
        first[row[1]] = min(first.get(row[1], row[0]), row[0])
    ops = {}
    lines = []
    for line_id, op_id, op_kind, op_date, unit_id, batch_id, kind, delta, weight, pair, measured, reason, cleaner \
            in rows:
        op = ops.setdefault(op_id, Op(op_id, op_kind, op_date, first[op_id]))
        lines.append(Line(line_id, op, unit_id, batch_id, kind, delta, weight, pair, measured, reason, bool(cleaner)))
    return lines


def moved_grams(batch_ids):
    """{line id: the grams it moved} for every live line of these batches: what the fold took out (a harvest
    line's book kilos, beside its weighed kilos) or brought in; None for a weighing, which sets the grams."""
    moved = {}
    fold(ledger(batch_ids), on_line=lambda line, share, grams: moved.__setitem__(line.id, grams))
    return moved


def share_on(unit_id, batch_id, day):
    """The batch in the unit at the end of `day` (after every operation dated that day or before)."""
    lines = [line for line in ledger([batch_id]) if line.op.date <= day]
    return fold(lines).get((unit_id, batch_id)) or Share()


def mixed(species_ids, cleaner, sea):
    """Whether these species may not share a unit: a unit holds one species, except that on a sea site (`sea`)
    cleaner fish (species ids in `cleaner`) may join its production species, whose species stays one (owner
    decision Q1 with D-1; a hatchery's tank holds one, as the smolt report has one species per tank)."""
    if not sea:
        return len(species_ids) > 1
    return len(set(species_ids) - set(cleaner)) > 1


def sea_units(unit_ids):
    """The ids of these units on a sea site (Site type sea cage), deleted units included."""
    return set(Tank.all_objects.filter(pk__in=unit_ids, production_department__site__type=Site.Type.SEA_CAGE)
               .values_list('pk', flat=True))


def unit_counts(unit_ids):
    """{unit id: fish in it now} from the live lines (units without lines are left out)."""
    rows = (StockMovement.objects.filter(unit_id__in=unit_ids, operation__is_deleted=False)
            .values('unit_id').annotate(fish=Sum('count_delta')))
    return {row['unit_id']: row['fish'] for row in rows}


def fish_of_batch(batch_id):
    """{unit id: fish of the batch in it now} from the live lines (units it has left are left out)."""
    rows = (StockMovement.objects.filter(batch_id=batch_id, operation__is_deleted=False)
            .values('unit_id').annotate(fish=Sum('count_delta')).filter(fish__gt=0))
    return {row['unit_id']: row['fish'] for row in rows}


def batches_in_stock():
    """The ids of the batches with fish in a unit now."""
    rows = (StockMovement.objects.filter(operation__is_deleted=False).values('batch_id')
            .annotate(fish=Sum('count_delta')).filter(fish__gt=0))
    return {row['batch_id'] for row in rows}


def batches_ever_in(unit_ids):
    """The ids of every batch that ever had a live line in these units."""
    return set(StockMovement.objects.filter(unit_id__in=unit_ids, operation__is_deleted=False)
               .values_list('batch_id', flat=True).distinct())


class Presence:
    """Which batch had fish in which unit on which day, from the counts of the live lines alone (no fold:
    a count is the sum of the lines up to a day). A batch counts on a day when it had fish there at the end
    of that day or of the day before, so fish stocked, moved or harvested that day count. The water judges
    a sample for the species present (farm/water/read.py), the health module finds the batches a treatment
    reached and the units a batch was in (farm/health/withdrawal.py).

    Build it with `of_units` (every batch that was in these units) or `of_batches` (every unit these
    batches were in)."""

    def __init__(self, rows):
        """`rows`: (unit id, batch id, date, count delta) of live lines."""
        changes = defaultdict(lambda: defaultdict(int))
        for unit_id, batch_id, day, delta in rows:
            changes[(unit_id, batch_id)][day] += delta
        self.timelines = {}                          # (unit, batch) -> (days, fish at the end of each)
        self.units = defaultdict(set)                # batch -> the units it was ever in
        self.batches = defaultdict(set)              # unit -> the batches ever in it
        for (unit_id, batch_id), by_day in changes.items():
            days, counts, running = [], [], 0
            for day in sorted(by_day):
                running += by_day[day]
                days.append(day)
                counts.append(running)
            self.timelines[(unit_id, batch_id)] = (days, counts)
            self.units[batch_id].add(unit_id)
            self.batches[unit_id].add(batch_id)

    @classmethod
    def _of(cls, lines):
        return cls(lines.values_list('unit_id', 'batch_id', 'operation__date', 'count_delta'))

    @classmethod
    def of_units(cls, unit_ids):
        return cls._of(StockMovement.objects.filter(unit_id__in=unit_ids, operation__is_deleted=False))

    @classmethod
    def of_batches(cls, batch_ids):
        return cls._of(StockMovement.objects.filter(batch_id__in=batch_ids, operation__is_deleted=False))

    def count_at_end(self, unit_id, batch_id, day):
        """The fish of the batch in the unit after every line dated `day` or before."""
        timeline = self.timelines.get((unit_id, batch_id))
        if timeline is None:
            return 0
        days, counts = timeline
        index = bisect_right(days, day) - 1
        return counts[index] if index >= 0 else 0

    def present(self, unit_id, batch_id, day):
        return self.count_at_end(unit_id, batch_id, day) > 0 or self.count_at_end(unit_id, batch_id, day - DAY) > 0

    def batches_in(self, unit_id, day):
        """The batches with fish in the unit on `day`."""
        return {batch_id for batch_id in self.batches.get(unit_id, ()) if self.present(unit_id, batch_id, day)}

    def units_of(self, batch_id, day):
        """The units the batch had fish in on `day`."""
        return {unit_id for unit_id in self.units.get(batch_id, ()) if self.present(unit_id, batch_id, day)}

    def present_between(self, unit_id, batch_id, first, last):
        """Whether the batch had fish in the unit on any day from `first` to `last`, both included. The count
        changes only on the days of its lines, so those days and `first` are the only ones to look at."""
        if first > last:
            return False
        if self.present(unit_id, batch_id, first):
            return True
        days, counts = self.timelines.get((unit_id, batch_id), ((), ()))
        return any(first < day <= last and count > 0 for day, count in zip(days, counts))


@dataclass
class BatchShare:
    """A batch in a unit now, from the fold."""
    batch: Batch
    count: int
    grams: Decimal
    since: object
    last_weighed: object
    fish_in: int
    deaths: int
    culls: int
    unit_count: int = 0      # the unit's fish of its kind (production or cleaner fish), for the share by count
    siblings: int = 1        # the batches of its kind in the unit, itself included
    lots: list = field(default_factory=list)   # sizes.Lot: its fish by size (a grading's classes kept apart)

    @property
    def cleaner(self):
        """Cleaner fish (a cleaner-fish species), beside the unit's production fish (D-1)."""
        return self.batch.species.is_cleaner_fish

    @property
    def target(self):
        return FeedTarget.CLEANER_FISH if self.cleaner else FeedTarget.PRODUCTION

    @property
    def biomass_kg(self):
        return self.grams / 1000

    @property
    def avg_weight_g(self):
        return self.grams / self.count

    @property
    def percent_of_unit(self):
        return HUNDRED * self.count / self.unit_count

    @property
    def survival(self):
        return HUNDRED * (1 - Decimal(self.deaths) / self.fish_in) if self.fish_in else None

    @property
    def losses(self):
        return self.deaths + self.culls


@dataclass
class UnitStock:
    """The fish in one unit now: every batch in it (`shares`), and the unit's figures, which are those of its
    production fish (`counted`). Cleaner fish beside them (D-1) are not in a unit's fish, biomass, density or
    capacity (D-2): they are their own figures, `of(FeedTarget.CLEANER_FISH)`."""
    unit: Tank
    shares: list = field(default_factory=list)
    target: str = FeedTarget.PRODUCTION

    @property
    def counted(self):
        """The shares the figures are of: the production fish, or the cleaner fish of `of`."""
        return [share for share in self.shares if share.target == self.target]

    @property
    def cleaner(self):
        """The cleaner fish's shares beside the production fish (D-1)."""
        return [share for share in self.shares if share.cleaner]

    @property
    def cleaner_stock(self):
        """The cleaner fish as a unit's figures of their own (count, biomass, average)."""
        return self.of(FeedTarget.CLEANER_FISH)

    def of(self, target):
        """The unit's fish of one kind, production or cleaner fish, with their own figures."""
        return UnitStock(self.unit, [share for share in self.shares if share.target == target], target)

    @property
    def count(self):
        return sum(share.count for share in self.counted)

    @property
    def grams(self):
        return sum((share.grams for share in self.counted), Decimal(0))

    @property
    def biomass_kg(self):
        return self.grams / 1000

    @property
    def avg_weight_g(self):
        return self.grams / self.count if self.count else None

    @property
    def volume_m3(self):
        """The volume the fish live in: the water volume, else the volume."""
        return self.unit.water_volume_m3 or self.unit.volume_m3

    @property
    def density(self):
        volume = self.volume_m3
        return self.biomass_kg / volume if volume else None

    @property
    def capacity(self):
        maximum = self.unit.max_biomass_kg
        return HUNDRED * self.biomass_kg / maximum if maximum else None

    @property
    def over_capacity(self):
        return self.capacity is not None and self.capacity > HUNDRED

    @property
    def since(self):
        """The start of the current stay of the unit's fish: the production fish's, the cleaner fish's when a unit
        holds only them."""
        return min((share.since for share in self.counted or self.shares), default=None)

    @property
    def fish_in(self):
        return sum(share.fish_in for share in self.counted)

    @property
    def deaths(self):
        return sum(share.deaths for share in self.counted)

    @property
    def culls(self):
        return sum(share.culls for share in self.counted)

    @property
    def losses(self):
        return self.deaths + self.culls

    @property
    def survival(self):
        return HUNDRED * (1 - Decimal(self.deaths) / self.fish_in) if self.fish_in else None

    @property
    def mortality(self):
        return HUNDRED * Decimal(self.deaths) / self.fish_in if self.fish_in else None

    @property
    def last_weighed(self):
        return max((share.last_weighed for share in self.counted if share.last_weighed), default=None)

    @property
    def batches(self):
        return [share.batch for share in self.counted]

    @property
    def size_mixes(self):
        """[sizes.SizeMix] of every lot in the unit (production and cleaner fish, each against its own species) at its
        measured weight, with its day: what Production units, which shows the measured averages, warns about."""
        return self.size_mixes_at()

    def size_mixes_at(self, factors=None):
        """The same at the feeding walk's estimates where feed was credited (`factors`: batch id -> the estimate over
        the measured average, sizes.size_mixes): what the meal board, which shows the estimates, warns about."""
        return size_mixes({share.batch.pk: share.lots for share in self.shares},
                          {share.batch.pk: share.batch for share in self.shares}, factors)

    def days(self, today):
        return (today - self.since).days if self.since else None


def stock_of(units):
    """{unit id: UnitStock} of the units that hold fish now; a unit without fish is left out."""
    unit_ids = [unit.pk for unit in units]
    present = (StockMovement.objects.filter(unit_id__in=unit_ids, operation__is_deleted=False)
               .values('batch_id').annotate(fish=Sum('count_delta')).filter(fish__gt=0))
    batch_ids = {row['batch_id'] for row in present}
    if not batch_ids:
        return {}
    lots = Lots()
    return _unit_stocks(units, fold(ledger(batch_ids), before=lots.before, on_line=lots.line), batch_ids, lots)


def stock_on(units, day):
    """{unit id: UnitStock} of the units that held fish at the end of `day` (after every operation dated that day
    or before): the fold of every batch ever in them, cut at `day`. A month's last day gives its closing stock, the
    day before it its opening stock. A unit without fish then is left out."""
    batch_ids = batches_ever_in([unit.pk for unit in units])
    lines = [line for line in ledger(batch_ids) if line.op.date <= day]
    lots = Lots()
    return _unit_stocks(units, fold(lines, before=lots.before, on_line=lots.line), batch_ids, lots) if lines else {}


def _unit_stocks(units, shares, batch_ids, lots=None):
    """{unit id: UnitStock} of `units` from the fold's shares: each unit's batches with fish, oldest stay first."""
    batches = Batch.all_objects.select_related('species').in_bulk(batch_ids)
    by_id = {unit.pk: unit for unit in units}
    stock = {}
    for (unit_id, batch_id), share in shares.items():
        if share.count and unit_id in by_id:
            stock.setdefault(unit_id, UnitStock(by_id[unit_id])).shares.append(BatchShare(
                batches[batch_id], share.count, share.grams, share.since, share.last_weighed, share.fish_in,
                share.deaths, share.culls, lots=lots.of.get((unit_id, batch_id), []) if lots else []))
    for unit_stock in stock.values():
        kinds = {target: unit_stock.of(target) for target in FeedTarget.values}
        unit_stock.shares.sort(key=lambda share: (share.cleaner, share.since, share.batch.code))
        for share in unit_stock.shares:
            share.unit_count = kinds[share.target].count
            share.siblings = len(kinds[share.target].shares)
    return stock


class InPeriod(NamedTuple):
    """What a monthly or weekly report reads of its units: the stock at the end of the day before the period
    (`opening`) and at its last day (`closing`), as `stock_on` gives them, and the live lines dated in it (`lines`)."""
    opening: dict
    closing: dict
    lines: list


def in_period(units, first, last):
    """The InPeriod of `units` from the day `first` to the day `last`, both included."""
    return InPeriod(stock_on(units, first - DAY), stock_on(units, last), movements(units, first, last))


@dataclass(frozen=True)
class Movement:
    """A live ledger line of a unit in a period, as the reports read it: what it did, its reason, the grams the fold
    moved with it (None for a weighing, which sets the grams instead), and for a transfer the unit at its other end."""
    line_id: int
    operation_id: object
    operation_kind: str
    date: object
    unit_id: object
    batch_id: object
    kind: str
    count: int                  # count_delta: + into the unit, - out of it, 0 for a weighing
    reason: str
    grams: Decimal = None
    measured_weight_kg: Decimal = None
    other_unit_id: object = None

    @property
    def kilos(self):
        """The weighed kilos when the line has them (dead fish, a harvest's catch), else the fold's."""
        if self.measured_weight_kg is not None:
            return self.measured_weight_kg
        return None if self.grams is None else self.grams / 1000


def movements(units, first, last):
    """[Movement] of the live lines in `units` dated from `first` to `last` (both included), in the fold's order. The
    grams come from folding every line of the batches ever in the units up to `last`, so a line moves exactly what
    the stock says it moved; a transfer's other end is the line of the same operation with the same pair."""
    unit_ids = {unit.pk for unit in units}
    lines = [line for line in ledger(batches_ever_in(unit_ids)) if line.op.date <= last]
    grams = {}
    fold(lines, on_line=lambda line, share, moved: grams.__setitem__(line.id, moved))
    ends = {}
    for line in lines:
        if line.pair is not None:
            ends.setdefault((line.op.id, line.pair), []).append(line)
    found = []
    for line in sorted(lines, key=lambda line: (line.op.date, line.op.seq, line.id)):
        if line.unit_id not in unit_ids or line.op.date < first:
            continue
        other = None
        if line.pair is not None:
            other = next((end.unit_id for end in ends[(line.op.id, line.pair)] if end.id != line.id), None)
        found.append(Movement(line.id, line.op.id, line.op.kind, line.op.date, line.unit_id, line.batch_id, line.kind,
                              line.count_delta, line.reason, grams.get(line.id), line.measured_weight_kg, other))
    return found

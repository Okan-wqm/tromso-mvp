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

from django.db.models import Sum

from farm.models import Batch, StockMovement, Tank

from .fold import Line, Op, Share, fold

HUNDRED = Decimal(100)
DAY = timedelta(days=1)


def ledger(batch_ids):
    """The live lines of these batches, as the fold reads them. Every operation belongs to one batch,
    so the lines of an operation all come with its batch."""
    rows = list(StockMovement.objects.filter(batch_id__in=batch_ids, operation__is_deleted=False).values_list(
        'id', 'operation_id', 'operation__kind', 'operation__date', 'unit_id', 'batch_id', 'kind', 'count_delta',
        'avg_weight_g', 'pair', 'measured_weight_kg'))
    first = {}
    for row in rows:
        first[row[1]] = min(first.get(row[1], row[0]), row[0])
    ops = {}
    lines = []
    for line_id, op_id, op_kind, op_date, unit_id, batch_id, kind, delta, weight, pair, measured in rows:
        op = ops.setdefault(op_id, Op(op_id, op_kind, op_date, first[op_id]))
        lines.append(Line(line_id, op, unit_id, batch_id, kind, delta, weight, pair, measured))
    return lines


def share_on(unit_id, batch_id, day):
    """The batch in the unit at the end of `day` (after every operation dated that day or before)."""
    lines = [line for line in ledger([batch_id]) if line.op.date <= day]
    return fold(lines).get((unit_id, batch_id)) or Share()


def unit_counts(unit_ids):
    """{unit id: fish in it now} from the live lines (units without lines are left out)."""
    rows = (StockMovement.objects.filter(unit_id__in=unit_ids, operation__is_deleted=False)
            .values('unit_id').annotate(fish=Sum('count_delta')))
    return {row['unit_id']: row['fish'] for row in rows}


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
    unit_count: int = 0      # every fish in the unit, for the share by count

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
    """The fish in one unit now."""
    unit: Tank
    shares: list = field(default_factory=list)

    @property
    def count(self):
        return sum(share.count for share in self.shares)

    @property
    def grams(self):
        return sum((share.grams for share in self.shares), Decimal(0))

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
        return min((share.since for share in self.shares), default=None)

    @property
    def fish_in(self):
        return sum(share.fish_in for share in self.shares)

    @property
    def deaths(self):
        return sum(share.deaths for share in self.shares)

    @property
    def culls(self):
        return sum(share.culls for share in self.shares)

    @property
    def survival(self):
        return HUNDRED * (1 - Decimal(self.deaths) / self.fish_in) if self.fish_in else None

    @property
    def mortality(self):
        return HUNDRED * Decimal(self.deaths) / self.fish_in if self.fish_in else None

    @property
    def last_weighed(self):
        return max((share.last_weighed for share in self.shares if share.last_weighed), default=None)

    @property
    def batches(self):
        return [share.batch for share in self.shares]

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
    shares = fold(ledger(batch_ids))
    batches = Batch.all_objects.select_related('species').in_bulk(batch_ids)
    by_id = {unit.pk: unit for unit in units}
    stock = {}
    for (unit_id, batch_id), share in shares.items():
        if share.count and unit_id in by_id:
            stock.setdefault(unit_id, UnitStock(by_id[unit_id])).shares.append(BatchShare(
                batches[batch_id], share.count, share.grams, share.since, share.last_weighed, share.fish_in,
                share.deaths, share.culls))
    for unit_stock in stock.values():
        total = unit_stock.count
        unit_stock.shares.sort(key=lambda share: (share.since, share.batch.code))
        for share in unit_stock.shares:
            share.unit_count = total
    return stock



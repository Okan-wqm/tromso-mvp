"""The stock as the ledger says it: one pure, date-ordered fold of the live lines (stock-db §6.3).

The count of a batch in a unit is the sum of its lines; the biomass needs the order of events, so it is
this one function over the lines, ordered by the operation's date, then by the order the operations
were entered (the first line id of each), and inside an operation removals first, then weighings,
then arrivals. Nothing here touches the database: the stock service, the page and check_stock all
fold the same way, and the feeding walk (farm/feeding/fold.py) reads the same fold through its hooks.

The rules (the source got each of these wrong somewhere, STK-14, STK-24, STK-29):
- fish leave at the share's own average on that day, so the average does not move;
- fish of a stated weight (selected fish) leave with that weight, and may not weigh as much as the
  whole share: weigh the unit first;
- the last fish out take whatever the book holds, so no biomass is left without fish;
- a weighing sets the share's biomass to its count times the measured average;
- fish moved between units arrive with exactly the grams that left the source;
- a grading is a weighing of the whole lot: the graded fish carry their measured weight and the
  fish that stay get their own measured average (a weighing line of the same operation).
Grams are Decimals at full precision, never rounded here; the page rounds for display."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from itertools import groupby

from farm.models.stock import MovementKind, OperationKind

ZERO = Decimal(0)


@dataclass(frozen=True)
class Op:
    """An operation as the fold needs it."""
    id: object
    kind: str
    date: date
    seq: int          # its first line id: the order of entry, which orders operations within a day


@dataclass(frozen=True)
class Line:
    id: int
    op: Op
    unit_id: object
    batch_id: object
    kind: str
    count_delta: int
    avg_weight_g: Decimal = None
    pair: int = None
    # A weighed total beside the book (dead fish, a harvest's catch): never in the fold, read by the
    # feeding walk for the biomass removed.
    measured_weight_kg: Decimal = None
    # The line's reason (a mortality's cause, a cull's reason): never in the fold, read by the reports.
    reason: str = ''


class StockError(Exception):
    """The lines describe something that cannot happen; `line` is where it happens."""
    SHORT = 'short'                        # more fish out than the batch has in the unit that day
    NOTHING_TO_WEIGH = 'nothing_to_weigh'  # a weighing where the batch has no fish that day
    OVER_BOOK = 'over_book'                # selected fish weigh as much as the whole share or more
    NO_AVERAGE = 'no_average'              # fish added at the share's average where it has none
    UNPAIRED = 'unpaired'                  # a transfer in without its transfer out
    NO_BIOMASS = 'no_biomass'              # fish left with no biomass (a grading without the remainder's weight)

    def __init__(self, reason, line, available=0):
        super().__init__(reason)
        self.reason, self.line, self.available = reason, line, available


@dataclass
class Share:
    """One batch in one unit. `since` is the start of the current stay (the day the batch last arrived
    in the unit while it had none of it there); the counters run from then."""
    count: int = 0
    grams: Decimal = ZERO
    since: date = None
    last_weighed: date = None
    fish_in: int = 0
    deaths: int = 0
    culls: int = 0

    @property
    def biomass_kg(self):
        return self.grams / 1000

    @property
    def avg_weight_g(self):
        return self.grams / self.count if self.count else None


def _stage(line):
    if line.count_delta < 0:
        return 0
    return 1 if line.kind == MovementKind.WEIGHING else 2


def operations(lines):
    """[(op, its lines)] in the order they happened."""
    ordered = sorted(lines, key=lambda line: (line.op.date, line.op.seq, _stage(line), line.id))
    return [(op, list(group)) for op, group in groupby(ordered, key=lambda line: line.op)]


def _take(share, k, line):
    """Takes `k` fish out of the share; returns the grams that left."""
    if k > share.count:
        raise StockError(StockError.SHORT, line, share.count)
    weight = line.avg_weight_g
    if weight is not None and line.op.kind == OperationKind.GRADING:
        out = k * weight                        # graded fish carry their measured weight
    elif k == share.count:
        out = share.grams                       # the last fish take what the book holds
    elif weight is None:
        out = share.grams * k / share.count     # at the share's average
    else:
        out = k * weight                        # selected fish of a stated weight
        if out >= share.grams:
            raise StockError(StockError.OVER_BOOK, line)
    share.count -= k
    share.grams = share.grams - out if share.count else ZERO
    return out


def _arriving(share, line, moved):
    """The grams of the fish a line brings in."""
    if line.kind == MovementKind.TRANSFER_IN:
        if line.pair not in moved:
            raise StockError(StockError.UNPAIRED, line)
        return moved[line.pair]
    if line.avg_weight_g is not None:
        return line.count_delta * line.avg_weight_g
    if not share.count:
        raise StockError(StockError.NO_AVERAGE, line)
    return share.grams * line.count_delta / share.count


def fold(lines, observe=None, *, before=None, on_line=None):
    """{(unit id, batch id): Share} after every line. `observe(op, shares)` is called after each
    operation, with the shares as they are then (the stock service checks capacity and species there),
    `before(op, shares)` before it, and `on_line(line, share, grams)` after each line with the grams it
    moved: the grams that left, or came in (None for a weighing, which sets the share's grams). Raises
    StockError at the first line that cannot happen."""
    shares = {}
    for op, op_lines in operations(lines):
        if before is not None:
            before(op, shares)
        moved = {}
        touched = []
        for line in op_lines:
            share = shares.setdefault((line.unit_id, line.batch_id), Share())
            touched.append((share, line))
            k = line.count_delta
            grams = None
            if k < 0:
                out = grams = _take(share, -k, line)
                if line.kind == MovementKind.MORTALITY:
                    share.deaths -= k
                elif line.kind == MovementKind.CULL:
                    share.culls -= k
                elif line.kind == MovementKind.TRANSFER_OUT:
                    moved[line.pair] = out
            elif line.kind == MovementKind.WEIGHING:
                if not share.count:
                    raise StockError(StockError.NOTHING_TO_WEIGH, line)
                share.grams = share.count * line.avg_weight_g
                share.last_weighed = op.date
            else:
                grams = _arriving(share, line, moved)
                if not share.count:
                    share.since, share.last_weighed, share.fish_in, share.deaths, share.culls = op.date, None, 0, 0, 0
                share.count += k
                share.grams += grams
                share.fish_in += k
            if on_line is not None:
                on_line(line, share, grams)
        for share, line in touched:
            if share.count and share.grams <= 0:
                raise StockError(StockError.NO_BIOMASS, line)
        if observe:
            observe(op, shares)
    return shares

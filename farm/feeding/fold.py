"""Feed against the stock's timeline: one walk over the stock fold (farm/stock/fold.py, through its hooks)
that splits each day's feed among the batches in the unit and keeps the measured points of every share,
from which FCR is read (farm/feeding/read.py). Pure: nothing here touches the database. The page, the
stock service's check and check_stock walk the same way (feeding-records §4.7, §4.8).

Feed is never written into the stock: the fold's grams are the book, measured weights only, and the
walk only reads them (the source added fed kg / expected FCR to the biomass, so its FCR met the target
by construction, FDR-19).

- A feeding is for the unit's production fish or for the cleaner fish beside them (its target, D-1): it
  needs fish of its target in its unit at the start of its day (after every operation dated before it) or
  at its end (after every operation dated that day); one without is an orphan.
- Its feed goes to the batches of its target in the unit at the start of the day, split by their book biomass
  then; when the unit held none at the start (stocked that day), by the biomass at the end of the day.
  Decimals at full precision, so the parts of a record add up to it; only the page rounds.
- A share's measured points in a stay (the time a batch is in a unit without a break): its stocking, fish
  graded into it while it had none (they carry their measured weight), a weighing (a grading's
  remainder too), and the harvest that empties it. Fish moved in by a plain transfer arrive at book
  grams, so they start no point. At each point the walk keeps the book biomass B and, since the stay
  began, the biomass removed R (dead and culled fish at their weighed kilos when weighed, a harvest at
  its weighed kilos, the rest at the grams the fold took), the part of R that is lost fish D (mortality,
  cull, a count adjustment down: escape or unaccounted loss) and the biomass added A (fish that came in
  during the stay)."""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from farm.models.feeding import FeedTarget
from farm.models.stock import MovementKind, OperationKind
from farm.stock.fold import fold

ZERO = Decimal(0)
LOST = (MovementKind.MORTALITY, MovementKind.CULL, MovementKind.ADJUSTMENT)


@dataclass(frozen=True)
class Feeding:
    """A feeding record as the walk needs it; `meals` and `order` (its place among the day's records: the time,
    then the order of entry) for the projected growth; `target`, the fish it is for (D-1)."""
    id: object
    unit_id: object
    date: date
    amount_kg: Decimal
    meals: int = None
    order: tuple = ()
    target: str = FeedTarget.PRODUCTION


class PointKind:
    START = 'start'          # stocked, or graded into the unit while the batch had no fish there
    WEIGHING = 'weighing'    # a weighing, or the fish that stay at a grading
    CLOSE = 'close'          # the harvest that empties the unit of the batch


@dataclass(frozen=True)
class Point:
    """A measured point of a share: the book biomass then, and the running sums of its stay (kg); the fish it had
    then, and the ledger line that measured it (the one reader of measured points, farm/feeding/read.py
    `measured_points`, reads the weight's source and sample from that line)."""
    kind: str
    day: date
    biomass_kg: Decimal
    removed_kg: Decimal
    lost_kg: Decimal
    added_kg: Decimal
    fish: int = None
    line_id: object = None

    @property
    def avg_weight_g(self):
        return self.biomass_kg * 1000 / self.fish if self.fish else None


@dataclass
class Stay:
    """A batch in a unit from the day it came in while it had none there: its measured points and the
    feed it was given, per day (kg). The sums run in grams."""
    since: date
    points: list = field(default_factory=list)
    feed: dict = field(default_factory=dict)
    removed: Decimal = ZERO
    lost: Decimal = ZERO
    added: Decimal = ZERO

    def fed_kg(self, start=None, end=None, closing=False):
        """The feed of the days from `start` up to, not including, `end` (including it when `closing`)."""
        return sum((kilos for day, kilos in self.feed.items()
                    if (start is None or day >= start)
                    and (end is None or day < end or closing and day == end)), ZERO)


def ratio(feed, gain):
    return feed / gain if feed > 0 and gain > 0 else None


@dataclass(frozen=True)
class Window:
    """A share's stay between two measured points: from its first to its last weighing (or the harvest that closed
    it) for FCR, or between two consecutive points for a weighing's realised FCR (farm/feeding/projection.py)."""
    start: object
    end: object
    feed_kg: Decimal

    @property
    def gain_kg(self):
        """Biological gain: the biomass grown, the fish removed meanwhile credited, those added not."""
        start, end = self.start, self.end
        return (end.biomass_kg - start.biomass_kg + (end.removed_kg - start.removed_kg)
                - (end.added_kg - start.added_kg))

    @property
    def economic_gain_kg(self):
        """Economic gain: the biological gain less the fish lost (dead, culled, escaped, unaccounted)."""
        return self.gain_kg - (self.end.lost_kg - self.start.lost_kg)

    @property
    def biological(self):
        return ratio(self.feed_kg, self.gain_kg)


def of_target(grams, cleaner, target):
    """{batch id: grams} of the batches of `target` among `grams`: the cleaner fish (batch ids in `cleaner`), or the
    production fish."""
    wanted = target == FeedTarget.CLEANER_FISH
    return {batch_id: value for batch_id, value in grams.items() if (batch_id in cleaner) == wanted}


@dataclass(frozen=True)
class Day:
    """A unit on a day: the grams of each batch with fish at the start of the day and at its end; `cleaner`, the
    batches of a cleaner-fish species among them. Its figures are of every batch; `of(target)` is the day of the
    production fish or of the cleaner fish alone (a feeding's, the feed rate's, a sea-lice count's)."""
    start: dict
    end: dict
    cleaner: frozenset = frozenset()

    def of(self, target):
        return Day(of_target(self.start, self.cleaner, target), of_target(self.end, self.cleaner, target),
                   self.cleaner)

    @property
    def production(self):
        return self.of(FeedTarget.PRODUCTION)

    @property
    def weights(self):
        """What the day's feed is split by: the start, or the end when the unit was empty at the start."""
        return self.start or self.end

    @property
    def has_fish(self):
        return bool(self.weights)

    @property
    def biomass_kg(self):
        """The book biomass the day's feed rate is read against (kg); 0 when the unit held no fish."""
        return sum(self.weights.values(), ZERO) / 1000


@dataclass
class Walk:
    shares: dict = field(default_factory=dict)                  # the fold: (unit, batch) -> Share
    stays: dict = field(default_factory=lambda: defaultdict(list))   # (unit, batch) -> [Stay], oldest first
    days: dict = field(default_factory=dict)                    # (unit, day) -> Day, for the days asked
    split: dict = field(default_factory=dict)                   # feeding id -> {batch id: kg}
    orphans: list = field(default_factory=list)                 # feedings without fish, earliest first
    lines: list = field(default_factory=list)                   # the ledger lines it folded, for a reader of the same
                                                                # fish that would else read them again (last_fed_of)


class _Walker:
    def __init__(self, feedings, days, observe, projector=None, cleaner=frozenset()):
        self.result = Walk()
        self.cleaner = cleaner
        self.observe = observe
        self.projector = projector
        self.feedings = defaultdict(list)
        wanted = defaultdict(set)
        for feeding in feedings:
            self.feedings[(feeding.unit_id, feeding.date)].append(feeding)
            wanted[feeding.date].add(feeding.unit_id)
        for unit_id, day in days:
            wanted[day].add(unit_id)
        self.wanted = wanted
        self.order = sorted(wanted)
        self.started = self.ended = 0    # the days whose start, and whose end, are read
        self.start = {}
        self.pending = {}                # points of the operation being folded: (unit, batch) -> (kind, line id)

    # ---- the days asked for: their start and their end ------------------------------------------
    def capture(self, shares, until=None):
        """Reads every asked day whose start (all operations before it folded) and end (all operations
        of it folded) are reached when the next operation is dated `until` (None: the fold is done). The shares
        do not change while it reads, so they are grouped by unit once per call (`_by_unit`), not scanned whole for
        every unit of every day."""
        grouped = None
        while self.started < len(self.order) and (until is None or self.order[self.started] <= until):
            day = self.order[self.started]
            grouped = _by_unit(shares) if grouped is None else grouped
            for unit_id in self.wanted[day]:
                self.start[(unit_id, day)] = present = _present(grouped.get(unit_id, {}), unit_id)
                for feeding in self.feedings.get((unit_id, day), ()):
                    self._allocate(feeding, day, of_target(present, self.cleaner, feeding.target))
            self.started += 1
        while self.ended < len(self.order) and (until is None or self.order[self.ended] < until):
            day = self.order[self.ended]
            grouped = _by_unit(shares) if grouped is None else grouped
            for unit_id in self.wanted[day]:
                own = grouped.get(unit_id, {})
                start = self.start.pop((unit_id, day))
                end = _present(own, unit_id)
                self.result.days[(unit_id, day)] = Day(start, end, self.cleaner)
                for feeding in self.feedings.get((unit_id, day), ()):
                    if feeding.id in self.result.split:
                        continue
                    grams = of_target(end, self.cleaner, feeding.target)
                    if grams:
                        self._allocate(feeding, day, grams)
                    else:
                        self.result.orphans.append(feeding)
                if self.projector is not None and end:
                    self.projector.day(unit_id, day, own, self.feedings.get((unit_id, day), ()), self.result.split)
            self.ended += 1

    def _allocate(self, feeding, day, grams):
        """Splits the feeding among `grams` (the batches of its target with fish then) by their book biomass; nothing
        when there are none."""
        if not grams:
            return
        total = sum(grams.values(), ZERO)
        parts = {batch_id: feeding.amount_kg * share / total for batch_id, share in grams.items()}
        self.result.split[feeding.id] = parts
        for batch_id, kilos in parts.items():
            stay = self.result.stays[(feeding.unit_id, batch_id)][-1]
            stay.feed[day] = stay.feed.get(day, ZERO) + kilos

    # ---- the fold's hooks ----------------------------------------------------------------------
    def before(self, op, shares):
        self.capture(shares, op.date)

    def line(self, line, share, grams):
        key = (line.unit_id, line.batch_id)
        k = line.count_delta
        if line.kind == MovementKind.WEIGHING:
            self.pending[key] = (PointKind.WEIGHING, line.id)
        elif k > 0 and share.count == k:          # the batch had no fish here: a new stay
            self.result.stays[key].append(Stay(line.op.date))
            if line.kind == MovementKind.INPUT or (line.kind == MovementKind.TRANSFER_IN
                                                   and line.op.kind == OperationKind.GRADING):
                self.pending[key] = (PointKind.START, line.id)
        elif k > 0:
            self.result.stays[key][-1].added += grams
        else:
            stay = self.result.stays[key][-1]
            removed = grams if line.measured_weight_kg is None else line.measured_weight_kg * 1000
            stay.removed += removed
            if line.kind in LOST:
                stay.lost += removed
            if line.kind == MovementKind.HARVEST:
                self.pending[key] = (PointKind.CLOSE, line.id)
        if self.projector is not None:
            self.projector.line(line, share, grams)

    def after(self, op, shares):
        for key, (kind, line_id) in self.pending.items():
            share = shares[key]
            if kind == PointKind.CLOSE and share.count:
                continue                           # a harvest that leaves fish: no measured point
            stay = self.result.stays[key][-1]
            stay.points.append(Point(kind, op.date, share.grams / 1000, stay.removed / 1000, stay.lost / 1000,
                                     stay.added / 1000, share.count, line_id))
            if self.projector is not None:
                self.projector.weighed(key, stay, stay.points[-1])
        self.pending.clear()
        if self.projector is not None:
            self.projector.end_op()
        if self.observe is not None:
            self.observe(op, shares)


def _present(shares, unit_id):
    """{batch id: grams} of the batches with fish in the unit now."""
    return {batch_id: share.grams for (unit, batch_id), share in shares.items() if unit == unit_id and share.count}


def _by_unit(shares):
    """{unit id: {(unit id, batch id): Share}} of the fold's shares, each unit's in the fold's own order: what a day of
    one unit reads (`_present`, Projector.day), without scanning every unit's shares."""
    grouped = defaultdict(dict)
    for key, share in shares.items():
        grouped[key[0]][key] = share
    return grouped


def walk(lines, feedings=(), days=(), observe=None, projector=None):
    """Folds `lines` (farm/stock/fold.py) and walks `feedings` (Feeding) along: their split (each among the batches
    of its target, the lines saying which batches are cleaner fish), the stays
    with their measured points and feed, the unit's book on each feeding day and on `days` ((unit id,
    day) pairs, e.g. the last week's for the feed rate), and the feedings without fish. `observe` is passed
    on to the fold. A `projector` (farm/feeding/projection.py) keeps the estimated weight along the same walk:
    it sees every stock line, every weighing point and the end of every day read. Raises the fold's StockError."""
    walker = _Walker(feedings, days, observe, projector, frozenset(line.batch_id for line in lines if line.cleaner))
    walker.result.lines = lines
    walker.result.shares = fold(lines, walker.after, before=walker.before, on_line=walker.line)
    walker.capture(walker.result.shares)
    return walker.result

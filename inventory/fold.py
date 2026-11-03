"""The store's book, worked out from its lines and the feeding records: pure, no database (inventory/read.py
loads the rows). A bucket is a lot in a location; one item is folded at a time, over every location of
every site, so a transfer between sites (owner decision Q-S6) is one fold.

Each day, in this order:

1. arrivals: delivered and moved-in lines add to their bucket;
2. departures: issued, written-off, returned and moved-out lines take from theirs, in the order entered;
3. feeding (feed only): the kilos the site's units were fed that day (the feeding records) are drawn
   from the site's buckets, first expired first out: lots not expired that day by expiry (none last),
   then by the day the lot first arrived, its number, the location's code; then expired lots, which is
   reported ("the book says feed of an expired lot was used"); what is left is **uncovered** feeding,
   reported per site and day and never refused (owner decision Q-S1: no later delivery fills it; it is
   fixed by recording the missing delivery on or before its day);
4. counts: a count sets every bucket of its location to the quantity counted (0 for what it does not
   list) at the end of the day; its variance is the counted quantity less the book just before it.

The lines are facts a person recorded; the feeding is an estimate of which lots were fed (a record names
no lot). So a departure is checked against the **physical** book, the lines alone (`physical`): it may
never take a bucket below 0, on its day or later. And feeding draws only what no later departure of the
same bucket needs: its draw from a bucket is at most the lowest physical balance from that day up to the
bucket's next count, less what feeding drew before. The book therefore never goes below 0 and a recorded
departure never turns wrong because of a feeding (the source refused the feeding instead, STR-01)."""
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

ZERO = Decimal(0)
ARRIVALS = ('in', 'transfer_in')
DEPARTURES = ('out', 'transfer_out')


@dataclass(frozen=True)
class Op:
    id: object
    kind: str
    day: date
    seq: object            # the order of entry (created_at, id): orders the operations of a day
    location: object = None   # a count's location


@dataclass(frozen=True)
class Line:
    id: int
    op: Op
    lot: object
    location: object
    kind: str
    quantity: Decimal


@dataclass(frozen=True)
class Lot:
    id: object
    number: str
    expiry: date = None


@dataclass(frozen=True)
class Place:
    id: object
    site: object
    code: str


@dataclass(frozen=True)
class Shortfall:
    """A departure that takes its bucket below 0 in the physical book: `available` was there."""
    line: Line
    available: Decimal


@dataclass(frozen=True)
class Draw:
    day: date
    site: object
    bucket: tuple
    kg: Decimal
    expired: bool


@dataclass(frozen=True)
class Variance:
    op: Op
    bucket: tuple
    book: Decimal       # the book just before the count, at the end of its day
    counted: Decimal

    @property
    def difference(self):
        return self.counted - self.book


@dataclass
class _Segment:
    """The physical balance of a bucket between two counts: points (day, balance after that day's moves),
    and the lowest balance from each point on (`floor`). It starts after `after` (a count's day) or at
    the beginning."""
    after: date = None
    days: list = field(default_factory=list)
    values: list = field(default_factory=list)
    floor: list = field(default_factory=list)

    def point(self, day, value):
        if self.days and self.days[-1] == day:
            self.values[-1] = value
        else:
            self.days.append(day)
            self.values.append(value)

    def close(self):
        lowest, floor = None, []
        for value in reversed(self.values):
            lowest = value if lowest is None else min(lowest, value)
            floor.append(lowest)
        self.floor = list(reversed(floor))

    def index(self, day):
        """The point in force on `day`, or None before the first."""
        index = bisect_right(self.days, day) - 1
        return index if index >= 0 else None


def _ordered(lines):
    return sorted(lines, key=lambda line: (line.op.day, line.op.seq, line.id))


def _physical(lines, counts):
    """The lines alone: each bucket's segments, the counts' resets, the first shortfall."""
    days = defaultdict(lambda: ([], [], []))     # day -> (arrivals, departures, counts)
    for line in _ordered(lines):
        if line.kind in ARRIVALS:
            days[line.op.day][0].append(line)
        elif line.kind in DEPARTURES:
            days[line.op.day][1].append(line)
    counted = defaultdict(dict)          # count op id -> {bucket: quantity}
    for line in lines:
        if line.kind == 'count':
            counted[line.op.id][(line.location, line.lot)] = line.quantity
    for op in sorted(counts, key=lambda op: op.seq):
        days[op.day][2].append(op)
    balance = defaultdict(lambda: ZERO)
    segments = defaultdict(lambda: [_Segment()])
    resets, shortfall = [], None
    for day in sorted(days):
        arrivals, departures, day_counts = days[day]
        for line in arrivals + departures:
            bucket = (line.location, line.lot)
            before = balance[bucket]
            balance[bucket] = before + line.quantity
            if shortfall is None and balance[bucket] < 0:
                shortfall = Shortfall(line, max(before, ZERO))
            segments[bucket][-1].point(day, balance[bucket])
        for op in day_counts:
            found = counted.get(op.id, {})
            here = {bucket for bucket in segments if bucket[0] == op.location} | set(found)
            for bucket in sorted(here, key=str):
                segment = segments[bucket][-1]
                resets.append((op, bucket, len(segments[bucket]) - 1, balance[bucket], found.get(bucket, ZERO)))
                balance[bucket] = found.get(bucket, ZERO)
                fresh = _Segment(after=day)
                fresh.point(day, balance[bucket])
                segments[bucket].append(fresh)
                if not segment.days:
                    segment.point(day, ZERO)
    for chain in segments.values():
        for segment in chain:
            segment.close()
    return dict(segments), resets, shortfall


def physical(lines, counts=()):
    """The first departure that takes its bucket below 0 in the physical book (the lines alone), or None:
    the rule every write path keeps (inventory/services.py)."""
    return _physical(lines, counts)[2]


def physical_end(lines, counts=()):
    """{bucket: balance} of the physical book after its last day."""
    segments = _physical(lines, counts)[0]
    return {bucket: chain[-1].values[-1] if chain[-1].values else ZERO for bucket, chain in segments.items()}


class Folded:
    """The book of one item: what each bucket holds on any day, the feeding drawn and left uncovered, and
    the counts' variances."""

    def __init__(self, lines, counts, feeding, lots, places):
        self.lots, self.places = lots, places
        self.segments, resets, self.shortfall = _physical(lines, counts)
        self.first_arrival = {}
        for line in _ordered(lines):
            if line.kind in (*ARRIVALS, 'count'):
                self.first_arrival.setdefault(line.lot, line.op.day)
        self.drawn = defaultdict(lambda: defaultdict(list))   # bucket -> segment index -> [(day, kg)]
        self.draws, self.uncovered = [], []
        for (site, day), kilos in sorted(feeding.items(), key=lambda item: (item[0][1], str(item[0][0]))):
            self._feed(site, day, kilos)
        self.variances = [
            Variance(op, bucket, before - self._drawn_in(bucket, index, op.day), counted)
            for op, bucket, index, before, counted in resets]
        self.lines = lines

    # ---- the feeding draw ------------------------------------------------------------------------
    def _segment(self, bucket, day, counted=False):
        """(index, segment) in force on `day` before its counts (the feeding's), or after them (`counted`,
        the end of the day)."""
        chain = self.segments.get(bucket)
        if not chain:
            return None, None
        for index in range(len(chain) - 1, -1, -1):
            after = chain[index].after
            if after is None or after < day or counted and after == day:
                return index, chain[index]
        return None, None

    def _drawn_in(self, bucket, index, until):
        return sum((kg for day, kg in self.drawn[bucket][index] if day <= until), ZERO)

    def _headroom(self, bucket, day):
        index, segment = self._segment(bucket, day)
        if segment is None:
            return ZERO
        point = segment.index(day)
        if point is None:
            return ZERO
        return max(segment.floor[point] - self._drawn_in(bucket, index, day), ZERO)

    def _order(self, bucket, day):
        lot = self.lots[bucket[1]]
        expired = lot.expiry is not None and lot.expiry < day
        return (expired, lot.expiry is None, lot.expiry or date.max, self.first_arrival.get(lot.id, date.max),
                lot.number, self.places[bucket[0]].code)

    def _feed(self, site, day, kilos):
        buckets = [bucket for bucket in self.segments if self.places[bucket[0]].site == site]
        left = kilos
        for bucket in sorted(buckets, key=lambda bucket: self._order(bucket, day)):
            if left <= 0:
                break
            take = min(self._headroom(bucket, day), left)
            if take <= 0:
                continue
            index, _segment = self._segment(bucket, day)
            self.drawn[bucket][index].append((day, take))
            lot = self.lots[bucket[1]]
            self.draws.append(Draw(day, site, bucket, take, lot.expiry is not None and lot.expiry < day))
            left -= take
        if left > 0:
            self.uncovered.append((site, day, left))

    # ---- reading it ------------------------------------------------------------------------------
    def balance(self, bucket, day):
        """What the bucket holds at the end of `day`, its counts included."""
        index, segment = self._segment(bucket, day, counted=True)
        if segment is None:
            return ZERO
        point = segment.index(day)
        if point is None:
            return ZERO
        return segment.values[point] - self._drawn_in(bucket, index, day)

    def on_hand(self, day):
        """{bucket: quantity} of every bucket that holds something at the end of `day`."""
        held = {bucket: self.balance(bucket, day) for bucket in self.segments}
        return {bucket: quantity for bucket, quantity in held.items() if quantity}

    def last_movement(self):
        """{bucket: the day of its latest line}."""
        latest = {}
        for line in self.lines:
            bucket = (line.location, line.lot)
            if bucket not in latest or line.op.day > latest[bucket]:
                latest[bucket] = line.op.day
        return latest

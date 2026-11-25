"""Reading the feeding records against the stock ledger: the batches each record fed, the last feeding,
FCR and the feed rate, all computed on read from the live records and the fold (farm/feeding/fold.py);
nothing is stored, so nothing drifts (the source kept a feed total per batch that drifted from its records,
and three FCR formulas that disagreed, FDR-17, FDR-22, FDR-32).

Definitions (feeding-records §4.7), for a unit u, a batch b, their share (u, b) and a day d; B is the
fold's book biomass (measured weights only), in kg:
- the feed of a record goes to the batches in u at the start of d, split by B then; to those at the end
  of d when u was empty at its start;
- last fed = the latest day of a live record of u in the current stay of its fish;
- a window runs from the first measured point i of a stay (its stocking, fish graded in) to its last
  weighing j (or the harvest that emptied it): F = the share's feed of the days i ≤ d < j (j included for
  a harvest: the fish are weighed before the day's feeding, a harvest after it);
  biological gain G = B_j − B_i + removed − added between them; economic gain = G − lost fish;
- bFCR = ΣF / ΣG and eFCR = ΣF / Σ economic gain over the windows (of a unit: of its shares that have
  one), shown only when F > 0 and the gain > 0; eFCR ≥ bFCR, deaths are credited only in bFCR;
- SFR (specific feeding rate, % of the body weight a day) = 100 × the feed of the days / the sum of B on
  those days (B at the start of a day, at its end when the unit was empty at the start), over the
  last 7 days on which the unit held fish. B does not grow between weighings, so SFR reads high as the
  last weighing ages.

Known bias, said on the page: dead fish between weighings leave at the last measured average, so their
growth since is not credited (bFCR slightly high when mortality is heavy).

The rations (`project`): the same walk with a projector (farm/feeding/projection.py), over the units' lineage (every
unit their batches were in), keeps the estimated weight and the day's ration of the days asked, from the protocols,
assignments and temperatures loaded once into a ration.Policy (`policy`). Nothing of it is stored."""
from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.db.models import Prefetch, Q, Sum
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from farm.handling import fasting
from farm.models import Batch, FeedingProtocol, FeedingRecord, ProtocolAssignment, ProtocolBand, StockMovement, Tank
from farm.models.feeding import FeedTarget
from farm.models.site import zone_of
from farm.models.stock import MovementKind
from farm.stock.dates import end_of, local_today, start_of
from farm.stock.fold import operations
from farm.stock.read import batches_ever_in, ledger

from .fold import ZERO, Feeding, PointKind, Window, ratio, walk
from .projection import Projector
from .ration import Band, Cell, Policy, Table
from .temperature import TemperatureBook

WEEK = 7          # the days the drawer's feed rate and feed total cover
HUNDRED = Decimal(100)

# Why a unit or a batch shows no FCR, the dash's title.
UNWEIGHED = _('Not weighed since the fish came in.')
UNFED = _('No feed recorded up to the last weighing.')
NO_GAIN = _('No growth up to the last weighing.')


def given(only=None):
    """THE kilos of feed given (the data-layering audit, L-8): the sum of `amount_kg` over the live feeding records (a
    voided one never counts), `only` a Q narrowing which (a site's own day, ...). An aggregate expression for
    `.aggregate()` / `.annotate()` on FeedingRecord rows; every figure of feed given (a day's ration check, the records'
    total, the meal board, the overview's cards, the store's draw on the feed) is this sum."""
    live = Q(is_deleted=False)
    return Sum('amount_kg', filter=live if only is None else live & only)


def feedings(unit_ids=None, since=None):
    """The live feedings (fold.Feeding) of these units (None: every unit) dated `since` or later, each with its
    meals and its place among the day's records (its time, a record without one last, then the order of entry)."""
    rows = FeedingRecord.objects.order_by()
    if unit_ids is not None:
        rows = rows.filter(unit_id__in=unit_ids)
    if since is not None:
        rows = rows.filter(date__gte=since)
    return [Feeding(pk, unit_id, day, kilos, meals, (clock is None, clock or time.min, created), target)
            for pk, unit_id, day, kilos, meals, clock, created, target
            in rows.values_list('pk', 'unit_id', 'date', 'amount_kg', 'meals', 'time', 'created_at', 'target')]


def _walk(unit_ids, records, days=()):
    """The walk of these units: the ledger of every batch ever in them, with `records` (fold.Feeding)."""
    return walk(ledger(batches_ever_in(unit_ids)), records, days)


# ---- the projected weight and the rations ------------------------------------------------------------------
def lineage(unit_ids):
    """(unit ids, batch ids) a projection of these units reads: every batch ever in them, every unit those batches
    were ever in, and every batch ever in those, until nothing is added. Fish moved in carry their estimate from
    where they were, and the feed of a unit is split among every batch in it."""
    units, batches = set(unit_ids), set()
    while True:
        added = batches_ever_in(units) - batches
        if not added:
            return units, batches
        batches |= added
        more = set(StockMovement.objects.filter(batch_id__in=added, operation__is_deleted=False)
                   .values_list('unit_id', flat=True)) - units
        if not more:
            return units, batches
        units |= more


def tables(protocol_ids):
    """{protocol id: ration.Table} of these protocols, their bands in weight order with their feed and cells."""
    bands = ProtocolBand.objects.select_related('feed').prefetch_related('rates').order_by('min_weight_g')
    found = {}
    for protocol in (FeedingProtocol.all_objects.filter(pk__in=protocol_ids).select_related('species')
                     .prefetch_related(Prefetch('bands', bands))):
        found[protocol.pk] = Table(protocol, tuple(
            Band(band.pk, band.min_weight_g, band.max_weight_g, band.feed, band.meals_per_day, band.expected_fcr,
                 tuple(Cell(rate.temperature_c, rate.sfr_pct)
                       for rate in sorted(band.rates.all(), key=lambda rate: rate.temperature_c)))
            for band in protocol.bands.all()))
    return found


def policy(units, batch_ids, first, now, read=()):
    """The ration.Policy of these units (Tank, by id) and batches from the day `first` to now: the assignment rows
    in force over those days, their tables, the batches' species and the units' temperatures, read once. `read`: the
    (unit id, day) pairs whose temperature the walk may ask (its feeding days and the days asked): the sensors' values
    at all their moments are read in one ask, not one per day."""
    rows = list(ProtocolAssignment.objects.filter(Q(unit_id__in=list(units)) | Q(batch_id__in=batch_ids))
                .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=first))
                .select_related('unit', 'protocol__species'))
    found_batches = list(Batch.all_objects.filter(pk__in=batch_ids)
                         .values_list('pk', 'species_id', 'species__cleaner_fish_type'))
    species = {pk: species_id for pk, species_id, _cleaner in found_batches}
    cleaner = frozenset(pk for pk, _species_id, cleaner_type in found_batches if cleaner_type)
    book = TemperatureBook(units.values(), datetime.combine(first, time.min, tzinfo=UTC) - timedelta(days=1), now)
    today = {unit_id: local_today(unit) for unit_id, unit in units.items()}
    found = {}

    def moment(unit_id, day):
        """Now for the unit's today, the end of the day for a day before it."""
        return now if day >= today[unit_id] else end_of(day, units[unit_id])

    def temperature(unit_id, day):
        if (unit_id, day) not in found:
            found[(unit_id, day)] = book.at(units[unit_id], moment(unit_id, day))
        return found[(unit_id, day)]

    def may_ask(unit_id, day):
        """Whether the walk can ask that day's temperature at all: `Policy.basis` reads it only for a share with a
        protocol in force that day, and a row reaches a unit's day only as the unit's own or as a whole batch's (a batch
        in this unit that day: not known before the walk, so every row of a batch counts). A day no row covers is never
        asked, whatever the fish weigh; the days left may still not be (the band is the weight's), and an unread day is
        simply asked on its own (`Series._live`), with the same answer."""
        return any(row.unit_id in (unit_id, None) and row.covers(day) for row in rows)

    book.prefetch(sorted({moment(unit_id, day) for unit_id, day in read if unit_id in units and may_ask(unit_id, day)}))

    # The fasts planned harvests and transports ask for, from `first` to the units' today (one query).
    fasts = fasting.fasts(list(units.values()), first, max(today.values(), default=first))
    return Policy(rows, tables({row.protocol_id for row in rows}), species, temperature,
                  fasting=lambda unit_id, day: fasts.get((unit_id, day)), cleaner=cleaner)


@dataclass
class Projection:
    """A walk with the projected weight (projection.Projector): the stays, the days asked (`days`: (unit id, day)
    -> projection.UnitDay) and the weighings' corrections."""
    walked: object
    projector: Projector

    @property
    def days(self):
        return self.projector.days

    def corrections(self, unit_id, batch_id=None):
        """The corrections of the batches of a unit (or of one batch in it), oldest first."""
        return [correction for (unit, batch), found in self.projector.corrections.items()
                if unit == unit_id and (batch_id is None or batch == batch_id) for correction in found]


def project(unit_ids, days=(), now=None):
    """One walk of the units' lineage with the projected weight, keeping the UnitDay of each (unit id, day) of
    `days`. Every feeding of those units is walked: the estimate runs from the last measured point, wherever the
    fish were then."""
    now = now or timezone.now()
    unit_ids, batch_ids = lineage(unit_ids)
    records = feedings(unit_ids)
    units = Tank.all_objects.select_related('production_department__site').in_bulk(unit_ids)
    first = min([record.date for record in records] + [day for _unit, day in days],
                default=timezone.localdate(now, zone_of(None)))
    read = {(record.unit_id, record.date) for record in records} | set(days)
    projector = Projector(policy(units, batch_ids, first, now, read), days)
    return Projection(walk(ledger(batch_ids), records, days, projector=projector), projector)


def book_on(unit, day):
    """The unit on `day` (fold.Day): the grams of its batches at the start and at the end of the day."""
    return _walk([unit.pk], [], [(unit.pk, day)]).days[(unit.pk, day)]


def split_of(records):
    """{record id: {batch id: kg}}: the batches each record fed and their part of it."""
    unit_ids = {record.unit_id for record in records}
    if not unit_ids:
        return {}
    return _walk(unit_ids, [Feeding(record.pk, record.unit_id, record.date, record.amount_kg, target=record.target)
                            for record in records]).split


def fed(units, first, last):
    """{(unit id, batch id, feed id): kg} of the live feedings of `units` dated from `first` to `last`, each split
    among the batches it fed as `split_of` splits it (the batches in the unit at the start of its day, by their book
    biomass then). The reports read the feed of a period here, never from the records' own kilos."""
    records = list(FeedingRecord.objects.filter(unit__in=list(units), date__gte=first, date__lte=last))
    feed_of = {record.pk: (record.unit_id, record.feed_id) for record in records}
    found = {}
    for record_id, parts in split_of(records).items():
        unit_id, feed_id = feed_of[record_id]
        for batch_id, kilos in parts.items():
            key = (unit_id, batch_id, feed_id)
            found[key] = found.get(key, ZERO) + kilos
    return found


def records_of_batch(batch, records):
    """The ids of `records` (a queryset) that fed `batch`: those whose split gives it a part."""
    unit_ids = set(StockMovement.objects.filter(batch=batch, operation__is_deleted=False)
                   .values_list('unit_id', flat=True))
    candidates = list(records.filter(unit_id__in=unit_ids, date__gte=batch.input_date))
    return [pk for pk, parts in split_of(candidates).items() if batch.pk in parts]


# ---- the last feeding of the fish ----------------------------------------------------------------
@dataclass(frozen=True)
class LastFed:
    """When fish were last fed: the moment on the clock of the feeding's site (its date and time; a record
    without a time counts from the end of its day, so a fast is never overstated) and the record."""
    moment: datetime
    record: FeedingRecord

    @property
    def timed(self):
        return self.record.time is not None


def fed_moment(record):
    """A feeding's moment on its site's clock: its date and time, or the end of its day without a time."""
    if record.time is None:
        return start_of(record.date + timedelta(days=1), record.unit)
    return datetime.combine(record.date, record.time, tzinfo=zone_of(record.unit.production_department.site))


@dataclass(frozen=True)
class Where:
    """A unit the fish now in another unit were in, and over which days (both included): the unit handled since they
    came into it, the unit they came from up to the day they left it, and so on back along their own path."""
    unit_id: object
    first: date
    last: date


@dataclass
class _Stay:
    """A batch in a unit from the line that brought fish of it in while it had none there (`at`: that line's place in
    the ledger's order, `since`: its day), and the transfers that brought more of it in during the stay (`arrivals`:
    (the arriving line's place, its day, the unit the fish left, the place of the line they left it by), in order)."""
    at: int
    since: date
    arrivals: list = field(default_factory=list)


class Paths:
    """Where fish were, back along their own path: the ledger's lines indexed ONCE, in the ledger's own order
    (farm.stock.fold.operations: the day, then the order the operations were entered, the order they happened in),
    for every unit asked afterwards (`where`). A transfer has a day and no time, so a path is cut at a PLACE in that
    order, never at a day: fish that left a unit by one transfer were in it up to that transfer, whatever was entered
    for the unit later the same day (a unit emptied and refilled on one day, a move there and back, a grading day:
    read by day, the lines after the move were taken for the stay the fish left, and their last feeding was lost,
    review F-02). Indexed once whatever the number of units (review F-04: once per unit, a units list of 200 units
    cost 60 times one of 25)."""

    def __init__(self, lines):
        self.days = []                           # the day of every line, in the ledger's order: where a day ends
        self.stays = defaultdict(list)           # (unit, batch) -> [_Stay], oldest first
        running = defaultdict(int)
        left = {}                                # (operation, pair) -> (the unit a transfer's fish left, that line's place)
        for op, op_lines in operations(lines):
            for line in op_lines:
                place, key = len(self.days), (line.unit_id, line.batch_id)
                self.days.append(op.date)
                if line.count_delta > 0 and running[key] <= 0:     # a new stay: what came before is not these fish
                    self.stays[key].append(_Stay(place, op.date))
                running[key] += line.count_delta
                if line.kind == MovementKind.TRANSFER_OUT:
                    left[(op.id, line.pair)] = (line.unit_id, place)
                elif line.kind == MovementKind.TRANSFER_IN and (op.id, line.pair) in left:
                    source, out = left[(op.id, line.pair)]
                    if source != line.unit_id:
                        self.stays[key][-1].arrivals.append((place, op.date, source, out))

    def where(self, unit_id, batch_ids, day, since=None):
        """[Where] of the fish of `batch_ids` that are in `unit_id` on `day` (after every line dated `day` or before).
        For each batch, the unit itself from the start of its stay there to `day`; for every arrival of that stay by a
        transfer, the unit it came from, from the start of the batch's stay THERE (the stay the fish left: the one
        going on just before the line they left by) to the day of the move (the move has no time, so its day counts in
        both units: a fast is never overstated), and so on back. A unit the fish were never in, and their old unit
        after they left it, are not in it: a sibling group fed elsewhere after a split does not break the fast of the
        fish handled (flow fault S-01). Nothing before `since` is followed."""
        found = {}                               # (unit, batch, the stay's place) -> [the stay's day, the last day]
        followed = {}                            # the same -> the place its arrivals are followed up to
        todo = [(unit_id, batch_id, bisect_right(self.days, day), day) for batch_id in batch_ids]
        while todo:
            unit, batch, cut, last = todo.pop()
            if since is not None and last < since:
                continue
            stays = self.stays.get((unit, batch), ())
            index = bisect_left(stays, cut, key=lambda stay: stay.at) - 1      # the stay going on before the cut
            if index < 0:
                continue
            stay = stays[index]
            key = (unit, batch, stay.at)
            if key in found:
                found[key][1] = max(found[key][1], last)
            else:
                found[key] = [stay.since, last]
            start = followed.get(key, 0)
            if cut <= start:
                continue                         # this stay's arrivals before the cut are followed already
            followed[key] = cut
            for _place, moved_on, source, out in stay.arrivals[bisect_left(stay.arrivals, (start,)):
                                                               bisect_left(stay.arrivals, (cut,))]:
                todo.append((source, batch, out, moved_on))
        return [Where(unit, first if since is None else max(first, since), last)
                for (unit, _batch, _at), (first, last) in found.items()]


def fed_where(lines, unit_id, batch_ids, day, since=None):
    """`Paths(lines).where(...)` for one unit: [Where] of the fish of `batch_ids` in `unit_id` on `day`."""
    return Paths(lines).where(unit_id, batch_ids, day, since)


def last_fed_of(asked, lines=None):
    """{unit id: LastFed or None}: THE reader of when the fish in a unit were last fed, for every page and check that
    says it (the handling check and its acknowledgement, the earliest harvest date, the units list, the drawer, the
    production plans, the cards). `asked`: [(unit, day, the ids of its production batches that day, since or None)].

    The fast is of the FISH IN THE UNIT, not of a batch across every unit it was ever in (flow fault S-01; the owner,
    14.11.2026: fish of two batches in one unit are one group, one fast for the unit whichever batch a dialog names):
    the feedings of production fish in the units and days `fed_where` gives for each batch in the unit, on or before
    `day`; the latest of them decides (the least-fasted fish: they cannot be handled apart). A cleaner fish's feeding
    is not theirs. One ledger read (none when the caller holds the lines of these batches already: `lines`, a walk's),
    indexed once (`Paths`), and one query of the feedings, for all the units asked: each answer's record and moment
    come from that one read, so a feeding voided or changed while it runs cannot break or split the answer."""
    asked = list(asked)
    found = {unit.pk: None for unit, _day, _ids, _since in asked}
    batch_ids = {batch_id for _unit, _day, ids, _since in asked for batch_id in ids}
    if not batch_ids:
        return found
    paths = Paths(ledger(batch_ids) if lines is None else lines)
    places = {unit.pk: paths.where(unit.pk, ids, day, since) for unit, day, ids, since in asked}
    every = [place for found_for in places.values() for place in found_for]
    if not every:
        return found
    # ONE read of the candidates, every column of each (a wall's thousands of feedings are never built as records): each
    # weighed by the one rule (`fed_moment`) on its unit's clock, and only the winners built as records, from the very
    # rows read. So a feeding voided, deleted or changed meanwhile can neither be missing from the answer nor disagree
    # with its own moment: the answer is of that one snapshot, as when the records were read whole. (The units are read
    # beside it: no feeding names a unit that is not there, the database refuses a hard delete of one.)
    unit_ids = {place.unit_id for place in every}
    units = Tank.all_objects.select_related('production_department__site').in_bulk(unit_ids)
    rows = FeedingRecord.objects.filter(unit_id__in=unit_ids, target=FeedTarget.PRODUCTION,
                                        date__gte=min(place.first for place in every),
                                        date__lte=max(place.last for place in every))
    columns = [column.attname for column in FeedingRecord._meta.concrete_fields]
    at = {name: columns.index(name) for name in ('id', 'unit_id', 'date', 'time', 'created_at')}
    by_unit = defaultdict(list)
    for row in rows.values_list(*columns):
        weighed = _Fed(row[at['id']], row[at['date']], row[at['time']], row[at['created_at']],
                       units[row[at['unit_id']]], row)
        by_unit[row[at['unit_id']]].append((weighed, fed_moment(weighed)))
    for unit_id, where in places.items():
        counted = {each.pk: (each, moment) for place in where for each, moment in by_unit.get(place.unit_id, ())
                   if place.first <= each.date <= place.last}
        if counted:
            winner, moment = max(counted.values(), key=lambda each: (each[1], each[0].created_at))
            record = FeedingRecord.from_db(rows.db, columns, winner.row)
            record.unit = winner.unit
            found[unit_id] = LastFed(moment, record)
    return found


@dataclass(frozen=True)
class _Fed:
    """A feeding as `last_fed_of` weighs it: what `fed_moment` reads, its entry time for a tie, its unit, and `row`, all
    its columns as read, from which a winner is built."""
    pk: object
    date: date
    time: time
    created_at: datetime
    unit: object
    row: tuple


def handled(unit, day):
    """The ids of the production batches a handling of `unit` on `day` handles: those in it at the start of the day or
    at its end (fish that arrive on the day are handled with the others; the cleaner fish beside them are not)."""
    return handled_of([(unit, day)])[(unit.pk, day)]


def handled_of(asked):
    """{(unit id, day): batch ids} of `handled` for every (unit, day) asked, from one walk of the units (a page of
    fifty units reads the ledger once, not fifty times)."""
    asked = list(asked)
    if not asked:
        return {}
    days = _walk({unit.pk for unit, _day in asked}, [], [(unit.pk, day) for unit, day in asked]).days
    found = {}
    for unit, day in asked:
        book = days[(unit.pk, day)].production
        found[(unit.pk, day)] = set(book.start) | set(book.end)
    return found


def last_fed_at(unit, day, since=None):
    """The latest feeding (LastFed) of the fish in `unit` on or before `day`, back to `since`; None when no record fed
    them (`last_fed_of`, for one unit). It takes no batch on purpose: the fast is the unit's."""
    return last_fed_of([(unit, day, handled(unit, day), since)])[unit.pk]


# ---- FCR -----------------------------------------------------------------------------------------
def _last_on(points, day):
    """The index of the last measured point on `day` (the state at the end of that day), else None."""
    found = [index for index, point in enumerate(points) if point.day == day]
    return found[-1] if found else None


def window(stay, first=None, last=None):
    """The stay's FCR window: from its first measured point to its last weighing (or the harvest that closed it).
    A bound `first` or `last` (a day) puts that end on the stay's measured point of that day (the last of the day);
    a day without a measured point gives None, never an interpolated one, and so does a window that would not
    start before it ends. Unbounded it is the whole stay's."""
    points = stay.points
    start = (0 if points else None) if first is None else _last_on(points, first)
    if start is None:
        return None
    if last is None:
        ends = [index for index, point in enumerate(points) if index > start
                and point.kind in (PointKind.WEIGHING, PointKind.CLOSE)]
        end = ends[-1] if ends else None
    else:
        end = _last_on(points, last)
    if end is None or end <= start:
        return None
    start, end = points[start], points[end]
    return Window(start, end, stay.fed_kg(start.day, end.day, closing=end.kind == PointKind.CLOSE))


def measured_on(unit_ids, day):
    """{(unit id, batch id)} of the batches in these units whose stay has a measured point (stocking, fish graded in, a
    weighing, the harvest that closed it) on `day`: a window can start or end there (`window`)."""
    unit_ids = list(unit_ids)
    walked = _walk(unit_ids, [])
    return {key for key, stays in walked.stays.items()
            if key[0] in unit_ids and any(point.day == day for stay in stays for point in stay.points)}


def windows_in(unit_ids, first=None, last=None):
    """{(unit id, batch id): Window} of the batches that were in these units, over the days `first` and `last`
    (window(): each a day with a measured point of the stay, else the share has no window; None: the stay's own
    end). One walk of the units' feeding from `first` on. A batch that came into a unit more than once has the
    window of its latest stay that has one. A replicate's FCR is `Conversion` of the windows of its tanks."""
    unit_ids = list(unit_ids)
    walked = _walk(unit_ids, feedings(unit_ids, since=first))
    found = {}
    for key, stays in walked.stays.items():
        if key[0] not in unit_ids:           # the ledger follows the batches into other units too
            continue
        for stay in stays:
            made = window(stay, first, last)
            if made is not None:
                found[key] = made
    return found


@dataclass
class Conversion:
    """Feed conversion over windows: ΣF / ΣG (bFCR) and ΣF / Σ economic gain (eFCR)."""
    windows: list = field(default_factory=list)

    @property
    def feed_kg(self):
        return sum((item.feed_kg for item in self.windows), ZERO)

    @property
    def gain_kg(self):
        return sum((item.gain_kg for item in self.windows), ZERO)

    @property
    def economic_gain_kg(self):
        return sum((item.economic_gain_kg for item in self.windows), ZERO)

    @property
    def biological(self):
        return ratio(self.feed_kg, self.gain_kg)

    @property
    def economic(self):
        return ratio(self.feed_kg, self.economic_gain_kg)

    def _why(self, gain):
        if not self.windows:
            return UNWEIGHED
        if self.feed_kg <= 0:
            return UNFED
        return NO_GAIN if gain <= 0 else ''

    @property
    def why_no_biological(self):
        return self._why(self.gain_kg)

    @property
    def why_no_economic(self):
        return self._why(self.economic_gain_kg)


@dataclass
class ShareFeeding:
    """A batch in a unit now: the feed of its current stay and its FCR window."""
    batch: object
    stay: object
    window: Window = None
    cleaner: bool = False

    @property
    def fed_kg(self):
        return self.stay.fed_kg()

    @property
    def conversion(self):
        return Conversion([self.window] if self.window else [])


@dataclass
class Week:
    """The unit's last WEEK days (the drawer): what it was fed today and over the days, and the feed rate."""
    first: date
    today_kg: Decimal
    today_meals: int          # None unless every record of today says its meals
    kg: Decimal
    biomass_days_kg: Decimal  # the sum of B over the days with fish
    feed: object              # the feed of the latest record of the current stay

    @property
    def sfr(self):
        return HUNDRED * self.kg / self.biomass_days_kg if self.biomass_days_kg else None


@dataclass
class UnitFeeding:
    """The feeding figures of a unit with fish; for a detailed unit (the drawer, a detailed card) also its last WEEK days, today's ration
    (projection.UnitDay) and the corrections of its weighings."""
    today: date
    last_fed: date = None
    last_fed_in: object = None     # the unit that feeding was in, when it is not this one (the fish were moved in since)
    shares: list = field(default_factory=list)
    week: Week = None
    ration: object = None
    corrections: list = field(default_factory=list)

    @property
    def conversion(self):
        """Over the windows of its production fish's shares; a share without one is left out of both sums."""
        return Conversion([share.window for share in self.shares if share.window and not share.cleaner])

    @property
    def unweighed(self):
        """The production batches without a window (named in the drawer)."""
        return [share.batch for share in self.shares if not share.window and not share.cleaner]


def figures(stock, details=(), ration=False):
    """{unit id: UnitFeeding} of the units with fish (`stock`: read.stock_of). For each unit of `details` (Tank
    objects) also its last WEEK days (`weeks`), today's ration (projection.UnitDay) and the corrections of its
    weighings; with `ration`, today's ration of every unit with fish. Whatever walks the projected weight
    (`project`) walks once for all of them, the page, the drawer and a wall of cards alike."""
    if not stock:
        return {}
    unit_ids = list(stock)
    today = {unit_id: local_today(item.unit) for unit_id, item in stock.items()}
    since = min(item.since for item in stock.values())
    detailed = [unit for unit in details if unit.pk in stock]
    days = {(unit_id, today[unit_id]): None for unit_id in unit_ids} if ration else {}
    for unit in detailed:
        first = today[unit.pk] - timedelta(days=WEEK - 1)
        days.update({(unit.pk, first + timedelta(days=n)): None for n in range(WEEK)})
        since = min(since, first)
    days = list(days)
    projection = project(unit_ids, days) if days else None
    walked = projection.walked if projection else _walk(unit_ids, feedings(unit_ids, since), days)
    # When the fish in each unit were last fed: the one reader (`last_fed_of`), so the list, the drawer, the plans and
    # the cards say what the handling check says (fish moved in bring their last meal in their old unit). It reads the
    # lines the walk has just folded (every batch ever in these units): no second read of the ledger, so a page or a
    # wall of cards costs the queries it cost before (monitoring's recorded counts, review F-01).
    last = last_fed_in(stock, lines=walked.lines)
    result = {}
    for unit_id, item in stock.items():
        fed = last.get(unit_id)
        unit = result[unit_id] = UnitFeeding(today[unit_id], fed.record.date if fed else None,
                                             fed.record.unit if fed and fed.record.unit_id != unit_id else None)
        for share in item.shares:
            stay = walked.stays[(unit_id, share.batch.pk)][-1]
            unit.shares.append(ShareFeeding(share.batch, stay, window(stay), share.cleaner))
        if ration:
            unit.ration = projection.days.get((unit_id, today[unit_id]))
    for unit, week in weeks(detailed, stock, today, walked).items():
        result[unit.pk].week = week
        result[unit.pk].ration = projection.days.get((unit.pk, today[unit.pk]))
        result[unit.pk].corrections = projection.corrections(unit.pk)
    return result


def last_fed_in(stock, lines=None):
    """{unit id: LastFed or None} of the units with fish (`stock`: read.stock_of): what `figures` says of each as its
    last feeding, `last_fed_of` the fish counted in it on its today, back to any day. A page that shows nothing else of
    the figures (the production plans) asks this alone and walks no feeding; `lines`: the ledger lines of these batches
    when the caller has them (a walk's)."""
    return last_fed_of(((item.unit, local_today(item.unit), [share.batch.pk for share in item.counted], None)
                        for item in stock.values()), lines=lines)


def weeks(units, stock, today, walked):
    """{unit: Week} of the units (Tank objects with fish, `stock` and `today` by unit id, `walked` the walk that
    kept their last WEEK days): two queries for all of them, the records of the days and the feed in use."""
    if not units:
        return {}
    ids = [unit.pk for unit in units]
    first = {unit.pk: today[unit.pk] - timedelta(days=WEEK - 1) for unit in units}
    # The production fish's feed against their biomass; the cleaner fish's feedings are theirs (D-1, D-2).
    records = {unit_id: [] for unit_id in ids}
    for record in (FeedingRecord.objects.filter(unit_id__in=ids, date__gte=min(first.values()),
                                                target=FeedTarget.PRODUCTION).select_related('feed')):
        if record.date >= first[record.unit_id]:
            records[record.unit_id].append(record)
    # The latest record of each unit's current stay: the feed in use (the record order of FeedingRecord.Meta).
    latest = {record.unit_id: record for record in
              FeedingRecord.objects.filter(unit_id__in=ids, target=FeedTarget.PRODUCTION).select_related('feed')
              .order_by('unit_id', *FeedingRecord._meta.ordering).distinct('unit_id')}
    found = {}
    for unit in units:
        mine, day = records[unit.pk], today[unit.pk]
        of_today = [record for record in mine if record.date == day]
        meals = [record.meals for record in of_today]
        current = latest.get(unit.pk)
        in_use = current if current is not None and stock[unit.pk].since and current.date >= stock[unit.pk].since             else None
        found[unit] = Week(
            first=first[unit.pk],
            today_kg=sum((record.amount_kg for record in of_today), ZERO),
            today_meals=sum(meals) if meals and None not in meals else None,
            kg=sum((record.amount_kg for record in mine if record.date <= day), ZERO),
            biomass_days_kg=sum((walked.days[(unit.pk, first[unit.pk] + timedelta(days=n))].production.biomass_kg
                                 for n in range(WEEK)), ZERO),
            feed=in_use.feed if in_use else None,
        )
    return found


# ---- the meal board's lines ---------------------------------------------------------------------------------
def drift(today, measured_on):
    """How far the estimate has run since its measured point (owner decision Q6): '', 'soon' or 'now'."""
    if measured_on is None:
        return ''
    days = (today - measured_on).days
    if days > settings.WEIGH_NOW_DAYS:
        return 'now'
    return 'soon' if days > settings.WEIGH_SOON_DAYS else ''


def meal_lines(unit_day, batches, today):
    """The line of each batch of a unit's day (projection.UnitDay, None: no day): its ShareDay, its batch (`batches`:
    by id), why it has no ration, whether its fish are cleaner fish (marked as such; without a feeding table of their
    own they have no ration and no why, D-1), the drift of its estimate and the days since its measured point. The meal
    board and the monitoring cards print these and nothing computed beside them.

    The day names its batches; `batches` is what the caller has (the unit's stock now) and may lack one: the day is the
    fold at the end of the unit's TODAY, the stock the fold of every line there is, so a line dated after today (a clock
    set back before the ledger's newest lines, a site whose time zone was moved a day behind) leaves a batch in the day
    that the stock no longer holds. Such a batch is read here, in one query for all of them, never a KeyError on a
    page."""
    shares = unit_day.shares if unit_day else []
    missing = {share.batch_id for share in shares} - batches.keys()
    if missing:
        batches = {**batches, **Batch.all_objects.select_related('species').in_bulk(missing)}
    return [{'share': share, 'batch': batches[share.batch_id], 'why': share.end.why(batches[share.batch_id]),
             'cleaner': batches[share.batch_id].species.is_cleaner_fish,
             'drift': drift(today, share.measured_on),
             'estimate_days': (today - share.measured_on).days if share.measured_on else None}
            for share in shares]


def fed_in(unit, start, end):
    """[(moment, record)] of the live feeding records of `unit` fed from `start` to before `end` (`fed_moment`), in time
    order: the feedings a unit's water history marks (Tank › Water)."""
    zone = zone_of(unit.production_department.site)
    first, last = start.astimezone(zone).date(), end.astimezone(zone).date()
    found = [(fed_moment(record), record) for record in FeedingRecord.objects.filter(unit=unit, date__gte=first, date__lte=last)
             .select_related('unit__production_department__site', 'feed')]
    return sorted(((at, record) for at, record in found if start <= at < end), key=lambda pair: pair[0])

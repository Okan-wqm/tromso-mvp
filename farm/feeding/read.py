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
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.db.models import Max, Prefetch, Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from farm.handling import fasting
from farm.models import Batch, FeedingProtocol, FeedingRecord, ProtocolAssignment, ProtocolBand, StockMovement, Tank
from farm.models.feeding import FeedTarget
from farm.models.site import zone_of
from farm.stock.dates import end_of, local_today, start_of
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


def policy(units, batch_ids, first, now):
    """The ration.Policy of these units (Tank, by id) and batches from the day `first` to now: the assignment rows
    in force over those days, their tables, the batches' species and the units' temperatures, read once."""
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

    def temperature(unit_id, day):
        """Now for the unit's today, the end of the day for a day before it."""
        if (unit_id, day) not in found:
            unit = units[unit_id]
            found[(unit_id, day)] = book.at(unit, now if day >= today[unit_id] else end_of(day, unit))
        return found[(unit_id, day)]

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
    projector = Projector(policy(units, batch_ids, first, now), days)
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


def last_fed_at(unit, day, batch=None, since=None):
    """The latest feeding (LastFed) of the fish on or before `day`, back to `since`: the fish of `batch`
    wherever they were (fish moved in were fed in their old unit), or, without a batch, of every batch in
    `unit` at the start of `day` (at its end when it was empty then), its production fish (the ones handled; a
    cleaner fish's feeding is not theirs). Which batches a record fed is the feeding walk's split, so a record of
    the unit before these fish came in does not count. None when no record fed them."""
    if batch is not None:
        batch_ids = {batch.pk}
    else:
        batch_ids = set(book_on(unit, day).production.weights)
    if not batch_ids:
        return None
    unit_ids = set(StockMovement.objects.filter(batch_id__in=batch_ids, operation__is_deleted=False)
                   .values_list('unit_id', flat=True))
    records = (FeedingRecord.objects.filter(unit_id__in=unit_ids, date__lte=day)
               .select_related('unit__production_department__site'))
    if since is not None:
        records = records.filter(date__gte=since)
    records = list(records)
    fed = split_of(records)
    moments = [(fed_moment(record), record) for record in records if batch_ids & set(fed.get(record.pk, {}))]
    if not moments:
        return None
    moment, record = max(moments, key=lambda item: (item[0], item[1].created_at))
    return LastFed(moment, record)


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
    last = dict(FeedingRecord.objects.filter(unit_id__in=unit_ids, target=FeedTarget.PRODUCTION).order_by()
                .values('unit_id').annotate(last=Max('date')).values_list('unit_id', 'last'))
    result = {}
    for unit_id, item in stock.items():
        fed = last.get(unit_id)
        unit = result[unit_id] = UnitFeeding(today[unit_id], fed if fed and fed >= item.since else None)
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
    own they have no ration and no why, D-1), the drift of its estimate and the days since its measured point. The meal board and the monitoring
    cards print these and nothing computed beside them."""
    return [{'share': share, 'batch': batches[share.batch_id], 'why': share.end.why(batches[share.batch_id]),
             'cleaner': batches[share.batch_id].species.is_cleaner_fish,
             'drift': drift(today, share.measured_on),
             'estimate_days': (today - share.measured_on).days if share.measured_on else None}
            for share in (unit_day.shares if unit_day else [])]

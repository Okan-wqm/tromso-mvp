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
growth since is not credited (bFCR slightly high when mortality is heavy)."""
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db.models import Max
from django.utils.translation import gettext_lazy as _

from farm.models import FeedingRecord, StockMovement
from farm.models.site import zone_of
from farm.stock.dates import local_today
from farm.stock.read import batches_ever_in, ledger

from .fold import ZERO, Feeding, PointKind, walk

WEEK = 7          # the days the drawer's feed rate and feed total cover
HUNDRED = Decimal(100)

# Why a unit or a batch shows no FCR, the dash's title.
UNWEIGHED = _('Not weighed since the fish came in.')
UNFED = _('No feed recorded up to the last weighing.')
NO_GAIN = _('No growth up to the last weighing.')


def feedings(unit_ids=None, since=None):
    """The live feedings (fold.Feeding) of these units (None: every unit) dated `since` or later."""
    rows = FeedingRecord.objects.order_by()
    if unit_ids is not None:
        rows = rows.filter(unit_id__in=unit_ids)
    if since is not None:
        rows = rows.filter(date__gte=since)
    return [Feeding(*row) for row in rows.values_list('pk', 'unit_id', 'date', 'amount_kg')]


def _walk(unit_ids, records, days=()):
    """The walk of these units: the ledger of every batch ever in them, with `records` (fold.Feeding)."""
    return walk(ledger(batches_ever_in(unit_ids)), records, days)


def book_on(unit, day):
    """The unit on `day` (fold.Day): the grams of its batches at the start and at the end of the day."""
    return _walk([unit.pk], [], [(unit.pk, day)]).days[(unit.pk, day)]


def split_of(records):
    """{record id: {batch id: kg}}: the batches each record fed and their part of it."""
    unit_ids = {record.unit_id for record in records}
    if not unit_ids:
        return {}
    return _walk(unit_ids, [Feeding(record.pk, record.unit_id, record.date, record.amount_kg)
                            for record in records]).split


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
    zone = zone_of(record.unit.production_department.site)
    if record.time is None:
        return datetime.combine(record.date + timedelta(days=1), time.min, tzinfo=zone)
    return datetime.combine(record.date, record.time, tzinfo=zone)


def last_fed_at(unit, day, batch=None, since=None):
    """The latest feeding (LastFed) of the fish on or before `day`, back to `since`: the fish of `batch`
    wherever they were (fish moved in were fed in their old unit), or, without a batch, of every batch in
    `unit` at the start of `day` (at its end when it was empty then). Which batches a record fed is the
    feeding walk's split, so a record of the unit before these fish came in does not count. None when no
    record fed them."""
    if batch is not None:
        batch_ids = {batch.pk}
    else:
        batch_ids = set(book_on(unit, day).weights)
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
def ratio(feed, gain):
    return feed / gain if feed > 0 and gain > 0 else None


@dataclass(frozen=True)
class Window:
    """A share's stay from its first measured point to its last weighing (or the harvest that closed it)."""
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


def window(stay):
    if not stay.points:
        return None
    first = stay.points[0]
    ends = [point for point in stay.points[1:] if point.kind in (PointKind.WEIGHING, PointKind.CLOSE)]
    if not ends:
        return None
    last = ends[-1]
    return Window(first, last, stay.fed_kg(first.day, last.day, closing=last.kind == PointKind.CLOSE))


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
    """The feeding figures of a unit with fish."""
    today: date
    last_fed: date = None
    shares: list = field(default_factory=list)
    week: Week = None

    @property
    def conversion(self):
        """Over the windows of its shares; a share without one is left out of both sums."""
        return Conversion([share.window for share in self.shares if share.window])

    @property
    def unweighed(self):
        """The batches without a window (named in the drawer)."""
        return [share.batch for share in self.shares if not share.window]


def figures(stock, detail=None):
    """{unit id: UnitFeeding} of the units with fish (`stock`: read.stock_of), and the last WEEK days of
    `detail` (the drawer's unit). One walk and two queries for the page."""
    if not stock:
        return {}
    unit_ids = list(stock)
    today = {unit_id: local_today(item.unit) for unit_id, item in stock.items()}
    since = min(item.since for item in stock.values())
    days = []
    if detail is not None and detail.pk in stock:
        first = today[detail.pk] - timedelta(days=WEEK - 1)
        days = [(detail.pk, first + timedelta(days=n)) for n in range(WEEK)]
        since = min(since, first)
    walked = _walk(unit_ids, feedings(unit_ids, since), days)
    last = dict(FeedingRecord.objects.filter(unit_id__in=unit_ids).order_by().values('unit_id')
                .annotate(last=Max('date')).values_list('unit_id', 'last'))
    result = {}
    for unit_id, item in stock.items():
        fed = last.get(unit_id)
        unit = result[unit_id] = UnitFeeding(today[unit_id], fed if fed and fed >= item.since else None)
        for share in item.shares:
            stay = walked.stays[(unit_id, share.batch.pk)][-1]
            unit.shares.append(ShareFeeding(share.batch, stay, window(stay)))
    if days:
        result[detail.pk].week = _week(detail, stock[detail.pk], today[detail.pk], days, walked)
    return result


def _week(unit, stock, today, days, walked):
    first = days[0][1]
    records = list(FeedingRecord.objects.filter(unit=unit, date__gte=first).select_related('feed'))
    of_today = [record for record in records if record.date == today]
    meals = [record.meals for record in of_today]
    latest = (FeedingRecord.objects.filter(unit=unit, date__gte=stock.since).select_related('feed').first())
    return Week(
        first=first,
        today_kg=sum((record.amount_kg for record in of_today), ZERO),
        today_meals=sum(meals) if meals and None not in meals else None,
        kg=sum((record.amount_kg for record in records if record.date <= today), ZERO),
        biomass_days_kg=sum((walked.days[key].biomass_kg for key in days), ZERO),
        feed=latest.feed if latest else None,
    )

"""Reading the store: the rows the fold needs (inventory/fold.py), loaded once per page, and the figures the
pages show, all computed on read from the live lines and the feeding records; nothing is stored.

- on hand: what a bucket (a lot in a location) holds at the end of its site's today;
- days of cover = feed on hand at a site ÷ the kilos fed a day there over the last WEEK days;
- low stock: on hand of an item in a location below its reorder level (owner decision Q-S4);
- over capacity: on hand of the items counted in a location's capacity unit above its capacity (Q-S2);
- expiring: lots with stock whose expiry is within EXPIRING_DAYS; expired: lots with stock past it;
- uncovered feeding: kilos fed beyond the book at a site, within the backdating window, where recording
  the missing delivery fixes it (Q-S1); older days stay on the item's page;
- value: on hand × what the lot cost when it was delivered, per currency, never added across currencies.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum

from core import sealing
from farm.models import Feed, FeedingRecord, Site
from farm.stock.dates import site_earliest, site_today

from .fold import ZERO, Folded, Line, Lot, Op, Place
from .models import InventoryItem, InventoryLine, InventoryLot, InventoryOperation, OperationKind, StorageLocation

WEEK = 7
EXPIRING_DAYS = 30


def _op(operation):
    return Op(operation.pk, operation.kind, operation.date, (operation.created_at, str(operation.pk)),
              operation.location_id)


def _counts():
    return [_op(op) for op in InventoryOperation.objects.filter(kind=OperationKind.COUNT)]


def _places():
    return {pk: Place(pk, site_id, code)
            for pk, site_id, code in StorageLocation.all_objects.values_list('pk', 'site_id', 'code')}


def _lines(items=None, exclude_op=None):
    """{item id: [fold.Line]} of the live operations."""
    rows = InventoryLine.objects.filter(operation__is_deleted=False).select_related('operation', 'lot')
    if items is not None:
        rows = rows.filter(lot__item__in=items)
    if exclude_op is not None:
        rows = rows.exclude(operation=exclude_op)
    found = defaultdict(list)
    ops = {}
    for row in rows:
        op = ops.setdefault(row.operation_id, _op(row.operation))
        found[row.lot.item_id].append(Line(row.pk, op, row.lot_id, row.location_id, row.kind, row.quantity))
    return found


@sealing.reads_as_system('the store')    # feed drawn from the store is a stock figure: every feeding counts (review F5)
def _feeding(feed_ids):
    """{feed id: {(site id, day): kg}} of the live feeding records, by the site of the unit's department."""
    found = defaultdict(dict)
    rows = (FeedingRecord.objects.filter(feed_id__in=feed_ids, unit__production_department__site__isnull=False)
            .order_by().values('feed_id', 'unit__production_department__site_id', 'date').annotate(kg=Sum('amount_kg')))
    for row in rows:
        found[row['feed_id']][(row['unit__production_department__site_id'], row['date'])] = row['kg']
    return found


def folds(items=None):
    """{item id: fold.Folded} of these items (InventoryItem rows; None: every item)."""
    items = list(InventoryItem.all_objects.all() if items is None else items)
    lines = _lines(items)
    counts = _counts()
    places = _places()
    feeding = _feeding([item.feed_id for item in items if item.feed_id])
    lots = defaultdict(dict)
    for lot in InventoryLot.all_objects.filter(item__in=items):
        lots[lot.item_id][lot.pk] = Lot(lot.pk, lot.number, lot.expiry_date)
    return {item.pk: Folded(lines.get(item.pk, []), counts, feeding.get(item.feed_id, {}), lots[item.pk], places)
            for item in items}


@sealing.reads_as_system('the store')    # feed drawn from the store is a stock figure: every feeding counts (review F5)
def undelivered():
    """{feed: fold.Folded} of the feeds that were fed (a live feeding record on a site) and have no item in the store:
    an item is made at a feed's first delivery or reorder level (services.item_for), so a feed never delivered had no
    fold and its feeding was compared with nothing: invisible in the store (flow fault M-03). Each is folded as an item
    without a line, by the same fold that finds a stocked item's shortfall, so all its feeding is `uncovered`."""
    stocked = set(InventoryItem.all_objects.values_list('feed_id', flat=True))
    feed_ids = set(FeedingRecord.objects.filter(unit__production_department__site__isnull=False)
                   .exclude(feed_id__in=stocked).order_by().values_list('feed_id', flat=True).distinct())
    if not feed_ids:
        return {}
    feeding, places = _feeding(feed_ids), _places()         # no line: no count to reset anything
    feeds = Feed.all_objects.in_bulk(feed_ids)
    return {feeds[feed_id]: Folded([], [], feeding.get(feed_id, {}), {}, places) for feed_id in feed_ids}


def physical_lines(items):
    """({item id: [fold.Line]}, [count fold.Op]): what a write path checks (the lines alone)."""
    return _lines(items), _counts()


def sites():
    return Site.all_objects.in_bulk()


# ---- a bucket's book -----------------------------------------------------------------------------
@dataclass
class Bucket:
    location: StorageLocation
    lot: InventoryLot
    item: InventoryItem
    quantity: Decimal
    last_movement: object = None
    cost: tuple = None          # (unit cost, currency) or None

    @property
    def site(self):
        return self.location.site

    @property
    def value(self):
        return None if self.cost is None else self.quantity * self.cost[0]


def costs():
    """{lot id: (unit cost, currency)}: the delivered lines' average cost in the currency of the latest one."""
    found = {}
    rows = (InventoryLine.objects.filter(operation__is_deleted=False, unit_cost__isnull=False)
            .order_by('operation__date', 'id').values_list('lot_id', 'quantity', 'unit_cost', 'currency'))
    by_lot = defaultdict(list)
    for lot_id, quantity, unit_cost, currency in rows:
        by_lot[lot_id].append((quantity, unit_cost, currency))
    for lot_id, entries in by_lot.items():
        currency = entries[-1][2]
        same = [(quantity, cost) for quantity, cost, money in entries if money == currency]
        total = sum((quantity for quantity, _cost in same), ZERO)
        found[lot_id] = (sum((quantity * cost for quantity, cost in same), ZERO) / total, currency)
    return found


def buckets(folded=None, *, empty=False, day=None):
    """Every bucket with stock at the end of its site's today (or `day`), as Bucket rows; `empty` adds the
    buckets that held something once and hold nothing now."""
    folded = folds() if folded is None else folded
    items = InventoryItem.all_objects.select_related('feed').in_bulk(list(folded))
    locations = StorageLocation.all_objects.select_related('site').in_bulk()
    lot_ids = {bucket[1] for fold in folded.values() for bucket in fold.segments}
    lots = InventoryLot.all_objects.in_bulk(lot_ids)
    priced = costs()
    rows = []
    for item_id, fold in folded.items():
        latest = fold.last_movement()
        for bucket in fold.segments:
            location = locations[bucket[0]]
            quantity = fold.balance(bucket, day or site_today(location.site))
            if not quantity and (not empty or location.is_deleted or lots[bucket[1]].is_deleted):
                continue
            rows.append(Bucket(location, lots[bucket[1]], items[item_id], quantity, latest.get(bucket),
                               priced.get(bucket[1])))
    rows.sort(key=lambda row: (row.site.name, row.location.code, str(row.item),
                               row.lot.expiry_date or row.lot.created_at.date(), row.lot.number))
    return rows


def holds_stock(location):
    """Whether the book has anything in the location at the end of its site's today."""
    items = InventoryItem.all_objects.filter(lots__lines__location=location).distinct()
    today = site_today(location.site)
    return any(fold.balance(bucket, today) for fold in folds(items).values() for bucket in fold.segments
               if bucket[0] == location.pk)


def book_at(location, day):
    """[(lot, quantity)] the book has in `location` at the end of `day`, before a count of that day is
    entered: the prefill of the count dialog."""
    items = InventoryItem.all_objects.filter(lots__lines__location=location).distinct()
    held = []
    for fold in folds(items).values():
        for bucket in fold.segments:
            if bucket[0] == location.pk:
                quantity = fold.balance(bucket, day)
                if quantity:
                    held.append((bucket[1], quantity))
    lots = InventoryLot.all_objects.select_related('item__feed').in_bulk([lot_id for lot_id, _q in held])
    rows = [(lots[lot_id], quantity) for lot_id, quantity in held]
    rows.sort(key=lambda row: (str(row[0].item), row[0].expiry_date or row[0].created_at.date(), row[0].number))
    return rows


# ---- the overview --------------------------------------------------------------------------------
@dataclass
class SiteItem:
    """One item on one site: on hand, days of cover, uncovered feeding within the window."""
    site: Site
    item: InventoryItem
    on_hand: Decimal = ZERO
    fed_week: Decimal = ZERO
    uncovered: Decimal = ZERO
    uncovered_since: object = None
    expired_used: Decimal = ZERO

    @property
    def cover_days(self):
        if not self.fed_week:
            return None
        return self.on_hand / (self.fed_week / WEEK)


@dataclass
class Undelivered:
    """A feed fed on a site and never delivered to the store: the kilos fed inside the correction window, all of them a
    shortfall, and the first such day."""
    site: Site
    feed: Feed
    kilos: Decimal
    since: object


@dataclass
class Overview:
    site_items: list = field(default_factory=list)
    undelivered: list = field(default_factory=list)    # Undelivered rows: feeds fed and never delivered
    low: list = field(default_factory=list)            # (location, item, on hand, level)
    over: list = field(default_factory=list)           # (location, on hand, capacity)
    expiring: list = field(default_factory=list)       # Bucket rows
    expired: list = field(default_factory=list)        # Bucket rows
    values: dict = field(default_factory=dict)         # site -> {currency: value}


def overview():
    """The overview of every site: per item its stock, cover and uncovered feeding, and the warnings."""
    folded = folds()
    rows = buckets(folded)
    site_rows = sites()
    items = InventoryItem.all_objects.select_related('feed').in_bulk(list(folded))
    found = Overview()
    per = {}

    def entry(site, item):
        return per.setdefault((site.pk, item.pk), SiteItem(site, item))

    for row in rows:
        entry(row.site, row.item).on_hand += row.quantity
        today = site_today(row.site)
        expiry = row.lot.expiry_date
        if expiry is not None and expiry < today:
            found.expired.append(row)
        elif expiry is not None and expiry <= today + timedelta(days=EXPIRING_DAYS):
            found.expiring.append(row)
        if row.value is not None:
            money = found.values.setdefault(row.site, defaultdict(lambda: ZERO))
            money[row.cost[1]] += row.value
    for item_id, fold in folded.items():
        for site_id, day, kilos in fold.uncovered:
            site = site_rows[site_id]
            if day >= site_earliest(site):
                record = entry(site, items[item_id])
                record.uncovered += kilos
                record.uncovered_since = min(day, record.uncovered_since or day)
        for draw in fold.draws:
            site = site_rows[draw.site]
            if draw.expired and draw.day >= site_earliest(site):
                entry(site, items[item_id]).expired_used += draw.kg
    for feed, fold in undelivered().items():
        short = {}
        for site_id, day, kilos in fold.uncovered:
            site = site_rows[site_id]
            if day >= site_earliest(site):
                held = short.setdefault(site_id, Undelivered(site, feed, ZERO, day))
                held.kilos += kilos
                held.since = min(held.since, day)
        found.undelivered += short.values()
    found.undelivered.sort(key=lambda row: (row.site.name, str(row.feed)))
    for (site_id, _item_id), record in per.items():
        if record.item.feed_id:
            today = site_today(record.site)
            with sealing.system('the store'):                   # a stock figure: every feeding counts
                record.fed_week = FeedingRecord.objects.filter(
                    feed_id=record.item.feed_id, unit__production_department__site_id=site_id,
                    date__range=(today - timedelta(days=WEEK - 1), today)).aggregate(kg=Sum('amount_kg'))['kg'] or ZERO
    found.site_items = sorted(per.values(), key=lambda record: (record.site.name, str(record.item)))
    held = defaultdict(lambda: ZERO)
    for row in rows:
        held[(row.location.pk, row.item.pk)] += row.quantity
    for location in StorageLocation.objects.select_related('site').prefetch_related('reorder_levels__item__feed'):
        for level in location.reorder_levels.all():
            quantity = held.get((location.pk, level.item_id), ZERO)
            if quantity < level.level:
                found.low.append((location, level.item, quantity, level.level))
        if location.capacity is not None:
            quantity = sum((row.quantity for row in rows if row.location.pk == location.pk
                            and row.item.unit == location.capacity_unit), ZERO)
            if quantity > location.capacity:
                found.over.append((location, quantity, location.capacity))
    found.values = {site: dict(money) for site, money in found.values.items()}
    return found


# ---- an item's day-by-day book, a lot's trace -----------------------------------------------------
@dataclass
class Day:
    day: object
    arrived: Decimal = ZERO
    left: Decimal = ZERO
    fed: Decimal = ZERO
    uncovered: Decimal = ZERO
    expired_used: Decimal = ZERO
    variance: Decimal = ZERO
    counted: bool = False
    closing: Decimal = ZERO


def item_days(item, site):
    """The day-by-day book of `item` at `site`, newest first: what arrived, left, was fed (drawn from the
    book), was fed beyond it, the counts' variance and the closing stock."""
    fold = folds([item])[item.pk]
    locations = set(StorageLocation.all_objects.filter(site=site).values_list('pk', flat=True))
    days = {}

    def entry(day):
        return days.setdefault(day, Day(day))

    for line in fold.lines:
        if line.location not in locations:
            continue
        if line.kind in ('in', 'transfer_in'):
            entry(line.op.day).arrived += line.quantity
        elif line.kind in ('out', 'transfer_out'):
            entry(line.op.day).left -= line.quantity
    for draw in fold.draws:
        if draw.site == site.pk:
            entry(draw.day).fed += draw.kg
            if draw.expired:
                entry(draw.day).expired_used += draw.kg
    for site_id, day, kilos in fold.uncovered:
        if site_id == site.pk:
            entry(day).uncovered += kilos
    for variance in fold.variances:
        if variance.bucket[0] in locations:
            row = entry(variance.op.day)
            row.variance += variance.difference
            row.counted = True
    buckets_here = [bucket for bucket in fold.segments if bucket[0] in locations]
    for row in days.values():
        row.closing = sum((fold.balance(bucket, row.day) for bucket in buckets_here), ZERO)
    return sorted(days.values(), key=lambda row: row.day, reverse=True)


def item_sites(item):
    """The sites where `item` was ever kept or fed from the store's book."""
    fold = folds([item])[item.pk]
    places = _places()
    ids = {places[bucket[0]].site for bucket in fold.segments} | {site for site, _day, _kg in fold.uncovered}
    return list(Site.all_objects.filter(pk__in=ids).order_by('name'))


def lot_trace(lot):
    """The lot's lines, oldest first, with their operation, and the feeding drawn from it per site and day
    (an estimate: a feeding record names no lot)."""
    lines = list(InventoryLine.objects.filter(lot=lot).select_related(
        'operation__supplier', 'operation__created_by', 'operation__deleted_by', 'location__site')
        .order_by('operation__date', 'operation__created_at', 'id'))
    fold = folds([lot.item])[lot.item_id]
    draws = defaultdict(lambda: ZERO)
    for draw in fold.draws:
        if draw.bucket[1] == lot.pk:
            draws[(draw.day, draw.bucket[0])] += draw.kg
    locations = StorageLocation.all_objects.select_related('site').in_bulk({location for _day, location in draws})
    fed = sorted(((day, locations[location], kilos) for (day, location), kilos in draws.items()),
                 key=lambda row: row[0])
    return lines, fed


def count_variances(operation):
    """[(lot, book, counted, difference)] of a count: the book at the end of its day just before it, every
    lot it lists or the book had there (none that was and stays 0)."""
    items = InventoryItem.all_objects.filter(lots__lines__location=operation.location_id).distinct()
    found = []
    for fold in folds(items).values():
        for variance in fold.variances:
            if variance.op.id == operation.pk and (variance.book or variance.counted):
                found.append(variance)
    lots = InventoryLot.all_objects.select_related('item__feed').in_bulk([variance.bucket[1] for variance in found])
    rows = [(lots[variance.bucket[1]], variance.book, variance.counted, variance.difference) for variance in found]
    rows.sort(key=lambda row: (str(row[0].item), row[0].number))
    return rows

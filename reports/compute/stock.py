"""The stock of a site's units over a period, as every monthly report reads it: the fold at the period's start and
end, the period's lines, and the state of a unit just before an operation emptied it. Only the farm's reads
(farm/stock/read.py) and fold; nothing here recomputes a count or a weight."""
from dataclasses import dataclass
from decimal import Decimal

from farm.models import Batch, Site, Species, StockOperation, Tank
from farm.stock import read
from farm.stock.fold import fold

ZERO = Decimal(0)


def held(unit_stock, batch_ids=None):
    """(fish, grams) of every batch in a unit (farm.stock.read.UnitStock), or of the batches `batch_ids` only, cleaner
    fish included: a unit's own figures are its production fish's, but a report of a hatchery's tank, whatever species it
    holds, reports all its fish."""
    shares = [share for share in unit_stock.shares if batch_ids is None or share.batch.pk in batch_ids]
    return sum(share.count for share in shares), sum((share.grams for share in shares), ZERO)


def site_units(site):
    """Every unit of the site, deleted ones too (a deleted unit keeps its records)."""
    return list(Tank.all_objects.filter(production_department__site=site)
                .select_related('production_department__site').order_by('code'))


@dataclass
class Emptied:
    """A unit just before an operation that emptied it in the period: the day, and each batch's fish and grams then."""
    day: object
    batches: dict           # {batch id: (fish, grams)}

    def of(self, batch_ids):
        """(fish, grams) of these batches just before."""
        found = [self.batches[batch_id] for batch_id in batch_ids if batch_id in self.batches]
        return sum(fish for fish, _grams in found), sum((grams for _fish, grams in found), ZERO)


def emptied_in(units, first, last):
    """{unit id: [Emptied]} of the units an operation dated from `first` to `last` left without fish, each time it
    happened and in order: the state just before that operation (the fold's `before` hook at it)."""
    unit_ids = {unit.pk for unit in units}
    lines = [line for line in read.ledger(read.batches_ever_in(unit_ids)) if line.op.date <= last]
    state_before = {}
    found = {}

    def before(op, shares):
        state_before.clear()
        for (unit_id, batch_id), share in shares.items():
            if unit_id in unit_ids and share.count:
                state_before.setdefault(unit_id, {})[batch_id] = (share.count, share.grams)

    def observe(op, shares):
        if not first <= op.date <= last:
            return
        left = {unit_id for (unit_id, _batch_id), share in shares.items() if unit_id in unit_ids and share.count}
        for unit_id, batches in state_before.items():
            if unit_id not in left:
                found.setdefault(unit_id, []).append(Emptied(op.date, dict(batches)))

    fold(lines, observe, before=before)
    return found


def scope_rows(units, last, batch_ids=None):
    """[(label, queryset)] of the rows a stock reading of `units` up to `last` reads, for the fingerprint: the
    operations of every batch ever in them dated up to `last` (a void bumps an operation's version, a backdated one
    is a new row), the batches, the units themselves (a unit moved to another site changes its version) and the master
    rows the figures name them by: the sites (their numbers) and the species (their codes)."""
    unit_ids = [unit.pk for unit in units]
    batch_ids = read.batches_ever_in(unit_ids) if batch_ids is None else batch_ids
    sites = {unit.production_department.site_id for unit in units if unit.production_department.site_id}
    return [
        ('sites', Site.all_objects.filter(pk__in=sites)),
        ('species', Species.all_objects.filter(batches__in=batch_ids).distinct()),
        ('stock_operations', StockOperation.all_objects.filter(movements__batch_id__in=batch_ids, date__lte=last)
         .distinct()),
        ('batches', Batch.all_objects.filter(pk__in=batch_ids)),
        ('units', Tank.all_objects.filter(pk__in=unit_ids)),
    ]

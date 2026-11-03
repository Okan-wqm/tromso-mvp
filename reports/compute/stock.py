"""The stock of a site's units over a period, as every monthly report reads it: the fold at the period's start and
end, the period's lines, and the state of a unit just before an operation emptied it. Only the farm's reads
(farm/stock/read.py) and fold; nothing here recomputes a count or a weight."""
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from farm.models import Batch, StockOperation, Tank
from farm.stock import read
from farm.stock.fold import fold

ZERO = Decimal(0)


def site_units(site):
    """Every unit of the site, deleted ones too (a deleted unit keeps its records)."""
    return list(Tank.all_objects.filter(production_department__site=site)
                .select_related('production_department__site').order_by('code'))


@dataclass
class Emptied:
    """A unit just before the operation that emptied it in the period: its fish and grams then, and the day."""
    count: int
    grams: Decimal
    day: object

    @property
    def avg_weight_g(self):
        return self.grams / self.count


def emptied_in(units, first, last):
    """{unit id: Emptied} of the units an operation dated from `first` to `last` left without fish: the state just
    before the last such operation (the fold's `before` hook at that operation)."""
    unit_ids = {unit.pk for unit in units}
    lines = [line for line in read.ledger(read.batches_ever_in(unit_ids)) if line.op.date <= last]
    totals_before = {}
    found = {}

    def totals(shares):
        summed = {}
        for (unit_id, _batch_id), share in shares.items():
            if unit_id in unit_ids and share.count:
                count, grams = summed.get(unit_id, (0, ZERO))
                summed[unit_id] = (count + share.count, grams + share.grams)
        return summed

    def before(op, shares):
        totals_before.clear()
        totals_before.update(totals(shares))

    def observe(op, shares):
        after = totals(shares)
        for unit_id, (count, grams) in totals_before.items():
            if unit_id not in after and first <= op.date <= last:
                found[unit_id] = Emptied(count, grams, op.date)

    fold(lines, observe, before=before)
    return found


def scope_rows(units, last, batch_ids=None):
    """[(label, queryset)] of the rows a stock reading of `units` up to `last` reads, for the fingerprint: the
    operations of every batch ever in them dated up to `last` (a void bumps an operation's version, a backdated one
    is a new row), the batches, and the units themselves (a unit moved to another site changes its version)."""
    unit_ids = [unit.pk for unit in units]
    batch_ids = read.batches_ever_in(unit_ids) if batch_ids is None else batch_ids
    return [
        ('stock_operations', StockOperation.all_objects.filter(movements__batch_id__in=batch_ids, date__lte=last)
         .distinct()),
        ('batches', Batch.all_objects.filter(pk__in=batch_ids)),
        ('units', Tank.all_objects.filter(pk__in=unit_ids)),
    ]


def day_before(period):
    return period.start - timedelta(days=1)

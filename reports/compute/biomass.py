"""The monthly biomass report to Fiskeridirektoratet (akvakulturdriftsforskriften § 44; docs/regulatory-reports.md 1.5,
2.5): for each production unit in operation, the fish stocked, the stock at the month's end with its biomass, the
harvest, the live fish moved to another site, the losses by cause and the feed; and the day the site was left
fallow. Cleaner fish are not in it (§ 3 h applies to them neither § 44 c nor d; they have their own report, D-2).
Fiskeridirektoratet's form is to be confirmed (D-12); the cause names are its statistics' (D-15, unverified).

The biomass at the month's end (D-7): the book (the last measured average) when the unit was weighed in the
REPORT_RECENT_WEIGHING_DAYS before the month's end; else the feeding projection when it has no blind day since its
last measured point; else the book, marked stale. Each batch's basis is filed with its figure."""
from decimal import Decimal

from django.conf import settings
from django.utils.translation import gettext as _

from farm.feeding import read as feeding_read
from farm.models import Batch, Feed, FeedingRecord, Tank
from farm.models.stock import AdjustmentReason, MovementKind
from farm.stock import read

from . import stock
from .common import Result, identity, species_code, text, unit_number, year_class

ZERO = Decimal(0)

# Fiskeridirektoratet's loss causes (its biomass statistics, D-15): what each line of ours goes to.
DEAD, ESCAPE, COUNTING, OTHER = 'dead', 'escape', 'counting_error', 'other'
ADJUSTMENT_CAUSE = {
    AdjustmentReason.ESCAPE: ESCAPE,
    AdjustmentReason.COUNT_CORRECTION: COUNTING,
    AdjustmentReason.UNACCOUNTED_LOSS: OTHER,
    AdjustmentReason.OTHER: OTHER,
}
BOOK, PROJECTED, STALE = 'book', 'projected', 'book_stale'


def is_production(batch):
    return not batch.species.cleaner_fish_type


def loss_cause(line):
    if line.kind in (MovementKind.MORTALITY, MovementKind.CULL):
        return DEAD
    return ADJUSTMENT_CAUSE.get(line.reason, OTHER)


def compute(site, period, report=None):
    problems, warnings = [], []
    units = stock.site_units(site)
    opening = read.stock_on(units, stock.day_before(period))
    closing = read.stock_on(units, period.end)
    lines = read.movements(units, period.start, period.end)
    batches = Batch.all_objects.select_related('species').in_bulk(
        {line.batch_id for line in lines} | {share.batch.pk for found in (opening, closing) for unit_stock in
                                             found.values() for share in unit_stock.shares})
    lines = [line for line in lines if is_production(batches[line.batch_id])]
    others = {unit.pk: unit for unit in Tank.all_objects.filter(
        pk__in={line.other_unit_id for line in lines if line.other_unit_id})
        .select_related('production_department__site')}
    fed = {key: kilos for key, kilos in feeding_read.fed(units, period.start, period.end).items()
           if is_production(batches[key[1]])}
    feeds = Feed.all_objects.in_bulk({feed_id for _unit, _batch, feed_id in fed})
    reduced = set(report.unit_answers.filter(reduced_capacity=True).values_list('unit_id', flat=True)
                  ) if report else set()

    def production(found, unit_id):
        return [share for share in found[unit_id].shares if is_production(share.batch)] if unit_id in found else []

    in_operation = [unit for unit in units if production(opening, unit.pk) or production(closing, unit.pk)
                    or any(line.unit_id == unit.pk for line in lines)]
    biomass = _biomass(in_operation, closing, period, warnings)
    rows = {}
    for unit in in_operation:
        unit_lines = [line for line in lines if line.unit_id == unit.pk]
        row = {'number': unit_number(unit), 'volume_m3': text(unit.water_volume_m3 or unit.volume_m3, 1),
               'reduced_capacity': unit.pk in reduced, 'stocked': [], 'stock': [], 'harvested': [],
               'moved_out': [], 'losses': [], 'feed': [], 'lines': sorted(line.line_id for line in unit_lines)}
        for line in unit_lines:
            batch = batches[line.batch_id]
            code, batch_year = species_code(batch.species, problems), year_class(batch, problems)
            other = others.get(line.other_unit_id)
            other_site = other.production_department.site if other else None
            if line.kind == MovementKind.INPUT or (line.kind == MovementKind.TRANSFER_IN and other_site != site):
                row['stocked'].append({'species': code, 'year_class': batch_year, 'fish': line.count,
                                       'from_lokalitetsnummer': other_site.lokalitetsnummer if other_site else None})
            elif line.kind == MovementKind.HARVEST:
                row['harvested'].append({'species': code, 'fish': -line.count, 'slaughter_weight_kg': text(
                    line.kilos, 1), 'condition': 'round'})
            elif line.kind == MovementKind.TRANSFER_OUT and other_site != site:
                row['moved_out'].append({'species': code, 'fish': -line.count, 'kg': text(line.kilos, 1),
                                         'to_lokalitetsnummer': other_site.lokalitetsnummer if other_site else None})
            elif line.kind in (MovementKind.MORTALITY, MovementKind.CULL, MovementKind.ADJUSTMENT):
                row['losses'].append({'species': code, 'cause': loss_cause(line), 'fish': -line.count,
                                      'kg': text(line.kilos if line.count < 0 else -(line.kilos or ZERO), 1)})
        for share in production(closing, unit.pk):
            figure = biomass[(unit.pk, share.batch.pk)]
            row['stock'].append({'species': species_code(share.batch.species, problems),
                                 'year_class': year_class(share.batch, problems), 'fish': share.count,
                                 'biomass_kg': text(figure['grams'] / 1000, 1), 'basis': figure['basis']})
        per_feed = {}
        for (unit_id, _batch_id, feed_id), kilos in fed.items():
            if unit_id == unit.pk:
                per_feed[feed_id] = per_feed.get(feed_id, ZERO) + kilos
        for feed_id, kilos in sorted(per_feed.items(), key=lambda item: feeds[item[0]].name):
            feed = feeds[feed_id]
            row['feed'].append({'feed': feed.name, 'feed_type': feed.feed_type, 'kg': text(kilos, 1)})
        rows[str(unit.pk)] = row
    content = {
        'kind': 'biomass', 'period': period.key, 'identity': identity(site, problems), 'units': rows,
        'fallow_since': _fallow_since(units, closing, period),
    }
    warnings.append(_('Fiskeridirektoratet’s current form is to be confirmed with Fiskeridirektoratet before relying '
                      'on this layout (D-12).'))
    scope = stock.scope_rows(units, period.end) + [
        ('feeding_records', FeedingRecord.all_objects.filter(unit__in=units, date__gte=period.start,
                                                             date__lte=period.end)),
    ]
    return Result(content, problems, warnings, scope)


def _biomass(units, closing, period, warnings):
    """{(unit id, batch id): {'grams', 'basis'}} at the month's end by the D-7 rule."""
    recent = settings.REPORT_RECENT_WEIGHING_DAYS
    shares = [(unit.pk, share) for unit in units for share in (closing[unit.pk].shares if unit.pk in closing else [])
              if is_production(share.batch)]
    if not shares:
        return {}
    # The projection carries each share's last measured point, wherever the fish were measured (fish moved keep
    # the day of their last weighing or stocking), and counts its feeding days without an expected FCR.
    unit_ids = {unit_id for unit_id, _share in shares}
    projection = feeding_read.project(unit_ids, days=[(unit_id, period.end) for unit_id in unit_ids])
    found = {}
    for unit_id, share in shares:
        day = projection.days.get((unit_id, period.end))
        estimate = next((item for item in day.shares if item.batch_id == share.batch.pk), None) if day else None
        measured = estimate.measured_on if estimate is not None and estimate.measured_on else (
            share.last_weighed or share.since)
        if (period.end - measured).days <= recent:
            figure = {'grams': share.grams, 'basis': {'method': BOOK, 'measured_on': measured.isoformat()}}
        elif estimate is not None and not estimate.blind_days:
            figure = {'grams': estimate.grams, 'basis': {'method': PROJECTED, 'measured_on': measured.isoformat(),
                                                         'measured_avg_g': text(estimate.measured_g, 2)}}
        else:
            figure = {'grams': share.grams, 'basis': {'method': STALE, 'measured_on': measured.isoformat()}}
            warnings.append(_('A batch’s biomass is its last measured average from %(date)s: no weighing in the '
                              '%(days)d days before the month’s end, and the projection has feeding days without a '
                              'feeding table.') % {'date': measured.isoformat(), 'days': recent})
        found[(unit_id, share.batch.pk)] = figure
    return found


def _fallow_since(units, closing, period):
    """The day the site's last production fish left, when it holds none at the month's end; None otherwise."""
    if any(is_production(share.batch) for unit_stock in closing.values() for share in unit_stock.shares):
        return None
    unit_ids = {unit.pk for unit in units}
    production = set(Batch.all_objects.filter(pk__in=read.batches_ever_in(unit_ids), species__cleaner_fish_type='')
                     .values_list('pk', flat=True))
    days = [line.op.date for line in read.ledger(production) if line.op.date <= period.end and line.unit_id in unit_ids]
    return max(days).isoformat() if days else None

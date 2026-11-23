"""The monthly cleaner-fish report (Mattilsynet, akvakulturdriftsforskriften § 44 with § 3 first paragraph h;
docs/regulatory-reports.md 1.4, 2.4, 3.3): for each production unit that held cleaner fish in the month, per species and
origin (farmed or wild-caught), the fish at the end of the month before, the new fish and those moved in, the fish taken
out by cause, and the month's feed, dry and wet, for the site.

Nothing is typed. The fish are the ledger's: the fold at the day before the month and at its last day, the month's lines
of the cleaner-fish batches (farm/stock/read.py). The counts balance by construction (opening + in - out = closing); the
report checks that every line found a place: a cull for a reason that is none of Mattilsynet's six, or a harvest, would
leave the balance open and is a problem. The month's count adjustments are netted per unit, species and origin (D-9):
a net loss is "fish that cannot be accounted for" (escaped, disappeared, a recount down); a net gain, which the report
has no field for, is shown with its explanation as a warning and the person files by hand or as Mattilsynet accepts."""
from decimal import Decimal

from django.utils.translation import gettext as _

from farm.feeding import read as feeding_read
from farm.models import Batch, Feed, FeedingRecord
from farm.models.feed import FeedForm
from farm.models.stock import CLEANER_CULL_REASONS, MovementKind
from farm.stock import read

from . import stock
from .common import Result, identity, note, species_code, taken_over, text, unit_number, whole

ZERO = Decimal(0)
CAUSES = tuple(reason.value for reason in CLEANER_CULL_REASONS)
FARMED, WILD = 'farmed', 'wild_caught'


def compute(site, period, report=None):
    problems, warnings = [], []
    units = stock.site_units(site)
    opening, closing, lines = read.in_period(units, period.start, period.end)
    batches = Batch.all_objects.select_related('species').in_bulk(
        {line.batch_id for line in lines} | {share.batch.pk for found in (opening, closing) for unit_stock in
                                             found.values() for share in unit_stock.shares})
    cleaner = {pk for pk, batch in batches.items() if batch.species.is_cleaner_fish}
    lines = [line for line in lines if line.batch_id in cleaner]
    taken_over(lines, {unit.pk: unit for unit in units}, batches, warnings)
    rows = {}

    def row(unit, batch):
        """The row of a unit, species and origin the batch belongs to."""
        species = species_code(batch.species, problems)
        if batch.provenance not in (FARMED, WILD):
            note(problems, _('Batch %(batch)s has no origin, farmed or wild-caught (Operations › Production units): '
                             'the report asks it of every cleaner fish.') % {'batch': batch.code})
        unit_row = rows.setdefault(str(unit.pk), {'number': unit_number(unit), 'species': {}, 'lines': []})
        return unit_row['species'].setdefault((species or '', batch.provenance), {
            'species': species, 'origin': batch.provenance or None, 'opening': 0, 'stocked': 0, 'moved_in': 0,
            'culled': dict.fromkeys(CAUSES, 0), 'died': 0, 'moved_out': 0, 'adjusted': 0, 'adjusted_down': 0,
            'closing': 0})

    by_id = {unit.pk: unit for unit in units}
    for found, field in ((opening, 'opening'), (closing, 'closing')):
        for unit_id, unit_stock in found.items():
            for share in unit_stock.shares:
                if share.batch.pk in cleaner:
                    row(by_id[unit_id], share.batch)[field] += share.count
    for line in lines:
        figures = row(by_id[line.unit_id], batches[line.batch_id])
        rows[str(line.unit_id)]['lines'].append(line.line_id)
        if line.opening:
            figures['opening'] += line.count        # stock the farm already had at the month's start, never stocked
        elif line.kind == MovementKind.INPUT:
            figures['stocked'] += line.count
        elif line.kind == MovementKind.TRANSFER_IN:
            figures['moved_in'] += line.count
        elif line.kind in (MovementKind.TRANSFER_OUT, MovementKind.DELIVERY):
            figures['moved_out'] -= line.count
        elif line.kind == MovementKind.MORTALITY:
            figures['died'] -= line.count
        elif line.kind == MovementKind.CULL:
            if line.reason in CAUSES:
                figures['culled'][line.reason] -= line.count
            else:
                problems.append(_('A cull of %(batch)s on %(date)s has the reason “%(reason)s”, which is none of '
                                  'Mattilsynet’s six causes for cleaner fish.') % {
                    'batch': batches[line.batch_id].code, 'date': line.date.isoformat(), 'reason': line.reason})
        elif line.kind == MovementKind.ADJUSTMENT:
            figures['adjusted'] += line.count
            figures['adjusted_down'] += min(line.count, 0)
        elif line.kind == MovementKind.HARVEST:
            problems.append(_('%(batch)s was harvested on %(date)s: cleaner fish are culled, not harvested.') % {
                'batch': batches[line.batch_id].code, 'date': line.date.isoformat()})
    content_rows = {}
    for unit_id, unit_row in rows.items():
        for figures in unit_row['species'].values():
            out = sum(figures['culled'].values()) + figures['died'] + figures['moved_out']
            if figures['opening'] + figures['stocked'] + figures['moved_in'] - out + figures['adjusted']                     != figures['closing']:
                problems.append(_('Unit %(unit)s: the fish of %(species)s at the start and the month’s lines do not '
                                  'add up to the fish at its end: look at its operations.') % {
                    'unit': unit_row['number'], 'species': figures['species']})
        species = []
        for (_code, _origin), figures in sorted(unit_row['species'].items(), key=str):
            lost = -figures['adjusted'] if figures['adjusted'] < 0 else 0
            gained = figures['adjusted'] if figures['adjusted'] > 0 else 0
            if figures['adjusted_down'] < 0 and figures['adjusted'] > figures['adjusted_down']:
                # An escape and a recount up in one month net to less than the escape: the netting must not hide it.
                warnings.append(_('Unit %(unit)s: count adjustments of both signs in the month net to %(net)+d fish of '
                                  '%(species)s, though %(down)d fish left by an escape or a recount down: check that the '
                                  'figure filed is the one meant.') % {
                    'unit': unit_row['number'], 'net': figures['adjusted'], 'species': figures['species'],
                    'down': -figures['adjusted_down']})
            if gained:
                warnings.append(_('Unit %(unit)s: %(fish)d more fish of %(species)s are in the count than the month’s '
                                  'lines explain (a recount up). The report has no field for it: file it as '
                                  'Mattilsynet accepts, or correct the count.') % {
                    'unit': unit_row['number'], 'fish': gained, 'species': figures['species']})
            species.append({**figures, 'unaccounted': lost, 'adjusted_up': gained})
        content_rows[unit_id] = {'number': unit_row['number'], 'species': species,
                                 'lines': sorted(unit_row['lines'])}
    if not content_rows:
        problems.append(_('No unit of the site held cleaner fish in the month: the report has nothing to file.'))
    feed = _feed(units, period, batches, cleaner)
    said_none = report is not None and report.no_cleaner_feed
    if rows and not feed['feeds'] and not said_none:
        problems.append(_('No feeding of the cleaner fish is recorded in the month: record it (Operations › Feeding: choose '
                          'the cleaner fish as the target), or say that none was given (the Report tab).'))
    if feed['feeds'] and said_none:
        problems.append(_('Feed was recorded for the cleaner fish this month, but the report says none was given.'))
    content = {'kind': 'cleaner_fish', 'period': period.key, 'identity': identity(site, problems), 'feed': feed,
               'units': content_rows}
    return Result(content, problems, warnings, scope(site, period, units))


def scope(site, period, units=None):
    """The rows the month's figures are read from (for the fingerprint), without computing them."""
    units = units if units is not None else stock.site_units(site)
    return stock.scope_rows(units, period.end) + [
        ('feeding_records', FeedingRecord.all_objects.filter(unit__in=units, date__gte=period.start,
                                                             date__lte=period.end)),
        ('feeds', Feed.all_objects.filter(feedings__unit__in=units, feedings__date__gte=period.start,
                                          feedings__date__lte=period.end).distinct()),
    ]


def _feed(units, period, batches, cleaner):
    """The month's feed of the site's cleaner fish in kilos, dry and wet (Mattilsynet's tørrforKg and våtforKg, whole
    kilos), and per feed: each record's feed is split among the batches of its target (farm/feeding/read.py `fed`), so
    the salmon's feed is not the cleaner fish's."""
    fed = {key: kilos for key, kilos in feeding_read.fed(units, period.start, period.end).items()
           if key[1] in cleaner}
    feeds = Feed.all_objects.in_bulk({feed_id for _unit, _batch, feed_id in fed})
    per_feed = {}
    for (_unit, _batch, feed_id), kilos in fed.items():
        per_feed[feed_id] = per_feed.get(feed_id, ZERO) + kilos
    totals = {FeedForm.DRY: ZERO, FeedForm.WET: ZERO}
    for feed_id, kilos in per_feed.items():
        totals[feeds[feed_id].feed_form] += kilos
    return {'dry_kg': whole(totals[FeedForm.DRY]), 'wet_kg': whole(totals[FeedForm.WET]),
            'feeds': [{'feed': feeds[feed_id].name, 'form': feeds[feed_id].feed_form, 'kg': text(kilos, 1)}
                      for feed_id, kilos in sorted(per_feed.items(), key=lambda item: feeds[item[0]].name)]}

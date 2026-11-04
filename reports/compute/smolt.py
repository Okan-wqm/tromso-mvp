"""The monthly smolt report (Mattilsynet, akvakulturdriftsforskriften § 58; docs/regulatory-reports.md 1.3, 2.3):
per production unit that held fish in the month, its number, species, the fish at the month's end and their average
weight, and the fish culled, dead and moved out of the site in the month.

Read from the ledger: the fold at the month's last day; the month's lines (culls, deaths, transfers out whose other
end is on another site). A unit emptied in the month reports the fish and their average just before the operation
that emptied it, since the authority wants an average above 0 ("eller når produksjonsenheten ble tømt"; whether its
count is that one or 0 is unverified, D-8), less the fish moved that day to another unit of the site: those are in that
unit's count, and counting them twice would put them in the site's total twice. Moves between units of the site are not
reported ("Intern flytting mellom kar skal ikke rapporteres"). A unit that held fish of two species one after the other
in the month is listed once for each. Until a start-feeding rule is set (D-8), every unit holding fish is listed."""
from django.utils.translation import gettext as _

from farm.models import Batch, Tank
from farm.models.stock import MovementKind
from farm.stock import read

from . import stock
from .common import Result, identity, species_code, text, unit_number


def compute(site, period):
    problems, warnings = [], []
    units = stock.site_units(site)
    opening, closing, lines = read.in_period(units, period.start, period.end)
    emptied = stock.emptied_in(units, period.start, period.end)
    by_unit = {}
    for line in lines:
        by_unit.setdefault(line.unit_id, []).append(line)
    held = set(closing) | set(opening) | set(by_unit)
    others = {unit.pk: unit for unit in Tank.all_objects.filter(
        pk__in={line.other_unit_id for line in lines if line.other_unit_id}).select_related('production_department')}
    batches = Batch.all_objects.select_related('species').in_bulk(
        {line.batch_id for line in lines} | {share.batch.pk for found in (closing, opening) for unit_stock in
                                             found.values() for share in unit_stock.shares}
        | {batch_id for events in emptied.values() for event in events for batch_id in event.batches})

    def within_site(line):
        return others[line.other_unit_id].production_department.site_id == site.pk

    rows = {}
    for unit in units:
        if unit.pk not in held:
            continue
        unit_lines = by_unit.get(unit.pk, [])
        of_species = {}                       # {species: the batches of it the unit held in the month}
        for line in unit_lines:
            of_species.setdefault(batches[line.batch_id].species, set()).add(line.batch_id)
        for found in (closing, opening):
            if unit.pk in found:
                for share in found[unit.pk].shares:
                    of_species.setdefault(share.batch.species, set()).add(share.batch.pk)
        for event in emptied.get(unit.pk, []):
            for batch_id in event.batches:
                of_species.setdefault(batches[batch_id].species, set()).add(batch_id)
        if len(of_species) > 1:
            warnings.append(_('%(unit)s held more than one species in the month and is listed once for each: confirm '
                              'that Mattilsynet takes one tank number twice.') % {'unit': unit.code})
        for species, batch_ids in sorted(of_species.items(), key=lambda item: item[0].code):
            species_lines = [line for line in unit_lines if line.batch_id in batch_ids]
            average = None
            if unit.pk in closing and any(share.batch.pk in batch_ids for share in closing[unit.pk].shares):
                count, grams = stock.held(closing[unit.pk], batch_ids)
                average = grams / count
            elif (found := next((event for event in reversed(emptied.get(unit.pk, []))
                                 if any(batch_id in event.batches for batch_id in batch_ids)), None)) is not None:
                before, grams = found.of(batch_ids)
                average = grams / before
                moved_within = -sum(line.count for line in species_lines if line.operation_id == found.operation_id
                                    and line.kind == MovementKind.TRANSFER_OUT and within_site(line))
                count = max(before - moved_within, 0)
                warnings.append(_('%(unit)s was emptied on %(date)s: the fish and the average weight just before are '
                                  'reported (whether Mattilsynet wants that count or 0 is to be confirmed).') % {
                    'unit': unit.code, 'date': found.day.isoformat()})
                if moved_within:
                    warnings.append(_('%(fish)d of the fish of %(unit)s were moved on %(date)s to other units of the '
                                      'site: they are in those units’ counts, not in this one’s (its average weight is '
                                      'the one just before).') % {'fish': moved_within, 'unit': unit.code,
                                                                  'date': found.day.isoformat()})
            else:
                count = 0
            # Fish moved to another site, and fish delivered out of the company (D-10).
            out_of_site = [line for line in species_lines if line.kind == MovementKind.DELIVERY or (
                line.kind == MovementKind.TRANSFER_OUT and not within_site(line))]
            key = str(unit.pk) if len(of_species) == 1 else f'{unit.pk}/{species.code}'
            rows[key] = {
                'number': unit_number(unit),
                'species': species_code(species, problems),
                'fish_at_end': count,
                'avg_weight_g': text(average, 2) if average is not None else None,
                'culled': -sum(line.count for line in species_lines if line.kind == MovementKind.CULL),
                'died': -sum(line.count for line in species_lines if line.kind == MovementKind.MORTALITY),
                'moved_out_of_site': -sum(line.count for line in out_of_site),
                'lines': sorted(line.line_id for line in species_lines),
            }
            if average is None:
                problems.append(_('%(unit)s has no average weight to report (the authority wants one above 0).') % {
                    'unit': unit.code})
            other = [line for line in species_lines if line.kind in (MovementKind.HARVEST, MovementKind.ADJUSTMENT)]
            if other:
                warnings.append(_('%(unit)s has harvests or count adjustments in the month, which this report has no '
                                  'field for.') % {'unit': unit.code})
    if not rows:
        problems.append(_('No unit of the site held fish in the month: the report has nothing to file.'))
    warnings.append(_('Every unit that held fish is listed, eggs and larvae included; § 58 asks for the units of '
                      'start-feeding fry or older (D-8): leave out those that were not.'))
    content = {
        'kind': 'smolt', 'period': period.key, 'identity': identity(site, problems), 'units': rows,
    }
    return Result(content, problems, warnings, scope(site, period, units))


def scope(site, period, units=None):
    """The rows the month's figures are read from (for the fingerprint), without computing them."""
    return stock.scope_rows(units if units is not None else stock.site_units(site), period.end)

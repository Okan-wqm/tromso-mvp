"""The monthly smolt report (Mattilsynet, akvakulturdriftsforskriften § 58; docs/regulatory-reports.md 1.3, 2.3):
per production unit that held fish in the month, its number, species, the fish at the month's end and their average
weight, and the fish culled, dead and moved out of the site in the month.

Read from the ledger: the fold at the month's last day; the month's lines (culls, deaths, transfers out whose other
end is on another site). A unit emptied in the month reports the fish and their average just before the operation
that emptied it, since the authority wants an average above 0 ("eller når produksjonsenheten ble tømt"; whether its
count is that one or 0 is unverified, D-8). Moves between units of the site are not reported ("Intern flytting
mellom kar skal ikke rapporteres"). Until a start-feeding rule is set (D-8), every unit holding fish is listed."""
from django.utils.translation import gettext as _

from farm.models import Batch, Tank
from farm.models.stock import MovementKind
from farm.stock import read

from . import stock
from .common import Result, identity, species_code, text, unit_number


def compute(site, period):
    problems, warnings = [], []
    units = stock.site_units(site)
    closing = read.stock_on(units, period.end)
    opening = read.stock_on(units, stock.day_before(period))
    lines = read.movements(units, period.start, period.end)
    emptied = stock.emptied_in(units, period.start, period.end)
    by_unit = {}
    for line in lines:
        by_unit.setdefault(line.unit_id, []).append(line)
    held = set(closing) | set(opening) | set(by_unit)
    others = {unit.pk: unit for unit in Tank.all_objects.filter(
        pk__in={line.other_unit_id for line in lines if line.other_unit_id}).select_related('production_department')}
    batches = Batch.all_objects.select_related('species').in_bulk(
        {line.batch_id for line in lines} | {share.batch.pk for found in (closing, opening) for unit_stock in
                                             found.values() for share in unit_stock.shares})
    rows = {}
    for unit in units:
        if unit.pk not in held:
            continue
        unit_lines = by_unit.get(unit.pk, [])
        species = {batches[line.batch_id].species for line in unit_lines}
        for found in (closing, opening):
            if unit.pk in found:
                species |= {share.batch.species for share in found[unit.pk].shares}
        if len(species) != 1:
            problems.append(_('%(unit)s held more than one species in the month.') % {'unit': unit.code})
        kind = sorted(species, key=lambda item: item.code)[0]
        if unit.pk in closing:
            count, grams = closing[unit.pk].count, closing[unit.pk].grams
        elif unit.pk in emptied:
            count, grams = emptied[unit.pk].count, emptied[unit.pk].grams
            warnings.append(_('%(unit)s was emptied on %(date)s: the fish and the average weight just before are '
                              'reported (whether Mattilsynet wants that count or 0 is to be confirmed).') % {
                'unit': unit.code, 'date': emptied[unit.pk].day.isoformat()})
        else:
            count, grams = 0, None
        out_of_site = [line for line in unit_lines if line.kind == MovementKind.TRANSFER_OUT
                       and others[line.other_unit_id].production_department.site_id != site.pk]
        rows[str(unit.pk)] = {
            'number': unit_number(unit),
            'species': species_code(kind, problems),
            'fish_at_end': count,
            'avg_weight_g': text(grams / count, 2) if count else None,
            'culled': -sum(line.count for line in unit_lines if line.kind == MovementKind.CULL),
            'died': -sum(line.count for line in unit_lines if line.kind == MovementKind.MORTALITY),
            'moved_out_of_site': -sum(line.count for line in out_of_site),
            'lines': sorted(line.line_id for line in unit_lines),
        }
        if not count:
            problems.append(_('%(unit)s has no average weight to report (the authority wants one above 0).') % {
                'unit': unit.code})
        other = [line for line in unit_lines if line.kind in (MovementKind.HARVEST, MovementKind.ADJUSTMENT)]
        if other:
            warnings.append(_('%(unit)s has harvests or count adjustments in the month, which this report has no '
                              'field for.') % {'unit': unit.code})
    if not rows:
        problems.append(_('No unit of the site held fish in the month: the report has nothing to file.'))
    content = {
        'kind': 'smolt', 'period': period.key, 'identity': identity(site, problems), 'units': rows,
    }
    return Result(content, problems, warnings, stock.scope_rows(units, period.end))

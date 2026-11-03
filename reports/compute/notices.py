"""Notices: what a person tells an authority about an event, and Fiskeridirektoratet's notices for a land or freshwater
site (akvakulturdriftsforskriften § 44a; docs/regulatory-reports.md 1.1, 1.8).

A notice's narrative is the person's (the report's own columns: what happened, when it was found, the cause, the fish
dead, injured and involved, the situation now, the measures taken); the site's identity and what the records say
about its fish are read here. § 44a: a site taken into use (the day its first fish arrived and their species), a site
emptied (the day its last fish left), and in continuous operation the stock by species and year class each year."""
from django.utils.translation import gettext as _

from farm.models import Batch
from farm.models.stock import MovementKind
from farm.stock import read

from . import stock
from .common import Result, identity, species_code, year_class

NARRATIVE = ('what_happened', 'cause', 'fish_dead', 'fish_injured', 'fish_involved', 'situation', 'measures')


def event(report):
    """An event notice (a welfare event, for now; escape and disease read their event too): the narrative as the
    person wrote it."""
    problems = []
    content = {'kind': report.kind, 'occurred_on': report.occurred_on.isoformat() if report.occurred_on else None,
               'identity': identity(report.site, problems),
               'found_at': report.found_at.isoformat() if report.found_at else None,
               **{name: getattr(report, name) or None for name in NARRATIVE}}
    if not report.what_happened.strip():
        problems.append(_('Say what happened.'))
    if report.found_at is None:
        problems.append(_('Say when it was found.'))
    return Result(content, problems, [], [])


def site_change(report):
    """A site taken into use (its first fish in, and their species) or emptied (its last fish out), on the day."""
    problems = []
    site, day = report.site, report.occurred_on
    units = stock.site_units(site)
    lines = [line for line in read.movements(units, day, day)]
    batches = Batch.all_objects.select_related('species').in_bulk({line.batch_id for line in lines})
    species = sorted({species_code(batches[line.batch_id].species, problems) or '' for line in lines
                      if line.kind in (MovementKind.INPUT, MovementKind.TRANSFER_IN)})
    content = {'kind': report.kind, 'occurred_on': day.isoformat(), 'identity': identity(site, problems)}
    if report.kind == 'site_in_use':
        if not species:
            problems.append(_('No fish arrived at the site on that day.'))
        content['species'] = species
    elif read.stock_on(units, day):
        problems.append(_('The site still holds fish at the end of that day.'))
    return Result(content, problems, [], stock.scope_rows(units, day))


def land_stock(report):
    """The stock of a land or freshwater site at the year's end, by species and year class (§ 44a second paragraph)."""
    problems = []
    site, period = report.site, report.period
    units = stock.site_units(site)
    closing = read.stock_on(units, period.end)
    totals = {}
    for unit_stock in closing.values():
        for share in unit_stock.shares:
            key = (species_code(share.batch.species, problems) or '', year_class(share.batch, problems))
            totals[key] = totals.get(key, 0) + share.count
    content = {'kind': report.kind, 'period': period.key, 'identity': identity(site, problems),
               'stock': [{'species': code, 'year_class': year, 'fish': fish}
                         for (code, year), fish in sorted(totals.items(), key=str)]}
    return Result(content, problems, [], stock.scope_rows(units, period.end))

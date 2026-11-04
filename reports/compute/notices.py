"""Notices: what a person tells an authority about an event, and Fiskeridirektoratet's notices for a land or freshwater
site (akvakulturdriftsforskriften § 44a; docs/regulatory-reports.md 1.1, 1.8).

A notice's narrative is the person's (the report's own columns: what happened, when it was found, the cause, the fish
dead, injured and involved, the situation now, the measures taken); the site's identity and what the records say
about its fish are read here. § 44a: a site taken into use (the day its first fish arrived and their species), a site
emptied (the day its last fish left), and in continuous operation the stock by species and year class each year."""
from django.utils.translation import gettext as _

from farm.health.read import with_deaths
from farm.models import Batch, EscapeRecord, HealthEvent, StockOperation
from farm.models.stock import MovementKind
from farm.stock import read

from . import stock
from .common import Result, identity, species_code, text, unit_number, year_class

NARRATIVE = ('what_happened', 'cause', 'fish_dead', 'fish_injured', 'fish_involved', 'situation', 'measures')


def event(report):
    """An event notice (a disease or a welfare event): the narrative as the person wrote it and, when it is about a
    health event, what the health records say of it (its day, diagnosis, units and the deaths recorded under it)."""
    problems = []
    content = {'kind': report.kind, 'occurred_on': report.occurred_on.isoformat() if report.occurred_on else None,
               'identity': identity(report.site, problems),
               'found_at': report.found_at.isoformat() if report.found_at else None,
               **{name: getattr(report, name) or None for name in NARRATIVE}}
    if report.health_event_id:
        event = with_deaths(HealthEvent.all_objects.filter(pk=report.health_event_id)).prefetch_related(
            'units').get()
        content['health_event'] = {
            'id': str(event.pk), 'date': event.date.isoformat(), 'diagnosis': event.diagnosis or None,
            'confirmation': event.confirmation or None, 'deaths': event.deaths,
            'units': sorted(unit_number(unit) for unit in event.units.all())}
    if report.escape_id:
        content['escape'] = _escape(report.escape, problems)
    if not report.what_happened.strip():
        problems.append(_('Say what happened.'))
    if report.found_at is None and not report.escape_id:       # an escape has its day and time on its record
        problems.append(_('Say when it was found.'))
    return Result(content, problems, [], event_scope(report))


def event_scope(report):
    """The rows an event notice reads (for the fingerprint), without computing it: the health event and the operations
    that name it, the escape and its operation."""
    scope = []
    if report.health_event_id:
        scope += [('health_events', HealthEvent.all_objects.filter(pk=report.health_event_id)),
                  ('stock_operations', StockOperation.all_objects.filter(health_event_id=report.health_event_id))]
    if report.escape_id:
        scope += [('stock_operations', StockOperation.all_objects.filter(pk=report.escape_id)),
                  ('escape_records', EscapeRecord.all_objects.filter(pk=report.escape_id))]
    return scope


def _escape(escape, problems):
    """What the escape record and its line say of the fish that escaped: the day (and time found), the unit, the species,
    the fish and their average weight (the fold's), the cause, their health status and the fish recaptured."""
    operation = StockOperation.all_objects.get(pk=escape.operation_id)
    line = operation.movements.select_related('unit', 'batch__species').get()
    moved = next((item for item in read.movements([line.unit], operation.date, operation.date)
                  if item.line_id == line.pk), None)         # none once the escape is voided
    if operation.is_deleted:
        problems.append(_('The escape was voided: the stock no longer says these fish escaped.'))
    fish = -line.count_delta
    found = {
        'id': str(operation.pk), 'date': operation.date.isoformat(),
        'found_time': escape.found_time.strftime('%H:%M') if escape.found_time else None,
        'suspected': escape.suspected, 'unit': unit_number(line.unit),
        'species': species_code(line.batch.species, problems), 'fish': fish,
        'avg_weight_g': text(abs(moved.grams) / fish, 1) if moved is not None and moved.grams is not None else None,
        'cause': escape.cause, 'health_status': escape.health_status or None, 'recaptured': escape.recaptured}
    return found


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
    return Result(content, problems, [], site_change_scope(report))


def site_change_scope(report):
    return stock.scope_rows(stock.site_units(report.site), report.occurred_on)


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
    return Result(content, problems, [], land_stock_scope(report))


def land_stock_scope(report):
    return stock.scope_rows(stock.site_units(report.site), report.period.end)

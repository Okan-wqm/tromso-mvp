"""What is due: which reports and notices the farm owes the authorities now, read from the records, never stored
(docs/regulatory-reports.md, 5.2).

A site owes reports by what it produces and what it holds. Its **production form** (juveniles, food fish, broodstock) and
its type decide which, its **reports-from** date says from when they are listed (the periods before were filed elsewhere), and
the fish it held decide which periods: a week or month in which it held no fish of the kind owes nothing. A site that holds fish
and has no reports-from date or no production form is listed as "not set up for reports", never hidden. The periods run from
the reports-from date to the last closed one, minus those that have a filed report; a draft stays listed with its deadline
and an overdue mark. Slaughter is owed per slaughter facility and week from the harvest plan, an escape or a disease from the
records of it with no filed notice. Every date is a calendar day in Europe/Oslo, whatever clock a site keeps.

Nothing here computes a figure of a report: that is reports/compute; this decides only which reports exist to be started."""
from dataclasses import dataclass, field
from datetime import date, timedelta

from django.conf import settings

from django.db.models import Exists, OuterRef, Q

from farm.health import diseases, notices
from farm.models import Batch, EscapeRecord, HandlingPlanItem, HealthEvent, Site, StockMovement, Tank
from farm.models.harvest import PlanKind
from farm.models.species import SALMONID_CODES
from farm.stock.read import Presence

from . import compute, periods
from .kinds import KINDS, ReportKind
from .models import Report

SEA_SITE = Site.Type.SEA_CAGE
PRODUCTION_FORM = Site.ProductionForm
ANY, SALMONID, CLEANER, PRODUCTION = 'any', 'salmonid', 'cleaner', 'production'


@dataclass(frozen=True)
class DueRow:
    """One report owed: its kind, for whom (a site, a slaughter facility), the period (None for a notice), the deadline
    (None for a notice, which is filed at once), whether the deadline has passed, the draft already started (or None), and
    the health event or escape a notice is about."""
    kind: str
    place: object
    period: object = None
    deadline: date = None
    overdue: bool = False
    report: object = None
    event: object = None

    @property
    def start_query(self):
        """The new-report page's address query that starts it: ?kind=&site= (or &facility=), &period=, &health_event= or
        &escape=."""
        query = {'kind': self.kind}
        if self.kind in (ReportKind.DISEASE, ReportKind.WELFARE):
            query['health_event'] = self.event.pk
        elif self.kind == ReportKind.ESCAPE:
            query['escape'] = self.event.pk
        else:
            query['facility' if self.kind == ReportKind.SLAUGHTER_PLANNED else 'site'] = self.place.pk
        if self.period is not None:
            query['period'] = self.period.key
        return query


@dataclass
class SetUp:
    """A site that holds fish and is not set up for its reports: what is missing (its reports-from date, its production
    form, the official code of the species it holds: a species without one is not known to be a salmonid)."""
    site: object
    reports_from: bool = False
    production_form: bool = False
    species: list = field(default_factory=list)


@dataclass
class DueList:
    rows: list = field(default_factory=list)
    not_set_up: list = field(default_factory=list)


def owed(site):
    """[(kind, the fish that make it owed)] a site owes by its type and production form. Sea lice follow the salmonids at a
    sea site whatever it produces (§ 2 lakselusforskriften); the others follow the production form (D-13): juveniles the
    smolt report, food fish and broodstock at sea the monthly biomass, food fish at sea the cleaner fish too, and on land
    or in fresh water the yearly stock (§ 44a)."""
    sea = site.type == SEA_SITE
    form = site.production_form
    found = [(ReportKind.SEA_LICE, SALMONID)] if sea else []
    if form == PRODUCTION_FORM.SETTEFISK:
        found.append((ReportKind.SMOLT, ANY))
    if sea:
        # The cleaner-fish report is owed by every sea site whatever its permit (Altinn: "Gjelder alle typer
        # akvakulturtillatelser ... for fisk med produksjon i sjøvann").
        found.append((ReportKind.CLEANER_FISH, CLEANER))
    if form in (PRODUCTION_FORM.MATFISK, PRODUCTION_FORM.STAMFISK):
        found.append((ReportKind.BIOMASS, PRODUCTION) if sea else (ReportKind.LAND_STOCK, ANY))
    elif form == PRODUCTION_FORM.SETTEFISK and not sea:
        # Cleaner-fish juveniles and broodstock on land are under § 44a too (§ 3 i).
        found.append((ReportKind.LAND_STOCK, CLEANER))
    return found


def _category(batch):
    species = batch.species
    return {SALMONID: species.official_code in SALMONID_CODES, CLEANER: species.is_cleaner_fish,
            PRODUCTION: not species.is_cleaner_fish, ANY: True}


def due(today=None):
    """The DueList as of `today` (in Oslo)."""
    today = today or periods.oslo_today()
    found = DueList()
    existing = _existing()
    for site in Site.objects.order_by('name'):
        _site(site, today, existing, found)
    _slaughter(today, existing, found.rows)
    _escapes(today, existing, found.rows)
    _diseases(today, existing, found.rows)
    found.rows.sort(key=lambda row: (not row.overdue, row.deadline or date.min, str(row.kind), str(row.place)))
    return found


def _existing():
    """{(kind, site id, facility id, period start, event id): the live original report} of every report started."""
    index = {}
    for report in Report.objects.filter(corrects__isnull=True):
        key = (report.kind, report.site_id, report.facility_id, report.period_start,
               report.health_event_id or report.escape_id)
        index[key] = report
    return index


def _row(kind, place, period, today, existing, event=None, agreed=None):
    """The row of a report owed, or None when it was filed already."""
    key = (kind, place.pk if isinstance(place, Site) else None,
           place.pk if kind == ReportKind.SLAUGHTER_PLANNED else None, period.start if period else None,
           event.pk if event is not None else None)
    report = existing.get(key)
    if report is not None and report.submitted_at is not None:
        return None
    rule = KINDS[kind].deadline
    deadline = rule(period) if rule and period else None
    if kind == ReportKind.SLAUGHTER_PLANNED:
        deadline = compute.slaughter.deadline(place, period, deadline)
        if agreed is not None:
            deadline = max(deadline, agreed)      # a slaughter agreed late is reported as soon as it is agreed
    return DueRow(kind, place, period, deadline, deadline is not None and today > deadline, report, event)


def _site(site, today, existing, found):
    """The rows of a site: the periods from its reports-from date to the last closed one in which it held the fish of each
    kind it owes, or what is missing for it to be listed."""
    kinds = owed(site)
    units = list(Tank.all_objects.filter(production_department__site=site))
    holds = bool(units) and StockMovement.objects.filter(unit__in=units, operation__is_deleted=False).exists()
    presence = Presence.of_units([unit.pk for unit in units])
    batches = Batch.all_objects.select_related('species').in_bulk({batch for _unit, batch in presence.timelines})
    uncoded = sorted({str(batch.species) for batch in batches.values() if not batch.species.official_code})
    if site.reports_from is None or not site.production_form or uncoded:
        if holds:
            found.not_set_up.append(SetUp(site, reports_from=site.reports_from is None,
                                          production_form=not site.production_form, species=uncoded))
        if site.reports_from is None or not kinds:
            return
    for kind, fish in kinds:
        grain = KINDS[kind].grain
        first = site.reports_from
        for period in periods.periods_between(grain, first, today - timedelta(days=1)):
            if period.end >= today:
                continue                                  # a period still open is owed when it has closed
            if not any(_category(batches[batch])[fish] and presence.present_between(unit, batch, period.start, period.end)
                       for unit, batch in presence.timelines):
                continue
            row = _row(kind, site, period, today, existing)
            if row is not None:
                found.rows.append(row)


def _slaughter(today, existing, rows):
    """A planned slaughter per facility and week, from this week on, for the open harvest plans."""
    items = HandlingPlanItem.objects.filter(kind=PlanKind.HARVEST, cancelled_reason='', operation__isnull=True,
                                            facility__isnull=False, date__gte=periods.week_start(today)
                                            ).select_related('facility')
    weeks = {}
    agreed = {}
    for item in items:
        key = (item.facility_id, periods.Period.of(periods.WEEK, item.date))
        weeks[key] = item.facility
        day = periods.oslo_today(item.created_at)
        agreed[key] = min(agreed.get(key, day), day)
    for (_facility, period), facility in weeks.items():
        row = _row(ReportKind.SLAUGHTER_PLANNED, facility, period, today, existing,
                   agreed=agreed[(_facility, period)])
        if row is not None:
            rows.append(row)


def _escapes(today, existing, rows):
    """An escape since its site's reports-from date (D-6) with no filed notice."""
    escapes = list(EscapeRecord.objects.select_related('operation'))
    lines = {}
    for line in (StockMovement.objects.filter(operation__in=[escape.operation_id for escape in escapes])
                 .select_related('unit__production_department__site').order_by('id')):
        lines.setdefault(line.operation_id, line)
    for escape in escapes:
        site = lines[escape.operation_id].unit.production_department.site if escape.operation_id in lines else None
        if site is None or site.reports_from is None or escape.operation.date < site.reports_from:
            continue
        row = _row(ReportKind.ESCAPE, site, None, today, existing, escape)
        if row is not None:
            rows.append(row)


def _diseases(today, existing, rows):
    """A health event of a listed disease, suspected or confirmed, since its site's reports-from date with no filed notice
    (the health records' own rule, farm/health/notices.py: asked once for all the events)."""
    events = list(HealthEvent.objects.filter(diagnosis__in=diseases.NOTIFIABLE).select_related('site'))
    for event in notices.pending(events) or []:
        if event.site.reports_from is None or event.date < event.site.reports_from:
            continue
        row = _row(ReportKind.DISEASE, event.site, None, today, existing, event)
        if row is not None:
            rows.append(row)


def no_longer_match(today=None):
    """The filed reports, not replaced by a correction, whose records have changed since they were filed. Only the rows a
    report reads are compared (compute.scope), never its figures; a report of a period that closed before the
    STOCK_BACKDATE_DAYS window cannot change and is not read again, a notice (it has no period) always is."""
    today = today or periods.oslo_today()
    recent = today - timedelta(days=settings.STOCK_BACKDATE_DAYS)
    filed = (Report.objects.filter(submitted_at__isnull=False).exclude(snapshot__format_version=0)
             .filter(Q(period_start__isnull=True) | Q(period_start__gte=recent - timedelta(days=366)))   # a year at most
             .annotate(has_filed_correction=Exists(Report.objects.filter(corrects=OuterRef('pk'),
                                                                         submitted_at__isnull=False)))
             .select_related('snapshot', 'site', 'facility').defer('snapshot__content'))
    found = []
    for report in filed:
        # A period older than the backdating window cannot change; a notice has no window and is always read again.
        if report.is_superseded or report.period and report.period.end < recent:
            continue
        if compute.fingerprint(compute.scope(report)) != report.snapshot.sources_fingerprint:
            found.append(report)
    return found

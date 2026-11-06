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

from django.db.models import Exists, OuterRef, Prefetch, Q

from farm.health import diseases, notices
from django.utils.translation import gettext as _, gettext_lazy

from farm.models import (
    Batch, EscapeRecord, HandlingPlanItem, HarvestRecord, HealthEvent, Site, SlaughterFacility, StockMovement, Tank,
)
from farm.models.harvest import FacilityStatus, PlanKind
from farm.models.species import SALMONID_CODES
from farm.stock.read import Presence

from . import compute, periods
from .kinds import EVENTS, KINDS, PERIODIC, ReportKind
from . import duties
from .models import DueClosure, OutsideDutyDone, Report

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


DUE, UP_TO_DATE, NOT_DUE = 'due', 'up_to_date', 'not_due'
# The kinds of a site, the periodic ones first; a slaughter facility has the planned slaughter alone.
SITE_KINDS = tuple(kind for kind in PERIODIC if KINDS[kind].scope == 'site') + EVENTS
NO_FISH = {SALMONID: gettext_lazy('no salmonids in the sea at %(site)s since %(date)s'),
           CLEANER: gettext_lazy('no cleaner fish held at %(site)s since %(date)s'),
           PRODUCTION: gettext_lazy('no production fish held at %(site)s since %(date)s'),
           ANY: gettext_lazy('no fish held at %(site)s since %(date)s')}


@dataclass(frozen=True)
class Line:
    """Where one kind of report stands for one site or facility: due (`count` of them), up to date, or not due, and in
    plain words why when nothing is due."""
    kind: str
    place: object
    status: str
    reason: str = ''
    count: int = 0


@dataclass
class DueList:
    rows: list = field(default_factory=list)
    not_set_up: list = field(default_factory=list)
    lines: list = field(default_factory=list)
    closed: list = field(default_factory=list)
    duties: list = field(default_factory=list)       # reports.duties.DutyLine: the annual duties outside this system

    def lines_of(self, kind):
        return [line for line in self.lines if line.kind == kind]


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
    found.closed = list(DueClosure.objects.select_related('site', 'facility', 'closed_by'))
    sites = list(Site.objects.order_by('name'))
    for site in sites:
        _site(site, today, existing, found)
    _slaughter(today, existing, found.rows)
    _escapes(today, existing, found.rows)
    _diseases(today, existing, found.rows)
    _unexplained(today, existing, found.rows)
    _lines_of_notices(sites, found)
    _lines_of_slaughter(found)
    found.rows.sort(key=lambda row: (not row.overdue, row.deadline or date.min, str(row.kind), str(row.place)))
    found.duties.sort(key=lambda line: (line.status != duties.OVERDUE, line.deadline, line.site.name, line.duty.code))
    return found


class Existing(dict):
    """The reports started, by key, and the keys a person closed with a reason (DueClosure): neither is owed."""
    closed = frozenset()
    done = {}


def _existing():
    """{(kind, site id, facility id, period start, event id): the live original report} of every report started."""
    index = Existing()
    index.done = {(record.duty, record.site_id, record.year): record
                  for record in OutsideDutyDone.objects.select_related('recorded_by')}
    index.closed = frozenset((closure.kind, closure.site_id, closure.facility_id, closure.period_start, None)
                             for closure in DueClosure.objects.all())
    for report in Report.objects.filter(corrects__isnull=True):
        key = (report.kind, report.site_id, report.facility_id, report.period_start,
               report.health_event_id or report.escape_id)
        index[key] = report
    return index


def _row(kind, place, period, today, existing, event=None):
    """The row of a report owed, or None when it was filed already."""
    key = (kind, place.pk if isinstance(place, Site) else None,
           place.pk if kind == ReportKind.SLAUGHTER_PLANNED else None, period.start if period else None,
           event.pk if event is not None else None)
    report = existing.get(key)
    if report is not None and report.submitted_at is not None or key in existing.closed:
        return None
    deadline = compute.deadline_of(kind, place, period)          # the one deadline (F-101)
    return DueRow(kind, place, period, deadline, deadline is not None and today > deadline, report, event)


def _site(site, today, existing, found):
    """The rows of a site: the periods from its reports-from date to the last closed one in which it held the fish of each
    kind it owes, or what is missing for it to be listed; and a line for each periodic kind, owed or not, with the reason
    when nothing is due."""
    owed_kinds = dict(owed(site))
    units = list(Tank.all_objects.filter(production_department__site=site))
    holds = bool(units) and StockMovement.objects.filter(unit__in=units, operation__is_deleted=False).exists()
    presence = Presence.of_units([unit.pk for unit in units])
    batches = Batch.all_objects.select_related('species').in_bulk({batch for _unit, batch in presence.timelines})
    uncoded = sorted({str(batch.species) for batch in batches.values() if not batch.species.official_code})
    if (site.reports_from is None or not site.production_form or uncoded) and holds:
        found.not_set_up.append(SetUp(site, reports_from=site.reports_from is None,
                                      production_form=not site.production_form, species=uncoded))
    salmonids = any(_category(batch)[SALMONID] for batch in batches.values())
    found.duties.extend(duties.lines_of(site, today, existing.done, salmonids))
    for kind in SITE_KINDS:
        if KINDS[kind].grain == 'event':
            continue
        if kind not in owed_kinds:
            found.lines.append(Line(kind, site, NOT_DUE, _not_owed(site, kind)))
        elif site.reports_from is None:
            found.lines.append(Line(kind, site, NOT_DUE, _('no reports-from date: its periods are not counted')))
        else:
            found.lines.append(_periodic_line(site, kind, owed_kinds[kind], today, existing, presence, batches, found))


def _periodic_line(site, kind, fish, today, existing, presence, batches, found):
    """The rows owed of a periodic kind at a site, added to the list, and its line."""
    rows, with_fish, open_fish = [], 0, False
    for period in periods.periods_between(KINDS[kind].grain, site.reports_from, today - timedelta(days=1)):
        if not any(_category(batches[batch])[fish] and presence.present_between(unit, batch, period.start, period.end)
                   for unit, batch in presence.timelines):
            continue
        if period.end >= today:
            open_fish = True                          # a period still open is owed when it has closed
            continue
        with_fish += 1
        row = _row(kind, site, period, today, existing)
        if row is not None:
            rows.append(row)
    found.rows.extend(rows)
    if rows:
        return Line(kind, site, DUE, count=len(rows))
    if with_fish:
        return Line(kind, site, UP_TO_DATE, _('every period since %(date)s with fish is filed') % {
            'date': site.reports_from.isoformat()})
    if open_fish:
        return Line(kind, site, NOT_DUE, _('owed once the month or week now running has closed'))
    return Line(kind, site, NOT_DUE, NO_FISH[fish] % {'site': site.name, 'date': site.reports_from.isoformat()})


def _not_owed(site, kind):
    """Why a site does not owe a periodic kind: its type or its production form (the same rules `owed` applies)."""
    if kind in (ReportKind.SEA_LICE, ReportKind.CLEANER_FISH):
        return _('%(site)s is not a sea site') % {'site': site.name}
    if not site.production_form:
        return _('site not set up: no production form')
    if site.production_form == PRODUCTION_FORM.OTHER:
        # Chapters 1, 2, 3 and 7 only apply to "annen produksjon" (§ 3 l); what else follows is not known (Q10).
        return _('research or other production reports none of the juvenile, biomass or yearly stock reports (§ 3 l: '
                 'only chapters 1, 2, 3 and 7 apply to it; unverified, Q10)')
    if kind == ReportKind.SMOLT:
        return _('%(site)s is not a juvenile (settefisk) site') % {'site': site.name}
    if kind == ReportKind.BIOMASS:
        if site.production_form == PRODUCTION_FORM.SETTEFISK:
            return _('a juvenile site reports smolt, not the monthly biomass')
        return _('%(site)s is on land: it reports its yearly stock') % {'site': site.name}
    if site.type == SEA_SITE:
        return _('%(site)s is at sea: it reports the monthly biomass') % {'site': site.name}
    return _('only a site of food fish, broodstock or cleaner-fish juveniles on land reports it')


def _lines_of_notices(sites, found):
    """The lines of the notices of every site: an escape or a listed disease owed, or why none is; a welfare event and the
    two notices of a land site are started by a person when something happens."""
    counts = {}
    for row in found.rows:
        if row.kind in (ReportKind.ESCAPE, ReportKind.DISEASE, ReportKind.WELFARE):
            counts[(row.kind, row.place.pk)] = counts.get((row.kind, row.place.pk), 0) + 1
    nothing = {ReportKind.ESCAPE: _('no escape without a filed notice since %(date)s'),
               ReportKind.DISEASE: _('no listed disease without a filed notice since %(date)s')}
    for site in sites:
        for kind in EVENTS:
            if kind in nothing:
                if site.reports_from is None:
                    found.lines.append(Line(kind, site, NOT_DUE, _('no reports-from date: nothing is counted')))
                elif counts.get((kind, site.pk)):
                    found.lines.append(Line(kind, site, DUE, count=counts[(kind, site.pk)]))
                else:
                    found.lines.append(Line(kind, site, NOT_DUE, nothing[kind] % {
                        'date': site.reports_from.isoformat()}))
            elif kind == ReportKind.WELFARE:
                if counts.get((kind, site.pk)):
                    found.lines.append(Line(kind, site, DUE, count=counts[(kind, site.pk)]))
                else:
                    found.lines.append(Line(kind, site, NOT_DUE, _(
                        'no increased mortality has stayed unexplained for 14 days; otherwise started by a person '
                        'when an event happens')))
            elif not site.production_form:
                found.lines.append(Line(kind, site, NOT_DUE, _('site not set up: no production form')))
            elif site.type != SEA_SITE and site.production_form in (PRODUCTION_FORM.MATFISK, PRODUCTION_FORM.STAMFISK):
                found.lines.append(Line(kind, site, NOT_DUE, _('started by a person when it happens')))
            else:
                found.lines.append(Line(kind, site, NOT_DUE,
                                        _('only a site of food fish or broodstock on land reports it')))


def _lines_of_slaughter(found):
    """The planned slaughter of every active slaughter facility (and any other that has a plan): due, or why not."""
    counts = {}
    for row in found.rows:
        if row.kind == ReportKind.SLAUGHTER_PLANNED:
            counts[row.place.pk] = counts.get(row.place.pk, 0) + 1
    facilities = SlaughterFacility.objects.filter(
        Q(status=FacilityStatus.ACTIVE) | Q(pk__in=list(counts))).order_by('name')
    for facility in facilities:
        if counts.get(facility.pk):
            found.lines.append(Line(ReportKind.SLAUGHTER_PLANNED, facility, DUE, count=counts[facility.pk]))
        else:
            found.lines.append(Line(ReportKind.SLAUGHTER_PLANNED, facility, NOT_DUE,
                                    _('no planned or recorded harvest to %(facility)s is waiting for its notice') % {
                                        'facility': facility.name}))


def _slaughter(today, existing, rows):
    """A planned slaughter per facility and week, from the first week the site reports (its reports-from date): the duty
    arises from the harvest, planned or done (restkontrollforskriften § 9a), so a harvest that was never planned owes it
    too, and a week stays owed after it has passed until the notice is filed or a person closes it with a reason."""
    weeks = {}
    # Open or done: a plan whose harvest was voided is planned again and still owed.
    plans = (HandlingPlanItem.objects.filter(kind=PlanKind.HARVEST, cancelled_reason='', facility__isnull=False)
             .select_related('facility', 'unit__production_department__site'))
    for item in plans:
        site = item.unit.production_department.site
        if site is None or site.reports_from is None or item.date < site.reports_from:
            continue
        key = (item.facility_id, periods.Period.of(periods.WEEK, item.date))
        weeks[key] = item.facility
    lines = Prefetch('operation__movements', StockMovement.objects.select_related(
        'unit__production_department__site').order_by('id'))
    records = list(HarvestRecord.objects.select_related('facility', 'operation').prefetch_related(lines))
    from_plans = compute.slaughter.plans_of(record.operation_id for record in records)   # owed with their plan
    for record in records:
        if record.operation_id in from_plans:
            continue
        first = next(iter(record.operation.movements.all()), None)
        site = first.unit.production_department.site if first is not None else None
        if site is None or site.reports_from is None or record.operation.date < site.reports_from:
            continue
        weeks.setdefault((record.facility_id, periods.Period.of(periods.WEEK, record.operation.date)), record.facility)
    for (_facility_id, period), facility in weeks.items():
        row = _row(ReportKind.SLAUGHTER_PLANNED, facility, period, today, existing)
        if row is not None:
            rows.append(row)


def _escapes(today, existing, rows):
    """An escape since its site's reports-from date (D-6) with no filed notice."""
    lines = Prefetch('operation__movements', StockMovement.objects.select_related(
        'unit__production_department__site').order_by('id'))
    for escape in EscapeRecord.objects.select_related('operation').prefetch_related(lines):
        first = next(iter(escape.operation.movements.all()), None)
        site = first.unit.production_department.site if first is not None else None
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


REASSESS_DAYS = 14          # dyrehelseforskriften § 7 second paragraph: a new assessment within 14 days


def _unexplained(today, existing, rows):
    """A welfare notice for an increased-mortality event still unexplained after the 14 days the regulation gives for the
    vet's reassessment (§ 7 second paragraph: notify as soon as practicable when the cause is still unclear after it). The
    records model it as a health event of the kind increased mortality with no diagnosis and not closed: giving the event a
    diagnosis, or closing it with its outcome, says the cause is clear and ends the duty. The system holds no field for
    the reassessment itself, only these two ways to say it is explained. Other signs of disease and a reduced production
    rate, which the paragraph also names, are not events the records hold."""
    events = list(HealthEvent.objects.filter(
        kind=HealthEvent.Kind.MORTALITY, diagnosis='', closed_on__isnull=True,
        date__lte=today - timedelta(days=REASSESS_DAYS)).select_related('site'))
    told = notices.told(events) or {}
    for event in events:
        if event.pk in told or event.site.reports_from is None or event.date < event.site.reports_from:
            continue
        row = _row(ReportKind.WELFARE, event.site, None, today, existing, event)
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

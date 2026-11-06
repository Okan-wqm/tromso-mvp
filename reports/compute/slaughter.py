"""The weekly planned-slaughter report (Mattilsynet, restkontrollforskriften § 9a; docs/regulatory-reports.md 1.6, 2.6):
for a slaughter facility and an ISO week, the kilos planned each weekday per locality and species, from the harvest
plan (Operations › Harvest › Harvest plan: planned harvests to the facility in the week, not cancelled).

The planned kilos are the plan's round kilos (whether Mattilsynet's planned kilos are round or gutted is unverified);
a plan's day is the day the fish leave the unit, which can differ from the slaughter day when they wait in a wellboat
or the slaughterhouse's pens: the page shows the days for the person to check (D-3). The deadline is the earlier of
Thursday 24:00 of the week before and the day the fish start fasting for the first harvest of the week."""
import re
from collections import defaultdict
from decimal import Decimal
from typing import NamedTuple

from django.utils.translation import gettext as _

from farm.handling.fasting import fast_of
from farm.models import HandlingPlanItem, Site, SlaughterFacility, StockMovement, StockOperation, Tank
from farm.models.stock import OperationKind

from .. import periods
from ..kinds import KINDS, ReportKind
from .common import Result, identity, note, species_code, whole

WEEKDAYS = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')
ZERO = Decimal(0)


class Entry(NamedTuple):
    """A harvest of the week as the report reads it: planned (a plan item, with its planned kilos) or never planned (a
    harvest recorded with no plan item: its weighed kilos)."""
    id: str
    unit: object
    batch: object
    date: object
    planned_kg: object
    planned: bool


def items_of(facility, period):
    """The planned harvests to the facility in the week, not cancelled, live (a deleted unit hides its items)."""
    return list(HandlingPlanItem.objects.filter(kind=HandlingPlanItem.Kind.HARVEST, facility=facility,
                                                date__gte=period.start, date__lte=period.end, cancelled_reason='')
                .select_related('unit__production_department__site', 'batch__species',
                                'operation__harvest_record__facility')
                .order_by('date', 'created_at'))


def plans_of(operation_ids):
    """THE planned-vs-done rule (audit F-085, F-227, F-238): {harvest operation id: the plan item it fulfils} of those of
    `operation_ids` recorded from a plan (a live harvest plan, not cancelled). Such a harvest is its plan's in the
    planned-slaughter report, whatever its own day and facility: owed in the plan's week and facility (reports/due.py),
    counted once there as planned, never again as not planned where it was really done; a harvest without a plan is its
    own week's and facility's, unplanned."""
    return {item.operation_id: item for item in HandlingPlanItem.objects.filter(
        kind=HandlingPlanItem.Kind.HARVEST, cancelled_reason='', operation_id__in=list(operation_ids))
        .select_related('facility', 'unit')}


def moved(item, period):
    """Whether a plan item was recorded in another week or at another facility than planned."""
    operation = item.operation if item.done else None
    if operation is None:
        return False
    record = getattr(operation, 'harvest_record', None)
    return not (period.start <= operation.date <= period.end) or (record is not None and
                                                                   record.facility_id != item.facility_id)


def _harvests_of(facility, period):
    return StockOperation.objects.filter(kind=OperationKind.HARVEST, harvest_record__facility=facility,
                                         date__gte=period.start, date__lte=period.end).order_by('date', 'created_at')


def unplanned_of(facility, period):
    """The harvests to the facility in the week that fulfil no plan (plans_of): the fish went and nobody planned them
    (the duty arises from the harvest, § 9a), read from the harvest's own weighed kilos."""
    operations = list(_harvests_of(facility, period))
    planned = plans_of(operation.pk for operation in operations)
    found = []
    for operation in (each for each in operations if each.pk not in planned):
        for line in (StockMovement.objects.filter(operation=operation, kind='harvest')
                     .select_related('unit__production_department__site', 'batch__species').order_by('id')):
            found.append(Entry(str(operation.pk), line.unit, line.batch, operation.date, line.measured_weight_kg, False))
    return found


def entries_of(facility, period):
    """Every harvest of the week the report is about: the planned ones, then the unplanned."""
    items = items_of(facility, period)
    return [Entry(str(item.pk), item.unit, item.batch, item.date, item.planned_kg, True) for item in items] + \
        unplanned_of(facility, period)


def _moved_warnings(facility, period, warnings):
    """Where the harvests of a plan recorded elsewhere went (plans_of): said in the plan's report, which counts it, and in
    the report of the week and facility it was really done in, which does not."""
    for item in items_of(facility, period):
        if moved(item, period):
            record = getattr(item.operation, 'harvest_record', None)
            warnings.append(_('The planned harvest of %(unit)s on %(planned)s was recorded on %(date)s at %(facility)s: it '
                              'is reported here as planned; correct the notice if it was filed.') % {
                'unit': item.unit.code, 'planned': item.date.isoformat(), 'date': item.operation.date.isoformat(),
                'facility': record.facility.name if record is not None else '–'})
    operations = list(_harvests_of(facility, period))
    planned = plans_of(operation.pk for operation in operations)
    for operation in operations:
        item = planned.get(operation.pk)
        if item is not None and (item.facility_id != facility.pk or not period.start <= item.date <= period.end):
            warnings.append(_('The harvest of %(unit)s on %(date)s is the plan of %(planned)s at %(facility)s: it is '
                              'reported with that plan, not here.') % {
                'unit': item.unit.code, 'date': operation.date.isoformat(), 'planned': item.date.isoformat(),
                'facility': item.facility.name})


def compute(facility, period):
    problems, warnings = [], []
    items = entries_of(facility, period)
    _moved_warnings(facility, period, warnings)
    sites = {}
    planned = defaultdict(lambda: ZERO)
    for item in items:
        site = item.unit.production_department.site
        if site is None:
            problems.append(_('%(unit)s is on no site.') % {'unit': item.unit.code})
            continue
        sites[site.pk] = site
        code = species_code(item.batch.species, problems)
        if not item.planned:
            warnings.append(_('The harvest of %(unit)s on %(date)s was not planned: its weighed kilos are reported, '
                              'late.') % {'unit': item.unit.code, 'date': item.date.isoformat()})
        if item.planned_kg is None:
            problems.append(_('The planned harvest of %(unit)s on %(date)s has no planned kilos (Operations › Harvest '
                              '› Harvest plan).') % {'unit': item.unit.code, 'date': item.date.isoformat()})
            continue
        planned[(site.pk, code, WEEKDAYS[item.date.isoweekday() - 1])] += item.planned_kg
    localities = {}
    for site in sorted(sites.values(), key=lambda site: site.name):
        species = {}
        for (site_id, code, weekday), kilos in planned.items():
            if site_id == site.pk:
                species.setdefault(code or '', {day: None for day in WEEKDAYS})[weekday] = whole(kilos)
        localities[str(site.pk)] = {**identity(site, problems), 'species': species}
    if not items:
        problems.append(_('No harvest to this facility is planned in the week.'))
    warnings.append(_('The days are the days the fish leave their units: check they are the slaughter days.'))
    filer = _filer(facility)
    if filer is None:
        note(problems, _('%(facility)s has no company that files for it with a 9-digit organisation number (Purchasing › '
                         'Suppliers, the operator of Slaughter facilities).') % {'facility': facility})
    content = {
        'kind': 'slaughter_planned', 'period': period.key,
        'facility': {'name': facility.name, 'approval_number': facility.approval_number, 'organisation_number': filer},
        'localities': localities, 'items': [item.id for item in items],
    }
    return Result(content, problems, warnings, scope(facility, period, items))


def scope(facility, period, items=None):
    """The rows the week's figures are read from (for the fingerprint), without computing them."""
    items = items if items is not None else entries_of(facility, period)
    sites = {item.unit.production_department.site_id for item in items if item.unit.production_department.site_id}
    return [
        ('plan_items', HandlingPlanItem.all_objects.filter(kind=HandlingPlanItem.Kind.HARVEST, facility=facility,
                                                           date__gte=period.start, date__lte=period.end)),
        ('harvests', StockOperation.all_objects.filter(kind=OperationKind.HARVEST, harvest_record__facility=facility,
                                                       date__gte=period.start, date__lte=period.end)),
        # The harvests the week's plans were recorded as, wherever and whenever they were done (plans_of).
        ('planned_harvests', StockOperation.all_objects.filter(
            plan_items__kind=HandlingPlanItem.Kind.HARVEST, plan_items__facility=facility,
            plan_items__date__gte=period.start, plan_items__date__lte=period.end).distinct()),
        ('facility', SlaughterFacility.all_objects.filter(pk=facility.pk)),
        ('sites', Site.all_objects.filter(pk__in=sites)),
        ('units', Tank.all_objects.filter(pk__in={item.unit.pk for item in items})),
    ]


def _filer(facility):
    """The organisation number of the company that files for the slaughterhouse (the report's own
    `organisasjonsnummer`: "selskapet som rapporterer planlagt slakt"): its operator's, nine digits; never taken from the
    farms whose fish it slaughters. None when the facility has no operator or its number is not nine digits."""
    operator = facility.operator
    found = re.fullmatch(r'(?:NO)?([0-9]{9})(?:MVA)?', operator.organisation_number) if operator else None
    return found.group(1) if found else None


def deadline(facility, period):
    """THE deadline of the facility's planned-slaughter report for the week (audit F-101: the due list, the report list,
    the report's page and the filing all read it, reports/compute `deadline_of`): the earlier of the rule's deadline
    (Thursday of the week before) and the first day the fish fast for a harvest of the week (restkontrollforskriften § 9a:
    "senest når fisken er satt til sulting"), the fast each plan asked for whether its harvest is done yet or not; and
    a slaughter agreed after that (the week's plans were first made later) is due the day it was agreed. An unplanned
    harvest has no fast to read and no day it was agreed: it is late from the rule's deadline."""
    items = items_of(facility, period)
    fasts = [fast_of(item, done_too=True) for item in items]
    found = min([KINDS[ReportKind.SLAUGHTER_PLANNED].deadline(period),
                 *(fast.first_day for fast in fasts if fast is not None)])
    agreed = min((periods.oslo_today(item.created_at) for item in items), default=None)
    return found if agreed is None else max(found, agreed)

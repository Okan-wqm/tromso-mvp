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

from django.utils.translation import gettext as _

from farm.handling.fasting import fast_of
from farm.models import HandlingPlanItem, Site, SlaughterFacility, Tank

from .common import Result, identity, note, species_code, whole

WEEKDAYS = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')
ZERO = Decimal(0)


def items_of(facility, period):
    """The planned harvests to the facility in the week, not cancelled, live (a deleted unit hides its items)."""
    return list(HandlingPlanItem.objects.filter(kind=HandlingPlanItem.Kind.HARVEST, facility=facility,
                                                date__gte=period.start, date__lte=period.end, cancelled_reason='')
                .select_related('unit__production_department__site', 'batch__species', 'operation')
                .order_by('date', 'created_at'))


def compute(facility, period):
    problems, warnings = [], []
    items = items_of(facility, period)
    sites = {}
    planned = defaultdict(lambda: ZERO)
    for item in items:
        site = item.unit.production_department.site
        if site is None:
            problems.append(_('%(unit)s is on no site.') % {'unit': item.unit.code})
            continue
        sites[site.pk] = site
        code = species_code(item.batch.species, problems)
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
        'localities': localities, 'items': [str(item.pk) for item in items],
    }
    return Result(content, problems, warnings, scope(facility, period, items))


def scope(facility, period, items=None):
    """The rows the week's figures are read from (for the fingerprint), without computing them."""
    items = items if items is not None else items_of(facility, period)
    sites = {item.unit.production_department.site_id for item in items if item.unit.production_department.site_id}
    return [
        ('plan_items', HandlingPlanItem.all_objects.filter(kind=HandlingPlanItem.Kind.HARVEST, facility=facility,
                                                           date__gte=period.start, date__lte=period.end)),
        ('facility', SlaughterFacility.all_objects.filter(pk=facility.pk)),
        ('sites', Site.all_objects.filter(pk__in=sites)),
        ('units', Tank.all_objects.filter(pk__in={item.unit_id for item in items})),
    ]


def _filer(facility):
    """The organisation number of the company that files for the slaughterhouse (the report's own
    `organisasjonsnummer`: "selskapet som rapporterer planlagt slakt"): its operator's, nine digits; never taken from the
    farms whose fish it slaughters. None when the facility has no operator or its number is not nine digits."""
    operator = facility.operator
    found = re.fullmatch(r'(?:NO)?([0-9]{9})(?:MVA)?', operator.organisation_number) if operator else None
    return found.group(1) if found else None


def deadline(facility, period, rule_deadline):
    """The earlier of the rule's deadline (Thursday of the week before) and the first day the fish fast for a
    harvest of the week (restkontrollforskriften § 9a: "senest når fisken er satt til sulting")."""
    fasts = [fast_of(item) for item in items_of(facility, period)]
    days = [fast.first_day for fast in fasts if fast is not None]
    return min([rule_deadline, *days])

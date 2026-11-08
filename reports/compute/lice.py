"""The weekly sea-lice report (Mattilsynet, lakselusforskriften § 10; docs/regulatory-reports.md 1.2, 2.2): the sea
temperature, the lice counted per stage (the site's average is the mean of the cages' averages, Vedlegg 1 point 6),
the treatments of the week with their substances and amounts, and the answers of the person: whether a treatment was
given before the count, which treatments were given together, the suspicions of resistance and the sensitivity tests.

Read from the health records through their own reads (farm/health/read.py `lice_weeks`) and the stock ledger. The
report also compares the cages counted with the cages that held salmonids that week and does not call itself ready
while one that was due a count has none ("Snitt fra telling i alle merder"): a cage is due when 7 days have passed
since its last count (14 below 4 °C; none for broodstock below 4 °C, nor when every fish of the site is planned for
slaughter within 14 days of the day it fell due, § 6). A week in which no count fell due is filed without counts."""
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db.models import Max, Q
from django.utils.translation import gettext as _

from farm.health import lice as health_lice, read as health_read
from farm.models import Batch, HandlingPlanItem, LiceCount, Medicine, Site, Species, StockOperation, Treatment
from farm.models.harvest import PlanKind
from farm.models.health import MEDICINAL, MedicineKind, TreatmentMethod, TreatmentReason
from farm.models.site import zone_of
from farm.models.species import SALMONID_CODES
from farm.models.water_point import PointKind
from farm.stock import read
from farm.water import read as water

from ..periods import OSLO
from . import stock
from .common import Result, identity, note, text, unit_number

TEMPERATURE_DEPTH_M = Decimal(3)         # § 6: the sea temperature is measured at 3 m depth
WARM_DAYS, COLD_DAYS, COLD = 7, 14, Decimal(4)
SLAUGHTER_DAYS = 14
STAGES = ('adult_females', 'mobile', 'attached')

# How the farm's treatment methods are the report's types (the mapping of the medicinal ones is unverified).
MEDICINAL_TYPE = {TreatmentMethod.IN_FEED: 'FORBEHANDLING', TreatmentMethod.BATH: 'BADEBEHANDLING',
                  TreatmentMethod.DIP: 'BADEBEHANDLING', TreatmentMethod.INJECTION: 'ANNEN_BEHANDLING'}
NON_MEDICINAL_TYPE = {TreatmentMethod.THERMAL: 'TERMISK_BEHANDLING', TreatmentMethod.MECHANICAL: 'MEKANISK_BEHANDLING',
                      TreatmentMethod.FRESHWATER: 'FERSKVANNSBEHANDLING', TreatmentMethod.OTHER: 'ANNEN_BEHANDLING'}
OTHER_SUBSTANCE = 'ANNET_VIRKESTOFF'


def week_treatments(site, period):
    """The sea-lice treatments of the site given on any day of the week: a treatment that spans two weeks is in both."""
    return (Treatment.objects.filter(reason=TreatmentReason.SEA_LICE, units__production_department__site=site,
                                     start_date__lte=period.end, end_date__gte=period.start)
            .select_related('medicine').prefetch_related('units__production_department').distinct()
            .order_by('start_date', 'created_at'))


def left_out(site, period):
    """The treatments of the site in the week with a sea-lice medicine given for another reason, which the report leaves
    out (farm.health.lice.left_out_of_lice_report): it says so, so that a reason chosen wrongly is caught before filing
    (audit F-083, F-239)."""
    found = (Treatment.objects.filter(medicine__kind=MedicineKind.LICE, units__production_department__site=site,
                                      start_date__lte=period.end, end_date__gte=period.start)
             .exclude(reason=TreatmentReason.SEA_LICE).select_related('medicine')
             .prefetch_related('units__production_department').distinct().order_by('start_date', 'created_at'))
    return [treatment for treatment in found if health_lice.left_out_of_lice_report(treatment.medicine, treatment.reason)]


def _left_out_warnings(site, period, warnings):
    for treatment in left_out(site, period):
        units = sorted(unit.code for unit in treatment.units.all() if unit.production_department.site_id == site.pk)
        warnings.append(_('The treatment with %(medicine)s in %(units)s from %(start)s to %(end)s was recorded for '
                          '“%(reason)s”, not for sea lice, so it is not in this report: if it was given against sea '
                          'lice, void it and record it again with the reason “%(sea_lice)s”.') % {
            'medicine': treatment.medicine, 'units': ', '.join(units), 'start': treatment.start_date.isoformat(),
            'end': treatment.end_date.isoformat(), 'reason': treatment.get_reason_display(),
            'sea_lice': TreatmentReason.SEA_LICE.label})


def depth_samples(site, period):
    """The live samples taken at 3 m depth on the site in the week, on the site's clock: those of a depth point of a unit
    whose depth is 3 m (farm/water/read.py, the one reader of the water samples). A queryset of voided samples too; the
    sea temperature leaves them out."""
    zone = zone_of(site)
    first = datetime.combine(period.start, time.min, tzinfo=zone)
    before = datetime.combine(period.end + timedelta(days=1), time.min, tzinfo=zone)
    return water.samples_of(site=site, since=first, before=before).filter(
        point__kind=PointKind.DEPTH, point__depth_m=TEMPERATURE_DEPTH_M)


def sea_temperature(site, period, problems):
    """(°C, the ids of the samples it is the mean of): the week's temperature at 3 m depth, which § 6 asks for, the mean
    of the live samples of the site's depth points at 3 m that have a temperature. With none, the report says which
    sample to take rather than take a typed number."""
    found = [sample for sample in depth_samples(site, period) if not sample.is_deleted
             and sample.temperature_c is not None]
    if not found:
        note(problems, _('%(site)s has no sea temperature at 3 m depth for the week: record a water sample at a depth '
                         'point of 3 m (Operations › Water chemistry).') % {'site': site})
        return None, []
    return sum((sample.temperature_c for sample in found), Decimal(0)) / len(found), sorted(
        str(sample.pk) for sample in found)


def compute(site, period, report):
    problems, warnings = [], []
    units = stock.site_units(site)
    salmonids = set(Species.all_objects.filter(official_code__in=SALMONID_CODES).values_list('pk', flat=True))
    held, holders = _held(units, period, salmonids)
    if not held:
        problems.append(_('No unit of the site held salmonids in the week: the report has nothing to file.'))
    temperature, samples = sea_temperature(site, period, problems)
    if zone_of(site) != OSLO:
        warnings.append(_('%(site)s keeps another clock than Oslo’s: the week and its samples are the site’s, the '
                          'authority’s week is Oslo’s.') % {'site': site})
    counts = _counts(site, units, period, problems, warnings)
    _coverage(site, units, held, counts, temperature, period, problems, warnings)
    treatments = _treatments(site, units, report, counts, problems, warnings, period, salmonids)
    _left_out_warnings(site, period, warnings)
    content = {
        'kind': 'sea_lice', 'period': period.key, 'identity': identity(site, problems),
        'temperature_c': text(temperature, 1), 'samples': samples, 'counts': counts['content'],
        'treatments': treatments,
        'resistance_suspicions': [
            {'substance': row.substance, 'other_substance': row.other_substance or None, 'cause': row.cause,
             'other_cause': row.other_cause or None} for row in report.resistance_suspicions.all()],
        'sensitivity_tests': [
            {'tested_on': row.tested_on.isoformat(), 'laboratory': row.laboratory, 'substance': row.substance,
             'other_substance': row.other_substance or None, 'result': row.result}
            for row in report.sensitivity_tests.all()],
    }
    return Result(content, problems, warnings, scope(site, period, units), _questions(content['treatments']))


def _questions(treatments):
    """The open questions the week's treatments rest on: the amount of a medicinal treatment is the product's, and the
    authority asks for the active substance's (Q1, R03); a medicated feed and an injection are given the types the
    authority has not defined (Q2, R04)."""
    found = []
    if any(row['medicinal'] for row in treatments):
        found.append('Q1')
    if any(row['type'] == 'FORBEHANDLING' or row['description'] == 'Injeksjon' for row in treatments):
        found.append('Q2')
    return found


def scope(site, period, units=None, version=2):
    """The rows the week's figures are read from (for the fingerprint), without computing them; of `version` 1 for a
    report filed before version 2 (reports.compute.SCOPE_VERSIONS)."""
    units = units if units is not None else stock.site_units(site)
    if version == 1:
        return stock.scope_rows(units, period.end) + [
            ('lice_counts', LiceCount.all_objects.filter(unit__in=units, date__gte=period.start, date__lte=period.end)),
            ('treatments', Treatment.all_objects.filter(reason=TreatmentReason.SEA_LICE,
                                                        units__production_department__site=site,
                                                        start_date__lte=period.end, end_date__gte=period.start)
             .distinct()),
            ('medicines', Medicine.all_objects.filter(treatments__in=week_treatments(site, period)).distinct()),
            ('water_samples', depth_samples(site, period)),
        ]
    plans = HandlingPlanItem.all_objects.filter(kind=PlanKind.HARVEST, unit__in=units,
                                                date__lte=period.end + timedelta(days=SLAUGHTER_DAYS))
    return stock.scope_rows(units, period.end) + [
        ('lice_counts', LiceCount.all_objects.filter(unit__in=units, date__gte=period.start, date__lte=period.end)),
        # What decides whether a cage was due a count: its earlier counts and the harvest plans of § 6 (F-206).
        ('earlier_lice_counts', LiceCount.all_objects.filter(unit__in=units, date__lt=period.start)),
        # Only plans the § 6 exception can read: dated up to SLAUGHTER_DAYS after the week (a later plan cannot cover a
        # count due in it), with the harvests they were recorded as (a harvest voided after filing reopens its plan).
        ('harvest_plans', plans),
        ('harvest_plan_operations', StockOperation.all_objects.filter(plan_items__in=plans).distinct()),
        # The treatments for sea lice, and those with a sea-lice medicine the report leaves out and says so (F-239).
        ('treatments', Treatment.all_objects.filter(
            Q(reason=TreatmentReason.SEA_LICE) | Q(medicine__kind=MedicineKind.LICE),
            units__production_department__site=site, start_date__lte=period.end, end_date__gte=period.start).distinct()),
        ('medicines', Medicine.all_objects.filter(treatments__in=week_treatments(site, period)).distinct()),
        ('water_samples', depth_samples(site, period)),
    ]


# ---- which cages held salmonids ---------------------------------------------------------------------------
def _held(units, period, salmonids):
    """({unit id: the first day of its salmonids' stay as far as known}, the units): the cages that held salmonids on
    any day of the week."""
    opening, closing, lines = read.in_period(units, period.start, period.end)
    species = dict(Batch.all_objects.filter(pk__in={line.batch_id for line in lines}).values_list('pk', 'species_id'))
    held = {}
    for found in (opening, closing):
        for unit_id, unit_stock in found.items():
            for share in unit_stock.shares:
                if share.batch.species_id in salmonids:
                    held[unit_id] = min(held.get(unit_id, share.since), share.since)
    for line in lines:
        if line.count > 0 and species[line.batch_id] in salmonids:
            held[line.unit_id] = min(held.get(line.unit_id, line.date), line.date)
    return held, {unit.pk: unit for unit in units if unit.pk in held}


# ---- the counts ---------------------------------------------------------------------------------------------
def _counts(site, units, period, problems, warnings):
    """The week's counts (farm/health/read.py): the latest of each cage counted, the site's average per stage."""
    found = LiceCount.objects.filter(unit__in=units, date__gte=period.start, date__lte=period.end)
    year, week = period.iso
    the_week = next((item for item in health_read.lice_weeks(found) if (item.year, item.week) == (year, week)), None)
    if the_week is None:
        return {'content': None, 'units': set(), 'week': None}
    for count in the_week.small_samples:
        warnings.append(_('%(unit)s: %(fish)d fish counted on %(date)s, where the regulation asks for %(least)d in '
                          'this week.') % {'unit': count.unit.code, 'fish': count.fish_counted,
                                           'date': count.date.isoformat(), 'least': the_week.minimum_fish})
    if the_week.area_unknown:
        warnings.append(_('%(site)s has no sea-lice limit area (Facility › Sites): the stricter limit and the larger '
                          'sample are applied.') % {'site': site})
    if the_week.over_limit:
        warnings.append(_('The site’s average of adult female lice, %(average)s, is not below the limit of '
                          '%(limit)s (lakselusforskriften § 8).') % {'average': text(the_week.adult_females, 3),
                                                                    'limit': the_week.limit})
    content = {
        'cages': [{'number': unit_number(count.unit), 'date': count.date.isoformat(), 'fish': count.fish_counted,
                   'count': str(count.pk), **{stage: text(count.per_fish(stage), 3) for stage in STAGES}}
                  for count in the_week.counts],
        **{stage: text(the_week.average(stage), 3) for stage in STAGES},
    }
    return {'content': content, 'units': {count.unit_id for count in the_week.counts}, 'week': the_week}


def _coverage(site, units, held, counts, temperature, period, problems, warnings):
    """A cage that held salmonids and was due a count has one, unless an exception of § 6 holds."""
    last = dict(LiceCount.objects.filter(unit__in=held, date__lt=period.start).values('unit_id')
                .annotate(last=Max('date')).values_list('unit_id', 'last'))
    interval = timedelta(days=COLD_DAYS if temperature is not None and temperature < COLD else WARM_DAYS)
    names = {unit.pk: unit for unit in units}
    due = {}
    for unit_id, first in held.items():
        if unit_id in counts['units']:
            counted = {count.unit_id: count.date for count in counts['week'].counts}[unit_id]
            if unit_id in last and counted - last[unit_id] > interval:
                warnings.append(_('%(unit)s was counted on %(date)s and before that on %(last)s: the regulation asks for '
                                  'a count at least every %(days)d days (§ 6).') % {
                    'unit': names[unit_id].code, 'date': counted.isoformat(), 'last': last[unit_id].isoformat(),
                    'days': interval.days})
            continue
        day = last.get(unit_id, first) + interval
        if day <= period.end:
            due[unit_id] = day
    # A cage with no production fish left on the day its count fell due (harvested, culled or moved out before it)
    # has none to count.
    fish_on = {day: {unit_id: unit_stock.count for unit_id, unit_stock in read.stock_on(units, day).items()}
               for day in set(due.values())}
    due = {unit_id: day for unit_id, day in due.items() if fish_on[day].get(unit_id, 0) > 0}
    if not due:
        if counts['content'] is None:
            warnings.append(_('No count fell due in the week: it is filed with the temperature and without counts.'))
        return
    if site.production_form == Site.ProductionForm.STAMFISK and temperature is not None and temperature < COLD:
        return                                  # broodstock below 4 °C is not counted
    if _all_to_be_slaughtered(units, held, due, fish_on, period):
        warnings.append(_('Every fish of the site is planned for slaughter within %(days)d days of the day the count '
                          'fell due: no count is needed (lakselusforskriften § 6).') % {'days': SLAUGHTER_DAYS})
        return
    for unit_id in sorted(due, key=lambda pk: names[pk].code):
        problems.append(_('%(unit)s held salmonids and was due a count by %(date)s: count it, or the site’s average '
                          'is not of every cage.') % {'unit': names[unit_id].code, 'date': due[unit_id].isoformat()})


def _all_to_be_slaughtered(units, held, due, fish_on, period):
    """Whether every cage with salmonids has a harvest planned that covers its production fish (cleaner fish are not
    harvested) within 14 days of the day its count fell due (of the week's end for a cage that was not due), the fish
    being those it held that day. A plan counts when it is not cancelled, whether still open or already recorded as a
    harvest: the exception does not lapse when the fish are slaughtered, and a plan whose harvest was voided is open
    again (HandlingPlanItem.done)."""
    closing = {unit_id: unit_stock.count for unit_id, unit_stock in read.stock_on(units, period.end).items()}
    fish = {unit_id: fish_on[due[unit_id]].get(unit_id, 0) if unit_id in due else closing.get(unit_id, 0)
            for unit_id in held}
    planned = {}
    items = HandlingPlanItem.objects.filter(kind=PlanKind.HARVEST, unit__in=held, cancelled_reason='')
    for item in items.select_related('operation'):
        reference = due.get(item.unit_id, period.end)
        if item.done and item.date <= reference:
            continue                    # taken out before: its fish are not among those counted that day
        if item.date <= reference + timedelta(days=SLAUGHTER_DAYS):
            planned[item.unit_id] = planned.get(item.unit_id, 0) + (item.planned_count or 0)
    return any(fish.values()) and all(planned.get(unit_id, 0) >= fish[unit_id] for unit_id in held)


# ---- the treatments -----------------------------------------------------------------------------------------
def _treatments(site, units, report, counts, problems, warnings, period, salmonids):
    answers = {answer.treatment_id: answer for answer in report.treatment_answers.all()}
    by_unit_day = {}
    if counts['week'] is not None:
        by_unit_day = {count.unit_id: count.date for count in counts['week'].counts}
    holding_cache = {}
    rows = []
    for treatment in week_treatments(site, period):
        treated = {unit.pk for unit in treatment.units.all() if unit.production_department.site_id == site.pk}
        first_day = max(treatment.start_date, period.start)
        if first_day not in holding_cache:
            holding_cache[first_day] = {
                unit_id for unit_id, unit_stock in read.stock_on(units, first_day).items()
                if any(share.batch.species_id in salmonids for share in unit_stock.shares)}
        holding = holding_cache[first_day]
        whole = holding <= treated
        cages = None if whole else len(holding & treated)
        if not holding or cages == 0:
            note(problems, _('The treatment of %(date)s was of no unit that held salmonids: the report cannot say how many '
                             'cages were treated.') % {'date': treatment.start_date.isoformat()})
        answer = answers.get(treatment.pk)
        before, ambiguous = _before_count(treatment, treated, by_unit_day)
        if answer is not None:
            before = answer.done_before_count
        elif ambiguous:
            problems.append(_('Say whether the treatment of %(date)s was given before the count (the Treatments tab): '
                              'the count was taken on the day it ended.') % {'date': treatment.start_date.isoformat()})
        row = {'treatment': str(treatment.pk), 'start': treatment.start_date.isoformat(),
               'end': treatment.end_date.isoformat(), 'whole_site': whole, 'cages': cages,
               'before_count': before, 'combination': answer.combination if answer is not None else None}
        row.update(_kind(treatment, problems))
        rows.append(row)
    if any(row['medicinal'] for row in rows):
        # § 10 c asks for the amount of active substance; the amount recorded is the product's (unverified which is meant).
        warnings.append(_('The amount of a medicinal treatment is the amount used of the product; Mattilsynet asks for the '
                          'amount of the active substance: confirm which it wants.'))
    groups = {}
    for row in rows:
        if row['combination'] is not None:
            groups.setdefault(row['combination'], []).append(row)
    for number, members in sorted(groups.items()):
        if len(members) < 2:
            problems.append(_('Combination %(number)d is of one treatment: a combination is of at least two.') % {
                'number': number})
    return rows


def _before_count(treatment, treated, count_days):
    """(whether the treatment was given before the count, whether that cannot be told): before when it ended before
    every count of its cages that week; ambiguous when one was taken on its last day (the records carry no times)."""
    days = [day for unit_id, day in count_days.items() if unit_id in treated]
    if not days:
        return False, False
    if any(day == treatment.end_date for day in days):
        return False, True
    return all(day > treatment.end_date for day in days), False


def _kind(treatment, problems):
    """The treatment's type in the report, and for a medicinal one its substance, strength and amount."""
    if treatment.method not in MEDICINAL:
        if treatment.method == TreatmentMethod.OTHER and not treatment.notes.strip():
            note(problems, _('Describe the treatment of %(date)s (Operations › Health): “other” is described in the '
                             'report.') % {'date': treatment.start_date.isoformat()})
        return {'medicinal': False, 'type': NON_MEDICINAL_TYPE[treatment.method], 'description': (
            treatment.notes if treatment.method == TreatmentMethod.OTHER else None), 'substance': None}
    medicine = treatment.medicine
    kind = MEDICINAL_TYPE[treatment.method]
    when = treatment.start_date.isoformat()
    code = medicine.lice_report_code
    if not code:
        note(problems, _('%(medicine)s has no substance in the lice report (Reference data › Medicines): the treatment '
                         'of %(date)s cannot be reported.') % {'medicine': medicine, 'date': when})
    if medicine.strength_value is None:
        note(problems, _('%(medicine)s has no strength (Reference data › Medicines).') % {'medicine': medicine})
    if treatment.amount_value is None:
        note(problems, _('The treatment of %(date)s has no amount used (Operations › Health): the report asks for it.')
             % {'date': when})
    return {
        'medicinal': True, 'type': kind,
        'description': 'Injeksjon' if treatment.method == TreatmentMethod.INJECTION else None,
        'substance': {
            'type': code or None, 'other': medicine.active_substance if code == OTHER_SUBSTANCE else None,
            'strength': {'value': text(medicine.strength_value, 3), 'unit': medicine.strength_unit or None},
            'amount': {'value': text(treatment.amount_value, 3), 'unit': treatment.amount_unit or None},
        },
    }

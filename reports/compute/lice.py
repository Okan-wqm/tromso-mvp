"""The weekly sea-lice report (Mattilsynet, lakselusforskriften § 10; docs/regulatory-reports.md 1.2, 2.2): the sea
temperature, the lice counted per stage (the site's average is the mean of the cages' averages, Vedlegg 1 point 6),
the treatments of the week with their substances and amounts, and the answers of the person: whether a treatment was
given before the count, which treatments were given together, the suspicions of resistance and the sensitivity tests.

Read from the health records through their own reads (farm/health/read.py `lice_weeks`) and the stock ledger. The
report also compares the cages counted with the cages that held salmonids that week and does not call itself ready
while one that was due a count has none ("Snitt fra telling i alle merder"): a cage is due when 7 days have passed
since its last count (14 below 4 °C; none for broodstock below 4 °C, nor when every fish of the site is planned for
slaughter within 14 days of the day it fell due, § 6). A week in which no count fell due is filed without counts."""
from datetime import timedelta
from decimal import Decimal

from django.db.models import Max
from django.utils.translation import gettext as _

from farm.health import read as health_read
from farm.models import Batch, HandlingPlanItem, LiceCount, Medicine, Site, Species, Treatment
from farm.models.harvest import PlanKind
from farm.models.health import MEDICINAL, TreatmentMethod, TreatmentReason
from farm.stock import read

from . import stock
from .common import Result, identity, note, text, unit_number

SALMONIDS = ('SAL', 'TRS', 'TRR')       # D-11: Mattilsynet's own "Laks, Ørret, Regnbueørret"
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


def sea_temperature(site, period, problems):
    """(°C, the samples it is the mean of): the week's temperature at 3 m depth, which § 6 asks for. The water samples
    carry no depth yet (OUR-13: the sampling points of the water module do), so there is none to read and the report
    says so rather than take a typed number."""
    note(problems, _('%(site)s has no sea temperature at 3 m depth for the week: record a water sample at 3 m '
                     '(Operations › Water chemistry).') % {'site': site})
    return None, []


def compute(site, period, report):
    problems, warnings = [], []
    units = stock.site_units(site)
    salmonids = set(Species.all_objects.filter(official_code__in=SALMONIDS).values_list('pk', flat=True))
    held, holders = _held(units, period, salmonids)
    if not held:
        problems.append(_('No unit of the site held salmonids in the week: the report has nothing to file.'))
    temperature, samples = sea_temperature(site, period, problems)
    counts = _counts(site, units, period, problems, warnings)
    _coverage(site, units, held, counts, temperature, period, problems, warnings)
    treatments = _treatments(site, units, report, counts, problems, period, salmonids)
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
    scope = stock.scope_rows(units, period.end) + [
        ('lice_counts', LiceCount.all_objects.filter(unit__in=units, date__gte=period.start, date__lte=period.end)),
        ('treatments', Treatment.all_objects.filter(reason=TreatmentReason.SEA_LICE,
                                                    units__production_department__site=site,
                                                    start_date__lte=period.end, end_date__gte=period.start)
         .distinct()),
        ('medicines', Medicine.all_objects.filter(treatments__in=week_treatments(site, period)).distinct()),
    ]
    return Result(content, problems, warnings, scope)


# ---- which cages held salmonids ---------------------------------------------------------------------------
def _held(units, period, salmonids):
    """({unit id: the first day of its salmonids' stay as far as known}, the units): the cages that held salmonids on
    any day of the week."""
    opening = read.stock_on(units, stock.day_before(period))
    closing = read.stock_on(units, period.end)
    lines = read.movements(units, period.start, period.end)
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
    due = {}
    for unit_id, first in held.items():
        if unit_id in counts['units']:
            continue
        day = last.get(unit_id, first) + interval
        if day <= period.end:
            due[unit_id] = day
    if not due:
        if counts['content'] is None:
            warnings.append(_('No count fell due in the week: it is filed with the temperature and without counts.'))
        return
    if site.production_form == Site.ProductionForm.STAMFISK and temperature is not None and temperature < COLD:
        return                                  # broodstock below 4 °C is not counted
    if _all_to_be_slaughtered(held, due, period):
        warnings.append(_('Every fish of the site is planned for slaughter within %(days)d days of the day the count '
                          'fell due: no count is needed (lakselusforskriften § 6).') % {'days': SLAUGHTER_DAYS})
        return
    names = {unit.pk: unit for unit in units}
    for unit_id in sorted(due, key=lambda pk: names[pk].code):
        problems.append(_('%(unit)s held salmonids and was due a count by %(date)s: count it, or the site’s average '
                          'is not of every cage.') % {'unit': names[unit_id].code, 'date': due[unit_id].isoformat()})


def _all_to_be_slaughtered(held, due, period):
    """Whether every cage with salmonids has a harvest planned that covers its fish within 14 days of the day its count
    fell due (of the week's end for a cage that was not due), a plan that is open: neither cancelled nor recorded."""
    fish = read.unit_counts(list(held))
    planned = {}
    for item in HandlingPlanItem.objects.filter(kind=PlanKind.HARVEST, unit__in=held, cancelled_reason='',
                                                operation__isnull=True):
        latest = due.get(item.unit_id, period.end) + timedelta(days=SLAUGHTER_DAYS)
        if item.date <= latest:
            planned[item.unit_id] = planned.get(item.unit_id, 0) + (item.planned_count or 0)
    return all(planned.get(unit_id, 0) >= fish.get(unit_id, 0) > 0 for unit_id in held)


# ---- the treatments -----------------------------------------------------------------------------------------
def _treatments(site, units, report, counts, problems, period, salmonids):
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

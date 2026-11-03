"""The medicine withdrawal of the fish, worked out on read from stored facts only: the live treatments with
a medicine, the stock ledger and the water samples (health-maturity §4b). Nothing is stored, so voiding a
treatment, correcting a temperature or a backdated transfer changes the answer at once (the source stored a
date that started at the click and survived a resolved disease, HLT-01, HLT-02).

The rules, for a batch b and a treatment T whose medicine states its withdrawal:

1. **It follows the fish.** T reached b when b had fish in one of T's units on a day from T's first day to its
   last (today at the latest; farm.stock.read.Presence). Wherever b is now, it is held; if only some of b's
   units were treated, the whole batch is held (conservative).
2. **Days**: day 1 is the day after T's last day, so the first day b may be harvested is the last day +
   the withdrawal days + 1.
3. **Degree-days**: the daily mean water temperature of b is added up from the day after T's last day until
   the sum reaches the medicine's degree-days; the next day is the first day b may be harvested.
   - A unit's daily mean is the mean of the live temperatures of that farm-local day measured in the unit,
     else in its system's loop (the water samples, farm/models/water.py). With b in several units that
     day, the lowest counts.
   - **A past day without a temperature counts as 0 °C** (conservative) and the warning says how many there
     were. Today without a temperature yet is not counted: it is projected.
4. Days and degree-days both given: the later end wins. Several treatments: each holds b on its own, and
   the latest end decides what the page shows.
5. Not reached by today, the rest is projected at the mean of the last 7 days with a temperature within
   30 days (`estimated`, shown as "about"). With none, the end is unknown (`until` None): "record the water
   temperature". A running course (its last day ahead) is projected from the day after its last day.
6. **Medicated feed** (a feed of the type Medicated) that fed b on a day no live in-feed treatment of its unit
   covers holds b with an unknown end until such a treatment is recorded or the feeding is voided.
7. A voided treatment holds nothing (it is not live).

`until` is the first day b may be harvested; a withdrawal holds on every day before it. The health module
gives the harvest side these blocks through the registry of farm/handling/withdrawal.py (`provider`)."""
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from datetime import timezone as dt_timezone
from decimal import ROUND_CEILING, Decimal

from django.db.models import Q
from django.utils.translation import gettext as _, ngettext

from farm.feeding import read as feeding_read
from farm.handling.withdrawal import WithdrawalBlock
from farm.models import Batch, FeedingRecord, Tank, Treatment, WaterMeasurement
from farm.models.feed import FeedType
from farm.models.health import TreatmentMethod
from farm.models.water import local_time
from farm.stock.dates import local_today, shown_date
from farm.stock.read import Presence

DAY = timedelta(days=1)
ZERO = Decimal(0)
PROJECTION_DAYS = 7     # the days with a temperature a projection takes the mean of
LOOKBACK_DAYS = 30      # how far back from today they are looked for (the water's window)


@dataclass(frozen=True)
class Withdrawal:
    """The withdrawal of one batch from one cause: a treatment, or a medicated feeding no in-feed treatment
    covers (`feeding`, with an unknown end)."""
    batch_id: object
    until: object                         # the first day the batch may be harvested; None: unknown
    estimated: bool = False               # projected: degree-days still accruing
    treatment: Treatment = None
    feeding: FeedingRecord = None
    days_without_temperature: int = 0     # past days counted as 0 °C
    remaining_degree_days: Decimal = None  # what was still to accrue today, when projected or unknown

    @property
    def source(self):
        return self.treatment if self.treatment is not None else self.feeding

    @property
    def last_day(self):
        """The last day of the withdrawal: the day before the batch may be harvested."""
        return self.until - DAY if self.until is not None else None

    def holds_on(self, day):
        return self.until is None or day < self.until


class Temperatures:
    """The daily mean water temperature of units from `first` to `last`: a unit's own live samples of that
    farm-local day, else its system loop's (a sample's day is on the clock of its point's site)."""

    def __init__(self, units, first, last):
        self.first, self.last = first, last
        self.units = {unit.pk: unit for unit in units}
        systems = {unit.system_id for unit in units if unit.system_id}
        values = defaultdict(list)
        if units and first <= last:
            start = datetime.combine(first - DAY, time.min, tzinfo=dt_timezone.utc)
            stop = datetime.combine(last + 2 * DAY, time.min, tzinfo=dt_timezone.utc)
            samples = (WaterMeasurement.objects
                       .filter(Q(unit__in=list(self.units)) | Q(system__in=systems), temperature_c__isnull=False,
                               measured_at__gte=start, measured_at__lt=stop)
                       .select_related('unit__production_department__site', 'system__site'))
            for sample in samples:
                day = local_time(sample.measured_at, sample.point).date()
                if first <= day <= last:
                    point = ('unit', sample.unit_id) if sample.unit_id else ('system', sample.system_id)
                    values[(point, day)].append(sample.temperature_c)
        self.means = {key: sum(found, ZERO) / len(found) for key, found in values.items()}

    def of(self, unit_id, day):
        """The unit's daily mean on `day`, else its system's; None when neither was measured."""
        mean = self.means.get((('unit', unit_id), day))
        if mean is None:
            system_id = self.units[unit_id].system_id
            if system_id:
                mean = self.means.get((('system', system_id), day))
        return mean


class Reader:
    """The withdrawals of a set of batches, as they stand on `today` (the farm's today)."""

    def __init__(self, batch_ids, today):
        self.batch_ids, self.today = set(batch_ids), today
        self.presence = Presence.of_batches(self.batch_ids)
        unit_ids = {unit_id for units in self.presence.units.values() for unit_id in units}
        self.units = Tank.all_objects.select_related('production_department__site').in_bulk(unit_ids)
        self.treatments = list(Treatment.objects.filter(units__in=unit_ids, medicine__isnull=False).distinct()
                               .select_related('medicine').prefetch_related('units').order_by('start_date', 'pk'))
        first = today - LOOKBACK_DAYS * DAY
        for treatment in self.treatments:
            first = min(first, treatment.end_date + DAY)
        self.temperatures = Temperatures(list(self.units.values()), first, today)

    # ---- which fish a treatment reached ---------------------------------------------------------
    def treated(self, treatment):
        """The batches of this reader that had fish in one of the treatment's units on one of its days (up
        to today: what happens later is not recorded yet)."""
        last = min(treatment.end_date, self.today)
        unit_ids = [unit.pk for unit in treatment.units.all()]
        return {batch_id for batch_id in self.batch_ids
                if any(self.presence.present_between(unit_id, batch_id, treatment.start_date, last)
                       for unit_id in unit_ids)}

    # ---- the batch's water --------------------------------------------------------------------------
    def temperature(self, batch_id, day):
        """The batch's daily mean on `day`: the lowest of its units' that were measured; None when none was."""
        found = [mean for mean in (self.temperatures.of(unit_id, day)
                                   for unit_id in self.presence.units_of(batch_id, day)) if mean is not None]
        return min(found) if found else None

    def projection(self, batch_id):
        """The mean of the batch's last PROJECTION_DAYS days with a temperature, within LOOKBACK_DAYS of today."""
        found, day = [], self.today
        while day > self.today - LOOKBACK_DAYS * DAY and len(found) < PROJECTION_DAYS:
            value = self.temperature(batch_id, day)
            if value is not None:
                found.append(value)
            day -= DAY
        return sum(found, ZERO) / len(found) if found else None

    def degree_days(self, batch_id, end, needed):
        """(first day, estimated, days without a temperature, degree-days still to accrue) of a withdrawal of
        `needed` degree-days after the last day `end` (rule 3 and 5); the first day is None when unknown."""
        if needed <= 0:
            return end + DAY, False, 0, ZERO
        total, missing, day = ZERO, 0, end
        while day < self.today:
            value = self.temperature(batch_id, day + DAY)
            if value is None and day + DAY == self.today:
                break                       # today has no temperature yet: projected, not counted as 0
            day += DAY
            if value is None:
                missing += 1
                value = ZERO
            total += value
            if total >= needed:
                return day + DAY, False, missing, ZERO
        remaining = needed - total
        mean = self.projection(batch_id)
        if mean is None or mean <= 0:
            return None, True, missing, remaining
        days = int((remaining / mean).to_integral_value(rounding=ROUND_CEILING))
        return day + days * DAY + DAY, True, missing, remaining

    # ---- the withdrawals ----------------------------------------------------------------------------
    def of_treatment(self, treatment, batch_id):
        """The withdrawal of one batch from one treatment (rules 2 to 5)."""
        medicine, end = treatment.medicine, treatment.end_date
        by_days = end + (medicine.withdrawal_days + 1) * DAY if medicine.withdrawal_days is not None else None
        if medicine.withdrawal_degree_days is None:
            return Withdrawal(batch_id, by_days, treatment=treatment)
        by_degrees, estimated, missing, remaining = self.degree_days(batch_id, end,
                                                                     Decimal(medicine.withdrawal_degree_days))
        if by_degrees is None:
            until, estimated = None, True
        elif by_days is not None and by_days > by_degrees:
            until, estimated = by_days, False
        else:
            until = by_degrees
        return Withdrawal(batch_id, until, estimated, treatment, days_without_temperature=missing,
                          remaining_degree_days=remaining if estimated else None)

    def uncovered_feedings(self):
        """Withdrawals of unknown end for the medicated feedings of the batches that no live in-feed
        treatment of their unit covers on their day (rule 6)."""
        unit_ids = list(self.units)
        records = list(FeedingRecord.objects.filter(unit_id__in=unit_ids, feed__feed_type=FeedType.MEDICATED)
                       .select_related('feed', 'unit'))
        if not records:
            return []
        in_feed = [(treatment, {unit.pk for unit in treatment.units.all()}) for treatment in self.treatments
                   if treatment.method == TreatmentMethod.IN_FEED]
        found = []
        for record_id, parts in feeding_read.split_of(records).items():
            record = next(item for item in records if item.pk == record_id)
            covered = any(record.unit_id in units and treatment.start_date <= record.date <= treatment.end_date
                          for treatment, units in in_feed)
            if not covered:
                found += [Withdrawal(batch_id, None, True, feeding=record)
                          for batch_id in sorted(parts, key=str) if batch_id in self.batch_ids]
        return found

    def withdrawals(self):
        """Every withdrawal of the batches, ended ones too."""
        found = [self.of_treatment(treatment, batch_id) for treatment in self.treatments
                 for batch_id in sorted(self.treated(treatment), key=str)]
        return found + self.uncovered_feedings()


# ---- what the pages and the handling check read --------------------------------------------------------
def holding(batch_ids, today, day=None):
    """{batch id: [Withdrawal]} of the withdrawals that hold the batches on `day` (default today)."""
    day = today if day is None else day
    found = defaultdict(list)
    if batch_ids:
        for withdrawal in Reader(batch_ids, today).withdrawals():
            if withdrawal.holds_on(day):
                found[withdrawal.batch_id].append(withdrawal)
    return found


def of_units(units, day=None):
    """{unit id: [Withdrawal]} of the batches in each unit on `day` (default each unit's today) that a
    withdrawal holds then; one reader per farm-local today (sites in different time zones)."""
    by_today = defaultdict(list)
    for unit in units:
        by_today[local_today(unit)].append(unit)
    found = {}
    for today, members in by_today.items():
        presence = Presence.of_units([unit.pk for unit in members])
        present = {unit.pk: presence.batches_in(unit.pk, day or today) for unit in members}
        held = holding({batch_id for batches in present.values() for batch_id in batches}, today, day)
        for unit in members:
            withdrawals = [withdrawal for batch_id in sorted(present[unit.pk], key=str)
                           for withdrawal in held.get(batch_id, [])]
            if withdrawals:
                found[unit.pk] = withdrawals
    return found


@dataclass(frozen=True)
class Summary:
    """What a unit or a batch shows: the latest end of the withdrawals that hold it (None when one of them is
    unknown), whether it is projected, and the reasons of the unknown ones."""
    until: object
    estimated: bool
    unknown: tuple

    @property
    def last_day(self):
        return self.until - DAY if self.until is not None else None


def summary(withdrawals):
    if not withdrawals:
        return None
    unknown = tuple(withdrawal for withdrawal in withdrawals if withdrawal.until is None)
    if unknown:
        return Summary(None, True, unknown)
    latest = max(withdrawals, key=lambda withdrawal: (withdrawal.until, withdrawal.estimated))
    return Summary(latest.until, latest.estimated, ())


def rule(medicine):
    """The medicine's withdrawal as the pages say it: 7 days, 150 degree-days, or both."""
    days, degrees = medicine.withdrawal_days, medicine.withdrawal_degree_days
    parts = []
    if degrees is not None:
        parts.append(ngettext('%(count)d degree-day', '%(count)d degree-days', degrees) % {'count': degrees})
    if days is not None:
        parts.append(ngettext('%(count)d day', '%(count)d days', days) % {'count': days})
    if len(parts) == 2:
        return _('%(degrees)s or %(days)s, whichever ends later') % {'degrees': parts[0], 'days': parts[1]}
    return parts[0]


def describe(withdrawal):
    """Why a withdrawal holds the fish and until when, in the active language."""
    if withdrawal.feeding is not None:
        record = withdrawal.feeding
        return _('Medicated feed %(feed)s was fed in %(unit)s on %(date)s and no in-feed treatment covers that '
                 'day: the withdrawal end is unknown. Record the treatment under Health › Treatments.') % {
            'feed': record.feed, 'unit': record.unit.code, 'date': shown_date(record.date)}
    treatment = withdrawal.treatment
    text = _('%(medicine)s, %(method)s from %(start)s to %(end)s: withdrawal %(rule)s.') % {
        'medicine': treatment.medicine, 'method': str(treatment.get_method_display()).lower(),
        'start': shown_date(treatment.start_date), 'end': shown_date(treatment.end_date),
        'rule': rule(treatment.medicine)}
    if withdrawal.until is None:
        text += ' ' + _('The end cannot be worked out: record the water temperature.')
    elif withdrawal.estimated:
        text += ' ' + _('Projected at the mean water temperature of the last days measured.')
    if withdrawal.days_without_temperature:
        text += ' ' + ngettext('%(count)d day without a water temperature is counted as 0 °C.',
                               '%(count)d days without a water temperature are counted as 0 °C.',
                               withdrawal.days_without_temperature) % {'count': withdrawal.days_without_temperature}
    return text


def provider(unit, day):
    """The health module's answer to farm.handling.withdrawal.blocks: a block per withdrawal that holds a
    batch in `unit` on `day`."""
    withdrawals = of_units([unit], day).get(unit.pk, [])
    batches = Batch.all_objects.in_bulk({withdrawal.batch_id for withdrawal in withdrawals})
    return [WithdrawalBlock(batches[withdrawal.batch_id], withdrawal.until, withdrawal.estimated,
                            describe(withdrawal), withdrawal.source) for withdrawal in withdrawals]

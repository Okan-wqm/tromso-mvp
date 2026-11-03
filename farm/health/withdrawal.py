"""The medicine withdrawal of the fish, worked out on read from stored facts only: the live treatments with
a medicine, the stock ledger and the water samples (health-maturity §4b). Nothing is stored, so voiding a
treatment, correcting a temperature or a backdated transfer changes the answer at once (the source stored a
date that started at the click and survived a resolved disease, HLT-01, HLT-02).

The rules, for a batch b and a treatment T with a medicine:

0. **The withdrawal is per species** (the rows of MedicineWithdrawal, Setup › Reference data › Medicines): the row
   for b's species, else the row for every species, else none, and `resolve` is the one place that says which
   (`row_for`). A row states days, degree-days or both, as the SPC does, and the farm's safety margin on top:
   used = value × (1 + margin ÷ 100), rounded up (`Rule`); with no margin the label value is used as it is.
   **No row for b's species, and none for every species: the end is unknown** (`until` None) and the warning says
   "no withdrawal is recorded for <species> of <medicine>: add it in Reference data › Medicines": never silently
   no withdrawal, never silently zero.
1. **It follows the fish.** T reached b when b had fish in one of T's units on a day from T's first day to its
   last (today at the latest; farm.stock.read.Presence). Wherever b is now, it is held; if only some of b's
   units were treated, the whole batch is held (conservative).
2. **Days**: day 1 is the day after T's last day, so the first day b may be harvested is the last day +
   the row's days (the margin applied) + 1.
3. **Degree-days**: the daily mean water temperature of b is added up from the day after T's last day until
   the sum reaches the row's degree-days (the margin applied); the next day is the first day b may be harvested.
   - The batch's daily mean water temperature, a past day without one counted at the species' assumed
     temperature (else 0 °C, said in the warning) and a day not measured yet projected, is farm/water/degree_days.py's
     (`BatchWater`), shared with the purging fast before a harvest: one definition for both. With b in several units
     that day, the lowest counts. Today without a temperature yet is not counted: it is projected.
4. Days and degree-days both given: the later end wins. Several treatments: each holds b on its own, and
   the latest end decides what the page shows.
5. Not reached by today, the rest is projected at the mean of the last 7 days with a temperature within
   30 days (`estimated`, shown as "about"). With none measured, at the species' assumed temperature when it has
   one (said so), else the end is unknown (`until` None): "record the water temperature". A running course
   (its last day ahead) is projected from the day after its last day.
6. **Medicated feed** (a feed of the type Medicated) that fed b on a day no live in-feed treatment of its unit
   covers holds b with an unknown end until such a treatment is recorded or the feeding is voided.
7. A voided treatment holds nothing (it is not live).

`until` is the first day b may be harvested; a withdrawal holds from the treatment's first day (or the
medicated feeding's day) to the day before `until`: a day before the treatment is not held. The health module
gives the harvest side these blocks through the registry of farm/handling/withdrawal.py (`provider`)."""
from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_CEILING, Decimal

from django.utils import formats
from django.utils.translation import gettext as _, ngettext

from farm.feeding import read as feeding_read
from farm.handling.withdrawal import WithdrawalBlock
from farm.models import Batch, FeedingRecord, MedicineWithdrawal, Treatment
from farm.models.feed import FeedType
from farm.models.health import TreatmentMethod
from farm.stock.dates import local_today, shown_date
from farm.stock.read import Presence
from farm.water.degree_days import (DAY, LOOKBACK_DAYS, PENDING, ZERO, BatchWater, degree_days_text,
                                    missing_sentence, projected_sentence)


def _plain(value):
    """150, or 12.5: a number as the language writes it, a decimal only when it has one."""
    value = Decimal(value)
    return formats.number_format(value, decimal_pos=0 if value == value.to_integral_value() else 1)


def _days(value):
    return ngettext('%(count)d day', '%(count)d days', value) % {'count': value}


@dataclass(frozen=True)
class Rule:
    """What a medicine's withdrawal row asks of fish of its species, the farm's safety margin applied: used =
    value × (1 + margin ÷ 100), rounded up; the label value is kept beside it, as the SPC states it. With no margin
    the label value is used as it is."""
    row: MedicineWithdrawal
    degree_days: Decimal | None = None      # used
    days: int | None = None                 # used

    @classmethod
    def of(cls, row):
        factor = 1 + row.safety_margin_pct / 100

        def used(value):
            if value is None or not row.safety_margin_pct:
                return value
            return (Decimal(value) * factor).to_integral_value(rounding=ROUND_CEILING)

        return cls(row, used(row.degree_days), None if row.days is None else int(used(row.days)))

    @property
    def margin(self):
        return self.row.safety_margin_pct

    def text(self):
        """150 degree-days + 20 % safety margin = 180 degree-days, 7 days, or both."""
        parts = []
        for label, used, say in ((self.row.degree_days, self.degree_days, degree_days_text),
                                 (self.row.days, self.days, _days)):
            if label is None:
                continue
            said = say(label)
            if self.margin:
                said = _('%(label)s + %(margin)s %% safety margin = %(used)s') % {
                    'label': said, 'margin': _plain(self.margin), 'used': say(used)}
            parts.append(said)
        if len(parts) == 2:
            return _('%(degrees)s or %(days)s, whichever ends later') % {'degrees': parts[0], 'days': parts[1]}
        return parts[0]


def row_for(rows, species_id):
    """THE resolution of a medicine's withdrawal for a species: its own row, else the row for every species, else
    None. Every reader (the withdrawal, the Medicines pages, the treatment dialog) asks here."""
    found = {row.species_id: row for row in rows}
    return found.get(species_id) or found.get(None)


def rule_for(rows, species_id):
    """The Rule of the row `row_for` finds, or None: the medicine has no withdrawal for this species."""
    row = row_for(rows, species_id)
    return Rule.of(row) if row is not None else None


@dataclass(frozen=True)
class Withdrawal:
    """The withdrawal of one batch from one cause: a treatment, or a medicated feeding no in-feed treatment
    covers (`feeding`, with an unknown end). A treatment whose medicine has no withdrawal for the batch's species
    has no `rule` and an unknown end."""
    batch_id: object
    until: object                         # the first day the batch may be harvested; None: unknown
    estimated: bool = False               # projected: degree-days still accruing
    treatment: Treatment = None
    feeding: FeedingRecord = None
    days_without_temperature: int = 0     # past days without a measured temperature
    rule: Rule = None                     # the medicine's withdrawal for the batch's species; None: not recorded
    species: object = None                # the batch's species, for the text of a withdrawal that has no rule
    assumed_temperature: Decimal = None   # the batch species' assumed temperature those days were counted at; None:
                                          # it has none and they were counted as 0 °C
    projected_at_assumed: bool = False    # no temperature was measured lately: projected at the assumed one
    remaining_degree_days: Decimal = None  # what was still to accrue today, when projected or unknown

    @property
    def source(self):
        return self.treatment if self.treatment is not None else self.feeding

    @property
    def last_day(self):
        """The last day of the withdrawal: the day before the batch may be harvested."""
        return self.until - DAY if self.until is not None else None

    @property
    def start(self):
        """The first day it holds: the treatment's first day, or the day of the medicated feeding."""
        return self.treatment.start_date if self.treatment is not None else self.feeding.date

    def holds_on(self, day):
        """From its first day (fish under treatment are held too) to the day before `until`."""
        return day >= self.start and (self.until is None or day < self.until)


class Reader:
    """The withdrawals of a set of batches, as they stand on `today` (the farm's today)."""

    def __init__(self, batch_ids, today):
        self.batch_ids, self.today = set(batch_ids), today
        self.presence = Presence.of_batches(self.batch_ids)
        unit_ids = {unit_id for units in self.presence.units.values() for unit_id in units}
        self.treatments = list(Treatment.objects.filter(units__in=unit_ids, medicine__isnull=False).distinct()
                               .select_related('medicine').prefetch_related('units').order_by('start_date', 'pk'))
        self.rows = {}                                 # medicine id -> its withdrawal rows
        self.load_rows({each.medicine_id for each in self.treatments})
        first = today - LOOKBACK_DAYS * DAY
        for treatment in self.treatments:
            first = min(first, treatment.end_date + DAY)
        self.water = BatchWater(self.batch_ids, today, first, presence=self.presence)
        self.units, self.batches = self.water.units, self.water.batches

    def load_rows(self, medicine_ids):
        """Reads the withdrawal rows of the medicines not read yet, in one query: a medicine without a row is an empty
        list, never a missing key (no withdrawal recorded is said, not assumed)."""
        new = {pk for pk in medicine_ids if pk not in self.rows}
        self.rows.update({pk: [] for pk in new})
        for row in MedicineWithdrawal.objects.filter(medicine__in=new):
            self.rows[row.medicine_id].append(row)

    # ---- which fish a treatment reached ---------------------------------------------------------
    def treated(self, treatment):
        """The batches of this reader that had fish in one of the treatment's units on one of its days (up
        to today: what happens later is not recorded yet)."""
        last = min(treatment.end_date, self.today)
        unit_ids = [unit.pk for unit in treatment.units.all()]
        return {batch_id for batch_id in self.batch_ids
                if any(self.presence.present_between(unit_id, batch_id, treatment.start_date, last)
                       for unit_id in unit_ids)}

    # ---- the batch's water (farm/water/degree_days.py) ------------------------------------------------
    def degree_days(self, batch_id, end, needed):
        """(first day, estimated, days without a temperature, degree-days still to accrue, projected at the
        assumed temperature) of a withdrawal of `needed` degree-days after the last day `end` (rule 3 and 5); the
        first day is None when unknown."""
        if needed <= 0:
            return end + DAY, False, 0, ZERO, False
        total, missing, day = ZERO, 0, end
        while day < self.today:
            counted = self.water.day(batch_id, day + DAY)
            if counted.how == PENDING:
                break                       # today has no temperature yet: projected, not counted
            day += DAY
            missing += counted.missing
            total += counted.value
            if total >= needed:
                return day + DAY, False, missing, ZERO, False
        remaining = needed - total
        mean, assumed = self.water.projection(batch_id)
        if mean is None or mean <= 0:
            return None, True, missing, remaining, False
        days = int((remaining / mean).to_integral_value(rounding=ROUND_CEILING))
        return day + days * DAY + DAY, True, missing, remaining, assumed

    # ---- the withdrawals ----------------------------------------------------------------------------
    def of_treatment(self, treatment, batch_id):
        """The withdrawal of one batch from one treatment (rules 2 to 5)."""
        end, species = treatment.end_date, self.batches[batch_id].species
        self.load_rows({treatment.medicine_id})
        rule = rule_for(self.rows[treatment.medicine_id], species.pk)
        if rule is None:                    # nothing recorded for this species: unknown, never "no withdrawal"
            return Withdrawal(batch_id, None, False, treatment, species=species)
        by_days = end + (rule.days + 1) * DAY if rule.days is not None else None
        if rule.degree_days is None:
            return Withdrawal(batch_id, by_days, treatment=treatment, rule=rule, species=species)
        by_degrees, estimated, missing, remaining, at_assumed = self.degree_days(batch_id, end, rule.degree_days)
        if by_degrees is None:
            until, estimated = None, True
        elif by_days is not None and by_days > by_degrees:
            until, estimated = by_days, False
        else:
            until = by_degrees
        return Withdrawal(batch_id, until, estimated, treatment, rule=rule, species=species,
                          days_without_temperature=missing, assumed_temperature=self.water.assumed(batch_id),
                          projected_at_assumed=at_assumed and until == by_degrees,
                          remaining_degree_days=remaining if estimated else None)

    def uncovered_feedings(self):
        """Withdrawals of unknown end for the medicated feedings of the batches that no live in-feed
        treatment of their unit covers on their day (rule 6)."""
        unit_ids = list(self.units)
        records = list(FeedingRecord.objects.filter(unit_id__in=unit_ids, feed__feed_type=FeedType.MEDICATED)
                       .select_related('feed', 'unit'))
        if not records:
            return []
        found = []
        for record_id, parts in feeding_read.split_of(records).items():
            record = next(item for item in records if item.pk == record_id)
            if not any(covers(treatment, record) for treatment in self.treatments):
                found += [Withdrawal(batch_id, None, True, feeding=record)
                          for batch_id in sorted(parts, key=str) if batch_id in self.batch_ids]
        return found

    def withdrawals(self):
        """Every withdrawal of the batches, ended ones too."""
        found = [self.of_treatment(treatment, batch_id) for treatment in self.treatments
                 for batch_id in sorted(self.treated(treatment), key=str)]
        return found + self.uncovered_feedings()


def covers(treatment, record):
    """Whether a treatment (live, its units prefetched) is an in-feed course of the feeding's unit on its day."""
    return (treatment.method == TreatmentMethod.IN_FEED
            and treatment.start_date <= record.date <= treatment.end_date
            and any(unit.pk == record.unit_id for unit in treatment.units.all()))


def covered(record):
    """Whether a live in-feed treatment of the feeding's unit covers its day (the feeding dialog's notice)."""
    return any(covers(treatment, record) for treatment in
               Treatment.objects.filter(units=record.unit_id).prefetch_related('units'))


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


def _rows(medicine):
    """A medicine's withdrawal rows, the one for every species first (its `withdrawals`: prefetch them for a list)."""
    return sorted(medicine.withdrawals.all(), key=lambda row: (row.species_id is not None,
                                                                row.species.common_name if row.species_id else ''))


def rule_lines(medicine):
    """[(who it is for, Rule)] of a medicine's withdrawal rows as the Medicines page says them: "Every species"
    when that is the only row, else "Other species" for the one for every species, and the species' names."""
    rows = _rows(medicine)
    others = len(rows) > 1 and rows[0].species_id is None
    return [(row.species.common_name if row.species_id else (_('Other species') if others else _('Every species')),
             Rule.of(row)) for row in rows]


def rules_text(medicine):
    """A medicine's withdrawal as one line: "150 degree-days" when it is the same for every species, else
    "Atlantic salmon: 150 degree-days; Other species: 7 days"; "Not recorded" without a row."""
    rows = _rows(medicine)
    if not rows:
        return _('Not recorded')
    if len(rows) == 1 and rows[0].species_id is None:
        return Rule.of(rows[0]).text()
    return '; '.join(f'{who}: {rule.text()}' for who, rule in rule_lines(medicine))


def describe(withdrawal):
    """Why a withdrawal holds the fish and until when, in the active language."""
    if withdrawal.feeding is not None:
        record = withdrawal.feeding
        return _('Medicated feed %(feed)s was fed in %(unit)s on %(date)s and no in-feed treatment covers that '
                 'day: the withdrawal end is unknown. Record the treatment under Health › Treatments.') % {
            'feed': record.feed, 'unit': record.unit.code, 'date': shown_date(record.date)}
    treatment = withdrawal.treatment
    params = {'medicine': treatment.medicine, 'method': str(treatment.get_method_display()).lower(),
              'start': shown_date(treatment.start_date), 'end': shown_date(treatment.end_date)}
    if withdrawal.rule is None:
        return (_('%(medicine)s, %(method)s from %(start)s to %(end)s.') % params + ' '
                + _('No withdrawal is recorded for %(species)s of %(medicine)s: add it in Reference data › '
                    'Medicines.') % {'species': withdrawal.species.common_name, 'medicine': treatment.medicine})
    text = _('%(medicine)s, %(method)s from %(start)s to %(end)s: withdrawal %(rule)s.') % {
        **params, 'rule': withdrawal.rule.text()}
    if withdrawal.until is None:
        text += ' ' + _('The end cannot be worked out: record the water temperature.')
    elif withdrawal.projected_at_assumed:
        text += ' ' + projected_sentence(withdrawal.assumed_temperature)
    elif withdrawal.estimated:
        text += ' ' + _('Projected at the mean water temperature of the last days measured.')
    if withdrawal.days_without_temperature:
        text += ' ' + missing_sentence(withdrawal.days_without_temperature, withdrawal.assumed_temperature)
    return text


def provider(unit, day):
    """The health module's answer to farm.handling.withdrawal.blocks: a block per withdrawal that holds a
    batch in `unit` on `day`."""
    withdrawals = of_units([unit], day).get(unit.pk, [])
    batches = Batch.all_objects.in_bulk({withdrawal.batch_id for withdrawal in withdrawals})
    return [WithdrawalBlock(batches[withdrawal.batch_id], withdrawal.until, withdrawal.estimated,
                            describe(withdrawal), withdrawal.source) for withdrawal in withdrawals]

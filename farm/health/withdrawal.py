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
import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import formats
from django.utils.translation import gettext as _, ngettext

from core import audit
from core.models import AuditLog
from farm import withdrawal_gate as gate
from farm.feeding import read as feeding_read
from farm.handling import check
from farm.handling.withdrawal import WithdrawalBlock, harvest_from, source_key
from farm.models import (Batch, FeedingRecord, MedicineWithdrawal, StockMovement, Tank, Treatment,
                         WithdrawalAcknowledgement)
from farm.models.feed import FeedType
from farm.models.handling import WithdrawalWarning
from farm.models.health import TreatmentMethod
from farm.models.stock import MovementKind
from farm.stock.dates import earliest_today, local_today, shown_date
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

    def holds_between(self, first, last):
        """Whether it holds on some day from `first` to `last`: it has begun by `last` and has not ended on `first`."""
        return last >= self.start and (self.until is None or first < self.until)


class Reader:
    """The withdrawals of a set of batches, read on `today`.

    **Whose today** (the owner's decision of 12.11.2026: everything is read on the site's own day). Fish are read on
    today of the site they are on NOW: a unit's own withdrawal line, the harvest check and the Treatments list all make
    their reader with that day (`of_units`, `of_treatments`: one reader per site's day), so they are one answer. The
    company's day plays no part in whether fish are held. A write guard is not a page of one site: its day stays the
    earliest today among every unit the fish were in (`reach`), the caller's to give.

    **What has begun where it was given has begun** (`there`): which fish a course reached is read up to the day it is
    in the units the course was given in, not only up to `today`. For a reader on its own site's day that changes
    nothing where the course was given on that site; it makes a guard, whose day can be an earlier one, see a course
    begun today on the later clock (`holds`), which it did not."""

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

    # ---- what has begun where it was given ------------------------------------------------------
    def there(self, unit_ids):
        """The day it is where a course (or a medicated feeding) was given: the latest today among `unit_ids`, its
        units, never before this reader's `today`. Units none of this reader's batches were in are not asked: no fish
        of these batches were treated there."""
        return max([self.today, *(local_today(self.units[unit_id]) for unit_id in unit_ids if unit_id in self.units)])

    def holds(self, withdrawal):
        """For a reader whose `today` is not one site's own (a write guard, what blocks a deletion: the earliest day
        among several units): whether the withdrawal holds its batch now. It has begun where it was given (`there`)
        and has not ended on `today`: held on some day from the one to the other. A reader on its own site's day asks
        that day itself (`holds_on(today)`)."""
        given_in = ([unit.pk for unit in withdrawal.treatment.units.all()] if withdrawal.treatment is not None
                    else [withdrawal.feeding.unit_id])
        return withdrawal.holds_between(self.today, self.there(given_in))

    # ---- which fish a treatment reached ---------------------------------------------------------
    def treated(self, treatment, unit_ids=None):
        """The batches of this reader that had fish in one of the treatment's units on one of its days, up to the day
        it is in those units (`there`: what happens later is not recorded yet, and what has happened there has
        happened, whatever day this reader's `today` is). `unit_ids`: the units of a treatment not saved yet."""
        if unit_ids is None:
            unit_ids = [unit.pk for unit in treatment.units.all()]
        last = min(treatment.end_date, self.there(unit_ids))
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
    """{batch id: [Withdrawal]} of the withdrawals that hold the batches on `day`, read on `today`. Without a day (a
    question that is not one site's own: what blocks a deletion, on the earliest day among several units), those that
    hold them now by Reader.holds."""
    found = defaultdict(list)
    if batch_ids:
        reader = Reader(batch_ids, today)
        for withdrawal in reader.withdrawals():
            if reader.holds(withdrawal) if day is None else withdrawal.holds_on(day):
                found[withdrawal.batch_id].append(withdrawal)
    return found


def reach(unit_sets):
    """{key: (the batches ever in the units of `unit_sets[key]`, the farm's earliest today among EVERY unit those
    batches were ever in; None when the units never held fish)}, for several sets of units at once.

    The day a WRITE GUARD reads the withdrawals of fish on (`_reached`), as it always was: a withdrawal follows the
    fish, so the day is asked of every unit they were in, the one they are in now among them, and the earliest wins
    (the guard asks before the write stands, and asks rather once too often). The pages do not read this day: they
    read the site's own (`of_units`, `of_treatments`). Three queries whatever the number of keys."""
    every = {unit_id for unit_ids in unit_sets.values() for unit_id in unit_ids}
    in_units = Presence.of_units(every).batches if every else {}
    return earliest_days({key: {batch_id for unit_id in unit_ids for batch_id in in_units.get(unit_id, ())}
                          for key, unit_ids in unit_sets.items()})


def earliest_days(batch_sets):
    """{key: (the batches of `batch_sets[key]`, the farm's earliest today among every unit they were ever in; None for
    no batches)}: `reach` for fish that are known already."""
    every = {batch_id for batch_ids in batch_sets.values() for batch_id in batch_ids}
    units_of = Presence.of_batches(every).units if every else {}
    units = Tank.all_objects.select_related('production_department__site').in_bulk(
        {unit_id for unit_ids in units_of.values() for unit_id in unit_ids})
    return {key: (set(batch_ids), earliest_today(
        units[unit_id] for batch_id in batch_ids for unit_id in units_of.get(batch_id, ()) if unit_id in units)
        if batch_ids else None) for key, batch_ids in batch_sets.items()}


def _reached(unit_ids=(), species=None):
    """(the batches ever in `unit_ids` or of `species`, the farm's earliest today among the units they were in: the
    longest held; `reach`)."""
    batch_ids = set(reach({None: set(unit_ids)})[None][0]) if unit_ids else set()
    if species is not None:
        batch_ids.update(Batch.all_objects.filter(species=species).values_list('pk', flat=True))
    return earliest_days({None: batch_ids})[None]


def held_reached(unit_ids=(), species=None):
    """Why a unit, a loop (the units in it) or a species is not deleted or restored now: the batches a withdrawal holds
    today among the fish ever in `unit_ids` and the batches of `species`. Deleting or restoring one moves their
    withdrawals (the treatments' units, the loop's samples that count for a unit, the species' assumed temperature), so
    it waits until they end (cross-review 3). [] when none is held."""
    batch_ids, today = _reached(unit_ids, species)
    if not batch_ids:
        return []
    codes = sorted(Batch.all_objects.filter(pk__in=holding(batch_ids, today)).values_list('code', flat=True))
    if not codes:
        return []
    return [ngettext('A medicine withdrawal holds batch %(batches)s, and this moves it: wait until it ends.',
                     'Medicine withdrawals hold batches %(batches)s, and this moves them: wait until they end.',
                     len(codes)) % {'batches': ', '.join(codes)}]


def weighed(record, values, unit_ids):
    """What writing `values` ({attname: value}) to the stored `record` would do to the withdrawals of every fish ever in
    `unit_ids`, worked out as the guard works it (before, the write, after) in a savepoint rolled back: the messages
    of the change, [] when it changes none (the withdrawal gate's rule for a unit's loop, written outside the guard)."""
    batch_ids, today = _reached(unit_ids)
    if not batch_ids:
        return []
    before = snapshot(batch_ids, today)
    with transaction.atomic(), gate.opened('weighing a write, rolled back'):
        type(record)._base_manager.filter(pk=record.pk).update(**values)
        after = snapshot(batch_ids, today)
        transaction.set_rollback(True)
    return change(before, after).messages()


def blockers_while_live(record):
    """A unit's, a loop's, a species' or a sampling point's withdrawal_blockers() as they stand with it live (the
    withdrawal gate's rule for its deleted flag): the readers read live records, so the fish of a deleted unit show no
    withdrawal at all, and a restore is weighed as the record would stand restored, in a savepoint rolled back."""
    if not record.is_deleted:
        return record.withdrawal_blockers()
    with transaction.atomic(), gate.opened('weighing a restore, rolled back'):
        type(record)._base_manager.filter(pk=record.pk).update(is_deleted=False)
        record.is_deleted = False
        reasons = record.withdrawal_blockers()
        transaction.set_rollback(True)
    return reasons


def site_days(units):
    """{today: [unit]}: the units by today on their own site's clock. THE day fish are read on is the day of the site
    they are on now (the owner's decision of 12.11.2026); every page that reads a withdrawal groups its units here."""
    by_today = defaultdict(list)
    for unit in units:
        by_today[local_today(unit)].append(unit)
    return by_today


def of_units(units, day=None):
    """{unit id: [Withdrawal]} of the batches in each unit on `day` (default each unit's today) that a withdrawal
    holds then: the unit's own withdrawal line, and what the harvest check reads. One reader per site's day
    (`site_days`), asked that day itself."""
    found = {}
    for today, members in site_days(units).items():
        presence = Presence.of_units([unit.pk for unit in members])
        present = {unit.pk: presence.batches_in(unit.pk, day or today) for unit in members}
        held = holding({batch_id for batches in present.values() for batch_id in batches}, today, day or today)
        for unit in members:
            withdrawals = [withdrawal for batch_id in sorted(present[unit.pk], key=str)
                           for withdrawal in held.get(batch_id, [])]
            if withdrawals:
                found[unit.pk] = withdrawals
    return found


@dataclass(frozen=True)
class Reached:
    """A batch a treatment reached, as the Treatments list shows it: read on today of the site its fish are on now."""
    batch: Batch
    withdrawal: Withdrawal          # None: the treatment has no medicine, or is voided
    held: bool                      # the withdrawal holds the fish on `today`
    today: object                   # today on the site these fish are on
    units: tuple = ()               # the codes of the units of this part, when the batch is on sites of different days


def of_treatments(treatments):
    """{treatment id: [Reached]} for the Treatments list (the treatments' units prefetched): each batch a treatment
    reached with the withdrawal it puts on it, read as the unit's own line reads it (`of_units`): on today of the site
    the fish are on now, by the same reader, asked that same day. So the list, "Under withdrawal today", the day counts
    and the unit's line are one answer, for a site ahead of the company or behind it, a batch moved between clocks
    (the day of where it is now, with the course history it carries), a course begun today on its site, a batch that
    arrived today. A batch whose fish are on sites of different days is shown once per day, each part with its units
    and its own answer. Fish that are nowhere any more (harvested out) are read on the day of the units the course
    was given in. One reader per site's day."""
    given = {treatment.pk: {unit.pk for unit in treatment.units.all()} for treatment in treatments}
    every = {unit_id for unit_ids in given.values() for unit_id in unit_ids}
    in_units = Presence.of_units(every).batches if every else {}
    candidates = {pk: {batch_id for unit_id in unit_ids for batch_id in in_units.get(unit_id, ())}
                  for pk, unit_ids in given.items()}
    presence = Presence.of_batches({batch_id for batch_ids in candidates.values() for batch_id in batch_ids})
    units = Tank.all_objects.select_related('production_department__site').in_bulk(
        {unit_id for unit_ids in presence.units.values() for unit_id in unit_ids})
    today_of = {pk: local_today(unit) for pk, unit in units.items()}
    where, wanted = {}, defaultdict(set)
    for batch_id, unit_ids in presence.units.items():            # where each batch is now, by its site's day
        now = [units[unit_id] for unit_id in unit_ids
               if unit_id in units and presence.present(unit_id, batch_id, today_of[unit_id])]
        where[batch_id] = site_days(now)
    gone = {pk: earliest_today(units[unit_id] for unit_id in unit_ids if unit_id in units)
            for pk, unit_ids in given.items()}                   # the day of fish that are nowhere any more
    for pk, batch_ids in candidates.items():
        for batch_id in batch_ids:
            for today in where.get(batch_id) or {gone[pk]: []}:
                wanted[today].add(batch_id)
    readers = {today: Reader(batch_ids, today) for today, batch_ids in wanted.items()}
    batches = Batch.all_objects.in_bulk({batch_id for batch_ids in candidates.values() for batch_id in batch_ids})
    found = {}
    for treatment in treatments:
        treated = {today: reader.treated(treatment) for today, reader in readers.items()}
        rows = []
        for batch_id in candidates[treatment.pk]:
            days = where.get(batch_id) or {gone[treatment.pk]: []}
            for today, members in days.items():
                if batch_id not in treated[today]:
                    continue
                held = (readers[today].of_treatment(treatment, batch_id)
                        if treatment.medicine_id and not treatment.is_deleted else None)
                rows.append(Reached(batches[batch_id], held, held is not None and held.holds_on(today), today,
                                    tuple(sorted(unit.code for unit in members)) if len(days) > 1 else ()))
        found[treatment.pk] = sorted(rows, key=lambda each: (each.batch.code, each.units))
    return found


# ---- harvests already recorded inside a withdrawal (audit F-195) -----------------------------------------
@dataclass(frozen=True)
class HarvestInside:
    """A harvest recorded on a day a withdrawal holds fish of its unit: its own batch, or a batch that shared the unit
    that day (`held`; a net cannot separate the batches of a unit, flow fault S-02): fish that may have gone to food
    medicated. It arises
    when the withdrawal is entered or grows after the harvest (a backdated treatment, a longer course, a corrected
    temperature, a medicine's withdrawal changed); a harvest made while the withdrawal was known is warned of then
    (farm/handling/check.py). As a warning of a treatment's dialog it is acknowledged like the handling warnings
    (`warning`, `key`, `message`, and what the acknowledgement keeps: `operation_id`, `until`, `approximate`,
    `reason`, and `batch`: the batch that is held, as the harvest's own acknowledgement names it)."""
    line: object                          # the harvest's StockMovement: its operation, unit, batch, fish
    withdrawal: Withdrawal
    held: object = None                   # the Batch the withdrawal holds; None: read as the harvest's own

    warning = WithdrawalWarning.HARVESTED

    @property
    def operation_id(self):
        return self.line.operation_id

    @property
    def until(self):
        return self.withdrawal.until

    @property
    def approximate(self):
        return self.withdrawal.estimated

    @property
    def reason(self):
        return describe(self.withdrawal)

    @property
    def fish(self):
        return -self.line.count_delta

    @property
    def facility(self):
        record = getattr(self.line.operation, 'harvest_record', None)
        return record.facility if record is not None else None

    @property
    def batch(self):
        """The batch the withdrawal holds: the harvest's own, or the one that shared its unit that day."""
        return self.held if self.held is not None else self.line.batch

    @property
    def own(self):
        """Whether the withdrawal holds the harvested batch itself (else a batch that shared its unit)."""
        return self.withdrawal.batch_id == self.line.batch_id

    def key(self):
        """What the person saw, as text: a change in it asks them again. The withdrawal is named by what it says, not by
        its record's id: a write asked about and sent again makes a new record."""
        return (f'harvested:{self.line.operation_id}:{self.line.batch_id}:{self.withdrawal.batch_id}:{self.until}:'
                f'{self.approximate}:{self.reason}')

    def identity(self):
        """Which harvest of which batch inside which withdrawal of which batch: what a guard compares before and after
        a write."""
        return (self.line.operation_id, self.line.batch_id, self.withdrawal.batch_id,
                source_key(self.withdrawal.source))

    def message(self):
        """The warning in the person's language (the activity log builds it in English)."""
        params = {'date': shown_date(self.line.operation.date), 'unit': self.line.unit.code,
                  'batch': self.line.batch.code, 'fish': formats.number_format(self.fish, force_grouping=True),
                  'facility': self.facility.name if self.facility is not None else _('an unknown facility'),
                  'end': harvest_from(self.until, self.approximate)}       # the one wording of a withdrawal's end
        text = _('Harvest of %(date)s from %(unit)s (%(batch)s, %(fish)s fish to %(facility)s) lies inside this '
                 'withdrawal (%(end)s): medicated fish may have gone to food.') % params
        if not self.own:
            text += ' ' + _('The withdrawal is of %(held)s, which was in %(unit)s with the fish harvested: the fish of '
                            'one unit cannot be told apart.') % {'held': self.batch.code, 'unit': self.line.unit.code}
        return text

    def same_harvest(self):
        """Which harvest of which batch it is, whatever the withdrawal's end."""
        return self.line.operation_id, self.line.batch_id


def _harvest_lines(batch_ids=None, since=None, unit_ids=()):
    """The live harvest lines (of `batch_ids`, and of any batch out of `unit_ids`; from `since`), with what a finding
    names."""
    lines = StockMovement.objects.filter(kind=MovementKind.HARVEST, operation__is_deleted=False).select_related(
        'operation__harvest_record__facility', 'unit__production_department__site', 'batch')
    if batch_ids is not None:
        lines = lines.filter(Q(batch_id__in=batch_ids) | Q(unit_id__in=unit_ids))
    if since is not None:
        lines = lines.filter(operation__date__gte=since)
    return list(lines.order_by('operation__date', 'unit__code', 'pk'))


def _inside(reader, withdrawals, lines):
    """THE rule: a harvest lies inside a withdrawal that holds on the harvest's day (Withdrawal.holds_on: from the
    treatment's first day, or the medicated feeding's, to the day before the batch may be harvested) and is of the
    harvested batch, or of a batch that had fish in the harvested unit that day (the stock's presence, as the unit's own
    withdrawal line and the harvest's handling check read it: the fish of one unit go to food together, S-02).
    `withdrawals` are `reader`'s (its presence and its batches say who was where)."""
    found = []
    for held in withdrawals:
        for line in lines:
            day = line.operation.date
            if held.holds_on(day) and (held.batch_id == line.batch_id
                                       or reader.presence.present(line.unit_id, held.batch_id, day)):
                found.append(HarvestInside(line, held, reader.batches[held.batch_id]))
    return sorted(found, key=lambda each: (each.line.operation.date, each.line.unit.code, each.line.pk,
                                           each.withdrawal.start, each.batch.code))


def harvests_inside():
    """Every live harvest that lies inside a withdrawal of a batch of its unit, however it came to (check_withdrawal):
    one reader per farm-local today of the harvested units (sites in different time zones), over the harvested batches
    and the batches that shared a harvested unit on the harvest's day."""
    every = _harvest_lines()
    presence = Presence.of_units({line.unit_id for line in every}) if every else None
    by_today = defaultdict(list)
    for line in every:
        by_today[local_today(line.unit)].append(line)
    found = []
    for today, lines in sorted(by_today.items()):
        batch_ids = {line.batch_id for line in lines}
        for line in lines:
            batch_ids |= presence.batches_in(line.unit_id, line.operation.date)
        reader = Reader(batch_ids, today)
        found += _inside(reader, reader.withdrawals(), lines)
    return found


# ---- the withdrawal guard: every write that changes a withdrawal (cross-reviews 1 and 2 of F-195, F-196) ----
def _end(withdrawals):
    """The latest end of some withdrawals, None (unknown) being the latest of all; with none, there is no end."""
    dated = [each.until for each in withdrawals]
    return None if any(until is None for until in dated) else max(dated)


def _later(first, second):
    """Whether withdrawal end `first` is after `second` (None: unknown, later than any day)."""
    if first is None:
        return second is not None
    return second is not None and first > second


@dataclass(frozen=True)
class Released:
    """Fish held today by a withdrawal whose end a write moves earlier (`until_after`), or ends today (no withdrawal
    holds them after it: `freed`): a course voided or shortened, a medicine's withdrawal shortened, a medicated feeding
    voided, a temperature corrected. Asked whether or not the new end is still ahead (cross-review 2, 4)."""
    batch: object
    withdrawal: Withdrawal                # the one that held the batch longest before the write
    until_after: object = None            # the end after the write
    freed: bool = False                   # no withdrawal holds the batch today after the write

    warning = WithdrawalWarning.RELEASED
    harvest = None

    @property
    def until(self):
        return self.withdrawal.until

    @property
    def approximate(self):
        return self.withdrawal.estimated

    @property
    def reason(self):
        return describe(self.withdrawal)

    def key(self):
        after = 'free' if self.freed else self.until_after
        return f'released:{self.batch.pk}:{self.until}:{after}:{self.approximate}:{self.reason}'

    def message(self):
        params = {'batch': self.batch.code, 'withdrawal': self.reason,
                  'until': shown_date(self.until) if self.until else _('an unknown end'),
                  'after': shown_date(self.until_after) if self.until_after else _('an unknown end')}
        if self.freed:
            return _('%(batch)s is held today (%(withdrawal)s) and would no longer be held by a medicine withdrawal after '
                     'this change: the fish could go to food.') % params
        return _('%(batch)s is held (%(withdrawal)s): after this change its withdrawal would end earlier, the fish may go '
                 'to food from %(after)s instead of %(until)s.') % params


@dataclass(frozen=True)
class Snapshot:
    """The withdrawals of some batches as the stored facts give them now: the harvests inside one (by identity) and the
    withdrawals that hold each batch today."""
    inside: dict
    held: dict


def snapshot(batch_ids, today):
    if not batch_ids:
        return Snapshot({}, {})
    reader = Reader(batch_ids, today)
    found = reader.withdrawals()
    held = defaultdict(list)
    for each in found:
        if reader.holds(each):            # held now, by the reader's rule for several clocks: the guards read it too
            held[each.batch_id].append(each)
    # The harvests of these batches, and of any batch out of a unit these batches were in: a harvest of another batch
    # lies inside a withdrawal of one of these when they shared its unit that day (`_inside`).
    lines = _harvest_lines(batch_ids, unit_ids=set(reader.units))
    return Snapshot({each.identity(): each for each in _inside(reader, found, lines)}, dict(held))


def _longest(withdrawals):
    return max(withdrawals, key=lambda each: (each.until is None, each.until or each.start))


@dataclass
class Change:
    """What a write did to the withdrawals of the fish it touched: the harvests it brought inside one, or whose
    withdrawal it made end later than before (`harvested`; an acknowledgement covers the end it was given for), and the
    held batches whose withdrawal it made end earlier or ended (`released`). Acknowledged through one box."""
    harvested: list = field(default_factory=list)
    released: list = field(default_factory=list)

    @property
    def warnings(self):
        return self.harvested + self.released

    @property
    def fingerprint(self):
        keys = sorted(warning.key() for warning in self.warnings)
        return hashlib.sha256('|'.join(keys).encode()).hexdigest()[:20] if keys else ''

    def messages(self):
        return [warning.message() for warning in self.warnings]

    @property
    def second_person(self):
        """Why this change cannot be gone past by a tick, or '': a second person must approve (check.needs_second_person,
        flow fault M-27: said with the question, not after the tick)."""
        return check.second_person_text() if check.needs_second_person(self) else ''


def change(before, after, exclude_operation=None):
    """The Change between two snapshots of the same batches. A harvest the write itself records is left out: the
    harvest's own handling check asks about the withdrawal in force on its day."""
    harvested = [found for key, found in after.inside.items() if found.operation_id != exclude_operation
                 and (key not in before.inside or _later(found.until, before.inside[key].until))]
    released = []
    batches = Batch.all_objects.in_bulk(list(before.held))
    for batch_id in sorted(before.held, key=str):
        old = _longest(before.held[batch_id])
        if batch_id not in after.held:
            released.append(Released(batches[batch_id], old, freed=True))
        else:
            new_end = _end(after.held[batch_id])
            if _later(_end(before.held[batch_id]), new_end):
                released.append(Released(batches[batch_id], old, until_after=new_end))
    return Change(harvested, released)


class WithdrawalChanged(ValidationError):
    """The guard's refusal (on the field `withdrawal_ack`), with the Change it found for the dialog to show."""

    def __init__(self, found, errors):
        super().__init__(errors)
        self.change = found

    def __reduce__(self):
        # Pickled (the parallel test runner, a worker) as what it was made of: ValidationError's own args are not its
        # constructor's.
        return type(self), (self.change, self.message_dict)


FIELD = 'withdrawal_ack'


def guarded(user, batch_ids, today, write, *, seen=None, record_of=None, exclude_operation=None):
    """THE one function every write that can create, grow, shorten or end a medicine withdrawal goes through (a
    treatment, its last day and its void, a medicated feeding and its void, a medicine's withdrawal rows, a water
    sample and its void, a stock operation and its void, a feed's type, a species' assumed temperature, a sampling
    point's active flag, kind and owner); the data layer refuses those writes anywhere else (farm/withdrawal_gate.py).

    Inside the caller's transaction, after its locks, it works out the withdrawals of `batch_ids` (the fish the write can
    touch, on the farm's `today`) before the write, makes the write ONCE in a savepoint and works them out again from
    what it left. When the write brings a recorded harvest inside a withdrawal (or makes one it is inside end later), or
    makes the withdrawal of fish held today end earlier, the person must have gone on past exactly this impact: `seen`
    is the fingerprint the write's own form carried (its box `withdrawal_ack`). Otherwise the savepoint is rolled back
    and the write refused (WithdrawalChanged, which carries what was found for the dialog). A `seen` that is not this
    impact's fingerprint (the impact changed since it was shown) is refused the same way. Going on stores a
    WithdrawalAcknowledgement per warning, naming the record `record_of(result)` (default: the result), and a critical
    log entry on it with what was acknowledged; the second-person hook is asked as for every withdrawal warning.
    `exclude_operation(result)`: a harvest the write itself records (its own handling check asks). Returns what
    `write()` returned."""
    batch_ids = set(batch_ids)
    seen = seen or ''
    before = snapshot(batch_ids, today)
    with gate.opened('withdrawal guard'), transaction.atomic():
        result = write()
        excluded = exclude_operation(result) if exclude_operation else None
        found = change(before, snapshot(batch_ids, today), excluded)
        if found.warnings or seen:
            if seen != found.fingerprint and not found.warnings:
                raise WithdrawalChanged(found, {FIELD: _('The warnings changed since the form was shown: read them '
                                                         'again, and tick the box to go on.')})
            check.require_acknowledged(found, seen, field=FIELD, user=user,
                                       refused=lambda errors: WithdrawalChanged(found, errors))
        if found.warnings:
            _acknowledge(user, record_of(result) if record_of else result, found)
    return result


def _acknowledge(user, record, found):
    """One WithdrawalAcknowledgement per warning gone past, naming the record, the batch, the withdrawal and the
    harvest, with what was shown; and a critical log entry on the record with the warnings, in English."""
    with audit.source_language():
        record_type = audit.english(audit.entity_type_of(type(record)))
        label = audit.bounded(audit.english(record))
        messages = ' '.join(found.messages())
    WithdrawalAcknowledgement.objects.bulk_create([
        WithdrawalAcknowledgement(
            created_by=user, record_type=record_type, record_id=str(record.pk), record_label=label,
            warning=warning.warning, batch=warning.batch,
            harvest_id=warning.line.operation_id if warning.warning == WithdrawalWarning.HARVESTED else None,
            source=source_key(warning.withdrawal.source), until=warning.until, approximate=warning.approximate, reason=warning.reason[:500])
        for warning in found.warnings])
    audit.record(user, AuditLog.Action.UPDATE, record, {'Withdrawal warnings acknowledged': [None, messages]},
                 label=label, severity=AuditLog.Severity.CRITICAL)


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


def provider(units, day):
    """The health module's answer to farm.handling.withdrawal.blocks_of: {unit id: [block]}, a block per withdrawal
    that holds a batch in the unit on `day` (None: the unit's own today); the units without one are left out."""
    withdrawals = of_units(units, day)
    batches = Batch.all_objects.in_bulk({withdrawal.batch_id for held in withdrawals.values() for withdrawal in held})
    return {unit_id: [WithdrawalBlock(batches[withdrawal.batch_id], withdrawal.until, withdrawal.estimated,
                                      describe(withdrawal), withdrawal.source) for withdrawal in held]
            for unit_id, held in withdrawals.items()}


def guarded_units(user, unit_ids, first, write, seen=None):
    """A write about reference data the withdrawals of the fish in `unit_ids` (from the day `first` on; None: every fish they ever held) are worked out
    from (a feed's type, a species' assumed temperature, a sampling point): those fish are locked as a stock operation
    locks them, and the write goes through the guard."""
    from farm.stock.services import lock_fish
    units, batch_ids = lock_fish(set(unit_ids), first) if unit_ids else ({}, set())
    today = earliest_today(units.values())
    return guarded(user, batch_ids, today, write, seen=seen)

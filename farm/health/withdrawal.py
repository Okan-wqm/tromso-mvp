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
1. **It holds the fish that were exposed, not their batch** (flow fault S-03; the owner, 14.11.2026; the lots:
   `Reader.lots`, a lot = the fish of one batch in one unit over one stay, worked out on read, nothing stored):
   A. T reached the fish of b that were in one of T's units on a day from T's first day to its last (today at the
      latest; farm.stock.read.Presence.during: at any moment of the day, so fish that passed through a treated unit
      on a course day are reached). T's withdrawal of b is worked out for b (its species' row, rules 2 to 5).
   B. The hold follows those fish: every move out of a held lot, dated on or after the day the lot became held,
      holds the lot the fish go into, to the same end.
   C. A unit is held as a whole: a batch that is in a unit at any moment of a day a held lot is in it is held there
      from that day, to the same end, and stays held after either moves on (they can no longer be told apart; the
      owner's example: tank C held to 23.11). The unit's line names the batch and says how: "These fish shared T-03
      with B-2026-001 (treated in T-01)."; and when that batch was itself only held by sharing, the treated batch as
      the source: "These fish shared T-03 with B-2026-002, which waits with B-2026-001 (treated in T-01)."
   D. Not held: fish of b that left the treated unit before T's first day, or were never in it, in a unit no held
      fish came into. A lot ends the day its last fish leave the unit (it still holds that day: a harvest of that
      day lies inside); fish of the same batch that come into the unit later are another lot.
   E. An unknown end (rule 0, rule 6) holds the same fish.
   The withdrawal is asked of a DAY: the order of the operations within the day is not read (a move has no time), so
   fish that left a unit on the day held fish came into it are held too (over-warned, never under-warned).
   **Cleaner fish** (the owner, 16.11.2026, decision 6; farm.handling.check.held_apart): a held lot of production
   fish holds the unit as a whole, the cleaner fish beside it too, and their hold follows them where they are moved
   (B); a held lot of cleaner fish never makes another lot held: sharing a unit with held cleaner fish carries no
   hold onward, to production fish or to other cleaner fish (the production fish's harvest dialog says it as a note).
   **Degree-days are still the exposed batch's** (rule 3: the lowest daily mean among EVERY unit b is in, also a
   unit that was never treated: the latest end, the safe side), until a vet has said whether they follow the held
   fish alone (RULES F). So for a degree-day medicine an untreated sibling unit's water still moves the end, and
   deleting that unit or its loop stays blocked (`held_reached`).
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
8. **An end unknown for want of a rule holds for a number of days only** (the owner's decision 10 of 17.11.2026; the
   platform owner's setting "An unknown withdrawal end holds for (days)", 180 until they set another): a withdrawal
   that has no rule to end by (rule 0: no row for the species; rule 6: medicated feed with no treatment) holds, and
   spreads as any other hold, to the day that many days after the course's last day (the medicated feeding's day).
   From the next day (`gives_up`) the fish are NOT held: no warning, nothing blocked. The course is then listed as an
   unresolved old course on the Treatments page and by `check_withdrawal` (`unresolved`), with what must be entered
   to give it an end. **It never applies to a degree-day withdrawal** (decision 11 of 18.11.2026, following decision
   9): degree-days that are short, or cannot be counted or projected for want of a temperature (rule 5: also a mean
   of 0 °C or below), hold until the farm records the water temperature or sets the species' assumed temperature,
   however old the course is; the unit's line and `describe` say both. A change of the setting is a change of a
   rule: it goes through the guard (`guarded_ceiling`), which asks when a shorter one would free fish held today, and
   when a longer one would hold fish again or bring a recorded harvest inside a withdrawal.

`until` is the first day b may be harvested; a withdrawal holds from the treatment's first day (or the
medicated feeding's day) to the day before `until`: a day before the treatment is not held. The health module
gives the harvest side these blocks through the registry of farm/handling/withdrawal.py (`provider`)."""
import hashlib
from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import ROUND_CEILING, Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import formats
from django.utils.translation import gettext as _, ngettext

from core import audit, sealing
from core.platform import correction_window_days, unknown_withdrawal_days
from core.models import AuditLog
from farm import withdrawal_gate as gate
from farm.feeding import read as feeding_read
from farm.handling import check
from farm.handling.withdrawal import WithdrawalBlock, harvest_from, leave_from, source_key
from farm.models import (Batch, FeedingRecord, HandlingAcknowledgement, MedicineWithdrawal, StockMovement, Tank, Treatment,
                         WithdrawalAcknowledgement)
from farm.models.feed import FeedType
from farm.models.handling import AcknowledgedWarning, WithdrawalWarning
from farm.models.health import TreatmentMethod
from farm.models.stock import MovementKind
from farm.stock import read as stock_read
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
    gives_up: object = None               # an unknown end: the first day it no longer holds (rule 8); else None

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

    @property
    def ends(self):
        """The first day it no longer holds: the first day the batch may be harvested, or for an end unknown for want
        of a rule the day it gives up (rule 8). None: no such day is known, it holds on: degree-days that cannot be
        counted or projected (rule 5), which never give up."""
        return self.until if self.until is not None else self.gives_up

    def holds_on(self, day):
        """From its first day (fish under treatment are held too) to the day before it ends."""
        return day >= self.start and (self.ends is None or day < self.ends)

    def holds_between(self, first, last):
        """Whether it holds on some day from `first` to `last`: it has begun by `last` and has not ended on `first`."""
        return last >= self.start and (self.ends is None or first < self.ends)


@dataclass(frozen=True)
class Hold:
    """A lot a withdrawal holds: the fish of one batch (`batch_id`) in one unit over one stay, from the day they became
    held there (`since`) to the day the last of them left the unit (`left`; None: they are there). `via_unit` and
    `via_batch` (codes) say how fish that were not exposed themselves came to be held: the unit they shared with held
    fish, and whose; '' for the exposed fish and the lots they were moved into. `chain`: the fish they shared it with
    were themselves held only by sharing a unit (they were never treated, and need not have been in a treated unit).
    `treated_in`: the codes of the units the withdrawal's batch (`of_batch`: its code) was exposed in (`exposed_in`:
    their ids): the source of the hold. Everything else is the withdrawal's (its end, its cause, its rule)."""
    withdrawal: Withdrawal
    unit_id: object
    batch_id: object
    since: object
    left: object = None
    via_unit: str = ''
    via_batch: str = ''
    treated_in: tuple = ()
    exposed_in: frozenset = frozenset()
    chain: bool = False
    of_batch: str = ''

    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return getattr(self.withdrawal, name)

    @property
    def shared(self):
        """Held because these fish shared a unit with held fish, not because they were exposed themselves."""
        return bool(self.via_unit)

    @property
    def own(self):
        """The fish of the batch the withdrawal was worked out for, exposed themselves."""
        return not self.shared and self.batch_id == self.withdrawal.batch_id

    def there(self, day):
        """Whether the lot is in its unit on `day` (the day its fish left counts)."""
        return self.since <= day and (self.left is None or day <= self.left)

    def on(self, day):
        """Whether the lot is held on `day`: it is there, and the withdrawal holds that day."""
        return self.there(day) and self.withdrawal.holds_on(day)


def _rank(hold):
    """What the latest of several holds is told by: an unknown end is the latest of all; of two equal ends the exposed
    fish's own comes first."""
    return hold.until is None, hold.until or date.min, hold.own, not hold.shared


LIFE = object()        # Reader(first=LIFE): from the first day that can matter to the batches asked


@sealing.reads_as_system('the medicine withdrawal')
class Reader:
    """The withdrawals of a set of batches, read on `today`.

    **The batches read are more than the batches asked** (`asked`): a batch can be held by a course given in a unit it
    was never in, through a unit it shared with held fish (rule 1 C). **What is read is bounded by what can hold fish
    in the window asked** (`first`..`last`, default today), never by the farm's history (review of S-03, F-3):
    - the causes: the live courses with a medicine begun by `last`, a course left out when its medicine's withdrawal
      is in days for every species and has ended before `first` whatever the species (no fish needs reading for
      that); the medicated feedings no in-feed course covers;
    - the batches those courses can have exposed (by the spans: farm.stock.read.between), with the batches asked:
      their lines are read, and their withdrawals worked out; a withdrawal that ended before `first` is dropped;
    - the batches the withdrawals left can have reached while in force (farm.stock.read.reach): read too, in one
      more query.
    So a batch that only shared a unit with fish that were never held, or long after a hold ended, is not read. One
    grouped query (`spans`: its answer, when the caller has it) says who was where; the number of queries does not
    grow with the units or the batches. A course with no rule to end by (no withdrawal row, an uncovered medicated
    feeding) is in force for the days of rule 8, and its fish are read for as long; degree-days that cannot be counted
    hold, and are read, until they can (a course with a degree-day row is never left out by its age).
    `first=LIFE`: from the first day that can matter to the batches asked (their earliest harvest, the earliest
    course that can have exposed them, the first day of the correction window): a write guard, which compares the
    harvests of their whole life and everything a record dated in the window can reach.
    `back` (with LIFE): a day the write reaches back to that the batches' own records do not tell (a write of
    reference data is not a dated record: a feed made Medicated holds fish from its first feeding, a longer ceiling
    from the oldest course without a rule), so the read starts there at the latest.
    `also`: treatments the caller will ask `of_treatment` of whatever their end (the Treatments list).
    `ceiling`: the days an end without a rule holds, in the place of the setting (what the longest setting could
    hold: `guarded_ceiling`).

    **Whose today** (the owner's decision of 12.11.2026: everything is read on the site's own day). Fish are read on
    today of the site they are on NOW: a unit's own withdrawal line, the harvest check and the Treatments list all make
    their reader with that day (`of_units`, `of_treatments`: one reader per site's day), so they are one answer. The
    company's day plays no part in whether fish are held. A write guard is not a page of one site: its day stays the
    earliest today among every unit the fish were in (`reach`), the caller's to give.

    **What has begun where it was given has begun** (`there`): which fish a course reached is read up to the day it is
    in the units the course was given in, not only up to `today`. For a reader on its own site's day that changes
    nothing where the course was given on that site; it makes a guard, whose day can be an earlier one, see a course
    begun today on the later clock (`holds`), which it did not."""

    def __init__(self, batch_ids, today, spans=None, first=None, last=None, also=(), back=None, ceiling=None):
        self.asked, self.today = set(batch_ids), today
        self.spans = stock_read.spans() if spans is None else spans
        self._withdrawals = self._lots = None
        self._ceiling = ceiling
        # A day beyond: a course begun today on a later clock has begun (`there`).
        self.last = max(today, last or today) + DAY
        every = list(Treatment.objects.filter(medicine__isnull=False, start_date__lte=self.last)
                     .select_related('medicine').prefetch_related('units').order_by('start_date', 'pk'))
        self.rows = {}                                 # medicine id -> its withdrawal rows
        self.load_rows({each.medicine_id for each in [*every, *also] if each.medicine_id})
        self.first = self._life(every, back) if first is LIFE else (today if first is None else first)
        self.in_feed = [each for each in every if each.method == TreatmentMethod.IN_FEED]
        self.listed = {each.pk for each in also}
        self.treatments = [each for each in every if each.pk in self.listed or not self._over(each)]
        records = list(FeedingRecord.objects.filter(feed__feed_type=FeedType.MEDICATED, date__lte=self.last)
                       .select_related('feed', 'unit'))
        self.feedings = [record for record in records
                         if not any(covers(treatment, record) for treatment in self.in_feed)]
        if self.feedings:                              # an unknown end that has given up before the window (rule 8)
            self.feedings = [record for record in self.feedings
                             if record.date + (self.ceiling + 1) * DAY > self.first]
        exposed = set()
        for treatment in [*self.treatments, *also]:
            exposed |= stock_read.between(self.spans, [unit.pk for unit in treatment.units.all()],
                                          treatment.start_date, treatment.end_date)
        for record in self.feedings:
            exposed |= stock_read.between(self.spans, [record.unit_id], record.date, record.date)
        self.batch_ids = exposed | self.asked
        self.presence = Presence.of_batches(self.batch_ids, moves=True)
        water = today - LOOKBACK_DAYS * DAY
        for treatment in [*self.treatments, *also]:        # the temperatures a degree-day end is added up from
            if any(row.degree_days is not None for row in self.rows.get(treatment.medicine_id, ())):
                water = min(water, treatment.end_date + DAY)
        self.water = BatchWater(self.batch_ids, today, water, presence=self.presence)
        self.units, self.batches = self.water.units, self.water.batches

    @property
    def ceiling(self):
        """The days an unknown end holds (rule 8), read once, and only when a course needs it."""
        if self._ceiling is None:
            self._ceiling = unknown_withdrawal_days()
        return self._ceiling

    def _over(self, treatment):
        """Whether a course's withdrawal has ended before the window whatever fish it reached: its medicine has no
        degree-day row, and the longest it can hold has run out: its longest row in days, and, when a species may be
        without a row (none is for every species), the days an unknown end holds (rule 8). A degree-day row needs
        the fish read to say."""
        rows = self.rows.get(treatment.medicine_id, ())
        if any(row.degree_days is not None for row in rows):
            return False
        longest = max((Rule.of(row).days for row in rows), default=0)
        if not any(row.species_id is None for row in rows):
            longest = max(longest, self.ceiling)
        return treatment.end_date + (longest + 1) * DAY <= self.first

    def _bounded(self, held):
        """A withdrawal whose end is unknown for want of a rule (no withdrawal row for the species, a medicated
        feeding no course covers) with the day it gives up (rule 8); any other as it is. A degree-day withdrawal never
        gives up (the owner's decisions 9 and 11): its end is not reached yet, or cannot be counted until a temperature
        is recorded, and its fish stay held as they always were."""
        if held.until is not None or held.rule is not None:
            return held
        last = held.treatment.end_date if held.treatment is not None else held.feeding.date
        return replace(held, gives_up=last + (self.ceiling + 1) * DAY)

    def _life(self, treatments, back=None):
        """The first day that can matter to the batches asked: their earliest live harvest or live delivery (the lines
        `_harvest_lines` compares), the first day of the
        earliest course that can have exposed them (by the spans), and the first day a record can still be dated on
        (the correction window): a course, a feeding or a move entered now for a day in the window holds fish from
        that day, also fish of other batches and their harvests, and both snapshots of a guard must read from before
        it. The window bounds a DATED record only: a write of reference data changes withdrawals from a day of its
        own (`back`), and a read that began later would hide the harvests it puts inside one (verification V-6)."""
        days = [self.today - correction_window_days() * DAY]
        if back is not None:
            days.append(back)
        harvested = (StockMovement.objects.filter(kind__in=sorted(check.WITHDRAWAL_LINES.values()),
                                                  operation__is_deleted=False, batch_id__in=self.asked)
                     .order_by('operation__date').values_list('operation__date', flat=True).first())
        if harvested is not None:
            days.append(harvested)
        for treatment in treatments:
            if self.asked & stock_read.between(self.spans, [unit.pk for unit in treatment.units.all()],
                                               treatment.start_date, treatment.end_date):
                days.append(treatment.start_date)
                break                                  # they are in the order of their first days
        return min(days)

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
    def exposed(self, treatment, unit_ids=None):
        """{batch id: {unit id: [day]}}: the fish a treatment reached (rule 1 A). For each of this reader's batches
        that had fish in one of the treatment's units at any moment of one of its days, up to the day it is in those
        units (`there`: what happens later is not recorded yet, and what has happened there has happened, whatever day
        this reader's `today` is), the units and in each the days its fish became exposed: the course's first day
        when they were there, and every later course day fish of it came in. `unit_ids`: the units of a treatment not
        saved yet."""
        if unit_ids is None:
            unit_ids = [unit.pk for unit in treatment.units.all()]
        first, last = treatment.start_date, min(treatment.end_date, self.there(unit_ids))
        found = defaultdict(dict)
        for unit_id in unit_ids:
            for batch_id in self.presence.batches.get(unit_id, ()):
                days = sorted(day for day in self.presence.arrived.get((unit_id, batch_id), ()) if first < day <= last)
                if first <= last and self.presence.during(unit_id, batch_id, first):
                    days.insert(0, first)
                if days:
                    found[batch_id][unit_id] = days
        return found

    def treated(self, treatment, unit_ids=None):
        """The batches of this reader with fish a treatment reached (`exposed`)."""
        return set(self.exposed(treatment, unit_ids))

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
        """The withdrawal of one batch from one treatment (rules 2 to 5, and 8 for an unknown end)."""
        return self._bounded(self._of_treatment(treatment, batch_id))

    def _of_treatment(self, treatment, batch_id):
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
        records = self.feedings
        if not records:
            return []
        found = []
        for record_id, parts in feeding_read.split_of(records).items():
            record = next(item for item in records if item.pk == record_id)
            found += [self._bounded(Withdrawal(batch_id, None, True, feeding=record))
                      for batch_id in sorted(parts, key=str) if batch_id in self.batch_ids]
        return found

    def withdrawals(self):
        """Every withdrawal of the batches, ended ones too: one per cause and batch exposed by it."""
        if self._withdrawals is None:
            self._seeds = []                      # beside each withdrawal: {unit id: [day]} its batch was exposed
            found = []
            for treatment in self.treatments:
                exposed = self.exposed(treatment)
                for batch_id in sorted(exposed, key=str):
                    held = self.of_treatment(treatment, batch_id)
                    # in force in the window, or after it; or a course the caller lists whatever its end
                    if held.ends is None or held.ends > self.first or treatment.pk in self.listed:
                        found.append(held)
                        self._seeds.append(exposed[batch_id])
            for held in self.uncovered_feedings():
                found.append(held)
                self._seeds.append({held.feeding.unit_id: [held.feeding.date]})
            self._withdrawals = found
            self._read_reached()
        return self._withdrawals

    def _read_reached(self):
        """Reads the batches the withdrawals in force can have reached (farm.stock.read.reach, by the spans) that are
        not read yet: their lines and moves in one query, the batches and their units in two. The walk then finds
        every batch a held lot met among the batches read."""
        wanted = set()
        for held, seeds in zip(self._withdrawals, self._seeds):
            wanted |= stock_read.reach(self.spans, [(unit_id, held.batch_id, min(days))
                                                    for unit_id, days in seeds.items()], held.ends)
        missing = wanted - self.batch_ids
        if not missing:
            return
        self.presence.add(Presence.of_batches(missing, moves=True))
        self.batches.update(Batch.all_objects.select_related('species').in_bulk(missing))
        unit_ids = {unit_id for batch_id in missing for unit_id in self.presence.units.get(batch_id, ())}
        self.units.update(Tank.all_objects.select_related('production_department__site').in_bulk(
            unit_ids - set(self.units)))
        self.batch_ids |= missing

    # ---- the lots a withdrawal holds (rule 1) -------------------------------------------------------
    def _cleaner(self, batch_id):
        return self.batches[batch_id].species.is_cleaner_fish

    def _walk(self, withdrawal, seeds):
        """[(unit id, batch id, since, left, via)] of the lots `withdrawal` holds, its batch exposed on `seeds`
        ({unit id: [day]}). The ledger's days are walked from the first of them while the withdrawal is in force and
        a lot is held or still to be exposed; on each day, to a fixpoint (the order within a day is not read): the
        exposed fish (A), the lots fish of a held lot were moved into (B), every batch in a unit a held lot is in
        (C; never from a cleaner-fish lot: the owner's decision 6). A lot whose last fish left by the end of the day ends
        with that day. `via`: (unit id, batch id, whether that lot was itself held only by sharing) of the held lot a
        shared lot met; None along the exposed fish's own path."""
        presence, batch_id, end = self.presence, withdrawal.batch_id, withdrawal.ends
        exposed_on = defaultdict(list)
        for unit_id, days in seeds.items():
            for day in days:
                exposed_on[day].append(unit_id)
        first, last = min(exposed_on), max(exposed_on)
        held, found = {}, []
        for day in sorted({*exposed_on, *(each for each in presence.days if each > first)}):
            if (end is not None and day >= end) or (day > last and not held):
                break
            for unit_id in exposed_on.get(day, ()):
                held.setdefault((unit_id, batch_id), (day, None))
            grown = True
            while grown:
                grown = False
                for source, target, moved in presence.moves.get(day, ()):
                    if (source, moved) in held and (target, moved) not in held:
                        held[(target, moved)] = (day, held[(source, moved)][1])
                        grown = True
                for unit_id, holder in list(held):
                    if self._cleaner(holder):
                        continue
                    for other in presence.batches.get(unit_id, ()):
                        if (unit_id, other) not in held and presence.during(unit_id, other, day):
                            held[(unit_id, other)] = (day, (unit_id, holder, held[(unit_id, holder)][1] is not None))
                            grown = True
            for lot in [lot for lot in held if presence.count_at_end(*lot, day) <= 0]:
                since, via = held.pop(lot)
                found.append((*lot, since, day, via))
        return found + [(*lot, since, None, via) for lot, (since, via) in held.items()]

    def lots(self):
        """[Hold]: every lot every withdrawal of this reader holds or held, ended ones too."""
        if self._lots is None:
            self._lots, self._by_unit, self._by_lot = [], defaultdict(list), defaultdict(list)
            for index, withdrawal in enumerate(self.withdrawals()):
                seeds = self._seeds[index]
                codes = tuple(sorted(self.units[unit_id].code for unit_id in seeds if unit_id in self.units))
                for unit_id, batch_id, since, left, via in self._walk(withdrawal, seeds):
                    hold = Hold(withdrawal, unit_id, batch_id, since, left,
                                self.units[via[0]].code if via else '', self.batches[via[1]].code if via else '',
                                codes, frozenset(seeds), bool(via and via[2]), self.batches[withdrawal.batch_id].code)
                    self._lots.append(hold)
                    self._by_unit[unit_id].append(hold)
                    self._by_lot[(unit_id, batch_id)].append(hold)
        return self._lots

    def of_lot(self, unit_id, batch_id, day):
        """The Holds of the fish of the batch in the unit on `day`."""
        self.lots()
        return [hold for hold in self._by_lot.get((unit_id, batch_id), ()) if hold.on(day)]

    def of_unit(self, unit_id, day):
        """[Hold]: the unit's own withdrawal line on `day`, what the harvest check reads. The unit is held as a whole
        (rule 1 C), so each cause is said once per batch (its latest end), and not again for the fish that are held only
        because they are beside the exposed fish of that cause while those are in the unit: they are named by the
        exposed batch's line, which holds every fish in the unit. A cleaner-fish line never stands for production fish
        (farm.handling.check.held_apart reads the line's batch)."""
        self.lots()
        latest = {}
        for hold in self._by_unit.get(unit_id, ()):
            if hold.on(day):
                key = (source_key(hold.source), hold.batch_id)
                if key not in latest or _rank(hold) > _rank(latest[key]):
                    latest[key] = hold
        kept = []
        for (cause, _batch), hold in latest.items():
            covering = [own for (theirs, _own), own in latest.items()
                        if theirs == cause and own.own and not self._cleaner(own.batch_id)]
            if hold.own or not any(not _later(hold.until, own.until) for own in covering):
                kept.append(hold)
        order = {id(withdrawal): index for index, withdrawal in enumerate(self.withdrawals())}
        return sorted(kept, key=lambda hold: (str(hold.batch_id), order[id(hold.withdrawal)]))

    def current(self, hold):
        """For a reader whose `today` is not one site's own (a write guard, what blocks a deletion): whether the lot
        is held now. Its fish are there (or left today at the earliest) and the withdrawal holds now (`holds`)."""
        return (hold.left is None or hold.left >= self.today) and self.holds(hold.withdrawal)


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


@sealing.reads_as_system('the medicine withdrawal')
def _reached(unit_ids=(), species=None):
    """(the batches ever in `unit_ids` or of `species`, the farm's earliest today among the units they were in: the
    longest held; `reach`)."""
    batch_ids = set(reach({None: set(unit_ids)})[None][0]) if unit_ids else set()
    if species is not None:
        batch_ids.update(Batch.all_objects.filter(species=species).values_list('pk', flat=True))
    return earliest_days({None: batch_ids})[None]


def held_reached(unit_ids=(), species=None):
    """Why a unit, a loop (the units in it) or a species is not deleted or restored now: the batches with fish a
    withdrawal holds today that deleting or restoring it would move. A lot is moved by `unit_ids` when
    - it is in one of them (the fish of a deleted unit show no withdrawal at all);
    - its withdrawal's batch was exposed in one of them (the treatment's unit, the medicated feeding's unit): without
      the unit the course reached nobody;
    - its withdrawal is in degree-days and its batch was in one of them since the course's last day: the unit's water
      counts for the end (rule 3: the lowest among every unit the batch is in, also one that was never treated; the
      vet's open question, rule 1), so its samples and its loop's move it;
    and by `species` when the lot's batch or its withdrawal's batch is of it (the species' withdrawal rows, its
    assumed temperature). A unit that was never treated, holds no held fish and whose water counts for no
    degree-days is NOT blocked by a hold elsewhere on a batch that was once in it (flow fault S-03, RULES case 9).
    [] when nothing held is moved."""
    batch_ids, today = _reached(unit_ids, species)
    if not batch_ids:
        return []
    unit_ids, reader = set(unit_ids), Reader(batch_ids, today)

    def of_species(batch_id):
        return species is not None and reader.batches[batch_id].species_id == species.pk

    def water_counts(held):
        if held.rule is None or held.rule.degree_days is None:
            return False
        return any(reader.presence.during_between(unit_id, held.batch_id, held.treatment.end_date + DAY, date.max)
                   for unit_id in unit_ids)

    moved = {hold.batch_id for hold in reader.lots() if reader.current(hold) and (
        hold.unit_id in unit_ids or unit_ids & hold.exposed_in or water_counts(hold.withdrawal)
        or of_species(hold.batch_id) or of_species(hold.withdrawal.batch_id))}
    codes = sorted(reader.batches[batch_id].code for batch_id in moved)
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
        after = snapshot(batch_ids | before.scope, today, before.since)
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
    """{unit id: [Hold]} of the lots in each unit on `day` (default each unit's today) that a withdrawal holds then:
    the unit's own withdrawal line (`Reader.of_unit`), and what the harvest check reads. One reader per site's day
    (`site_days`), asked that day itself; the same number of queries for one unit as for fifty."""
    found, spans = {}, None
    for today, members in site_days(units).items():
        spans = stock_read.spans() if spans is None else spans
        on = day or today
        batch_ids = stock_read.in_units(spans, [unit.pk for unit in members], on)
        if not batch_ids:
            continue
        reader = Reader(batch_ids, today, spans, first=min(on, today), last=on)
        for unit in members:
            holds = reader.of_unit(unit.pk, on)
            if holds:
                found[unit.pk] = holds
    return found


@dataclass(frozen=True)
class Reached:
    """Fish a treatment reached or holds, as the Treatments list shows them: a batch, read on today of the site its
    held fish are on now."""
    batch: Batch
    withdrawal: object              # the Hold (or the Withdrawal, for fish that are nowhere any more) with the latest
                                    # end; None: the treatment has no medicine, or is voided
    held: bool                      # a lot of the batch is held by the treatment on `today`
    today: object                   # today on the site these fish are on
    units: tuple = ()               # the codes of the units of this part, when the batch is on sites of different days
    shared: bool = False            # not exposed itself: held because it shared a unit with held fish
    where: tuple = ()               # the codes of the units its lots under this treatment's withdrawal are in now


def of_treatments(treatments):
    """{treatment id: [Reached]} for the Treatments list (the treatments' units prefetched): each batch with fish a
    treatment reached, and each batch its withdrawal holds through a shared unit (rule 1 C), with the units those
    lots are in now and the withdrawal on them, read as the unit's own line reads it (`of_units`): on today of the
    site the fish are on now, by the same reader, asked that same day. So the list, "Under withdrawal today", the day
    counts and the unit's line are one answer. A batch whose held fish are on sites of different days is shown once
    per day (`units`: that part's; `where` names the units of every part, always). A batch the treatment reached whose exposed fish are nowhere any more (harvested out) is shown once,
    without a unit, not held, with the withdrawal the course put on it, read on the day of the units the course was
    given in. One reader per site's day."""
    found = {treatment.pk: [] for treatment in treatments}
    given = {treatment.pk: {unit.pk for unit in treatment.units.all()} for treatment in treatments}
    every = {unit_id for unit_ids in given.values() for unit_id in unit_ids}
    spans = stock_read.spans() if every else {}
    batch_ids = set()
    for treatment in treatments:
        batch_ids |= stock_read.between(spans, given[treatment.pk], treatment.start_date, treatment.end_date)
    if not batch_ids:
        return found
    # The days of every site with fish: the fish a course holds can be on any of them.
    units = Tank.all_objects.select_related('production_department__site').in_bulk({unit_id for unit_id, _b in spans}
                                                                                   | every)
    today_of = {pk: local_today(unit) for pk, unit in units.items()}
    readers = {today: Reader(batch_ids, today, spans, also=treatments) for today in sorted(set(today_of.values()))}
    for treatment in treatments:
        live = bool(treatment.medicine_id) and not treatment.is_deleted
        gone = earliest_today(units[unit_id] for unit_id in given[treatment.pk] if unit_id in units)
        rows, exposed, listed = [], {}, set()
        for today, reader in readers.items():
            for batch_id in reader.treated(treatment):
                exposed.setdefault(batch_id, reader)
            parts = defaultdict(list)
            for hold in reader.lots() if live else ():
                if (hold.treatment is not None and hold.treatment.pk == treatment.pk
                        and today_of.get(hold.unit_id) == today and hold.there(today)
                        and reader.presence.during(hold.unit_id, hold.batch_id, today)):
                    parts[hold.batch_id].append(hold)
            for batch_id, holds in parts.items():
                listed.add(batch_id)
                rows.append(Reached(reader.batches[batch_id], max(holds, key=_rank),
                                    any(hold.on(today) for hold in holds), today,
                                    shared=all(hold.shared for hold in holds),
                                    where=tuple(sorted({units[hold.unit_id].code for hold in holds}))))
        several = {batch.pk for batch in (row.batch for row in rows)
                   if len({row.today for row in rows if row.batch.pk == batch.pk}) > 1}
        rows = [replace(row, units=row.where) if row.batch.pk in several else row for row in rows]
        for batch_id, reader in exposed.items():
            if batch_id not in listed:
                reader = readers.get(gone, reader)
                rows.append(Reached(reader.batches[batch_id], reader.of_treatment(treatment, batch_id) if live else None,
                                    False, reader.today))
        found[treatment.pk] = sorted(rows, key=lambda each: (each.batch.code, each.units))
    return found


# ---- harvests (and live deliveries) already recorded inside a withdrawal (audit F-195) ---------------------
@dataclass(frozen=True)
class HarvestInside:
    """A harvest recorded on a day a withdrawal holds fish of its unit: its own batch, or a batch that shared the unit
    that day (`held`; a net cannot separate the batches of a unit, flow fault S-02): fish that may have gone to food
    medicated. It arises
    when the withdrawal is entered or grows after the harvest (a backdated treatment, a longer course, a corrected
    temperature, a medicine's withdrawal changed); a harvest made while the withdrawal was known is warned of then
    (farm/handling/check.py). As a warning of a treatment's dialog it is acknowledged like the handling warnings
    (`warning`, `key`, `message`, and what the acknowledgement keeps: `operation_id`, `until`, `approximate`,
    `reason`, and `batch`: the batch that is held, as the harvest's own acknowledgement names it).

    **A live delivery is a harvest here** (the owner's decision 13 of 19.11.2026): its fish left the farm alive and may
    be eaten, so a delivery a later write puts inside a withdrawal is found, asked, stored and logged exactly as a
    harvest is, by this same class (`line` is then the delivery's line; check.WITHDRAWAL_LINES says which lines are
    such); only its words differ (`delivery`: "Live delivery of … to <destination> lies inside this withdrawal (the fish
    may leave the farm from …)"), and its acknowledgement row is `delivered`, naming the delivery."""
    line: object                          # the harvest's (the delivery's) StockMovement: its operation, unit, batch, fish
    withdrawal: Withdrawal
    held: object = None                   # the Batch the withdrawal is of; None: read as the harvest's own
    hold: Hold = None                     # the lot of the harvested fish the withdrawal holds, with how it came to

    @property
    def delivery(self):
        """Whether the fish left alive (a live delivery), not harvested."""
        return self.line.kind == MovementKind.DELIVERY

    @property
    def warning(self):
        return WithdrawalWarning.DELIVERED if self.delivery else WithdrawalWarning.HARVESTED

    @property
    def operation_id(self):
        return self.line.operation_id

    @property
    def harvest(self):
        """The operation the acknowledgement names (its `harvest`): the harvest, or the live delivery."""
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
        """The slaughter facility a harvest went to (None for a live delivery: `destination`)."""
        record = getattr(self.line.operation, 'harvest_record', None)
        return record.facility if record is not None else None

    @property
    def destination(self):
        """Whom a live delivery went to ('' for a harvest, or a delivery without its record)."""
        record = getattr(self.line.operation, 'delivery_record', None) if self.delivery else None
        return record.destination if record is not None else ''

    @property
    def taken_to(self):
        """Where the fish went, as the messages name it: the facility, or the delivery's receiver."""
        if self.delivery:
            return self.destination or _('an unknown receiver')
        return self.facility.name if self.facility is not None else _('an unknown facility')

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
        return (f'{self.warning}:{self.line.operation_id}:{self.line.batch_id}:{self.withdrawal.batch_id}:{self.until}:'
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
                  'facility': self.taken_to}
        if self.delivery:                   # a live delivery's end in its own words (F-1): not "harvest from"
            text = _('Live delivery of %(date)s from %(unit)s (%(batch)s, %(fish)s fish to %(facility)s) lies inside '
                     'this withdrawal (%(end)s): medicated fish sold alive may have been eaten.') % {
                **params, 'end': leave_from(self.until, self.approximate)}
        else:
            text = _('Harvest of %(date)s from %(unit)s (%(batch)s, %(fish)s fish to %(facility)s) lies inside this '
                     'withdrawal (%(end)s): medicated fish may have gone to food.') % {
                **params, 'end': harvest_from(self.until, self.approximate)}   # the one wording of a withdrawal's end
        if not self.own:
            text += ' ' + self.through()
        return text

    @property
    def chained(self):
        """Whether the fish harvested are held through a batch that was itself only held by sharing a unit (not the
        withdrawal's own batch): the withdrawal's batch need never have been in a unit with them."""
        return self.hold is not None and self.hold.chain and self.hold.via_batch != self.batch.code

    @property
    def beside(self):
        """Whether the withdrawal's own batch was in the harvested unit with the fish harvested (else they met it in
        another unit before, or met fish held with it: `chained`)."""
        return self.hold is None or (not self.chained and self.hold.via_unit in ('', self.line.unit.code))

    def through(self):
        """How a withdrawal of another batch came to hold the fish harvested (delivered alive: `delivery`)."""
        delivered = self.delivery
        if self.chained:
            text = (_('The withdrawal is of %(held)s: the fish delivered shared %(unit)s with %(with)s, which waits '
                      'with %(held)s, and the fish of one unit cannot be told apart.') if delivered else
                    _('The withdrawal is of %(held)s: the fish harvested shared %(unit)s with %(with)s, which waits '
                      'with %(held)s, and the fish of one unit cannot be told apart.'))
        elif self.beside:
            text = (_('The withdrawal is of %(held)s, which was in %(unit)s with the fish delivered: the fish of '
                      'one unit cannot be told apart.') if delivered else
                    _('The withdrawal is of %(held)s, which was in %(unit)s with the fish harvested: the fish of '
                      'one unit cannot be told apart.'))
            return text % {'held': self.batch.code, 'unit': self.line.unit.code}
        else:
            text = (_('The withdrawal is of %(held)s: the fish delivered shared %(unit)s with %(with)s before, and '
                      'the fish of one unit cannot be told apart.') if delivered else
                    _('The withdrawal is of %(held)s: the fish harvested shared %(unit)s with %(with)s before, and '
                      'the fish of one unit cannot be told apart.'))
        return text % {'held': self.batch.code, 'unit': self.hold.via_unit, 'with': self.hold.via_batch}

    def same_harvest(self):
        """Which harvest of which batch it is, whatever the withdrawal's end."""
        return self.line.operation_id, self.line.batch_id


@sealing.reads_as_system('the medicine withdrawal')
def _harvest_lines(batch_ids=None, since=None, unit_ids=()):
    """The live lines of the fish that left the farm and may be eaten: a harvest's and a live delivery's
    (check.WITHDRAWAL_LINES, the owner's decisions 12 and 13), of `batch_ids`, and of any batch out of `unit_ids`; from
    `since`; with what a finding names. THE one read of them every after-the-fact check goes through (the guard's
    snapshots, check_withdrawal), so a delivery is never compared otherwise than a harvest."""
    lines = StockMovement.objects.filter(kind__in=sorted(check.WITHDRAWAL_LINES.values()),
                                         operation__is_deleted=False).select_related(
        'operation__harvest_record__facility', 'operation__delivery_record', 'unit__production_department__site',
        'batch')
    if batch_ids is not None:
        lines = lines.filter(Q(batch_id__in=batch_ids) | Q(unit_id__in=unit_ids))
    if since is not None:
        lines = lines.filter(operation__date__gte=since)
    return list(lines.order_by('operation__date', 'unit__code', 'pk'))


def _inside(reader, lines):
    """THE rule: a harvest (a live delivery: the owner's decision 13, `_harvest_lines`) lies inside a withdrawal that
    holds the lot of the harvested fish (their batch in their
    unit) on the harvest's day (Hold.on: the lot is there, the day its last fish left too, and the withdrawal holds:
    from the treatment's first day, or the medicated feeding's, to the day before the fish may be harvested). The lots
    say which fish a withdrawal holds (rule 1): the exposed fish, where they were moved, and every batch that was in a
    unit with held fish (the fish of one unit go to food together, S-02; also fish that came in and left again that
    day, review F-03), also after they moved on. Production fish are never held by a lot of cleaner fish (the
    owner's decision 6), so a harvest is never inside a cleaner fish's withdrawal. `reader` has read the harvested batches."""
    found = []
    for line in lines:
        for hold in reader.of_lot(line.unit_id, line.batch_id, line.operation.date):
            found.append(HarvestInside(line, hold.withdrawal, reader.batches[hold.withdrawal.batch_id], hold))
    best = {}
    for each in found:                    # a withdrawal holds a lot once a day; a lot ended and begun again that day
        best.setdefault((each.line.pk, each.identity()), each)
    return sorted(best.values(), key=lambda each: (each.line.operation.date, each.line.unit.code, each.line.pk,
                                                   each.withdrawal.start, each.batch.code))


def harvests_inside():
    """Every live harvest and live delivery that lies inside a withdrawal that holds its fish, however it came to
    (check_withdrawal; `_harvest_lines`):
    one reader per farm-local today of the harvested units (sites in different time zones), over the harvested
    batches (the reader loads the batches they can have met)."""
    every = _harvest_lines()
    spans = stock_read.spans() if every else None
    by_today = defaultdict(list)
    for line in every:
        by_today[local_today(line.unit)].append(line)
    found = []
    for today, lines in sorted(by_today.items()):
        found += _inside(Reader({line.batch_id for line in lines}, today, spans,
                                first=min(line.operation.date for line in lines),
                                last=max(line.operation.date for line in lines)), lines)
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
    voided, a temperature corrected, a move of fish voided or dated before the course that reached them. Asked whether
    or not the new end is still ahead (cross-review 2, 4). The fish are a lot: a batch in a unit (`unit`)."""
    batch: object
    withdrawal: Withdrawal                # the one that held the fish longest before the write
    until_after: object = None            # the end after the write
    freed: bool = False                   # no withdrawal holds the fish today after the write
    unit: object = None                   # the unit the fish are in after the write

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
        return f'released:{self.batch.pk}:{self.unit.pk}:{self.until}:{after}:{self.approximate}:{self.reason}'

    def message(self):
        params = {'batch': self.batch.code, 'unit': self.unit.code, 'withdrawal': self.reason,
                  'until': shown_date(self.until) if self.until else _('an unknown end'),
                  'after': shown_date(self.until_after) if self.until_after else _('an unknown end')}
        if self.freed:
            return _('%(batch)s in %(unit)s is held today (%(withdrawal)s) and would no longer be held by a medicine '
                     'withdrawal after this change: the fish could go to food.') % params
        return _('%(batch)s in %(unit)s is held (%(withdrawal)s): after this change its withdrawal would end earlier, '
                 'the fish may go to food from %(after)s instead of %(until)s.') % params


@dataclass(frozen=True)
class Combined:
    """Fish that wait longer for the harvest after a stock operation, because it combines them with held fish: fish
    that were not held, and fish held to an earlier end than the hold they now share (the
    owner's decisions 7 and 8 of 16.11.2026: fish moved into a tank that already holds fish are one group with them,
    whoever is combined waits for the others' withdrawal, wherever those fish go; it is SAID at the move, and the move
    is allowed). Asked like every warning of the guard, by a tick; stored as a handling acknowledgement of the
    operation (the batch that now waits, the end, the withdrawal's source and this sentence) and logged critical. It
    is not a withdrawal gone past (no fish goes to food by it), so the second-person setting does not apply."""
    batch: object
    unit: object
    withdrawal: Hold                      # the Hold on the lot after the operation, with how it came to

    warning = 'combined'
    harvest = None

    @property
    def until(self):
        return self.withdrawal.until

    @property
    def approximate(self):
        return self.withdrawal.estimated

    @property
    def reason(self):
        return self.message()

    def key(self):
        # The batch by its code: a batch the operation itself stocks has a new id each time it is sent.
        return (f'combined:{self.batch.code}:{self.unit.pk}:{self.until}:{self.approximate}:'
                f'{source_key(self.withdrawal.source)}:{self.withdrawal.via_unit}:{self.withdrawal.via_batch}')

    def message(self):
        """Who the fish wait with: the held fish they are combined with and where; or, when the operation made them
        exposed themselves (fish moved or stocked into the treated unit dated on a course day, and where those fish
        went since: there is no other batch to name), the fish treated there. Never a sentence with an empty name
        (verification V-3)."""
        hold = self.withdrawal
        params = {'batch': self.batch.code, 'unit': self.unit.code, 'with': hold.via_batch,
                  'where': hold.via_unit, 'end': harvest_from(self.until, self.approximate),
                  'withdrawal': describe(hold.withdrawal), 'units': ', '.join(hold.treated_in)}
        if not hold.shared:
            if hold.feeding is not None:
                return _('%(batch)s in %(unit)s will wait for the harvest with the fish given medicated feed in '
                         '%(units)s, and the end of that withdrawal is not known. %(withdrawal)s') % params
            if self.until is None:
                return _('%(batch)s in %(unit)s will wait for the harvest with the fish treated in %(units)s, and the '
                         'end of that withdrawal is not known. %(withdrawal)s') % params
            return _('%(batch)s in %(unit)s will wait for the harvest with the fish treated in %(units)s: %(end)s. '
                     '%(withdrawal)s') % params
        if self.until is None:
            return _('%(batch)s in %(unit)s will wait for the harvest with %(with)s, the held fish it is combined with '
                     'in %(where)s, and the end of that withdrawal is not known. %(withdrawal)s') % params
        return _('%(batch)s in %(unit)s will wait for the harvest with %(with)s, the held fish it is combined with '
                 'in %(where)s: %(end)s. %(withdrawal)s') % params


@dataclass(frozen=True)
class HeldAgain:
    """Fish that are not held today and are held after a change of the rule of how long an end without a rule holds
    (rule 8; a longer ceiling: a course that had given up holds again, verification V-7). Asked like every warning of
    the guard, stored as a withdrawal acknowledgement (`held`) and logged critical. Nobody's fish go to food by it
    (the harvests it puts inside the withdrawal are asked about beside it), so the second-person setting does not
    apply to it alone."""
    batch: object
    unit: object
    withdrawal: Hold                      # the Hold on the lot after the change, with how it came to

    warning = WithdrawalWarning.HELD
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
        return (f'held:{self.batch.pk}:{self.unit.pk}:{self.until}:{self.approximate}:'
                f'{source_key(self.withdrawal.source)}:{self.reason}')

    def message(self):
        return _('%(batch)s in %(unit)s is not held today and would be held again by a medicine withdrawal after '
                 'this change, and the end of that withdrawal is not known. %(withdrawal)s') % {
            'batch': self.batch.code, 'unit': self.unit.code, 'withdrawal': self.reason}


@dataclass(frozen=True)
class Snapshot:
    """The withdrawals of some fish as the stored facts give them now: the harvests inside one (by identity), the
    withdrawals that hold each lot today (`held`: {(unit id, batch id): [Hold]}), the lots with fish now (`stocked`),
    the moves of fish between units (`transfers`) and the batches read (`scope`: the batches asked and every batch
    their fish can have met)."""
    inside: dict
    held: dict
    scope: frozenset = frozenset()
    stocked: frozenset = frozenset()
    transfers: frozenset = frozenset()
    since: object = LIFE


def snapshot(batch_ids, today, since=LIFE, back=None):
    """The Snapshot of the fish `batch_ids` on `today`, read from `since` (default: the first day that can matter to
    them, Reader's LIFE, and `back` when the write reaches further back; the guard reads its second snapshot from the
    first one's day, so the two compare the same days)."""
    if not batch_ids:
        return Snapshot({}, {})
    reader = Reader(batch_ids, today, first=since, back=back)
    held = defaultdict(list)
    for hold in reader.lots():
        if reader.current(hold):          # held now, by the reader's rule for several clocks: the guards read it too
            held[(hold.unit_id, hold.batch_id)].append(hold)
    # The harvests and live deliveries of every batch read: a harvest of a batch that was never treated lies inside a
    # withdrawal when its
    # fish shared a unit with held fish (`_inside`).
    lines = _harvest_lines(reader.batch_ids, since=reader.first)
    stocked = frozenset(lot for lot, (_days, counts) in reader.presence.timelines.items() if counts[-1] > 0)
    return Snapshot({each.identity(): each for each in _inside(reader, lines)}, dict(held),
                    frozenset(reader.batch_ids), stocked, frozenset(reader.presence.transfers), reader.first)


def held_with(batch_ids, first=None, spans=None):
    """The batches the withdrawals of `batch_ids` hold, from the day `first` on (None: in their whole life): every
    batch with a lot under a withdrawal worked out for one of them (the exposed fish, where they were moved, the
    fish that shared a unit with them). What a write that can change those withdrawals locks beside its own fish
    (farm.stock.services.lock_fish). Read on the company's day: the ends decide only which withdrawals are over."""
    if not batch_ids:
        return set()
    batch_ids = set(batch_ids)
    reader = Reader(batch_ids, local_today(), spans, first=LIFE if first is None else first)
    return {hold.batch_id for hold in reader.lots() if hold.withdrawal.batch_id in batch_ids}


def _longest(withdrawals):
    return max(withdrawals, key=lambda each: (each.until is None, each.until or each.start))


@dataclass
class Change:
    """What a write did to the withdrawals of the fish it touched: the harvests and live deliveries it brought inside
    one, or whose withdrawal it made end later than before (`harvested`, HarvestInside: a delivery is asked as a harvest
    is, the owner's decision 13; an acknowledgement covers the end it was given for), and the
    held batches whose withdrawal it made end earlier or ended (`released`). Acknowledged through one box."""
    harvested: list = field(default_factory=list)
    released: list = field(default_factory=list)
    combined: list = field(default_factory=list)
    held_again: list = field(default_factory=list)

    @property
    def warnings(self):
        return self.harvested + self.released + self.combined + self.held_again

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


def change(before, after, exclude_operation=None, combining=False, holding=False):
    """The Change between two snapshots, `after` read over `before`'s batches at least (`guarded`). A harvest (a live
    delivery) the write itself records is left out: its own handling check asks about the withdrawal in force on its
    day.

    A harvest that neither is of a batch read before nor lies inside a withdrawal of one is not this write's: the write
    only joined its fish to the fish asked (a move into their unit), and what was true of it before stays true.

    Fish are RELEASED lot by lot (a batch in a unit, rule 1): a lot with fish after the write whose fish were held
    before it and are not held after it, or to an earlier end. "Its fish before the write" are the lot's own and those
    the write itself moved into it: the lot a move the write records took them out of, the lot a move the write voids
    had put them in. So fish taken out of a course's reach by a move dated before it, or put back by a void, are asked
    about where they are now; a move of fish that were never held asks nothing."""
    harvested = [found for key, found in after.inside.items() if found.operation_id != exclude_operation
                 and (not before.scope or found.line.batch_id in before.scope
                      or found.withdrawal.batch_id in before.scope)
                 and (key not in before.inside or _later(found.until, before.inside[key].until))]
    came_from = defaultdict(set)
    for _operation, _pair, source, target, batch_id in after.transfers - before.transfers:
        came_from[(target, batch_id)].add((source, batch_id))
    for _operation, _pair, source, target, batch_id in before.transfers - after.transfers:
        came_from[(source, batch_id)].add((target, batch_id))
    found = []
    for lot in sorted({*before.held, *came_from}, key=str):
        prior = [hold for each in (lot, *sorted(came_from.get(lot, ()), key=str)) for hold in before.held.get(each, ())]
        if not prior or lot not in after.stocked:
            continue
        if lot not in after.held:
            found.append((lot, _longest(prior), None, True))
        elif _later(_end(prior), _end(after.held[lot])):
            found.append((lot, _longest(prior), _end(after.held[lot]), False))
    batches = Batch.all_objects.in_bulk({batch_id for (_unit, batch_id), *_rest in found})
    units = Tank.all_objects.in_bulk({unit_id for (unit_id, _batch), *_rest in found})
    released = [Released(batches[batch_id], old, until_after, freed, units[unit_id])
                for (unit_id, batch_id), old, until_after, freed in found]
    return Change(harvested, released, _combined(before, after, came_from) if combining else [],
                  _held_again(before, after) if holding else [])


def _held_again(before, after):
    """[HeldAgain]: the lots with fish that no withdrawal held before a change of the ceiling and one holds after it.
    One per lot, with the withdrawal that holds it longest."""
    found = [(lot, max(after.held[lot], key=_rank)) for lot in sorted(after.held, key=str)
             if lot in after.stocked and lot not in before.held]
    batches = Batch.all_objects.in_bulk({batch_id for (_unit, batch_id), _hold in found})
    units = Tank.all_objects.in_bulk({unit_id for (unit_id, _batch), _hold in found})
    return [HeldAgain(batches[batch_id], units[unit_id], hold) for (unit_id, batch_id), hold in found]


def _cause(hold):
    """Which withdrawal a Hold is of: its cause (the course, the medicated feeding) and the batch it was worked out
    for."""
    return source_key(hold.source), hold.withdrawal.batch_id


def _combined(before, after, came_from):
    """[Combined]: the lots with fish after a stock operation that now wait for a withdrawal their fish did not wait
    for before it, and wait LONGER by it. "Their fish before" are the lot's own and those of a lot the operation moved
    fish out of into it. So:
    - fish no withdrawal held (held fish were moved in beside them, they were moved in beside held fish, or they went
      on from a unit that now counts as shared: a move dated in the past);
    - fish that were held already, to an EARLIER end, and are combined with a longer or an unknown hold, in either
      direction (verification V-1: B waited until tomorrow, and after the move for two months, and nothing was said).
    Held fish moved alone, fish combined with a hold that ends no later than their own, and an end that only moved
    (the same withdrawal, other water) are not said. One per lot, with the new withdrawal that holds it longest.

    The fish of a lot after the operation are GROUPS, each asked about on its own, whatever their batch (verification
    of 27e554e, W-1): the lot's own fish (when it had fish before the operation, or when none came into it by a move:
    a stocking, fish that went on from a unit that now counts as shared) and the fish of each lot the operation moved
    fish out of into it. A lot is a batch in a unit, so held fish moved in beside fish of their OWN batch that are not
    held (a split before the course merged back, decision 7's sibling tank moved into its held part) used to hide them
    behind the arriving fish's cause: the same batch is now asked exactly as another batch is (decision 8)."""
    found = []
    for lot in sorted(after.held, key=str):
        if lot not in after.stocked:
            continue
        arrived = sorted(came_from.get(lot, ()), key=str)
        groups = ([lot] if lot in before.stocked or not arrived else []) + arrived
        waiting = []
        for group in groups:
            prior = list(before.held.get(group, ()))
            known = {_cause(hold) for hold in prior}
            new = [hold for hold in after.held[lot] if _cause(hold) not in known]
            if not new:
                continue
            longest = max(new, key=_rank)
            if prior and not _later(longest.until, _end(prior)):
                continue
            waiting.append(longest)
        if waiting:
            found.append((lot, max(waiting, key=_rank)))
    batches = Batch.all_objects.in_bulk({batch_id for (_unit, batch_id), _hold in found})
    units = Tank.all_objects.in_bulk({unit_id for (unit_id, _batch), _hold in found})
    return [Combined(batches[batch_id], units[unit_id], hold) for (unit_id, batch_id), hold in found]


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


def guarded(user, batch_ids, today, write, *, seen=None, record_of=None, exclude_operation=None, combining=False,
            back=None, holding=False):
    """THE one function every write that can create, grow, shorten or end a medicine withdrawal goes through (a
    treatment, its last day and its void, a medicated feeding and its void, a medicine's withdrawal rows, a water
    sample and its void, a stock operation and its void, a feed's type, a species' assumed temperature, a sampling
    point's active flag, kind and owner); the data layer refuses those writes anywhere else (farm/withdrawal_gate.py).

    Inside the caller's transaction, after its locks, it works out the withdrawals of `batch_ids` (the fish the write can
    touch, on the farm's `today`) before the write, makes the write ONCE in a savepoint and works them out again from
    what it left. When the write brings a recorded harvest or live delivery inside a withdrawal (or makes one it is
    inside end later), or
    makes the withdrawal of fish held today end earlier, the person must have gone on past exactly this impact: `seen`
    is the fingerprint the write's own form carried (its box `withdrawal_ack`). Otherwise the savepoint is rolled back
    and the write refused (WithdrawalChanged, which carries what was found for the dialog). A `seen` that is not this
    impact's fingerprint (the impact changed since it was shown) is refused the same way. Going on stores a
    WithdrawalAcknowledgement per warning, naming the record `record_of(result)` (default: the result), and a critical
    log entry on it with what was acknowledged; the second-person hook is asked as for every withdrawal warning.
    `exclude_operation(result)`: a harvest the write itself records (its own handling check asks). `combining`: the
    write is a stock operation, which also asks when it combines held fish with fish that are not held, in either
    direction (`Combined`; the owner's decision 8: it is said at the move, and the move is allowed). `back`: the first
    day the write can change a withdrawal from, when it is not a dated record the correction window bounds (reference
    data: `guarded_units`, `guarded_ceiling`); both snapshots read from it. `holding`: the write is a change of the
    ceiling, which also asks when it holds fish again (`HeldAgain`). Returns what `write()` returned."""
    batch_ids = set(batch_ids)
    seen = seen or ''
    before = snapshot(batch_ids, today, back=back)
    with gate.opened('withdrawal guard'), transaction.atomic():
        result = write()
        excluded = exclude_operation(result) if exclude_operation else None
        # Read again over everything read before (a write that parts fish, a move voided, must not lose them from
        # the comparison) and whatever the write joined to it.
        found = change(before, snapshot(batch_ids | before.scope, today, before.since), excluded,
                       combining=combining, holding=holding)
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
            harvest_id=warning.harvest,                 # the harvest or live delivery inside; None for the others
            source=source_key(warning.withdrawal.source), until=warning.until, approximate=warning.approximate, reason=warning.reason[:500])
        for warning in [*found.harvested, *found.released, *found.held_again]])
    # Fish a stock operation combined with held fish: the operation's own handling acknowledgement, one per lot.
    HandlingAcknowledgement.objects.bulk_create([
        HandlingAcknowledgement(
            operation=record, warning=AcknowledgedWarning.WITHDRAWAL, batch=warning.batch,
            withdrawal_until=warning.until, withdrawal_approximate=warning.approximate,
            withdrawal_reason=warning.reason[:500], withdrawal_source=source_key(warning.withdrawal.source))
        for warning in found.combined])
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
    """Why a withdrawal holds the fish and until when, in the active language. Of a Hold (the fish of a batch in a
    unit), first how these fish came to be held when they were not exposed themselves ("These fish shared T-03 with
    B-2026-001 (treated in T-01)."), or where they were treated when that is not the unit they are in now."""
    if isinstance(withdrawal, Hold):
        return ' '.join(part for part in (_held_how(withdrawal), describe(withdrawal.withdrawal)) if part)
    if withdrawal.feeding is not None:
        record = withdrawal.feeding
        return _('Medicated feed %(feed)s was fed in %(unit)s on %(date)s and no in-feed treatment covers that '
                 'day: the withdrawal end is unknown. Record the treatment under Health › Treatments.') % {
            'feed': record.feed, 'unit': _shown(Tank, [record.unit.code])[record.unit.code],
            'date': shown_date(record.date)}
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
        # The other record that gives it an end (rule 5); with past days uncounted, the sentence about them says it.
        if withdrawal.assumed_temperature is None and not withdrawal.days_without_temperature:
            text += ' ' + _('Or set the assumed water temperature of %(species)s in Reference data › Species: the '
                            'days without a measured temperature then count.') % {
                'species': withdrawal.species.common_name}
    elif withdrawal.projected_at_assumed:
        text += ' ' + projected_sentence(withdrawal.assumed_temperature)
    elif withdrawal.estimated:
        text += ' ' + _('Projected at the mean water temperature of the last days measured.')
    if withdrawal.days_without_temperature:
        text += ' ' + missing_sentence(withdrawal.days_without_temperature, withdrawal.assumed_temperature)
    return text


def _shown(model, codes):
    """{code: what to print}: a unit's or a batch's code when whoever is looking may see it, else "a restricted unit"
    or "a restricted batch" (core.sealing: a hold caused through a sealed tank names neither the tank nor its fish)."""
    codes = [code for code in codes if code]
    seen = set(model.all_objects.filter(code__in=codes).values_list('code', flat=True))
    other = _('a restricted unit') if model is Tank else _('a restricted batch')
    return {code: code if code in seen else other for code in codes}


def _held_how(hold):
    """How the fish of a Hold came to be held, when it is not said by the withdrawal itself: '' for the exposed fish
    in a unit they were exposed in. A unit or a batch the person may not see is not named (`_shown`)."""
    units_shown = _shown(Tank, [*hold.treated_in, hold.via_unit])
    batches_shown = _shown(Batch, [hold.via_batch, hold.of_batch])
    units = ', '.join(dict.fromkeys(units_shown[code] for code in hold.treated_in))
    if not hold.shared:
        if hold.unit_id in hold.exposed_in or not units:
            return ''
        if hold.feeding is not None:
            return _('These fish were given the medicated feed in %(units)s.') % {'units': units}
        return _('These fish were treated in %(units)s.') % {'units': units}
    if hold.feeding is not None:
        how = _('given medicated feed in %(units)s') % {'units': units}
    else:
        how = _('treated in %(units)s') % {'units': units}
    if hold.chain and hold.via_batch != hold.of_batch:
        # The batch they shared the unit with was never treated: it waits with the treated batch, the source.
        return _('These fish shared %(unit)s with %(batch)s, which waits with %(source)s (%(how)s).') % {
            'unit': units_shown.get(hold.via_unit, hold.via_unit), 'batch': batches_shown.get(hold.via_batch, hold.via_batch),
            'source': batches_shown.get(hold.of_batch, hold.of_batch), 'how': how}
    return _('These fish shared %(unit)s with %(batch)s (%(how)s).') % {
        'unit': units_shown.get(hold.via_unit, hold.via_unit), 'batch': batches_shown.get(hold.via_batch, hold.via_batch),
        'how': how}


def provider(units, day):
    """The health module's answer to farm.handling.withdrawal.blocks_of: {unit id: [block]}, a block per line of the
    unit's withdrawal on `day` (None: the unit's own today; `of_units`): the batch held there, the end, and why, which
    says by name when the fish are held because they shared a unit; the units without one are left out."""
    withdrawals = of_units(units, day)
    batches = Batch.all_objects.select_related('species').in_bulk(
        {withdrawal.batch_id for held in withdrawals.values() for withdrawal in held})
    return {unit_id: [WithdrawalBlock(batches[withdrawal.batch_id], withdrawal.until, withdrawal.estimated,
                                      describe(withdrawal), withdrawal.source) for withdrawal in held]
            for unit_id, held in withdrawals.items()}


def unresolved(today=None):
    """[(Batch, Withdrawal)]: the unresolved old courses (rule 8): every live course with a medicine, and every
    medicated feeding no in-feed course covers, whose withdrawal for a batch it reached has no rule to end by and has
    given up by `today` (default the company's). They hold nobody any more; the Treatments page and check_withdrawal
    list them with what gives each an end (`unresolved_text`). A degree-day withdrawal is never one of them: it holds
    until it can be counted (decision 11)."""
    today = today or local_today()
    # A last day before this has given up: last + days + 1 <= today.
    return without_a_rule(today, today - unknown_withdrawal_days() * DAY)


def without_a_rule(today, before=None):
    """[(Batch, Withdrawal)]: every live course with a medicine that has no withdrawal row for the species of a batch
    it reached, and every medicated feeding no in-feed course covers, with the batch: the withdrawals whose end is
    unknown for want of a rule, which the ceiling of rule 8 bounds. `before`: only those whose last day is before it
    (None: of any age). Only the batches of a species without a row of the medicine are read."""
    days = unknown_withdrawal_days()
    spans = stock_read.spans()
    old = {} if before is None else {'end_date__lt': before}
    treatments = list(Treatment.objects.filter(medicine__isnull=False, **old)
                      .select_related('medicine').prefetch_related('units').order_by('start_date', 'pk'))
    rows = defaultdict(list)
    for row in MedicineWithdrawal.objects.filter(medicine__in={each.medicine_id for each in treatments}):
        rows[row.medicine_id].append(row)
    reached = {each.pk: stock_read.between(spans, [unit.pk for unit in each.units.all()], each.start_date,
                                           each.end_date) for each in treatments}
    batches = Batch.all_objects.select_related('species').in_bulk({pk for ids in reached.values() for pk in ids})

    wanted = {each.pk: {pk for pk in reached[each.pk]
                        if rule_for(rows[each.medicine_id], batches[pk].species_id) is None} for each in treatments}
    listed = [each for each in treatments if wanted[each.pk]]
    found = []
    if listed:
        reader = Reader({pk for each in listed for pk in wanted[each.pk]}, today, spans, also=listed)
        for treatment in listed:
            for batch_id in sorted(wanted[treatment.pk] & reader.treated(treatment), key=str):
                found.append((batches[batch_id], reader.of_treatment(treatment, batch_id)))
    in_feed = list(Treatment.objects.filter(medicine__isnull=False, method=TreatmentMethod.IN_FEED)
                   .prefetch_related('units'))
    old = {} if before is None else {'date__lt': before}
    records = [record for record in FeedingRecord.objects.filter(feed__feed_type=FeedType.MEDICATED, **old)
               .select_related('feed', 'unit') if not any(covers(treatment, record) for treatment in in_feed)]
    if records:
        parts = feeding_read.split_of(records)
        fed = Batch.all_objects.select_related('species').in_bulk({pk for each in parts.values() for pk in each})
        for record in sorted(records, key=lambda each: (each.date, each.pk)):
            for batch_id in sorted(parts.get(record.pk, ()), key=str):
                found.append((fed[batch_id], Withdrawal(batch_id, None, True, feeding=record,
                                                        gives_up=record.date + (days + 1) * DAY)))
    return found


def unresolved_text(batch, held):
    """An unresolved old course as the Treatments page and check_withdrawal say it: the batch, the course and why its
    end is unknown, which says what to enter (`describe`)."""
    return f'{batch.code}: {describe(held)}'


def guarded_ceiling(user, write, seen=None):
    """A change of the platform owner's setting of how long an end without a rule holds fish (rule 8): a change of a
    rule, through the guard. Made shorter, it frees fish held today: asked. Made longer, it holds fish again that had
    been let go, and brings the harvests recorded since they were let go inside the withdrawal: asked too
    (verification V-7), each stored and logged as critical.

    The fish asked of are every batch such a withdrawal can hold at the longest setting there is (the new value is
    not known before the write): the courses and feedings without a rule of any age (`without_a_rule`), walked with
    that ceiling from the oldest of them. Those batches are locked first, as every write locks them, and both
    snapshots read from that oldest day, not from the correction window's (a setting is not a dated record)."""
    from core.models import UNKNOWN_WITHDRAWAL_DAYS
    from farm.stock.services import locked
    today = local_today()
    with transaction.atomic():
        with sealing.system('the medicine withdrawal'):        # a guard weighs every course, whoever asks
            known = [held for _batch, held in without_a_rule(today)]
        if not known:
            return guarded(user, set(), today, write, seen=seen)
        back = min(held.start for held in known)
        reader = Reader({held.batch_id for held in known}, today, first=back, ceiling=UNKNOWN_WITHDRAWAL_DAYS[1])
        batch_ids = {hold.batch_id for hold in reader.lots() if hold.rule is None}
        locked(Batch, batch_ids)
        return guarded(user, batch_ids, today, write, seen=seen, back=back, holding=True)


def guarded_units(user, unit_ids, first, write, seen=None):
    """A write about reference data the withdrawals of the fish in `unit_ids` (from the day `first` on; None: every fish they ever held) are worked out
    from (a feed's type, a species' assumed temperature, a sampling point): those fish are locked as a stock operation
    locks them, and the write goes through the guard. Such a record is not dated: the guard reads from the day it
    reaches those fish (`first`; None: the day the first of them came into a unit), however long ago, so that every
    recorded harvest the write puts inside a withdrawal is asked about (verification V-6)."""
    from farm.stock.services import lock_fish
    units, batch_ids = lock_fish(set(unit_ids), first) if unit_ids else ({}, set())
    today = earliest_today(units.values())
    if first is None and batch_ids:
        first = min(began for (_unit, batch_id), (began, _ended) in stock_read.spans().items() if batch_id in batch_ids)
    return guarded(user, batch_ids, today, write, seen=seen, back=first)

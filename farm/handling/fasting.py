"""Fasting before handling: which rule applies, how long the fish have been without feed, and when feeding must stop
for a planned harvest or transport.

The rule (HandlingRule, Setup › Reference data › Handling rules): for a kind of handling, the species' row, else the
row for every species, else none ("not checked", never a default). A grading moves the fish too, so it takes the longer
of its own rule and the transport rule (owner decision).

What a rule asks (`Requirement`): hours (the one hours column; the form enters days too, 5 days is 120 hours), and for a
harvest **purging** in degree-days: the fish are held without feed, in clean water, so that any off-flavour clears. A
rule has the one or the other or both, and each that is set must be reached: the later decides.

How long the fish have fasted (`fasted`), never overstated (owner rule):
- **hours** from the fish's last feeding (farm.feeding.read.last_fed_at; a record without a time counts from the end
  of its day) to the start of the handling's day on the site's clock, since an operation has a date and no time. A
  feeding on the day itself gives 0 hours;
- **degree-days** are the batch's daily mean water temperatures of the **full days after the day of the last feeding
  up to the day before the handling**: the days of the feeding and of the handling are not counted. The days and their
  sum are farm/water/degree_days.py's one walk (`BatchWater.walk`), the one the medicine withdrawal adds up (the
  lowest of a day's closed probe days and water samples; else for a past day the species' assumed temperature, capped;
  else 0 °C; a mean of 0 °C or below adds nothing; a probe day not closed yet is projected); the warning says how many
  days came from each source.

When feeding must stop for a handling on day D (`start_of_fast`, **the one function** the meal board, the plan rows and
the earliest harvest date ask): the fast starts at the later of the two starts the rule asks for, counted back from D.
By hours it is the start of D's day less the hours; by degree-days, the day s such that the full days s to D − 1 add up
to the rule's degree-days (the same walk, backward from D − 1: a day not over or still to come at the mean of the
batch's last 7 measured days, else the species' assumed temperature; with none, the degree-days are unknown and the
hours rule alone applies, and it is said). Every day from the day the fast starts on to D is a fasting day in full, for
the whole unit (two batches in a unit cannot be fed apart).

**The days looked at.** No horizon is a constant. A purge in degree-days is looked for back to the batch's first day
on the farm (its presence): a fast the water has not reached since the fish came starts on that day and says "not
reached since the fish came", never "complete". The last feeding is looked for as far back as the rule needs
(`fed_since`): for a rule that asks degree-days, without a bound (fish not fed for a month in cold water have not
purged); for a rule in hours alone, LOOKBACK_DAYS back, one day more than the longest rule allowed in hours
(farm.models.handling.MAX_FASTING_HOURS, 720 h), so fish not fed in that time have fasted long enough for it. The day
a fast is complete is asked of the same walk, forward from the day after the feeding (`complete_on`): the one search
for "which day is it reached", for the earliest harvest date too (farm/handling/check.py).

A planned harvest or transport (HandlingPlanItem, planned or overdue) asks the unit to fast so. The meal board asks
`fasting_on`."""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal

from django.db.models import Q
from django.utils import formats
from django.utils.translation import gettext as _, ngettext

from core import versions
from farm.models import HandlingPlanItem, HandlingRule
from farm.models.handling import MAX_FASTING_HOURS, HandlingKind
from farm.models.site import zone_of
from farm.stock import read as stock_read
from farm.stock.dates import local_today, start_of
from farm.water.degree_days import BatchWater, accrual_text, degree_days_text, projected_sentence

# How far back the last feeding is looked for by a rule in hours alone: one day longer than the longest rule allowed
# (the module's docstring). A rule that asks degree-days looks back without a bound (`fed_since`).
LOOKBACK_DAYS = MAX_FASTING_HOURS // 24 + 1
DAY = timedelta(days=1)
HOUR = Decimal('0.1')

# The rules each kind of handling is checked against; the longest applies.
RULES_OF = {
    HandlingKind.HARVEST: (HandlingKind.HARVEST,),
    HandlingKind.TRANSPORT: (HandlingKind.TRANSPORT,),
    HandlingKind.GRADING: (HandlingKind.GRADING, HandlingKind.TRANSPORT),
    HandlingKind.TREATMENT: (HandlingKind.TREATMENT,),
}


def rule_for(kind, species):
    """The rule of one kind for a species: the species' own row, else the row for every species, else None."""
    every = Q(species__isnull=True)
    rules = {rule.species_id: rule for rule in HandlingRule.objects.filter(
        Q(kind=kind) & (every | Q(species=species) if species is not None else every))}
    return rules.get(species.pk if species is not None else None) or rules.get(None)


def rule_of(kind, species):
    """The rule a handling of `kind` is checked against for a species: the longest of RULES_OF[kind] (the first
    on a tie); None when no rule applies. Only a harvest's rule has degree-days, so the others compare hours."""
    found = [rule for rule in (rule_for(each, species) for each in RULES_OF[kind]) if rule is not None]
    return max(found, key=lambda rule: rule.min_fasting_hours or 0, default=None)


def shown_moment(moment, unit):
    """A moment on the unit's site clock as the language writes it: 2 Nov 2026, 18:00."""
    return formats.date_format(moment.astimezone(zone_of(unit.production_department.site)), 'DATETIME_FORMAT')


# ---- what a rule asks, in words ----------------------------------------------------------------------
def hours_text(hours, days=False):
    """72 h; with `days`, a rule of whole days as "3 days (72 h)"."""
    if days and hours and hours % 24 == 0:
        return ngettext('%(count)d day (%(hours)d h)', '%(count)d days (%(hours)d h)', hours // 24) % {
            'count': hours // 24, 'hours': hours}
    return _('%(hours)s h') % {'hours': formats.number_format(hours, 1 if isinstance(hours, Decimal) else 0)}


def both_text(hours, degrees):
    """What is asked or reached, in the hours and the degree-days that are there: "72 h", "60 degree-days" or both."""
    parts = [text for text in (hours, degrees) if text is not None]
    if len(parts) < 2:
        return parts[0] if parts else ''
    return _('%(hours)s and %(degrees)s') % {'hours': parts[0], 'degrees': parts[1]}


def asks_text(hours, degree_days, days=False):
    """The rule's fast: "72 h", "3 days (72 h)" (with `days`), "60 degree-days" or "72 h and 60 degree-days"."""
    return both_text(None if hours is None else hours_text(hours, days),
                     None if degree_days is None else degree_days_text(degree_days))


@dataclass(frozen=True)
class Requirement:
    """What the rule that applies asks of the fast: hours, degree-days (a harvest's purging) or both; each that is
    set must be reached."""
    rule: HandlingRule
    hours: int | None
    degree_days: Decimal | None

    @classmethod
    def of(cls, rule):
        return None if rule is None else cls(rule, rule.min_fasting_hours, rule.min_fasting_degree_days)

    @property
    def asks(self):
        """Whether it asks anything: a rule of 0 hours and no degree-days asks nothing."""
        return bool(self.hours or self.degree_days)

    def text(self):
        return asks_text(self.hours, self.degree_days)


def requirement_of(kind, species):
    """The Requirement a handling of `kind` is checked against for a species; None when no rule applies."""
    return Requirement.of(rule_of(kind, species))


# ---- how long the fish have fasted ---------------------------------------------------------------------
@dataclass(frozen=True)
class Fasted:
    """How long fish had gone without feed at the start of a handling day: the hours since the last feeding and, when
    the rule asks for degree-days, the degree-days of the full days between (`accrual`: how they were found), and
    whether what the rule asks for is reached."""
    hours: Decimal
    degree_days: Decimal | None
    accrual: object
    ok: bool

    def text(self, requirement=None):
        """6.0 h, 36 degree-days or both: only what the rule asks (the hours when there is no rule)."""
        asks_hours = requirement is None or requirement.hours is not None
        return both_text(hours_text(self.hours) if asks_hours else None,
                         None if self.degree_days is None else degree_days_text(self.degree_days))


def hours_since(unit, day, moment):
    """The hours from `moment` to the start of `day` on the unit's site clock, never rounded up."""
    hours = max(Decimal((start_of(day, unit) - moment).total_seconds()) / 3600, Decimal(0))
    return hours.quantize(HOUR, rounding=ROUND_DOWN)


def fed_since(requirement, day):
    """The first day the last feeding before a handling on `day` is looked for: LOOKBACK_DAYS back for a rule in hours
    alone (or none); None, any day, for a rule that asks degree-days."""
    if requirement is not None and requirement.degree_days is not None:
        return None
    return day - LOOKBACK_DAYS * DAY


def fasted(unit, day, fed, requirement, water=None, batch_ids=()):
    """The Fasted of fish last fed as `fed` (farm.feeding.read.LastFed) for a handling on `day`, against the
    requirement (None: only the hours are told). `water` (farm.water.degree_days.BatchWater of the batches) and the
    `batch_ids` are needed when the requirement asks for degree-days; with several batches the fewest degree-days
    count (the fast is never overstated)."""
    hours = hours_since(unit, day, fed.moment)
    degrees, accrual = None, None
    if requirement is not None and requirement.degree_days is not None:
        accruals = [water.accrue(batch_id, fed.record.date + DAY, day - DAY) for batch_id in batch_ids]
        accrual = min(accruals, key=lambda each: each.total)
        degrees = accrual.total.quantize(HOUR, rounding=ROUND_DOWN)
    ok = (requirement is None
          or ((requirement.hours is None or hours >= requirement.hours)
              and (requirement.degree_days is None or degrees >= requirement.degree_days)))
    return Fasted(hours, degrees, accrual, ok)


def complete_on(unit, fed, requirement, water=None, batch_ids=()):
    """The first handling day the fast the requirement asks is complete on, for fish last fed as `fed`: the first day
    `fasted` says ok, found without trying the days one by one. By hours, the first day that starts the hours after
    the feeding; by degree-days, the day after the one the batch's walk forward from the day after the feeding reaches
    them on (`BatchWater.walk`, the one search; of several batches the latest); the later of the two. None when the
    degree-days are never reached (nothing to project at, or a projection of 0 °C or below)."""
    day = fed.record.date
    if requirement.hours:
        due = fed.moment + timedelta(hours=requirement.hours)
        day = due.astimezone(zone_of(unit.production_department.site)).date()
        if start_of(day, unit) < due:
            day += DAY
    if requirement.degree_days is not None:
        for batch_id in batch_ids:
            if requirement.degree_days <= 0:
                continue
            accrual = water.walk(batch_id, fed.record.date + DAY, needed=requirement.degree_days)
            if accrual.reached is None:
                return None
            day = max(day, accrual.reached + DAY)
    return day


# ---- when feeding must stop ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Start:
    """When the fast before a handling must start (see `start_of_fast`): the moment (None when it cannot be worked out:
    degrees asked, none known, no hours), and how it was found."""
    starts_at: datetime | None
    # How the degree-days were added up, backward from the day before the handling (farm.water.degree_days.Accrual);
    # None when the rule asks for none.
    accrual: object = field(default=None, compare=False)

    @property
    def unknown(self):
        """The degree-days could not be worked out: no temperature to project at."""
        return self.accrual is not None and self.accrual.unknown

    @property
    def unreached(self):
        """The degree-days are not reached since the fish came, at these temperatures."""
        return self.accrual is not None and not self.accrual.unknown and self.accrual.reached is None

    @property
    def projected(self):
        """Days ahead were counted at a projection."""
        return self.accrual is not None and bool(self.accrual.projected)

    @property
    def projected_at_assumed(self):
        return self.projected and self.accrual.projected_at_assumed

    @property
    def missing(self):
        """Past days counted without a measured temperature."""
        return self.accrual.missing if self.accrual is not None else 0

    @property
    def assumed(self):
        return self.accrual.assumed if self.accrual is not None else None


def start_of_fast(unit, day, requirement, water=None, batch_id=None, since=None):
    """The Start of the fast for a handling on `day`: the later of the hours' start and the degree-days' start (module
    docstring). `water` (BatchWater with `batch_id`) is needed when the requirement asks for degree-days. `since`: the
    earliest day the fast can start on when the caller knows it (the day after the last feeding: a fast does not start
    before the fish were last fed); else the batch's first day on the farm."""
    candidates, accrual = [], None
    if requirement.hours:
        candidates.append(start_of(day, unit) - timedelta(hours=requirement.hours))
    if requirement.degree_days:
        # Back to `since` (the batch's first day on the farm), never further: reached, or the fast starts on that day.
        first = max(since or water.began(batch_id), water.began(batch_id))
        walked = (day - DAY - first).days + 1
        accrual = water.walk(batch_id, day - DAY, backward=True, needed=requirement.degree_days, days=max(walked, 0))
        if not accrual.unknown and (accrual.reached or accrual.last) is not None:
            candidates.append(start_of(accrual.reached or accrual.last, unit))
    return Start(min(candidates, default=None), accrual)


# ---- the fasts plans ask for --------------------------------------------------------------------------
@dataclass(frozen=True)
class Fast:
    """The fast a planned harvest or transport asks of its unit."""
    item: HandlingPlanItem
    requirement: Requirement
    start: Start

    @property
    def starts_at(self):
        return self.start.starts_at

    @property
    def hours(self):
        return self.requirement.hours

    @property
    def degree_days(self):
        return self.requirement.degree_days

    @property
    def on(self):
        return self.item.date

    @property
    def first_day(self):
        """The first fasting day; None when the fast cannot be worked out (degrees asked, none known, no hours)."""
        return self.starts_at.date() if self.starts_at is not None else None

    def covers(self, day):
        return self.first_day is not None and self.first_day <= day <= self.on

    def why(self):
        """Fasting before the harvest of 15 Nov 2026: from 12 Nov 2026, 00:00 (72 h)."""
        start = self.start
        params = {'date': formats.date_format(self.on, 'DATE_FORMAT'), 'asks': self.requirement.text(),
                  'start': shown_moment(self.starts_at, self.item.unit) if self.starts_at is not None else ''}
        harvest = self.item.kind == HandlingPlanItem.Kind.HARVEST
        if self.starts_at is None:
            text = (_('Fasting before the harvest of %(date)s: %(asks)s.') if harvest
                    else _('Fasting before the transport of %(date)s: %(asks)s.')) % params
        elif harvest:
            text = _('Fasting before the harvest of %(date)s: from %(start)s (%(asks)s).') % params
        else:
            text = _('Fasting before the transport of %(date)s: from %(start)s (%(asks)s).') % params
        if start.unknown:
            text += ' ' + _('Degree-days unknown: no temperature.')
        if start.unreached:
            walked = sum(start.accrual.days.values())
            text += ' ' + ngettext(
                'The degree-days are not reached since the fish came (%(days)d day) at these temperatures.',
                'The degree-days are not reached since the fish came (%(days)d days) at these temperatures.',
                walked) % {'days': walked}
        if start.projected:
            text += ' ' + (projected_sentence(start.assumed) if start.projected_at_assumed else
                           _('Projected at the mean water temperature of the last days measured.'))
        counted = accrual_text(start.accrual)
        return f'{text} {counted}' if counted else text


def fast_of(item, water=None, requirement=None, done_too=False):
    """The fast a plan item asks for; None when it is done or cancelled, or no rule (or one that asks nothing) applies.
    `water` (BatchWater with the item's batch) and `requirement` are given by a caller that has them for many items.
    `done_too`: the fast a done item asked for as well (the planned-slaughter deadline: the day the fish were to start
    fasting does not move once the harvest is recorded, audit F-101)."""
    if item.cancelled_reason or (item.done and not done_too):
        return None
    if requirement is None:
        requirement = requirement_of(item.kind, item.batch.species)
    if requirement is None or not requirement.asks:
        return None
    if requirement.degree_days and water is None:
        water = BatchWater({item.batch_id}, local_today(item.unit))
    return Fast(item, requirement, start_of_fast(item.unit, item.date, requirement, water, item.batch_id))


def planned_as_of(units, first, moment):
    """The plans (HandlingPlanItem) of these units (Tank, with their sites) for `first` or later, as they were recorded
    at `moment`, each found by its id (core.versions): one made since is not read, one changed or cancelled since is
    read as it was. Their units are the ones given, their batches read once with their species."""
    by_id = {unit.pk: unit for unit in units}
    items = [item for item in versions.as_of(HandlingPlanItem, moment, unit=list(by_id)) if item.date >= first]
    batches = stock_read.batches_of({item.batch_id for item in items})
    for item in items:
        item.unit, item.batch = by_id[item.unit_id], batches[item.batch_id]
    return items


def fasts(units, first, last, as_of=None):
    """{(unit id, day): Fast} for the fasting days from `first` to `last` of these units; where the fasts of two
    plans overlap, the one that starts first wins. Loaded once for a page or a walk: the rules and, for the plans
    whose rule asks for degree-days, the water of their batches (one reading for the farm's today of each unit).
    `as_of` (a moment): the fasts of the plans as they were recorded then (`planned_as_of`: the plan from a past start,
    owner decision 12), their water read as on that moment's day on each unit's clock."""
    # A plan of any later day can have started its fast by `last` (a purge has no longest: it is the water's).
    if as_of is None:
        items = list(HandlingPlanItem.objects.filter(unit__in=units, date__gte=first)
                     .select_related('unit__production_department__site', 'batch__species', 'operation'))
        today_of = local_today
    else:
        items = planned_as_of(units, first, as_of)

        def today_of(unit):
            return as_of.astimezone(zone_of(unit.production_department.site)).date()
    requirements = {}
    for item in items:
        key = (item.kind, item.batch.species_id)
        if key not in requirements:
            requirements[key] = requirement_of(item.kind, item.batch.species)
    degrees = [item for item in items if item.is_open and requirements[(item.kind, item.batch.species_id)]
               and requirements[(item.kind, item.batch.species_id)].degree_days]
    waters = {}
    for today in {today_of(item.unit) for item in degrees}:
        members = [item for item in degrees if today_of(item.unit) == today]
        water = BatchWater({item.batch_id for item in members}, today)
        waters.update({item.pk: water for item in members})
    found = {}
    for item in items:
        fast = fast_of(item, waters.get(item.pk), requirements[(item.kind, item.batch.species_id)])
        if fast is None or fast.starts_at is None:
            continue
        day = max(fast.first_day, first)
        while day <= min(fast.on, last):
            key = (item.unit_id, day)
            if key not in found or fast.starts_at < found[key].starts_at:
                found[key] = fast
            day += DAY
    return found


def fasting_on(unit, day):
    """Why the fish of `unit` fast on `day` (the meal board shows no ration with it), or None."""
    fast = fasts([unit], day, day).get((unit.pk, day))
    return fast.why() if fast is not None else None

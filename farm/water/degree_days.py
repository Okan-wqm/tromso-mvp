"""The water a batch lived in, day by day, and what it adds up to in degree-days: the one definition and the one
accrual for every reader, the medicine withdrawal (farm/health/withdrawal.py) and the purging fast before a harvest
(farm/handling/fasting.py). Ending a withdrawal too early is the dangerous direction: every rule below takes the safe
side (the coordinator's decisions of 2026-11-26 on the architecture audit's H-2 and M-3 and on the independent review
of the first round, REVIEW-1: never an earlier end without a question).

- **Where a unit's water is read**: owner rule A9's tiers, from the one resolver (farm/water/read.py `tiers`): the
  unit's OWN places (its own-water points: middle, depth, outlets, drain; never the inlet), and only when the day has
  nothing there, its SYSTEM's (the loop point, or the system's own sensors when it has no loop point).
- **A day's temperature** at a unit, per farm-local day on the clock of the place it is read at, is **the lowest of
  everything measured in the first tier that has a measurement that day**, probe days and water samples together:
  - **a probe day** is a CLOSED day of a temperature probe (farm.models.ProbeDay, a stored fact written when the day
    is over by farm/water/services.py and changed only through the withdrawal guard; never the live readings): the
    time-weighted mean of the day's good readings, counted when at least `sensor_day_hours` (20) of the day's hours
    hold a good reading and as many hours are covered, a reading standing for the water until the channel's next
    stored row and at most `sensor_hold_seconds` (an hour), the channel has a range set and the mean lies inside the
    parameter's plausible range. Today is never a probe day: it is not over;
  - **the water samples**: the mean of the day's live samples at a point.
  A probe day and the samples of the same tier that differ by more than `probe_sample_tolerance_c` are said (the
  lower counts all the same).
- **A day a probe is still expected for** (its place had a probe day row on the last day the daily job closed, and
  this day is after it) is NOT CLOSED YET: it is projected, never assumed and never read from the samples alone, and
  a sum that needs such a day is "about" and cannot free fish (farm/health/withdrawal.py).
- **A past day with nothing measured** counts at **the species' assumed water temperature**
  (`Species.withdrawal_temperature_c`, Setup › Reference data › Species), **but never above the cap**: the coldest
  daily mean measured in the `assumption_cap_days` (7) days before the gap of unmeasured days began (the cap does not
  run out inside a gap: it lifts only when a measurement says so), and not above the first day measured after the
  gap when there is one. The gap is traced back no further than the walk's first day less the cap's days, a bound
  that never moves with today (REVIEW-2, N-1); a projection at the assumed temperature is capped the same way (N-9).
  **0 °C when the species has no assumed temperature.**
- A batch in several units that day takes the lowest unit's (a unit not closed yet makes the batch's day not closed).
- **A daily mean of 0 °C or below adds nothing**: degree-days never go down.
- **A projection** is the mean of the batch's last PROJECTION_DAYS (7) measured days within LOOKBACK_DAYS (30) of
  today; with none measured, the species' assumed temperature; with neither, nothing (`unknown`). A projection of 0 °C
  or below adds nothing a day, so a sum still to reach is never reached (`unreachable`).
- **Every sum says its sources**: how many days came from the sensors, the samples, an assumption (capped or not, or
  0 °C), how many are not closed yet and how many are projected (`Accrual.days`, `accrual_text`).

The three numbers in backticks are the platform owner's settings (core.platform.degree_day_rules), changed only
through the withdrawal guard. `BatchWater` reads everything it needs for a set of batches at once (their presence in
the units, the units, their species, the samples, the closed probe days): its questions never query per batch, and no
page reads the sensors' readings. `BatchWater.walk` is the one accrual: forward from a day (the withdrawal, the fast's
degree-days, the day a purge is complete) or backward (when a fast must start)."""
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_CEILING, Decimal

from django.db.models import Max, Q
from django.utils import formats
from django.utils.translation import gettext as _, ngettext

from core import platform
from farm.models import Batch, ProbeDay, ProbeDayClosing, Tank
from farm.models.site import zone_of
from farm.models.water_point import local_time, site_of
from farm.stock.dates import end_of, shown_date, start_of
from farm.stock.read import Presence

from . import parameters, sources
from .read import Series, tiers

DAY = timedelta(days=1)
TEMPERATURE = parameters.TEMPERATURE
ZERO = Decimal(0)
PROJECTION_DAYS = 7     # the days with a temperature a projection takes the mean of
LOOKBACK_DAYS = 30      # how far back from today a projection looks for measured days
# A probe is still expected at a place that had a closed row on one of this many last closed days of its clock: a day it
# was silent (dead for a day, a cleaning flagged as maintenance) does not let the next day count from the samples before
# the job closes it (REVIEW-2, N-2), and a probe removed for good stops being expected this many days after its last row,
# so it never holds fish for ever (only days after the clock's last closing are ever not closed). A week: the cap's.
EXPECTED_DAYS = 7

# Where a day's temperature came from (Accrual.days counts them). UNCLOSED: a past day a probe is still expected for;
# PENDING: today or a day to come, not measured.
SENSOR, SAMPLES, ASSUMED, CAPPED, NOTHING, PROJECTED, UNCLOSED, PENDING = (
    'sensor', 'samples', 'assumed', 'capped', 'zero', 'projected', 'unclosed', 'pending')
MISSING = (ASSUMED, CAPPED, NOTHING)


@dataclass(frozen=True)
class Measured:
    """A measured daily mean and its source (SENSOR or SAMPLES); `differs`: by how much the probe day and the samples
    of its tier disagreed, when it is more than the tolerance (None otherwise)."""
    value: Decimal
    source: str
    differs: Decimal | None = None


NOT_CLOSED = object()        # what a day a probe is still expected for answers instead of a Measured


def zone_key(site):
    """The clock a place's probe days are closed on: its site's time zone, by name (ProbeDayClosing.timezone)."""
    return zone_of(site).key


class Temperatures:
    """The daily mean water temperature of units from `first` to `last`, read once: the samples of their points in one
    query, the closed probe days of their places in one, the newest closing of each clock in one. A day outside the
    range was not read: asking for it is an error, never "not measured"."""

    def __init__(self, units, first, last, tolerance=None):
        units = list(units)
        self.first, self.last = first, last
        # (the platform's setting when the caller has not read the rules already)
        self.tolerance = platform.degree_day_rules()[3] if tolerance is None else tolerance
        self.tiers = tiers(units, nested=False)
        points = {point.pk: point for found in self.tiers.values() for tier in found for point in tier.points}
        values = defaultdict(list)
        if points and first <= last:
            series = Series(points.values(), TEMPERATURE, *span(units, first, last))
            for point_id, point in points.items():
                for moment, value in zip(series.moments[point_id], series.values[point_id]):
                    day = local_time(moment, point).date()
                    if first <= day <= last:
                        values[(point_id, day)].append(value)
        self.samples = {key: sum(found, ZERO) / len(found) for key, found in values.items()}
        # The sensors' places: each target with the clock its days are closed on (a point's site; a system's).
        clocks = {}
        for found in self.tiers.values():
            for tier in found:
                for point in tier.points:
                    clocks[(sources.POINT, point.pk)] = zone_key(site_of(point))
                for target, _origin in tier.targets:
                    if target not in clocks:               # a system's own sensors
                        clocks[target] = zone_key(tier.owner.site)
        self.probes, self.rowed, self.closed = defaultdict(list), set(), {}
        if clocks and first <= last:
            self._read_probe_days(clocks, first, last)

    def _read_probe_days(self, clocks, first, last):
        """The closed probe days of the places from `first` to `last` and on each clock's last closed day (what says
        whether a probe is still expected at a place): `probes` {(target, day): [the means that count]}, `rowed` the
        (target, day) with any live row, `closed` {target: its clock's last closed day}."""
        last_closed = dict(ProbeDayClosing.objects.values('timezone').annotate(last=Max('day'))
                           .values_list('timezone', 'last'))
        self.closed = {target: last_closed[clock] for target, clock in clocks.items() if clock in last_closed}
        days = Q(day__gte=first, day__lte=last)
        for closed in set(last_closed.values()):      # and the last closed days a probe is expected after
            days |= Q(day__gt=closed - EXPECTED_DAYS * DAY, day__lte=closed)
        point_ids = [pk for kind, pk in clocks if kind == sources.POINT]
        system_ids = [pk for kind, pk in clocks if kind == sources.SYSTEM]
        rows = (ProbeDay.objects.filter(voided_at__isnull=True)
                .filter(Q(point_id__in=point_ids) | Q(system_id__in=system_ids))
                .filter(days)
                .values_list('point_id', 'system_id', 'day', 'mean_c', 'counts'))
        for point_id, system_id, day, mean, counts in rows:
            target = (sources.POINT, point_id) if point_id else (sources.SYSTEM, system_id)
            self.rowed.add((target, day))
            if counts:
                self.probes[(target, day)].append(mean)

    def _expected(self, target, day):
        """Whether a probe day is still expected at `target` for `day`: the day is after the last one its clock was
        closed for, the place had a probe day row on one of the EXPECTED_DAYS last closed days, and has none for the
        day itself (a backfilled or corrected one counts as it stands)."""
        closed = self.closed.get(target)
        return (closed is not None and day > closed and (target, day) not in self.rowed
                and any((target, closed - back * DAY) in self.rowed for back in range(EXPECTED_DAYS)))

    def of(self, unit_id, day):
        """The unit's day: a Measured (the lowest of the probe days and the samples of the first tier that has any:
        its own places, else its system's), NOT_CLOSED when a probe of that tier is still expected for the day, or
        None when nothing was measured. LookupError for a day that was not read."""
        if not self.first <= day <= self.last:
            raise LookupError(f'The water of {day:%Y-%m-%d} was not read ({self.first:%Y-%m-%d} to '
                              f'{self.last:%Y-%m-%d}): an unread day is not an unmeasured one.')
        for tier in self.tiers.get(unit_id, []):
            if any(self._expected(target, day) for target, _origin in tier.targets):
                return NOT_CLOSED
            probes = [mean for target, _origin in tier.targets for mean in self.probes.get((target, day), ())]
            samples = [self.samples[(point.pk, day)] for point in tier.points if (point.pk, day) in self.samples]
            if probes and samples:
                probe, sample = min(probes), min(samples)
                differs = abs(probe - sample) if abs(probe - sample) > self.tolerance else None
                return Measured(min(probe, sample), SENSOR if probe <= sample else SAMPLES, differs)
            if probes:
                return Measured(min(probes), SENSOR)
            if samples:
                return Measured(min(samples), SAMPLES)
        return None


def span(units, first, last):
    """(start, end): the moments a Temperatures of these units reads its samples between, from the first moment of
    `first` to the last of `last`, the earliest and the latest on the clocks of the units' sites; None without units.
    A sample counts on the day of its point's clock, so a point on a site of another clock (a system's loop point) can
    have samples of `first` before the start: what is read depends on the units' clocks (`BatchWater.of_each`)."""
    units = list(units)
    if not units:
        return None
    return min(start_of(first, unit) for unit in units), max(end_of(last, unit) for unit in units)


@dataclass(frozen=True)
class Counted:
    """What one day counts for: its temperature and where it came from (`how`). `value` is None for a day that is not
    closed, not over or still to come: the walk projects it. `differs`: a probe day and the samples disagreed."""
    value: Decimal | None
    how: str
    differs: Decimal | None = None


@dataclass
class Accrual:
    """The degree-days of a walk over days (`BatchWater.walk`): `total` (projected days too) and `counted` (the days
    not projected), how many days came from each source (`days`: SENSOR, SAMPLES, ASSUMED, CAPPED, NOTHING, UNCLOSED,
    PROJECTED), the species' `assumed` temperature, the projection's temperature and whether it was the assumed one,
    `reached` (the day the sum reached what was asked), `last` (the last day walked), `unknown` (a day had nothing to
    be projected at), `unreachable` (the projection is 0 °C or below: what is still asked is never reached), the days a
    probe and the samples disagreed on (`differed`), and the settings it was counted with."""
    total: Decimal = ZERO
    counted: Decimal = ZERO
    days: Counter = field(default_factory=Counter)
    assumed: Decimal | None = None
    projected_at: Decimal | None = None
    projected_at_assumed: bool = False
    reached: date | None = None
    last: date | None = None
    unknown: bool = False
    unreachable: bool = False
    differed: list = field(default_factory=list)
    values: dict = field(default_factory=dict)      # {day: what it added}, of the days counted (not projected)
    cap_days: int = 0
    tolerance: Decimal = ZERO

    @property
    def missing(self):
        """Past days counted without a measurement: at the assumed temperature, capped or not, or as 0 °C."""
        return sum(self.days[how] for how in MISSING)

    @property
    def projected(self):
        """The days counted at a projection: those not over or still to come, and those not closed yet."""
        return self.days[PROJECTED] + self.days[UNCLOSED]

    @property
    def unclosed(self):
        """The past days a probe is still expected for: while there are any, the sum cannot free fish."""
        return self.days[UNCLOSED]


class BatchWater:
    """The water of a set of batches on the farm's `today`, with the temperatures read from `first` (None: from the
    first day any of the batches was on the farm) and the cap's days earlier (a gap of unmeasured days is traced back
    so far for its cap), and at least the LOOKBACK_DAYS before today (a projection's days). `presence`
    (farm.stock.read.Presence of the batches) can be handed in by a caller that has it already; `read_from`: the exact
    first day to read (`of_each`)."""

    def __init__(self, batch_ids, today, first=None, presence=None, read_from=None):
        self.batch_ids, self.today = set(batch_ids), today
        self.presence = presence if presence is not None else Presence.of_batches(self.batch_ids)
        unit_ids = {unit_id for units in self.presence.units.values() for unit_id in units}
        self.units = Tank.all_objects.select_related('production_department__site').in_bulk(unit_ids)
        # The batches' species in one query: the assumed temperature of a day without a measured one.
        self.batches = Batch.all_objects.select_related('species').in_bulk(self.batch_ids)
        _hours, _hold, self.cap_days, self.tolerance = platform.degree_day_rules()
        if read_from is None:
            if first is None:
                first = min((self.began(batch_id) for batch_id in self.batch_ids), default=today)
            read_from = self.first_day(today, first, self.cap_days)
        self.temperatures = Temperatures(list(self.units.values()), read_from, today, self.tolerance)
        self._projections, self._days, self._caps = {}, {}, {}

    @staticmethod
    def first_day(today, first, cap_days):
        """The first day the temperatures are read for: the cap's days before `first` (a walk from `first` caps a gap
        with the measured days no further back than that: `cap`), and at least LOOKBACK_DAYS back from today (a
        projection takes the last measured days within them)."""
        return min(first - cap_days * DAY, today - LOOKBACK_DAYS * DAY)

    @classmethod
    def of_each(cls, asked):
        """{(batch id, today, first): BatchWater} of every (batch id, today, first) asked (`first` None: from the
        batch's first day on the farm): one whose every answer about that batch is what `BatchWater({batch id}, today,
        first)` gives, the batch read alone, with the batches whose reads are the same read together (a page of fifty
        rows reads the water about once, not fifty times).

        Batches share one only when they share the day, the first day read and `span`, the moments their samples are
        read between on the clocks of the units each batch was ever in. Everything else a BatchWater holds is each
        batch's own: its presence, its species, the tiers of each unit, a point's daily means of samples, which are
        its samples between those moments of a day on its own clock, and a place's closed probe days, each on its own
        clock. A batch beside batches of other clocks would read a wider span, and a loop point on a site of a third
        clock could then count a sample on the first day read that the batch alone does not: a different mean, a
        different date (verification of wip/plans-perf, finding 2)."""
        asked = set(asked)
        if not asked:
            return {}
        presence = Presence.of_batches({batch_id for batch_id, _today, _first in asked})
        units = Tank.all_objects.select_related('production_department__site').in_bulk(
            {unit_id for unit_ids in presence.units.values() for unit_id in unit_ids})
        cap_days = platform.degree_day_rules()[2]
        keys = {}
        for batch_id, today, first in asked:
            first_day = cls.first_day(today, _began(presence, batch_id, today) if first is None else first, cap_days)
            read = span([units[unit_id] for unit_id in presence.units.get(batch_id, ())], first_day, today)
            keys[(batch_id, today, first)] = (today, first_day, read)
        groups = defaultdict(set)
        for (batch_id, _today, _first), key in keys.items():
            groups[key].add(batch_id)
        # One group holds every batch asked: the presence read above is the one it would read.
        waters = {key: cls(batch_ids, key[0], read_from=key[1], presence=presence if len(groups) == 1 else None)
                  for key, batch_ids in groups.items()}
        return {each: waters[key] for each, key in keys.items()}

    def began(self, batch_id):
        """The first day the batch had fish on the farm (today for a batch with no line)."""
        return _began(self.presence, batch_id, self.today)

    def assumed(self, batch_id):
        """The batch species' assumed water temperature; None when it has none."""
        return self.batches[batch_id].species.withdrawal_temperature_c

    def measured(self, batch_id, day):
        """The batch's day: the Measured that is the lowest of its units', NOT_CLOSED when a unit's probe day is still
        expected (it may be the lowest), None when nothing was measured (or the day is still to come)."""
        key = (batch_id, day)
        if key not in self._days:
            self._days[key] = self._measured(batch_id, day)
        return self._days[key]

    def _measured(self, batch_id, day):
        if day > self.today:
            return None
        found = [self.temperatures.of(unit_id, day) for unit_id in self.presence.units_of(batch_id, day)]
        if any(each is NOT_CLOSED for each in found):
            return NOT_CLOSED
        found = [each for each in found if each is not None]
        return min(found, key=lambda each: each.value) if found else None

    def _value(self, batch_id, day, floor):
        """The batch's measured mean of `day`, or None (not measured, not closed, or before `floor`: what a walk may not
        look back to). A day after `floor` that was not read is an error (Temperatures.of), never "not measured"."""
        if day < floor:
            return None
        found = self.measured(batch_id, day)
        return found.value if isinstance(found, Measured) else None

    def cap(self, batch_id, day, floor):
        """What caps the assumed temperature of the unmeasured `day`: the coldest daily mean measured in the cap's days
        (calendar days) before the gap of unmeasured days it lies in began, and the first day measured after the gap,
        the lower of them; None when neither is there. The gap is followed back no further than `floor`, the first day
        of the walk less the cap's days (never a bound that moves with today: REVIEW-2, N-1), and forward to today.
        Worked out once a gap: every day of it has the same cap (N-4)."""
        key = (batch_id, floor, day)
        if key not in self._caps:
            first = day
            while first - DAY >= floor and self._value(batch_id, first - DAY, floor) is None:
                first -= DAY
            last = day
            while last + DAY <= self.today and self._value(batch_id, last + DAY, floor) is None:
                last += DAY
            before = first - DAY
            found = [value for value in (self._value(batch_id, before - back * DAY, floor)
                                         for back in range(self.cap_days)) if value is not None]
            if last + DAY <= self.today:
                found.append(self._value(batch_id, last + DAY, floor))
            cap = min(found, default=None)
            gap = first
            while gap <= last:
                self._caps[(batch_id, floor, gap)] = cap
                gap += DAY
        return self._caps[key]

    def day(self, batch_id, day, floor=None):
        """What `day` counts for the batch (the module's rules); `floor`: how far back a gap's cap may look (default:
        the first day read)."""
        floor = self.temperatures.first if floor is None else floor
        found = self.measured(batch_id, day)
        if isinstance(found, Measured):
            return Counted(found.value, found.source, found.differs)
        if day >= self.today:
            return Counted(None, PENDING)
        if found is NOT_CLOSED:
            return Counted(None, UNCLOSED)
        assumed = self.assumed(batch_id)
        if assumed is None:
            return Counted(ZERO, NOTHING)
        cap = self.cap(batch_id, day, floor)
        return Counted(cap, CAPPED) if cap is not None and cap < assumed else Counted(assumed, ASSUMED)

    def projection(self, batch_id, floor=None):
        """(the temperature a day is projected at, whether it is the species' assumed one): the mean of the batch's
        last PROJECTION_DAYS measured days within LOOKBACK_DAYS of today; with none measured the assumed temperature,
        capped as a past day of the gap today lies in is (REVIEW-2, N-9; `floor` as for `cap`); (None, False) with
        neither."""
        floor = self.temperatures.first if floor is None else floor
        if (batch_id, floor) not in self._projections:
            found, day = [], self.today
            while day > self.today - LOOKBACK_DAYS * DAY and len(found) < PROJECTION_DAYS:
                value = self._value(batch_id, day, self.temperatures.first)
                if value is not None:
                    found.append(value)
                day -= DAY
            if found:
                self._projections[(batch_id, floor)] = (sum(found, ZERO) / len(found), False)
            else:
                assumed = self.assumed(batch_id)
                if assumed is not None:
                    cap = self.cap(batch_id, self.today, floor)
                    assumed = cap if cap is not None and cap < assumed else assumed
                self._projections[(batch_id, floor)] = (assumed, assumed is not None)
        return self._projections[(batch_id, floor)]

    def walk(self, batch_id, start, backward=False, needed=None, days=None):
        """THE accrual: the degree-days of the batch's days from `start`, forward (or `backward`), until the sum reaches
        `needed` (`reached` is that day) or after `days` days; at least one of them is given. A day counts at its
        temperature (the module's rules), 0 °C or below as 0; a day not closed, not over or still to come at the
        projection (with none, `unknown`, and the walk stops). Forward, every day from today's projected one on is
        projected too: the days still needed are worked out at once (`unreachable` when the projection adds nothing).
        The cap of a gap looks back no further than the walk's first day less the cap's days (`cap`)."""
        if needed is None and days is None:
            raise ValueError('A walk needs a sum to reach or a number of days.')
        earliest = (start if not backward else start - (days - 1) * DAY if days
                    else self.temperatures.first + self.cap_days * DAY)
        floor = min(earliest, start) - self.cap_days * DAY
        accrual = Accrual(assumed=self.assumed(batch_id), cap_days=self.cap_days, tolerance=self.tolerance)
        step, day, walked = (-DAY if backward else DAY), start, 0
        while (days is None or walked < days) and not (needed is not None and accrual.total >= needed):
            counted = self.day(batch_id, day, floor)
            if counted.value is None:
                mean, at_assumed = self.projection(batch_id, floor)
                if mean is None:
                    accrual.unknown = True
                    break
                accrual.projected_at, accrual.projected_at_assumed = mean, at_assumed
                value = max(mean, ZERO)
                if counted.how == PENDING and not backward and needed is not None:
                    self._project_rest(accrual, day, value, needed, None if days is None else days - walked)
                    break
                accrual.days[PROJECTED if counted.how == PENDING else UNCLOSED] += 1
            else:
                value = max(counted.value, ZERO)
                accrual.days[counted.how] += 1
                accrual.counted += value
                accrual.values[day] = value
                if counted.differs is not None:
                    accrual.differed.append(day)
            accrual.total += value
            accrual.last, walked = day, walked + 1
            if needed is not None and accrual.total >= needed:
                accrual.reached = day
            day += step
        return accrual

    @staticmethod
    def _project_rest(accrual, day, value, needed, left):
        """A forward walk's projected days from `day` (today or later) on, all at `value`, at once: as many as reach
        `needed`, at most `left` (None: no bound); none reach it at 0 °C (`unreachable`)."""
        if value <= 0:
            count, accrual.unreachable = left or 0, True
        else:
            count = int(((needed - accrual.total) / value).to_integral_value(rounding=ROUND_CEILING))
            count = count if left is None else min(count, left)
        if count:
            accrual.days[PROJECTED] += count
            accrual.total += count * value
            accrual.last = day + (count - 1) * DAY
            if accrual.total >= needed:
                accrual.reached = accrual.last

    def accrue(self, batch_id, first, last):
        """The degree-days of the days from `first` to `last` (both counted): a walk of those days."""
        return self.walk(batch_id, first, days=max((last - first).days + 1, 0))


def _began(presence, batch_id, today):
    """The first day a batch had fish in any unit (`today` for a batch with no line)."""
    return min((days[0] for (_unit, batch), (days, _counts) in presence.timelines.items() if batch == batch_id),
               default=today)


def _plain(value):
    """8.0 as the language writes it, one decimal."""
    return formats.number_format(value, 1)


def degree_days_text(value):
    """150 degree-days, 12.5 degree-days: a value as the pages say it (a decimal only when it has one)."""
    value = Decimal(value)
    count = formats.number_format(value, decimal_pos=0 if value == value.to_integral_value() else 1)
    return ngettext('%(count)s degree-day', '%(count)s degree-days', 1 if value == 1 else 2) % {'count': count}


def missing_sentence(count, assumed):
    """The sentence that says how many past days had no measured water temperature and were counted at the species'
    assumed temperature as it is, or as 0 °C with the way to set one."""
    params = {'count': count}
    if assumed is not None:
        params['temperature'] = _plain(assumed)
        return ngettext(
            '%(count)d day without a measured water temperature is counted at the assumed %(temperature)s °C '
            '(the species’ setting in Reference data).',
            '%(count)d days without a measured water temperature are counted at the assumed %(temperature)s °C '
            '(the species’ setting in Reference data).', count) % params
    return ngettext(
        '%(count)d day without a measured water temperature is counted as 0 °C: set the species’ assumed '
        'temperature in Reference data › Species.',
        '%(count)d days without a measured water temperature are counted as 0 °C: set the species’ assumed '
        'temperature in Reference data › Species.', count) % params


def capped_sentence(count, cap_days):
    """The sentence that says how many past days without a measurement were counted below the species' assumed
    temperature, at the coldest day measured around their gap."""
    return ngettext(
        '%(count)d day without a measured water temperature is counted below the species’ assumed temperature: at '
        'the coldest daily mean measured in the %(days)d days before the gap began, or the first day measured after '
        'it when that is colder.',
        '%(count)d days without a measured water temperature are counted below the species’ assumed temperature: at '
        'the coldest daily mean measured in the %(days)d days before their gap began, or the first day measured '
        'after it when that is colder.', count) % {'count': count, 'days': cap_days}


def projected_sentence(assumed):
    """The sentence that says a projection was made at the species' assumed temperature, nothing having been
    measured lately."""
    return _('Projected at the assumed %(temperature)s °C (the species’ setting in Reference data): no water '
             'temperature was measured in the last %(days)d days.') % {'temperature': _plain(assumed),
                                                                       'days': LOOKBACK_DAYS}


def accrual_text(accrual):
    """What every reader that adds degrees up says of them: how many days came from each source ("Days counted: 5 days
    measured by the sensors, 2 days from water samples, 1 day without a measurement, 1 sensor day not closed yet, 3
    days projected."), then how the days without a measurement were counted, and the days a probe and the samples
    disagreed on. '' for no accrual."""
    if accrual is None:
        return ''
    days = accrual.days
    parts = [text % {'count': count} for text, count in (
        (ngettext('%(count)d day measured by the sensors', '%(count)d days measured by the sensors', days[SENSOR]),
         days[SENSOR]),
        (ngettext('%(count)d day from water samples', '%(count)d days from water samples', days[SAMPLES]),
         days[SAMPLES]),
        (ngettext('%(count)d day without a measurement', '%(count)d days without a measurement', accrual.missing),
         accrual.missing),
        (ngettext('%(count)d sensor day not closed yet', '%(count)d sensor days not closed yet', days[UNCLOSED]),
         days[UNCLOSED]),
        (ngettext('%(count)d day projected', '%(count)d days projected', days[PROJECTED]), days[PROJECTED]),
    ) if count]
    sentences = [_('Days counted: %(parts)s.') % {'parts': ', '.join(parts)}] if parts else []
    if days[ASSUMED] or days[NOTHING]:
        sentences.append(missing_sentence(days[ASSUMED] + days[NOTHING], accrual.assumed))
    if days[CAPPED]:
        sentences.append(capped_sentence(days[CAPPED], accrual.cap_days))
    if accrual.differed:
        count = len(accrual.differed)
        sentences.append(ngettext(
            'On %(count)d day (%(day)s) the probe’s daily mean and the water samples differed by more than '
            '%(tolerance)s °C: the lower was counted. Check the probe.',
            'On %(count)d days (the first %(day)s) the probe’s daily mean and the water samples differed by more than '
            '%(tolerance)s °C: the lower was counted. Check the probe.', count) % {
            'count': count, 'day': shown_date(min(accrual.differed)), 'tolerance': _plain(accrual.tolerance)})
    return ' '.join(sentences)


def probe_days_of(units):
    """The probe day rows, voided ones too, of the places the degree-days of these units read (their tiers), oldest
    first: what `manage.py probe_days list` shows."""
    targets = {target for found in tiers(units, nested=False).values() for tier in found
               for target, _origin in tier.targets}
    return list(ProbeDay.objects.filter(
        Q(point_id__in=[pk for kind, pk in targets if kind == sources.POINT])
        | Q(system_id__in=[pk for kind, pk in targets if kind == sources.SYSTEM]))
        .select_related('point', 'system').order_by('day', 'id'))


def probe_day(pk):
    """The probe day row of that id, or None."""
    return ProbeDay.objects.filter(pk=pk).first()

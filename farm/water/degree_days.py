"""The water a batch lived in, day by day, and what it adds up to in degree-days: the one definition and the one
accrual for every reader, the medicine withdrawal (farm/health/withdrawal.py) and the purging fast before a harvest
(farm/handling/fasting.py). Ending a withdrawal too early is the dangerous direction: every rule below takes the safe
side (the coordinator's decision of 2026-11-26 on the architecture audit's H-2 and M-3).

- **A day's temperature** at a unit, per farm-local day on the clock of the place it is read at, from the first source
  that has one:
  1. **the sensors**: a temperature probe with at least SENSOR_DAY_HOURS (20) hours of fresh, good readings that day
     counts at their time-weighted mean (each reading holds until the channel's next one, at most its fresh time:
     sensors/provider.py `covered`), rounded down to 0.01 °C. The places are owner rule A9's tiers: the unit's own-water
     points (middle, depth, outlets, drain; never the inlet), else its system (the loop point, or the system's own
     sensors when it has no loop point). With several probes or points in a tier, the lowest mean;
  2. else **the water samples**: the mean of the day's live samples at the unit's own-water points (the lowest point's),
     else at its system's loop point (farm/water/read.py's `water_sources`);
  3. else, for a past day, **the species' assumed water temperature** (`Species.withdrawal_temperature_c`, Setup ›
     Reference data › Species), **but never above the coldest daily mean measured (1 or 2) in the CAP_DAYS (7) days
     before it**, so an assumption cannot run ahead of the water; **0 °C when the species has none**. A day that is
     not over, or still to come, without a measurement is not counted: it is projected.
  A batch in several units that day takes the lowest unit's.
- **A daily mean of 0 °C or below adds nothing**: degree-days never go down.
- **A projection** is the mean of the batch's last PROJECTION_DAYS (7) measured days within LOOKBACK_DAYS (30) of
  today; with none measured, the species' assumed temperature; with neither, nothing (`unknown`). A projection of 0 °C
  or below adds nothing a day, so a sum still to reach is never reached (`unreachable`).
- **Every sum says its sources**: how many days came from the sensors, the samples, an assumption (capped or not, or
  0 °C) and a projection (`Accrual.days`, `accrual_text`); a sensor reading that failed is said.

`BatchWater` reads everything it needs for a set of batches at once (their presence in the units, the units, their
species, the samples, the sensors' daily means): its questions never query per batch. `BatchWater.walk` is the one
accrual: forward from a day (the withdrawal, the fast's degree-days) or backward (when a fast must start)."""
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from django.utils import formats, timezone
from django.utils.translation import gettext as _, ngettext

from farm.models import Batch, System, Tank
from farm.models.site import zone_of
from farm.models.water_point import local_time, site_of
from farm.stock.dates import end_of, start_of
from farm.stock.read import Presence

from . import parameters, sources
from .read import SYSTEM, SYSTEM_KEY, UNIT, Series, sensor_targets, water_sources

DAY = timedelta(days=1)
TEMPERATURE = parameters.TEMPERATURE
ZERO = Decimal(0)
SENSOR_DAY_HOURS = 20   # the hours of fresh good readings a day needs before the sensors' mean counts for it
CAP_DAYS = 7            # an assumed temperature is never above the coldest daily mean measured in these days before
PROJECTION_DAYS = 7     # the days with a temperature a projection takes the mean of
LOOKBACK_DAYS = 30      # how far back from today they are looked for (the water's window)
SENSOR_STEP = Decimal('0.01')

# Where a day's temperature came from (Accrual.days counts them).
SENSOR, SAMPLES, ASSUMED, CAPPED, NOTHING, PROJECTED, PENDING = (
    'sensor', 'samples', 'assumed', 'capped', 'zero', 'projected', 'pending')
MISSING = (ASSUMED, CAPPED, NOTHING)


@dataclass(frozen=True)
class Measured:
    """A measured daily mean and its source (SENSOR or SAMPLES)."""
    value: Decimal
    source: str


class Temperatures:
    """The daily mean water temperature of units from `first` to `last` (the module's rules 1 and 2), read once: the
    samples of their points in one query, the sensors' coverage of every place and day in one ask
    (farm/water/sources.py `covered`). `failed`: the sensors could not be read; their days then come from the samples
    or the assumption, and the sum says so."""

    def __init__(self, units, first, last):
        units = list(units)
        self.first, self.last = first, last
        self.sources = water_sources(units, nested=False, every_point=True)
        points = {source.point.pk: source.point for found in self.sources.values() for source in found}
        values = defaultdict(list)
        if points and first <= last:
            series = Series(points.values(), TEMPERATURE, *span(units, first, last))
            for point_id, point in points.items():
                for moment, value in zip(series.moments[point_id], series.values[point_id]):
                    day = local_time(moment, point).date()
                    if first <= day <= last:
                        values[(point_id, day)].append(value)
        self.samples = {key: sum(found, ZERO) / len(found) for key, found in values.items()}
        # The sensors' tiers (owner rule A9): the unit's own points, then its system's loop point, or the system's own
        # sensors when it has no loop point.
        looped = {unit_id: [source.point.pk for source in found if source.via == SYSTEM]
                  for unit_id, found in self.sources.items()}
        bare = {unit.system_id for unit in units if unit.system_id and not looped.get(unit.pk)}
        systems = System.objects.select_related('site').in_bulk(bare) if bare else {}
        self.tiers = {}
        for unit in units:
            own = [source.point.pk for source in self.sources.get(unit.pk, []) if source.via == UNIT]
            system = looped.get(unit.pk) or ([SYSTEM_KEY(unit.system_id)] if unit.system_id in systems else [])
            self.tiers[unit.pk] = [tier for tier in (own, system) if tier]
        places = {pk: (sensor_targets(point), site_of(point)) for pk, point in points.items()}
        places.update({SYSTEM_KEY(pk): ([((sources.SYSTEM, pk), None)], system.site) for pk, system in systems.items()})
        self.sensed, self.failed = self._sensed(places, first, last)

    @staticmethod
    def _sensed(places, first, last):
        """({(place key, day): the lowest mean of the probes with SENSOR_DAY_HOURS covered}, whether the sensors
        failed), each day on the clock of the place's site; today up to now."""
        asks, keys, now = [], [], timezone.now()
        for key, (targets, site) in places.items():
            zone, day = zone_of(site), first
            while day <= last:
                start = datetime.combine(day, time.min, tzinfo=zone)
                end = min(datetime.combine(day + DAY, time.min, tzinfo=zone), now)
                if start < end:
                    for target, _origin in targets:
                        asks.append((target, start, end))
                        keys.append((key, day))
                day += DAY
        if not asks:
            return {}, False
        answer = sources.covered(asks, TEMPERATURE)
        needed, found = SENSOR_DAY_HOURS * 3600, {}
        for index, covered in answer.values.items():
            for each in covered:
                if each.seconds >= needed:
                    mean = Decimal(repr(each.mean)).quantize(SENSOR_STEP, rounding=ROUND_FLOOR)
                    key = keys[index]
                    found[key] = min(found.get(key, mean), mean)
        return found, answer.failed

    def of(self, unit_id, day):
        """The unit's Measured on `day`, or None: the sensors' lowest mean in the first tier that has one; else the
        lowest of its own-water points' samples (never the inlet; owner, 2026-11-08: the conservative side), else its
        system's loop's."""
        for tier in self.tiers.get(unit_id, []):
            found = [self.sensed[(key, day)] for key in tier if (key, day) in self.sensed]
            if found:
                return Measured(min(found), SENSOR)
        own = [mean for mean in (self.samples.get((source.point.pk, day)) for source in self.sources.get(unit_id, [])
                                 if source.via == UNIT) if mean is not None]
        if own:
            return Measured(min(own), SAMPLES)
        for source in self.sources.get(unit_id, []):
            mean = self.samples.get((source.point.pk, day))
            if mean is not None:
                return Measured(mean, SAMPLES)
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
    over (or still to come) and has no measurement: the walk projects it."""
    value: Decimal | None
    how: str


@dataclass
class Accrual:
    """The degree-days of a walk over days (`BatchWater.walk`): `total` (projected days too) and `counted` (the days
    not projected), how many days came from each source (`days`: SENSOR, SAMPLES, ASSUMED, CAPPED, NOTHING, PROJECTED),
    the species' `assumed` temperature, the projection's temperature and whether it was the assumed one, `reached` (the
    day the sum reached what was asked), `last` (the last day walked), `unknown` (a day ahead had nothing to be
    projected at), `unreachable` (the projection is 0 °C or below: what is still asked is never reached) and
    `sensors_failed`."""
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
    sensors_failed: bool = False

    @property
    def missing(self):
        """Past days counted without a measurement: at the assumed temperature, capped or not, or as 0 °C."""
        return sum(self.days[how] for how in MISSING)

    @property
    def projected(self):
        return self.days[PROJECTED]


class BatchWater:
    """The water of a set of batches on the farm's `today`, with the temperatures read from `first` (CAP_DAYS earlier,
    for the cap, and the LOOKBACK_DAYS before today, whichever is earlier). `presence` (farm.stock.read.Presence of the
    batches) can be handed in by a caller that has it already."""

    def __init__(self, batch_ids, today, first, presence=None):
        self.batch_ids, self.today = set(batch_ids), today
        self.presence = presence if presence is not None else Presence.of_batches(self.batch_ids)
        unit_ids = {unit_id for units in self.presence.units.values() for unit_id in units}
        self.units = Tank.all_objects.select_related('production_department__site').in_bulk(unit_ids)
        # The batches' species in one query: the assumed temperature of a day without a measured one.
        self.batches = Batch.all_objects.select_related('species').in_bulk(self.batch_ids)
        self.temperatures = Temperatures(list(self.units.values()), self.first_day(today, first), today)
        self._projections = {}

    @staticmethod
    def first_day(today, first):
        """The first day the temperatures are read for: CAP_DAYS before `first` (an assumption is capped by the days
        before it), and at least LOOKBACK_DAYS back (a projection takes the last measured days within them)."""
        return min(first - CAP_DAYS * DAY, today - LOOKBACK_DAYS * DAY)

    @classmethod
    def of_each(cls, asked):
        """{(batch id, today, first): BatchWater} of every (batch id, today, first) asked: one whose every answer about
        that batch is what `BatchWater({batch id}, today, first)` gives, the batch read alone, with the batches whose
        reads are the same read together (a page of fifty rows reads the water about once, not fifty times).

        Batches share one only when they share the day, the first day read and `span`, the moments their samples are
        read between on the clocks of the units each batch was ever in. Everything else a BatchWater holds is each
        batch's own: its presence, its species, the sources of each unit (a unit's own points and its system's loop
        point), a point's daily means of samples, which are its samples between those moments of a day on its own
        clock, and a place's sensor days, each on its own clock. A batch beside batches of other clocks would read a
        wider span, and a loop point on a site of a third clock could then count a sample on the first day read that
        the batch alone does not: a different mean, a different date (verification of wip/plans-perf, finding 2)."""
        asked = set(asked)
        if not asked:
            return {}
        presence = Presence.of_batches({batch_id for batch_id, _today, _first in asked})
        units = Tank.all_objects.select_related('production_department__site').in_bulk(
            {unit_id for unit_ids in presence.units.values() for unit_id in unit_ids})
        keys = {}
        for batch_id, today, first in asked:
            first_day = cls.first_day(today, first)
            read = span([units[unit_id] for unit_id in presence.units.get(batch_id, ())], first_day, today)
            keys[(batch_id, today, first)] = (today, first_day, read)
        groups = defaultdict(set)
        for (batch_id, _today, _first), key in keys.items():
            groups[key].add(batch_id)
        # One group holds every batch asked: the presence read above is the one it would read. A BatchWater made with
        # `first` = the key's first day + CAP_DAYS reads from exactly the key's first day (`first_day`).
        waters = {key: cls(batch_ids, key[0], key[1] + CAP_DAYS * DAY, presence=presence if len(groups) == 1 else None)
                  for key, batch_ids in groups.items()}
        return {each: waters[key] for each, key in keys.items()}

    def assumed(self, batch_id):
        """The batch species' assumed water temperature; None when it has none."""
        return self.batches[batch_id].species.withdrawal_temperature_c

    def measured(self, batch_id, day):
        """The batch's Measured on `day`: the lowest of its units' that were measured; None when none was."""
        found = [each for each in (self.temperatures.of(unit_id, day)
                                   for unit_id in self.presence.units_of(batch_id, day)) if each is not None]
        return min(found, key=lambda each: each.value) if found else None

    def cap(self, batch_id, day):
        """The coldest daily mean measured for the batch in the CAP_DAYS days before `day`; None when none was."""
        found = [each.value for each in (self.measured(batch_id, day - back * DAY) for back in range(1, CAP_DAYS + 1))
                 if each is not None]
        return min(found, default=None)

    def day(self, batch_id, day):
        """What `day` counts for the batch (the module's rules 1 to 3)."""
        found = self.measured(batch_id, day)
        if found is not None:
            return Counted(found.value, found.source)
        if day >= self.today:
            return Counted(None, PENDING)
        assumed = self.assumed(batch_id)
        if assumed is None:
            return Counted(ZERO, NOTHING)
        cap = self.cap(batch_id, day)
        return Counted(cap, CAPPED) if cap is not None and cap < assumed else Counted(assumed, ASSUMED)

    def projection(self, batch_id):
        """(the temperature a day ahead is projected at, whether it is the species' assumed one): the mean of the batch's
        last PROJECTION_DAYS measured days within LOOKBACK_DAYS of today; with none measured the assumed temperature;
        (None, False) with neither."""
        if batch_id not in self._projections:
            found, day = [], self.today
            while day > self.today - LOOKBACK_DAYS * DAY and len(found) < PROJECTION_DAYS:
                measured = self.measured(batch_id, day)
                if measured is not None:
                    found.append(measured.value)
                day -= DAY
            if found:
                self._projections[batch_id] = (sum(found, ZERO) / len(found), False)
            else:
                assumed = self.assumed(batch_id)
                self._projections[batch_id] = (assumed, assumed is not None)
        return self._projections[batch_id]

    def walk(self, batch_id, start, backward=False, needed=None, days=None):
        """THE accrual: the degree-days of the batch's days from `start`, forward (or `backward`), until the sum reaches
        `needed` (`reached` is that day) or after `days` days; at least one of them is given. A day counts at its
        temperature (the module's rules), 0 °C or below as 0; a day not over or still to come without a measurement at
        the projection (with none, `unknown`, and the walk stops). Forward, every day from the first projected one on is
        projected too: the days still needed are worked out at once (`unreachable` when the projection adds nothing)."""
        if needed is None and days is None:
            raise ValueError('A walk needs a sum to reach or a number of days.')
        accrual = Accrual(assumed=self.assumed(batch_id), sensors_failed=self.temperatures.failed)
        step, day, walked = (-DAY if backward else DAY), start, 0
        while (days is None or walked < days) and not (needed is not None and accrual.total >= needed):
            counted = self.day(batch_id, day)
            if counted.how == PENDING:
                mean, at_assumed = self.projection(batch_id)
                if mean is None:
                    accrual.unknown = True
                    break
                accrual.projected_at, accrual.projected_at_assumed = mean, at_assumed
                value = max(mean, ZERO)
                if not backward and needed is not None:
                    self._project_rest(accrual, day, value, needed, None if days is None else days - walked)
                    break
                accrual.days[PROJECTED] += 1
            else:
                value = max(counted.value, ZERO)
                accrual.days[counted.how] += 1
                accrual.counted += value
            accrual.total += value
            accrual.last, walked = day, walked + 1
            if needed is not None and accrual.total >= needed:
                accrual.reached = day
            day += step
        return accrual

    @staticmethod
    def _project_rest(accrual, day, value, needed, left):
        """A forward walk's projected days from `day` on, all at `value`, at once: as many as reach `needed`, at most
        `left` (None: no bound); none reach it at 0 °C (`unreachable`)."""
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


def capped_sentence(count):
    """The sentence that says how many past days without a measurement were counted below the species' assumed
    temperature, at the coldest day measured before them."""
    return ngettext(
        '%(count)d day without a measured water temperature is counted at the coldest daily mean measured in the '
        '%(days)d days before it, below the species’ assumed temperature.',
        '%(count)d days without a measured water temperature are counted at the coldest daily mean measured in the '
        '%(days)d days before each, below the species’ assumed temperature.', count) % {'count': count,
                                                                                        'days': CAP_DAYS}


def projected_sentence(assumed):
    """The sentence that says a projection was made at the species' assumed temperature, nothing having been
    measured lately."""
    return _('Projected at the assumed %(temperature)s °C (the species’ setting in Reference data): no water '
             'temperature was measured in the last %(days)d days.') % {'temperature': _plain(assumed),
                                                                       'days': LOOKBACK_DAYS}


def accrual_text(accrual):
    """What every reader that adds degrees up says of them: how many days came from each source ("Days counted: 5 days
    measured by the sensors, 2 days from water samples, 1 day without a measurement, 3 days projected."), then how the
    days without a measurement were counted, and that the sensors could not be read when they could not. '' for no
    accrual."""
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
        (ngettext('%(count)d day projected', '%(count)d days projected', days[PROJECTED]), days[PROJECTED]),
    ) if count]
    sentences = [_('Days counted: %(parts)s.') % {'parts': ', '.join(parts)}] if parts else []
    if days[ASSUMED] or days[NOTHING]:
        sentences.append(missing_sentence(days[ASSUMED] + days[NOTHING], accrual.assumed))
    if days[CAPPED]:
        sentences.append(capped_sentence(days[CAPPED]))
    if accrual.sensors_failed:
        sentences.append(_('The sensors could not be read: their days are counted from the water samples or the '
                           'assumed temperature.'))
    return ' '.join(sentences)

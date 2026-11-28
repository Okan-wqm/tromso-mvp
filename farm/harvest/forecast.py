"""The production plan of a batch in a unit: the feeding protocols' estimate now walked forward a day at a time, the
measured weights beside it, and the plan as it was from any measured point. Computed on read, nothing stored
(harvest.md §3.6; the owner's requirement of 2026-11-26).

- The start is today's estimated average (farm/feeding/projection.py: the estimate from the last measured point,
  after today's feedings), or, for "where the plan said we would be", a measured point of the batch's stay in the
  unit (its stocking, a weighing): the weight and the fish measured then. A plan from a past start is the plan as it
  stood that day (owner decision 12 as decided after review 1): the assignments, their protocols' tables, the
  temperature profiles and the planned harvests and transports (their fasts) each as recorded by the end of that day,
  found by its id (read.as_recorded, core.versions: never by a name), and the temperature measured by then, held;
  nothing measured, assigned or planned since leaks into it, and no day's sensor values are read.
- Each day ahead reads the ration's basis of that day at the weight reached (farm/feeding/ration.py, Policy.basis):
  the protocol in force that day, the band at that weight, its SFR at the temperature, the expected FCR and the uneaten
  share there. The day's ration counts as given, and the fish grow by the one growth rule (farm/feeding/growth.py):
  the feed given less the uneaten share, ÷ the FCR. Feed above the ration is never growth (owner decision Q4), and
  past days are not planned: the estimate between weighings grows on recorded feedings only.
- The temperature of a day ahead is the temperature profile's in force for the batch in the unit that day, at the
  fish's projected weight (decisions 15-17: resolved as a protocol is, so after a grading each part reads its own);
  without a profile, the unit's latest measured temperature, held (from a past start: the latest measured by then).
  Each day says which (its `temperature_from`), and a temperature held that is not fresh says how old it is.
- The expected mortality a month of the band (else the protocol's, else none) lowers the fish, so the biomass and the
  feed, never the average weight.
- A fasting day ahead (a planned harvest or transport, farm/handling/fasting.py) gives no feed and no growth.
- No protocol, a weight outside its bands, no temperature or one outside its table stops the walk: the page shows
  the basis's reason, never a default. The platform owner's horizon (core.platform.plan_horizon_days) stops it too."""
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.utils import formats
from django.utils.translation import gettext as _

from core import platform
from farm.feeding import growth, ration, read as feeding_read
from farm.feeding.fold import PointKind
from farm.stock.dates import end_of, local_today

HUNDRED = Decimal(100)
WEEK = 7


@dataclass(frozen=True)
class Forecast:
    """The plan of a batch in a unit from `start`: the average and the fish then, the curve ahead (None when no target
    asked for one), the temperature profiles its days read (`profiles`, in the order first read) and the measured
    temperature held on the days without one (`held`)."""
    now_g: Decimal
    fish: Decimal = None
    start: date = None
    curve: growth.Curve = None
    profiles: tuple = ()
    horizon_days: int = None
    held: object = None           # the temperature held (feeding.temperature.Temperature), with its age: never silent
    protocols: tuple = ()         # the feeding protocols its days read, in the order first read
    as_recorded: bool = False     # a plan from a past start: as it stood that day

    @property
    def stale(self):
        """What to say when the temperature held is not fresh ('' when it is, or when none is held)."""
        return self.held.warning if self.held is not None and self.planned else ''

    @property
    def day(self):
        """The day the target is reached; None when it is not, or when there is no target."""
        return self.curve.reached if self.curve is not None else None

    @property
    def reached(self):
        return self.day is not None

    @property
    def temperature_c(self):
        """The measured temperature held over the days ahead without a profile; None when every day had one."""
        return self.held.value_c if self.held is not None else None

    @property
    def why(self):
        """Why the target is not reached, as the page says it; '' when it is, or when there is no target."""
        if self.curve is None or self.curve.reached is not None:
            return ''
        if self.curve.why:
            return self.curve.why
        if self.curve.target_g is None:
            return ''
        return _('Not reached within %(days)d days at this rate.') % {'days': self.horizon_days}

    @property
    def planned(self):
        """Whether a day ahead was planned at all: there is feed and an economic FCR to say."""
        return self.curve is not None and bool(self.curve.points)

    def weight_on(self, day):
        """The planned average on `day`: the start's own on the start, a planned day's, else None."""
        if self.curve is None:
            return None
        if day == self.start:
            return self.now_g
        return next((point.weight_g for point in self.curve.points if point.day == day), None)

    def weekly(self):
        """The curve's days a week apart from the start, and its last day."""
        points = self.curve.points if self.curve is not None else ()
        return [point for index, point in enumerate(points, start=1) if index % WEEK == 0 or index == len(points)]


def _ahead(policy, unit, batch, start, weight_g, fish, target_g, horizon_days, today):
    """The Forecast from `start`, where the fish weigh `weight_g` and number `fish`. Each day's terms are the policy's
    basis of that day (ration.Policy.basis: the protocol in force, the band, the SFR, the fast a planned harvest or
    transport asks, read with the walk's own reads) at the day's temperature: the temperature profile in force at the
    weight reached (Policy.planned_temperature); without one, from today the unit's own as the ration reads it (its
    latest, held), and from a past start the latest measured by the end of that day, held. A past start reads no
    temperature of a later day: with none measured by then and no profile, its plan stops and says so."""
    past = start < today
    then = policy.temperature(unit.pk, start) if past else None
    held, profiles, protocols = [], [], []

    def terms_of(day, weight):
        planned = policy.planned_temperature(unit.pk, batch.pk, day, weight)
        if isinstance(planned, ration.ProfileGap):
            return growth.Stop(planned.why())
        if planned is not None:
            basis = policy.basis(unit.pk, batch.pk, day, weight, temperature=planned)
        elif past:
            # the temperature measured by then (None: no reading of a later day is ever asked instead)
            basis = policy.basis(unit.pk, batch.pk, day, weight, temperature=then)
            if basis.missing == ration.NO_TEMPERATURE:
                return growth.Stop(_('No temperature had been measured here by %(date)s, and no temperature profile '
                                     'applies: the plan as it stood then has none to read.') % {
                    'date': formats.date_format(start, 'DATE_FORMAT')})
        else:
            basis = policy.basis(unit.pk, batch.pk, day, weight)
        if basis.protocol is not None and basis.protocol not in protocols:
            protocols.append(basis.protocol)
        if basis.missing == ration.FASTING:
            return growth.Terms(mortality_pct_month=basis.mortality_pct_month, fasting=True)
        if not basis.has_ration or basis.fcr is None:
            return growth.Stop(basis.why(batch))
        if planned is None and not held:
            held.append(basis.temperature)
        if planned is not None and planned.profile not in profiles:
            profiles.append(planned.profile)
        return growth.Terms(basis.sfr.value, basis.fcr, basis.uneaten_pct, basis.mortality_pct_month,
                            basis.temperature.value_c, temperature_from=planned.profile if planned else None)

    curve = growth.curve(start, weight_g, Decimal(fish), target_g, horizon_days, terms_of)
    return Forecast(weight_g, Decimal(fish), start, curve, tuple(profiles), horizon_days, held[0] if held else None,
                    tuple(protocols), past)


def forecasts(shares, targets):
    """{(unit id, batch id): Forecast} of the shares ((unit, stock.read BatchShare) pairs): the estimate now, and,
    for a batch with a target (`targets`: batch id -> grams), the plan ahead to it. One projection walk for all."""
    wanted = list(shares)
    if not wanted:
        return {}
    today = {unit.pk: local_today(unit) for unit, _share in wanted}
    horizon_days = platform.plan_horizon_days()
    # one walk, its policy reading the fasts of the days ahead too (one read of the planned harvests and transports)
    projection = feeding_read.project(list(today), [(unit_id, day) for unit_id, day in today.items()],
                                      ahead_days=horizon_days)
    found = {}
    for unit, share in wanted:
        estimate = _estimate(projection, unit, share.batch, today[unit.pk])
        if estimate is None:
            continue
        target = targets.get(share.batch.pk)
        found[(unit.pk, share.batch.pk)] = (
            Forecast(estimate.end_g, Decimal(share.count), today[unit.pk]) if target is None else
            _ahead(projection.projector.policy, unit, share.batch, today[unit.pk], estimate.end_g, share.count,
                   target, horizon_days, today[unit.pk]))
    return found


def _estimate(projection, unit, batch, day):
    unit_day = projection.days.get((unit.pk, day))
    return next((item for item in (unit_day.shares if unit_day else []) if item.batch_id == batch.pk), None)


@dataclass(frozen=True)
class Against:
    """A measured point beside the plan: what the plan from the chosen start said for that day (None on or before the
    start, or past the plan's end), and the measured weight's difference from it."""
    point: object                 # feeding.read.Measured
    planned_g: Decimal = None

    @property
    def difference_g(self):
        return None if self.planned_g is None else self.point.avg_weight_g - self.planned_g

    @property
    def difference_pct(self):
        return HUNDRED * self.difference_g / self.planned_g if self.planned_g else None


@dataclass(frozen=True)
class Plan:
    """A batch in a unit as its plan page shows it: the plan from the chosen start (`chosen`: a measured point, None:
    today's estimate), the measured points of its stay each beside that plan, and today."""
    forecast: Forecast
    measured: tuple               # Against, oldest first
    chosen: object = None
    today: date = None
    batch: object = None


def plan(unit, share, target_g, start_day=None, horizon_days=None):
    """The Plan of a batch in stock in a unit (`share`: its stock.read BatchShare there), from today's estimate or,
    with `start_day`, from the measured point of that day as the plan stood then (a day that is none is today's
    estimate: a stale link shows the plan there is). `horizon_days`: the platform owner's when not given. Without a
    target the curve runs the whole horizon. None when the batch has no estimate (no fish in the unit today)."""
    batch, today = share.batch, local_today(unit)
    # a start is a measured point of the stay: a day outside it is never read (an address is typed by anyone)
    within = start_day is not None and share.since <= start_day < today
    asked = [(unit.pk, today)] + ([(unit.pk, start_day)] if within else [])
    horizon_days = platform.plan_horizon_days() if horizon_days is None else horizon_days
    projection = feeding_read.project([unit.pk], asked, ahead_days=horizon_days)
    estimate = _estimate(projection, unit, batch, today)
    if estimate is None:
        return None
    points = feeding_read.measured_points(projection, unit.pk, batch.pk)
    chosen = next((point for point in points if point.day == start_day and point.kind != PointKind.CLOSE), None)
    start = chosen.day if chosen is not None else today
    policy = projection.projector.policy
    if chosen is None:
        forecast = _ahead(policy, unit, batch, today, estimate.end_g, share.count, target_g, horizon_days, today)
    else:
        recorded = _as_recorded(policy, unit, batch, chosen.day, horizon_days)
        forecast = _ahead(recorded, unit, batch, chosen.day, chosen.avg_weight_g, chosen.fish, target_g, horizon_days,
                          today)
    return Plan(forecast, tuple(Against(point, forecast.weight_on(point.day) if point.day > start else None)
                                for point in points), chosen, today, batch)




def plan_of(unit, batch_id, start_day=None, horizon_days=None):
    """The Plan of the batch `batch_id` in `unit` (a Tank with its site), with its production plan's target; None when
    the batch has no fish in the unit today. What the growth plan page and the service both read."""
    from farm.models import ProductionPlan
    from farm.stock import read as stock_read
    stock = stock_read.stock_of([unit]).get(unit.pk)
    share = next((each for each in (stock.counted if stock is not None else ()) if each.batch.pk == batch_id), None)
    if share is None:
        return None
    target = ProductionPlan.objects.filter(batch=share.batch).first()
    return plan(unit, share, target.target_weight_g if target is not None else None, start_day, horizon_days)


def _as_recorded(policy, unit, batch, day, horizon_days):
    """The policy of the plan from a past `day`: the protocols' and the profiles' rows of the unit and the batch, their
    tables and profiles, and the fasts the plans of the unit asked over the plan's days, every row as it was recorded
    by the end of that day (read.as_recorded: by its id, core.versions)."""
    return policy.recorded(**feeding_read.as_recorded({unit.pk: unit}, [batch.pk], day,
                                                      day + timedelta(days=horizon_days), end_of(day, unit)))


# ---- the projection as a service (owner decision 20) ------------------------------------------------------------
class ProjectionError(ValueError):
    """An id a service gave that names no unit or batch: said, never a silent None."""


def _uuid(value, what):
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise ProjectionError(f'{what} must be a UUID: {value!r}') from None


def _plain(value):
    return value.name if hasattr(value, 'name') else value


def projection(unit_id, batch_id, start_day=None, horizon_days=None):
    """THE projection of a batch in a unit, as a service asks it (owner decision 20): the planning tools, and later the
    AI agents, which interpret and propose but never write a plan. It reads and writes nothing (a test holds that only
    SELECTs run). In: the unit's and the batch's ids (a UUID or its text: anything else is a ProjectionError), a start
    day (a measured point of the batch's stay there, the plan as it stood then; None: today's estimate) and a horizon
    in days (None: the platform owner's). The target is the batch's production plan's (none: the whole horizon).

    Out: None when the batch has no fish in the unit today; else a dict of plain values only (text, numbers as Decimal,
    dates, lists and dicts; no record of the database), its keys pinned by a test:
      unit_id, unit, batch_id, batch (ids as text, codes), start_day, start_weight_g, start_fish, horizon_days,
      as_recorded (the plan as it stood on a past start), target_g, target_day, why (why the target is not reached),
      feed_kg, eaten_kg, uneaten_kg, fcr_on_feed_given, economic_fcr, protocols, temperature_profiles (names),
      temperature_held_c, days (a dict per day ahead: day, weight_g, fish, biomass_kg, feed_kg, eaten_kg, uneaten_kg,
      growth_kg, feed_to_date_kg, fcr, uneaten_pct, temperature_c, temperature_source (a profile's name, None: the
      measured temperature held), fasting), measured (a dict per measured point: day, kind, fish, weight_g, source,
      sample_count, sample_weight_kg, planned_g, difference_g).
    The numbers come from one pure function (growth.curve) fed the day's terms by the ration's policy."""
    unit_id, batch_id = _uuid(unit_id, 'unit_id'), _uuid(batch_id, 'batch_id')
    if horizon_days is not None and (not isinstance(horizon_days, int) or horizon_days < 0):
        raise ProjectionError(f'horizon_days must be a whole number of days, 0 or more: {horizon_days!r}')
    from farm.models import Tank
    unit = Tank.objects.select_related('production_department__site').filter(pk=unit_id).first()
    if unit is None:
        raise ProjectionError(f'No unit {unit_id}.')
    found = plan_of(unit, batch_id, start_day, horizon_days)
    if found is None:
        return None
    share_batch = found.batch
    forecast, curve = found.forecast, found.forecast.curve
    return {
        'unit_id': str(unit.pk), 'unit': unit.code, 'batch_id': str(share_batch.pk), 'batch': share_batch.code,
        'start_day': forecast.start, 'start_weight_g': forecast.now_g, 'start_fish': forecast.fish,
        'horizon_days': forecast.horizon_days, 'as_recorded': forecast.as_recorded, 'target_g': curve.target_g,
        'target_day': forecast.day, 'why': str(forecast.why), 'feed_kg': curve.feed_kg, 'eaten_kg': curve.eaten_kg,
        'uneaten_kg': curve.uneaten_kg, 'fcr_on_feed_given': curve.fcr_on_feed_given,
        'economic_fcr': curve.economic_fcr, 'protocols': [each.name for each in forecast.protocols],
        'temperature_profiles': [each.name for each in forecast.profiles],
        'temperature_held_c': forecast.temperature_c,
        'days': [{'day': point.day, 'weight_g': point.weight_g, 'fish': point.fish, 'biomass_kg': point.biomass_kg,
                  'feed_kg': point.feed_kg, 'eaten_kg': point.eaten_kg, 'uneaten_kg': point.uneaten_kg,
                  'growth_kg': point.growth_kg, 'feed_to_date_kg': point.feed_to_date_kg, 'fcr': point.fcr,
                  'uneaten_pct': point.uneaten_pct, 'temperature_c': point.temperature_c,
                  'temperature_source': _plain(point.temperature_from), 'fasting': point.fasting}
                 for point in curve.points],
        'measured': [{'day': item.point.day, 'kind': item.point.kind, 'fish': item.point.fish,
                      'weight_g': item.point.avg_weight_g, 'source': _plain(item.point.source),
                      'sample_count': item.point.sample_count, 'sample_weight_kg': item.point.sample_weight_kg,
                      'planned_g': item.planned_g, 'difference_g': item.difference_g} for item in found.measured],
    }

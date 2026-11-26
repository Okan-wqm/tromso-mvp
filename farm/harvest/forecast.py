"""The production plan of a batch in a unit: the feeding protocols' estimate now walked forward a day at a time, the
measured weights beside it, and the plan as it was from any measured point. Computed on read, nothing stored
(harvest.md §3.6; the owner's requirement of 2026-11-26).

- The start is today's estimated average (farm/feeding/projection.py: the estimate from the last measured point,
  after today's feedings), or, for "where the plan said we would be", a measured point of the batch's stay in the
  unit (its stocking, a weighing): the weight and the fish measured then.
- Each day ahead reads the ration's basis of that day at the weight reached (farm/feeding/ration.py, Policy.basis):
  the protocol in force that day, the band at that weight, its SFR at the temperature, the expected FCR and the uneaten
  share there. The day's ration counts as given, and the fish grow by the one growth rule (farm/feeding/growth.py):
  the feed given less the uneaten share, ÷ the FCR. Feed above the ration is never growth (owner decision Q4), and
  past days are not planned: the estimate between weighings grows on recorded feedings only.
- The temperature ahead is the site's water temperature of the day's month when the site has its twelve (Setup ›
  Sites), else the unit's latest usable one at the start, held constant. The page says which.
- The expected mortality a month of the band (else the protocol's, else none) lowers the fish, so the biomass and the
  feed, never the average weight.
- A fasting day ahead (a planned harvest or transport, farm/handling/fasting.py) gives no feed and no growth.
- No protocol, a weight outside its bands, no temperature or one outside its table stops the walk: the page shows
  the basis's reason, never a default. The platform owner's horizon (core.platform.plan_horizon_days) stops it too."""
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.utils.translation import gettext as _

from core import platform
from farm.feeding import growth, read as feeding_read
from farm.feeding.fold import PointKind
from farm.feeding.ration import PlannedTemperature
from farm.handling import fasting
from farm.stock.dates import local_today

HUNDRED = Decimal(100)
WEEK = 7


@dataclass(frozen=True)
class Forecast:
    """The plan of a batch in a unit from `start`: the average and the fish then, the curve ahead (None when no target
    asked for one) and what its temperature was read from (`monthly`: the site's months; else held)."""
    now_g: Decimal
    fish: Decimal = None
    start: date = None
    curve: growth.Curve = None
    monthly: bool = False
    horizon_days: int = None

    @property
    def day(self):
        """The day the target is reached; None when it is not, or when there is no target."""
        return self.curve.reached if self.curve is not None else None

    @property
    def reached(self):
        return self.day is not None

    @property
    def temperature_c(self):
        """The temperature held over the days ahead; None when the site's months were read, or no day was planned."""
        return None if self.curve is None or self.monthly else self.curve.temperature_c

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


def _ahead(policy, unit, batch, start, weight_g, fish, target_g, horizon_days, fasts):
    """The Forecast from `start`, where the fish weigh `weight_g` and number `fish`."""
    site = unit.production_department.site
    monthly = site.plan_temperatures() if site is not None else None
    held = None if monthly else policy.temperature(unit.pk, start)

    def terms_of(day, weight):
        temperature = PlannedTemperature(monthly[day.month - 1]) if monthly else held
        basis = policy.basis(unit.pk, batch.pk, day, weight, temperature=temperature)
        if (unit.pk, day) in fasts:
            return growth.Terms(mortality_pct_month=basis.mortality_pct_month, fasting=True)
        if not basis.has_ration or basis.fcr is None:
            return growth.Stop(basis.why(batch))
        return growth.Terms(basis.sfr.value, basis.fcr, basis.uneaten_pct, basis.mortality_pct_month,
                            temperature.value_c)

    curve = growth.curve(start, weight_g, Decimal(fish), target_g, horizon_days, terms_of)
    return Forecast(weight_g, Decimal(fish), start, curve, bool(monthly), horizon_days)


def forecasts(shares, targets):
    """{(unit id, batch id): Forecast} of the shares ((unit, stock.read BatchShare) pairs): the estimate now, and,
    for a batch with a target (`targets`: batch id -> grams), the plan ahead to it. One projection walk for all."""
    wanted = list(shares)
    if not wanted:
        return {}
    today = {unit.pk: local_today(unit) for unit, _share in wanted}
    projection = feeding_read.project(list(today), [(unit_id, day) for unit_id, day in today.items()])
    units = list({unit.pk: unit for unit, _share in wanted}.values())
    horizon_days = platform.plan_horizon_days()
    fasts = fasting.fasts(units, min(today.values()), max(today.values()) + timedelta(days=horizon_days))
    found = {}
    for unit, share in wanted:
        estimate = _estimate(projection, unit, share.batch, today[unit.pk])
        if estimate is None:
            continue
        target = targets.get(share.batch.pk)
        found[(unit.pk, share.batch.pk)] = (
            Forecast(estimate.end_g, Decimal(share.count), today[unit.pk]) if target is None else
            _ahead(projection.projector.policy, unit, share.batch, today[unit.pk], estimate.end_g, share.count,
                   target, horizon_days, fasts))
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


def plan(unit, share, target_g, start_day=None):
    """The Plan of a batch in stock in a unit (`share`: its stock.read BatchShare there), from today's estimate or,
    with `start_day`, from the measured point of that day (a day that is none is today's estimate: a stale link shows
    the plan there is). Without a target the curve runs the whole horizon. None when the batch has no estimate (no
    fish in the unit today)."""
    batch, today = share.batch, local_today(unit)
    # a start is a measured point of the stay: a day outside it is never read (an address is typed by anyone)
    within = start_day is not None and share.since <= start_day < today
    asked = [(unit.pk, today)] + ([(unit.pk, start_day)] if within else [])
    projection = feeding_read.project([unit.pk], asked)
    estimate = _estimate(projection, unit, batch, today)
    if estimate is None:
        return None
    points = feeding_read.measured_points(projection, unit.pk, batch.pk)
    chosen = next((point for point in points if point.day == start_day and point.kind != PointKind.CLOSE), None)
    horizon_days = platform.plan_horizon_days()
    start = chosen.day if chosen is not None else today
    fasts = fasting.fasts([unit], start, max(start, today) + timedelta(days=horizon_days))
    policy = projection.projector.policy
    if chosen is None:
        forecast = _ahead(policy, unit, batch, today, estimate.end_g, share.count, target_g, horizon_days, fasts)
    else:
        forecast = _ahead(policy, unit, batch, chosen.day, chosen.avg_weight_g, chosen.fish, target_g, horizon_days,
                          fasts)
    return Plan(forecast, tuple(Against(point, forecast.weight_on(point.day) if point.day > start else None)
                                for point in points), chosen, today)

"""How feed becomes growth: the one rule of the estimated weight between weighings (farm/feeding/projection.py) and of
the plan ahead (farm/harvest/forecast.py). Pure: no database, no clock, no settings; every input is a plain value, so
the rule is tested on its own, exhaustively (farm/tests/test_growth.py). Nothing else in the code turns feed into
weight.

- `step(feed, fcr, uneaten_pct)`: of the feed given, the uneaten share is not eaten; the fish grow by the feed eaten
  ÷ the FCR. The FCR is the biological one (on feed eaten); the economic one (on feed given) is
  `economic_fcr(fcr, uneaten_pct)` = FCR ÷ (1 − uneaten), computed and shown, never entered.
- `interpolate(anchors, at)`: a value that changes over the fish's weight without a jump. Each band's value sits at
  the band's anchor weight (`anchor`: the middle of the band; a band without an upper weight has no middle, so its
  lower weight); between two neighbouring anchors the value is linear, before the first and after the last it is
  constant. Used for the FCR and for the uneaten share, and by nothing else: the SFR keeps its own rule (the band's
  row, interpolated over the temperature: farm/feeding/ration.py).
- `survival_a_day(mortality_pct_month)`: the share of the fish still alive after a day at an expected mortality in %
  a month (30 days, compounded: after 30 days exactly that share has died). Mortality lowers the count, never the
  average weight: the fish that die are taken to weigh the average.
- `curve(...)`: the plan ahead, a day at a time, from today's estimate: every day's ration counts as given.

The arithmetic uses only the inputs' own number type and whole numbers, so exact types (Decimal, Fraction) stay exact:
with no uneaten feed a step is feed ÷ FCR to the last digit."""
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

MONTH_DAYS = 30


@dataclass(frozen=True)
class Step:
    """Feed given and what became of it, all in the feed's own unit: eaten + uneaten = given, growth = eaten ÷ FCR."""
    given: object
    eaten: object
    uneaten: object
    growth: object


def step(feed, fcr, uneaten_pct=0):
    """The growth `feed` gives at the biological `fcr` when `uneaten_pct` % of it is not eaten."""
    eaten = feed * (100 - uneaten_pct) / 100
    return Step(feed, eaten, feed - eaten, eaten / fcr)


def economic_fcr(fcr, uneaten_pct=0):
    """Feed given per growth: the biological FCR ÷ the share eaten."""
    return fcr * 100 / (100 - uneaten_pct)


def anchor(lower, upper):
    """The weight a band's value sits at: its middle, or its lower weight when it has no upper one."""
    return lower if upper is None else (lower + upper) / 2


def interpolate(anchors, at):
    """The value at `at` of `anchors` ((weight, value) pairs in weight order, at least one): linear between two
    neighbours, the first value before the first and the last after the last."""
    first_at, first = anchors[0]
    if at <= first_at:
        return first
    for (low_at, low), (high_at, high) in zip(anchors, anchors[1:]):
        if at == high_at:
            return high
        if at < high_at:
            return low + (high - low) * (at - low_at) / (high_at - low_at)
    return anchors[-1][1]


def survival_a_day(mortality_pct_month):
    """The share of the fish alive after one day; 1 without an expected mortality."""
    if not mortality_pct_month:
        return Decimal(1)
    return (1 - Decimal(mortality_pct_month) / 100) ** (Decimal(1) / MONTH_DAYS)


# ---- the plan ahead ---------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Terms:
    """What a day ahead rests on: the SFR (% of the body weight a day), the biological FCR and the uneaten share at the
    fish's weight, the expected mortality (None: none) and the temperature the SFR was read at. `fasting`: no feed
    that day, so no growth (the other terms but the mortality are not read)."""
    sfr_pct: object = 0
    fcr: object = None
    uneaten_pct: object = 0
    mortality_pct_month: object = None
    temperature_c: object = None
    fasting: bool = False


@dataclass(frozen=True)
class Stop:
    """Why the plan cannot go past a day (no protocol, a weight outside the bands, no temperature)."""
    why: str


@dataclass(frozen=True)
class Point:
    """A day ahead: the average weight and the fish at its end, and the day's feed for the fish alive at its start."""
    day: date
    weight_g: object
    fish: object
    feed_kg: object
    eaten_kg: object
    uneaten_kg: object
    growth_kg: object
    feed_to_date_kg: object
    fcr: object = None
    uneaten_pct: object = 0
    temperature_c: object = None
    fasting: bool = False

    @property
    def biomass_kg(self):
        return self.weight_g * self.fish / 1000


@dataclass(frozen=True)
class Curve:
    """The plan ahead of a batch in a unit from `start` (the estimate that day): a Point per day; `reached`, the day
    the target is reached (the start itself when the fish are there already), or `why` it is not."""
    start: date
    start_g: object
    start_fish: object
    target_g: object = None
    points: tuple = ()
    reached: date = None
    why: str = ''
    horizon: bool = False         # the plan ran its whole horizon (`why` says so when a target was not reached)

    def _sum(self, name):
        return sum((getattr(point, name) for point in self.points), 0)

    @property
    def feed_kg(self):
        """The feed given over the whole curve: to the target when it is reached."""
        return self._sum('feed_kg')

    @property
    def eaten_kg(self):
        return self._sum('eaten_kg')

    @property
    def uneaten_kg(self):
        return self._sum('uneaten_kg')

    @property
    def growth_kg(self):
        return self._sum('growth_kg')

    @property
    def economic_fcr(self):
        """Feed given ÷ growth over the whole curve; None when nothing grew."""
        growth = self.growth_kg
        return self.feed_kg / growth if growth else None

    @property
    def end_g(self):
        return self.points[-1].weight_g if self.points else self.start_g

    @property
    def end_fish(self):
        return self.points[-1].fish if self.points else self.start_fish

    @property
    def temperature_c(self):
        """The temperature of the last day fed (the one the page names when it is held)."""
        return next((point.temperature_c for point in reversed(self.points) if not point.fasting), None)


def curve(start, weight_g, fish, target_g, horizon_days, terms_of):
    """The plan ahead from `start`, where the fish weigh `weight_g` on average and number `fish`: each day ahead the
    fish alive are given the day's ration (weight × SFR ÷ 100 each), grow by `step`, and the expected mortality takes
    its share of the count at the day's end. `terms_of(day, weight_g)` gives the day's Terms at the weight reached, or
    a Stop. It ends on the day the weight reaches `target_g` (None: no target), at a Stop (`why`), or after
    `horizon_days` days (`horizon`)."""
    start_g, start_fish = weight_g, fish
    day, points, to_date = start, [], 0

    def ended(**how):
        return Curve(start, start_g, start_fish, target_g, tuple(points), **how)

    for ahead in range(horizon_days + 1):
        if target_g is not None and weight_g >= target_g:
            return ended(reached=day)
        if ahead == horizon_days:
            break
        day += timedelta(days=1)
        terms = terms_of(day, weight_g)
        if isinstance(terms, Stop):
            return ended(why=terms.why)
        if terms.fasting:
            fed, fcr, uneaten_pct = step(weight_g * 0, 1), None, 0             # nothing, in the weight's own number type
        else:
            fcr, uneaten_pct = terms.fcr, terms.uneaten_pct
            fed = step(weight_g * terms.sfr_pct / 100, fcr, uneaten_pct)       # grams a fish
        to_date += fed.given * fish / 1000                                     # kg of all the fish alive
        weight_g += fed.growth
        alive = fish * survival_a_day(terms.mortality_pct_month)
        points.append(Point(day, weight_g, alive, fed.given * fish / 1000, fed.eaten * fish / 1000,
                            fed.uneaten * fish / 1000, fed.growth * fish / 1000, to_date, fcr, uneaten_pct,
                            terms.temperature_c, terms.fasting))
        fish = alive
    return ended(horizon=True)

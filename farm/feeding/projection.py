"""The fish's estimated weight between weighings and the day's ration it gives (owner requirement 2; feeding-protocols
§6.6 with owner decisions Q4, Q7 and Q9). A track of its own beside the measured book, kept by the feeding walk
(farm/feeding/fold.py calls a Projector at every stock line, measured point and feeding day) and never written back:
bFCR, eFCR, density, capacity and the feeding acknowledgement read the measured book only, so the source's loop of
rations sized on biomass that feed itself raised (FP-01) cannot happen.

- The estimate restarts at the measured value at every measured point: a stocking, a weighing (a grading's remainder
  too) and fish graded into a unit where the batch had none.
- Fish that leave (mortality, cull, harvest, transfer out, a count adjusted down) take the estimate's own average, so
  the estimated average does not move when fish leave; fish moved by a plain transfer carry their estimated grams and
  the day of their last measured point into the unit they go to; graded fish carry their measured weight.
- After each feeding of the day (in their order: time, then entry), the batch gains what its part of the feed grows
  by the one growth rule (farm/feeding/growth.py, `step`): the part eaten (the feed less the protocol's uneaten
  share) ÷ the expected FCR, both read at its estimated weight then (Q7, Q9; ration.Basis), but only up to the day's
  calculated ration (Q4): feed above it is "over the ration" and not growth. The next meal is read at the new
  estimate. A day without a recorded feeding adds nothing: only the plan ahead (farm/harvest/forecast.py) counts a
  ration as given.
- A feeding of fish without an expected FCR (no protocol, a weight outside its bands) adds nothing and is counted:
  the estimate is incomplete for that many feeding days, and the pages say so. Never a default FCR. Cleaner fish
  without a feeding table of their own beside production fish (ration.CLEANER_FISH) are not modelled at all: their
  estimate stays at the measured weight and their feedings are no gap; alone in a unit they are its production fish.

The day's calculated ration follows the same rule: with M meals a day in the band and R the ration at the estimate
(farm/feeding/ration.py), each recorded meal counts R ÷ M at the estimate just before it (a record's meals, or one
when it does not say, counted up to M), and the meals still to come count R ÷ M at the current estimate. The next meal
is R ÷ M at the current estimate (the owner's rule: "as soon as it is fed, the next meal is computed again").

A weighing is a correction point: just before it resets the estimate, the walk keeps the estimated and the measured
average, the days since the previous measured point, the realised bFCR between that point and this one (the window
rule of farm/feeding/read.py) and the expected FCR of the feed given meanwhile, on feed given as the realised one is
(Σ feed ÷ Σ expected growth: the economic FCR, equal to the entered one when nothing is left uneaten)."""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from farm.models.feeding import FeedTarget
from farm.models.stock import MovementKind, OperationKind

from . import growth
from .fold import PointKind, Window

ZERO = Decimal(0)
HUNDRED = Decimal(100)


@dataclass
class Track:
    """A batch's estimated grams in a unit, the day of the measured point they run from, and the feed since then:
    the feed with an expected FCR and Σ feed ÷ FCR (their ratio is the interval's expected FCR), and the feeding days
    without one."""
    grams: Decimal = ZERO
    measured_on: date = None
    feed_kg: Decimal = ZERO
    feed_per_fcr: Decimal = ZERO
    blind_days: set = field(default_factory=set)

    @property
    def expected_fcr(self):
        return self.feed_kg / self.feed_per_fcr if self.feed_per_fcr else None

    def part(self, grams, share):
        """The track of some of its fish, `share` of them, weighing `grams`."""
        return Track(grams, self.measured_on, self.feed_kg * share, self.feed_per_fcr * share, set(self.blind_days))

    def merge(self, other):
        """Fish of another track join this one; the older measured point is the estimate's age."""
        self.grams += other.grams
        if other.measured_on is not None and (self.measured_on is None or other.measured_on < self.measured_on):
            self.measured_on = other.measured_on
        self.feed_kg += other.feed_kg
        self.feed_per_fcr += other.feed_per_fcr
        self.blind_days |= other.blind_days


@dataclass(frozen=True)
class Correction:
    """A weighing compared with the estimate it replaces: what the fish were estimated at and what they weighed, the
    expected FCR of the feed since the previous measured point and the realised bFCR between the two points (None
    when the previous point is in another unit: fish moved in by a plain transfer)."""
    unit_id: object
    batch_id: object
    day: date
    fish: int
    estimated_g: Decimal
    measured_g: Decimal
    since: date
    expected_fcr: Decimal
    blind_days: int
    window: Window = None

    @property
    def difference_g(self):
        """Measured − estimated: below 0 when the fish weighed less than estimated."""
        return self.measured_g - self.estimated_g

    @property
    def difference_kg(self):
        return self.difference_g * self.fish / 1000

    @property
    def difference_pct(self):
        return HUNDRED * self.difference_g / self.estimated_g if self.estimated_g else None

    @property
    def days(self):
        return (self.day - self.since).days if self.since else None

    @property
    def realised_fcr(self):
        return self.window.biological if self.window is not None else None


@dataclass
class ShareDay:
    """A batch in a unit on a day: its fish at the end of the day, its measured and estimated average, the basis of
    its ration at the start of the day's feeding and now (ration.Basis), and its feeding that day."""
    batch_id: object
    fish: int
    measured_g: Decimal
    last_weighed: date
    start_g: Decimal
    end_g: Decimal
    measured_on: date
    blind_days: int
    start: object
    end: object
    grams: Decimal = ZERO          # the estimated grams of its fish now
    fed_kg: Decimal = ZERO
    credited_kg: Decimal = ZERO
    meals: int = 0                # recorded meals counted toward the band's meals
    portions_kg: Decimal = ZERO   # what those meals count in the calculated ration
    fed_since_kg: Decimal = ZERO  # the feed with an expected FCR since its measured point, its fish's part: 0 when the
    #                               estimate is still the measured weight

    @property
    def biomass_kg(self):
        return self.grams / 1000

    @property
    def ration_kg(self):
        """The day's ration at the current estimate; None when the basis gives none."""
        return self.end.ration_kg(self.biomass_kg) if self.end.has_ration else None

    @property
    def planned_meals(self):
        return self.end.meals

    @property
    def meal_kg(self):
        ration = self.ration_kg
        return ration / self.planned_meals if ration is not None else None

    @property
    def meals_left(self):
        return max(0, self.planned_meals - self.meals) if self.planned_meals else 0

    @property
    def next_meal_kg(self):
        return self.meal_kg if self.meals_left and self.meal_kg is not None else None

    @property
    def remaining_kg(self):
        return self.meals_left * self.meal_kg if self.meal_kg is not None else None

    @property
    def calculated_kg(self):
        """The day's calculated ration: the portions of the meals recorded and the meals to come."""
        remaining = self.remaining_kg
        return self.portions_kg + remaining if remaining is not None else None

    @property
    def over_kg(self):
        """Feed above the ration, not credited as growth."""
        return self.fed_kg - self.credited_kg if self.end.fcr is not None else ZERO


@dataclass
class UnitDay:
    """A unit on a day: its batches (ShareDay) and the feedings recorded. Its totals (fed, meals, the ration) are
    those of its production fish and their feedings: cleaner fish beside them (`cleaner`, their batch ids) have their
    own lines and their own feedings (D-1), so a lumpfish batch without a feeding table leaves the salmon's ration
    alone."""
    unit_id: object
    day: date
    shares: list
    feedings: list
    cleaner: frozenset = frozenset()

    @property
    def production(self):
        return [share for share in self.shares if share.batch_id not in self.cleaner]

    @property
    def production_feedings(self):
        return [feeding for feeding in self.feedings if feeding.target == FeedTarget.PRODUCTION]

    @property
    def fed_kg(self):
        return sum((feeding.amount_kg for feeding in self.production_feedings), ZERO)

    @property
    def meals_done(self):
        """The meals recorded, a record that does not say counting as one."""
        return sum(feeding.meals or 1 for feeding in self.production_feedings)

    def _total(self, name):
        values = [getattr(share, name) for share in self.production]
        if not values or any(value is None for value in values):
            return None
        return sum(values, ZERO)

    @property
    def calculated_kg(self):
        """Σ of the batches' calculated rations; None when one of them has none (the reason is on its line)."""
        return self._total('calculated_kg')

    @property
    def ration_kg(self):
        return self._total('ration_kg')

    @property
    def remaining_kg(self):
        return self._total('remaining_kg')

    @property
    def next_meal_kg(self):
        values = [share.next_meal_kg for share in self.production if share.next_meal_kg is not None]
        return sum(values, ZERO) if values and self.ration_kg is not None else None

    @property
    def deviation_kg(self):
        calculated = self.calculated_kg
        return self.fed_kg - calculated if calculated is not None else None

    @property
    def deviation_pct(self):
        calculated = self.calculated_kg
        return HUNDRED * (self.fed_kg - calculated) / calculated if calculated else None


def feed(track, fish, measured_g, last_weighed, day, parts, basis_of):
    """Credits a batch's feeding of one day to its track, in the day's order, and returns the ShareDay. `parts`:
    [(feeding, kg of it this batch got)]; `basis_of(weight)`: the ration.Basis at an estimated average."""
    start_g = track.grams / fish
    start = basis_of(start_g)
    result = ShareDay(None, fish, measured_g, last_weighed, start_g, start_g, track.measured_on, 0, start, start,
                      track.grams)
    for feeding, part in parts:
        basis = basis_of(track.grams / fish)
        result.fed_kg += part
        if basis.fcr is None:
            if not basis.cleaner_fish:      # cleaner fish without a table of their own are not modelled: no gap
                track.blind_days.add(day)
            continue
        credit = part
        if basis.has_ration:
            ration, meals = basis.ration_kg(track.grams / 1000), basis.meals
            planned = result.portions_kg + max(0, meals - result.meals) * ration / meals
            credit = min(part, max(ZERO, planned - result.credited_kg))
            taken = min(feeding.meals or 1, max(0, meals - result.meals))
            result.portions_kg += taken * ration / meals
            result.meals += taken
        result.credited_kg += credit
        track.grams += growth.step(credit * 1000, basis.fcr, basis.uneaten_pct).growth
        track.feed_kg += part
        # what the feed given was expected to grow: Σ feed ÷ this is the interval's expected FCR on feed given (the
        # economic one), which is what a weighing's realised FCR, also on feed given, is compared with
        track.feed_per_fcr += growth.step(part, basis.fcr, basis.uneaten_pct).growth
    result.grams = track.grams
    result.fed_since_kg = track.feed_kg
    result.end_g = track.grams / fish
    result.end = basis_of(result.end_g)
    result.blind_days = len(track.blind_days)
    return result


class Projector:
    """The estimate of every batch in every unit, kept along the feeding walk (farm/feeding/fold.py, `projector`):
    the walk calls `line` after each stock line, `weighed` at each weighing point and `day` at the end of each day it
    reads. `asked`: the (unit id, day) pairs whose UnitDay is kept (`days`); the corrections are kept per batch in a
    unit, oldest first."""

    def __init__(self, policy, asked=()):
        self.policy = policy
        self.asked = set(asked)
        self.tracks = {}          # (unit id, batch id) -> Track
        self.moved = {}           # (operation id, pair) -> Track of the fish a plain transfer moves
        self.estimates = {}       # (unit id, batch id) -> (estimated average, Track) before a weighing
        self.days = {}            # (unit id, day) -> UnitDay
        self.corrections = {}     # (unit id, batch id) -> [Correction]
        self.cleaner = set()      # the batches of a cleaner-fish species seen

    # ---- the stock lines --------------------------------------------------------------------------
    def line(self, line, share, grams):
        key = (line.unit_id, line.batch_id)
        k = line.count_delta
        track = self.tracks.get(key)
        if line.cleaner:
            self.cleaner.add(line.batch_id)
        if line.kind == MovementKind.WEIGHING:
            if track is not None:
                self.estimates[key] = (track.grams / share.count, line.avg_weight_g, share.count, track)
            self.tracks[key] = Track(share.grams, line.op.date)
        elif k < 0:
            before = share.count - k
            if line.avg_weight_g is not None:
                out = -k * line.avg_weight_g           # graded fish leave at their measured weight
            elif not share.count:
                out = track.grams                      # the last fish take the whole estimate
            else:
                out = track.grams * -k / before        # at the estimate's own average
            if line.kind == MovementKind.TRANSFER_OUT:
                self.moved[(line.op.id, line.pair)] = track.part(out, Decimal(-k) / before)
            track.grams = track.grams - out if share.count else ZERO
        else:
            if line.kind == MovementKind.TRANSFER_IN and line.op.kind != OperationKind.GRADING:
                incoming = self.moved[(line.op.id, line.pair)]
            elif line.kind in (MovementKind.INPUT, MovementKind.TRANSFER_IN):
                incoming = Track(grams, line.op.date)  # stocked or graded fish: as measured
            else:
                incoming = track.part(track.grams * k / (share.count - k), Decimal(0))
            if track is None or share.count == k:
                self.tracks[key] = incoming            # the batch had no fish here
            else:
                track.merge(incoming)

    def weighed(self, key, stay, point):
        """A weighing point of a stay was just added: keep the correction it makes, with the realised bFCR since the
        stay's previous measured point."""
        estimate = self.estimates.pop(key, None)
        if estimate is None or point.kind != PointKind.WEIGHING:
            return
        estimated, measured, fish, track = estimate
        previous = stay.points[-2] if len(stay.points) > 1 else None
        window = Window(previous, point, stay.fed_kg(previous.day, point.day)) if previous is not None else None
        self.corrections.setdefault(key, []).append(Correction(
            key[0], key[1], point.day, fish, estimated, measured, track.measured_on, track.expected_fcr,
            len(track.blind_days), window))

    def end_op(self):
        self.moved.clear()

    # ---- the days -----------------------------------------------------------------------------------
    def day(self, unit_id, day, shares, feedings, split):
        """The end of `day` in the unit: credits its feedings (`split`: feeding id -> {batch id: kg}) to the batches
        with fish, and keeps the UnitDay when it was asked for."""
        asked = (unit_id, day) in self.asked
        ordered = sorted(feedings, key=lambda feeding: feeding.order)
        found = []
        # Cleaner fish are exempt from a missing table only beside production fish (ration.Policy.basis).
        beside = any(share.count and batch_id not in self.cleaner for (unit, batch_id), share in shares.items()
                     if unit == unit_id)
        for (unit, batch_id), share in shares.items():
            if unit != unit_id or not share.count:
                continue
            parts = [(feeding, split[feeding.id][batch_id]) for feeding in ordered
                     if batch_id in split.get(feeding.id, {})]
            if not parts and not asked:
                continue
            share_day = feed(self.tracks[(unit_id, batch_id)], share.count, share.avg_weight_g, share.last_weighed,
                             day, parts, lambda weight, batch_id=batch_id: self.policy.basis(unit_id, batch_id, day,
                                                                                             weight, beside))
            share_day.batch_id = batch_id
            found.append(share_day)
        if asked:
            self.days[(unit_id, day)] = UnitDay(unit_id, day, found, ordered, frozenset(self.cleaner))

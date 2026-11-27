"""THE judgement of a worked-out water value (NH₃-N, NH₄-N), pure: no database, no clock, no settings (the coordinator's
architecture of 2026-11-26, after reviews 1 to 5 of derived-fresh found order, tie and tier bugs wherever the judgement
was interleaved with the reads). The read layer (farm/water/read.py, the shell) fetches the samples and the live values,
works them out, judges each against the limits and hands each to the judge as a Record built in ONE place
(read.record_of); everything that decides which value stands for a point, which value a place keeps, what is said and
whether a level may clear is decided HERE, and only here. The latest read (the pages, the cards), the alarm pass
(through it, and `clears`) and the history page all call it.

Per point (`point_verdict`; a "point" is where a value BELONGS: a sample's point, a live value's where its sensor is
bound, so a system's analyser is the system's, never a unit's own point's):
- the EVIDENCE value is the newest worked-out value that has a value, was not refused by the chemistry core and was
  fresh at its own time (never one stale from its start), in the ORDER (ORDER_FIELDS); a live value (a TAN analyser's)
  is evidence where it is bound as a sample is;
- the JUDGED SET is the evidence value and every value newer than it or of its MINUTE (`minute`): a same-minute peer, a
  refused value on its basis, a value stale from its start. The point is the WORST of them, whatever order they were
  entered in, and the value it SHOWS is that worst (else its newest record);
- a newer sample that gives no value never takes the slot: it is said (`lacking`, a value-less `refused`);
- the newest refused sample newer than the evidence is "cannot be evaluated" until an evidence value is newer than it;
- a stored value measured before the minute of the point's evidence (a live analyser's included: review 8, N1) is a LATE
  result when it was not already superseded when it was entered: entered after the newest stored evidence, or itself of
  that evidence's minute or newer (it only stood until the live value came). It is said with what superseded it, never
  an alarm. A live value is never late;
- a point the shell stopped looking back at before it found evidence (`complete` False: the ceiling) cannot be evaluated:
  what was fetched is judged, and is never taken for the whole (`ceiling`).
Per place (`place_verdict`: the unit's own points and its system's, or one point read on its own):
- a judged value, stale now and worse than the value shown, is HELD (the place keeps its judgement until that point gives
  evidence newer than it) when it is of the place's own points or of the point shown, or of the system's tier and newer
  than the value shown; a system's such value OLDER than the value shown is said (`older`), never held;
- an own sample newer than a system's value shown that gives no value turns an OK place into ATTENTION, never plain OK,
  and never beside a held value;
and a level clears only on evidence fresh now and measured strictly after its last bad value: a tie never clears
(`clears`). The shell asks the judge, never decides."""
from dataclasses import dataclass
from datetime import datetime

from .evaluate import ALERTS, RANK, Status

# The one order of a point's values, newest last: by these fields of a Record, in this order. The database ranks by the
# same columns (farm/water/read.py ORDER is built from this), and the id's text orders as the database's uuid does.
ORDER_FIELDS = ('measured_at', 'created_at', 'id')


def minute(moment):
    """The minute a value was measured in: THE one definition of "the same minute", for the judge and for the shell's
    queries (read.py)."""
    return moment.replace(second=0, microsecond=0)


@dataclass(frozen=True)
class Record:
    """One worked-out value where it belongs, as the shell found it (built ONLY by read.record_of). No field has a
    default: a builder that forgets one fails, it never gets a fresh evidence value (review 7, L6).
    - `key`: the shell's handle (its Reading), compared by identity, never read here;
    - `point`: where the value belongs (a point's id; a system's key for a system-level sensor's);
    - `measured_at`, `created_at`, `id` (text): its ORDER; `stored`: a stored sample's (a live value's: False);
    - `value`: whether it has a value; `refused`: the chemistry core refused it (with a basis value or none);
    - `fresh_at_own_time`: it was fresh when it was measured;
    - `fresh_now`: it is fresh at the moment of the read, by its OWN freshness, never a status; None where the shell
      has no moment (a look-back): `place_verdict` and `clears` refuse it;
    - `status`: the limits' judgement of its value for the place's fish."""
    key: object
    point: object
    measured_at: datetime
    created_at: datetime
    id: str
    stored: bool
    value: bool
    refused: bool
    fresh_at_own_time: bool
    fresh_now: bool | None
    status: str

    @property
    def order(self):
        """The one order of a point's values, newest last (ORDER_FIELDS)."""
        return tuple(getattr(self, name) for name in ORDER_FIELDS)

    @property
    def minute(self):
        return minute(self.measured_at)

    @property
    def evidence(self):
        return self.value and not self.refused and self.fresh_at_own_time


def _fresh_now(record):
    if record.fresh_now is None:
        raise ValueError('The judge was asked whether a value is fresh now by a shell that gave it no moment.')
    return record.fresh_now


@dataclass(frozen=True)
class PointVerdict:
    """What a point's values say: its `evidence` value (or None); the `judged` set, newest first; its `worst` (the most
    severe of the judged set, an evidence value before another, then the newest); the record it `shown` (its worst, else
    its newest); its newest `lacking` sample (no value for want of an input) and newest `refused` one, each newer than
    the evidence or of its minute (or None); its `late` results, the worst first, then the newest (what superseded
    each: `superseded`); its newest stored evidence (`superseded_by`, what the shell's late query is bounded by);
    `ceiling`: the shell stopped before it found evidence."""
    evidence: Record | None
    judged: tuple
    worst: Record | None
    shown: Record | None
    lacking: Record | None
    refused: Record | None
    late: tuple
    superseded_by: Record | None
    ceiling: bool

    def superseded(self, late):
        """What superseded a `late` result: the newest stored evidence where it is of a newer minute, else the point's
        evidence (a live value)."""
        stored = self.superseded_by
        return stored if stored is not None and stored.minute > late.minute else self.evidence


def newest_first(records):
    return sorted(records, key=lambda record: record.order, reverse=True)


def worst_first(records):
    """`records` the most severe first, then the newest."""
    return sorted(newest_first(records), key=lambda record: RANK[record.status])


def point_verdict(records, complete=True):
    """The verdict of one point's values (`records`, any order, of one worked-out code). `complete` False: the shell
    stopped its look-back at the ceiling (`over_ceiling`); with no evidence among them the point says so (`ceiling`)."""
    ordered = newest_first(records)
    evidence = next((record for record in ordered if record.evidence), None)
    newer = ordered if evidence is None else [
        record for record in ordered if record.order > evidence.order or record.minute == evidence.minute]
    stored = next((record for record in ordered if record.evidence and record.stored), None)
    late = () if evidence is None else tuple(worst_first(
        record for record in ordered if record.stored and record.value and not record.refused
        and record.minute < evidence.minute
        and (stored is None or record.minute >= stored.minute or record.created_at > stored.created_at)))
    judged = tuple(record for record in newer if record.value)
    worst = worst_of(judged)
    return PointVerdict(evidence, judged, worst, worst or (ordered[0] if ordered else None),
                        next((record for record in newer if not record.value and not record.refused), None),
                        next((record for record in newer if record.refused), None), late, stored,
                        not complete and evidence is None)


def worst_of(records):
    """The worst of `records`: the most severe status, then an evidence value before another, then the newest."""
    return min(newest_first(records), key=lambda record: (RANK[record.status], not record.evidence), default=None)


def settled(candidates, exhausted):
    """Whether a point's look-back may stop after these `candidates` (its newest records that may give a value, as the
    shell fetches them a few at a time, newest first): there are no more (`exhausted`), or it holds its evidence and a
    candidate of a minute older than the evidence's, so every value of the evidence's minute is in."""
    if exhausted:
        return True
    evidence = point_verdict(candidates).evidence
    return evidence is not None and any(record.minute < evidence.minute for record in candidates)


# How many candidates of one point the shell looks back at before it stops without evidence (`over_ceiling`). A point
# sampled every hour for the 30 days of the read's window has 720; 512 is past three weeks of hourly samples. The
# shell's doubling rounds (2, 4, … 256: 510) end with a round of the 2 left, so it reads EXACTLY 512 candidates before it
# stops (farm/water/read.py prefetch_newest_worked; a test counts them at this value). A point with that many samples and
# not one evaluable value is not a water that can be judged from its list: it "cannot be evaluated", said so, and what
# was fetched is still judged.
CEILING = 512


def over_ceiling(candidates, ceiling):
    """Whether the shell stops a point's look-back here, unsettled: `ceiling` candidates (CEILING) and no evidence among
    them."""
    return len(candidates) >= ceiling and point_verdict(candidates).evidence is None


def shown_without_value(tiers):
    """The record a place shows when no tier has a worked-out value: the newest record (it says why it has no value) of
    the first tier that has one (`tiers`: the own points' records, then the system's); None for none."""
    return next((newest_first(tier)[0] for tier in tiers if tier), None)


@dataclass(frozen=True)
class PlaceVerdict:
    """What a place's worked-out value takes from its points: the value `held` (or None); whether it needs `attention`;
    its newest `refused` record of the tier read (or None); the value-less newer records to say (`said`); the late
    results judged critical or a warning, the worst first, then the newest, across its points, each with what
    superseded it (`late`: ((late, evidence), …)); the system's stale alerts older than the value shown (`older`, said, never held); and the
    points of the tier read that could not be evaluated whole (`ceiling`)."""
    held: Record | None
    attention: bool
    refused: Record | None
    said: tuple
    late: tuple
    older: tuple
    ceiling: tuple


def place_verdict(shown, points, own_points):
    """The verdict of a place. `shown`: the Record of the value the place shows, its `status` the place's judgement
    after the worst fresh value. `points`: {point: PointVerdict} of every point of the place, own and system. `own_points`:
    the place's own points (a unit's own-water points; for a point read on its own, itself)."""
    shown_rank = RANK[shown.status]
    kept, older = [], []
    for point, verdict in points.items():
        for record in verdict.judged:
            if _fresh_now(record) or record.status not in ALERTS or RANK[record.status] >= shown_rank:
                continue
            if point in own_points or point == shown.point or record.order > shown.order:
                kept.append(record)
            else:
                older.append(record)                        # the system's, older than the value shown: said
    held = worst_of(kept)
    from_system = shown.point not in own_points
    tier = {point: verdict for point, verdict in points.items()
            if point in own_points or from_system or not shown.value}
    refused = max((verdict.refused for verdict in tier.values() if verdict.refused is not None),
                  key=lambda record: record.order, default=None)
    said = tuple(record for verdict in points.values() for record in (verdict.lacking, verdict.refused)
                 if record is not None and not record.value and record.key is not shown.key)
    superseded = {id(record): verdict.superseded(record) for verdict in points.values() for record in verdict.late}
    late = tuple((record, superseded[id(record)]) for record in worst_first(
        record for verdict in points.values() for record in verdict.late if record.status in ALERTS))
    attention = (from_system and held is None and shown.status == Status.OK
                 and any(points[point].lacking is not None and points[point].lacking.order > shown.order
                         for point in own_points if point in points))
    return PlaceVerdict(held, attention, refused, said, late, tuple(worst_first(older)),
                        tuple(point for point, verdict in tier.items() if verdict.ceiling))


def clears(decider, last_bad_at):
    """Whether a value may end a level of a worked-out value: it is evidence (a value, not refused, fresh at its own time),
    fresh now by its own freshness, and measured strictly after the last value that held the level (a tie never clears);
    with no last bad value known, evidence fresh now is enough."""
    return (decider is not None and decider.evidence and _fresh_now(decider)
            and (last_bad_at is None or decider.measured_at > last_bad_at))

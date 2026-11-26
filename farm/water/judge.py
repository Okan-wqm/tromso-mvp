"""THE judgement of a worked-out water value (NH₃-N, NH₄-N), pure: no database, no clock, no settings (the coordinator's
architecture of 2026-11-26, after reviews 1 to 5 of derived-fresh found order, tie and tier bugs wherever the judgement
was interleaved with the reads). The read layer (farm/water/read.py, the shell) fetches the samples, works their values
out and judges each against the limits (`Record.status`); everything that decides which value stands for a point, which
value a place keeps, what is said and whether a level may clear is decided HERE, and only here. The latest read (the
pages, the cards), the alarm pass (through it) and the history page all call it.

The rule (review 5, the coordinator's round 6), per point:
- the EVIDENCE value is the newest worked-out value that has a value, was not refused by the chemistry core and was
  fresh at its own time (never one stale from its start), in the order (measured_at, created_at, id);
- the JUDGED SET is the evidence value and every value newer than it or of its minute (a same-minute peer, a refused
  value on its basis, a value stale from its start): the point is the WORST of them, whatever order they were entered in;
- a newer sample that gives no value never takes the slot: it is said (`lacking`, a value-less `refused`);
- the newest refused sample newer than the evidence is "cannot be evaluated" until an evidence value is newer than it;
- a value measured before the evidence but entered after it is a LATE result: said, never a candidate, never an alarm.
Per place (a unit's point, its other own points, its system's loop):
- a judged value of an own point, or of the point of the value shown, stale now and worse than the value shown, is HELD:
  the place keeps its judgement until that point gives evidence newer than it;
- an own sample newer than a system's value shown that gives no value makes the place need ATTENTION, never plain OK;
and a level clears only on evidence strictly newer than its last bad value: a tie never clears (`clears`)."""
from dataclasses import dataclass
from datetime import datetime

from .evaluate import ALERTS, RANK, Status


@dataclass(frozen=True)
class Record:
    """One worked-out value of one sample at one point, as the shell found it. `key` is the shell's handle (its Reading),
    never read here. `point`: the point's id; `tier`: 0 the unit's own points, 1 its system's. `value`: whether it has a
    value; `refused`: the chemistry core refused it (with a basis value or none); `fresh_at_own_time`: it was fresh when it
    was measured (its inputs did not end at its start); `fresh_now`: it is fresh at the moment of the read; `status`: the
    limits' judgement of its value for the place's fish (an evaluate.Status value)."""
    key: object
    point: object
    tier: int
    measured_at: datetime
    created_at: datetime
    id: str
    value: bool
    refused: bool = False
    fresh_at_own_time: bool = True
    fresh_now: bool = True
    status: str = Status.NOT_MEASURED

    @property
    def order(self):
        """The one order of a point's values, newest last: (measured_at, created_at, id)."""
        return (self.measured_at, self.created_at, str(self.id))

    @property
    def evidence(self):
        return self.value and not self.refused and self.fresh_at_own_time


@dataclass(frozen=True)
class PointVerdict:
    """What a point's values say: its `evidence` value (or None); the `judged` set, newest first; its `worst` (the worst
    of the judged set: the most severe, then evidence before non-evidence, then the newest); its newest `lacking` sample
    (no value for want of an input) and newest `refused` one, each newer than the evidence (or None); its `late` results,
    newest first."""
    evidence: Record | None
    judged: tuple
    worst: Record | None
    lacking: Record | None
    refused: Record | None
    late: tuple


def newest_first(records):
    return sorted(records, key=lambda record: record.order, reverse=True)


def point_verdict(records):
    """The verdict of one point's values (`records`, any order, of one worked-out code)."""
    ordered = newest_first(records)
    evidence = next((record for record in ordered if record.evidence), None)
    if evidence is None:
        newer, late = ordered, ()
    else:
        newer = [record for record in ordered
                 if record.order > evidence.order or record.measured_at == evidence.measured_at]
        late = tuple(record for record in ordered if record.measured_at < evidence.measured_at
                     and record.created_at > evidence.created_at and record.value and not record.refused)
    judged = tuple(record for record in newer if record.value)
    return PointVerdict(evidence, judged, worst_of(judged),
                        next((record for record in newer if not record.value and not record.refused), None),
                        next((record for record in newer if record.refused), None), late)


def worst_of(records):
    """The worst of `records`: the most severe status, then an evidence value before another, then the newest."""
    return min(newest_first(records), key=lambda record: (RANK[record.status], not record.evidence), default=None)


def settled(records, exhausted):
    """Whether a point's look-back may stop after these `records` (its newest, fetched by the shell a few at a time):
    there are no more (`exhausted`), or it found its evidence and a value older than the evidence's minute."""
    if exhausted or not records:
        return True
    evidence = point_verdict(records).evidence
    return evidence is not None and newest_first(records)[-1].measured_at < evidence.measured_at


@dataclass(frozen=True)
class PlaceVerdict:
    """What a place's worked-out value takes from its points: the value `held` (or None), whether it needs `attention`,
    its newest `refused` record of the tier read (or None), the value-less newer records to say (`said`), and the late
    results judged critical or a warning, each with its point's evidence (`late`: ((late, evidence), …))."""
    held: Record | None
    attention: bool
    refused: Record | None
    said: tuple
    late: tuple


def place_verdict(shown, points, own_points, for_unit=True):
    """The verdict of a place. `shown`: the Record of the value A9 chose to show (its judgement after the worst fresh
    value; None when none). `points`: {point id: PointVerdict} of every point of the place, own and system.
    `own_points`: the ids of the unit's own points. `for_unit`: the place stands for a unit."""
    shown_point = shown.point if shown is not None else None
    shown_rank = RANK[shown.status] if shown is not None else RANK[Status.NOT_MEASURED]
    held = None
    if for_unit:
        kept = [record for point, verdict in points.items() if point in own_points or point == shown_point
                for record in verdict.judged
                if (shown is None or record.key is not shown.key) and not record.fresh_now
                and record.status in ALERTS and RANK[record.status] < shown_rank]
        held = min(kept, key=lambda record: RANK[record.status], default=None)
    from_system = shown_point is not None and shown_point not in own_points
    tier = [verdict for point, verdict in points.items()
            if point in own_points or from_system or shown is None or not shown.value]
    refused = max((verdict.refused for verdict in tier if verdict.refused is not None),
                  key=lambda record: record.order, default=None)
    said = tuple(record for verdict in points.values() for record in (verdict.lacking, verdict.refused)
                 if record is not None and not record.value and (shown is None or record.key is not shown.key))
    late = tuple((record, verdict.evidence) for verdict in points.values() for record in verdict.late
                 if record.status in ALERTS)
    attention = (for_unit and from_system and held is None and shown_rank > RANK[Status.UNEVALUATED]
                 and any(points[point].lacking is not None and points[point].lacking.order > shown.order
                         for point in own_points if point in points))
    return PlaceVerdict(held, attention, refused, said, late)


def clears(decider, last_bad_at):
    """Whether a value may end a level of a worked-out value: it is evidence (a value, not refused, fresh at its own time)
    fresh now, and measured strictly after the last value that held the level (a tie never clears)."""
    return (decider is not None and decider.evidence and decider.fresh_now
            and (last_bad_at is None or decider.measured_at > last_bad_at))

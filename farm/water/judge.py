"""THE judgement of a worked-out water value (NH₃-N, NH₄-N), pure: no database, no clock, no settings (the coordinator's
architecture of 2026-11-26, after reviews 1 to 5 of derived-fresh found order, tie and tier bugs wherever the judgement
was interleaved with the reads). The read layer (farm/water/read.py, the shell) fetches the samples and the live values,
works them out, judges each against the limits and hands each to the judge as a Record built in ONE place
(read.record_of); everything that decides which value stands for a point, which value a place keeps, what is said and
whether a level may clear is decided HERE, and only here. The latest read (the pages, the cards), the alarm pass
(through it, and `clears`) and the history page all call it.

The rule (review 5, the coordinator's round 6), per point (`point_verdict`):
- the EVIDENCE value is the newest worked-out value that has a value, was not refused by the chemistry core and was
  fresh at its own time (never one stale from its start), in the ORDER (measured_at, created_at, id); a live value (a TAN
  analyser's) is evidence at its point as a sample is;
- the JUDGED SET is the evidence value and every value newer than it or of its MINUTE (`minute`): a same-minute peer, a
  refused value on its basis, a value stale from its start. The point is the WORST of them, whatever order they were
  entered in, and the value it SHOWS is that worst (else its newest record);
- a newer sample that gives no value never takes the slot: it is said (`lacking`, a value-less `refused`);
- the newest refused sample newer than the evidence is "cannot be evaluated" until an evidence value is newer than it;
- a value measured before the evidence's minute but entered after the evidence is a LATE result: said, never an alarm.
Per place (`place_verdict`: a unit's point, its other own points, its system's loop):
- a judged value, stale now and worse than the value shown, is HELD (the place keeps its judgement until that point gives
  evidence newer than it) when it is of the unit's own points or of the point shown, or of the system's tier and newer
  than the value shown (review 6, M7); a system's such value older than the value shown is said as a late result;
- an own sample newer than a system's value shown that gives no value turns an OK place into ATTENTION, never plain OK;
and a level clears only on evidence fresh now and measured strictly after its last bad value: a tie never clears
(`clears`). The shell asks the judge, never decides (review 6, M1)."""
from dataclasses import dataclass
from datetime import datetime

from .evaluate import ALERTS, RANK, Status

# The one order of a point's values, newest last, as the database ranks them (farm/water/read.py ORDER: the same three
# columns, and the id's text orders as the database's uuid does).
ORDER_FIELDS = ('measured_at', 'created_at', 'id')


def minute(moment):
    """The minute a value was measured in: THE one definition of "the same minute" (review 6, L5), for the judge and for
    the shell's queries (read.py)."""
    return moment.replace(second=0, microsecond=0)


@dataclass(frozen=True)
class Record:
    """One worked-out value at one point, as the shell found it (built ONLY by read.record_of). `key` is the shell's
    handle (its Reading), compared by identity, never read here. `point`: the point's id; `tier`: 0 the unit's own points,
    1 its system's. `value`: whether it has a value; `refused`: the chemistry core refused it (with a basis value or
    none); `fresh_at_own_time`: it was fresh when it was measured; `fresh_now`: it is fresh at the moment of the read (its
    OWN freshness, never a status: review 6, M2); `status`: the limits' judgement of its value for the place's fish."""
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
        """The one order of a point's values, newest last (ORDER_FIELDS)."""
        return (self.measured_at, self.created_at, str(self.id))

    @property
    def minute(self):
        return minute(self.measured_at)

    @property
    def evidence(self):
        return self.value and not self.refused and self.fresh_at_own_time


@dataclass(frozen=True)
class PointVerdict:
    """What a point's values say: its `evidence` value (or None); the `judged` set, newest first; its `worst` (the most
    severe of the judged set, an evidence value before another, then the newest); the record it `shown` (its worst, else
    its newest); its newest `lacking` sample (no value for want of an input) and newest `refused` one, each newer than
    the evidence or of its minute (or None); its `late` results, newest first."""
    evidence: Record | None
    judged: tuple
    worst: Record | None
    shown: Record | None
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
        newer = [record for record in ordered if record.order > evidence.order or record.minute == evidence.minute]
        late = tuple(record for record in ordered if record.minute < evidence.minute
                     and record.created_at > evidence.created_at and record.value and not record.refused)
    judged = tuple(record for record in newer if record.value)
    worst = worst_of(judged)
    return PointVerdict(evidence, judged, worst, worst or (ordered[0] if ordered else None),
                        next((record for record in newer if not record.value and not record.refused), None),
                        next((record for record in newer if record.refused), None), late)


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


@dataclass(frozen=True)
class PlaceVerdict:
    """What a place's worked-out value takes from its points: the value `held` (or None), whether it needs `attention`,
    its newest `refused` record of the tier read (or None), the value-less newer records to say (`said`), and the late
    results judged critical or a warning, each with the value it was superseded by (`late`: ((late, newer), …))."""
    held: Record | None
    attention: bool
    refused: Record | None
    said: tuple
    late: tuple


def place_verdict(shown, points, own_points, for_unit=True):
    """The verdict of a place. `shown`: the Record of the value A9 chose to show, with its judgement after the worst fresh
    value (None when none). `points`: {point id: PointVerdict} of every point of the place, own and system. `own_points`:
    the ids of the unit's own points. `for_unit`: the place stands for a unit."""
    shown_point = shown.point if shown is not None else None
    shown_rank = RANK[shown.status] if shown is not None else RANK[Status.NOT_MEASURED]

    def alarming(record):
        return ((shown is None or record.key is not shown.key) and not record.fresh_now and record.status in ALERTS
                and RANK[record.status] < shown_rank)

    held, system_late = None, []
    if for_unit:
        kept = []
        for point, verdict in points.items():
            for record in verdict.judged:
                if not alarming(record):
                    continue
                if point in own_points or point == shown_point or shown is None or record.order > shown.order:
                    kept.append(record)
                else:
                    system_late.append(record)              # the system's, older than the value shown: said (M7)
        held = min(kept, key=lambda record: RANK[record.status], default=None)
    from_system = shown_point is not None and shown_point not in own_points
    tier = [verdict for point, verdict in points.items()
            if point in own_points or from_system or shown is None or not shown.value]
    refused = max((verdict.refused for verdict in tier if verdict.refused is not None),
                  key=lambda record: record.order, default=None)
    said = tuple(record for verdict in points.values() for record in (verdict.lacking, verdict.refused)
                 if record is not None and not record.value and (shown is None or record.key is not shown.key))
    late = (*((record, verdict.evidence) for verdict in points.values() for record in verdict.late
              if record.status in ALERTS),
            *((record, shown) for record in system_late))
    attention = (for_unit and from_system and held is None and shown is not None and shown.status == Status.OK
                 and any(points[point].lacking is not None and points[point].lacking.order > shown.order
                         for point in own_points if point in points))
    return PlaceVerdict(held, attention, refused, said, tuple(late))


def clears(decider, last_bad_at):
    """Whether a value may end a level of a worked-out value: it is evidence (a value, not refused, fresh at its own time),
    fresh now by its own freshness, and measured strictly after the last value that held the level (a tie never
    clears)."""
    return (decider is not None and decider.evidence and decider.fresh_now
            and (last_bad_at is None or decider.measured_at > last_bad_at))

"""The pure judgement of a worked-out water value (farm/water/judge.py), tested exhaustively: for small scenarios of two
to four values at one point, mixing a critical, an OK, a refused value, a value-less sample and values stale from their
start, at the same minute or not, EVERY order of entry (created_at) is tried (itertools), and the invariants the
coordinator set after review 5 of derived-fresh must hold in each:
(i) a critical is never hidden by a value that is no evidence;
(ii) a level clears only on evidence strictly newer than its last bad value (a tie never clears);
(iii) for values of one minute, the verdict does not depend on the order they were entered in;
(iv) the point is the worst of its judged set.
No database, no clock: a SimpleTestCase."""
import itertools
from datetime import datetime, timedelta, timezone

from django.test import SimpleTestCase

from ..water import judge
from ..water.evaluate import RANK, Status

T0 = datetime(2026, 11, 26, 8, 0, tzinfo=timezone.utc)
CRITICAL, WARNING, OK, UNEVALUATED = Status.CRITICAL, Status.WARNING, Status.OK, Status.UNEVALUATED
# What a value can be: (has a value, refused, fresh at its own time, its status)
KINDS = {
    'critical': (True, False, True, CRITICAL),
    'warning': (True, False, True, WARNING),
    'ok': (True, False, True, OK),
    'refused_basis_ok': (True, True, True, UNEVALUATED),       # refused, its basis inside the limits
    'refused_basis_critical': (True, True, True, CRITICAL),    # refused, its basis past the critical limit
    'refused_bare': (False, True, True, Status.NOT_MEASURED),  # refused, no basis either
    'lacking': (False, False, True, Status.NOT_MEASURED),      # a TAN without a pH or a temperature
    'stale_ok': (True, False, False, OK),                      # stale from its start
    'stale_critical': (True, False, False, CRITICAL),
}


def record(name, kind, minute, created, point='P', tier=0, fresh_now=None):
    """A value. Whether it is fresh NOW is its own axis (review 6, M5), apart from whether it was fresh at its own time:
    by default every other entry is fresh now."""
    value, refused, fresh_at_own_time, status = KINDS[kind]
    return judge.Record(key=name, point=point, tier=tier, measured_at=T0 + timedelta(minutes=minute),
                        created_at=T0 + timedelta(hours=10, minutes=created), id=name, value=value, refused=refused,
                        fresh_at_own_time=fresh_at_own_time,
                        fresh_now=(created % 2 == 0) if fresh_now is None else fresh_now, status=status)


def said(values):
    """A scenario in a failure's message: (name, status, has a value, refused, fresh at its time, minute, entered)."""
    return [(each.id, each.status, each.value, each.refused, each.fresh_at_own_time, each.measured_at.minute,
             each.created_at.minute) for each in values]


def scenarios():
    """Every pair, triple and quadruple of kinds, each value at minute 0 or 5 (so same-minute ties and plain order), in
    every order of entry."""
    kinds = list(KINDS)
    for size in (2, 3, 4):
        for chosen in itertools.combinations_with_replacement(kinds, size):
            for minutes in (itertools.product((0, 5), repeat=size) if size < 4
                            else ((0, 0, 0, 0), (0, 5, 0, 5), (5, 0, 0, 5))):   # four: one minute, and two pairs
                for created in itertools.permutations(range(size)):
                    yield [record(f'v{index}', kind, minute, created[index])
                           for index, (kind, minute) in enumerate(zip(chosen, minutes))]


class InvariantTests(SimpleTestCase):
    def test_the_scenarios_are_many(self):
        self.assertGreater(sum(1 for _scenario in scenarios()), 10000)

    def test_i_a_critical_is_never_hidden_by_a_value_that_is_no_evidence(self):
        """A critical value as new as the newest evidence's minute or newer (by its measurement), or the newest evidence
        itself critical: the point is critical."""
        for values in scenarios():
            verdict = judge.point_verdict(values)
            evidence = verdict.evidence
            criticals = [each for each in values if each.value and each.status == CRITICAL
                         and (evidence is None or each.minute >= evidence.minute)]
            if criticals:
                self.assertEqual(verdict.worst.status, CRITICAL, said(values))

    def test_ii_a_level_clears_only_on_evidence_strictly_newer_than_its_last_bad_value(self):
        for values in scenarios():
            for each in values:
                for last_bad in (T0, T0 + timedelta(minutes=5)):
                    if judge.clears(each, last_bad) != (each.evidence and each.fresh_now and each.measured_at > last_bad):
                        self.fail(said(values))

    def test_iii_values_of_one_minute_are_judged_alike_in_any_order_of_entry(self):
        kinds = list(KINDS)
        for size in (2, 3, 4):
            for chosen in itertools.combinations_with_replacement(kinds, size):
                verdicts = set()
                for created in itertools.permutations(range(size)):
                    values = [record(f'v{index}', kind, 0, created[index]) for index, kind in enumerate(chosen)]
                    verdict = judge.point_verdict(values)
                    verdicts.add((verdict.worst.status if verdict.worst else None,
                                  frozenset(each.id for each in verdict.judged)))
                self.assertEqual(len(verdicts), 1, (chosen, verdicts))

    def test_iv_the_point_is_the_worst_of_its_judged_set(self):
        for values in scenarios():
            verdict = judge.point_verdict(values)
            if verdict.judged:
                self.assertEqual(RANK[verdict.worst.status], min(RANK[each.status] for each in verdict.judged),
                                 said(values))
                self.assertIn(verdict.worst, verdict.judged)
            else:
                self.assertIsNone(verdict.worst)

    def test_the_evidence_is_the_newest_value_that_is_evidence_and_nothing_older_is_judged(self):
        for values in scenarios():
            verdict = judge.point_verdict(values)
            evidence = [each for each in values if each.evidence]
            if evidence:
                self.assertEqual(verdict.evidence, max(evidence, key=lambda each: each.order), said(values))
                self.assertTrue(all(each.measured_at >= verdict.evidence.measured_at for each in verdict.judged))
            else:
                self.assertIsNone(verdict.evidence)
                self.assertEqual(set(verdict.judged), {each for each in values if each.value}, said(values))

    def test_a_value_less_sample_never_takes_the_slot_and_is_said(self):
        for values in scenarios():
            verdict = judge.point_verdict(values)
            self.assertTrue(all(each.value for each in verdict.judged))
            lacking = [each for each in values if not each.value and not each.refused
                       and (verdict.evidence is None or each.order > verdict.evidence.order
                            or each.measured_at == verdict.evidence.measured_at)]
            self.assertEqual(verdict.lacking, max(lacking, key=lambda each: each.order) if lacking else None,
                             said(values))


class ExamplesTests(SimpleTestCase):
    """The reviews' cases, as the judge says them."""

    def test_a_same_minute_lab_critical_and_kit_ok_are_critical_in_both_entry_orders(self):
        for lab_first in (True, False):
            with self.subTest(lab_first=lab_first):
                lab = record('lab', 'critical', 0, 0 if lab_first else 1)
                kit = record('kit', 'ok', 0, 1 if lab_first else 0)
                self.assertEqual(judge.point_verdict([lab, kit]).worst.key, 'lab')

    def test_a_refused_value_on_its_basis_ahead_of_a_late_lab_critical(self):
        lab = record('lab', 'critical', 0, 5)                        # measured first, entered last
        refused = record('refused', 'refused_basis_ok', 5, 1)
        verdict = judge.point_verdict([lab, refused])
        self.assertEqual((verdict.evidence.key, verdict.worst.key, verdict.refused.key), ('lab', 'lab', 'refused'))

    def test_a_value_stale_from_its_start_ahead_of_a_critical(self):
        verdict = judge.point_verdict([record('bad', 'critical', 0, 0), record('stale', 'stale_ok', 5, 1)])
        self.assertEqual((verdict.evidence.key, verdict.worst.key), ('bad', 'bad'))

    def test_a_late_result_before_newer_evidence_is_late_never_judged(self):
        ok = record('ok', 'ok', 5, 0)
        lab = record('lab', 'critical', 0, 3)
        verdict = judge.point_verdict([ok, lab])
        self.assertEqual((verdict.worst.key, [each.key for each in verdict.late]), ('ok', ['lab']))

    def test_a_held_value_at_an_own_point_and_attention_from_the_system(self):
        outlet = judge.point_verdict([record('outlet', 'critical', 0, 0, point='outlet', fresh_now=False)])
        middle = judge.point_verdict([record('middle', 'ok', 5, 1, point='middle')])
        shown = middle.worst
        place = judge.place_verdict(shown, {'outlet': outlet, 'middle': middle}, {'outlet', 'middle'})
        self.assertEqual(place.held.key, 'outlet')
        loop = judge.point_verdict([record('loop', 'ok', 0, 0, point='loop', tier=1)])
        own = judge.point_verdict([record('tan', 'lacking', 5, 1, point='middle')])
        place = judge.place_verdict(loop.worst, {'loop': loop, 'middle': own}, {'middle'})
        self.assertTrue(place.attention)
        self.assertEqual([each.key for each in place.said], ['tan'])

    def test_a_loops_refused_sample_is_the_places_when_the_loop_is_read(self):
        loop = judge.point_verdict([record('ok', 'ok', 0, 0, point='loop', tier=1),
                                    record('refused', 'refused_bare', 5, 1, point='loop', tier=1)])
        place = judge.place_verdict(loop.worst, {'loop': loop}, set())
        self.assertEqual(place.refused.key, 'refused')

    def test_a_tie_never_clears(self):
        self.assertFalse(judge.clears(record('kit', 'ok', 0, 1), T0))
        self.assertTrue(judge.clears(record('kit', 'ok', 5, 1), T0))


class PointRuleTests(SimpleTestCase):
    """The point rules the mutants of review 6 showed thin."""

    def test_the_worst_prefers_an_evidence_value_of_the_worst_status(self):
        for values in scenarios():
            verdict = judge.point_verdict(values)
            if verdict.worst is None:
                continue
            same = [each for each in verdict.judged if each.status == verdict.worst.status]
            if any(each.evidence for each in same):
                self.assertTrue(verdict.worst.evidence, said(values))

    def test_the_refused_record_is_newer_than_the_evidence_or_of_its_minute(self):
        for values in scenarios():
            verdict = judge.point_verdict(values)
            if verdict.refused is not None and verdict.evidence is not None:
                self.assertTrue(verdict.refused.order > verdict.evidence.order
                                or verdict.refused.minute == verdict.evidence.minute, said(values))

    def test_a_late_result_is_never_refused_and_always_older_than_the_evidence(self):
        for values in scenarios():
            verdict = judge.point_verdict(values)
            for late in verdict.late:
                self.assertFalse(late.refused, said(values))
                self.assertLess(late.minute, verdict.evidence.minute)
                self.assertGreater(late.created_at, verdict.evidence.created_at)

    def test_clears_needs_fresh_now_on_its_own_axis(self):
        for kind in KINDS:
            for fresh_now in (True, False):
                value = record('v', kind, 5, 0, fresh_now=fresh_now)
                expected = value.evidence and fresh_now
                self.assertEqual(judge.clears(value, T0), expected, (kind, fresh_now))
                self.assertFalse(judge.clears(value, T0 + timedelta(minutes=5)), (kind, fresh_now))

    def test_shown_is_the_worst_else_the_newest(self):
        for values in scenarios():
            verdict = judge.point_verdict(values)
            self.assertEqual(verdict.shown, verdict.worst or max(values, key=lambda each: each.order), said(values))


def candidates_of(values):
    """What the shell's evidence stream fetches: the values that may give one (a value, or refused by the core)."""
    return [each for each in values if each.value or each.refused]


class SettledTests(SimpleTestCase):
    """The shell stops a point's look-back when `settled` says so (review 6, M5): on ANY prefix it says settled, the
    verdict must be the full one's."""

    def test_a_settled_prefix_gives_the_full_verdict(self):
        checked = 0
        for values in scenarios():
            candidates = judge.newest_first(candidates_of(values))
            valueless = [each for each in values if not each.value and not each.refused]
            full = judge.point_verdict(values)
            for size in range(1, len(candidates) + 1):
                if not judge.settled(candidates[:size], exhausted=size == len(candidates)):
                    continue
                checked += 1
                prefix = judge.point_verdict([*candidates[:size], *valueless])
                self.assertEqual((prefix.evidence, set(prefix.judged), prefix.worst and prefix.worst.status,
                                  prefix.refused),
                                 (full.evidence, set(full.judged), full.worst and full.worst.status, full.refused),
                                 (size, said(values)))
                break
        self.assertGreater(checked, 1000)


PLACE_KINDS = ('critical', 'warning', 'ok', 'lacking', 'refused_bare', 'stale_critical')


def place_scenarios():
    """Two own points and the system's loop, each with no value or one of PLACE_KINDS, fresh now or not, at minute 0 or 5;
    the value shown each of their values in turn (its status as the place judged it)."""
    choices = [None, *((kind, minute, fresh) for kind in PLACE_KINDS for minute in (0, 5) for fresh in (True, False))]
    for o1, o2, loop in itertools.product(choices, repeat=3):
        values = {}
        for index, (point, tier, choice) in enumerate((('o1', 0, o1), ('o2', 0, o2), ('loop', 1, loop))):
            if choice is not None:
                kind, minute, fresh = choice
                values[point] = record(point, kind, minute, index, point=point, tier=tier, fresh_now=fresh)
        verdicts = {point: judge.point_verdict([value]) for point, value in values.items()}
        for shown in [each for each in values.values() if each.value] or [None]:
            yield values, verdicts, shown


class PlaceTests(SimpleTestCase):
    """The place rules (review 6, M5, M7), on every place scenario."""

    def test_the_place_scenarios_are_many(self):
        self.assertGreater(sum(1 for _scenario in place_scenarios()), 10000)

    def test_held_is_stale_an_alert_and_worse_than_shown(self):
        for values, verdicts, shown in place_scenarios():
            held = judge.place_verdict(shown, verdicts, {'o1', 'o2'}).held
            if held is not None:
                self.assertFalse(held.fresh_now)
                self.assertIn(held.status, (CRITICAL, WARNING))
                if shown is not None:
                    self.assertLess(RANK[held.status], RANK[shown.status])
                    self.assertIsNot(held.key, shown.key)

    def test_every_stale_worse_alert_is_held_or_said(self):
        """An own point's, the point shown's, or the system's newer than the value shown: held, or a worse one is. The
        system's older than the value shown: said as a late result (M7)."""
        for values, verdicts, shown in place_scenarios():
            verdict = judge.place_verdict(shown, verdicts, {'o1', 'o2'})
            for point, value in values.items():
                alarming = (value.value and not value.fresh_now and value.status in (CRITICAL, WARNING)
                            and (shown is None or (value.key is not shown.key and RANK[value.status] < RANK[shown.status])))
                if not alarming:
                    continue
                if point != 'loop' or shown is None or shown.point == 'loop' or value.order > shown.order:
                    self.assertIsNotNone(verdict.held, (point, shown and shown.point))
                    self.assertLessEqual(RANK[verdict.held.status], RANK[value.status])
                else:
                    self.assertIn(value.key, [late.key for late, _newer in verdict.late], (point, shown.point))

    def test_attention_only_turns_an_ok_value_of_the_system(self):
        for values, verdicts, shown in place_scenarios():
            verdict = judge.place_verdict(shown, verdicts, {'o1', 'o2'})
            if verdict.attention:
                self.assertEqual((shown.point, shown.status), ('loop', OK))
                self.assertTrue(any(verdicts[point].lacking is not None and verdicts[point].lacking.order > shown.order
                                    for point in ('o1', 'o2') if point in verdicts))

    def test_the_refused_record_is_of_the_tier_read(self):
        for values, verdicts, shown in place_scenarios():
            refused = judge.place_verdict(shown, verdicts, {'o1', 'o2'}).refused
            if refused is not None and shown is not None and shown.value and shown.point != 'loop':
                self.assertNotEqual(refused.point, 'loop')


    def test_an_older_stale_alert_at_the_system_point_shown_is_held(self):
        """The point shown is the system's loop: a stale critical of its judged set entered before the value shown (the
        same minute) is held, as at an own point (the point shown is judged as its own points are), never only said."""
        old = record('old', 'stale_critical', 0, 0, point='loop', tier=1, fresh_now=False)
        new = record('new', 'ok', 0, 1, point='loop', tier=1, fresh_now=True)
        loop = judge.point_verdict([old, new])
        place = judge.place_verdict(new, {'loop': loop}, {'o1'})
        self.assertEqual(place.held and place.held.key, 'old')


class MinuteTests(SimpleTestCase):
    def test_one_minute_is_one_definition(self):
        """Review 6, L5: values at 08:00:10 and 08:00:50 are of one minute (judge.minute), so judged together."""
        early = judge.Record(key='early', point='P', tier=0, measured_at=T0 + timedelta(seconds=10), created_at=T0,
                             id='a', value=True, status=CRITICAL)
        late = judge.Record(key='late', point='P', tier=0, measured_at=T0 + timedelta(seconds=50), created_at=T0,
                            id='b', value=True, status=OK)
        self.assertEqual(judge.point_verdict([early, late]).worst.key, 'early')
        self.assertEqual(judge.minute(T0 + timedelta(seconds=59, microseconds=5)), T0)

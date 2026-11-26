"""The pure judgement of a worked-out water value (farm/water/judge.py), tested exhaustively. No database, no clock: a
SimpleTestCase.

Point scenarios: two to four values at one point, each a critical, a warning, an OK, a refused value (on its basis or
bare), a value-less sample or a value stale from its start, fresh now or not on its own axis, at the same minute or not,
in EVERY order of entry (itertools). The invariants the coordinator set after review 5 of derived-fresh hold in each:
(i) a critical is never hidden by a value that is no evidence;
(ii) a level clears only on evidence fresh now and strictly newer than its last bad value (a tie never clears);
(iii) for values of one minute, the verdict does not depend on the order they were entered in;
(iv) the point is the worst of its judged set.
Place scenarios: two own points and the system's loop, each value shown in turn with the place's judgement: what is held,
what is only said, the attention, the refused record and the value-less ones said. `settled` on every prefix. And the
rules one by one, each the one a mutant of farm/tests/test_judge_mutants.py breaks."""
import dataclasses
import itertools
from datetime import datetime, timedelta, timezone

from django.test import SimpleTestCase

from ..water import judge
from ..water.evaluate import RANK, Status

T0 = datetime(2026, 11, 26, 8, 0, tzinfo=timezone.utc)
CRITICAL, WARNING, OK, UNEVALUATED = Status.CRITICAL, Status.WARNING, Status.OK, Status.UNEVALUATED
ALERTS = (CRITICAL, WARNING)
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


def record(name, kind, minute, created, point='P', fresh_now=None, stored=True, seconds=0):
    """A value of `kind` measured `minute` minutes (and `seconds`) after T0, entered `created` minutes after T0 + 10 h.
    Whether it is fresh NOW is its own axis, apart from whether it was fresh at its own time: by default every other
    entry is fresh now."""
    value, refused, fresh_at_own_time, status = KINDS[kind]
    return judge.Record(key=name, point=point, measured_at=T0 + timedelta(minutes=minute, seconds=seconds),
                        created_at=T0 + timedelta(hours=10, minutes=created), id=name, stored=stored, value=value,
                        refused=refused, fresh_at_own_time=fresh_at_own_time,
                        fresh_now=(created % 2 == 0) if fresh_now is None else fresh_now, status=status)


def key(found):
    """A record's key, None for none: an assertion on it FAILS for a missing record, never crashes."""
    return found.key if found is not None else None


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
        """A critical value of the newest evidence's minute or newer, or the newest evidence itself critical: the point is
        critical."""
        for values in scenarios():
            verdict = judge.point_verdict(values)
            evidence = verdict.evidence
            criticals = [each for each in values if each.value and each.status == CRITICAL
                         and (evidence is None or each.minute >= evidence.minute)]
            if criticals:
                self.assertEqual(verdict.worst.status, CRITICAL, said(values))

    def test_ii_a_level_clears_only_on_evidence_fresh_now_strictly_newer_than_its_last_bad_value(self):
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
                self.assertTrue(all(each.minute >= verdict.evidence.minute for each in verdict.judged))
            else:
                self.assertIsNone(verdict.evidence)
                self.assertEqual(set(verdict.judged), {each for each in values if each.value}, said(values))

    def test_a_value_less_sample_never_takes_the_slot_and_is_said(self):
        for values in scenarios():
            verdict = judge.point_verdict(values)
            self.assertTrue(all(each.value for each in verdict.judged))
            lacking = [each for each in values if not each.value and not each.refused
                       and (verdict.evidence is None or each.order > verdict.evidence.order
                            or each.minute == verdict.evidence.minute)]
            self.assertEqual(verdict.lacking, max(lacking, key=lambda each: each.order) if lacking else None,
                             said(values))


class PointRuleTests(SimpleTestCase):
    """The point rules, each on every scenario."""

    def test_the_worst_prefers_an_evidence_value_of_the_worst_status(self):
        for values in scenarios():
            verdict = judge.point_verdict(values)
            if verdict.worst is None:
                continue
            same = [each for each in verdict.judged if each.status == verdict.worst.status]
            if any(each.evidence for each in same):
                self.assertTrue(verdict.worst.evidence, said(values))

    def test_the_refused_record_is_the_newest_refused_newer_than_the_evidence_or_of_its_minute(self):
        for values in scenarios():
            verdict = judge.point_verdict(values)
            refused = [each for each in values if each.refused
                       and (verdict.evidence is None or each.order > verdict.evidence.order
                            or each.minute == verdict.evidence.minute)]
            self.assertEqual(verdict.refused, max(refused, key=lambda each: each.order) if refused else None,
                             said(values))

    def test_a_late_result_is_never_refused_and_always_of_an_older_minute_entered_later(self):
        for values in scenarios():
            verdict = judge.point_verdict(values)
            for late in verdict.late:
                self.assertFalse(late.refused, said(values))
                self.assertTrue(late.value)
                self.assertLess(late.minute, verdict.superseded_by.minute)
                self.assertGreater(late.created_at, verdict.superseded_by.created_at)
                self.assertNotIn(late, verdict.judged)

    def test_clears_needs_fresh_now_on_its_own_axis(self):
        for kind in KINDS:
            for fresh_now in (True, False):
                value = record('v', kind, 5, 0, fresh_now=fresh_now)
                expected = value.evidence and fresh_now
                self.assertEqual(judge.clears(value, T0), expected, (kind, fresh_now))
                self.assertEqual(judge.clears(value, None), expected, (kind, fresh_now))      # no last bad value known
                self.assertFalse(judge.clears(value, T0 + timedelta(minutes=5)), (kind, fresh_now))

    def test_shown_is_the_worst_else_the_newest(self):
        for values in scenarios():
            verdict = judge.point_verdict(values)
            self.assertEqual(verdict.shown, verdict.worst or max(values, key=lambda each: each.order), said(values))


class ExamplesTests(SimpleTestCase):
    """The reviews' cases and the rules' edges, as the judge says them."""

    def test_a_same_minute_lab_critical_and_kit_ok_are_critical_in_both_entry_orders(self):
        for lab_first in (True, False):
            with self.subTest(lab_first=lab_first):
                lab = record('lab', 'critical', 0, 0 if lab_first else 1)
                kit = record('kit', 'ok', 0, 1 if lab_first else 0)
                self.assertEqual(key(judge.point_verdict([lab, kit]).worst), 'lab')

    def test_a_refused_value_on_its_basis_ahead_of_a_late_lab_critical(self):
        lab = record('lab', 'critical', 0, 5)                        # measured first, entered last
        refused = record('refused', 'refused_basis_ok', 5, 1)
        verdict = judge.point_verdict([lab, refused])
        self.assertEqual((key(verdict.evidence), key(verdict.worst), key(verdict.refused)), ('lab', 'lab', 'refused'))

    def test_a_value_stale_from_its_start_ahead_of_a_critical(self):
        verdict = judge.point_verdict([record('bad', 'critical', 0, 0), record('stale', 'stale_ok', 5, 1)])
        self.assertEqual((key(verdict.evidence), key(verdict.worst)), ('bad', 'bad'))

    def test_a_refused_sample_older_than_the_evidence_is_no_longer_the_points(self):
        verdict = judge.point_verdict([record('refused', 'refused_bare', 0, 0), record('ok', 'ok', 5, 1)])
        self.assertIsNone(verdict.refused)

    def test_of_two_refused_samples_newer_than_the_evidence_the_newest_is_the_points(self):
        verdict = judge.point_verdict([record('ok', 'ok', 0, 0), record('first', 'refused_bare', 5, 1),
                                       record('second', 'refused_bare', 10, 2)])
        self.assertEqual(key(verdict.refused), 'second')

    def test_a_late_result_before_newer_evidence_is_late_never_judged(self):
        ok = record('ok', 'ok', 5, 0)
        lab = record('lab', 'critical', 0, 3)
        verdict = judge.point_verdict([ok, lab])
        self.assertEqual((key(verdict.worst), [each.key for each in verdict.late], key(verdict.superseded_by)),
                         ('ok', ['lab'], 'ok'))

    def test_late_results_are_the_worst_first(self):
        values = [record('ok', 'ok', 30, 0), record('late ok', 'ok', 20, 3), record('late critical', 'critical', 0, 4),
                  record('late warning', 'warning', 10, 5)]
        self.assertEqual([each.key for each in judge.point_verdict(values).late],
                         ['late critical', 'late warning', 'late ok'])

    def test_a_value_of_the_evidences_minute_is_judged_never_late(self):
        """The evidence at 08:00:50, another value at 08:00:10 entered after it: one minute (judge.minute), so judged."""
        evidence = record('evidence', 'ok', 0, 0, seconds=50)
        peer = record('peer', 'critical', 0, 3, seconds=10)
        verdict = judge.point_verdict([evidence, peer])
        self.assertEqual((verdict.late, key(verdict.worst)), ((), 'peer'))
        self.assertEqual(judge.minute(T0 + timedelta(seconds=59, microseconds=5)), T0)

    def test_a_value_entered_at_the_evidences_instant_is_not_late(self):
        evidence = record('evidence', 'ok', 5, 2)
        older = record('older', 'critical', 0, 2)
        self.assertEqual(judge.point_verdict([evidence, older]).late, ())

    def test_a_live_value_takes_no_part_in_what_is_late(self):
        """Late is late against the STORED evidence: a live value is neither late nor what a result is late against."""
        live = record('live', 'ok', 5, 0, stored=False)
        lab = record('lab', 'critical', 0, 3)
        verdict = judge.point_verdict([live, lab])
        self.assertEqual((key(verdict.evidence), verdict.late, key(verdict.superseded_by)), ('live', (), 'lab'))
        stored = record('stored', 'ok', 5, 0)
        earlier_live = record('earlier live', 'critical', 0, 3, stored=False)
        self.assertEqual(judge.point_verdict([stored, earlier_live]).late, ())

    def test_the_order_is_measured_then_entered_then_the_id(self):
        measured_later = record('a', 'ok', 5, 0)
        entered_later = record('b', 'ok', 0, 5)
        self.assertEqual(judge.newest_first([entered_later, measured_later])[0].key, 'a')
        first, second = record('a', 'ok', 0, 0), record('b', 'ok', 0, 0)
        for values in ([first, second], [second, first]):
            self.assertEqual([each.key for each in judge.newest_first(values)], ['b', 'a'])
        self.assertEqual(judge.ORDER_FIELDS, ('measured_at', 'created_at', 'id'))

    def test_of_two_equal_worst_values_the_newest_is_the_worst(self):
        values = [record('old', 'critical', 0, 0), record('new', 'critical', 5, 1)]
        self.assertEqual(judge.worst_of(values).key, 'new')
        self.assertEqual([each.key for each in judge.worst_first([*values, record('ok', 'ok', 10, 2)])],
                         ['new', 'old', 'ok'])

    def test_a_tie_never_clears(self):
        self.assertFalse(judge.clears(record('kit', 'ok', 0, 1, fresh_now=True), T0))
        self.assertTrue(judge.clears(record('kit', 'ok', 5, 1, fresh_now=True), T0))
        self.assertFalse(judge.clears(None, T0))

    def test_a_value_with_no_moment_is_refused_where_fresh_now_is_asked(self):
        """A Record built without a moment (fresh_now None) is never taken for fresh: the judge refuses it."""
        unknown = dataclasses.replace(record('v', 'critical', 0, 0), fresh_now=None)
        with self.assertRaises(ValueError):
            judge.clears(dataclasses.replace(unknown, status=OK), T0 - timedelta(minutes=5))
        shown = record('shown', 'ok', 5, 1, point='Q', fresh_now=True)
        with self.assertRaises(ValueError):
            judge.place_verdict(shown, {'P': judge.point_verdict([unknown]), 'Q': judge.point_verdict([shown])},
                                {'P', 'Q'})

    def test_the_ceiling_never_passes_for_the_whole(self):
        refused = [record(f'r{index}', 'refused_basis_ok', index, index) for index in range(3)]
        self.assertTrue(judge.point_verdict(refused, complete=False).ceiling)
        self.assertFalse(judge.point_verdict(refused).ceiling)
        self.assertFalse(judge.point_verdict([*refused, record('ok', 'ok', 9, 9)], complete=False).ceiling)
        self.assertTrue(judge.over_ceiling(refused, 3))
        self.assertFalse(judge.over_ceiling(refused, 4))
        self.assertFalse(judge.over_ceiling([*refused, record('ok', 'ok', 9, 9)], 3))
        self.assertGreaterEqual(judge.CEILING, 256)
        shown = record('shown', 'ok', 5, 9, point='loop', fresh_now=True)
        place = judge.place_verdict(shown, {'o1': judge.point_verdict(refused, complete=False),
                                            'loop': judge.point_verdict([shown])}, {'o1'})
        self.assertEqual(place.ceiling, ('o1',))

    def test_the_value_less_record_a_place_shows(self):
        own = [record('own old', 'lacking', 0, 0), record('own new', 'lacking', 5, 1)]
        system = [record('system', 'lacking', 10, 2, point='loop')]
        self.assertEqual(judge.shown_without_value([own, system]).key, 'own new')
        self.assertEqual(judge.shown_without_value([[], system]).key, 'system')
        self.assertIsNone(judge.shown_without_value([[], []]))


class PlaceExamplesTests(SimpleTestCase):
    def test_a_held_value_at_an_own_point_and_attention_from_the_system(self):
        outlet = judge.point_verdict([record('outlet', 'critical', 0, 0, point='outlet', fresh_now=False)])
        middle = judge.point_verdict([record('middle', 'ok', 5, 1, point='middle', fresh_now=True)])
        place = judge.place_verdict(middle.worst, {'outlet': outlet, 'middle': middle}, {'outlet', 'middle'})
        self.assertEqual(key(place.held), 'outlet')
        loop = judge.point_verdict([record('loop', 'ok', 0, 0, point='loop', fresh_now=True)])
        own = judge.point_verdict([record('tan', 'lacking', 5, 1, point='middle')])
        place = judge.place_verdict(loop.worst, {'loop': loop, 'middle': own}, {'middle'})
        self.assertTrue(place.attention)
        self.assertEqual([each.key for each in place.said], ['tan'])

    def test_a_loops_refused_sample_is_the_places_when_the_loop_is_read(self):
        loop = judge.point_verdict([record('ok', 'ok', 0, 0, point='loop', fresh_now=True),
                                    record('refused', 'refused_bare', 5, 1, point='loop')])
        place = judge.place_verdict(loop.worst, {'loop': loop}, set())
        self.assertEqual(key(place.refused), 'refused')

    def test_the_systems_refused_sample_counts_when_the_value_shown_has_no_value(self):
        """Review 5's H2 for an own TAN alone shown: nothing of the unit's own is worked out, so the system's is read."""
        own = judge.point_verdict([record('tan', 'lacking', 5, 2, point='o1')])
        loop = judge.point_verdict([record('ok', 'ok', 0, 0, point='loop', fresh_now=True),
                                    record('refused', 'refused_bare', 3, 1, point='loop')])
        place = judge.place_verdict(own.shown, {'o1': own, 'loop': loop}, {'o1'})
        self.assertEqual(key(place.refused), 'refused')

    def test_of_the_tiers_refused_samples_the_newest_is_the_places(self):
        first = judge.point_verdict([record('first', 'refused_bare', 0, 0, point='o1')])
        second = judge.point_verdict([record('second', 'refused_bare', 5, 1, point='o2')])
        shown = record('shown', 'ok', 10, 2, point='o1', fresh_now=True)
        place = judge.place_verdict(shown, {'o1': first, 'o2': second}, {'o1', 'o2'})
        self.assertEqual(key(place.refused), 'second')

    def test_an_older_stale_alert_at_the_system_point_shown_is_held(self):
        """The point shown is the system's loop: a stale critical of its judged set entered before the value shown (the
        same minute) is held, as at an own point, never only said."""
        old = record('old', 'stale_critical', 0, 0, point='loop', fresh_now=False)
        new = record('new', 'ok', 0, 1, point='loop', fresh_now=True)
        place = judge.place_verdict(new, {'loop': judge.point_verdict([old, new])}, {'o1'})
        self.assertEqual((key(place.held), place.older), ('old', ()))

    def test_a_fresh_alert_is_never_held(self):
        """A hold is of a value stale NOW: a fresh critical is the worst fresh value's to say (read.worst_fresh), never
        held (a value ahead of the clock is fresh by its own freshness or not, and nothing else)."""
        fresh = record('fresh', 'critical', 0, 0, point='o1', fresh_now=True)
        shown = record('shown', 'ok', 5, 1, point='o2', fresh_now=True)
        place = judge.place_verdict(shown, {'o1': judge.point_verdict([fresh]), 'o2': judge.point_verdict([shown])},
                                    {'o1', 'o2'})
        self.assertIsNone(place.held)

    def test_a_point_read_on_its_own_holds_as_the_point_shown(self):
        """Review 7, M5: an outlet's own row: the lab's critical and the kit's OK of one minute, both stale now, the kit
        shown: the critical is held."""
        lab = record('lab', 'critical', 0, 0, point='outlet', fresh_now=False)
        kit = record('kit', 'ok', 0, 1, point='outlet', fresh_now=False)
        place = judge.place_verdict(kit, {'outlet': judge.point_verdict([lab, kit])}, {'outlet'})
        self.assertEqual(key(place.held), 'lab')

    def test_a_points_late_alert_is_said_with_its_own_evidence_and_an_ok_one_is_not(self):
        """The owner's decision: a late result judged critical or a warning is said by the place with the evidence OF ITS
        POINT that superseded it, whatever value the place shows; a late OK is not said."""
        for kind, expected in (('critical', True), ('warning', True), ('ok', False)):
            evidence = record('evidence', 'ok', 5, 0, point='o1', fresh_now=True)
            late = record('late', kind, 0, 3, point='o1', fresh_now=False)
            shown = record('other', 'ok', 9, 1, point='o2', fresh_now=True)
            place = judge.place_verdict(shown, {'o1': judge.point_verdict([evidence, late]),
                                                'o2': judge.point_verdict([shown])}, {'o1', 'o2'})
            self.assertEqual([(each.key, newer.key) for each, newer in place.late],
                             [('late', 'evidence')] if expected else [], kind)
            self.assertIsNone(place.held)


PLACE_KINDS = ('critical', 'warning', 'ok', 'refused_basis_ok', 'stale_critical')
VALUE_LESS = ('lacking', 'refused_bare')


def place_scenarios():
    """Two own points and the system's loop, each with no value or one value (of PLACE_KINDS fresh now or not, or
    value-less), at minute 0 or 5; the value shown each of their values in turn, with the place's judgement: the worst of
    it and of every fresh value of the place (the worst fresh value, read.worst_fresh)."""
    choices = [None, *((kind, minute, fresh) for kind in PLACE_KINDS for minute in (0, 5) for fresh in (True, False)),
               *((kind, minute, True) for kind in VALUE_LESS for minute in (0, 5))]
    for o1, o2, loop in itertools.product(choices, repeat=3):
        values = {}
        for index, (point, choice) in enumerate((('o1', o1), ('o2', o2), ('loop', loop))):
            if choice is not None:
                kind, minute, fresh = choice
                values[point] = record(point, kind, minute, index, point=point, fresh_now=fresh)
        verdicts = {point: judge.point_verdict([value]) for point, value in values.items()}
        fresh = [each.status for each in values.values() if each.value and each.fresh_now]
        for shown in (each for each in values.values() if each.value):
            status = min([shown.status, *fresh], key=RANK.__getitem__)
            yield values, verdicts, dataclasses.replace(shown, status=status)


OWN = {'o1', 'o2'}


class PlaceTests(SimpleTestCase):
    """The place rules on every place scenario."""

    def test_the_place_scenarios_are_many(self):
        self.assertGreater(sum(1 for _scenario in place_scenarios()), 10000)

    def test_held_is_stale_an_alert_worse_than_shown_and_never_also_late_or_older(self):
        for values, verdicts, shown in place_scenarios():
            verdict = judge.place_verdict(shown, verdicts, OWN)
            held = verdict.held
            if held is not None:
                self.assertFalse(held.fresh_now)
                self.assertIn(held.status, ALERTS)
                self.assertLess(RANK[held.status], RANK[shown.status])
                self.assertNotIn(held.key, [late.key for late, _newer in verdict.late])
                self.assertNotIn(held.key, [each.key for each in verdict.older])

    def test_every_stale_worse_alert_is_held_or_said_as_older(self):
        """An own point's, the point shown's, or the system's newer than the value shown: held, or a worse one is. The
        system's older than the value shown: said (`older`), never held."""
        for values, verdicts, shown in place_scenarios():
            verdict = judge.place_verdict(shown, verdicts, OWN)
            older = [each.key for each in verdict.older]
            for point, value in values.items():
                if not (value.value and not value.fresh_now and value.status in ALERTS
                        and RANK[value.status] < RANK[shown.status]):
                    self.assertNotIn(value.key, older)
                    continue
                if point != 'loop' or shown.point == 'loop' or value.order > shown.order:
                    self.assertIsNotNone(verdict.held, (point, shown.point))
                    self.assertLessEqual(RANK[verdict.held.status], RANK[value.status])
                    self.assertNotIn(value.key, older)
                else:
                    self.assertIn(value.key, older, (point, shown.point))
                    self.assertTrue(verdict.held is None or key(verdict.held) != value.key)

    def test_attention_only_turns_an_ok_value_of_the_system_and_never_beside_a_held_value(self):
        seen = 0
        for values, verdicts, shown in place_scenarios():
            verdict = judge.place_verdict(shown, verdicts, OWN)
            newer_lacking = any(verdicts[point].lacking is not None and verdicts[point].lacking.order > shown.order
                                for point in OWN if point in verdicts)
            expected = shown.point == 'loop' and shown.status == OK and newer_lacking and verdict.held is None
            self.assertEqual(verdict.attention, expected, (shown.point, shown.status))
            seen += shown.point == 'loop' and shown.status == OK and newer_lacking and verdict.held is not None
        self.assertGreater(seen, 0)                 # the two conditions do meet: a held value beside a newer lacking one

    def test_the_value_less_records_are_said_and_only_they(self):
        for values, verdicts, shown in place_scenarios():
            verdict = judge.place_verdict(shown, verdicts, OWN)
            self.assertEqual({each.key for each in verdict.said},
                             {each.key for each in values.values() if not each.value})

    def test_the_refused_record_is_the_newest_of_the_tier_read(self):
        for values, verdicts, shown in place_scenarios():
            verdict = judge.place_verdict(shown, verdicts, OWN)
            tier = [each for point, each in values.items()
                    if each.refused and (point in OWN or shown.point == 'loop')]
            self.assertEqual(verdict.refused, max(tier, key=lambda each: each.order) if tier else None,
                             (shown.point, said(values.values())))


def candidates_of(values):
    """What the shell's evidence stream fetches: the values that may give one (a value, or refused by the core)."""
    return [each for each in values if each.value or each.refused]


class SettledTests(SimpleTestCase):
    """The shell stops a point's look-back when `settled` says so: on ANY prefix it says settled, the verdict must be the
    full one's."""

    def test_a_settled_prefix_gives_the_full_verdict(self):
        checked = early = 0
        for values in scenarios():
            candidates = judge.newest_first(candidates_of(values))
            valueless = [each for each in values if not each.value and not each.refused]
            full = judge.point_verdict(values)
            for size in range(1, len(candidates) + 1):
                if not judge.settled(candidates[:size], exhausted=size == len(candidates)):
                    continue
                checked += 1
                early += size < len(candidates)
                prefix = judge.point_verdict([*candidates[:size], *valueless])
                self.assertEqual((prefix.evidence, set(prefix.judged), prefix.worst and prefix.worst.status,
                                  prefix.refused),
                                 (full.evidence, set(full.judged), full.worst and full.worst.status, full.refused),
                                 (size, said(values)))
                break
        self.assertGreater(checked, 1000)
        self.assertGreater(early, 100)              # it does stop early: before the last candidate

    def test_it_never_settles_without_evidence_while_there_are_more(self):
        refused = [record(f'r{index}', 'refused_basis_ok', index, index) for index in range(4)]
        self.assertFalse(judge.settled(refused, exhausted=False))
        self.assertTrue(judge.settled(refused, exhausted=True))
        self.assertFalse(judge.settled([record('ok', 'ok', 5, 0), record('peer', 'ok', 5, 1)], exhausted=False))
        self.assertTrue(judge.settled([record('ok', 'ok', 5, 0), record('older', 'ok', 0, 1)], exhausted=False))

"""A fixed list of named regressions of the pure judge (farm/water/judge.py), each of which its tests must catch. It is
NOT mutation testing: it is the mutants the reviewers of derived-fresh wrote (reviews 6 and 7) and the rules this branch
added, one line of the judge changed each. Each mutant is built in memory, put in the judge's place, and the test
classes that guard its rule (in farm/tests/test_judge.py) are run against it: at least one test must FAIL. A test that
only crashes is no kill (an error checks no rule). A text of the judge that is no longer found once fails loudly here,
so an edit of those lines is an edit of this list in the same commit. No database: a SimpleTestCase."""
import inspect
import types
import unittest
from unittest import mock

from django.test import SimpleTestCase

from ..water import judge
from . import test_judge

# The classes of farm/tests/test_judge.py: the examples (fast), and the enumerations.
E, PE = ('ExamplesTests',), ('PlaceExamplesTests',)
POINT, PLACE = ('InvariantTests', 'PointRuleTests'), ('PlaceTests',)
# (name, the judge's own text, the mutant's, the test classes that guard the rule)
MUTANTS = [
    ('no same minute in the judged set',
     'record for record in ordered if record.order > evidence.order or record.minute == evidence.minute]',
     'record for record in ordered if record.order > evidence.order]', E),
    ('the judged set is the evidence alone',
     'judged = tuple(record for record in newer if record.value)', 'judged = (evidence,) if evidence else ()', E),
    ('the worst is the newest', 'key=lambda record: (RANK[record.status], not record.evidence), default=None)',
     'key=lambda record: 0, default=None)', E),
    ('the worst prefers a value that is no evidence',
     'key=lambda record: (RANK[record.status], not record.evidence), default=None)',
     'key=lambda record: (RANK[record.status], record.evidence), default=None)', POINT),
    ('of two equal worst values the oldest', 'return min(newest_first(records), key=',
     'return min(sorted(records, key=lambda record: record.order), key=', E),
    ('a tie clears', 'decider.measured_at > last_bad_at', 'decider.measured_at >= last_bad_at', E),
    ('clears ignores fresh_now', 'decider.evidence and _fresh_now(decider)', 'decider.evidence', POINT),
    ('no last bad value: never clears', '(last_bad_at is None or decider.measured_at > last_bad_at)',
     '(last_bad_at is not None and decider.measured_at > last_bad_at)', POINT),
    ('a value with no moment is fresh', 'if record.fresh_now is None:', 'if False:', E),
    ('evidence ignores refused', 'return self.value and not self.refused and self.fresh_at_own_time',
     'return self.value and self.fresh_at_own_time', E),
    ('evidence ignores fresh at its own time', 'return self.value and not self.refused and self.fresh_at_own_time',
     'return self.value and not self.refused', E),
    ('the order has no id', "ORDER_FIELDS = ('measured_at', 'created_at', 'id')",
     "ORDER_FIELDS = ('measured_at', 'created_at')", E),
    ('the order is entered before measured', "ORDER_FIELDS = ('measured_at', 'created_at', 'id')",
     "ORDER_FIELDS = ('created_at', 'measured_at', 'id')", E),
    ('the refused record of any age', 'next((record for record in newer if record.refused), None), late, stored,',
     'next((record for record in ordered if record.refused), None), late, stored,', E),
    ('the oldest refused record newer than the evidence',
     'next((record for record in newer if record.refused), None), late, stored,',
     'next((record for record in reversed(newer) if record.refused), None), late, stored,', E),
    ('lacking includes refused', 'next((record for record in newer if not record.value and not record.refused), None),',
     'next((record for record in newer if not record.value), None),', POINT),
    ('late includes refused', 'record.stored and record.value and not record.refused',
     'record.stored and record.value', E),
    ('late without a value', 'record.stored and record.value and not record.refused',
     'record.stored and not record.refused', POINT),
    ('late by an older order, not an older minute', 'and record.minute < evidence.minute',
     'and record.order < evidence.order', POINT),
    ('late when entered at the same instant', 'or record.created_at > stored.created_at)))',
     'or record.created_at >= stored.created_at)))', E),
    ('a live value is late', 'record for record in ordered if record.stored and record.value',
     'record for record in ordered if record.value', ('LiveLateTests',)),
    ('late never against a live evidence (review 7)', 'late = () if evidence is None else tuple(worst_first(',
     'late = () if stored is None else tuple(worst_first(', ('LiveLateTests',)),
    ('behind a live value only what is entered late',
     '(stored is None or record.minute >= stored.minute or record.created_at > stored.created_at)',
     '(stored is None or record.created_at > stored.created_at)', ('LiveLateTests',)),
    ('behind a live value every stored value is late',
     '(stored is None or record.minute >= stored.minute or record.created_at > stored.created_at)', 'True',
     POINT),
    ('superseded always by the stored evidence', 'stored.minute > late.minute else self.evidence',
     'True else self.evidence', ('LiveLateTests',)),
    ('superseded always by the evidence', 'stored.minute > late.minute else self.evidence',
     'False else self.evidence', POINT),
    ('late results are the newest first', 'late = () if evidence is None else tuple(worst_first(',
     'late = () if evidence is None else tuple(newest_first(', E),
    ('a late value stale from its start is dropped', 'record.stored and record.value and not record.refused',
     'record.stored and record.evidence', E),
    ('the ceiling is a bound only', 'CEILING = 512', 'CEILING = 10 ** 9', E),
    ('the ceiling passes for the whole', 'not complete and evidence is None)', 'False)', E),
    ('the ceiling is never reached',
     'return len(candidates) >= ceiling and point_verdict(candidates).evidence is None', 'return False', E),
    ('the ceiling stops a point with evidence',
     'return len(candidates) >= ceiling and point_verdict(candidates).evidence is None',
     'return len(candidates) >= ceiling', E),
    ('the value-less record shown is the oldest', 'next((newest_first(tier)[0] for tier in tiers if tier), None)',
     'next((newest_first(tier)[-1] for tier in tiers if tier), None)', E),
    ('settled always', '    if exhausted:', '    if True:', ('SettledTests',)),
    ('settled on the evidence alone',
     'return evidence is not None and any(record.minute < evidence.minute for record in candidates)',
     'return evidence is not None', ('SettledTests',)),
    ('held ignores fresh_now', 'if _fresh_now(record) or record.status not in ALERTS or',
     'if record.status not in ALERTS or', PE),
    ('as bad as the value shown is held', 'or RANK[record.status] >= shown_rank:', 'or RANK[record.status] > shown_rank:',
     PLACE),
    ('a stale "cannot be evaluated" is held', 'or record.status not in ALERTS or',
     'or record.status not in (*ALERTS, Status.UNEVALUATED) or', PLACE),
    ('held only of own points', 'if point in own_points or point == shown.point or record.order > shown.order:',
     'if point in own_points or record.order > shown.order:', PE),
    ('the system never held', 'if point in own_points or point == shown.point or record.order > shown.order:',
     'if point in own_points or point == shown.point:', PLACE),
    ('the system older than the value shown held',
     'if point in own_points or point == shown.point or record.order > shown.order:', 'if True:', PLACE),
    ('the system older than the value shown never said', 'tuple(worst_first(older)),', '(),', PLACE),
    ('the refused record never of the system', 'if point in own_points or from_system or not shown.value}',
     'if point in own_points}', PE),
    ('the refused record not of the system when the value shown has no value',
     'if point in own_points or from_system or not shown.value}', 'if point in own_points or from_system}', PE),
    ('the oldest refused record of the tier', 'refused = max((verdict.refused', 'refused = min((verdict.refused', PE),
    ('a refused sample without a value is not said', 'for record in (verdict.lacking, verdict.refused)',
     'for record in (verdict.lacking,)', PLACE),
    ('a refused value on its basis is said as giving no value',
     'if record is not None and not record.value and record.key is not shown.key)',
     'if record is not None and record.key is not shown.key)', PLACE),
    ('late off', 'for record in verdict.late if record.status in ALERTS))',
     'for record in verdict.late if False))', PE),
    ('a late result superseded by the value shown', 'late = tuple((record, superseded[id(record)]) for record in',
     'late = tuple((record, shown) for record in', PE),
    ("the place's late results the newest first", 'late = tuple((record, superseded[id(record)]) for record in worst_first(',
     'late = tuple((record, superseded[id(record)]) for record in newest_first(', PE),
    ("the place's late results point by point", 'late = tuple((record, superseded[id(record)]) for record in worst_first(',
     'late = tuple((record, superseded[id(record)]) for record in list(', PE),
    ('the ceiling of every point, not of the tier read', 'tuple(point for point, verdict in tier.items() if verdict.ceiling))',
     'tuple(point for point, verdict in points.items() if verdict.ceiling))', PE),
    ('the value-less record shown said again', 'if record is not None and not record.value and record.key is not shown.key)',
     'if record is not None and not record.value)', PE),
    ("the system's older alerts the newest first", 'tuple(worst_first(older)),', 'tuple(newest_first(older)),', PE),
    ('attention off', 'attention = (from_system and held is None', 'attention = (False and held is None', PE),
    ('attention beside a held value', 'attention = (from_system and held is None and', 'attention = (from_system and',
     PLACE),
    ('attention for any status', 'and shown.status == Status.OK', 'and shown.status != Status.CRITICAL', PLACE),
    ('attention for an own value shown', 'attention = (from_system and held is None', 'attention = (held is None',
     PLACE),
    ('the ceiling of a point is not the place\'s', 'tuple(point for point, verdict in tier.items() if verdict.ceiling))',
     '())', E),
]
PUBLIC = ('ORDER_FIELDS', 'CEILING', 'minute', 'Record', 'PointVerdict', 'newest_first', 'worst_first', 'point_verdict',
          'worst_of', 'settled', 'over_ceiling', 'shown_without_value', 'PlaceVerdict', 'place_verdict', 'clears')


def mutant_module(original, mutated):
    source = inspect.getsource(judge)
    assert source.count(original) == 1, f'not once in the judge: {original}'
    module = types.ModuleType('judge_mutant')
    module.__dict__['__name__'] = 'farm.water.judge_mutant'
    code = source.replace(original, mutated).replace('from .evaluate import', 'from farm.water.evaluate import')
    exec(compile(code, 'judge_mutant', 'exec'), module.__dict__)
    return module


def run_against(module, classes=None):
    """(failures, errors) of farm/tests/test_judge.py's tests (of `classes`, else all) with `module` in the judge's place."""
    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite(loader.loadTestsFromTestCase(getattr(test_judge, name)) for name in classes) \
        if classes else loader.loadTestsFromModule(test_judge)
    with mock.patch.multiple(judge, **{name: getattr(module, name) for name in PUBLIC}):
        result = unittest.TestResult()
        suite.run(result)
    return len(result.failures), len(result.errors)


class MutantTests(SimpleTestCase):
    def test_the_judge_itself_passes(self):
        self.assertEqual(run_against(judge), (0, 0))

    def test_every_listed_mutant_fails_a_test_of_its_rule(self):
        """Killed means a test FAILED (an assertion about a rule); a mutant whose tests only crash survives."""
        survived = [name for name, original, mutated, classes in MUTANTS
                    if not run_against(mutant_module(original, mutated), classes)[0]]
        self.assertEqual(survived, [])

    def test_the_guard_classes_exist(self):
        for _name, _original, _mutated, classes in MUTANTS:
            for name in classes:
                self.assertTrue(issubclass(getattr(test_judge, name), SimpleTestCase), name)

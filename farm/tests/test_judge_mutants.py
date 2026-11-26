"""The pure judge's tests kill its mutants (review 6, M5): each mutant of farm/water/judge.py (the reviewer's list, and
the system-tier rule of M7) is built in memory, put in the judge's place, and farm/tests/test_judge.py must FAIL against
it. A mutant that survives means a rule of the judge no test holds. No database: a SimpleTestCase."""
import inspect
import types
import unittest
from unittest import mock

from django.test import SimpleTestCase

from ..water import judge
from . import test_judge

# (name, the judge's own text, the mutant's) — each text found exactly once in farm/water/judge.py.
MUTANTS = [
    ('no same minute in the judged set',
     'record.order > evidence.order or record.minute == evidence.minute]', 'record.order > evidence.order]'),
    ('the judged set is the evidence alone',
     'judged = tuple(record for record in newer if record.value)', 'judged = (evidence,) if evidence else ()'),
    ('the worst is the newest',
     "key=lambda record: (RANK[record.status], not record.evidence), default=None)",
     "key=lambda record: 0, default=None)"),
    ('the worst prefers a value that is no evidence',
     "key=lambda record: (RANK[record.status], not record.evidence), default=None)",
     "key=lambda record: (RANK[record.status], record.evidence), default=None)"),
    ('a tie clears', 'decider.measured_at > last_bad_at', 'decider.measured_at >= last_bad_at'),
    ('clears ignores fresh_now', 'decider.evidence and decider.fresh_now', 'decider.evidence'),
    ('evidence ignores refused', 'return self.value and not self.refused and self.fresh_at_own_time',
     'return self.value and self.fresh_at_own_time'),
    ('evidence ignores fresh at its own time', 'return self.value and not self.refused and self.fresh_at_own_time',
     'return self.value and not self.refused'),
    ('the refused record never of the system',
     'if point in own_points or from_system or shown is None or not shown.value]', 'if point in own_points]'),
    ('the refused record of any age',
     'next((record for record in newer if record.refused), None), late)',
     'next((record for record in ordered if record.refused), None), late)'),
    ('lacking includes refused', 'next((record for record in newer if not record.value and not record.refused), None)',
     'next((record for record in newer if not record.value), None)'),
    ('attention off', 'attention = (for_unit and from_system', 'attention = (False and from_system'),
    ('late off', "if record.status in ALERTS),", 'if False),'),
    ('late includes refused', 'and record.created_at > evidence.created_at and record.value and not record.refused)',
     'and record.created_at > evidence.created_at and record.value)'),
    ('held ignores fresh_now', 'and not record.fresh_now and record.status in ALERTS', 'and record.status in ALERTS'),
    ('held only of own points',
     'if point in own_points or point == shown_point or shown is None or record.order > shown.order:',
     'if point in own_points or shown is None or record.order > shown.order:'),
    ('the system never held (M7)',
     'if point in own_points or point == shown_point or shown is None or record.order > shown.order:',
     'if point in own_points or point == shown_point or shown is None:'),
    ('the system older than shown never said (M7)', '*((record, shown) for record in system_late))', ')'),
    ('settled always', '    if exhausted:\n        return True\n    evidence', '    if True:\n        return True\n    evidence'),
    ('settled on the evidence alone',
     'return evidence is not None and any(record.minute < evidence.minute for record in candidates)',
     'return evidence is not None'),
]
PUBLIC = ('ORDER_FIELDS', 'minute', 'Record', 'PointVerdict', 'newest_first', 'point_verdict', 'worst_of', 'settled',
          'PlaceVerdict', 'place_verdict', 'clears')


def mutant_module(original, mutated):
    source = inspect.getsource(judge)
    assert source.count(original) == 1, original
    module = types.ModuleType('judge_mutant')
    module.__dict__['__name__'] = 'farm.water.judge_mutant'
    code = source.replace(original, mutated).replace('from .evaluate import', 'from farm.water.evaluate import')
    exec(compile(code, 'judge_mutant', 'exec'), module.__dict__)
    return module


def failures_against(module):
    """How many of farm/tests/test_judge.py's tests fail with `module` in the judge's place."""
    suite = unittest.defaultTestLoader.loadTestsFromModule(test_judge)
    with mock.patch.multiple(judge, **{name: getattr(module, name) for name in PUBLIC}):
        result = unittest.TestResult()
        result.failfast = True
        suite.run(result)
    return len(result.failures) + len(result.errors)


class MutantTests(SimpleTestCase):
    def test_the_judge_itself_passes(self):
        self.assertEqual(failures_against(judge), 0)

    def test_every_mutant_is_killed(self):
        survived = [name for name, original, mutated in MUTANTS
                    if not failures_against(mutant_module(original, mutated))]
        self.assertEqual(survived, [])

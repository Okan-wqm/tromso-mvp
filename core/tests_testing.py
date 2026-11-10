"""The tests' clock (core/testing.py): FrozenClock holds `timezone.now()` at the class's NOW while its data is made and
in each of its tests, and gives the real clock back afterwards, also when the class's set-up fails."""
import unittest
from datetime import datetime, timedelta, timezone as utc

from django.test import SimpleTestCase
from django.utils import timezone

from core.testing import FrozenClock

THEN = datetime(2026, 10, 17, tzinfo=utc.utc)


def run(case):
    result = unittest.TestResult()
    unittest.defaultTestLoader.loadTestsFromTestCase(case).run(result)
    return result


class FrozenClockTests(SimpleTestCase):
    def test_the_clock_stands_at_now_for_the_class_data_and_each_test_and_runs_again_afterwards(self):
        seen = {}

        class Held(FrozenClock, unittest.TestCase):
            NOW = THEN

            @classmethod
            def setUpClass(cls):
                super().setUpClass()
                seen['class data'] = timezone.now()

            def test_one(self):
                seen['test'] = (timezone.now(), timezone.localdate(timezone=utc.utc))

            def test_two(self):
                seen['later test'] = timezone.now()

        result = run(Held)
        self.assertEqual((result.testsRun, result.errors, result.failures), (2, [], []))
        self.assertEqual(seen, {'class data': THEN, 'test': (THEN, THEN.date()), 'later test': THEN})
        self.assertLess(abs(timezone.now() - datetime.now(utc.utc)), timedelta(minutes=1))

    def test_a_failing_set_up_gives_the_real_clock_back(self):
        class Broken(FrozenClock, unittest.TestCase):
            NOW = THEN

            @classmethod
            def setUpClass(cls):
                super().setUpClass()
                raise RuntimeError('the class data could not be made')

            def test_one(self):
                raise AssertionError('never run')

        result = run(Broken)
        self.assertEqual((result.testsRun, len(result.errors)), (0, 1))
        self.assertLess(abs(timezone.now() - datetime.now(utc.utc)), timedelta(minutes=1))

    def test_a_class_without_an_aware_now_is_refused(self):
        for moment in (None, datetime(2026, 10, 17)):
            class Unset(FrozenClock, unittest.TestCase):
                NOW = moment

                def test_one(self):
                    raise AssertionError('never run')

            with self.subTest(moment=moment):
                result = run(Unset)
                self.assertEqual((result.testsRun, len(result.errors)), (0, 1))
                self.assertIn('an aware datetime', result.errors[0][1])

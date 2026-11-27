"""The tests' clock (core/testing.py): FrozenClock holds `timezone.now()` at the class's NOW while its data is made and
in each of its tests, and gives the real clock back afterwards, also when the class's set-up fails. And `reads`: what
each statement of a block read and handed back, counted by the database."""
import threading
import unittest
from datetime import datetime, timedelta, timezone as utc

from django.contrib.auth.models import Group
from django.db import IntegrityError, connection, connections, transaction
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from core.testing import FrozenClock, Unmeasured, assert_reads_do_not_grow, reads

THEN = datetime(2026, 10, 17, tzinfo=utc.utc)
GIVEN = timezone.now            # the clock as the run gave it, the same function object a test must leave behind


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
        self.assertIs(timezone.now, GIVEN)                                 # the clock given back

    def test_a_started_clock_starts_at_now_runs_on_and_is_given_back(self):
        import time

        from core.testing import StartedClock
        seen = []

        class Running(StartedClock, unittest.TestCase):
            NOW = THEN

            def test_one(self):
                seen.append(timezone.now())
                time.sleep(0.02)
                seen.append(timezone.now())

        result = run(Running)
        self.assertEqual((result.testsRun, result.errors, result.failures), (1, [], []))
        first, second = seen
        self.assertLessEqual(THEN, first)
        self.assertLess(first, second)                                   # two records are told apart by their time
        self.assertLess(second - THEN, timedelta(seconds=30))            # and the day is still NOW's
        self.assertIs(timezone.now, GIVEN)                                 # the clock given back

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
        self.assertIs(timezone.now, GIVEN)                                 # the clock given back

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


class BadHoursTests(SimpleTestCase):
    """core.testing.at_bad_hours: a test class run again with the clock held at each moment when the server's day (UTC)
    is not the company's (core/tests_day_boundary.py)."""

    def test_every_bad_hour_but_the_one_just_before_midnight_is_another_day_in_oslo_than_on_the_server(self):
        from zoneinfo import ZoneInfo

        from core.testing import BAD_HOURS
        oslo = ZoneInfo('Europe/Oslo')
        ahead = {name: (moment.astimezone(oslo).date() - moment.date()).days for name, moment in BAD_HOURS.items()}
        self.assertEqual(ahead, {'WinterNight': 1, 'SummerNight': 1, 'JustBeforeOslosMidnight': 0,
                                 'JustAfterOslosMidnight': 1, 'NewYearsEve': 1})
        self.assertEqual(BAD_HOURS['NewYearsEve'].astimezone(oslo).year, BAD_HOURS['NewYearsEve'].year + 1)

    def test_a_class_is_made_for_each_moment_with_its_clock_held_there(self):
        from core.testing import at_bad_hours
        seen = {}

        class Counted(unittest.TestCase):
            def test_one(self):
                seen[type(self).__name__] = timezone.now()

        later = THEN + timedelta(days=1)
        module = {'__name__': 'somewhere.tests'}
        at_bad_hours(module, Counted, moments={'Then': THEN, 'Later': later})
        self.assertEqual(sorted(name for name in module if name != '__name__'), ['CountedAtLater', 'CountedAtThen'])
        for made in (module['CountedAtThen'], module['CountedAtLater']):
            self.assertEqual((made.__module__, issubclass(made, Counted), issubclass(made, FrozenClock)),
                             ('somewhere.tests', True, True))
            result = run(made)
            self.assertEqual((result.testsRun, result.errors, result.failures), (1, [], []))
        self.assertEqual(seen, {'CountedAtThen': THEN, 'CountedAtLater': later})       # the original was not run here


class RunClockTests(SimpleTestCase):
    """core.testing.run_clock: a whole run's clock started at a moment (TEST_CLOCK) and running on from there."""

    def test_without_a_moment_there_is_no_clock_and_a_moment_without_its_offset_is_refused(self):
        from unittest import mock

        from core.testing import run_clock
        with mock.patch.dict('os.environ', {'TEST_CLOCK': ''}):
            self.assertIsNone(run_clock())
        with self.assertRaisesMessage(ValueError, 'give its offset'):
            run_clock('2026-11-10T23:30:00')
        self.assertIs(timezone.now, GIVEN)                                 # the clock given back

    def test_the_clock_starts_at_the_moment_runs_on_and_is_given_back(self):
        import time
        from unittest import mock

        from core.testing import run_clock
        real = timezone.now
        with mock.patch.dict('os.environ', {'TEST_CLOCK': '2026-11-10T23:30:00+00:00'}):
            clock = run_clock()
        try:
            first = timezone.now()
            time.sleep(0.02)
            second = timezone.now()
        finally:
            clock.stop()
        start = datetime(2026, 11, 10, 23, 30, tzinfo=utc.utc)
        self.assertLessEqual(start, first)
        self.assertLess(first, second)                                   # it runs on: time passes in a run
        self.assertLess(second - start, timedelta(seconds=30))
        self.assertIs(timezone.now, real)


class ReadsTests(TestCase):
    """core.testing.reads: what a block read of each table and what each statement handed back, counted by PostgreSQL;
    nothing left out on its connection, and what it cannot see (another thread's statements, a server-side cursor's
    rows) refused, never a silent zero."""

    @classmethod
    def setUpTestData(cls):
        Group.objects.bulk_create(Group(name=f'reads {number:04d}') for number in range(2000))
        with connection.cursor() as cursor:
            cursor.execute('ANALYZE auth_group')
        cls.total = Group.objects.count()

    def test_a_lookup_by_key_reads_its_entry_and_a_filter_without_an_index_reads_the_table(self):
        keys = list(Group.objects.filter(name__startswith='reads').values_list('pk', flat=True)[:3])
        with reads() as by_key:
            list(Group.objects.filter(pk__in=keys))
        with reads() as by_text:
            list(Group.objects.filter(name__endswith='7'))
        self.assertEqual(by_key.read('auth_group'), 3, by_key.reads())                  # exactly: no rounding
        self.assertEqual(by_text.read('auth_group'), self.total, by_text.reads())
        self.assertEqual(by_text.most_returned('auth_group'), Group.objects.filter(name__endswith='7').count())
        self.assertEqual(by_text.most_returned('auth_permission'), 0)
        self.assertRegex(by_text.described('auth_group'), rf'^{self.total:,} rows: SELECT .*"auth_group"')

    def test_every_statement_of_the_connection_is_counted_however_it_is_written(self):
        with reads() as union:                                          # Django writes "(SELECT ...) UNION (SELECT ...)"
            list(Group.objects.filter(name__endswith='1').union(Group.objects.filter(name__endswith='2')))
        with reads() as many, connection.cursor() as cursor:
            cursor.executemany('SELECT count(*) FROM auth_group WHERE name LIKE %s', [['%3'], ['%4']])
        with reads() as numbered, connection.cursor() as cursor:
            cursor.execute("SELECT count(*), nextval('auth_group_id_seq') FROM auth_group WHERE name LIKE '%%5'")
        self.assertEqual(union.read('auth_group'), 2 * self.total, union.reads())
        self.assertEqual(many.read('auth_group'), 2 * self.total, many.reads())
        self.assertEqual(numbered.read('auth_group'), self.total, numbered.reads())

    def test_a_write_is_done_once_and_a_failing_one_fails_as_it_would(self):
        with reads() as found:
            Group.objects.create(name='once')
        self.assertEqual(Group.objects.filter(name='once').count(), 1)
        self.assertEqual([statement.returned for statement in found], [1])          # (its id, RETURNING)
        with reads(), self.assertRaises(IntegrityError), transaction.atomic():
            Group.objects.create(name='once')
        self.assertEqual(Group.objects.filter(name='once').count(), 1)

    def test_what_it_cannot_see_is_refused_never_a_silent_zero(self):
        def elsewhere():
            try:
                list(Group.objects.filter(name__endswith='9'))       # another thread: its own connection
            finally:
                connections.close_all()
        with reads() as found:
            thread = threading.Thread(target=elsewhere)
            thread.start()
            thread.join(60)
        with self.assertRaisesMessage(Unmeasured, 'another thread'):
            found.read('auth_group')
        with self.assertRaisesMessage(Unmeasured, 'another thread'):
            found.most_returned('auth_group')
        self.assertEqual(found.read('auth_permission'), 0)              # a table none of them names: answered
        with transaction.atomic(), reads() as fetched:
            for _group in Group.objects.filter(name__endswith='8').iterator(chunk_size=10):   # a server-side cursor
                pass
        with self.assertRaisesMessage(Unmeasured, 'server-side cursor'):
            fetched.most_returned('auth_group')
        self.assertEqual(fetched.read('auth_group'), self.total)         # its rows are counted all the same

    def test_parallel_workers_are_off_in_the_block_and_given_back(self):
        """A parallel plan's workers read in processes whose counters are not the transaction's: none in the block."""
        def workers():
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_setting('max_parallel_workers_per_gather')")
                return cursor.fetchone()[0]
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config('max_parallel_workers_per_gather', '3', true)")
        with reads():
            self.assertEqual(workers(), '0')
        self.assertEqual(workers(), '3')

    def test_a_read_that_grows_with_the_history_is_refused_and_one_by_key_is_not(self):
        import contextlib
        added = []

        class Recorder:                       # the assertions as a test makes them, recorded
            def __init__(self):
                self.failed = []

            def subTest(self, **kwargs):
                return contextlib.nullcontext()

            def assertLessEqual(self, first, second, msg=None):
                if first > second:
                    self.failed.append(msg)

        def grow():
            Group.objects.bulk_create(Group(name=f'grown {len(added)} {number}') for number in range(1000))
            added.append(1000)

        def measured(rows):
            def measure():
                with reads() as found:
                    list(rows())
                return found
            return measure
        key = Group.objects.order_by('pk').values_list('pk', flat=True)[0]
        by_key, by_text = Recorder(), Recorder()
        assert_reads_do_not_grow(by_key, grow, measured(lambda: Group.objects.filter(pk=key)), ['auth_group'], 'key')
        assert_reads_do_not_grow(by_text, grow, measured(lambda: Group.objects.filter(name__endswith='x')),
                                 ['auth_group'], 'text')
        self.assertEqual(by_key.failed, [])
        self.assertEqual(len(by_text.failed), 1)
        self.assertIn('rows of auth_group, then', by_text.failed[0])


class OneMomentTests(SimpleTestCase):
    def test_the_clock_stands_for_the_block_and_is_given_back(self):
        import time

        from core.testing import one_moment
        with one_moment() as moment:
            first = timezone.now()
            time.sleep(0.002)
            self.assertEqual((first, timezone.now()), (moment, moment))
        self.assertIs(timezone.now, GIVEN)

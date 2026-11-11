"""The tests' clock. A test whose records are dated on fixed days must not read the day it runs on: the rules that count
from today (a record dated at most the correction window back, nothing in the future, a value's freshness) would fail
it, or pass it, by the calendar. `FrozenClock` holds the clock the code reads at one moment for a test class's whole
life, its class data included. That clock is `django.utils.timezone.now`: the code's days and moments come from it
(core.dates, farm.stock.dates; core/tests_company_clock.py refuses `date.today()` and the like). The database's own
clock (`now()` in SQL) is not held.

Nor must a test read the hour it runs at. The server's day (UTC) and the company's (settings.COMPANY_TIME_ZONE, Oslo)
differ for an hour or two before every UTC midnight, and a site on a third zone differs for longer: a test that says
"today" on one clock while the code reads another passes all day and fails in those hours. `BAD_HOURS` are moments
inside them; core/tests_day_boundary.py runs the tests that count days again at each (`at_bad_hours`), and
`TEST_CLOCK` starts a whole run's clock at any moment (`run_clock`: scripts/test.sh passes it on), to look for more."""
import os
from datetime import datetime, timezone as dt_timezone
from unittest import mock

CLOCK = 'django.utils.timezone.now'

# Moments at which the UTC day is not the company's (Europe/Oslo unless the environment names another). The first is
# the middle of the CI run that found the class (run 42921917659, 23:17 to 23:57 UTC on 10.11.2026).
BAD_HOURS = {
    'WinterNight': datetime(2026, 11, 10, 23, 30, tzinfo=dt_timezone.utc),      # 00:30 on the 11th in Oslo (UTC+1)
    'SummerNight': datetime(2026, 7, 10, 22, 30, tzinfo=dt_timezone.utc),       # 00:30 on the 11th in Oslo (UTC+2)
    'JustBeforeOslosMidnight': datetime(2026, 11, 10, 22, 59, 59, tzinfo=dt_timezone.utc),   # the same day on both
    'JustAfterOslosMidnight': datetime(2026, 11, 10, 23, 0, 0, tzinfo=dt_timezone.utc),      # Oslo is a day ahead
    'NewYearsEve': datetime(2026, 12, 31, 23, 30, tzinfo=dt_timezone.utc),      # 2027 in Oslo, 2026 on the server
}


class FrozenClock:
    """Mixed in before the TestCase: `timezone.now()` is NOW (an aware datetime) while the class's data is made
    (setUpTestData) and in every test of it, and the real clock again afterwards, also when the set-up fails."""
    NOW = None

    @classmethod
    def setUpClass(cls):
        if cls.NOW is None or cls.NOW.tzinfo is None:
            raise TypeError(f'{cls.__name__}.NOW is the moment its clock stands at: an aware datetime.')
        clock = mock.patch(CLOCK, return_value=cls.NOW)
        clock.start()
        cls.addClassCleanup(clock.stop)
        super().setUpClass()


def at_bad_hours(namespace, *cases, moments=BAD_HOURS):
    """Puts into `namespace` (a test module's globals()) one class per test class of `cases` and moment of `moments`:
    the same tests with the clock held at that moment (`<Case>At<Moment>`). The cases are given as attributes of their
    modules (`test_pages.WallTests`): a class imported by name would be collected a second time where it is imported."""
    for case in cases:
        for name, moment in moments.items():
            held = type(f'{case.__name__}At{name}', (FrozenClock, case), {
                'NOW': moment, '__module__': namespace['__name__'],
                '__doc__': f'{case.__module__}.{case.__name__} with the clock held at {moment.isoformat()}.'})
            namespace[held.__name__] = held


def run_clock(text=None):
    """The clock of a whole run started at the moment `text` (ISO, with its offset: 2026-11-10T23:30:00+00:00) and
    running on from there, or None without one (TEST_CLOCK in the environment unless given): started by the test runner
    before any test or class data (config/test_runner.py), in every worker. A class's FrozenClock still holds its own.
    The database's clock stays the real one, so a test that compares the two fails in such a run: it is a way to look
    for tests that read the hour, the day or the year they run in, not a way to run the suite."""
    text = os.environ.get('TEST_CLOCK', '') if text is None else text
    if not text:
        return None
    start = datetime.fromisoformat(text)
    if start.tzinfo is None:
        raise ValueError(f'TEST_CLOCK {text!r} is the moment the run\'s clock starts at: give its offset (+00:00).')
    began = datetime.now(dt_timezone.utc)
    clock = mock.patch(CLOCK, side_effect=lambda: start + (datetime.now(dt_timezone.utc) - began))
    clock.start()
    return clock

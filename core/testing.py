"""The tests' clock. A test whose records are dated on fixed days must not read the day it runs on: the rules that count
from today (a record dated at most the correction window back, nothing in the future, a value's freshness) would fail
it, or pass it, by the calendar. `FrozenClock` holds the clock the code reads at one moment for a test class's whole
life, its class data included. That clock is `django.utils.timezone.now`: the code's days and moments come from it
(core.dates, farm.stock.dates; core/tests_company_clock.py refuses `date.today()` and the like). The database's own
clock (`now()` in SQL) is not held."""
from unittest import mock


class FrozenClock:
    """Mixed in before the TestCase: `timezone.now()` is NOW (an aware datetime) while the class's data is made
    (setUpTestData) and in every test of it, and the real clock again afterwards, also when the set-up fails."""
    NOW = None

    @classmethod
    def setUpClass(cls):
        if cls.NOW is None or cls.NOW.tzinfo is None:
            raise TypeError(f'{cls.__name__}.NOW is the moment its clock stands at: an aware datetime.')
        clock = mock.patch('django.utils.timezone.now', return_value=cls.NOW)
        clock.start()
        cls.addClassCleanup(clock.stop)
        super().setUpClass()

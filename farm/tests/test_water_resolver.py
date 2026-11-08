"""The second cross review of the water's one resolver (farm/water/read.py, owner rule A9) and what an oxygen value is
worked out with. Each case is a probe of the review (P1-P8) turned round: it asserts what the water must say.

- A device clock ahead of ours: a value stamped more than evaluate.CLOCK_SKEW in the future is neither fresh nor the
  newest (P7)."""
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal

from django.test import SimpleTestCase

from ..water import evaluate
from ..water.evaluate import is_fresh
from ..water.parameters import get
from .test_water_sources import SourcesCase

D = Decimal


class ClockSkewTests(SimpleTestCase):
    def test_a_value_from_further_ahead_than_the_skew_is_not_fresh(self):
        now = datetime(2026, 11, 8, 12, tzinfo=dt_timezone.utc)
        ph = get('ph')
        CLOCK_SKEW = getattr(evaluate, 'CLOCK_SKEW', timedelta(minutes=5))
        self.assertEqual(getattr(evaluate, 'CLOCK_SKEW', None), timedelta(minutes=5))
        self.assertTrue(is_fresh(ph, now + CLOCK_SKEW, now))
        self.assertFalse(is_fresh(ph, now + CLOCK_SKEW + timedelta(seconds=1), now))
        self.assertFalse(is_fresh(ph, now + timedelta(minutes=50), now, fresh_for=3600))


class FutureValueTests(SourcesCase):
    def test_p7_a_value_stamped_50_minutes_ahead_is_not_the_newest(self):
        self.sample(hours=0, ph='6.0')
        self.on(self.mid1, self.value('ph', 7.5, seconds=-3000))      # 50 min ahead (the contract allows 3600 s)
        reading = self.latest().get('ph')
        self.assertEqual(reading.value, D('6.00'))
        self.on(self.mid1, self.value('ph', 7.2, seconds=-60, channel_no=2))   # a minute ahead: an ordinary clock
        self.assertEqual(self.latest().get('ph').value, D('7.20'))

    def test_a_value_only_from_the_future_is_shown_but_never_fresh(self):
        self.on(self.mid1, self.value('ph', 7.5, seconds=-3000))
        reading = self.latest().get('ph')
        self.assertEqual(reading.value, D('7.50'))
        self.assertFalse(reading.fresh(self.now))

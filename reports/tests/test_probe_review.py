"""The cross-reviewer's probes, adopted as failing tests (findings 4, 7): the lice fingerprint ignores plans far after
the week; a plan entered after its own slaughter day cannot move the deadline past that day."""
from datetime import datetime, timedelta, timezone as utc

from farm.models import Batch, HandlingPlanItem

from .. import compute
from .helpers import day
from .test_deadline import MONDAY, OneDeadlineTests
from .test_lice import LiceTestCase


class LiceFingerprintProbe(LiceTestCase):
    def test_a_plan_months_later_does_not_change_a_filed_weeks_fingerprint(self):
        before = compute.fingerprint(compute.scope(self.draft))
        batch = Batch.objects.get(movements__unit=self.m1)
        HandlingPlanItem.objects.create(kind='harvest', date=day(10, 31) + timedelta(days=120), unit=self.m1,
                                        batch=batch, planned_count=10, facility=self.facility, created_by=self.user)
        self.assertEqual(before, compute.fingerprint(compute.scope(self.draft)),
                         'a harvest plan 4 months after the week changes the lice report fingerprint')


class DeadlineProbe(OneDeadlineTests):
    def test_a_plan_entered_after_its_own_slaughter_day_does_not_move_the_deadline_past_it(self):
        HandlingPlanItem.objects.filter(pk=self.item.pk).update(created_at=datetime(2026, 11, 2, 9, tzinfo=utc.utc))
        found = compute.deadline(self.report_)
        self.assertLessEqual(found, MONDAY)

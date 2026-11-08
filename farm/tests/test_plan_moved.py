"""A harvest recorded from a plan on another week or at another facility than planned is the plan's in the
planned-slaughter report (reports/tests/test_slaughter_duty.py, PlannedAndDoneTests): the harvest dialog says so before
it is saved, never refuses it (audit F-227)."""
from datetime import timedelta

from django.urls import reverse

from ..models import HandlingPlanItem
from .helpers import make_facility
from .test_harvest import HarvestTestCase


class MovedPlanNoteTests(HarvestTestCase):
    NOTE = 'reported in the planned-slaughter notice of the plan’s week and facility'

    def plan(self, days_ahead):
        return HandlingPlanItem.objects.create(kind='harvest', date=self.today + timedelta(days=days_ahead),
                                               unit=self.t1, batch=self.batch, planned_count=100,
                                               facility=self.facility)

    def test_a_harvest_of_another_week_than_its_plan_is_told_where_it_is_reported(self):
        item = self.plan(14)                               # two weeks ahead: today is another week
        page = self.client.get(f"{reverse('farm:stock_harvest', args=[self.t1.pk])}?plan={item.pk}")
        self.assertContains(page, self.NOTE)

    def test_the_planned_week_and_facility_say_nothing(self):
        item = self.plan(0)
        page = self.client.get(f"{reverse('farm:stock_harvest', args=[self.t1.pk])}?plan={item.pk}")
        self.assertNotContains(page, self.NOTE)
        other = make_facility('Kyst Slakteri', 'M456')
        HandlingPlanItem.objects.filter(pk=item.pk).update(facility=other)
        page = self.client.get(f"{reverse('farm:stock_harvest', args=[self.t1.pk])}?plan={item.pk}")
        self.assertNotContains(page, self.NOTE)        # the dialog offers the plan's facility

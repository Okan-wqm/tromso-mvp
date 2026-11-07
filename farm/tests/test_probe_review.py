"""The cross-reviewer's probes, adopted as failing tests (findings 1, 2): a backdated medicated feeding over a recorded
harvest is asked; check_withdrawal labels an acknowledgement per withdrawal."""
import io
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.management import call_command

from ..feeding import services as feeding_services
from ..handling import check
from ..health import withdrawal
from ..models import Feed
from ..stock import services as stock_services
from .helpers import going_on
from .test_harvest_inside_withdrawal import HarvestInsideTestCase


class ProbeTests(HarvestInsideTestCase):
    def test_backdated_medicated_feeding_over_a_recorded_harvest_is_asked(self):
        self.harvest(2)
        feed = Feed.objects.create(name='Medisinfor', code='MED-1', feed_type='medicated')
        try:
            feeding_services.record_feeding(self.user, unit=self.t1, day=self.day(4), feed=feed,
                                            amount_kg=Decimal('2'))
            saved = True
        except ValidationError:
            saved = False
        self.assertFalse(saved, 'a backdated medicated feeding that puts a recorded harvest inside a withdrawal '
                                'was saved with no warning/acknowledgement')

    def test_check_withdrawal_ack_label_is_per_withdrawal(self):
        bath = self.medicine(days=7)
        self.treat(bath, 6, 6)                                   # held until 1 day ago
        seen = check.assess('harvest', self.t1, self.day(3), self.batch).fingerprint
        stock_services.record_harvest(self.user, unit=self.t1, batch=self.batch, day=self.day(3), count=500,
                                      measured_weight_kg=Decimal('600'), facility=self.facility, handling_ack=seen)
        feed = Feed.objects.create(name='Medisinfor', code='MED-1', feed_type='medicated')
        going_on(feeding_services.record_feeding, self.user, unit=self.t1, day=self.day(5), feed=feed,
                 amount_kg=Decimal('2'))                  # the guard asks: gone on past it, as the person would
        out = io.StringIO()
        call_command('check_withdrawal', stdout=out)
        lines = [line for line in out.getvalue().splitlines() if 'medicated feed' in line.lower()
                 or 'in-feed' in line.lower()]
        self.assertTrue(lines)
        self.assertFalse(any('Acknowledged when the harvest was recorded' in line for line in lines),
                         'the unknown-end medicated-feed withdrawal nobody saw is labelled acknowledged')

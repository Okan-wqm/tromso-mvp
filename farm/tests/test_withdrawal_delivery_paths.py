"""A live delivery is a harvest after the fact on the paths farm/tests/test_withdrawal_delivery_after.py does not walk
with a delivery (the owner's decision 13 of 19.11.2026; the verification of the S-03 follow-up, can-follow 5: its probes
W1-W4, R1-R4 and F5, adopted as tests): a water sample that slows the degree-days (recorded, in a round, voided through
the services and behind them), the reference data a withdrawal is worked out from (a feed made medicated, a species'
assumed temperature, a sampling point made inactive, a unit moved into a cold loop), and the second-person setting
before the fact. Each asks the same question as for a harvest: the delivery in its own words, the tick, one `delivered`
row naming it and one critical log line on the write."""
import io
from datetime import datetime, time
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.urls import reverse

from core.models import AuditLog, PlatformSettings

from .. import withdrawal_gate as gate
from ..feeding import services as feeding_services
from ..handling import check
from ..models import Feed, SamplingPoint, Species, StockOperation, System, Tank, WithdrawalAcknowledgement
from ..models.handling import HandlingKind
from ..models.site import zone_of
from ..models.stock import OperationKind
from ..stock import services as stock_services
from ..water import services as water_services
from .helpers import may_record, point_of, role
from .test_withdrawal_gate import edit_data
from .test_withdrawal_guard import GuardTestCase

TO = 'Nordic Smolt AS'
LOGGED = 'Withdrawal warnings acknowledged'
SECOND = ('A second person must approve going on past a medicine withdrawal (the platform owner’s setting), and that '
          'approval cannot be given here yet.')


class DeliveryTestCase(GuardTestCase):
    def deliver(self, days_ago, unit=None, batch=None, count=300):
        """A live delivery recorded through the services while no withdrawal held its fish (nothing acknowledged)."""
        unit, batch = unit or self.t1, batch or self.batch
        seen = check.assess(HandlingKind.TRANSPORT, unit, self.day(days_ago), batch,
                            operation=OperationKind.DELIVERY).fingerprint
        delivery = stock_services.record_delivery(self.user, unit=unit, batch=batch, day=self.day(days_ago),
                                                  count=count, destination=TO, handling_ack=seen or None)
        self.assertFalse(WithdrawalAcknowledgement.objects.exists(), 'the delivery was free when recorded')
        return delivery

    def delivered(self, change, delivery):
        """The change's one finding about the delivery, asked as `delivered` in a delivery's words."""
        found = [each for each in change.harvested if each.operation_id == delivery.pk]
        self.assertEqual(len(found), 1, change.messages())
        self.assertEqual((found[0].warning, found[0].harvest), ('delivered', delivery.pk))
        self.assertTrue(any(message.startswith('Live delivery of') and TO in message for message in change.messages()))
        return found[0]

    def stored(self, delivery):
        """The one `delivered` row names the delivery; the write's one critical line says it."""
        row = WithdrawalAcknowledgement.objects.get(warning='delivered')
        self.assertEqual((row.harvest_id, row.created_by), (delivery.pk, self.user))
        entries = [each for each in AuditLog.objects.filter(entity_type=row.record_type, entity_id=row.record_id,
                                                            severity=AuditLog.Severity.CRITICAL)
                   if LOGGED in each.changes and 'Live delivery of' in each.changes[LOGGED][1]]
        self.assertEqual(len(entries), 1)
        return row


class WaterSampleTests(DeliveryTestCase):
    """The harvest's schedule (test_withdrawal_guard: a backdated water sample that slows the degree-days) with a live
    delivery: a 55 degree-day bath 6 days ago, T-01 at 20 °C for three days, 300 fish delivered yesterday."""

    def setUp(self):
        super().setUp()
        bath = self.medicine(degree_days=55)
        self.samples = [self.temperature(self.t1, days_ago, '20') for days_ago in (5, 4, 3)]
        self.treat(bath, 6, 6)
        self.delivery = self.deliver(1)
        self.moment = datetime.combine(self.day(4), time(18), tzinfo=zone_of(self.bergen))

    def test_a_backdated_sample_asks_about_the_delivery(self):
        def write(**ack):
            may_record(self.user, 'add_watermeasurement')  # the water service asks (L-6)
            return water_services.record(self.user, point=point_of(self.t1), measured_at=self.moment,
                                         source='manual', values={'temperature_c': Decimal('0')}, **ack)
        change = self.asked(write)
        self.delivered(change, self.delivery)
        write(withdrawal_ack=change.fingerprint)
        self.stored(self.delivery)

    def test_a_round_asks_about_the_delivery(self):
        def write(**ack):
            may_record(self.user, 'add_watermeasurement')  # the water service asks (L-6)
            return water_services.record_round(self.user, measured_at=self.moment, source='manual',
                                               rows=[(point_of(self.t1), {'temperature_c': Decimal('0')}, '')], **ack)
        change = self.asked(write)
        self.delivered(change, self.delivery)
        write(withdrawal_ack=change.fingerprint)
        self.stored(self.delivery)

    def test_voiding_a_warm_sample_asks_about_the_delivery(self):
        sample = self.samples[1]                                             # 4 days ago
        change = self.asked(water_services.void, self.user, sample, 'a wrong reading')
        self.delivered(change, self.delivery)
        water_services.void(self.user, sample, 'a wrong reading', withdrawal_ack=change.fingerprint)
        self.stored(self.delivery)

    def test_check_withdrawal_lists_it_after_a_sample_voided_behind_the_services(self):
        with gate.opened('test: a sample voided behind the services'):
            self.samples[1].void_reason = 'a script'
            self.samples[1].soft_delete(self.user)
        out = io.StringIO()
        call_command('check_withdrawal', stdout=out)
        self.assertIn('Live delivery of', out.getvalue())
        self.assertIn('1 live delivery lies inside a medicine withdrawal.', out.getvalue())


class ReferenceDataTests(DeliveryTestCase):
    """A change of the reference data a withdrawal is worked out from, made on its edit page."""

    def setUp(self):
        super().setUp()
        self.user.groups.add(role('Setup keeper', 'view_feed', 'change_feed', 'view_species', 'change_species',
                                  'view_samplingpoint', 'change_samplingpoint', 'view_supplier', 'view_tank',
                                  'change_tank'))

    def page(self, url_name, obj, drop=(), **changes):
        """The edit page refuses the change with the question (422), then saves it ticked (302); the change shown."""
        url = reverse(url_name, args=[obj.pk])
        data = edit_data(self.client.get(url).context['form'], **changes)
        for name in drop:
            data.pop(name, None)
        refused = self.client.post(url, data)
        self.assertEqual(refused.status_code, 422)
        self.assertContains(refused, 'Live delivery of', status_code=422)
        change = refused.context['withdrawal_change']
        self.assertEqual(self.client.post(url, {**data, 'withdrawal_ack': change.fingerprint}).status_code, 302)
        return change

    def test_a_feed_made_medicated_asks_about_the_delivery(self):
        feed = Feed.objects.create(name='Grower X', code='GRX', feed_type='grower')
        may_record(self.user, 'add_feedingrecord')  # the feeding service asks (L-6)
        feeding_services.record_feeding(self.user, unit=self.t1, day=self.day(3), feed=feed, amount_kg=Decimal('2'))
        delivery = self.deliver(1)
        change = self.page('farm:feed_edit', feed, feed_type='medicated')
        self.delivered(change, delivery)
        self.assertEqual(Feed.objects.get(pk=feed.pk).feed_type, 'medicated')
        self.stored(delivery)

    def test_a_species_assumed_temperature_lowered_asks_about_the_delivery(self):
        with gate.opened('test fixture: the assumed temperature'):
            Species.objects.filter(pk=self.salmon.pk).update(withdrawal_temperature_c=Decimal(40))
        self.salmon.refresh_from_db()
        self.treat(self.medicine(degree_days=100), 6, 6)     # no samples: 40 °C a day, free from 2 days ago
        self.assertEqual(self.held(day=self.day(1)), [])
        delivery = self.deliver(1)
        change = self.page('farm:species_edit', self.salmon, withdrawal_temperature_c='1')
        self.delivered(change, delivery)
        self.stored(delivery)

    def test_a_middle_point_made_inactive_asks_about_the_delivery(self):
        bath = self.medicine(degree_days=55)
        for days_ago in (5, 4, 3):
            self.temperature(self.t1, days_ago, '20')
        self.treat(bath, 6, 6)
        delivery = self.deliver(1)
        point = point_of(self.t1)
        change = self.page('farm:samplingpoint_edit', point, drop=('is_active',))
        self.delivered(change, delivery)
        self.assertFalse(SamplingPoint.all_objects.get(pk=point.pk).is_active)
        self.stored(delivery)

    def test_a_unit_moved_into_a_cold_loop_asks_about_the_delivery(self):
        loop = System.objects.create(name='RAS 1', code='R1', site=self.bergen, production_department=self.hall)
        with gate.opened('test fixture: the assumed temperature'):
            Species.objects.filter(pk=self.salmon.pk).update(withdrawal_temperature_c=Decimal(10))
        self.salmon.refresh_from_db()
        for days_ago in range(7, 0, -1):
            self.temperature(loop, days_ago, '2')
        self.treat(self.medicine(degree_days=50), 8, 8)      # T-01 has no sample: 10 °C a day, free from 2 days ago
        self.assertEqual(self.held(day=self.day(1)), [])
        delivery = self.deliver(1)
        change = self.page('farm:tank_edit', self.t1, system=str(loop.pk))
        self.delivered(change, delivery)
        self.assertEqual(Tank.objects.get(pk=self.t1.pk).system, loop)
        self.stored(delivery)


class SecondPersonBeforeTheFactTests(DeliveryTestCase):
    def test_a_ticked_delivery_of_held_fish_is_refused_like_a_harvest(self):
        self.treat(self.medicine(days=7), 2, 2)
        PlatformSettings.objects.update(second_approval_withdrawal=True)
        seen = check.assess(HandlingKind.TRANSPORT, self.t1, self.today, self.batch, operation=OperationKind.DELIVERY)
        with self.assertRaises(ValidationError) as delivery:
            stock_services.record_delivery(self.user, unit=self.t1, batch=self.batch, day=self.today, count=100,
                                           destination=TO, handling_ack=seen.fingerprint)
        harvest_seen = check.assess(HandlingKind.HARVEST, self.t1, self.today, self.batch)
        with self.assertRaises(ValidationError) as harvest:
            stock_services.record_harvest(self.user, unit=self.t1, batch=self.batch, day=self.today, count=100,
                                          measured_weight_kg=Decimal(13), facility=self.facility,
                                          handling_ack=harvest_seen.fingerprint)
        self.assertEqual(delivery.exception.message_dict, {'handling_ack': [SECOND]})
        self.assertEqual(harvest.exception.message_dict, delivery.exception.message_dict)
        self.assertFalse(StockOperation.objects.filter(kind__in=['delivery', 'harvest']).exists())

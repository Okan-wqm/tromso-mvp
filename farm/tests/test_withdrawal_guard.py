"""Every write that can create, grow, shorten or end a medicine withdrawal goes through ONE function,
farm.health.withdrawal.guarded (cross-review of F-195, F-196): it works out the withdrawals of the fish the write
touches before and after it, in the write's transaction, and asks before the write stands when

- a harvest already recorded now lies inside a withdrawal it was not inside before (medicated fish may have gone to
  food), or
- fish held by a withdrawal today are no longer held (the write would free them to go to food).

Going on needs the box (`withdrawal_ack`, the change's fingerprint): stored as WithdrawalAcknowledgement rows naming the
write, the batch, the withdrawal and the harvest, and logged as critical. The write paths are enumerated below, so a new
one that skips the guard fails a test."""
import inspect
import io
from datetime import datetime, time, timedelta
from decimal import Decimal
from unittest import mock

from django.core.management import call_command
from django.urls import reverse

from core.models import AuditLog

from ..feeding import services as feeding_services
from ..handling import check
from ..health import services, withdrawal
from ..health.withdrawal import WithdrawalChanged
from ..models import Feed, WaterMeasurement, WithdrawalAcknowledgement
from ..models.site import zone_of
from ..resources.medicine import MedicineWithdrawalList
from ..stock import services as stock_services
from ..water import services as water_services
from .helpers import point_of, rows_data
from .test_harvest_inside_withdrawal import HarvestInsideTestCase


class GuardTestCase(HarvestInsideTestCase):
    def asked(self, call, *args, **kwargs):
        """The change a write is refused for, until it is acknowledged."""
        with self.assertRaises(WithdrawalChanged) as caught:
            call(*args, **kwargs)
        self.assertEqual(caught.exception.message_dict, {'withdrawal_ack': [
            'Tick the box to go on despite these warnings.']})
        return caught.exception.change

    def acknowledged(self, change, call, *args, **kwargs):
        with withdrawal.acknowledging(change.fingerprint):
            return call(*args, **kwargs)

    def medicated(self):
        return Feed.objects.create(name='Medisinfor', code='MED-1', feed_type='medicated')

    def feed(self, days_ago, feed=None):
        return feeding_services.record_feeding(self.user, unit=self.t1, day=self.day(days_ago),
                                               feed=feed or self.medicated(), amount_kg=Decimal('2'))


class HarvestBroughtInsideTests(GuardTestCase):
    def test_a_backdated_medicated_feeding_over_a_recorded_harvest_asks_and_is_stored(self):
        harvest = self.harvest(2)
        feed = self.medicated()
        change = self.asked(self.feed, 4, feed)
        [found] = change.harvested
        self.assertEqual((found.operation_id, found.until), (harvest.pk, None))
        self.assertIn('lies inside this withdrawal, whose end is unknown', change.messages()[0])
        record = self.acknowledged(change, self.feed, 4, feed)
        [row] = WithdrawalAcknowledgement.objects.all()
        self.assertEqual((row.warning, row.harvest, row.batch, row.record_type, row.record_id, row.created_by),
                         ('harvested', harvest, self.batch, 'feeding record', str(record.pk), self.user))
        self.assertEqual(row.source, f'feeding:{record.pk}')
        log = AuditLog.objects.get(entity_type='feeding record', entity_id=str(record.pk),
                                   severity=AuditLog.Severity.CRITICAL)
        self.assertIn('lies inside this withdrawal', log.changes['Withdrawal warnings acknowledged'][1])

    def test_a_backdated_treatment_asks_through_the_same_box(self):
        harvest = self.harvest(3)
        bath = self.medicine(days=7)
        change = self.asked(self.treat, bath, 5, 5)
        self.assertEqual([found.operation_id for found in change.harvested], [harvest.pk])
        treatment = self.acknowledged(change, self.treat, bath, 5, 5)
        row = WithdrawalAcknowledgement.objects.get()
        self.assertEqual((row.record_type, row.record_id, row.source), ('treatment', str(treatment.pk),
                                                                       f'treatment:{treatment.pk}'))

    def test_a_medicine_row_made_longer_over_a_recorded_harvest_asks_on_its_page(self):
        bath = self.medicine(days=1)
        self.treat(bath, 5, 5)                               # held until 3 days ago
        self.harvest(2)
        url = reverse('farm:medicine_withdrawals', args=[bath.pk])
        data = rows_data('withdrawals', [{'species': '', 'degree_days': '', 'days': '7', 'safety_margin_pct': '',
                                          'note': ''}], 0, record=bath)
        refused = self.client.post(url, data)
        self.assertEqual(refused.status_code, 422)
        self.assertContains(refused, 'lies inside this withdrawal', status_code=422)
        self.assertEqual(list(bath.withdrawals.values_list('days', flat=True)), [1])
        fingerprint = refused.context['withdrawal_change'].fingerprint
        self.assertEqual(self.client.post(url, {**data, 'withdrawal_ack': fingerprint}).status_code, 302)
        self.assertEqual(list(bath.withdrawals.values_list('days', flat=True)), [7])
        self.assertEqual(WithdrawalAcknowledgement.objects.get().record_type, 'medicine')

    def test_a_backdated_water_sample_that_slows_the_degree_days_asks(self):
        bath = self.medicine(degree_days=55)
        for days_ago in (5, 4, 3):
            self.temperature(self.t1, days_ago, '20')        # 60 degree-days by 3 days ago: free from 2 days ago
        self.treat(bath, 6, 6)
        self.harvest(1)
        moment = datetime.combine(self.day(4), time(18), tzinfo=zone_of(self.bergen))
        change = self.asked(water_services.record, self.user, point=point_of(self.t1), measured_at=moment,
                            source='manual', values={'temperature_c': Decimal('0')})
        self.assertEqual(len(change.harvested), 1)

    def test_a_harvest_inside_a_known_withdrawal_is_asked_once_by_the_harvest_dialog(self):
        self.treat(self.medicine(days=7), 3, 3)
        seen = check.assess('harvest', self.t1, self.day(1), self.batch).fingerprint
        stock_services.record_harvest(self.user, unit=self.t1, batch=self.batch, day=self.day(1), count=10,
                                      measured_weight_kg=Decimal('12'), facility=self.facility, handling_ack=seen)
        self.assertFalse(WithdrawalAcknowledgement.objects.exists())


class FreedFishTests(GuardTestCase):
    def test_voiding_a_course_that_holds_fish_today_asks(self):
        treatment = self.treat(self.medicine(days=7), 2, 2)
        change = self.asked(services.void_treatment, self.user, treatment, 'Wrong unit')
        [freed] = change.released
        self.assertEqual((freed.batch, freed.until), (self.batch, self.day(-6)))
        self.assertIn('would no longer be held', change.messages()[0])
        self.acknowledged(change, services.void_treatment, self.user, treatment, 'Wrong unit')
        row = WithdrawalAcknowledgement.objects.get()
        self.assertEqual((row.warning, row.harvest, row.until), ('released', None, self.day(-6)))
        self.assertTrue(AuditLog.objects.filter(entity_type='treatment', severity=AuditLog.Severity.CRITICAL,
                                                action='void').exists())

    def test_voiding_a_course_whose_withdrawal_has_ended_asks_nothing(self):
        treatment = self.treat(self.medicine(days=1), 9, 9)
        services.void_treatment(self.user, treatment, 'Wrong unit')
        self.assertFalse(WithdrawalAcknowledgement.objects.exists())

    def test_a_shorter_course_that_frees_held_fish_asks_and_one_still_holding_does_not(self):
        bath = self.medicine(days=1)
        treatment = self.treat(bath, 3, -5)                  # running: held until 7 days ahead
        services.change_last_day(self.user, treatment, self.day(-1))   # still held, until 3 days ahead
        change = self.asked(services.change_last_day, self.user, treatment, self.day(3))   # until yesterday
        self.assertEqual([freed.batch for freed in change.released], [self.batch])

    def test_a_medicine_row_made_shorter_that_frees_held_fish_asks(self):
        bath = self.medicine(days=7)
        self.treat(bath, 3, 3)                               # held until 5 days ahead
        url = reverse('farm:medicine_withdrawals', args=[bath.pk])
        data = rows_data('withdrawals', [{'species': '', 'degree_days': '', 'days': '1', 'safety_margin_pct': '',
                                          'note': ''}], 0, record=bath)
        refused = self.client.post(url, data)
        self.assertEqual(refused.status_code, 422)
        self.assertContains(refused, 'would no longer be held', status_code=422)
        self.assertEqual(list(bath.withdrawals.values_list('days', flat=True)), [7])

    def test_voiding_the_medicated_feeding_that_holds_fish_asks(self):
        record = self.feed(1)
        change = self.asked(feeding_services.void_feeding, self.user, record, 'Wrong feed')
        self.assertEqual([freed.batch for freed in change.released], [self.batch])


class CheckWithdrawalLabelTests(GuardTestCase):
    def test_acknowledged_only_for_the_withdrawal_that_was_acknowledged(self):
        bath = self.medicine(days=7)
        self.treat(bath, 6, 6)                               # held until 1 day ago
        seen = check.assess('harvest', self.t1, self.day(3), self.batch).fingerprint
        stock_services.record_harvest(self.user, unit=self.t1, batch=self.batch, day=self.day(3), count=500,
                                      measured_weight_kg=Decimal('600'), facility=self.facility, handling_ack=seen)
        feed = self.medicated()
        change = self.asked(self.feed, 5, feed)
        self.acknowledged(change, self.feed, 5, feed)
        out = io.StringIO()
        call_command('check_withdrawal', stdout=out)
        lines = out.getvalue().splitlines()
        [salmosan] = [line for line in lines if line.startswith('Harvest') and 'Salmosan' in line]
        [fed] = [line for line in lines if line.startswith('Harvest') and 'Medicated feed' in line]
        self.assertTrue(salmosan.endswith('Acknowledged when the harvest was recorded.'))
        self.assertTrue(fed.endswith('Acknowledged when the feeding record was recorded.'), fed)

    def test_an_acknowledgement_of_another_withdrawal_is_not_this_ones(self):
        bath = self.medicine(days=7)
        self.treat(bath, 6, 6)
        seen = check.assess('harvest', self.t1, self.day(3), self.batch).fingerprint
        harvest = stock_services.record_harvest(self.user, unit=self.t1, batch=self.batch, day=self.day(3), count=500,
                                                measured_weight_kg=Decimal('600'), facility=self.facility,
                                                handling_ack=seen)
        feed = self.medicated()
        with mock.patch.object(withdrawal, 'guarded', side_effect=lambda user, batch_ids, today, write, **kw: write()):
            self.feed(5, feed)                               # a write that skipped the guard (as before it existed)
        out = io.StringIO()
        call_command('check_withdrawal', stdout=out)
        [fed] = [line for line in out.getvalue().splitlines() if line.startswith('Harvest') and 'Medicated' in line]
        self.assertTrue(fed.endswith('Not acknowledged.'), fed)
        self.assertTrue(harvest.pk)


class WritePathTests(GuardTestCase):
    """The write paths of the facts a withdrawal is worked out from (treatments, feedings, the medicines' rows, water
    samples, the stock ledger): each goes through the guard. A new write function in these modules that neither calls
    `guarded` nor writes through one that does fails here."""

    MODULES = {
        services: ('record_treatment', 'change_last_day', 'void_treatment'),
        feeding_services: ('record_feeding', 'void_feeding'),
        water_services: ('record', 'record_round', 'void'),
        stock_services: ('_commit', 'void'),
    }
    # Writes that cannot change a withdrawal (a lice count, a health event's void, refused while a treatment names it), and
    EXEMPT = {(services, 'record_lice_count'), (services, 'void_lice_count'), (services, 'void_event'),
              # The shared void step: it is called inside each guarded void (stock, feeding, treatment, water).
              (stock_services, 'voided')}

    def test_every_write_function_of_the_modules_is_guarded(self):
        for module, guarded_names in self.MODULES.items():
            for name, function in inspect.getmembers(module, inspect.isfunction):
                if function.__module__ != module.__name__:
                    continue
                writes = name.startswith(('record', 'void', 'change', '_commit'))
                if not writes or (module, name) in self.EXEMPT:
                    continue
                source = inspect.getsource(function)
                with self.subTest(function=f'{module.__name__}.{name}'):
                    self.assertTrue(name in guarded_names or '_commit(' in source or 'record_round(' in source
                                    or 'record(' in source and module is water_services, name)
            for name in guarded_names:
                with self.subTest(guarded=f'{module.__name__}.{name}'):
                    self.assertIn('guarded(', inspect.getsource(getattr(module, name)))
        self.assertIn('guarded(', inspect.getsource(MedicineWithdrawalList.save))

    def test_each_path_calls_the_guard(self):
        bath = self.medicine(days=7)
        calls = []
        real = withdrawal.guarded

        def spy(*args, **kwargs):
            calls.append(kwargs.get('record_type') or 'stock')
            return real(*args, **kwargs)

        with mock.patch.object(withdrawal, 'guarded', side_effect=spy):
            treatment = self.treat(bath, 9, 9)
            services.change_last_day(self.user, treatment, self.day(8))
            services.void_treatment(self.user, treatment, 'Test')
            grower = Feed.objects.create(name='Grower', code='GR-1', feed_type='grower')
            record = self.feed(1, grower)
            feeding_services.void_feeding(self.user, record, 'Test')
            sample = water_services.record(self.user, point=point_of(self.t1),
                                           measured_at=datetime.combine(self.day(1), time(9), tzinfo=zone_of(self.bergen)),
                                           source='manual', values={'temperature_c': Decimal('8')})
            water_services.void(self.user, sample, 'Test')
            operation = self.mortality(self.batch, 5)
            stock_services.void(self.user, operation, 'Test')
        self.assertEqual(len(calls), 9)
        self.assertTrue(WaterMeasurement.all_objects.filter(pk=sample.pk).exists())

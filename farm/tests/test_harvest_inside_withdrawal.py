"""A treatment entered after the fact (backdated, or a course made longer) whose withdrawal reaches back over a harvest
already recorded: the medicated fish went to food before anyone knew. Nothing may let that pass in silence (audit F-195,
F-188): the treatment's dialog and the last-day dialog name every such harvest and go on only past an explicit
acknowledgement, stored with the treatment and logged as critical; the units and their batches are locked as a harvest
locks them, so the two take turns; and check_withdrawal lists every harvest that lies inside a withdrawal, however it
came to (a treatment, a corrected temperature, a medicine's withdrawal changed)."""
import io
from decimal import Decimal
from unittest import mock

from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from core.models import AuditLog

from ..handling import check
from ..health import services
from ..models import HandlingAcknowledgement, StockOperation, Treatment
from ..stock import read as stock_read, services as stock_services
from .helpers import make_facility
from .test_health import HealthTestCase, treatment_data


class HarvestInsideTestCase(HealthTestCase):
    def setUp(self):
        super().setUp()
        self.facility = make_facility()

    def harvest(self, days_ago, count=500, kilos='600', everything=False):
        return stock_services.record_harvest(self.user, unit=self.t1, batch=self.batch, day=self.day(days_ago),
                                             count=count, measured_weight_kg=Decimal(kilos), facility=self.facility,
                                             everything=everything)


class BackdatedTreatmentTests(HarvestInsideTestCase):
    def test_a_backdated_treatment_names_the_harvest_already_inside_its_withdrawal_and_asks(self):
        harvest = self.harvest(3)                            # 500 fish to food 3 days ago
        bath = self.medicine(days=7)                         # 5 days ago: withdrawal until 3 days ahead
        refused = self.refused(self.treat, bath, 5, 5)
        self.assertEqual(refused, {'handling_ack': ['Tick the box to go on despite these warnings.']})
        self.assertFalse(Treatment.all_objects.exists())
        checked = services.handling([self.t1], self.day(5), 'bath', medicine=bath, end_date=self.day(5))
        [found] = checked.harvested
        self.assertEqual((found.operation_id, found.until, found.approximate), (harvest.pk, self.day(-3), False))
        self.assertEqual(checked.messages(), [
            f'Harvest of {stock_services.shown_date(self.day(3))} from T-01 ({self.batch.code}, 500 fish to '
            f'{self.facility.name}) lies inside this withdrawal, which holds the fish until '
            f'{stock_services.shown_date(self.day(-3))}: medicated fish may have gone to food.'])
        treatment = self.treat(bath, 5, 5, handling_ack=checked.fingerprint)
        [row] = HandlingAcknowledgement.objects.all()
        self.assertEqual((row.treatment, row.operation, row.harvest, row.warning, row.withdrawal_until, row.kind),
                         (treatment, None, harvest, 'harvested', self.day(-3), 'treatment'))
        log = AuditLog.objects.get(entity_type='treatment', action='create')
        self.assertEqual(log.severity, AuditLog.Severity.CRITICAL)
        self.assertIn('lies inside this withdrawal', log.changes['Handling warnings acknowledged'][1])

    def test_a_harvest_before_the_first_day_or_after_the_withdrawal_asks_nothing(self):
        self.harvest(8)                                      # before the course
        bath = self.medicine(days=2)
        self.treat(bath, 6, 6)                               # held from 6 to 4 days ago
        self.harvest(2)                                      # after it ended
        self.assertFalse(HandlingAcknowledgement.objects.exists())
        self.assertEqual(services.handling([self.t1], self.day(6), 'bath', medicine=bath,
                                           end_date=self.day(6)).harvested, [])

    def test_a_treatment_without_a_medicine_holds_nothing_and_asks_nothing(self):
        self.harvest(3)
        self.treat(None, 5, 5, method='thermal', notes='Thermolicer')
        self.assertFalse(HandlingAcknowledgement.objects.exists())

    def test_the_harvest_of_the_whole_batch_is_found_too(self):
        self.harvest(3, count=2000, kilos='2400', everything=True)       # the unit is empty since
        bath = self.medicine(days=7)
        self.assertIn('handling_ack', self.refused(self.treat, bath, 5, 5))

    def test_the_dialog_shows_the_harvest_and_takes_its_box(self):
        self.harvest(3)
        bath = self.medicine(days=7)
        url = reverse('farm:treatment_record')
        data = treatment_data([self.t1], method='bath', medicine=str(bath.pk), start_date=self.day(5).isoformat(),
                              end_date=self.day(5).isoformat())
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 422)
        self.assertContains(response, 'lies inside this withdrawal', status_code=422)
        fingerprint = services.handling([self.t1], self.day(5), 'bath', medicine=bath,
                                        end_date=self.day(5)).fingerprint
        self.assertEqual(self.client.post(url, {**data, 'handling_ack': fingerprint}).status_code, 302)
        self.assertEqual(HandlingAcknowledgement.objects.get().warning, 'harvested')

    def test_the_treatment_locks_its_units_and_the_batches_in_them(self):
        bath = self.medicine(days=7)
        with CaptureQueriesContext(connection) as queries:
            self.treat(bath, 1, 1)
        locks = [query['sql'] for query in queries.captured_queries if 'FOR UPDATE' in query['sql']]
        self.assertTrue(any('"batches"' in sql for sql in locks), locks)
        self.assertTrue(any('"tanks"' in sql for sql in locks), locks)


class LongerCourseTests(HarvestInsideTestCase):
    def test_a_longer_course_names_the_harvest_it_brings_inside_and_asks(self):
        bath = self.medicine(days=2)
        treatment = self.treat(bath, 8, 8)                   # held until 5 days ago
        harvest = self.harvest(4)
        refused = self.refused(services.change_last_day, self.user, treatment, self.day(6))   # now until 3 days ago
        self.assertEqual(refused, {'handling_ack': ['Tick the box to go on despite these warnings.']})
        self.assertEqual(Treatment.objects.get().end_date, self.day(8))
        checked = services.last_day_handling(treatment, self.day(6))
        [found] = checked.harvested
        self.assertEqual(found.operation_id, harvest.pk)
        services.change_last_day(self.user, treatment, self.day(6), handling_ack=checked.fingerprint)
        self.assertEqual(Treatment.objects.get().end_date, self.day(6))
        [row] = HandlingAcknowledgement.objects.all()
        self.assertEqual((row.treatment_id, row.harvest, row.warning, row.withdrawal_until),
                         (treatment.pk, harvest, 'harvested', self.day(3)))
        log = AuditLog.objects.get(entity_type='treatment', action='update')
        self.assertEqual(log.severity, AuditLog.Severity.CRITICAL)
        self.assertIn('lies inside this withdrawal', log.changes['Handling warnings acknowledged'][1])

    def test_a_harvest_already_inside_before_the_change_is_not_asked_again(self):
        bath = self.medicine(days=7)
        self.harvest(3)
        treatment = self.treat(bath, 5, 5, handling_ack=services.handling(
            [self.t1], self.day(5), 'bath', medicine=bath, end_date=self.day(5)).fingerprint)
        services.change_last_day(self.user, treatment, self.day(4))    # longer, but the harvest was inside already
        services.change_last_day(self.user, treatment, self.day(5))    # shorter
        self.assertEqual(HandlingAcknowledgement.objects.count(), 1)
        self.assertEqual(AuditLog.objects.filter(entity_type='treatment', action='update',
                                                 severity=AuditLog.Severity.CRITICAL).count(), 0)

    def test_the_last_day_dialog_shows_the_harvest_and_takes_its_box(self):
        treatment = self.treat(self.medicine(days=2), 8, 8)
        self.harvest(4)
        url = reverse('farm:treatment_last_day', args=[treatment.pk])
        response = self.client.post(url, {'end_date': self.day(6).isoformat()})
        self.assertEqual(response.status_code, 422)
        self.assertContains(response, 'lies inside this withdrawal', status_code=422)
        fingerprint = services.last_day_handling(treatment, self.day(6)).fingerprint
        self.assertEqual(self.client.post(url, {'end_date': self.day(6).isoformat(),
                                                'handling_ack': fingerprint}).status_code, 302)
        self.assertEqual(Treatment.objects.get().end_date, self.day(6))

    def test_changing_the_last_day_locks_the_units_and_their_batches(self):
        treatment = self.treat(self.medicine(days=2), 8, 8)
        with CaptureQueriesContext(connection) as queries:
            services.change_last_day(self.user, treatment, self.day(7))
        locks = [query['sql'] for query in queries.captured_queries if 'FOR UPDATE' in query['sql']]
        self.assertTrue(any('"batches"' in sql for sql in locks), locks)
        self.assertTrue(any('"tanks"' in sql for sql in locks), locks)


class SecondPersonHookTests(HarvestInsideTestCase):
    def test_the_platform_owners_setting_is_asked_in_one_place_before_a_withdrawal_is_gone_past(self):
        self.harvest(3)
        bath = self.medicine(days=7)
        fingerprint = services.handling([self.t1], self.day(5), 'bath', medicine=bath, end_date=self.day(5)).fingerprint
        with mock.patch.object(check, 'second_person_must_approve', return_value=True) as asked:
            refused = self.refused(self.treat, bath, 5, 5, handling_ack=fingerprint)
        self.assertEqual(asked.call_count, 1)
        self.assertEqual(refused, {'handling_ack': [
            'A second person must approve going on past a medicine withdrawal (the platform owner’s setting), and '
            'that approval cannot be given here yet.']})
        self.assertFalse(Treatment.all_objects.exists())
        self.assertFalse(check.second_person_must_approve(['withdrawal']))     # off until the setting exists


class AcknowledgementShapeTests(HarvestInsideTestCase):
    def test_a_harvest_row_names_its_harvest_and_its_treatment_and_no_other_row_names_a_harvest(self):
        harvest = self.harvest(3)
        treatment = self.treat(None, 5, 5, method='thermal', notes='Thermolicer')
        operation = StockOperation.objects.filter(kind='input').get()
        withdrawal_row = {'withdrawal_until': self.day(-3), 'withdrawal_reason': 'Salmosan vet.'}
        broken = [
            {'warning': 'harvested', 'treatment': treatment, **withdrawal_row},                       # no harvest
            {'warning': 'harvested', 'operation': operation, 'harvest': harvest, **withdrawal_row},   # not a treatment
            {'warning': 'withdrawal', 'operation': operation, 'harvest': harvest, **withdrawal_row},  # only harvested
        ]
        for fields in broken:
            with self.subTest(fields=fields), self.assertRaises(IntegrityError), transaction.atomic():
                HandlingAcknowledgement.objects.create(**fields)
        HandlingAcknowledgement.objects.create(warning='harvested', treatment=treatment, harvest=harvest,
                                               **withdrawal_row)


class CheckWithdrawalTests(HarvestInsideTestCase):
    def test_it_lists_every_harvest_inside_a_withdrawal_and_whether_it_was_acknowledged(self):
        bath = self.medicine(days=7)
        self.harvest(3)
        self.treat(bath, 5, 5, handling_ack=services.handling(
            [self.t1], self.day(5), 'bath', medicine=bath, end_date=self.day(5)).fingerprint)
        out = io.StringIO()
        call_command('check_withdrawal', stdout=out)
        self.assertIn(f'Harvest of {self.day(3).isoformat()} from T-01 · {self.batch.code} (500 fish to '
                      f'{self.facility.name}) lies inside a withdrawal until {self.day(-3).isoformat()}: Salmosan vet., '
                      f'bath', out.getvalue())
        self.assertIn('Acknowledged with the treatment.', out.getvalue())
        self.assertIn('1 harvest lies inside a medicine withdrawal.', out.getvalue())

    def test_a_harvest_a_changed_medicine_row_brings_inside_is_listed_as_not_acknowledged(self):
        bath = self.medicine(days=1)
        self.treat(bath, 5, 5)                               # held until 3 days ago
        self.harvest(3)
        bath.withdrawals.update(days=7)                      # the medicine's row changed later
        out = io.StringIO()
        call_command('check_withdrawal', stdout=out)
        self.assertIn('Not acknowledged.', out.getvalue())
        self.assertIn('1 harvest lies inside a medicine withdrawal.', out.getvalue())

    def test_with_none_it_says_so(self):
        self.harvest(3)
        out = io.StringIO()
        call_command('check_withdrawal', stdout=out)
        self.assertIn('No harvest lies inside a medicine withdrawal.', out.getvalue())

    def test_it_folds_the_stock_once(self):
        with mock.patch.object(stock_read, 'stock_of', wraps=stock_read.stock_of) as folded:
            call_command('check_withdrawal', stdout=io.StringIO())
        self.assertEqual(folded.call_count, 1)

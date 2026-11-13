"""A treatment entered after the fact (backdated, or a course made longer) whose withdrawal reaches back over a harvest
already recorded: the medicated fish went to food before anyone knew. Nothing may let that pass in silence (audit F-195,
F-188): the treatment's dialog and the last-day dialog name every such harvest and go on only past an explicit
acknowledgement (the withdrawal guard, farm.health.withdrawal.guarded, which every write that changes a withdrawal goes
through: test_withdrawal_guard.py), stored and logged as critical; the units and their batches are locked as a harvest
locks them, so the two take turns; and check_withdrawal lists every harvest that lies inside a withdrawal, however it
came to."""
import io
from decimal import Decimal
from unittest import mock

from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from core.models import AuditLog

from .. import withdrawal_gate as gate
from ..handling import check
from ..health import services
from ..health.withdrawal import WithdrawalChanged
from ..models import Treatment, WithdrawalAcknowledgement
from ..stock import read as stock_read, services as stock_services
from .helpers import make_facility
from .test_health import HealthTestCase, treatment_data

ASKED = {'withdrawal_ack': ['Tick the box to go on despite these warnings.']}


class HarvestInsideTestCase(HealthTestCase):
    def setUp(self):
        super().setUp()
        self.facility = make_facility()

    def harvest(self, days_ago, count=500, kilos='600', everything=False):
        return stock_services.record_harvest(self.user, unit=self.t1, batch=self.batch, day=self.day(days_ago),
                                             count=count, measured_weight_kg=Decimal(kilos), facility=self.facility,
                                             everything=everything)

    def change_of(self, call, *args, **kwargs):
        with self.assertRaises(WithdrawalChanged) as caught:
            call(*args, **kwargs)
        self.assertEqual(caught.exception.message_dict, ASKED)
        return caught.exception.change


class BackdatedTreatmentTests(HarvestInsideTestCase):
    def test_a_backdated_treatment_names_the_harvest_already_inside_its_withdrawal_and_asks(self):
        harvest = self.harvest(3)                            # 500 fish to food 3 days ago
        bath = self.medicine(days=7)                         # 5 days ago: withdrawal until 3 days ahead
        change = self.change_of(self.treat, bath, 5, 5)
        self.assertFalse(Treatment.all_objects.exists())
        [found] = change.harvested
        self.assertEqual((found.operation_id, found.until, found.approximate), (harvest.pk, self.day(-3), False))
        self.assertEqual(change.messages(), [
            f'Harvest of {stock_services.shown_date(self.day(3))} from T-01 ({self.batch.code}, 500 fish to '
            f'{self.facility.name}) lies inside this withdrawal, which holds the fish until '
            f'{stock_services.shown_date(self.day(-3))}: medicated fish may have gone to food.'])
        treatment = self.treat(bath, 5, 5, withdrawal_ack=change.fingerprint)
        [row] = WithdrawalAcknowledgement.objects.all()
        self.assertEqual((row.record_type, row.record_id, row.harvest, row.batch, row.warning, row.until),
                         ('treatment', str(treatment.pk), harvest, self.batch, 'harvested', self.day(-3)))
        log = AuditLog.objects.get(entity_type='treatment', severity=AuditLog.Severity.CRITICAL)
        self.assertIn('lies inside this withdrawal', log.changes['Withdrawal warnings acknowledged'][1])

    def test_a_harvest_before_the_first_day_or_after_the_withdrawal_asks_nothing(self):
        self.harvest(8)                                      # before the course
        bath = self.medicine(days=2)
        self.treat(bath, 6, 6)                               # held from 6 to 4 days ago
        self.harvest(2)                                      # after it ended
        self.assertFalse(WithdrawalAcknowledgement.objects.exists())

    def test_a_treatment_without_a_medicine_holds_nothing_and_asks_nothing(self):
        self.harvest(3)
        self.treat(None, 5, 5, method='thermal', notes='Thermolicer')
        self.assertFalse(WithdrawalAcknowledgement.objects.exists())

    def test_the_harvest_of_the_whole_batch_is_found_too(self):
        self.harvest(3, count=2000, kilos='2400', everything=True)       # the unit is empty since
        self.change_of(self.treat, self.medicine(days=7), 5, 5)

    def test_the_dialog_shows_the_harvest_and_takes_its_box(self):
        self.harvest(3)
        bath = self.medicine(days=7)
        url = reverse('farm:treatment_record')
        data = treatment_data([self.t1], method='bath', medicine=str(bath.pk), start_date=self.day(5).isoformat(),
                              end_date=self.day(5).isoformat())
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 422)
        self.assertContains(response, 'lies inside this withdrawal', status_code=422)
        self.assertContains(response, 'name="withdrawal_ack"', status_code=422)
        fingerprint = response.context['form'].withdrawal_change.fingerprint
        self.assertEqual(self.client.post(url, {**data, 'withdrawal_ack': fingerprint}).status_code, 302)
        self.assertEqual(WithdrawalAcknowledgement.objects.get().warning, 'harvested')

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
        change = self.change_of(services.change_last_day, self.user, treatment, self.day(6))   # until 3 days ago
        self.assertEqual(Treatment.objects.get().end_date, self.day(8))
        self.assertEqual([found.operation_id for found in change.harvested], [harvest.pk])
        services.change_last_day(self.user, treatment, self.day(6), withdrawal_ack=change.fingerprint)
        self.assertEqual(Treatment.objects.get().end_date, self.day(6))
        [row] = WithdrawalAcknowledgement.objects.all()
        self.assertEqual((row.record_id, row.harvest, row.warning, row.until),
                         (str(treatment.pk), harvest, 'harvested', self.day(3)))
        log = AuditLog.objects.get(entity_type='treatment', severity=AuditLog.Severity.CRITICAL)
        self.assertIn('lies inside this withdrawal', log.changes['Withdrawal warnings acknowledged'][1])

    def test_the_last_day_dialog_shows_the_harvest_and_takes_its_box(self):
        treatment = self.treat(self.medicine(days=2), 8, 8)
        self.harvest(4)
        url = reverse('farm:treatment_last_day', args=[treatment.pk])
        response = self.client.post(url, {'end_date': self.day(6).isoformat()})
        self.assertEqual(response.status_code, 422)
        self.assertContains(response, 'lies inside this withdrawal', status_code=422)
        fingerprint = response.context['form'].withdrawal_change.fingerprint
        self.assertEqual(self.client.post(url, {'end_date': self.day(6).isoformat(),
                                                'withdrawal_ack': fingerprint}).status_code, 302)
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
        change = self.change_of(self.treat, bath, 5, 5)
        with mock.patch.object(check, 'second_person_must_approve', return_value=True) as asked:
            with self.assertRaises(WithdrawalChanged) as caught:
                self.treat(bath, 5, 5, withdrawal_ack=change.fingerprint)
        self.assertEqual(asked.call_count, 1)
        user, kinds, record = asked.call_args.args
        self.assertEqual((user, kinds, record.fingerprint), (self.user, ['harvested'], change.fingerprint))
        self.assertEqual(caught.exception.message_dict, {'withdrawal_ack': [
            'A second person must approve going on past a medicine withdrawal (the platform owner’s setting), and '
            'that approval cannot be given here yet.']})
        self.assertFalse(Treatment.all_objects.exists())
        self.assertFalse(check.second_person_must_approve(self.user, ['withdrawal'], change))   # off until it exists


class SecondPersonSettingTests(HarvestInsideTestCase):
    """Cross review F4: the platform owner's setting "a second person approves a withdrawal acknowledgement" is wired to
    the one hook, and fails closed while the approval flow does not exist: ticked, going on past a medicine withdrawal is
    refused with the reason (a second approver is needed), never let through by one person; its help text says so."""

    def tick(self, value=True):
        from core.models import PlatformSettings
        PlatformSettings.objects.update(second_approval_withdrawal=value)

    def test_ticked_a_withdrawal_is_never_gone_past_by_one_person(self):
        self.tick()
        self.harvest(3)
        bath = self.medicine(days=7)
        change = self.change_of(self.treat, bath, 5, 5)
        with self.assertRaises(WithdrawalChanged) as caught:
            self.treat(bath, 5, 5, withdrawal_ack=change.fingerprint)
        self.assertIn('A second person must approve', caught.exception.message_dict['withdrawal_ack'][0])
        self.assertFalse(Treatment.all_objects.exists())
        self.assertTrue(check.second_person_must_approve(self.user, ['harvested'], change))

    def test_unticked_one_persons_acknowledgement_goes_on(self):
        self.tick(False)
        self.harvest(3)
        bath = self.medicine(days=7)
        change = self.change_of(self.treat, bath, 5, 5)
        self.treat(bath, 5, 5, withdrawal_ack=change.fingerprint)
        self.assertTrue(Treatment.objects.exists())

    def test_the_help_text_tells_the_truth(self):
        from core.forms import PlatformSettingsForm
        text = str(PlatformSettingsForm.base_fields['second_approval_withdrawal'].help_text)
        self.assertIn('refused', text)
        self.assertIn('not built yet', text)


class AcknowledgementShapeTests(HarvestInsideTestCase):
    def test_a_harvested_row_names_its_harvest_and_a_released_row_none(self):
        harvest = self.harvest(3)
        base = {'record_type': 'treatment', 'record_id': '1', 'record_label': 'Treatment', 'batch': self.batch,
                'source': 'treatment:1', 'created_by': self.user}
        broken = [{'warning': 'harvested', **base}, {'warning': 'released', 'harvest': harvest, **base},
                  {'warning': 'other', **base}]
        for fields in broken:
            with self.subTest(fields=fields), self.assertRaises(IntegrityError), transaction.atomic():
                WithdrawalAcknowledgement.objects.create(**fields)
        row = WithdrawalAcknowledgement.objects.create(warning='harvested', harvest=harvest, **base)
        with self.assertRaises(Exception), transaction.atomic():
            WithdrawalAcknowledgement.objects.filter(pk=row.pk).update(reason='changed')    # append-only


class CheckWithdrawalTests(HarvestInsideTestCase):
    def test_it_lists_every_harvest_inside_a_withdrawal_and_whether_it_was_acknowledged(self):
        bath = self.medicine(days=7)
        self.harvest(3)
        change = self.change_of(self.treat, bath, 5, 5)
        self.treat(bath, 5, 5, withdrawal_ack=change.fingerprint)
        out = io.StringIO()
        call_command('check_withdrawal', stdout=out)
        self.assertIn(f'Harvest of {self.day(3).isoformat()} from T-01 · {self.batch.code} (500 fish to '
                      f'{self.facility.name}) lies inside a withdrawal until {self.day(-3).isoformat()}: Salmosan vet., '
                      f'bath', out.getvalue())
        self.assertIn('Acknowledged when the treatment was recorded.', out.getvalue())
        self.assertIn('1 harvest lies inside a medicine withdrawal.', out.getvalue())

    def test_a_harvest_a_change_outside_the_services_brings_inside_is_listed_as_not_acknowledged(self):
        bath = self.medicine(days=1)
        self.treat(bath, 5, 5)                               # held until 3 days ago
        self.harvest(3)
        with gate.opened('test: a change behind the services'):
            bath.withdrawals.update(days=7)                  # changed behind the services' back (e.g. a script)
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

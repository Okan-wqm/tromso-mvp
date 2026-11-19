"""Held fish leaving the farm are warned, never blocked (the owner's decision 12 of 19.11.2026; W-4 of REVIEW-S03).

A harvest of held fish is warned, the person ticks to go on, the acknowledgement is kept and the activity log records,
as a critical line, that held fish were harvested with the warning acknowledged. A LIVE DELIVERY (fish sold alive) of
held fish works the same way, through the same check (farm.handling.check, `WITHDRAWAL_OPERATIONS`): the same
withdrawal warning, worded for a delivery, the same box, the same rows and the same critical line. A transfer or a
grading on the farm is still not asked about the withdrawal (the fish are not eaten)."""
import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import translation

from core.models import AuditLog

from ..handling import check
from ..models import DeliveryRecord, HandlingAcknowledgement, StockOperation
from ..models.handling import HandlingKind
from ..models.stock import OperationKind
from ..stock import services as stock_services
from ..stock.dates import shown_date
from .test_harvest_inside_withdrawal import ASKED, HarvestInsideTestCase

LOGGED = 'Handling warnings acknowledged'


class LeavingTestCase(HarvestInsideTestCase):
    """T-01: A, 2,000 fish, bathed 2 days ago (7 days: harvest from 5 days ahead)."""

    def setUp(self):
        super().setUp()
        self.a = self.batch
        self.treat(self.medicine(days=7), 2, 2)
        self.until = self.day(-5)

    def deliver(self, count=400, **fields):
        return stock_services.record_delivery(self.user, unit=self.t1, batch=self.a, day=self.today, count=count,
                                              destination='Nordic Smolt AS', **fields)

    def logged(self, operation):
        """The critical line of the operation, and what it says the person went on past."""
        [entry] = [each for each in AuditLog.objects.filter(entity_type='stock operation', entity_id=str(operation.pk))
                   if LOGGED in each.changes]
        self.assertEqual(entry.severity, 'critical')
        return entry.changes[LOGGED][1]


class DeliveryTests(LeavingTestCase):
    def test_a_live_delivery_of_held_fish_is_warned_through_the_same_check(self):
        result = check.assess(HandlingKind.TRANSPORT, self.t1, self.today, self.a, operation=OperationKind.DELIVERY)
        [warning] = [each for each in result.warnings if each.warning == 'withdrawal']
        self.assertEqual(warning.block.until, self.until)
        self.assertTrue(warning.message().startswith(
            f'Not suitable for a live delivery — medicine withdrawal of {self.a.code}: harvest from '
            f'{shown_date(self.until)}. Fish sold alive may be eaten.'), warning.message())
        with self.assertRaises(ValidationError) as refused:
            self.deliver()
        self.assertEqual(refused.exception.message_dict, {'handling_ack': [ASKED['withdrawal_ack'][0]]})
        self.assertFalse(StockOperation.objects.filter(kind='delivery').exists())     # not without the tick

    def test_ticked_it_is_written_and_the_acknowledgement_is_kept_and_logged_as_critical(self):
        seen = check.assess(HandlingKind.TRANSPORT, self.t1, self.today, self.a, operation=OperationKind.DELIVERY)
        operation = self.deliver(handling_ack=seen.fingerprint)                         # never blocked
        self.assertEqual(operation.kind, 'delivery')
        row = HandlingAcknowledgement.objects.get(operation=operation, warning='withdrawal')
        self.assertEqual((row.batch, row.withdrawal_until), (self.a, self.until))
        self.assertIn('Not suitable for a live delivery', self.logged(operation))
        self.assertIn(self.a.code, self.logged(operation))

    def test_the_dialog_shows_the_warning_and_takes_the_tick(self):
        url = reverse('farm:stock_delivery', args=[self.t1.pk])
        form = self.client.get(url, headers={'X-Modal': '1'})
        self.assertContains(form, 'Not suitable for a live delivery — medicine withdrawal of ' + self.a.code)
        self.assertContains(form, 'Fish under a medicine withdrawal must not go to food.')
        data = {'token': str(uuid.uuid4()), 'batch': str(self.a.pk), 'date': self.today.isoformat(), 'count': '400',
                'measured_weight_kg': '', 'destination': 'Nordic Smolt AS', 'destination_site_number': '',
                'notes': '', 'handling_ack': ''}
        refused = self.client.post(url, data, headers={'X-Modal': '1'})
        self.assertEqual(refused.status_code, 422)
        self.assertFalse(DeliveryRecord.objects.exists())
        fingerprint = refused.context['form'].handling.fingerprint
        done = self.client.post(url, {**data, 'handling_ack': fingerprint}, headers={'X-Modal': '1'})
        self.assertEqual(done.status_code, 204)
        operation = DeliveryRecord.objects.get().operation
        self.assertTrue(HandlingAcknowledgement.objects.filter(operation=operation, warning='withdrawal').exists())
        self.assertIn('Not suitable for a live delivery', self.logged(operation))

    def test_after_the_withdrawal_a_delivery_is_not_asked_and_a_transfer_never_is(self):
        result = check.assess(HandlingKind.TRANSPORT, self.t1, self.day(-6), self.a, operation=OperationKind.DELIVERY)
        self.assertFalse([each for each in result.warnings if each.warning == 'withdrawal'])
        moved = check.assess(HandlingKind.TRANSPORT, self.t1, self.today, self.a, operation=OperationKind.TRANSFER)
        self.assertFalse([each for each in moved.warnings if each.warning == 'withdrawal'])

    def test_the_warning_is_translated(self):
        result = check.assess(HandlingKind.TRANSPORT, self.t1, self.today, self.a, operation=OperationKind.DELIVERY)
        [warning] = [each for each in result.warnings if each.warning == 'withdrawal']
        english = warning.message()
        for language in ('nb', 'tr'):
            with translation.override(language):
                said = warning.message()
            self.assertNotEqual(said.split(' — ')[0], english.split(' — ')[0], language)
            self.assertIn(self.a.code, said)


class HarvestTests(LeavingTestCase):
    def test_a_harvest_of_held_fish_is_not_blocked_and_the_log_says_it_was_acknowledged(self):
        with self.assertRaises(ValidationError) as refused:
            self.harvest(0, count=100)
        self.assertEqual(refused.exception.message_dict, {'handling_ack': [ASKED['withdrawal_ack'][0]]})
        seen = check.assess(HandlingKind.HARVEST, self.t1, self.today, self.a)
        operation = stock_services.record_harvest(self.user, unit=self.t1, batch=self.a, day=self.today, count=100,
                                                  measured_weight_kg=Decimal(13), facility=self.facility,
                                                  handling_ack=seen.fingerprint)
        row = HandlingAcknowledgement.objects.get(operation=operation, warning='withdrawal')
        self.assertEqual((row.batch, row.withdrawal_until), (self.a, self.until))
        said = self.logged(operation)
        self.assertIn(f'Not suitable for harvest — medicine withdrawal of {self.a.code}: harvest from '
                      f'{shown_date(self.until)}.', said)

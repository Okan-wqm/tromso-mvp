"""Held fish leaving the farm are warned, never blocked (the owner's decision 12 of 19.11.2026; W-4 of REVIEW-S03).

A harvest of held fish is warned, the person ticks to go on, the acknowledgement is kept and the activity log records,
as a critical line, that held fish were harvested with the warning acknowledged. A LIVE DELIVERY (fish sold alive) of
held fish works the same way, through the same check (farm.handling.check, `WITHDRAWAL_OPERATIONS`): the same
withdrawal warning, worded for a delivery, the same box, the same rows and the same critical line. A transfer or a
grading on the farm is still not asked about the withdrawal (the fish are not eaten)."""
import uuid
from datetime import time
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import translation
from django.utils.translation import gettext

from core.models import AuditLog

from ..feeding import services as feeding_services
from ..handling import check, withdrawal as withdrawal_words
from ..handling.check import Earliest
from ..handling.withdrawal import WithdrawalBlock
from ..models import DeliveryRecord, Feed, HandlingAcknowledgement, StockOperation
from ..models.handling import HandlingKind
from ..models.stock import OperationKind
from ..stock import services as stock_services
from ..stock.dates import shown_date
from .test_harvest_inside_withdrawal import ASKED, HarvestInsideTestCase
from .helpers import may_record

LOGGED = 'Handling warnings acknowledged'


class LeavingTestCase(HarvestInsideTestCase):
    """T-01: A, 2,000 fish, bathed 2 days ago (7 days: harvest from 6 days ahead)."""

    def setUp(self):
        super().setUp()
        self.a = self.batch
        self.treat(self.medicine(days=7), 2, 2)
        self.until = self.day(-6)

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
            f'Not suitable for a live delivery — medicine withdrawal of {self.a.code}: the fish may leave the farm '
            f'from {shown_date(self.until)}. Fish sold alive may be eaten.'), warning.message())
        self.assertNotIn('harvest', warning.message())             # its own words (F-1), not a slaughter's
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


class DeliveryWordingTests(LeavingTestCase):
    """The review of S-03 at 6776780, F-1: someone selling live fish reads "harvest from 21.11" as a rule about slaughter.
    A delivery's warning says when the fish may LEAVE THE FARM, its shared-unit sentence speaks of the fish being caught
    (not "at a harvest"), and its dialog shows the earliest suitable date, as a harvest's does. A harvest's words are
    unchanged."""

    def delivery(self, unit=None, day=None):
        return check.assess(HandlingKind.TRANSPORT, unit or self.t1, day or self.today, self.a,
                            operation=OperationKind.DELIVERY)

    def test_the_end_in_its_own_words_known_projected_and_unknown(self):
        day = shown_date(self.until)
        self.assertEqual(withdrawal_words.leave_from(self.until), f'the fish may leave the farm from {day}')
        self.assertEqual(withdrawal_words.leave_from(self.until, True), f'the fish may leave the farm from about {day}')
        self.assertEqual(withdrawal_words.leave_from(None), 'end unknown')
        self.assertEqual(withdrawal_words.harvest_from(self.until), f'harvest from {day}')       # a harvest's: as it was
        unknown = check.withdrawal_text(WithdrawalBlock(self.a, None, True, '', None), HandlingKind.TRANSPORT)
        self.assertEqual(unknown, f'Not suitable for a live delivery — medicine withdrawal of {self.a.code}: end '
                                  f'unknown. Fish sold alive may be eaten.')
        for language, words in (('nb', 'fisken kan forlate anlegget fra'), ('tr', 'çiftlikten çıkabilir')):
            with translation.override(language):
                self.assertIn(words, withdrawal_words.leave_from(self.until), language)
                self.assertIn(words, self.delivery().warnings[0].message(), language)

    def test_a_shared_unit_is_said_of_the_fish_being_caught_not_of_a_harvest(self):
        b = self.going_on(self.stock, self.t1, count=500, days_ago=5)            # in T-01 on the course day too
        warnings = [each for each in self.delivery().warnings if each.warning == 'withdrawal']
        self.assertEqual(sorted(each.block.batch.code for each in warnings), sorted([self.a.code, b.code]))
        for warning in warnings:
            self.assertTrue(warning.shared)
            self.assertIn('It holds every fish in T-01: the fish of different batches in one unit cannot be told '
                          'apart when they are caught.', warning.message())
            self.assertNotIn('harvest', warning.message())
        harvest = [each for each in check.assess(HandlingKind.HARVEST, self.t1, self.today, self.a).warnings
                   if each.warning == 'withdrawal']
        self.assertIn('cannot be told apart at a harvest.', harvest[0].message())          # a harvest's: unchanged
        caught = ('It holds every fish in %(unit)s: the fish of different batches in one unit cannot be told apart '
                  'when they are caught.')
        at_harvest = ('It holds every fish in %(unit)s: the fish of different batches in one unit cannot be told '
                      'apart at a harvest.')
        for language in ('nb', 'tr'):
            with translation.override(language):
                said = warnings[0].message()
                self.assertNotEqual(gettext(caught), caught, language)                     # translated
                self.assertIn(gettext(caught) % {'unit': 'T-01'}, said, language)
                self.assertNotIn(gettext(at_harvest) % {'unit': 'T-01'}, said, language)

    def test_the_earliest_suitable_date_is_a_note_of_the_delivery_dialog(self):
        day = shown_date(self.until)
        note = (f'Earliest suitable live delivery date: {day}. Medicine withdrawal decides: the fish may leave the farm '
                f'from {day}.')
        seen = self.delivery()
        self.assertEqual((seen.earliest.day, seen.earliest.decides), (self.until, 'withdrawal'))
        self.assertIn(note, seen.notes)
        dialog = self.client.get(reverse('farm:stock_delivery', args=[self.t1.pk]), headers={'X-Modal': '1'})
        self.assertContains(dialog, note)
        harvest = check.assess(HandlingKind.HARVEST, self.t1, self.today, self.a)
        self.assertIn(f'Earliest suitable harvest date: {day}. Medicine withdrawal decides: harvest from {day}.',
                      harvest.notes)
        for language in ('nb', 'tr'):
            with translation.override(language):
                self.assertNotIn(note.split(':')[0], self.delivery().earliest.text(), language)
        # A save asks for the warnings only, as a harvest's does.
        self.assertIsNone(check.assess(HandlingKind.TRANSPORT, self.t1, self.today, self.a, with_earliest=False,
                                       operation=OperationKind.DELIVERY).earliest)
        # A transfer is no delivery: no withdrawal, no earliest date.
        self.assertIsNone(check.assess(HandlingKind.TRANSPORT, self.t1, self.today, self.a,
                                       operation=OperationKind.TRANSFER).earliest)

    def test_the_fast_that_decides_a_delivery_is_the_transports_not_the_harvests_purge(self):
        """Fed yesterday at 18:00, no withdrawal: the transport's 24 h are complete from tomorrow, the harvest's 72 h
        from three days ahead; each dialog says its own, in its own words."""
        fresh =self.stock(self.t2, count=1000, days_ago=5)
        feed = Feed.objects.create(name='Grower', code='GR-1', feed_type='grower')
        may_record(self.user, 'add_feedingrecord')  # the feeding service asks (L-6)
        feeding_services.record_feeding(self.user, unit=self.t2, day=self.day(1), feed=feed, amount_kg=Decimal('1'),
                                        time=time(18, 0))
        delivery = check.earliest(self.t2, fresh, kind=HandlingKind.TRANSPORT)
        harvest = check.earliest(self.t2, fresh)
        self.assertEqual((delivery.decides, delivery.day), ('purging', self.day(-1)))
        self.assertEqual((harvest.decides, harvest.day), ('purging', self.day(-3)))
        self.assertTrue(delivery.text().startswith(f'Earliest suitable live delivery date: '
                                                   f'{shown_date(self.day(-1))}. The fast decides: feeding must stop by '),
                        delivery.text())
        self.assertTrue(harvest.text().startswith(f'Earliest suitable harvest date: {shown_date(self.day(-3))}. '
                                                  f'Purging decides: feeding must stop by '), harvest.text())
        seen = check.assess(HandlingKind.TRANSPORT, self.t2, self.today, fresh, operation=OperationKind.DELIVERY)
        self.assertIn(delivery.text(), seen.notes)
        self.assertEqual(Earliest(fresh, None, 'purging', kind=HandlingKind.TRANSPORT).text(),
                         'Earliest suitable live delivery date: not known. The fast decides.')


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

"""A live delivery is a harvest also AFTER the fact (the owner's decision 13 of 19.11.2026; F-2 of the review of S-03 at
6776780).

A delivery recorded while no withdrawal held its fish asks nothing then. A later write that puts it inside a
withdrawal asks the same question as for a harvest, through the same guard (farm.health.withdrawal.guarded) and the
same class (HarvestInside: the guard's snapshots read every line whose fish left the farm and may be eaten,
check.WITHDRAWAL_LINES): the warning in a delivery's own words, the tick to go on, the acknowledgement row
(`delivered`, naming the delivery) and the critical log line; and check_withdrawal lists it next to the harvests.
One test per kind of write that can do it: a backdated course, a longer course, a medicine's withdrawal row, a
medicated feeding, a backdated move of held fish, a void, the ceiling of an unknown end."""
import io
from decimal import Decimal
from unittest import mock

from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import translation

from core.models import AuditLog, PlatformSettings

from .. import withdrawal_gate as gate
from ..handling import check
from ..health import services
from ..health.withdrawal import WithdrawalChanged
from ..models import HandlingAcknowledgement, Treatment, WithdrawalAcknowledgement
from ..models.handling import HandlingKind
from ..models.stock import OperationKind
from ..stock import integrity, services as stock_services
from ..stock.dates import shown_date
from .helpers import rows_data
from .test_harvest_inside_withdrawal import ASKED
from .test_health import treatment_data
from .test_stock import make_unit
from .test_withdrawal_ceiling import SettingTestCase
from .test_withdrawal_combined import CombinedTestCase
from .test_withdrawal_guard import GuardTestCase

TO = 'Nordic Smolt AS'
LOGGED = 'Withdrawal warnings acknowledged'
SECOND = ('A second person must approve going on past a medicine withdrawal (the platform owner’s setting), and that '
          'approval cannot be given here yet.')


class Delivered:
    """What every case below checks, as the harvest's tests check it."""

    def deliver(self, days_ago, unit=None, batch=None, count=300, **fields):
        return stock_services.record_delivery(self.user, unit=unit or self.t1, batch=batch or self.batch,
                                              day=self.day(days_ago), count=count, destination=TO, **fields)

    def found(self, change, delivery):
        """The change's finding about the delivery: one, a delivery, asked as `delivered`."""
        [found] = [each for each in change.harvested if each.operation_id == delivery.pk]
        self.assertTrue(found.delivery)
        self.assertEqual((found.warning, found.harvest, found.destination), ('delivered', delivery.pk, TO))
        return found

    def sentence(self, delivery, batch, unit, end, fish=300):
        return (f'Live delivery of {shown_date(delivery.date)} from {unit} ({batch.code}, {fish} fish to {TO}) lies '
                f'inside this withdrawal ({end}): medicated fish sold alive may have been eaten.')

    def leave(self, day):
        return f'the fish may leave the farm from {shown_date(day)}'

    def stored(self, delivery, record_type, record_id, batch, until):
        """The one `delivered` row: it names the delivery, the write, the batch held and the end it was given for."""
        row = WithdrawalAcknowledgement.objects.get(warning='delivered')
        self.assertEqual((row.harvest, row.batch, row.until, row.record_type, row.record_id, row.created_by),
                         (delivery, batch, until, record_type, str(record_id), self.user))
        return row

    def logged(self, entity_type, entity_id):
        """The write's critical line and what it says the person went on past."""
        [entry] = [each for each in AuditLog.objects.filter(entity_type=entity_type, entity_id=str(entity_id),
                                                            severity=AuditLog.Severity.CRITICAL)
                   if LOGGED in each.changes]
        return entry.changes[LOGGED][1]

    def command(self, *args):
        out = io.StringIO()
        call_command('check_withdrawal', *args, stdout=out)
        return out.getvalue()


class CourseOverADeliveryTests(Delivered, GuardTestCase):
    """T-01: batch A, 2,000 fish. 300 of them delivered alive 3 days ago, when nothing held them."""

    def setUp(self):
        super().setUp()
        self.delivery = self.deliver(3)
        self.assertFalse(HandlingAcknowledgement.objects.exists())          # free that day: nothing asked

    def test_a_backdated_course_asks_stores_and_logs_it_as_for_a_harvest(self):
        bath = self.medicine(days=7)                         # 5 days ago: the fish may leave from 3 days ahead
        change = self.asked(self.treat, bath, 5, 5)
        self.assertFalse(Treatment.all_objects.exists())     # not without the tick
        found = self.found(change, self.delivery)
        self.assertEqual((found.until, found.approximate, found.batch, found.own), (self.day(-3), False, self.batch,
                                                                                    True))
        self.assertEqual(change.messages(), [self.sentence(self.delivery, self.batch, 'T-01', self.leave(self.day(-3)))])
        self.assertNotIn('harvest', change.messages()[0])
        treatment = self.acknowledged(change, self.treat, bath, 5, 5)
        self.stored(self.delivery, 'treatment', treatment.pk, self.batch, self.day(-3))
        self.assertEqual(self.logged('treatment', treatment.pk), change.messages()[0])

    def test_the_treatment_dialog_shows_it_and_takes_its_box(self):
        bath = self.medicine(days=7)
        url = reverse('farm:treatment_record')
        data = treatment_data([self.t1], method='bath', medicine=str(bath.pk), start_date=self.day(5).isoformat(),
                              end_date=self.day(5).isoformat())
        refused = self.client.post(url, data)
        self.assertEqual(refused.status_code, 422)
        self.assertContains(refused, f'Live delivery of {shown_date(self.day(3))} from T-01', status_code=422)
        self.assertContains(refused, 'name="withdrawal_ack"', status_code=422)
        fingerprint = refused.context['form'].withdrawal_change.fingerprint
        self.assertEqual(self.client.post(url, {**data, 'withdrawal_ack': fingerprint}).status_code, 302)
        self.assertEqual(WithdrawalAcknowledgement.objects.get().warning, 'delivered')

    def test_a_longer_course_asks(self):
        treatment = self.treat(self.medicine(days=1), 6, 6)  # free from 4 days ago: the delivery was free
        change = self.asked(services.change_last_day, self.user, treatment, self.day(4))     # free from 2 days ago
        found = self.found(change, self.delivery)
        self.assertEqual(found.until, self.day(2))
        self.assertEqual(Treatment.objects.get().end_date, self.day(6))
        self.acknowledged(change, services.change_last_day, self.user, treatment, self.day(4))
        self.stored(self.delivery, 'treatment', treatment.pk, self.batch, self.day(2))
        self.assertIn(self.sentence(self.delivery, self.batch, 'T-01', self.leave(self.day(2))),
                      self.logged('treatment', treatment.pk))

    def test_a_medicine_row_made_longer_asks_on_its_page(self):
        bath = self.medicine(days=1)
        self.treat(bath, 5, 5)                               # held until 3 days ago: the delivery of that day is free
        self.assertFalse(WithdrawalAcknowledgement.objects.exists())
        url = reverse('farm:medicine_withdrawals', args=[bath.pk])
        data = rows_data('withdrawals', [{'species': '', 'degree_days': '', 'days': '7', 'safety_margin_pct': '',
                                          'note': ''}], 0, record=bath)
        refused = self.client.post(url, data)
        self.assertEqual(refused.status_code, 422)
        self.assertContains(refused, self.sentence(self.delivery, self.batch, 'T-01', self.leave(self.day(-3))),
                            status_code=422)
        self.assertEqual(list(bath.withdrawals.values_list('days', flat=True)), [1])
        fingerprint = refused.context['withdrawal_change'].fingerprint
        self.assertEqual(self.client.post(url, {**data, 'withdrawal_ack': fingerprint}).status_code, 302)
        self.stored(self.delivery, 'medicine', bath.pk, self.batch, self.day(-3))

    def test_a_backdated_medicated_feeding_asks_with_an_unknown_end(self):
        feed = self.medicated()
        change = self.asked(self.feed, 4, feed)
        found = self.found(change, self.delivery)
        self.assertIsNone(found.until)
        self.assertEqual(change.messages(), [self.sentence(self.delivery, self.batch, 'T-01', 'end unknown')])
        record = self.acknowledged(change, self.feed, 4, feed)
        self.stored(self.delivery, 'feeding record', record.pk, self.batch, None)
        self.assertIn('Live delivery of', self.logged('feeding record', record.pk))

    def test_a_voided_delivery_is_never_inside(self):
        stock_services.void(self.user, self.delivery, 'typed on the wrong unit')
        self.treat(self.medicine(days=7), 5, 5)              # nothing asked: raises if it is
        self.assertFalse(WithdrawalAcknowledgement.objects.exists())

    def test_a_course_after_the_delivery_asks_nothing(self):
        self.treat(self.medicine(days=7), 2, 2)              # begins after the fish left
        self.assertFalse(WithdrawalAcknowledgement.objects.exists())

    def test_the_second_person_setting_refuses_it_as_it_refuses_a_harvest(self):
        bath = self.medicine(days=7)
        change = self.asked(self.treat, bath, 5, 5)
        with mock.patch.object(check, 'second_person_must_approve', return_value=True) as asked:
            with self.assertRaises(WithdrawalChanged) as caught:
                self.treat(bath, 5, 5, withdrawal_ack=change.fingerprint)
        self.assertEqual(asked.call_args.args[1], ['delivered'])
        self.assertEqual(caught.exception.message_dict, {'withdrawal_ack': [SECOND]})
        PlatformSettings.objects.update(second_approval_withdrawal=True)            # the real setting, ticked
        with self.assertRaises(WithdrawalChanged) as caught:
            self.treat(bath, 5, 5, withdrawal_ack=change.fingerprint)
        self.assertEqual(caught.exception.message_dict, {'withdrawal_ack': [SECOND]})
        self.assertFalse(Treatment.all_objects.exists())

    def test_the_question_is_translated(self):
        change = self.asked(self.treat, self.medicine(days=7), 5, 5)
        english = change.messages()[0]
        harvest = ('Harvest of %(date)s from %(unit)s (%(batch)s, %(fish)s fish to %(facility)s) lies inside this '
                   'withdrawal (%(end)s): medicated fish may have gone to food.')
        for language in ('nb', 'tr'):
            with translation.override(language):
                said = change.messages()[0]
                self.assertNotEqual(said, english, language)
                self.assertIn(self.batch.code, said)
                self.assertIn(TO, said)
                self.assertNotEqual(translation.gettext(harvest), harvest, language)
                # The harvest's ending ("medicated fish may have gone to food") is not the delivery's.
                self.assertNotIn(translation.gettext(harvest).rsplit(':', 1)[-1], said, language)

    def test_check_withdrawal_lists_it_next_to_the_harvests(self):
        bath = self.medicine(days=7)
        change = self.asked(self.treat, bath, 5, 5)
        self.acknowledged(change, self.treat, bath, 5, 5)
        out = self.command()
        self.assertIn(f'Live delivery of {self.day(3).isoformat()} from T-01 · {self.batch.code} (300 fish to {TO}) '
                      f'lies inside a withdrawal (the fish may leave the farm from {self.day(-3).isoformat()}): '
                      f'Salmosan vet., bath', out)
        self.assertIn('Acknowledged when the treatment was recorded.', out)
        self.assertIn('1 live delivery lies inside a medicine withdrawal.', out)
        self.assertIn('No harvest lies inside a medicine withdrawal.', out)
        seen = check.assess(HandlingKind.HARVEST, self.t1, self.day(2), self.batch).fingerprint
        stock_services.record_harvest(self.user, unit=self.t1, batch=self.batch, day=self.day(2), count=100,
                                      measured_weight_kg=Decimal('12'), facility=self.facility, handling_ack=seen)
        self.assertIn('1 harvest lies inside a medicine withdrawal.', self.command())
        listing = [line.split('\t') for line in self.command('--listing').splitlines() if line.startswith('inside')]
        self.assertEqual([line[:6] for line in listing], [
            ['inside', self.day(3).isoformat(), 'T-01', self.batch.code, 'delivery', '300'],
            ['inside', self.day(2).isoformat(), 'T-01', self.batch.code, 'harvest', '100']])

    def test_check_withdrawal_says_when_nobody_acknowledged_it(self):
        bath = self.medicine(days=1)
        self.treat(bath, 5, 5)                               # held until 3 days ago: the delivery is free
        with gate.opened('test: a change behind the services'):
            bath.withdrawals.update(days=7)                  # changed behind the services' back (e.g. a script)
        out = self.command()
        self.assertIn('Live delivery of', out)
        self.assertIn('Not acknowledged.', out)
        self.assertIn('1 live delivery lies inside a medicine withdrawal.', out)


class KnownWithdrawalTests(Delivered, GuardTestCase):
    def test_a_delivery_inside_a_known_withdrawal_is_asked_once_by_its_own_dialog(self):
        self.treat(self.medicine(days=7), 3, 3)
        seen = check.assess(HandlingKind.TRANSPORT, self.t1, self.day(1), self.batch, operation=OperationKind.DELIVERY)
        self.deliver(1, handling_ack=seen.fingerprint)
        self.assertFalse(WithdrawalAcknowledgement.objects.exists())        # the guard leaves its own delivery out
        out = self.command()
        self.assertIn('Acknowledged when the delivery was recorded.', out)
        self.assertIn('1 live delivery lies inside a medicine withdrawal.', out)

    def test_a_later_course_that_makes_its_withdrawal_end_later_asks_again(self):
        treatment = self.treat(self.medicine(days=2), 3, 3)  # the fish may leave from today
        seen = check.assess(HandlingKind.TRANSPORT, self.t1, self.day(1), self.batch, operation=OperationKind.DELIVERY)
        delivery = self.deliver(1, handling_ack=seen.fingerprint)
        change = self.asked(services.change_last_day, self.user, treatment, self.day(1))      # from 2 days ahead
        self.assertEqual(self.found(change, delivery).until, self.day(-2))
        with gate.opened('test: a change behind the services'):
            Treatment.objects.filter(pk=treatment.pk).update(end_date=self.day(1))    # e.g. a script
        out = self.command()
        self.assertIn('Not acknowledged (acknowledged for the fish may leave the farm from '
                      f'{self.day(0).isoformat()}; now the fish may leave the farm from {self.day(-2).isoformat()}).',
                      out)


class AcknowledgementShapeTests(Delivered, GuardTestCase):
    def test_a_delivered_row_names_its_delivery(self):
        delivery = self.deliver(3)
        base = {'record_type': 'treatment', 'record_id': '1', 'record_label': 'Treatment', 'batch': self.batch,
                'source': 'treatment:1', 'created_by': self.user}
        with self.assertRaises(IntegrityError), transaction.atomic():
            WithdrawalAcknowledgement.objects.create(warning='delivered', **base)
        row = WithdrawalAcknowledgement.objects.create(warning='delivered', harvest=delivery, **base)
        self.assertEqual(str(row.get_warning_display()), 'Live delivery inside a withdrawal')
        with self.assertRaises(Exception), transaction.atomic():
            WithdrawalAcknowledgement.objects.filter(pk=row.pk).update(reason='changed')    # append-only

    def test_check_stock_says_a_row_that_names_the_wrong_kind_of_operation(self):
        """The CHECK holds only that an operation is named; a delivered row naming a harvest (or a harvested row naming
        a delivery, or either naming a transfer) is found by the stock's integrity rules (the verification of the S-03
        follow-up, §6 and probe Q6: the database took them and check_stock said nothing)."""
        delivery = self.deliver(3, count=100)
        harvest = self.harvest(2, count=10)
        transfer = stock_services.record_transfer(self.user, source=self.t1, batch=self.batch, day=self.day(1),
                                                  legs=[(self.t2, 10)], reason='density')
        base = {'record_type': 'treatment', 'record_id': '1', 'record_label': 'Treatment', 'batch': self.batch,
                'source': 'treatment:1', 'created_by': self.user}
        WithdrawalAcknowledgement.objects.create(warning='delivered', harvest=delivery, **base)
        WithdrawalAcknowledgement.objects.create(warning='harvested', harvest=harvest, **base)
        self.assertEqual([each for each in integrity.problems() if 'Withdrawal acknowledgement' in each], [])
        wrong = [WithdrawalAcknowledgement.objects.create(warning=warning, harvest=operation, **base)
                 for warning, operation in (('delivered', harvest), ('harvested', delivery), ('delivered', transfer))]
        self.assertEqual([each for each in integrity.problems() if 'Withdrawal acknowledgement' in each], [
            f'Withdrawal acknowledgement {wrong[0].pk} (delivered) names harvest {harvest.pk}, not a delivery.',
            f'Withdrawal acknowledgement {wrong[1].pk} (harvested) names delivery {delivery.pk}, not a harvest.',
            f'Withdrawal acknowledgement {wrong[2].pk} (delivered) names transfer {transfer.pk}, not a delivery.'])


class MoveOverADeliveryTests(Delivered, CombinedTestCase):
    """CombinedTestCase: T-01 A bathed 6 days ago (the fish may leave from 2 days ahead); T-02 B, never treated."""

    def test_a_backdated_move_of_held_fish_asks_about_the_fish_delivered_since(self):
        delivery = self.deliver(1, unit=self.t2, batch=self.b)               # B is not held: nothing asked
        change = self.change_of(self.transfer, self.a, self.t1, [(self.t2, 300)], days_ago=2)
        found = self.found(change, delivery)
        self.assertEqual((found.batch, found.until, found.own, found.beside), (self.a, self.until, False, True))
        self.assertEqual(found.message(), self.sentence(delivery, self.b, 'T-02', self.leave(self.until))
                         + f' The withdrawal is of {self.a.code}, which was in T-02 with the fish delivered: the fish '
                           'of one unit cannot be told apart.')
        self.assertEqual([(each.batch.code, each.unit.code) for each in change.combined], [(self.b.code, 'T-02')])
        operation = self.transfer(self.a, self.t1, [(self.t2, 300)], days_ago=2, withdrawal_ack=change.fingerprint)
        self.stored(delivery, 'stock operation', operation.pk, self.a, self.until)
        said = self.logged('stock operation', operation.pk)
        for message in change.messages():
            self.assertIn(message, said)
        self.assertEqual(HandlingAcknowledgement.objects.get(operation=operation).batch, self.b)    # the combined lot

    def test_fish_delivered_from_where_held_fish_went_on_say_how_they_met_them(self):
        """B shares T-01 with held A 4 days ago, goes on to T-03 3 days ago, 200 delivered from T-03 yesterday: then
        the move into T-01 is entered. The delivered fish met the withdrawal in T-01, before."""
        self.transfer(self.b, self.t2, [(self.t3, 1000)], days_ago=5)
        delivery = self.deliver(1, unit=self.t3, batch=self.b, count=200)
        self.going_on(self.transfer, self.b, self.t3, [(self.t1, 500)], days_ago=4)   # asked as combined only
        self.assertEqual(WithdrawalAcknowledgement.objects.filter(warning='delivered').count(), 0)
        change = self.change_of(self.transfer, self.b, self.t1, [(self.t3, 400)], days_ago=3)
        found = self.found(change, delivery)
        self.assertFalse(found.beside)
        self.assertIn(f'The withdrawal is of {self.a.code}: the fish delivered shared T-01 with {self.a.code} before',
                      found.message())


class VoidOverADeliveryTests(Delivered, CombinedTestCase):
    def test_a_void_that_puts_held_fish_back_beside_fish_delivered_since_asks(self):
        t5 = make_unit('T-05', self.hall)
        out = self.transfer(self.a, self.t1, [(t5, 2000)], days_ago=4)      # every held A leave T-01
        self.transfer(self.b, self.t2, [(self.t1, 500)], days_ago=3)        # B into the emptied T-01: free
        delivery = self.deliver(1, unit=self.t1, batch=self.b, count=100)   # free: nothing asked
        self.assertFalse(WithdrawalAcknowledgement.objects.exists())
        change = self.change_of(stock_services.void, self.user, out, 'never happened')
        found = self.found(change, delivery)
        self.assertEqual((found.batch, found.until), (self.a, self.until))
        stock_services.void(self.user, out, 'never happened', withdrawal_ack=change.fingerprint)
        row = self.stored(delivery, 'stock operation', out.pk, self.a, self.until)
        self.assertIn(found.message(), self.logged('stock operation', out.pk))
        self.assertEqual(row.source, f'treatment:{self.treatment.pk}')


class CeilingOverADeliveryTests(Delivered, SettingTestCase):
    """A course 200 days ago with no row gave up 20 days ago: O in T-02 was free when 100 were delivered 10 days ago. A
    longer ceiling holds them again, and the delivery lies inside the withdrawal after it."""

    def test_a_longer_ceiling_asks_about_the_delivery_it_brings_inside(self):
        course = self.old_course(200)
        delivery = self.deliver(10, unit=self.t2, batch=self.o, count=100)
        refused = self.edit(365)
        self.assertEqual(refused.status_code, 422)
        self.assertContains(refused, self.sentence(delivery, self.o, 'T-02', 'end unknown', fish=100), status_code=422)
        self.assertEqual(PlatformSettings.get().unknown_withdrawal_days, 180)       # nothing saved
        change = refused.context['withdrawal_change']
        self.found(change, delivery)
        self.assertEqual(self.edit(365, withdrawal_ack=change.fingerprint).status_code, 302)
        self.assertCountEqual(
            WithdrawalAcknowledgement.objects.values_list('warning', 'batch', 'harvest', 'record_type', 'source'),
            [('delivered', self.o.pk, delivery.pk, 'platform settings', f'treatment:{course.pk}'),
             ('held', self.o.pk, None, 'platform settings', f'treatment:{course.pk}')])
        self.assertIn('Acknowledged when the platform settings was recorded.', self.command())


class AskedBeforeTheWriteTests(Delivered, GuardTestCase):
    def test_the_refusal_names_the_box(self):
        self.deliver(3)
        with self.assertRaises(WithdrawalChanged) as caught:
            self.treat(self.medicine(days=7), 5, 5)
        self.assertEqual(caught.exception.message_dict, ASKED)

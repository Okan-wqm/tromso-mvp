"""Batches of very different sizes of one species in one unit (the owner: fish of very different weights of the same
species must not be in the same tank). A stocking, a transfer or split and a grading that would leave a unit holding two
batches of a species whose averages are further apart than the species' size limit (Setup › Species) ask first, as the
max density does: without the tick nothing is written and the person reads both batches, both weights, how many times
heavier and the limit; with it the operation is written and the acknowledgement stored on it and in its log entry. A
species without a limit is not checked; cleaner fish are another species than the salmon they clean (D-1)."""
import uuid
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.urls import reverse

from core.audit import message
from core.models import AuditLog, Profile

from ..models import Batch, Species, StockOperation
from ..stock import integrity, read, services
from .test_cleaner_fish import CleanerFishTestCase
from .test_stock import DialogTests, StockTestCase, make_unit
from farm import withdrawal_gate

D = Decimal
TICK = 'Tick the box below to put them together anyway.'


def stocked(weight, day):
    """A measured weight as the message and the chip say it: the weight and the day it was measured at the stocking."""
    return f'{weight} as stocked {services.shown_date(day)}'


def mix_message(unit, species, day, heavy, light, times, limit='2×'):
    """The refusal's text: `heavy` and `light` are (batch code, weight as shown)."""
    return (f'{unit} would hold {species} of very different sizes on {services.shown_date(day)}: {heavy[0]} at '
            f'{heavy[1]} and {light[0]} at {light[1]}, {times} times as heavy, above the limit of {limit} '
            f'(Setup › Species). {TICK}')


class SizeMixTestCase(StockTestCase):
    """1,000 salmon of 4,217 g in T-01 (4,217 kg of its 5,000) since 10 days; salmon may be 2 times apart."""

    def setUp(self):
        super().setUp()
        self.salmon.max_weight_ratio = D(2)
        self.salmon.save()
        self.big = self.stock(self.t1, count=1000, weight='4217', days_ago=10)
        self.year = self.day(10).year

    def small(self, unit=None, weight='78', days_ago=5, **fields):
        return self.stock(unit or self.t1, count=1000, weight=weight, days_ago=days_ago, **fields)

    def code(self, number):
        return f'B-{self.year}-{number:03d}'


class StockingTests(SizeMixTestCase):
    def test_a_stocking_beside_a_batch_of_another_size_asks_and_writes_nothing_without_the_tick(self):
        errors = self.refused(self.small)
        self.assertEqual(errors, {'size_mix_ack': [mix_message(
            'T-01', 'Atlantic salmon (SAL)', self.day(5), (self.big.code, stocked('4,217 g', self.day(10))),
            (self.code(2), stocked('78.0 g', self.day(5))), '54.07')]})
        self.assertEqual((Batch.all_objects.count(), StockOperation.objects.count(), self.fish(self.t1)),
                         (1, 1, 1000))

    def test_with_the_tick_it_is_written_and_the_acknowledgement_stored_and_logged(self):
        small = self.small(size_mix_ack=True)
        operation = StockOperation.objects.get(movements__batch=small)
        self.assertEqual((operation.size_mix_ack, operation.over_capacity_ack), (True, False))
        entry = AuditLog.objects.get(entity_type='stock operation', entity_id=str(operation.pk))
        self.assertEqual(entry.changes['Batches of different sizes, accepted'], [None, message('Yes')])
        self.assertEqual(self.fish(self.t1), 2000)
        self.assertEqual(integrity.problems(), [])

    def test_within_the_limit_nothing_is_asked_and_a_tick_not_needed_is_not_stored(self):
        self.small(self.t2, weight='100', days_ago=6)
        self.small(self.t2, weight='200', size_mix_ack=True)               # exactly 2 times: within the limit
        self.assertEqual(list(StockOperation.objects.filter(movements__unit=self.t2)
                              .values_list('size_mix_ack', flat=True)), [False, False])
        self.assertEqual(self.refused(self.small, self.t2, weight='99.9')['size_mix_ack'][0].split(':')[0],
                         f'T-02 would hold Atlantic salmon (SAL) of very different sizes on '
                         f'{services.shown_date(self.day(5))}')

    def test_a_species_without_a_limit_is_not_checked(self):
        self.salmon.max_weight_ratio = None
        self.salmon.save()
        self.small()
        self.assertEqual(self.fish(self.t1), 2000)

    def test_the_heaviest_and_the_lightest_are_named_whatever_the_order_they_came_in(self):
        self.stock(self.t1, count=100, weight='3000', days_ago=8)          # 1.4 times: no question
        errors = self.refused(self.stock, self.t1, count=100, weight='600', days_ago=5)
        self.assertIn(f'{self.big.code} at {stocked("4,217 g", self.day(10))} and {self.code(3)} at '
                      f'{stocked("600 g", self.day(5))}, 7.03 times as heavy',
                      errors['size_mix_ack'][0])

    def test_over_the_capacity_and_mixed_sizes_are_asked_together_and_each_tick_answers_its_own(self):
        heavy = {'count': 1000, 'weight': '900'}                           # 900 kg more: 5,117 kg of 5,000
        errors = self.refused(self.stock, self.t1, days_ago=5, **heavy)
        self.assertEqual(set(errors), {'over_capacity_ack', 'size_mix_ack'})
        self.assertEqual(set(self.refused(self.stock, self.t1, days_ago=5, ack=True, **heavy)), {'size_mix_ack'})
        self.assertEqual(set(self.refused(self.stock, self.t1, days_ago=5, size_mix_ack=True, **heavy)),
                         {'over_capacity_ack'})
        self.stock(self.t1, days_ago=5, ack=True, size_mix_ack=True, **heavy)
        operation = StockOperation.objects.get(movements__unit=self.t1, movements__count_delta=1000,
                                               movements__avg_weight_g=D(900))
        self.assertEqual((operation.over_capacity_ack, operation.size_mix_ack), (True, True))

    def test_operations_that_bring_no_fish_in_are_never_asked(self):
        small = self.small(size_mix_ack=True)
        self.mortality(small, 10)
        services.record_weighing(self.user, unit=self.t1, batch=self.big, day=self.day(1), avg_weight_g=D(5000))
        services.record_cull(self.user, unit=self.t1, batch=small, day=self.day(1), count=5, reason='grading')
        self.assertEqual(StockOperation.objects.filter(size_mix_ack=True).count(), 1)

    @withdrawal_gate.opened('test fixture: a stock operation written straight in the database')
    def test_the_database_keeps_the_acknowledgement_to_operations_that_bring_fish_in(self):
        with self.assertRaisesMessage(IntegrityError, 'chk_stock_operations_size_mix_ack_on_arrival'), \
                transaction.atomic():
            StockOperation.objects.create(kind='mortality', date=self.today, size_mix_ack=True)


class TransferAndGradingTests(SizeMixTestCase):
    def setUp(self):
        super().setUp()
        self.t3 = make_unit('T-03', self.hall)
        self.little = self.small(self.t2)                                  # 1,000 of 78 g in T-02

    def transfer(self, legs, **fields):
        return services.record_transfer(self.user, source=self.t1, batch=self.big, day=self.day(1), legs=legs,
                                        reason='split', **fields)

    def test_a_split_asks_for_the_unit_it_would_mix_only(self):
        errors = self.refused(self.transfer, [(self.t3, 400), (self.t2, 100)])
        self.assertEqual(errors, {'size_mix_ack': [mix_message(
            'T-02', 'Atlantic salmon (SAL)', self.day(1), (self.big.code, stocked('4,217 g', self.day(10))),
            (self.little.code, stocked('78.0 g', self.day(5))), '54.07')]})
        self.assertFalse(StockOperation.objects.filter(kind='transfer').exists())
        self.transfer([(self.t3, 400), (self.t2, 100)], size_mix_ack=True)
        self.assertTrue(StockOperation.objects.get(kind='transfer').size_mix_ack)
        self.assertEqual((self.fish(self.t1), self.fish(self.t2), self.fish(self.t3)), (500, 1100, 400))

    def test_a_transfer_into_an_empty_unit_or_of_the_same_batch_is_not_asked(self):
        self.transfer([(self.t3, 400)])
        services.record_transfer(self.user, source=self.t3, batch=self.big, day=self.day(0), legs=[(self.t1, 100)],
                                 reason='split')
        self.assertFalse(StockOperation.objects.filter(size_mix_ack=True).exists())

    def test_a_grading_asks_for_the_unit_a_size_class_would_mix(self):
        def grade(**fields):
            return services.record_grading(self.user, source=self.t1, batch=self.big, day=self.day(1),
                                           outputs=[(self.t2, 200, D(3500), 'Small')], remainder_avg_weight_g=D(4400),
                                           **fields)
        errors = self.refused(grade)
        self.assertIn(f'{self.big.code} at 3,500 g weighed {services.shown_date(self.day(1))} and {self.little.code} at '
                      f'{stocked("78.0 g", self.day(5))}, 44.88 times as heavy',
                      errors['size_mix_ack'][0])
        grade(size_mix_ack=True)
        self.assertTrue(StockOperation.objects.get(kind='grading').size_mix_ack)


class CleanerFishAreAnotherSpeciesTests(CleanerFishTestCase):
    """The cleaner-fish cage: 2,000 salmon of 125 g and 10,000 lumpfish of 50 g; both species 2 times apart at most."""

    def setUp(self):
        super().setUp()
        for species in (self.salmon, self.lump):
            species.max_weight_ratio = D(2)
            species.save()

    def test_cleaner_fish_are_never_weighed_against_the_salmon_but_against_their_own_kind(self):
        self.stock(self.cage2, count=100, weight='4000', days_ago=4)       # big salmon alone
        self.stock(self.cage2, count=500, weight='20', days_ago=3, species=self.lump)   # 200 times lighter: no question
        errors = self.refused(self.stock, self.cage, count=500, weight='200', days_ago=3, species=self.lump)
        self.assertIn(f'C-01 would hold Lumpfish (LUM) of very different sizes', errors['size_mix_ack'][0])
        self.assertIn(f'at {stocked("200 g", self.day(3))} and {self.lump_batch.code} at {stocked("50.0 g", self.day(10))}, '
                      '4.00 times as heavy', errors['size_mix_ack'][0])


class SizeMixDialogTests(SizeMixTestCase):
    post = DialogTests.post
    input_data = DialogTests.input_data

    def test_the_stocking_dialog_shows_the_question_and_its_box_and_saves_with_the_tick(self):
        url = reverse('farm:stock_input')
        data = self.input_data([(self.t1, 1000)], count='1000', avg_weight_g='78', input_date=self.day(5).isoformat())
        response = self.post(url, data)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.context['form'].errors['size_mix_ack'], [mix_message(
            'T-01', 'Atlantic salmon (SAL)', self.day(5), (self.big.code, stocked('4,217 g', self.day(10))),
            (self.code(2), stocked('78.0 g', self.day(5))), '54.07')])
        self.assertContains(response, 'name="size_mix_ack"', status_code=422)
        self.assertNotContains(response, 'name="over_capacity_ack"', status_code=422)   # only the box asked for
        self.assertEqual(Batch.all_objects.count(), 1)
        self.assertEqual(self.post(url, {**data, 'size_mix_ack': 'on'}).status_code, 204)
        self.assertTrue(StockOperation.objects.get(movements__avg_weight_g=D(78)).size_mix_ack)

    def test_the_transfer_dialog_asks_too_and_both_boxes_show_when_both_are_asked(self):
        self.small(self.t2)
        url = f'{reverse("farm:stock_transfer", args=[self.t1.pk])}?unit={self.t1.pk}'
        data = {'token': str(uuid.uuid4()), 'batch': str(self.big.pk), 'date': self.day(1).isoformat(),
                'reason': 'density', 'notes': '', 'rows-TOTAL_FORMS': '1', 'rows-INITIAL_FORMS': '0',
                'rows-MIN_NUM_FORMS': '1', 'rows-MAX_NUM_FORMS': '12', 'rows-0-unit': str(self.t2.pk),
                'rows-0-count': '990'}                                     # 4,175 kg into T-02's 5,000 beside 78 kg
        response = self.post(url, data)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(set(response.context['form'].errors), {'size_mix_ack'})
        data['rows-0-count'] = '1000'                                      # 78 + 770 + 4,217 kg: over the 5,000
        self.stock(self.t2, count=1100, weight='700', days_ago=4, size_mix_ack=True)
        response = self.post(url, data)
        self.assertEqual(set(response.context['form'].errors), {'over_capacity_ack', 'size_mix_ack'})
        self.assertContains(response, 'name="over_capacity_ack"', status_code=422)
        self.assertContains(response, 'name="size_mix_ack"', status_code=422)
        response = self.post(url, {**data, 'over_capacity_ack': 'on', 'size_mix_ack': 'on'})
        self.assertEqual(response.status_code, 204)
        operation = StockOperation.objects.get(kind='transfer')
        self.assertEqual((operation.over_capacity_ack, operation.size_mix_ack), (True, True))

    def test_the_question_speaks_each_language(self):
        url = reverse('farm:stock_input')
        data = self.input_data([(self.t1, 1000)], count='1000', avg_weight_g='78', input_date=self.day(5).isoformat())
        for language, words in {'nb': ('svært ulik størrelse', 'sette dem sammen likevel'),
                                'tr': ('çok farklı boyda', 'yine de bir araya')}.items():
            Profile.objects.update_or_create(user=self.user, defaults={'language': language})
            with self.subTest(language=language):
                response = self.post(url, {**data, 'token': str(uuid.uuid4())})
                for word in words:
                    self.assertContains(response, word, status_code=422)

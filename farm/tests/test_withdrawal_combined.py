"""What the review of S-03 asked for beside the rule itself.

- **The spread is said at the move** (the owner's decision 8 of 16.11.2026; review F-1): a transfer, a split, a grading
  or a stocking that combines held fish with fish that are not held, in either direction, asks the tick with a
  sentence naming the fish that will now wait, stores the acknowledgement on the operation and logs it critical; the
  move is allowed. A move dated in the past that newly holds fish asks too, for every lot it reaches.
- **What a reader loads and a write locks does not grow with the farm's history** (F-3): counted on a ledger with two
  and with eight generations of fish that are long gone.
- **`check_withdrawal --listing`** (F-4): the two lists as stable, sorted lines, to be compared before and after.
- **The Norwegian and Turkish sentences** say that the OTHER batch was treated, not the fish that shared its unit (F-5).
"""
import io
import uuid
from decimal import Decimal

from django.core.management import call_command
from django.urls import reverse
from django.utils import translation

from core.models import AuditLog

from ..health import withdrawal
from ..models import Batch, HandlingAcknowledgement, StockOperation, WithdrawalAcknowledgement
from ..stock import read as stock_read, services as stock_services
from ..stock.dates import shown_date
from .helpers import correction_window
from .test_harvest_inside_withdrawal import HarvestInsideTestCase
from .test_stock import make_unit


class CombinedTestCase(HarvestInsideTestCase):
    """T-01: batch A, bathed 6 days ago (7 days: harvest from 2 days ahead). T-02: batch B, never treated. T-03, T-04:
    empty."""

    def setUp(self):
        super().setUp()
        self.a = self.batch
        self.b = self.stock(self.t2, count=3000, days_ago=9)
        self.t3, self.t4 = make_unit('T-03', self.hall), make_unit('T-04', self.hall)
        self.treatment = self.treat(self.medicine(days=7), 6, 6)
        self.until = self.day(-2)

    def transfer(self, batch, source, legs, days_ago=0, **fields):
        return stock_services.record_transfer(self.user, source=source, batch=batch, day=self.day(days_ago),
                                              legs=legs, reason='density', **fields)

    def asked(self, call, *args, **kwargs):
        """The lots the write is asked about as newly held: [(batch, unit, end)], and the change."""
        change = self.change_of(call, *args, **kwargs)
        return [(each.batch.code, each.unit.code, each.until) for each in change.combined], change

    def sentence(self, batch, unit, other, where):
        return (f'{batch.code} in {unit} will wait for the harvest with {other.code}, the held fish it is combined '
                f'with in {where}: harvest from {shown_date(self.until)}.')


class SaidAtTheMoveTests(CombinedTestCase):
    def test_held_fish_moved_in_beside_fish_that_are_not_held_ask_and_store_it(self):
        combined, change = self.asked(self.transfer, self.a, self.t1, [(self.t2, 500)])
        self.assertEqual(combined, [(self.b.code, 'T-02', self.until)])
        [message] = change.messages()
        self.assertIn(self.sentence(self.b, 'T-02', self.a, 'T-02'), message)
        self.assertFalse(StockOperation.objects.filter(kind='transfer').exists())       # nothing written yet
        operation = self.transfer(self.a, self.t1, [(self.t2, 500)], withdrawal_ack=change.fingerprint)
        row = HandlingAcknowledgement.objects.get()
        self.assertEqual((row.operation, row.warning, row.batch, row.withdrawal_until, row.withdrawal_source),
                         (operation, 'withdrawal', self.b, self.until, f'treatment:{self.treatment.pk}'))
        self.assertIn(self.sentence(self.b, 'T-02', self.a, 'T-02'), row.withdrawal_reason)
        self.assertFalse(WithdrawalAcknowledgement.objects.exists())
        entry = AuditLog.objects.get(entity_type='stock operation', action='update', entity_id=str(operation.pk),
                                     severity='critical')
        self.assertIn(self.sentence(self.b, 'T-02', self.a, 'T-02'),
                      entry.changes['Withdrawal warnings acknowledged'][1])
        self.assertEqual([held.until for held in self.held(self.t2)], [self.until])     # the move is allowed

    def test_fish_that_are_not_held_moved_in_beside_held_fish_ask(self):
        combined, change = self.asked(self.transfer, self.b, self.t2, [(self.t1, 500)])
        self.assertEqual(combined, [(self.b.code, 'T-01', self.until)])
        self.assertIn(self.sentence(self.b, 'T-01', self.a, 'T-01'), change.messages()[0])

    def test_a_split_asks_for_the_tank_with_other_fish_and_not_for_the_empty_one(self):
        c = self.stock(self.t3, count=1000, days_ago=8)
        combined, _change = self.asked(self.transfer, self.a, self.t1, [(self.t3, 300), (self.t4, 300)])
        self.assertEqual(combined, [(c.code, 'T-03', self.until)])

    def test_a_grading_asks_in_both_directions(self):
        def grade(batch, source, target, **fields):
            return stock_services.record_grading(self.user, source=source, batch=batch, day=self.today,
                                                 outputs=[(target, 400, Decimal(140), 'Large')],
                                                 remainder_avg_weight_g=Decimal(120), **fields)
        combined, _change = self.asked(grade, self.a, self.t1, self.t2)
        self.assertEqual(combined, [(self.b.code, 'T-02', self.until)])
        combined, _change = self.asked(grade, self.b, self.t2, self.t1)
        self.assertEqual(combined, [(self.b.code, 'T-01', self.until)])

    def test_a_batch_stocked_into_a_held_tank_asks(self):
        def stock(**fields):
            return stock_services.record_input(self.user, species=self.salmon, input_stage='smolt', origin='purchased',
                                               day=self.today, lines=[(self.t1, 200, Decimal(125))],
                                               supplier=self.supplier, **fields)
        change = self.change_of(stock)
        [found] = change.combined
        self.assertEqual((found.unit.code, found.until), ('T-01', self.until))
        self.assertFalse(Batch.objects.exclude(pk__in=[self.a.pk, self.b.pk]).exists())
        stock(withdrawal_ack=change.fingerprint)
        new = Batch.objects.exclude(pk__in=[self.a.pk, self.b.pk]).get()
        self.assertEqual(HandlingAcknowledgement.objects.get().batch, new)

    def test_an_unknown_end_is_said_as_unknown(self):
        self.going_on(self.treat, self.medicine(name='No row'), 4, 4)
        combined, change = self.asked(self.transfer, self.a, self.t1, [(self.t2, 500)])
        self.assertEqual(combined, [(self.b.code, 'T-02', None)])
        self.assertIn(f'{self.b.code} in T-02 will wait for the harvest with {self.a.code}, the held fish it is '
                      'combined with in T-02, and the end of that withdrawal is not known.', change.messages()[0])

    def test_a_move_dated_in_the_past_asks_for_every_lot_it_newly_holds(self):
        self.transfer(self.b, self.t2, [(self.t3, 500)], days_ago=2)        # B's fish went on to T-03 two days ago
        combined, _change = self.asked(self.transfer, self.a, self.t1, [(self.t2, 500)], days_ago=3)
        self.assertCountEqual(combined, [(self.b.code, 'T-02', self.until), (self.b.code, 'T-03', self.until)])

    def test_held_fish_moved_into_an_empty_tank_and_fish_that_are_not_held_ask_nothing(self):
        self.transfer(self.a, self.t1, [(self.t3, 500)])                    # held fish alone: they were held already
        self.transfer(self.b, self.t2, [(self.t4, 500)])                    # nobody is held
        self.assertFalse(HandlingAcknowledgement.objects.exists())
        self.assertFalse(WithdrawalAcknowledgement.objects.exists())

    def test_the_transfer_dialog_shows_the_sentence_and_takes_the_tick(self):
        url = reverse('farm:stock_transfer', args=[self.t1.pk])
        data = {'token': str(uuid.uuid4()), 'batch': str(self.a.pk), 'date': self.today.isoformat(),
                'reason': 'density', 'notes': '', 'rows-TOTAL_FORMS': '1', 'rows-INITIAL_FORMS': '0',
                'rows-MIN_NUM_FORMS': '1', 'rows-MAX_NUM_FORMS': '12', 'rows-0-unit': str(self.t2.pk),
                'rows-0-count': '500'}
        refused = self.client.post(url, data)
        self.assertEqual(refused.status_code, 422)
        self.assertContains(refused, self.sentence(self.b, 'T-02', self.a, 'T-02'), status_code=422)
        self.assertContains(refused, 'name="withdrawal_ack"', status_code=422)
        fingerprint = refused.context['form'].withdrawal_change.fingerprint
        self.assertEqual(self.client.post(url, {**data, 'withdrawal_ack': fingerprint}).status_code, 302)
        self.assertEqual(HandlingAcknowledgement.objects.get().batch, self.b)


class SentenceTests(CombinedTestCase):
    """Review F-5: in Norwegian and Turkish the bracket read as if the fish that only SHARED the unit were treated."""

    def setUp(self):
        super().setUp()
        self.going_on(self.transfer, self.b, self.t2, [(self.t1, 500)], days_ago=4)
        self.going_on(self.transfer, self.b, self.t1, [(self.t3, 500)], days_ago=2)
        [self.hold] = self.held(self.t3)

    def test_the_bracket_is_about_the_batch_that_was_treated(self):
        self.assertIn(f'These fish shared T-01 with {self.a.code} (treated in T-01).', withdrawal.describe(self.hold))
        with translation.override('nb'):
            self.assertIn(f'Denne fisken delte T-01 med {self.a.code} (som ble behandlet i T-01).',
                          withdrawal.describe(self.hold))
        with translation.override('tr'):
            self.assertIn(f'Bu balıklar T-01 birimini {self.a.code} ile paylaştı (T-01 içinde tedavi edilen parti).',
                          withdrawal.describe(self.hold))

    def test_the_combined_sentence_is_translated(self):
        change = self.change_of(self.transfer, self.a, self.t1, [(self.t2, 500)])
        for language, words in (('nb', 'venter på slakt'), ('tr', 'hasat için')):
            with translation.override(language):
                self.assertIn(words, change.messages()[0], language)


class ListingTests(CombinedTestCase):
    def test_the_listing_is_stable_sorted_lines_of_the_two_lists(self):
        self.going_on(self.transfer, self.b, self.t2, [(self.t1, 500)], days_ago=4)
        self.going_on(self.transfer, self.b, self.t1, [(self.t3, 500)], days_ago=2)
        seen = withdrawal.check.assess('harvest', self.t3, self.today, self.b).fingerprint
        stock_services.record_harvest(self.user, unit=self.t3, batch=self.b, day=self.today, count=100,
                                      measured_weight_kg=Decimal('13'), facility=self.facility, handling_ack=seen)
        out = io.StringIO()
        call_command('check_withdrawal', '--listing', stdout=out)
        lines = out.getvalue().splitlines()
        self.assertEqual(lines, sorted(lines))
        day, until = self.today.isoformat(), self.until.isoformat()
        cause = f'treatment of {self.day(6).isoformat()}'
        self.assertEqual([line.split('\t')[:6] for line in lines if line.startswith('held')], [
            ['held', 'T-01', self.a.code, until, '', cause],
            ['held', 'T-03', self.b.code, until, '', cause]])
        self.assertEqual([line.split('\t') for line in lines if line.startswith('inside')], [
            ['inside', day, 'T-03', self.b.code, '100', self.a.code, until, '', cause]])
        again = io.StringIO()
        call_command('check_withdrawal', '--listing', stdout=again)
        self.assertEqual(again.getvalue(), out.getvalue())


class HistoryTests(HarvestInsideTestCase):
    """Review F-3: what is read and locked is bounded by the holds in force, not by the farm's history."""

    def generations(self, count):
        """`count` generations of fish that are long gone: each was stocked in its own tank, bathed there (7 days),
        joined the generation before it in the shared tank MIX for a week, and was harvested out. Every one of them
        shared MIX with the next, so the farm's history is one chain up to the fish of today (T-01, which joined the
        last generation in MIX before that one left)."""
        mix = make_unit('MIX', self.hall)
        bath = self.medicine(name='Old bath', days=7)
        with correction_window(3650):
            for index in range(count, 0, -1):
                start = 100 + 60 * index
                tank = make_unit(f'G-{index:02d}', self.hall)
                batch = self.stock(tank, count=1000, days_ago=start)
                self.going_on(self.treat, bath, start - 5, start - 5, units=[tank])
                self.going_on(stock_services.record_transfer, self.user, source=tank, batch=batch,
                              day=self.day(start - 20), legs=[(mix, 1000)], reason='density')
                self.going_on(stock_services.record_harvest, self.user, unit=mix, batch=batch,
                              day=self.day(start - 90), count=1000, measured_weight_kg=Decimal(125),
                              facility=self.facility, everything=True)
            today_fish = self.stock(self.t2, count=1000, days_ago=110)
            self.going_on(stock_services.record_transfer, self.user, source=self.t2, batch=today_fish,
                          day=self.day(95), legs=[(mix, 500)], reason='density')
        return today_fish

    def measured(self, count):
        fish = self.generations(count)
        self.treat(self.medicine(days=7), 3, 3)                             # T-01's fish are held today
        reader = withdrawal.Reader({fish.pk, self.batch.pk}, self.today)
        reader.lots()
        guard = withdrawal.snapshot({self.batch.pk}, self.today)
        locked = stock_services._reach([self.t1.pk], {self.batch.pk}, self.today)
        return {'read for a page': len(reader.batch_ids), 'read by a guard': len(guard.scope), 'locked': len(locked)}

    def test_two_generations_of_history(self):
        self.assertEqual(self.measured(2), {'read for a page': 2, 'read by a guard': 1, 'locked': 1})

    def test_eight_generations_of_history_cost_what_two_do(self):
        self.assertEqual(self.measured(8), {'read for a page': 2, 'read by a guard': 1, 'locked': 1})

    def test_the_spans_reach_what_the_walk_reaches_and_no_batch_before_the_hold(self):
        fish = self.generations(2)
        spans = stock_read.spans()
        mix = next(unit_id for unit_id, batch_id in spans if batch_id == fish.pk and unit_id != self.t2.pk)
        self.assertEqual(stock_read.reach(spans, [(mix, fish.pk, self.day(3))]), {fish.pk})
        oldest = Batch.objects.order_by('input_date').first()               # from the first of them, with no end: all
        self.assertEqual(len(stock_read.reach(spans, [(mix, oldest.pk, self.day(3000))])), 3)

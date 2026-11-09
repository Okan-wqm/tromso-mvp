"""The cross review of the size rule (REVIEW-CROSS-stock-mix, F1 to F8, F10), each finding a test that failed before its
fix:
- F1: size classes of one batch put back together are lots of their own, compared like batches, and seen by the chip;
- F2: a backdated arrival is asked about every mix (and every unit over its capacity) it makes on any later day;
- F3: a void that brings fish back beside fish of another size, or over the capacity, asks with the same boxes;
- F4: lumpfish that are a tank's own fish keep "No protocol is assigned" and "Estimate incomplete";
- F5: the weights compared and shown are the board's estimates where the feed since was credited, else the measured
  weights with the day they were measured;
- F6: the ratio is printed so that it never reads as the limit itself."""
import uuid
from datetime import timedelta
from decimal import Decimal

from django.test import SimpleTestCase
from django.urls import reverse

from core.models import AuditLog

from ..models import FeedingRecord, StockOperation
from ..stock import read, services
from ..templatetags.stock import grams
from .helpers import role
from .test_cleaner_fish import CleanerFishTestCase
from .test_protocols import PROTOCOL_KEEPER, ProtocolTestCase
from .test_size_mix import SizeMixTestCase
from .test_stock import make_unit

D = Decimal


def stocked(weight, day):
    return f'{weight} as stocked {services.shown_date(day)}'


class SameBatchSizeClassesTests(SizeMixTestCase):
    """F1: a grading keeps the batch; its size classes put back into one unit are two lots of very different sizes."""

    def setUp(self):
        super().setUp()
        self.t3 = make_unit('T-03', self.hall)
        services.record_grading(self.user, source=self.t1, batch=self.big, day=self.day(3),
                                outputs=[(self.t3, 500, D(300), 'Small')], remainder_avg_weight_g=D(8134))

    def back(self, **fields):
        return services.record_transfer(self.user, source=self.t3, batch=self.big, day=self.day(1),
                                        legs=[(self.t1, 500)], reason='split', **fields)

    def test_putting_the_classes_back_together_asks_and_the_chip_sees_it(self):
        errors = self.refused(self.back)
        self.assertEqual(errors, {'size_mix_ack': [
            f'T-01 would hold Atlantic salmon (SAL) of very different sizes on {services.shown_date(self.day(1))}: '
            f'{self.big.code} at 8,134 g weighed {services.shown_date(self.day(3))} and {self.big.code} at 300 g '
            f'weighed {services.shown_date(self.day(3))}, 27.12 times as heavy, above the limit of 2× (Setup › '
            'Species). Tick the box below to put them together anyway.']})
        self.back(size_mix_ack=True)
        self.assertTrue(StockOperation.objects.get(kind='transfer').size_mix_ack)
        mix, = read.stock_of([self.t1])[self.t1.pk].size_mixes
        self.assertEqual((mix.heavy, mix.light, mix.heavy_g, mix.light_g), (self.big, self.big, D(8134), D(300)))

    def test_a_weighing_keeps_the_classes_apart_and_a_grading_makes_them_one(self):
        self.back(size_mix_ack=True)
        services.record_weighing(self.user, unit=self.t1, batch=self.big, day=self.day(0), avg_weight_g=D(6000))
        mix, = read.stock_of([self.t1])[self.t1.pk].size_mixes
        self.assertEqual(round(mix.heavy_g / mix.light_g, 2), D('27.11'))          # the spread is not measured away
        services.record_grading(self.user, source=self.t1, batch=self.big, day=self.day(0),
                                outputs=[(self.t3, 500, D(300), 'Small')], remainder_avg_weight_g=D(8000))
        self.assertEqual(read.stock_of([self.t1])[self.t1.pk].size_mixes, [])     # graded: one size left


class LaterDaysTests(SizeMixTestCase):
    """F2: the timeline with the new operation against the timeline without it, from its date to today."""

    def test_a_backdated_stocking_is_asked_about_the_mix_it_makes_on_a_later_day(self):
        t3 = make_unit('T-03', self.hall)
        small = self.small(t3, weight='78', days_ago=5)
        errors = self.refused(self.stock, t3, count=100, weight='4000', days_ago=8)
        self.assertEqual(errors['size_mix_ack'], [
            f'T-03 would hold Atlantic salmon (SAL) of very different sizes on {services.shown_date(self.day(5))}: '
            f'{self.code(3)} at {stocked("4,000 g", self.day(8))} and {small.code} at {stocked("78.0 g", self.day(5))}, '
            '51.29 times as heavy, above the limit of 2× (Setup › Species). Tick the box below to put them together '
            'anyway.'])
        self.stock(t3, count=100, weight='4000', days_ago=8, size_mix_ack=True)
        self.assertTrue(StockOperation.objects.get(movements__unit=t3, movements__count_delta=100).size_mix_ack)

    def test_a_backdated_stocking_is_asked_about_the_capacity_it_overruns_on_a_later_day(self):
        self.salmon.max_weight_ratio = None
        self.salmon.save()
        self.stock(self.t2, count=1000, weight='4000', days_ago=5)                 # 4,000 kg of 5,000
        errors = self.refused(self.stock, self.t2, count=1000, weight='1500', days_ago=8)
        self.assertEqual(errors, {'over_capacity_ack': [
            f'T-02 would hold 5,500 kg on {services.shown_date(self.day(5))}, 110 % of its max biomass (5,000 kg at '
            '50.00 kg/m³). Tick the box below to stock it anyway.']})
        self.stock(self.t2, count=1000, weight='1500', days_ago=8, ack=True)

    def test_a_mix_there_already_is_not_asked_again(self):
        self.small(size_mix_ack=True)                                           # 78 g beside 4,217 g, accepted
        self.small(weight='80', days_ago=4, size_mix_ack=False)                 # another small lot: within its kind
        self.assertEqual(StockOperation.objects.filter(size_mix_ack=True).count(), 1)


class VoidTests(SizeMixTestCase):
    """F3: a void that brings fish back asks as an arrival does, and the void's log keeps the answer."""

    def setUp(self):
        super().setUp()
        self.t3 = make_unit('T-03', self.hall)
        self.out = services.record_transfer(self.user, source=self.t1, batch=self.big, day=self.day(4),
                                            legs=[(self.t3, 1000)], reason='split')

    def test_a_void_bringing_big_fish_back_beside_small_ones_asks(self):
        self.small(self.t1, weight='78', days_ago=3)
        errors = self.refused(services.void, self.user, self.out, 'typo')
        self.assertIn(f'T-01 would hold Atlantic salmon (SAL) of very different sizes on '
                      f'{services.shown_date(self.day(3))}', errors['size_mix_ack'][0])
        self.assertFalse(StockOperation.all_objects.get(pk=self.out.pk).is_deleted)
        services.void(self.user, self.out, 'typo', size_mix_ack=True)
        entry = AuditLog.objects.get(entity_id=str(self.out.pk), action='void')
        self.assertEqual(entry.changes['Batches of different sizes, accepted'], [None, 'Yes'])

    def test_a_void_bringing_fish_back_over_the_capacity_asks(self):
        self.salmon.max_weight_ratio = None
        self.salmon.save()
        self.small(self.t1, weight='1000', days_ago=3)                            # 1,000 kg; 5,217 kg with the void
        self.assertEqual(set(self.refused(services.void, self.user, self.out, 'typo')), {'over_capacity_ack'})
        services.void(self.user, self.out, 'typo', ack=True)
        entry = AuditLog.objects.get(entity_id=str(self.out.pk), action='void')
        self.assertEqual(entry.changes['Above the max density, accepted'], [None, 'Yes'])

    def test_the_void_dialog_shows_the_box_asked_for(self):
        self.small(self.t1, weight='78', days_ago=3)
        url = f'{reverse("farm:stock_void", args=[self.out.pk])}?unit={self.t1.pk}'
        response = self.client.post(url, {'reason': 'typo'})
        self.assertContains(response, 'name="size_mix_ack"', status_code=422)
        self.assertNotContains(response, 'name="over_capacity_ack"', status_code=422)
        self.client.post(url, {'reason': 'typo', 'size_mix_ack': 'on'})
        self.assertTrue(StockOperation.all_objects.get(pk=self.out.pk).is_deleted)


class RatioTextTests(SizeMixTestCase):
    def test_the_ratio_never_reads_as_the_limit(self):
        """F6: 204 g against 100 g is 2.04 times, never "2.0 times, above the limit of 2×"."""
        t3 = make_unit('T-03', self.hall)
        self.small(t3, weight='100', days_ago=6)
        errors = self.refused(self.small, t3, weight='204', days_ago=5)
        self.assertIn(', 2.04 times as heavy, above the limit of 2×', errors['size_mix_ack'][0])
        errors = self.refused(self.small, t3, weight='200.01', days_ago=5)
        self.assertIn(', 2.01 times as heavy', errors['size_mix_ack'][0])            # rounded up, never down to 2


class EstimatedWeightsTests(SizeMixTestCase):
    """F5: the chip on the meal board reads the board's own estimate; Production units, which shows the measured
    average, reads that with its day."""

    def setUp(self):
        super().setUp()
        self.user.groups.add(role('Board', 'view_feedingrecord', 'add_feedingrecord', *PROTOCOL_KEEPER))
        from .test_feeding import FeedingTestCase
        from ..models import Feed
        self.feed = Feed.objects.create(name='Grower 4', code='GR-4', feed_type='grower', pellet_size_mm=D(4))
        self.salmon_protocol = ProtocolTestCase.make_protocol(self, bands=((0, None, '1.00'),), columns=('8', '14'),
                                                              sfr=(('1.00', '1.00'),))
        ProtocolTestCase.assign(self, self.salmon_protocol, unit=self.t1, days_ago=10)
        ProtocolTestCase.water(self, '10', unit=self.t1, hours=0)
        self.little = self.small(size_mix_ack=True)
        self.record = FeedingTestCase.record.__get__(self)
        self.record(kilos='20', days_ago=1)

    def test_the_board_chip_shows_the_estimates_and_production_units_the_measured_weights(self):
        board = self.client.get(reverse('farm:meal_board'))
        row = next(row for row in board.context['rows'] if row['unit'] == self.t1)
        estimate = {line['batch']: line['share'].end_g for line in row['lines']}
        self.assertNotEqual(estimate[self.big], D(4217))                           # fed: the estimate moved
        self.assertContains(board, f'<span>Mixed sizes: {grams(estimate[self.big])} est. and '
                                   f'{grams(estimate[self.little])} est. (limit 2×)</span>', count=1)
        units = self.client.get(reverse('farm:production_units'))
        self.assertContains(units, f'<span>Mixed sizes: {stocked("4,217 g", self.day(10))} and '
                                   f'{stocked("78.0 g", self.day(5))} (limit 2×)</span>', count=1)


class LumpfishOfTheirOwnTests(CleanerFishTestCase):
    """F4: lumpfish alone in a hatchery tank are that tank's production fish: a missing feeding table is a real gap."""

    def test_lumpfish_alone_keep_the_warnings_and_beside_salmon_lose_them(self):
        hatch = make_unit('H-01', self.hall)
        batch = self.stock(hatch, count=5000, weight='2', days_ago=5, species=self.lump)
        self.record(kilos='0.5', days_ago=1, unit=hatch, target='cleaner_fish')
        response = self.client.get(reverse('farm:meal_board'), {'site': self.bergen.pk})
        line = next(row for row in response.context['rows'] if row['unit'] == hatch)['lines'][0]
        self.assertEqual((line['batch'], line['why'], line['share'].end.missing, line['share'].blind_days),
                         (batch, 'No protocol is assigned to these fish.', 'no_protocol', 1))
        self.assertTrue(FeedingRecord.objects.filter(unit=hatch).exists())
        cage = self.client.get(reverse('farm:meal_board'), {'site': self.fjord.pk})
        lump = next(line for row in cage.context['rows'] if row['unit'] == self.cage for line in row['lines']
                    if line['batch'] == self.lump_batch)
        self.assertEqual((lump['why'], lump['share'].end.missing), ('', 'cleaner_fish'))


class SizeAckConstraintMigrationTests(SimpleTestCase):
    """F10: migration 0035 adds its check NOT VALID, then validates it in a second step, so the table is not scanned
    under the lock that adds it; the database holds it validated."""
    databases = {'default'}

    def test_added_not_valid_then_validated(self):
        import importlib
        from django.db import connection
        from django.db.migrations.operations.special import RunSQL, SeparateDatabaseAndState
        migration = importlib.import_module('farm.migrations.0035_stock_operation_size_mix_ack').Migration
        sql = [operation.sql for item in migration.operations if isinstance(item, SeparateDatabaseAndState)
               for operation in item.database_operations if isinstance(operation, RunSQL)]
        self.assertTrue(any('NOT VALID' in text for text in sql), sql)
        self.assertTrue(any('VALIDATE CONSTRAINT chk_stock_operations_size_mix_ack_on_arrival' in text for text in sql))
        with connection.cursor() as cursor:
            cursor.execute("SELECT convalidated FROM pg_constraint WHERE conname = "
                           "'chk_stock_operations_size_mix_ack_on_arrival'")
            self.assertEqual(cursor.fetchall(), [(True,)])

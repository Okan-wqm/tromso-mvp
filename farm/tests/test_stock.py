"""The stock ledger and Operations › Production units: the fold, the one write path, the page, its
dialogs, the permissions and the integrations, each checked against the stored rows."""
import io
import random
import uuid
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from core import access, database, navigation
from core.audit import message
from core.models import AuditLog, Profile

from ..models import (
    Batch, ProductionDepartment, Site, Species, StockMovement, StockOperation, Supplier, Tank,
)
from ..stock import integrity, read, services
from ..stock.fold import Line, Op, StockError, fold
from .helpers import make_facility, make_species, role, stock_fish

Status = Tank.Status


def setUpModule():
    call_command('compile_catalogs', verbosity=0)    # the language tests read the built catalogs
STOCK_KEEPER = ('view_stockoperation', 'add_stockoperation', 'delete_stockoperation', 'view_tank', 'change_tank',
                'delete_tank', 'view_species', 'delete_species', 'view_auditlog')


# ---- the fold, without a database ------------------------------------------------------------------
def op(seq, kind, day):
    return Op(f'op{seq}', kind, date(2026, 1, day), seq)


def line(line_id, operation, kind, delta, unit='T1', batch='B1', weight=None, pair=None):
    return Line(line_id, operation, unit, batch, kind, delta, None if weight is None else Decimal(weight), pair)


class FoldTests(SimpleTestCase):
    def test_removals_leave_at_the_shares_average_and_the_last_fish_take_the_book(self):
        stocked, died, gone = op(1, 'input', 1), op(2, 'mortality', 2), op(3, 'mortality', 3)
        shares = fold([line(1, stocked, 'input', 1000, weight='50'), line(2, died, 'mortality', -100)])
        share = shares[('T1', 'B1')]
        self.assertEqual((share.count, share.grams, share.avg_weight_g, share.deaths), (900, Decimal(45000), 50, 100))
        share = fold([line(1, stocked, 'input', 3, weight='10'), line(2, died, 'mortality', -1),
                      line(3, gone, 'mortality', -2)])[('T1', 'B1')]
        self.assertEqual((share.count, share.grams), (0, 0))

    def test_a_weighing_sets_the_biomass_and_later_removals_use_its_average(self):
        lines = [line(1, op(1, 'input', 1), 'input', 1000, weight='10'),
                 line(2, op(2, 'weighing', 5), 'weighing', 0, weight='50'),
                 line(3, op(3, 'mortality', 6), 'mortality', -100)]
        share = fold(lines)[('T1', 'B1')]
        # STK-14: the source took the dead fish out at the stocking weight (10 g) and left 54.4 g.
        self.assertEqual((share.count, share.biomass_kg, share.avg_weight_g, share.last_weighed),
                         (900, Decimal(45), 50, date(2026, 1, 5)))

    def test_a_transfer_at_average_conserves_fish_and_biomass(self):
        moved = op(2, 'transfer', 2)
        shares = fold([line(1, op(1, 'input', 1), 'input', 1000, weight='20'),
                       line(3, moved, 'transfer_in', 400, unit='T2', pair=1),
                       line(2, moved, 'transfer_out', -400, pair=1)])
        source, target = shares[('T1', 'B1')], shares[('T2', 'B1')]
        self.assertEqual((source.count + target.count, source.grams + target.grams), (1000, Decimal(20000)))
        self.assertEqual((target.count, target.avg_weight_g, target.since, target.fish_in), (400, 20, date(2026, 1, 2),
                                                                                             400))

    def test_a_grading_carries_measured_weights_and_weighs_the_fish_that_stay(self):
        graded = op(2, 'grading', 3)
        shares = fold([line(1, op(1, 'input', 1), 'input', 1000, weight='10'),
                       line(2, graded, 'transfer_out', -300, weight='40', pair=1),
                       line(3, graded, 'transfer_in', 300, unit='T2', pair=1),
                       line(4, graded, 'weighing', 0, weight='25')])
        # The graded fish weigh more than the book held: no refusal, the grading is a weighing (STK-24).
        self.assertEqual(shares[('T2', 'B1')].grams, Decimal(12000))
        self.assertEqual((shares[('T1', 'B1')].count, shares[('T1', 'B1')].grams), (700, Decimal(17500)))

    def test_operations_follow_their_date_then_the_order_they_were_entered(self):
        later_entered_earlier_day = op(5, 'mortality', 2)
        lines = [line(9, later_entered_earlier_day, 'mortality', -10),
                 line(1, op(1, 'input', 1), 'input', 100, weight='5'),
                 line(4, op(4, 'weighing', 3), 'weighing', 0, weight='8')]
        share = fold(lines)[('T1', 'B1')]
        self.assertEqual((share.count, share.grams), (90, Decimal(720)))

    def test_a_new_stay_starts_its_counters_again(self):
        lines = [line(1, op(1, 'input', 1), 'input', 10, weight='5'), line(2, op(2, 'mortality', 2), 'mortality', -10),
                 line(3, op(3, 'input', 4), 'input', 20, weight='6', batch='B1')]
        share = fold(lines)[('T1', 'B1')]
        self.assertEqual((share.since, share.fish_in, share.deaths), (date(2026, 1, 4), 20, 0))

    def test_what_cannot_happen_is_refused_where_it_happens(self):
        stocked = line(1, op(1, 'input', 1), 'input', 10, weight='5')
        cases = [
            ([stocked, line(2, op(2, 'mortality', 2), 'mortality', -11)], StockError.SHORT, 10),
            ([line(2, op(2, 'weighing', 2), 'weighing', 0, weight='5')], StockError.NOTHING_TO_WEIGH, 0),
            ([stocked, line(2, op(2, 'harvest', 2), 'harvest', -5, weight='10')], StockError.OVER_BOOK, 0),
            ([line(2, op(2, 'transfer', 2), 'transfer_in', 5, pair=1)], StockError.UNPAIRED, 0),
            ([line(2, op(2, 'adjustment', 2), 'adjustment', 5)], StockError.NO_AVERAGE, 0),
        ]
        for lines, reason, available in cases:
            with self.subTest(reason=reason), self.assertRaises(StockError) as caught:
                fold(lines)
            self.assertEqual((caught.exception.reason, caught.exception.line.id, caught.exception.available),
                             (reason, lines[-1].id, available))

    def test_selected_fish_lighter_than_the_book_leave_with_their_own_weight(self):
        share = fold([line(1, op(1, 'input', 1), 'input', 100, weight='10'),
                      line(2, op(2, 'harvest', 2), 'harvest', -10, weight='30')])[('T1', 'B1')]
        self.assertEqual((share.count, share.grams), (90, Decimal(700)))


# ---- the write path --------------------------------------------------------------------------------
def make_unit(code, department, kind='tank', status=Status.PREPARING, **fields):
    measures = {
        'tank': {'shape': 'rectangular', 'material': 'fiberglass', 'length': 10, 'width': 5, 'depth': 2,
                 'max_density_kg_m3': 50},
        'pond': {'pond_type': 'earthen', 'surface_area_m2': 1000, 'depth': Decimal('1.5'), 'max_density_kg_m3': 2},
    }[kind]
    unit = Tank.objects.create(name=f'Unit {code}', code=code, kind=kind, production_department=department,
                               water_type='freshwater', status=status, **{**measures, **fields})
    unit.refresh_from_db()
    return unit


class StockTestCase(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('ali', 'ali@example.com', 'eski-sifre-123')
        self.user.groups.add(role('Stock keeper', *STOCK_KEEPER))
        self.client.force_login(self.user)
        self.bergen = Site.objects.create(name='Bergen', code='BG')
        self.tromso = Site.objects.create(name='Tromso', code='TR')
        self.hall = ProductionDepartment.objects.create(site=self.bergen, name='Hall A', code='HA')
        self.sea = ProductionDepartment.objects.create(site=self.tromso, name='Sea', code='SE')
        self.t1 = make_unit('T-01', self.hall)            # 100 m³ at 50 kg/m³: 5,000 kg
        self.t2 = make_unit('T-02', self.hall)
        self.p1 = make_unit('P-01', self.sea, 'pond', status=Status.MAINTENANCE)   # 1,500 m³ at 2 kg/m³
        self.salmon = make_species()
        self.trout = make_species('RBT', 'Rainbow trout', 'Oncorhynchus mykiss', local_name='', saltwater=False)
        self.supplier = Supplier.objects.create(name='Smolt AS', code='SMA', supplies=['live_fish', 'transport'])
        self.today = services.local_today(self.t1)

    def day(self, days_ago):
        return self.today - timedelta(days=days_ago)

    def stock(self, unit=None, count=2000, weight='125', days_ago=10, **fields):
        return stock_fish(self.user, unit or self.t1, count, weight, days_ago, species=fields.pop('species', self.salmon),
                          **fields)

    def mortality(self, batch, count, days_ago=1, unit=None, **fields):
        return services.record_mortality(self.user, unit=unit or self.t1, batch=batch, day=self.day(days_ago),
                                         count=count, cause=fields.pop('cause', 'disease'), **fields)

    def fish(self, unit):
        return read.unit_counts([unit.pk]).get(unit.pk, 0)

    def refused(self, call, *args, **kwargs):
        with self.assertRaises(ValidationError) as caught:
            call(*args, **kwargs)
        return caught.exception.message_dict

    def assertStockAddsUp(self):
        self.assertEqual(integrity.problems(), [])


class InputTests(StockTestCase):
    def test_a_batch_is_stocked_with_its_lines_and_no_count_of_its_own(self):
        operation = services.record_input(
            self.user, species=self.salmon, input_stage='smolt', origin='purchased', day=self.day(3),
            lines=[(self.t1, 3000, Decimal('80.5')), (self.t2, 2000, Decimal('80.5'))], supplier=self.supplier,
            supplier_batch_ref='AG-77', strain='AquaGen Atlantic', name='Spring smolt', notes='Healthy on arrival',
            expected_harvest_date=self.day(3) + timedelta(days=400))
        batch = Batch.objects.get()
        self.assertEqual(
            (batch.code, batch.species, batch.input_stage, batch.origin, batch.supplier, batch.supplier_batch_ref,
             batch.strain, batch.name, batch.input_date, batch.notes, batch.created_by),
            (f'B-{self.day(3).year}-001', self.salmon, 'smolt', 'purchased', self.supplier, 'AG-77', 'AquaGen Atlantic',
             'Spring smolt', self.day(3), 'Healthy on arrival', self.user))
        self.assertEqual((operation.kind, operation.date, operation.over_capacity_ack, operation.created_by),
                         ('input', self.day(3), False, self.user))
        self.assertEqual(list(StockMovement.objects.order_by('unit__code').values_list(
            'unit__code', 'batch', 'kind', 'count_delta', 'avg_weight_g')),
            [('T-01', batch.pk, 'input', 3000, Decimal('80.5000')), ('T-02', batch.pk, 'input', 2000,
                                                                   Decimal('80.5000'))])
        self.assertEqual((self.fish(self.t1), self.fish(self.t2)), (3000, 2000))
        self.assertStockAddsUp()

    def test_a_stocking_into_sixty_tanks_is_logged_with_a_label_that_fits_the_log_and_keeps_its_batch_and_date(self):
        """A research facility stocks one batch into every tank of a trial: the log's label listed every unit's code and
        overflowed its column at about 35 tanks, so the stocking failed with a database error."""
        units = [make_unit(f'RESEARCH-TANK-{number:02d}', self.hall) for number in range(60)]
        operation = services.record_input(self.user, species=self.salmon, input_stage='fry', origin='own_hatchery',
                                          day=self.day(3), lines=[(unit, 10, Decimal(5)) for unit in units])
        entry = AuditLog.objects.get(entity_type='stock operation', action='create')
        batch = Batch.objects.get()
        self.assertLessEqual(len(entry.entity_label), 255)
        self.assertTrue(entry.entity_label.startswith('Stocking · RESEARCH-TANK-00, RESEARCH-TANK-01, '))
        self.assertTrue(entry.entity_label.endswith(f', … · {batch.code} · {self.day(3).isoformat()}'))
        self.assertEqual(entry.changes['Stock lines'][1].count('RESEARCH-TANK-'), 60)      # every line is still there
        self.assertEqual(StockMovement.objects.filter(operation=operation).count(), 60)
        self.assertEqual(services.label(operation), entry.entity_label)
        small = services.record_input(self.user, species=self.salmon, input_stage='fry', origin='own_hatchery',
                                      day=self.day(2), lines=[(self.t1, 10, Decimal(5)), (self.t2, 10, Decimal(5))])
        self.assertEqual(services.label(small), f'Stocking · T-01, T-02 · {Batch.objects.latest("created_at").code} · '
                                                f'{self.day(2).isoformat()}')

    def test_batch_numbers_follow_the_year_and_are_never_given_twice(self):
        first = self.stock()
        second = self.stock(self.t2)
        services.void(self.user, StockOperation.objects.get(movements__batch=second), 'Typed into the wrong unit')
        third = self.stock(self.t2)
        year = self.day(10).year
        self.assertEqual([first.code, second.code, third.code], [f'B-{year}-001', f'B-{year}-002', f'B-{year}-003'])

    def test_the_date_is_the_farms_today_at_the_latest_and_31_days_back_at_the_earliest(self):
        def stock(day):
            return services.record_input(self.user, species=self.salmon, input_stage='fry', origin='own_hatchery',
                                         day=day, lines=[(self.t1, 10, Decimal(1))])
        self.assertEqual(self.refused(stock, self.today + timedelta(days=1)),
                         {'date': ['The date cannot be in the future.']})
        self.assertEqual(self.refused(stock, self.day(32)), {'date': ['Operations can be dated at most 31 days back.']})
        stock(self.day(31))
        self.assertEqual(Batch.objects.count(), 1)

    def test_the_farms_today_is_in_the_sites_time_zone(self):
        self.bergen.timezone = 'Asia/Tokyo'
        self.bergen.save()
        self.t1.refresh_from_db()
        from django.utils import timezone
        from zoneinfo import ZoneInfo
        self.assertEqual(services.local_today(self.t1), timezone.localdate(timezone=ZoneInfo('Asia/Tokyo')))
        self.assertEqual(services.local_today(self.p1), timezone.localdate())   # no zone: the company's (UTC)

    def test_only_units_that_take_fish_are_stocked(self):
        for status in (Status.HARVESTING, Status.CLEANING, Status.MAINTENANCE, Status.QUARANTINE, Status.INACTIVE):
            Tank.objects.filter(pk=self.t2.pk).update(status=status)
            with self.subTest(status=status):
                errors = self.refused(self.stock, self.t2)
                self.assertEqual(errors['unit'], [f'T-02 has the status {Status(status).label.lower()}, so it cannot '
                                                  'take fish: it can when it is active, preparing or fallow.'])
        self.assertFalse(Batch.all_objects.exists())

    def test_one_species_per_unit_and_several_batches_of_it(self):
        self.stock(days_ago=10)
        self.stock(days_ago=5)     # a second batch of salmon into the active unit (owner decisions Q1, Q5)
        self.assertEqual(self.fish(self.t1), 4000)
        errors = self.refused(self.stock, species=self.trout)
        self.assertEqual(errors['species'], [f'T-01 would hold Atlantic salmon (SAL) + Rainbow trout (RBT) on '
                                             f'{services.shown_date(self.day(10))}: a unit holds one species at a '
                                             'time (cleaner fish join the production fish only on a sea site).'])

    def test_a_discontinued_species_is_not_stocked(self):
        self.salmon.status = Species.Status.DISCONTINUED
        self.salmon.save()
        self.assertEqual(self.refused(self.stock)['species'],
                         ['Atlantic salmon (SAL) is discontinued: a new batch takes an active or experimental species.'])

    def test_above_the_max_biomass_only_with_the_acknowledgement(self):
        errors = self.refused(self.stock, count=50000, weight='110')          # 5,500 kg in a 5,000 kg tank
        self.assertEqual(errors['over_capacity_ack'], [
            f'T-01 would hold 5,500 kg on {services.shown_date(self.day(10))}, 110 % of its max biomass (5,000 kg at '
            '50.00 kg/m³). Tick the box below to stock it anyway.'])
        self.assertFalse(Batch.all_objects.exists())
        self.stock(count=50000, weight='110', ack=True)
        self.assertTrue(StockOperation.objects.get().over_capacity_ack)
        # A tick that was not needed is not stored as an acknowledgement.
        self.stock(self.t2, ack=True)
        self.assertFalse(StockOperation.objects.get(movements__unit=self.t2).over_capacity_ack)

    def test_the_same_form_sent_twice_records_once(self):
        token = uuid.uuid4()
        self.stock(token=token)
        with self.assertRaises(services.AlreadyRecorded):
            self.stock(token=token)
        self.assertEqual((Batch.objects.count(), StockOperation.objects.count(), self.fish(self.t1)), (1, 1, 2000))


class RemovalTests(StockTestCase):
    def test_a_mortality_takes_fish_out_at_the_average_and_keeps_the_weighed_kilos(self):
        batch = self.stock()
        self.mortality(batch, 40, measured_weight_kg=Decimal('5.4'), notes='Gill disease', cause='disease')
        line = StockMovement.objects.get(kind='mortality')
        self.assertEqual((line.count_delta, line.reason, line.measured_weight_kg, line.avg_weight_g, line.unit),
                         (-40, 'disease', Decimal('5.400'), None, self.t1))
        self.assertEqual(line.operation.notes, 'Gill disease')
        stock = read.stock_of([self.t1])[self.t1.pk]
        self.assertEqual((stock.count, stock.biomass_kg, stock.avg_weight_g, stock.deaths), (1960, 245, 125, 40))

    def test_a_cull_is_counted_apart_from_the_deaths(self):
        batch = self.stock()
        services.record_cull(self.user, unit=self.t1, batch=batch, day=self.day(1), count=100, reason='small_size')
        stock = read.stock_of([self.t1])[self.t1.pk]
        self.assertEqual((stock.count, stock.culls, stock.deaths, stock.survival), (1900, 100, 0, 100))

    def test_other_needs_a_word(self):
        batch = self.stock()
        self.assertEqual(self.refused(self.mortality, batch, 1, cause='other'),
                         {'notes': ['Say what it was: the reason is “other”.']})
        self.mortality(batch, 1, cause='other', notes='Jumped out')

    def test_no_more_fish_out_than_are_there_that_day(self):
        batch = self.stock(count=100)
        self.assertEqual(self.refused(self.mortality, batch, 101)['count'],
                         [f'Only 100 fish of {batch.code} are in T-01 on {services.shown_date(self.day(1))}.'])
        self.assertEqual(self.refused(self.mortality, batch, 1, unit=self.t2)['count'],
                         [f'No fish of {batch.code} are in T-02 on {services.shown_date(self.day(1))}.'])
        self.assertEqual(self.refused(self.mortality, batch, 1, days_ago=11)['date'],
                         [f'{batch.code} was stocked on {services.shown_date(self.day(10))}: an operation on it cannot '
                          'be dated before.'])
        self.assertEqual(self.fish(self.t1), 100)

    def test_a_backdated_operation_is_accepted_only_when_every_later_day_stays_valid(self):
        batch = self.stock(count=1000)
        self.mortality(batch, 900, days_ago=2)
        errors = self.refused(self.mortality, batch, 200, days_ago=5)
        self.assertEqual(errors['__all__'], [
            f'The mortality of {services.shown_date(self.day(2))} in T-01 would be left without its fish: only 800 fish '
            f'of {batch.code} would be there that day. Void that operation first, or correct this one.'])
        self.mortality(batch, 100, days_ago=5)      # fits: 1000 − 100 − 900 = 0
        self.assertEqual(self.fish(self.t1), 0)
        self.assertStockAddsUp()


class WeighingTests(StockTestCase):
    def test_a_bulk_sample_sets_the_average_from_that_day(self):
        batch = self.stock(count=1000, weight='10')
        services.record_weighing(self.user, unit=self.t1, batch=batch, day=self.day(2), sample_count=30,
                                 sample_weight_kg=Decimal('1.6'))
        line = StockMovement.objects.get(kind='weighing')
        self.assertEqual((line.count_delta, line.sample_count, line.sample_weight_kg, line.avg_weight_g),
                         (0, 30, Decimal('1.6000'), Decimal('53.3333')))
        self.mortality(batch, 100, days_ago=1)
        stock = read.stock_of([self.t1])[self.t1.pk]
        # 1000 × 53.3333 g weighed, 100 out at that average: 900 fish, 47,999.97 g.
        self.assertEqual((stock.count, stock.grams, stock.last_weighed), (900, Decimal('47999.97'), self.day(2)))

    def test_the_average_or_the_sample_not_both_and_only_where_fish_are(self):
        batch = self.stock()
        weigh = services.record_weighing
        common = {'unit': self.t1, 'batch': batch, 'day': self.day(1)}
        self.assertIn('avg_weight_g', self.refused(weigh, self.user, avg_weight_g=Decimal(1), sample_count=3,
                                                   sample_weight_kg=Decimal(1), **common))
        self.assertIn('avg_weight_g', self.refused(weigh, self.user, sample_count=3, **common))
        self.assertEqual(self.refused(weigh, self.user, **{**common, 'unit': self.t2}, avg_weight_g=Decimal(5)),
                         {'date': [f'No fish of {batch.code} are in T-02 on {services.shown_date(self.day(1))} to '
                                   'weigh.']})
        weigh(self.user, avg_weight_g=Decimal('140.25'), **common)
        self.assertEqual(read.stock_of([self.t1])[self.t1.pk].biomass_kg, Decimal('280.5'))


class VoidTests(StockTestCase):
    def test_a_void_gives_the_fish_back_and_keeps_the_operation_with_its_reason(self):
        batch = self.stock()
        operation = self.mortality(batch, 1000)
        services.void(self.user, operation, ' Typed 1000 instead of 100 ')
        operation = StockOperation.all_objects.get(pk=operation.pk)
        self.assertEqual((operation.is_deleted, operation.void_reason, operation.deleted_by),
                         (True, 'Typed 1000 instead of 100', self.user))
        self.assertEqual(self.fish(self.t1), 2000)
        self.assertEqual(self.refused(services.void, self.user, operation, 'again'),
                         {'__all__': ['This operation is already voided.']})
        self.assertEqual(self.refused(services.void, self.user, self.mortality(batch, 1), '  '),
                         {'reason': ['Say why it is voided.']})

    def test_a_stocking_whose_fish_are_used_later_is_voided_last(self):
        batch = self.stock()
        stocking = StockOperation.objects.get(kind='input')
        died = self.mortality(batch, 10)
        errors = self.refused(services.void, self.user, stocking, 'Wrong species')
        self.assertIn('Void that operation first', errors['__all__'][0])
        services.void(self.user, died, 'Wrong batch')
        services.void(self.user, stocking, 'Wrong species')
        self.assertTrue(Batch.all_objects.get(pk=batch.pk).is_deleted)
        self.assertEqual(self.fish(self.t1), 0)
        self.assertStockAddsUp()

    def test_only_within_the_backdating_window(self):
        batch = self.stock(days_ago=31)
        died = self.mortality(batch, 1, days_ago=31)
        StockOperation.objects.filter(pk=died.pk).update(date=self.day(32))
        self.assertEqual(self.refused(services.void, self.user, died, 'old'),
                         {'__all__': ['Operations older than 31 days cannot be voided.']})


class StatusTests(StockTestCase):
    def test_a_unit_follows_its_fish_in_and_out(self):
        Tank.objects.filter(pk=self.t2.pk).update(status=Status.FALLOW)
        batch = self.stock(self.t1)
        other = self.stock(self.t2)
        statuses = lambda: dict(Tank.objects.filter(pk__in=[self.t1.pk, self.t2.pk]).values_list('code', 'status'))
        self.assertEqual(statuses(), {'T-01': 'active', 'T-02': 'active'})
        self.mortality(batch, 2000)
        Tank.objects.filter(pk=self.t2.pk).update(status=Status.QUARANTINE)
        self.mortality(other, 2000, unit=self.t2)
        self.assertEqual(statuses(), {'T-01': 'fallow', 'T-02': 'cleaning'})
        logged = AuditLog.objects.filter(entity_type='unit').order_by('created_at')
        self.assertEqual([(entry.entity_label, entry.changes['Status']) for entry in logged], [
            ('Unit T-01 (T-01)', [message('Preparing'), message('Active')]),
            ('Unit T-02 (T-02)', [message('Fallow'), message('Active')]),
            ('Unit T-01 (T-01)', [message('Active'), message('Fallow')]),
            ('Unit T-02 (T-02)', [message('Quarantine'), message('Cleaning')]),
        ])

    def test_a_unit_in_maintenance_stays_in_it_when_emptied_and_a_void_moves_it_back(self):
        batch = self.stock()
        Tank.objects.filter(pk=self.t1.pk).update(status=Status.MAINTENANCE)
        died = self.mortality(batch, 2000)
        self.assertEqual(Tank.objects.get(pk=self.t1.pk).status, 'maintenance')
        Tank.objects.filter(pk=self.t1.pk).update(status=Status.FALLOW)
        services.void(self.user, died, 'Counted twice')
        self.assertEqual(Tank.objects.get(pk=self.t1.pk).status, 'active')

    def test_has_stock_reads_the_ledger_and_the_statuses_follow_it(self):
        self.assertFalse(self.t1.has_stock())
        batch = self.stock()
        unit = Tank.objects.get(pk=self.t1.pk)
        self.assertTrue(unit.has_stock())
        self.assertEqual(unit.next_statuses(), ['active', 'harvesting', 'maintenance', 'quarantine'])
        unit.status = Status.FALLOW
        with self.assertRaisesMessage(ValidationError, 'Fish are in the unit, so it cannot be fallow'):
            unit.full_clean()
        self.mortality(batch, 2000)
        unit = Tank.objects.get(pk=self.t1.pk)
        self.assertFalse(unit.has_stock())
        self.assertEqual(unit.next_statuses(), ['fallow', 'preparing'])


class IntegrityTests(StockTestCase):
    def test_check_stock_reports_rows_that_got_past_the_service(self):
        batch = self.stock()
        call_command('check_stock', stdout=io.StringIO())
        died = self.mortality(batch, 10)
        StockOperation.objects.filter(pk=died.pk).update(kind='cull')
        Tank.objects.filter(pk=self.t1.pk).update(status=Status.INACTIVE)
        found = integrity.problems()
        self.assertIn(f'Cull {died.pk} of {died.date} must be one cull line.', found)
        self.assertIn('Unit T-01 is inactive but holds 1990 fish.', found)
        with self.assertRaisesMessage(Exception, 'problem(s) in the stock'):
            call_command('check_stock', stdout=io.StringIO())

    def test_random_operations_never_leave_a_share_below_zero(self):
        """Stockings, removals, weighings, backdated ones and voids in a random order: whatever the service
        accepts, the stock adds up and the fold agrees with the sum of the lines."""
        rng = random.Random(20261102)
        units = [self.t1, self.t2]
        for _ in range(60):
            unit = rng.choice(units)
            present = read.stock_of([unit]).get(unit.pk)
            choice = rng.random()
            try:
                if present is None or choice < .15:
                    self.stock(unit, count=rng.randint(1, 500), weight=str(rng.randint(1, 200)),
                               days_ago=rng.randint(5, 30))
                elif choice < .55:
                    share = rng.choice(present.shares)
                    self.mortality(share.batch, rng.randint(1, share.count + 20), days_ago=rng.randint(0, 25),
                                   unit=unit)
                elif choice < .7:
                    share = rng.choice(present.shares)
                    services.record_weighing(self.user, unit=unit, batch=share.batch, day=self.day(rng.randint(0, 25)),
                                             avg_weight_g=Decimal(rng.randint(1, 300)))
                else:
                    operation = rng.choice(list(StockOperation.objects.all()))
                    services.void(self.user, operation, 'random')
            except ValidationError:
                pass
            shares = fold(read.ledger(set(Batch.all_objects.values_list('pk', flat=True))))
            self.assertTrue(all(share.count >= 0 for share in shares.values()))
        sums = dict(((row['unit_id'], row['batch_id']), row['fish']) for row in StockMovement.objects.filter(
            operation__is_deleted=False).values('unit_id', 'batch_id').annotate(fish=Sum('count_delta')))
        self.assertEqual({key: share.count for key, share in shares.items()}, sums)
        self.assertStockAddsUp()


class ConstraintTests(StockTestCase):
    """The database holds the line rules whatever writes the rows."""

    def test_the_checks(self):
        batch = self.stock()
        operation = StockOperation.objects.get()
        good = {'operation': operation, 'batch': batch, 'unit': self.t1}
        bad = [
            {'kind': 'mortality', 'count_delta': 5, 'reason': 'disease'},              # sign
            {'kind': 'input', 'count_delta': 5},                                       # weight required
            {'kind': 'mortality', 'count_delta': -5, 'reason': 'small_size'},          # a cull's reason
            {'kind': 'cull', 'count_delta': -5, 'reason': ''},                         # reason required
            {'kind': 'transfer_out', 'count_delta': -5, 'reason': 'split'},            # no pair
            {'kind': 'transfer_in', 'count_delta': 5, 'pair': 1, 'avg_weight_g': 3},   # weight inherited
            {'kind': 'weighing', 'count_delta': 0, 'avg_weight_g': 10, 'sample_count': 3,
             'sample_weight_kg': Decimal('0.1')},                                      # sample ≠ average
            {'kind': 'input', 'count_delta': 5, 'avg_weight_g': 0},                    # weight above 0
            {'kind': 'input', 'count_delta': 5, 'avg_weight_g': 1, 'measured_weight_kg': 1},   # measured on a removal only
            {'kind': 'input', 'count_delta': 5, 'avg_weight_g': 1, 'size_class': 'L'},          # size on a move only
            {'kind': 'escape', 'count_delta': -5},                                     # kind
        ]
        for fields in bad:
            with self.subTest(fields=fields), self.assertRaises(IntegrityError), transaction.atomic():
                StockMovement.objects.create(**good, **fields)
        StockMovement.objects.create(**good, kind='weighing', count_delta=0, avg_weight_g=Decimal('33.3333'),
                                     sample_count=3, sample_weight_kg=Decimal('0.1'))
        with self.assertRaises(IntegrityError), transaction.atomic():
            StockOperation.objects.filter(pk=operation.pk).update(is_deleted=True)          # a void needs its reason
        with self.assertRaises(IntegrityError), transaction.atomic():
            StockOperation.objects.create(kind='mortality', date=self.today, over_capacity_ack=True)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Batch.objects.filter(pk=batch.pk).update(supplier=self.supplier)                 # own hatchery, no supplier
        with self.assertRaises(IntegrityError), transaction.atomic():
            Batch.objects.filter(pk=batch.pk).update(expected_harvest_date=batch.input_date)


class DeletePlanTests(StockTestCase):
    def test_a_unit_with_fish_and_a_species_with_batches_stay(self):
        batch = self.stock()
        page = self.client.get(reverse('farm:tank_delete', args=[self.t1.pk]))
        self.assertContains(page, 'It holds fish: move or harvest them first.')
        self.client.post(reverse('farm:tank_delete', args=[self.t1.pk]))
        self.client.post(reverse('farm:species_delete', args=[self.salmon.pk]))
        self.assertContains(self.client.get(reverse('farm:species_delete', args=[self.salmon.pk])),
                            '1 batch still belongs to it.')
        self.assertTrue(Tank.objects.filter(pk=self.t1.pk).exists())
        self.assertTrue(Species.objects.filter(pk=self.salmon.pk).exists())
        self.assertEqual(batch.delete_blockers(), ['It has stock operations: void them first.'])
        # Emptied, the unit can go; its history stays with it.
        self.mortality(batch, 2000)
        self.client.post(reverse('farm:tank_delete', args=[self.t1.pk]))
        self.assertTrue(Tank.all_objects.get(pk=self.t1.pk).is_deleted)
        self.assertEqual(StockMovement.objects.filter(unit=self.t1).count(), 2)

    def test_a_void_that_would_put_fish_back_into_a_deleted_unit_is_refused(self):
        batch = self.stock()
        died = self.mortality(batch, 2000)
        self.client.post(reverse('farm:tank_delete', args=[self.t1.pk]))
        self.assertEqual(self.refused(services.void, self.user, died, 'oops'),
                         {'__all__': ['T-01 is deleted and would hold fish again: restore it first.']})


# ---- transfer, grading, harvest ---------------------------------------------------------------------
class TransferTests(StockTestCase):
    def setUp(self):
        super().setUp()
        self.t3 = make_unit('T-03', self.hall)
        self.batch = self.stock(count=2000, weight='125')           # 250 kg in T-01

    def transfer(self, legs, days_ago=1, reason='split', **fields):
        return services.record_transfer(self.user, source=fields.pop('source', self.t1), batch=self.batch,
                                        day=self.day(days_ago), legs=legs, reason=reason, **fields)

    def test_a_split_moves_fish_and_their_biomass_and_keeps_the_batch(self):
        operation = self.transfer([(self.t2, 600), (self.t3, 400)])
        self.assertEqual(list(operation.movements.order_by('id').values_list(
            'unit__code', 'kind', 'count_delta', 'pair', 'reason', 'avg_weight_g')), [
            ('T-01', 'transfer_out', -600, 1, 'split', None), ('T-02', 'transfer_in', 600, 1, '', None),
            ('T-01', 'transfer_out', -400, 2, 'split', None), ('T-03', 'transfer_in', 400, 2, '', None)])
        stock = read.stock_of([self.t1, self.t2, self.t3])
        self.assertEqual([(stock[unit.pk].count, stock[unit.pk].biomass_kg, stock[unit.pk].batches)
                          for unit in (self.t1, self.t2, self.t3)],
                         [(1000, 125, [self.batch]), (600, 75, [self.batch]), (400, 50, [self.batch])])
        self.assertEqual(dict(Tank.objects.values_list('code', 'status')),
                         {'T-01': 'active', 'T-02': 'active', 'T-03': 'active', 'P-01': 'maintenance'})
        self.assertStockAddsUp()

    def test_moving_every_fish_empties_the_source_and_a_void_brings_them_back(self):
        operation = self.transfer([(self.t2, 2000)], reason='maintenance')
        self.assertEqual((self.fish(self.t1), Tank.objects.get(pk=self.t1.pk).status), (0, 'fallow'))
        services.void(self.user, operation, 'Wrong unit')
        self.assertEqual((self.fish(self.t1), self.fish(self.t2)), (2000, 0))
        self.assertEqual([Tank.objects.get(pk=unit.pk).status for unit in (self.t1, self.t2)], ['active', 'fallow'])
        self.assertStockAddsUp()

    def test_what_a_transfer_cannot_do(self):
        refused = lambda *args, **kwargs: self.refused(self.transfer, *args, **kwargs)
        self.assertEqual(refused([(self.t1, 10)]), {'destinations': ['The fish cannot move into the unit they leave.']})
        self.assertEqual(refused([(self.t2, 10), (self.t2, 5)]), {'destinations': ['Each unit can be listed once.']})
        self.assertEqual(refused([]), {'destinations': ['Choose the unit the fish go into.']})
        self.assertEqual(refused([(self.t2, 2001)])['count'],
                         [f'Only 2,000 fish of {self.batch.code} are in T-01 on {services.shown_date(self.day(1))}.'])
        self.assertIn('unit', refused([(self.p1, 10)]))                      # maintenance takes no fish
        self.assertEqual(refused([(self.t2, 10)], reason='other'),
                         {'notes': ['Say what it was: the reason is “other”.']})
        trout = self.stock(self.t2, count=10, species=self.trout)
        self.assertIn('species', refused([(self.t2, 10)]))
        self.assertEqual(StockOperation.objects.filter(kind='transfer').count(), 0)
        self.assertEqual(trout.movements.count(), 1)

    def test_above_the_max_density_on_arrival_with_the_acknowledgement(self):
        self.stock(self.t2, count=39000, weight='125')                    # 4,875 kg of 5,000
        self.transfer([(self.t2, 1000)])                                   # 5,000 kg: at the max, allowed
        errors = self.refused(self.transfer, [(self.t2, 100)])
        self.assertEqual(errors['over_capacity_ack'], [
            f'T-02 would hold 5,013 kg on {services.shown_date(self.day(1))}, 100 % of its max biomass (5,000 kg at '
            '50.00 kg/m³). Tick the box below to stock it anyway.'])
        self.transfer([(self.t2, 100)], ack=True)
        self.assertEqual(list(StockOperation.objects.filter(kind='transfer').order_by('created_at')
                              .values_list('over_capacity_ack', flat=True)), [False, True])

    def test_through_the_dialog(self):
        url = f'{reverse("farm:stock_transfer", args=[self.t1.pk])}?unit={self.t1.pk}'
        form = self.client.get(url)
        self.assertEqual([unit.code for unit in form.context['rows'].forms[0].fields['unit'].queryset],
                         ['T-02', 'T-03'])                                  # not the source, not P-01 (maintenance)
        data = {'token': str(uuid.uuid4()), 'batch': str(self.batch.pk), 'date': self.day(1).isoformat(),
                'reason': 'density', 'notes': '', 'rows-TOTAL_FORMS': '2', 'rows-INITIAL_FORMS': '0',
                'rows-MIN_NUM_FORMS': '1', 'rows-MAX_NUM_FORMS': '12', 'rows-0-unit': str(self.t2.pk),
                'rows-0-count': '700', 'rows-1-unit': '', 'rows-1-count': ''}
        response = self.client.post(url, data, headers={'X-Modal': '1'})
        self.assertEqual(response['X-Modal-Redirect'], f'{reverse("farm:production_units")}?unit={self.t1.pk}')
        self.assertEqual((self.fish(self.t1), self.fish(self.t2)), (1300, 700))
        self.assertEqual(StockMovement.objects.get(kind='transfer_out').reason, 'density')
        page = self.client.get(reverse('farm:production_units'), {'unit': self.t1.pk})
        self.assertContains(page, f'Transfer recorded: 700 fish of {self.batch.code} from T-01 to T-02.')
        self.assertContains(page, 'T-02 · ' + self.batch.code + ': +700 fish')
        response = self.client.post(url, {**data, 'token': str(uuid.uuid4()), 'rows-0-count': '5000'},
                                    headers={'X-Modal': '1'})
        self.assertContains(response, f'Only 1,300 fish of {self.batch.code} are in T-01', status_code=422)


class GradingTests(StockTestCase):
    def setUp(self):
        super().setUp()
        self.t3 = make_unit('T-03', self.hall)
        self.batch = self.stock(count=2000, weight='10')            # 20 kg

    def grade(self, outputs, remainder=None, **fields):
        return services.record_grading(self.user, source=self.t1, batch=self.batch, day=self.day(1), outputs=outputs,
                                       remainder_avg_weight_g=remainder, **fields)

    def test_graded_fish_carry_their_weight_and_the_fish_that_stay_are_weighed(self):
        operation = self.grade([(self.t2, 600, Decimal(20), 'Large'), (self.t3, 400, Decimal(5), 'Small')],
                               remainder=Decimal('10.5'))
        self.assertEqual(list(operation.movements.order_by('id').values_list(
            'unit__code', 'kind', 'count_delta', 'avg_weight_g', 'size_class', 'reason')), [
            ('T-01', 'transfer_out', -600, Decimal('20.0000'), 'Large', 'grading'),
            ('T-02', 'transfer_in', 600, None, 'Large', ''),
            ('T-01', 'transfer_out', -400, Decimal('5.0000'), 'Small', 'grading'),
            ('T-03', 'transfer_in', 400, None, 'Small', ''),
            ('T-01', 'weighing', 0, Decimal('10.5000'), '', '')])
        stock = read.stock_of([self.t1, self.t2, self.t3])
        self.assertEqual([(stock[unit.pk].count, stock[unit.pk].biomass_kg) for unit in (self.t1, self.t2, self.t3)],
                         [(1000, Decimal('10.5')), (600, 12), (400, 2)])
        self.assertStockAddsUp()

    def test_the_fish_that_stay_are_weighed_and_grading_everything_needs_no_weighing(self):
        self.assertEqual(self.refused(self.grade, [(self.t2, 600, Decimal(20), 'Large')]),
                         {'avg_weight_g': ['1,400 fish stay in T-01: weigh them too.']})
        self.grade([(self.t2, 1200, Decimal(14), 'Large'), (self.t3, 800, Decimal(4), 'Small')])
        self.assertEqual((self.fish(self.t1), Tank.objects.get(pk=self.t1.pk).status), (0, 'fallow'))
        self.assertFalse(StockMovement.objects.filter(kind='weighing').exists())

    def test_through_the_dialog(self):
        url = reverse('farm:stock_grading', args=[self.t1.pk])
        data = {'token': str(uuid.uuid4()), 'batch': str(self.batch.pk), 'date': self.day(1).isoformat(),
                'remainder_avg_weight_g': '', 'notes': 'Grader 6 mm', 'rows-TOTAL_FORMS': '1',
                'rows-INITIAL_FORMS': '0', 'rows-MIN_NUM_FORMS': '1', 'rows-MAX_NUM_FORMS': '12',
                'rows-0-unit': str(self.t2.pk), 'rows-0-count': '500', 'rows-0-avg_weight_g': '18',
                'rows-0-size_class': 'Large'}
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.context['form'].errors['remainder_avg_weight_g'],
                         ['1,500 fish stay in T-01: weigh them too.'])
        self.client.post(url, {**data, 'remainder_avg_weight_g': '9'})
        operation = StockOperation.objects.get(kind='grading')
        self.assertEqual((operation.notes, self.fish(self.t2)), ('Grader 6 mm', 500))
        self.assertEqual(read.stock_of([self.t1])[self.t1.pk].biomass_kg, Decimal('13.5'))


class HarvestTests(StockTestCase):
    def setUp(self):
        super().setUp()
        self.batch = self.stock(count=2000, weight='125')           # 250 kg in the book
        self.facility = make_facility()

    def harvest(self, count, kilos, **fields):
        return services.record_harvest(self.user, unit=self.t1, batch=self.batch, day=self.day(1), count=count,
                                       measured_weight_kg=Decimal(kilos), facility=self.facility, **fields)

    def test_a_harvest_keeps_its_weighed_kilos_beside_the_book(self):
        self.harvest(500, '70')
        line = StockMovement.objects.get(kind='harvest')
        self.assertEqual((line.count_delta, line.measured_weight_kg, line.avg_weight_g), (-500, Decimal('70.000'), None))
        stock = read.stock_of([self.t1])[self.t1.pk]
        self.assertEqual((stock.count, stock.biomass_kg), (1500, Decimal('187.5')))

    def test_the_last_harvest_is_never_refused_for_weighing_more_than_the_book(self):
        Tank.objects.filter(pk=self.t1.pk).update(status=Status.HARVESTING)
        self.harvest(2000, '310')                                      # the fish grew: 310 kg against 250 in the book
        self.assertEqual((self.fish(self.t1), Tank.objects.get(pk=self.t1.pk).status), (0, 'cleaning'))
        self.assertStockAddsUp()

    def test_harvesting_everything_records_the_fish_not_found_as_an_unaccounted_loss(self):
        operation = self.harvest(1985, '255', everything=True)
        self.assertEqual(list(operation.movements.order_by('id').values_list('kind', 'count_delta', 'reason')),
                         [('adjustment', -15, 'unaccounted_loss'), ('harvest', -1985, '')])
        self.assertEqual(self.fish(self.t1), 0)
        self.assertEqual(self.refused(self.harvest, 1, '1')['count'],
                         [f'Only 0 fish of {self.batch.code} are in T-01 on {services.shown_date(self.day(1))}.'])
        self.assertStockAddsUp()

    def test_a_void_puts_the_fish_back_and_the_unit_in_use_again(self):
        operation = self.harvest(2000, '260')
        self.assertEqual(Tank.objects.get(pk=self.t1.pk).status, 'fallow')
        services.void(self.user, operation, 'Harvest was postponed')
        self.assertEqual((self.fish(self.t1), Tank.objects.get(pk=self.t1.pk).status), (2000, 'active'))

    def test_a_harvest_is_always_weighed(self):
        operation = StockOperation.objects.get()
        with self.assertRaises(IntegrityError), transaction.atomic():
            StockMovement.objects.create(operation=operation, batch=self.batch, unit=self.t1, kind='harvest',
                                         count_delta=-5)

    def test_through_the_dialog(self):
        url = reverse('farm:stock_harvest', args=[self.t1.pk])
        data = {'token': str(uuid.uuid4()), 'batch': str(self.batch.pk), 'date': self.day(1).isoformat(),
                'count': '2000', 'measured_weight_kg': '', 'facility': str(self.facility.pk), 'notes': ''}
        self.assertIn('measured_weight_kg', self.client.post(url, data).context['form'].errors)
        response = self.client.post(url, {**data, 'measured_weight_kg': '262.4', 'everything': 'on'},
                                    headers={'X-Modal': '1'})
        self.assertEqual(response.status_code, 204)
        self.assertEqual(StockMovement.objects.get(kind='harvest').measured_weight_kg, Decimal('262.400'))
        page = self.client.get(reverse('farm:production_units'), {'unit': self.t1.pk})
        self.assertContains(page, f'Harvest recorded: 2,000 fish of {self.batch.code} from T-01, 262.4 kg weighed.')
        self.assertContains(page, '262 kg weighed')


class SupplierLinkTests(StockTestCase):
    def test_bought_fish_name_a_live_fish_supplier_who_keeps_the_category_and_cannot_be_deleted(self):
        feed_mill = Supplier.objects.create(name='Feed Mill', code='FM', supplies=['feed'])
        form = self.client.get(reverse('farm:stock_input')).context['form']
        self.assertEqual(list(form.fields['supplier'].queryset), [self.supplier])
        batch = services.record_input(self.user, species=self.salmon, input_stage='smolt', origin='purchased',
                                      day=self.day(1), lines=[(self.t1, 10, Decimal(80))], supplier=self.supplier)
        batch = batch.movements.get().batch
        self.assertEqual(self.refused(services.record_input, self.user, species=self.salmon, input_stage='smolt',
                                      origin='purchased', day=self.day(1), lines=[(self.t2, 10, Decimal(80))],
                                      supplier=feed_mill), {'supplier': ['Choose a supplier of live fish and eggs.']})
        self.supplier.supplies = ['transport']
        with self.assertRaisesMessage(ValidationError, '1 batch of fish was bought from it: keep “Live fish and eggs” '
                                                       'ticked.'):
            self.supplier.full_clean()
        self.user.user_permissions.add(*Permission.objects.filter(codename__in=['view_supplier', 'delete_supplier']))
        self.client.post(reverse('farm:supplier_delete', args=[self.supplier.pk]))
        self.assertTrue(Supplier.objects.filter(pk=self.supplier.pk).exists())     # PROTECT: its fish are traced
        self.assertEqual(batch.supplier, self.supplier)


# ---- the page ----------------------------------------------------------------------------------------
class PageTests(StockTestCase):
    url = reverse('farm:production_units')

    def setUp(self):
        super().setUp()
        self.batch = self.stock(days_ago=19)
        self.mortality(self.batch, 40)

    def page(self, **query):
        return self.client.get(self.url, query)

    def codes(self, **query):
        return [row['unit'].code for row in self.page(**query).context['rows']]

    def test_every_unit_with_its_numbers_from_the_ledger(self):
        response = self.page()
        self.assertEqual(self.codes(), ['T-01', 'T-02', 'P-01'])
        row = response.context['rows'][0]
        self.assertEqual((row['stock'].count, row['stock'].biomass_kg, row['stock'].density, row['stock'].capacity,
                          row['stock'].survival), (1960, 245, Decimal('2.45'), Decimal('4.9'), 98))
        html = response.content.decode()
        for text in ('1,960', '125 g', '245 kg', '2.5 kg/m³', '5 %', '98.0 %', self.batch.code, 'Laks',
                     'Empty — ready to stock', 'Empty · Maintenance', '3 units · 245 kg',
                     '<span class="view-count">1</span>'):
            self.assertIn(text, html)
        # No weighing since stocking: no FCR yet, and why; last fed is a dash until a feeding is recorded
        # (farm/tests/test_feeding.py has the figures).
        self.assertContains(response, 'title="Not weighed since the fish came in."', count=1)
        self.assertContains(response, '<h1>Production units</h1>', html=True)

    def test_filters_and_the_drawer_are_in_the_address(self):
        self.assertEqual(self.codes(site=self.tromso.pk), ['P-01'])
        self.assertEqual(self.codes(kind='pond'), ['P-01'])
        self.assertEqual(self.codes(occupancy='stocked'), ['T-01'])
        self.assertEqual(self.codes(occupancy='empty'), ['T-02', 'P-01'])
        self.assertEqual(self.codes(status='maintenance'), ['P-01'])
        self.assertEqual(self.codes(q=self.batch.code.lower()), ['T-01'])
        self.assertEqual(self.codes(q='salmo'), ['T-01'])
        self.assertEqual(self.codes(q='p-0'), ['P-01'])
        self.assertEqual(self.codes(site='x', kind='y', occupancy='z', status='w', unit='v'), ['T-01', 'T-02', 'P-01'])
        response = self.page(kind='tank', unit=self.t1.pk)
        self.assertEqual(response.context['drawer'], self.t1)
        # Each filter button keeps the others and the drawer.
        pond = next(button for button in response.context['kind_buttons'] if button['label'] == 'Ponds')
        self.assertEqual(pond['href'], f'{self.url}?kind=pond&unit={self.t1.pk}')
        self.assertContains(response, f'href="{self.url}?kind=tank"')                        # the drawer's close link

    def test_the_picked_row_and_a_row_over_capacity_look_different(self):
        self.stock(self.t2, count=60000, weight='100', ack=True)        # 6,000 kg in 5,000 kg
        response = self.page(unit=self.t1.pk)
        self.assertContains(response, '<tr class="unit-row is-selected" aria-current="true">')
        self.assertContains(response, '<tr class="unit-row is-over">')
        self.assertContains(response, '<span class="over-badge">Over</span>', count=1)
        response = self.page(unit=self.t2.pk)
        self.assertContains(response, '<tr class="unit-row is-selected is-over" aria-current="true">')

    def test_two_empty_states(self):
        self.assertContains(self.page(q='nothing like it'), 'No units match these filters.')
        self.assertContains(self.page(q='nothing like it'), f'href="{self.url}">Clear filters')
        StockMovement.objects.all().delete()
        Tank.objects.all().delete()
        response = self.page()
        self.assertContains(response, 'No production units yet')
        self.assertContains(response, f'href="{reverse("farm:tank_list")}"')

    def test_the_drawer_of_a_stocked_unit(self):
        response = self.page(unit=self.t1.pk)
        html = response.content.decode()
        for text in ('Stocked · 19 days', 'Record mortality', 'Sampling weigh-in', 'Transfer / split', 'Grading',
                     'Record cull', 'Harvest', 'Stock another batch',
                     'Recent operations', '−40 fish · Disease', '+2,000 fish · 125 g', '40 dead · 0 culled',
                     'Max 50 kg/m³, 5,000 kg'):
            self.assertIn(text, html)
        self.assertContains(response, f'href="{reverse("farm:stock_mortality", args=[self.t1.pk])}?unit={self.t1.pk}"')
        self.assertContains(response, '>Void</a>', count=2)

    def test_the_drawer_of_an_empty_unit(self):
        response = self.page(unit=self.t2.pk)
        self.assertContains(response, 'Stock this unit')
        self.assertContains(response, f'href="{reverse("farm:stock_input")}?unit={self.t2.pk}"')
        self.assertNotContains(response, 'Record mortality')
        self.assertContains(response, 'Nothing recorded in this unit yet.')
        response = self.page(unit=self.p1.pk)
        self.assertNotContains(response, 'Stock this unit')
        self.assertContains(response, 'P-01 has the status maintenance: set it to preparing or fallow in Setup to '
                                      'stock it.')

    def test_a_voided_operation_stays_in_the_history_struck_through(self):
        services.void(self.user, StockOperation.objects.get(kind='mortality'), 'Counted the same fish twice')
        response = self.page(unit=self.t1.pk)
        self.assertContains(response, 'op-entry is-voided')
        self.assertContains(response, 'voided by ali: Counted the same fish twice')
        self.assertContains(response, '>Void</a>', count=1)

    def test_the_overview_shows_the_stock(self):
        tiles = self.client.get(reverse('production_home')).context['stock_tiles']
        self.assertEqual([(str(tile['label']), tile['count']) for tile in tiles],
                         [('Stocked units', 1), ('Fish', '1,960'), ('Biomass', '245 kg')])

    def test_the_page_speaks_each_language(self):
        for language, words in {'tr': ('Üretim birimleri', 'Boş — stoklamaya hazır', '%5', '%98,0', '245 kg',
                                       '1.960'),
                                'nb': ('Produksjonsenheter', 'Tom – klar for utsett', '5 %', '98,0 %')}.items():
            Profile.objects.update_or_create(user=self.user, defaults={'language': language})
            response = self.page(unit=self.t1.pk)
            for word in words:
                self.assertContains(response, word, msg_prefix=language)


class DialogTests(StockTestCase):
    def post(self, url, data, modal=True):
        return self.client.post(url, data, headers={'X-Modal': '1'} if modal else {})

    def input_data(self, rows, **fields):
        data = {'token': str(uuid.uuid4()), 'species': str(self.salmon.pk), 'input_stage': 'fry',
                'input_date': self.day(2).isoformat(), 'count': '5000', 'avg_weight_g': '2.5', 'origin': 'purchased',
                'supplier': str(self.supplier.pk), 'supplier_batch_ref': 'S-9', 'strain': '', 'name': '',
                'expected_harvest_date': '', 'notes': '', 'provenance': '', 'year_class': '',
                'units-TOTAL_FORMS': str(len(rows)),
                'units-INITIAL_FORMS': '0', 'units-MIN_NUM_FORMS': '1', 'units-MAX_NUM_FORMS': '20'}
        for index, (unit, count) in enumerate(rows):
            data[f'units-{index}-unit'] = str(unit.pk) if unit else ''
            data[f'units-{index}-count'] = str(count)
        data.update(fields)
        return data

    def test_a_new_batch_through_the_dialog(self):
        url = f'{reverse("farm:stock_input")}?unit={self.t1.pk}&kind=tank'
        form = self.client.get(url, headers={'X-Modal': '1'})
        self.assertContains(form, 'Stock unit T-01')
        self.assertContains(form, 'class="modal-head"')
        self.assertEqual(form.context['rows'].initial, [{'unit': self.t1.pk}])
        self.assertEqual(form.context['form']['input_date'].value(), self.today)
        response = self.post(url, self.input_data([(self.t1, 3000), (self.t2, 2000)], provenance='farmed',
                                                  year_class='2026'))
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response['X-Modal-Redirect'], f'{reverse("farm:production_units")}?kind=tank&unit={self.t1.pk}')
        batch = Batch.objects.get()
        self.assertEqual((batch.supplier, batch.supplier_batch_ref, batch.input_date, batch.origin, batch.provenance,
                          batch.year_class), (self.supplier, 'S-9', self.day(2), 'purchased', 'farmed', 2026))
        self.assertEqual(sorted(StockMovement.objects.values_list('unit__code', 'count_delta', 'avg_weight_g')),
                         [('T-01', 3000, Decimal('2.5000')), ('T-02', 2000, Decimal('2.5000'))])
        page = self.client.get(reverse('farm:production_units'))
        self.assertContains(page, f'Batch {batch.code} stocked: 5,000 fish into T-01, T-02.')

    def test_the_provenance_follows_the_origin_and_a_cleaner_fish_needs_one(self):
        url = reverse('farm:stock_input')
        own = {'origin': 'own_hatchery', 'supplier': '', 'supplier_batch_ref': ''}
        self.post(url, self.input_data([(self.t1, 5000)], **own))
        batch = Batch.objects.get()
        self.assertEqual((batch.provenance, batch.year_class), ('farmed', None))       # said by the origin; no default
        response = self.post(url, self.input_data([(self.t2, 5000)], **{**own, 'origin': 'wild'}, provenance='farmed'))
        self.assertEqual(response.context['form'].errors['provenance'],
                         ['Fish of the own hatchery are farmed, fish caught in the wild wild-caught.'])
        lumpfish = make_species('LUM', 'Lumpfish', 'Cyclopterus lumpus', local_name='Rognkjeks', freshwater=False,
                                cleaner_fish_type='lumpfish')
        response = self.post(url, self.input_data([(self.t2, 5000)], species=str(lumpfish.pk)))
        message = ['Farmed or wild-caught? The cleaner-fish report asks it of every cleaner fish.']
        self.assertEqual(response.context['form'].errors['provenance'], message)
        self.assertEqual(self.refused(services.record_input, self.user, species=lumpfish, input_stage='fry',
                                      origin='purchased', supplier=self.supplier, day=self.day(2),
                                      lines=[(self.t2, 10, Decimal(5))])['provenance'], message)
        self.assertEqual(Batch.all_objects.count(), 1)
        response = self.post(url, self.input_data([(self.t2, 5000)], species=str(lumpfish.pk), provenance='wild_caught',
                                                  year_class='1979'))
        self.assertIn('year_class', response.context['form'].errors)
        self.assertEqual(Batch.all_objects.count(), 1)

    def test_the_split_must_add_up_and_name_each_unit_once(self):
        url = reverse('farm:stock_input')
        response = self.post(url, self.input_data([(self.t1, 3000), (self.t2, 1000)]))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.context['form'].errors['count'],
                         ['The units take 4,000 fish, but 5,000 arrive: the split must add up.'])
        response = self.post(url, self.input_data([(self.t1, 3000), (self.t1, 2000)]))
        self.assertEqual(response.context['form'].non_field_errors(), ['Each unit can be listed once.'])
        response = self.post(url, self.input_data([(self.t1, 5000)], origin='own_hatchery'))
        self.assertEqual(response.context['form'].errors['supplier'], ['Only bought fish have a supplier.'])
        response = self.post(url, self.input_data([(self.p1, 5000)]))
        self.assertIn('unit', response.context['rows'].forms[0].errors)       # a unit in maintenance is not offered
        self.assertFalse(Batch.all_objects.exists())

    def test_above_the_max_density_asks_first(self):
        url = reverse('farm:stock_input')
        data = self.input_data([(self.t1, 60000)], count='60000', avg_weight_g='100')
        response = self.post(url, data)
        self.assertEqual(response.status_code, 422)
        self.assertIn('T-01 would hold 6,000 kg', response.context['form'].errors['over_capacity_ack'][0])
        self.assertContains(response, 'name="over_capacity_ack"', status_code=422)
        self.assertEqual(self.post(url, {**data, 'over_capacity_ack': 'on'}).status_code, 204)
        self.assertTrue(StockOperation.objects.get().over_capacity_ack)

    def test_a_form_sent_twice_stocks_once(self):
        data = self.input_data([(self.t1, 5000)])
        self.post(reverse('farm:stock_input'), data)
        self.assertEqual(self.post(reverse('farm:stock_input'), data).status_code, 204)
        self.assertEqual(StockMovement.objects.count(), 1)

    def test_mortality_cull_and_weighing_through_their_dialogs(self):
        batch = self.stock()
        base = {'token': str(uuid.uuid4()), 'batch': str(batch.pk), 'date': self.day(1).isoformat(), 'notes': ''}
        url = reverse('farm:stock_mortality', args=[self.t1.pk])
        form = self.client.get(url).context['form']
        self.assertEqual((form.only_batch.batch, form['batch'].field.widget.input_type), (batch, 'hidden'))
        response = self.post(f'{url}?unit={self.t1.pk}', {**base, 'count': '25', 'cause': 'oxygen',
                                                         'measured_weight_kg': '3.1'})
        self.assertEqual(response['X-Modal-Redirect'], f'{reverse("farm:production_units")}?unit={self.t1.pk}')
        self.assertEqual(list(StockMovement.objects.filter(kind='mortality').values_list(
            'count_delta', 'reason', 'measured_weight_kg')), [(-25, 'oxygen', Decimal('3.100'))])
        self.post(reverse('farm:stock_cull', args=[self.t1.pk]),
                  {**base, 'token': str(uuid.uuid4()), 'count': '5', 'reason': 'deformed'})
        self.post(reverse('farm:stock_weighing', args=[self.t1.pk]),
                  {**base, 'token': str(uuid.uuid4()), 'sample_count': '20', 'sample_weight_kg': '3', 'avg_weight_g': ''})
        self.assertEqual(list(StockMovement.objects.order_by('id').values_list('kind', 'count_delta', 'avg_weight_g'))[2:],
                         [('cull', -5, None), ('weighing', 0, Decimal('150.0000'))])
        self.assertEqual(self.fish(self.t1), 1970)

    def test_the_servers_reason_is_shown_on_the_field(self):
        batch = self.stock(count=100)
        url = reverse('farm:stock_mortality', args=[self.t1.pk])
        data = {'token': str(uuid.uuid4()), 'batch': str(batch.pk), 'date': self.day(1).isoformat(), 'count': '150',
                'cause': 'unknown', 'notes': ''}
        response = self.post(url, data)
        self.assertEqual(response.status_code, 422)
        self.assertContains(response, f'Only 100 fish of {batch.code} are in T-01', status_code=422)
        response = self.post(url, {**data, 'count': '1', 'date': (self.today + timedelta(days=1)).isoformat()})
        self.assertEqual(response.context['form'].errors['date'], ['The date cannot be in the future.'])

    def test_a_unit_with_two_batches_asks_which(self):
        first = self.stock(days_ago=10)
        second = self.stock(days_ago=5)
        url = reverse('farm:stock_cull', args=[self.t1.pk])
        form = self.client.get(url).context['form']
        self.assertIsNone(form.only_batch)
        self.assertEqual([value for value, _label in form.fields['batch'].choices], ['', str(first.pk), str(second.pk)])
        response = self.post(url, {'token': str(uuid.uuid4()), 'batch': '', 'date': self.day(1).isoformat(),
                                   'count': '1', 'reason': 'sick', 'notes': ''})
        self.assertIn('batch', response.context['form'].errors)
        self.post(url, {'token': str(uuid.uuid4()), 'batch': str(second.pk), 'date': self.day(1).isoformat(),
                        'count': '1', 'reason': 'sick', 'notes': ''})
        self.assertEqual(StockMovement.objects.get(kind='cull').batch, second)

    def test_an_empty_unit_has_nothing_to_record(self):
        response = self.client.get(reverse('farm:stock_mortality', args=[self.t2.pk]))
        self.assertContains(response, 'No fish are in T-02.')
        self.assertNotIn('form', response.context)

    def test_void_through_its_dialog(self):
        batch = self.stock()
        died = self.mortality(batch, 7)
        url = f'{reverse("farm:stock_void", args=[died.pk])}?unit={self.t1.pk}'
        self.assertContains(self.client.get(url), 'Void the mortality of')
        self.assertEqual(self.post(url, {'reason': ''}).status_code, 422)
        response = self.post(url, {'reason': 'Wrong unit'})
        self.assertEqual(response['X-Modal-Redirect'], f'{reverse("farm:production_units")}?unit={self.t1.pk}')
        self.assertEqual(StockOperation.all_objects.get(pk=died.pk).void_reason, 'Wrong unit')
        self.assertEqual(self.client.get(url).status_code, 404)      # voided: no longer offered

    def test_every_dialog_opens_as_a_page_too(self):
        self.stock()
        for url in (reverse('farm:stock_input'), reverse('farm:stock_mortality', args=[self.t1.pk]),
                    reverse('farm:stock_cull', args=[self.t1.pk]), reverse('farm:stock_weighing', args=[self.t1.pk])):
            response = self.client.get(url)
            self.assertContains(response, 'id="rail"', msg_prefix=url)
            self.assertContains(response, 'aria-current="page"', msg_prefix=url)     # the menu marks Production units


class PermissionTests(StockTestCase):
    def as_role(self, *codenames):
        person = get_user_model().objects.create_user(f'p{len(codenames)}', f'p{len(codenames)}@example.com')
        person.groups.add(role(f'Role {len(codenames)}', *codenames))
        self.client.force_login(person)

    def test_read_record_and_void_are_separate(self):
        batch = self.stock()
        died = self.mortality(batch, 1)
        mortality = reverse('farm:stock_mortality', args=[self.t1.pk])
        void = reverse('farm:stock_void', args=[died.pk])
        self.as_role('view_stockoperation')
        page = self.client.get(reverse('farm:production_units'), {'unit': self.t1.pk})
        self.assertEqual(page.status_code, 200)
        for text in ('New batch', 'Record mortality', '>Void</a>'):
            self.assertNotContains(page, text)
        for url in (reverse('farm:stock_input'), mortality, void):
            self.assertEqual(self.client.post(url, {}).status_code, 403, url)
        self.as_role('view_stockoperation', 'add_stockoperation')
        page = self.client.get(reverse('farm:production_units'), {'unit': self.t1.pk})
        self.assertContains(page, 'Record mortality')
        self.assertNotContains(page, '>Void</a>')
        self.assertEqual(self.client.post(void, {'reason': 'x'}).status_code, 403)
        self.assertEqual(self.client.get(mortality).status_code, 200)
        self.assertFalse(StockOperation.all_objects.filter(is_deleted=True).exists())

    def test_no_read_no_page_and_no_menu_entry(self):
        self.as_role('view_tank')
        self.assertEqual(self.client.get(reverse('farm:production_units')).status_code, 403)
        self.assertNotContains(self.client.get(reverse('production_home')), reverse('farm:production_units'))

    def test_the_menu_and_the_role_matrix_place_it_under_operations(self):
        response = self.client.get(reverse('farm:production_units'))
        self.assertContains(response, '<p class="rail-section">Operations</p>', html=True)
        self.assertEqual(str(navigation.place('farm.view_stockoperation').path), 'Production · Operations')
        area = next(area for area in access.areas() if area.model == 'farm.StockOperation')
        self.assertEqual((str(area.label), area.actions), ('Production units', ('view', 'add', 'delete')))


class ActivityLogTests(StockTestCase):
    def test_each_operation_and_void_is_readable_in_the_log(self):
        batch = self.stock(days_ago=3)
        died = self.mortality(batch, 12, notes='Found at the outlet', measured_weight_kg=Decimal('1.5'))
        services.void(self.user, died, 'Same fish as yesterday')
        entries = list(AuditLog.objects.order_by('created_at'))
        self.assertEqual([(entry.action, entry.entity_type) for entry in entries], [
            ('create', 'batch'), ('create', 'stock operation'), ('update', 'unit'), ('create', 'stock operation'),
            ('void', 'stock operation')])
        stocked, recorded, voided = entries[1], entries[3], entries[4]
        self.assertEqual(stocked.entity_label, f'Stocking · T-01 · {batch.code} · {self.day(3).isoformat()}')
        self.assertEqual(stocked.changes['Stock lines'], [None, f'T-01 · {batch.code}: +2000 fish at 125 g'])
        self.assertEqual(recorded.changes, {
            'Operation': [None, message('Mortality')], 'Date': [None, self.day(1).isoformat()],
            'Notes': [None, 'Found at the outlet'],
            'Stock lines': [None, f'T-01 · {batch.code}: -12 fish, Disease, weighed 1.5 kg']})
        self.assertEqual(voided.changes, {'Reason for voiding': [None, 'Same fish as yesterday']})
        self.assertEqual(entries[0].changes['Species'], [None, 'Atlantic salmon (SAL)'])
        page = self.client.get(reverse('core:activity_log'), {'q': batch.code})
        self.assertContains(page, 'Voided')
        self.assertContains(page, 'Same fish as yesterday')
        Profile.objects.update_or_create(user=self.user, defaults={'language': 'tr'})
        self.assertContains(self.client.get(reverse('core:activity_log')), 'Ölüm')


class SiteHistoryTests(StockTestCase):
    """A unit's stock records belong to its site (OUR-06): the reports to the authorities are per locality."""

    def test_a_unit_with_stock_records_stays_on_its_site(self):
        batch = self.stock()
        services.record_transfer(self.user, source=self.t1, batch=batch, day=self.day(1), legs=[(self.t2, 2000)],
                                 reason='maintenance')
        unit = Tank.objects.get(pk=self.t1.pk)                    # empty now, with a history
        unit.production_department = self.sea
        with self.assertRaises(ValidationError) as caught:
            unit.full_clean()
        self.assertEqual(caught.exception.message_dict['production_department'],
                         ['It has stock records on its site: it can only move to a production department of the same '
                          'site.'])
        unit.production_department = ProductionDepartment.objects.create(site=self.bergen, name='Hall B', code='HB')
        unit.full_clean()                                         # another department of the same site is fine
        fresh = make_unit('T-09', self.hall)
        fresh.production_department = self.sea
        fresh.full_clean()                                        # a unit without records may move anywhere

    def test_a_department_whose_units_have_stock_records_stays_on_its_site(self):
        # Its move would take the units along: the same rule as a unit's own move.
        self.stock()
        self.hall.site = self.tromso
        with self.assertRaises(ValidationError) as caught:
            self.hall.full_clean()
        self.assertEqual(caught.exception.message_dict['site'],
                         ['Its units have stock records on their site: the department stays on it.'])
        empty = ProductionDepartment.objects.create(site=self.bergen, name='Hall B', code='HB')
        make_unit('T-09', empty)
        empty.site = self.tromso
        empty.full_clean()

    def test_a_site_with_stock_records_is_closed_not_deleted(self):
        from core.softdelete import plan_delete
        self.assertEqual(plan_delete(self.bergen).blockers, [])
        operation = services.record_input(self.user, species=self.salmon, input_stage='fry', origin='own_hatchery',
                                          day=self.day(3), lines=[(self.t1, 10, Decimal(5))])
        self.assertEqual(plan_delete(Site.objects.get(pk=self.bergen.pk)).blockers,
                         ['Its units have stock records: set its status to Closed instead.'])
        services.void(self.user, operation, 'Entered by mistake')    # a voided stocking is no record
        self.assertEqual(plan_delete(Site.objects.get(pk=self.bergen.pk)).blockers, [])


class ReadsOfAPeriodTests(StockTestCase):
    """The reads the regulatory reports stand on: the stock at the end of a past day and the lines of a period,
    both the fold's own figures (farm/stock/read.py)."""

    def setUp(self):
        super().setUp()
        self.batch = self.stock(count=2000, weight='125', days_ago=10)            # 250 kg in T-01
        self.mortality(self.batch, 100, days_ago=8, cause='disease')
        services.record_cull(self.user, unit=self.t1, batch=self.batch, day=self.day(7), count=50, reason='deformed')
        services.record_weighing(self.user, unit=self.t1, batch=self.batch, day=self.day(6), avg_weight_g=Decimal(200))
        self.moved = services.record_transfer(self.user, source=self.t1, batch=self.batch, day=self.day(4),
                                              legs=[(self.t2, 600)], reason='density')

    def test_stock_on_a_past_day_is_the_fold_cut_at_that_day(self):
        self.assertEqual(read.stock_on([self.t1, self.t2], self.day(11)), {})
        on = read.stock_on([self.t1, self.t2], self.day(9))
        self.assertEqual((list(on), on[self.t1.pk].count, on[self.t1.pk].biomass_kg), ([self.t1.pk], 2000, 250))
        on = read.stock_on([self.t1, self.t2], self.day(7))      # 100 died, 50 culled, at 125 g
        self.assertEqual((on[self.t1.pk].count, on[self.t1.pk].biomass_kg, on[self.t1.pk].deaths,
                          on[self.t1.pk].culls), (1850, Decimal('231.25'), 100, 50))
        on = read.stock_on([self.t1, self.t2], self.day(4))      # weighed at 200 g, then 600 moved
        self.assertEqual([(on[unit.pk].count, on[unit.pk].biomass_kg, on[unit.pk].batches)
                          for unit in (self.t1, self.t2)], [(1250, 250, [self.batch]), (600, 120, [self.batch])])
        # Today's stock is the same fold, cut at today: stock_of and stock_on agree.
        now, today = read.stock_of([self.t1, self.t2]), read.stock_on([self.t1, self.t2], self.today)
        self.assertEqual({key: (value.count, value.grams) for key, value in now.items()},
                         {key: (value.count, value.grams) for key, value in today.items()})

    def test_a_unit_emptied_before_the_day_is_left_out_and_a_void_changes_the_past(self):
        back = services.record_transfer(self.user, source=self.t2, batch=self.batch, day=self.day(2),
                                        legs=[(self.t1, 600)], reason='density')
        self.assertEqual(set(read.stock_on([self.t1, self.t2], self.day(2))), {self.t1.pk})
        services.void(self.user, back, 'Entered by mistake')
        self.assertEqual(read.stock_on([self.t1, self.t2], self.day(2))[self.t2.pk].count, 600)

    def test_the_lines_of_a_period_with_their_reasons_grams_and_the_other_end(self):
        lines = read.movements([self.t1], self.day(8), self.day(4))
        self.assertEqual([(line.kind, line.count, line.reason, line.kilos, line.date) for line in lines], [
            ('mortality', -100, 'disease', Decimal('12.5'), self.day(8)),
            ('cull', -50, 'deformed', Decimal('6.25'), self.day(7)),
            ('weighing', 0, '', None, self.day(6)),
            ('transfer_out', -600, 'density', Decimal(120), self.day(4)),
        ])
        self.assertEqual(lines[-1].other_unit_id, self.t2.pk)
        arrived = read.movements([self.t2], self.day(10), self.today)
        self.assertEqual([(line.kind, line.count, line.kilos, line.other_unit_id) for line in arrived],
                         [('transfer_in', 600, Decimal(120), self.t1.pk)])
        # Outside the period, nothing; a void takes its lines out.
        self.assertEqual(read.movements([self.t1], self.day(3), self.today), [])
        services.void(self.user, self.moved, 'Entered by mistake')
        self.assertEqual(read.movements([self.t2], self.day(10), self.today), [])

    def test_a_weighed_mortality_reports_its_weighed_kilos(self):
        self.mortality(self.batch, 10, days_ago=1, measured_weight_kg=Decimal('2.5'))
        line, = read.movements([self.t1], self.day(1), self.day(1))
        self.assertEqual((line.kilos, line.grams), (Decimal('2.5'), Decimal(2000)))


class DatabaseViewerTests(TestCase):
    def test_the_stock_tables_are_shown_with_their_descriptions_and_checks(self):
        tables = {table.name: table for _, tables in database.sections() for table in tables}
        self.assertEqual(tables['batches'].description, 'A group of fish that came in together: its identity and '
                                                        'origin, no counts.')
        self.assertTrue(tables['stock_operations'].description.startswith('One thing a person did to the stock'))
        self.assertTrue(tables['stock_movements'].description.startswith('A line of the stock ledger'))
        names = {constraint.name for constraint in tables['stock_movements'].structure().constraints}
        self.assertTrue({'chk_stock_movements_sign', 'chk_stock_movements_sample', 'chk_stock_movements_reason',
                         'uq_stock_movements_line'} <= names | {index.name for index in
                                                                tables['stock_movements'].structure().indexes})

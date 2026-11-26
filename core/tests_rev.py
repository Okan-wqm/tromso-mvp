"""The revision table `core_rev` (core.rev): a counter per (scope, key) that the database moves whenever a tracked row
changes, so a stored figure can prove it is still valid. Each tracked table's triggers note the changed keys while
the transaction runs and apply them at commit, sorted, once per key (two writers in opposite order never deadlock);
raw SQL, bulk inserts, soft deletes, date edits and a TRUNCATE are all seen, because no Python code bumps anything.

A TestCase never commits, so its deferred triggers are fired with `rev.settle()` (which leaves them deferred again, so
the writes between two settles count as one transaction); the concurrency, commit and rollback tests use their own
connections or real transactions and commit."""
import threading
from datetime import date, timedelta
from decimal import Decimal as D
from io import StringIO

import psycopg
from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from core.checks import revision_triggers
from core.models import PlatformSettings
from farm import withdrawal_gate
from farm.handling import check
from farm.models import (Equipment, EquipmentSystem, EquipmentType, ProductionDepartment, SamplingPoint, Site, Species,
                         StockMovement, StockOperation, System, Tank, WaterFreshness, WaterLimit, WaterMeasurement)
from farm.models.stock import TransferReason
from farm.stock import services
from farm.tests.helpers import make_species, may_record, point_of, stock_fish
from farm.tests.test_stock import make_unit
from farm.water import services as water
from sensors import quantities
from sensors.models import Binding, Channel
from sensors.tests import make_channel, make_connection, make_device, make_format

from . import rev
from .operations import TrackRev


def row(scope, key='0'):
    """(rev, dirty_epoch, dirty_from) of a key, or None."""
    with connection.cursor() as cursor:
        cursor.execute('SELECT rev, dirty_epoch, dirty_from FROM core_rev WHERE scope = %s AND key = %s', [scope, str(key)])
        return cursor.fetchone()


def sql(statement, params=()):
    with connection.cursor() as cursor:
        cursor.execute(statement, params)


# These tests write the stock ledger, the samples and the points straight through the ORM, as a hand edit or a restore
# would (the withdrawal gate refuses that outside its guard, farm/withdrawal_gate.py): the triggers must see it all.
GATE_REASON = 'core_rev tests: every way a tracked row can be written'


class Gate:
    def setUp(self):
        self.enterContext(withdrawal_gate.opened(GATE_REASON))
        super().setUp()


class Farm:
    def make_farm(self):
        self.user = may_record(get_user_model().objects.create_user('rev', 'rev@example.com', 'x'))
        site = Site.objects.create(name='Bergen', code='BG')
        hall = ProductionDepartment.objects.create(site=site, name='Hall A', code='HA')
        self.t1, self.t2 = make_unit('T-01', hall), make_unit('T-02', hall)
        self.salmon = make_species()
        self.today = services.local_today(self.t1)

    def operation(self, days_ago, kind='weighing'):
        return StockOperation.objects.create(kind=kind, date=self.today - timedelta(days=days_ago), created_by=self.user,
                                             updated_by=self.user)

    def weighing_sql(self, operation, batch, unit):
        return ("INSERT INTO stock_movements (operation_id, batch_id, unit_id, kind, count_delta, avg_weight_g, reason, "
                "size_class) VALUES (%s, %s, %s, 'weighing', 0, 60, '', '')", [operation.pk, batch.pk, unit.pk])


class BumpTests(TestCase):
    def note(self, scope, key, day=None):
        sql('SELECT core_rev_note(%s, %s, %s)', [scope, str(key), day])

    def test_noted_keys_are_applied_once_with_the_earliest_day(self):
        self.note('t', 1, date(2026, 3, 5))
        self.note('t', 1, date(2026, 3, 1))
        self.note('t', 1, date(2026, 3, 9))
        self.note('t', 2)
        self.assertIsNone(row('t', 1))                       # nothing is written before the apply
        rev.settle()
        self.assertEqual(row('t', 1), (1, 0, date(2026, 3, 1)))
        self.assertEqual(row('t', 2), (1, 0, rev.EVERYTHING))   # a change without a day: the whole history

    def test_a_change_without_a_day_after_a_dated_one_still_marks_the_whole_history(self):
        self.note('t', 1, date(2026, 3, 5))
        self.note('t', 1)
        rev.settle()
        self.assertEqual(row('t', 1), (1, 0, rev.EVERYTHING))

    def test_a_key_changed_again_after_an_apply_moves_again(self):
        self.note('t', 1, date(2026, 3, 5))
        rev.settle()
        self.note('t', 1, date(2026, 3, 7))
        rev.settle()
        self.assertEqual(row('t', 1), (2, 0, date(2026, 3, 5)))

    def test_a_bad_scope_or_key_is_refused(self):
        for scope, key in (('T', '1'), ('t1', '1'), ('t', 'a|b'), ('t', 'a;b')):
            with self.subTest(scope=scope, key=key), self.assertRaises(Exception), transaction.atomic():
                self.note(scope, key)

    def test_a_revision_is_never_negative_and_a_key_is_unique(self):
        self.note('t', 1)
        rev.settle()
        with self.assertRaises(IntegrityError), transaction.atomic():
            sql("UPDATE core_rev SET rev = -1 WHERE scope = 't'")
        with self.assertRaises(IntegrityError), transaction.atomic():
            sql("INSERT INTO core_rev (scope, key, rev, dirty_epoch) VALUES ('t', '1', 5, 0)")

    def test_rev_reads_a_missing_key_as_none_and_stamp_reads_many_in_one_query(self):
        self.note('t', 1)
        self.note('u', 0)
        rev.settle()
        self.assertIsNone(rev.rev('t', 9))
        self.assertEqual(rev.rev('t', 1), 1)
        with self.assertNumQueries(1):
            stamp = rev.stamp([('u', 0), ('t', 1), ('t', 9)])
        self.assertEqual(stamp, 't:1:1 t:9:- u:0:1')        # sorted; a missing key says so
        self.assertEqual(rev.stamp([]), '')

    def test_mark_built_sets_the_epoch_only_when_the_revision_has_not_moved(self):
        self.note('t', 1, date(2026, 3, 5))
        rev.settle()
        self.assertTrue(rev.mark_built('t', 1, 1))
        self.assertEqual(row('t', 1), (1, 1, None))
        self.assertFalse(rev.mark_built('t', 1, 0))          # built from an older revision: refused
        self.assertEqual(row('t', 1), (1, 1, None))

    def test_a_write_after_mark_built_in_the_same_transaction_moves_the_revision(self):
        # mark_built forgets the transaction's notes of that key, so a later change in the same transaction counts.
        self.note('t', 1, date(2026, 3, 5))
        rev.settle()
        rev.mark_built('t', 1, 1)
        self.note('t', 1, date(2026, 3, 9))
        rev.settle()
        self.assertEqual(row('t', 1), (2, 1, date(2026, 3, 9)))

    def test_rebuild_moves_every_revision_past_every_stamp_and_clears_the_days(self):
        self.note('t', 1, date(2026, 3, 5))
        self.note('t', 2)
        rev.settle()
        sql("UPDATE core_rev SET rev = 7 WHERE key = '2'")
        rev.rebuild(stamped=[8])                              # a stored figure stamped 8 (a restore can go back)
        self.assertEqual(row('t', 1), (9, 9, None))
        self.assertEqual(row('t', 2), (9, 9, None))
        # A key seen for the first time after the rebuild starts above the floor: a figure stamped before the restore
        # can never meet its revision again.
        self.note('t', 3)
        rev.settle()
        self.assertEqual(row('t', 3), (10, 0, rev.EVERYTHING))


class StockTrackingTests(Gate, Farm, TestCase):
    """Every way the stock ledger changes moves the revision of the batches it touches and of the units they are in,
    with the earliest day changed."""

    def setUp(self):
        super().setUp()
        self.make_farm()
        self.batch = stock_fish(self.user, self.t1, 1000, '50', 20, species=self.salmon)
        rev.settle()
        rev.mark_built('batch', self.batch.pk, rev.rev('batch', self.batch.pk))
        rev.mark_built('unit_stock', self.t1.pk, rev.rev('unit_stock', self.t1.pk))

    def day(self, days_ago):
        return self.today - timedelta(days=days_ago)

    def transfer(self, days_ago, count=100):
        day = self.day(days_ago)
        seen = check.assess('transport', self.t1, day, self.batch).fingerprint
        return services.record_transfer(self.user, source=self.t1, batch=self.batch, day=day, legs=[(self.t2, count)],
                                        reason='density', handling_ack=seen)

    def test_the_services_write_moves_the_batch_and_the_unit(self):
        fresh = stock_fish(self.user, self.t2, 500, '40', 5, species=self.salmon)
        services.record_mortality(self.user, unit=self.t1, batch=self.batch, day=self.day(3), count=10, cause='disease')
        rev.settle()
        self.assertEqual(row('batch', fresh.pk), (1, 0, self.day(5)))
        self.assertEqual(row('batch', self.batch.pk), (2, 1, self.day(3)))
        self.assertEqual(row('unit_stock', self.t2.pk), (1, 0, self.day(5)))
        self.assertEqual(row('unit_stock', self.t1.pk), (2, 1, self.day(3)))

    def test_a_transfer_moves_both_units_once(self):
        self.transfer(2)
        rev.settle()
        self.assertEqual(row('unit_stock', self.t1.pk), (2, 1, self.day(2)))
        self.assertEqual(row('unit_stock', self.t2.pk), (1, 0, self.day(2)))
        self.assertEqual(row('batch', self.batch.pk), (2, 1, self.day(2)))

    def test_bulk_create_and_raw_sql_move_the_batch_and_the_unit(self):
        StockMovement.objects.bulk_create([StockMovement(
            operation=self.operation(4), batch=self.batch, unit=self.t1, kind='weighing', count_delta=0,
            avg_weight_g=55)])
        rev.settle()
        self.assertEqual(row('batch', self.batch.pk)[2], self.day(4))
        self.assertEqual(row('unit_stock', self.t1.pk)[2], self.day(4))
        rev.mark_built('batch', self.batch.pk, rev.rev('batch', self.batch.pk))
        sql(*self.weighing_sql(self.operation(2), self.batch, self.t1))
        rev.settle()
        self.assertEqual(row('batch', self.batch.pk), (3, 2, self.day(2)))
        self.assertEqual(row('unit_stock', self.t1.pk), (3, 1, self.day(4)))

    def test_a_5000_line_operation_moves_each_key_once(self):
        # a split of 2,500 pairs of lines (one fish each out of T-01, into T-02), one bulk insert
        big = stock_fish(self.user, self.t1, 5000, '50', 20, species=self.salmon)
        rev.settle()
        keys = (('batch', big.pk), ('unit_stock', self.t1.pk), ('unit_stock', self.t2.pk))
        before = [rev.rev(*key) or 0 for key in keys]
        for (scope, key), start in zip(keys, before):
            rev.mark_built(scope, key, start)
        operation = self.operation(1, kind='transfer')
        StockMovement.objects.bulk_create(transfer_lines(operation, big, self.t1, self.t2, 2500))
        rev.settle()
        self.assertEqual([rev.rev(*key) - start for key, start in zip(keys, before)], [1, 1, 1])
        self.assertEqual([row(*key)[2] for key in keys], [self.day(1)] * 3)

    def test_a_void_and_a_restore_move_the_batch_and_the_unit_of_every_line(self):
        operation = services.record_mortality(self.user, unit=self.t1, batch=self.batch, day=self.day(6), count=5,
                                              cause='disease')
        rev.settle()
        rev.mark_built('batch', self.batch.pk, rev.rev('batch', self.batch.pk))
        rev.mark_built('unit_stock', self.t1.pk, rev.rev('unit_stock', self.t1.pk))
        services.void(self.user, operation, 'Entered twice')
        rev.settle()
        self.assertEqual(row('batch', self.batch.pk), (3, 2, self.day(6)))
        self.assertEqual(row('unit_stock', self.t1.pk), (3, 2, self.day(6)))
        rev.mark_built('batch', self.batch.pk, 3)
        StockOperation.all_objects.filter(pk=operation.pk).update(is_deleted=False, void_reason='')
        rev.settle()
        self.assertEqual(row('batch', self.batch.pk), (4, 3, self.day(6)))
        self.assertEqual(row('unit_stock', self.t1.pk), (4, 2, self.day(6)))

    def test_a_date_edit_marks_the_earlier_of_the_two_days(self):
        operation = services.record_mortality(self.user, unit=self.t1, batch=self.batch, day=self.day(6), count=5,
                                              cause='disease')
        rev.settle()
        rev.mark_built('batch', self.batch.pk, 2)
        rev.mark_built('unit_stock', self.t1.pk, 2)
        StockOperation.all_objects.filter(pk=operation.pk).update(date=self.day(12))
        rev.settle()
        self.assertEqual(row('batch', self.batch.pk), (3, 2, self.day(12)))
        self.assertEqual(row('unit_stock', self.t1.pk), (3, 2, self.day(12)))
        rev.mark_built('batch', self.batch.pk, 3)
        StockOperation.all_objects.filter(pk=operation.pk).update(date=self.day(1))
        rev.settle()
        self.assertEqual(row('batch', self.batch.pk), (4, 3, self.day(12)))

    def test_an_edit_of_a_column_the_ledger_does_not_read_moves_nothing(self):
        operation = StockOperation.objects.get(movements__batch=self.batch)
        StockOperation.all_objects.filter(pk=operation.pk).update(notes='checked')
        type(self.batch).all_objects.filter(pk=self.batch.pk).update(notes='checked')
        rev.settle()
        self.assertEqual(row('batch', self.batch.pk), (1, 1, None))
        self.assertEqual(row('unit_stock', self.t1.pk), (1, 1, None))

    def test_a_species_change_marks_the_whole_history_of_the_batch_and_of_every_unit_it_was_in(self):
        self.transfer(2)
        rev.settle()
        rev.mark_built('unit_stock', self.t2.pk, 1)
        trout = make_species('RBT', 'Rainbow trout', 'Oncorhynchus mykiss', local_name='', saltwater=False)
        type(self.batch).all_objects.filter(pk=self.batch.pk).update(species=trout)
        rev.settle()
        self.assertEqual(row('batch', self.batch.pk)[2], rev.EVERYTHING)
        self.assertEqual(row('unit_stock', self.t1.pk)[2], rev.EVERYTHING)
        self.assertEqual(row('unit_stock', self.t2.pk), (2, 1, rev.EVERYTHING))

    def test_a_deleted_line_and_a_line_moved_to_another_batch_and_unit_move_both(self):
        other = stock_fish(self.user, self.t2, 300, '40', 30, species=self.salmon)
        rev.settle()
        rev.mark_built('batch', other.pk, 1)
        rev.mark_built('unit_stock', self.t2.pk, 1)
        line = StockMovement.objects.create(operation=self.operation(8), batch=self.batch, unit=self.t1,
                                            kind='weighing', count_delta=0, avg_weight_g=52)
        rev.settle()
        rev.mark_built('batch', self.batch.pk, 2)
        sql('UPDATE stock_movements SET batch_id = %s, unit_id = %s WHERE id = %s', [other.pk, self.t2.pk, line.pk])
        rev.settle()
        self.assertEqual(row('batch', self.batch.pk), (3, 2, self.day(8)))
        self.assertEqual(row('batch', other.pk), (2, 1, self.day(8)))
        self.assertEqual(row('unit_stock', self.t1.pk)[0], 3)
        self.assertEqual(row('unit_stock', self.t2.pk), (2, 1, self.day(8)))
        rev.mark_built('batch', other.pk, 2)
        StockMovement.objects.filter(pk=line.pk).delete()
        rev.settle()
        self.assertEqual(row('batch', other.pk), (3, 2, self.day(8)))
        self.assertEqual(row('unit_stock', self.t2.pk)[0], 3)


def transfer_lines(operation, batch, source, target, pairs):
    """`pairs` transfer pairs of one fish each (2 x pairs lines) of one operation: out of `source`, into `target`."""
    reason = TransferReason.values[0]
    lines = []
    for pair in range(1, pairs + 1):
        lines.append(StockMovement(operation=operation, batch=batch, unit=source, kind='transfer_out', count_delta=-1,
                                   pair=pair, reason=reason))
        lines.append(StockMovement(operation=operation, batch=batch, unit=target, kind='transfer_in', count_delta=1,
                                   pair=pair))
    return lines


def window(number):
    """A binding period of its own (one hour, `number` days back): one primary channel of a quantity per target at a
    time."""
    start = timezone.now().replace(microsecond=0) - timedelta(days=number)
    return {'valid_from': start, 'valid_to': start + timedelta(hours=1)}


def latin(number):
    """A scientific name's species word for a number (letters only, as the species check wants)."""
    return 'pisc' + chr(97 + number // 26 % 26) + chr(97 + number % 26)


# Parameters a new limit may be set for besides the fixture's (one live row per species, parameter and water type).
PARAMETERS = ('ph', 'oxygen_mg_l', 'tan_mg_l', 'co2_mg_l', 'nitrite_n_mg_l', 'nitrate_n_mg_l', 'salinity_ppt')


def unit_fields(code, department):
    return {'name': f'Unit {code}', 'code': code, 'kind': 'tank', 'production_department': department,
            'water_type': 'freshwater', 'status': 'preparing', 'shape': 'rectangular', 'material': 'fiberglass',
            'length': 10, 'width': 5, 'depth': 2, 'max_density_kg_m3': 50}


def channel_fields(device, number):
    return {**quantities.defaults('temperature_c'), 'device': device, 'quantity': 'temperature_c',
            'code': f'TEMP-{number}', 'name': f'temperature {number}', 'value_path': f'/t{number}'}


class WaterInputTests(Gate, TestCase):
    """Every input of the water's judgement moves its key, once per transaction, whichever way it is written: the ORM's
    insert, save and soft delete, `bulk_create`, and raw SQL. A table that is one key moves ('<table>', '0'); a sample
    moves its sampling point ('water_point', <point id>)."""

    @classmethod
    def setUpTestData(cls):
        with withdrawal_gate.opened(GATE_REASON):
            cls.make_fixture()

    @classmethod
    def make_fixture(cls):
        cls.user = may_record(get_user_model().objects.create_user('rev', 'rev@example.com', 'x'))
        cls.site = Site.objects.create(name='Bergen', code='BG', timezone='UTC')
        cls.hall = ProductionDepartment.objects.create(site=cls.site, name='Hall A', code='HA')
        cls.ras = System.objects.create(name='RAS 1', code='R1', site=cls.site, production_department=cls.hall)
        cls.t1 = make_unit('T-01', cls.hall, system=cls.ras)
        cls.mid1, cls.loop = point_of(cls.t1), point_of(cls.ras)
        cls.salmon = make_species()
        cls.pump_type = EquipmentType.objects.get(code='pump-centrifugal')
        cls.pump = cls.equipment('P1')
        cls.link = EquipmentSystem.objects.create(equipment=cls.pump, system=cls.ras, is_primary=True)
        cls.limit = WaterLimit.objects.create(species=cls.salmon, parameter='temperature_c', water_type='any',
                                              warning_high=D('18'))
        cls.device = make_device(make_connection(), make_format(), cls.site)
        cls.ph = make_channel(cls.device, 'ph')
        cls.binding = Binding.objects.create(channel=cls.ph, role='primary', point=cls.mid1,
                                             valid_from=timezone.now() - timedelta(days=3))

    @classmethod
    def equipment(cls, code):
        return Equipment.objects.create(name=f'Pump {code}', code=code, equipment_type=cls.pump_type,
                                        production_department=cls.hall, specifications={'flowRate': 100})

    def changes(self, scope, key='0', by=1):
        """A block after which the key has moved `by` (settled before and after: the block is one transaction)."""
        test = self

        class Changes:
            def __enter__(self):
                rev.settle()
                self.before = rev.rev(scope, key) or 0

            def __exit__(self, kind, *rest):
                if kind is None:
                    rev.settle()
                    test.assertEqual((rev.rev(scope, key) or 0) - self.before, by, f'{scope}:{key}')
        return Changes()

    def specs(self):
        """Per table scope: the model, a new row's fields, the row to edit and the edit."""
        numbers = iter(range(10, 99))
        limited = iter(PARAMETERS)

        def number():
            return next(numbers)

        def named(prefix, code_prefix, **fields):
            n = number()
            return {'name': f'{prefix} {n}', 'code': f'{code_prefix}{n}', **fields}
        return {
            'sites': (Site, lambda: named('Site', 'S', timezone='UTC'), self.site, {'name': 'Bergen hall'}),
            'production_departments': (ProductionDepartment, lambda: named('Hall', 'H', site=self.site), self.hall,
                                       {'name': 'Hall'}),
            'systems': (System, lambda: named('RAS', 'R', site=self.site, production_department=self.hall), self.ras,
                        {'name': 'RAS one'}),
            'tanks': (Tank, lambda: unit_fields(f'T-{number()}', self.hall), self.t1, {'name': 'Unit one'}),
            'equipment': (Equipment, lambda: named('Pump', 'P', equipment_type=self.pump_type,
                                                   production_department=self.hall, specifications={'flowRate': 100}),
                          self.pump, {'name': 'Main pump'}),
            'equipment_systems': (EquipmentSystem, lambda: {'equipment': self.equipment(f'Q{number()}'),
                                                            'system': self.ras}, self.link, {'criticality': 4}),
            'water_sampling_points': (SamplingPoint, lambda: {'unit': self.t1, 'kind': 'outlet',
                                                              'name': f'Outlet {number()}'},
                                      self.mid1, {'description': 'by the wall'}),
            'water_limits': (WaterLimit, lambda: {'species': self.salmon, 'parameter': next(limited),
                                                  'water_type': 'freshwater', 'warning_high': D('5')},
                             self.limit, {'warning_high': D('17')}),
            'species': (Species, lambda: {'code': f'SP{(n := number())}', 'common_name': f'Fish {n}',
                                          'scientific_name': f'Piscis {latin(n)}', 'local_name': '', 'freshwater': True},
                        self.salmon, {'local_name': 'Atlantisk laks'}),
            'sensors_channel': (Channel, lambda: channel_fields(self.device, number()), self.ph, {'name': 'pH probe'}),
            'sensors_binding': (Binding, lambda: {
                'channel': Channel.objects.create(**channel_fields(self.device, number())), 'role': 'primary',
                'system': self.ras, **window(number())}, self.binding, {'note': 'checked'}),
        }

    def test_every_table_scope_moves_once_per_transaction_on_insert_bulk_create_save_delete_and_raw_sql(self):
        specs = self.specs()
        self.assertEqual(set(specs) | {'water_freshness', 'platform_settings'}, set(rev.WATER_TABLES))
        for scope, (model, fields, existing, change) in specs.items():
            table = model._meta.db_table
            self.assertEqual(table, scope)
            with self.subTest(scope=scope, way='two inserts'), self.changes(scope):
                first = model.objects.create(**fields())
                model.objects.create(**fields())
            with self.subTest(scope=scope, way='bulk_create'), self.changes(scope):
                model.objects.bulk_create([model(**fields()), model(**fields())])
            with self.subTest(scope=scope, way='save'), self.changes(scope):
                for name, value in change.items():
                    setattr(existing, name, value)
                existing.save()
                existing.save()
            if hasattr(first, 'soft_delete'):
                with self.subTest(scope=scope, way='soft delete'), self.changes(scope):
                    first.soft_delete(self.user)
            else:
                with self.subTest(scope=scope, way='delete'), self.changes(scope):
                    first.delete()
            with self.subTest(scope=scope, way='raw SQL'), self.changes(scope):
                column = model._meta.pk.column
                sql(f'UPDATE {table} SET {column} = {column} WHERE {column} = %s', [existing.pk])
                sql(f'UPDATE {table} SET {column} = {column} WHERE {column} = %s', [existing.pk])
            with self.subTest(scope=scope, way='rolled back'), self.changes(scope, by=0):
                with self.assertRaises(RuntimeError), transaction.atomic():
                    model.objects.create(**fields())
                    raise RuntimeError('rolled back')

    def test_the_freshness_rules_move_when_changed(self):
        # Never lost nor made again: the database refuses a DELETE (farm 0051), core/tests_kept_rows.py.
        found = WaterFreshness.objects.get(parameter='ph')
        with self.changes('water_freshness'):
            found.fresh_hours = 48
            found.save()
        with self.changes('water_freshness'):
            sql("UPDATE water_freshness SET fresh_hours = 24 WHERE parameter = 'ph'")

    def test_the_platform_settings_move_when_saved_or_written_by_raw_sql(self):
        settings = PlatformSettings.get()
        with self.changes('platform_settings'):
            settings.clock_tolerance_seconds += 1
            settings.save()
        with self.changes('platform_settings'):
            sql('UPDATE platform_settings SET clock_tolerance_seconds = clock_tolerance_seconds + 1')

    def test_a_sample_moves_its_point_and_nothing_else(self):
        moment = timezone.now() - timedelta(hours=1)
        with self.changes('water_point', self.mid1.pk), self.changes('water_point', self.loop.pk, by=0):
            sample = water.record(self.user, point=self.mid1, measured_at=moment, source='manual',
                                  values={'temperature_c': D('12.0')})
            WaterMeasurement.objects.bulk_create([WaterMeasurement(
                point=self.mid1, measured_at=moment - timedelta(hours=1), source='manual', temperature_c=D('11.0'))])
        with self.changes('water_point', self.mid1.pk):
            sample.notes = 'checked'
            sample.save()
        with self.changes('water_point', self.mid1.pk):
            water.void(self.user, sample, 'Entered twice')
        with self.changes('water_point', self.mid1.pk):
            WaterMeasurement.all_objects.filter(pk=sample.pk).update(is_deleted=False, void_reason='')
        with self.changes('water_point', self.mid1.pk), self.changes('water_point', self.loop.pk):
            sql('UPDATE water_measurements SET point_id = %s WHERE id = %s', [self.loop.pk, sample.pk])
        with self.changes('water_point', self.loop.pk), self.changes('water_point', self.mid1.pk, by=0):
            sql('DELETE FROM water_measurements WHERE id = %s', [sample.pk])
        with self.changes('water_point', self.mid1.pk, by=0), self.assertRaises(RuntimeError), transaction.atomic():
            water.record(self.user, point=self.mid1, measured_at=moment, source='manual',
                         values={'temperature_c': D('13.0')})
            raise RuntimeError('rolled back')

    def test_the_tables_the_ingest_may_write_are_never_tracked_and_have_no_revision_trigger(self):
        # Held by the ingest's database role itself, not by a list: whatever table it is granted a write on is in
        # NEVER_TRACKED, has no revision trigger and is none of TRACKED's.
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = current_schema() AND c.relkind IN ('r', 'p') AND ("
                "has_table_privilege('sensors_ingest', c.oid, 'INSERT') OR has_table_privilege('sensors_ingest', c.oid, "
                "'UPDATE') OR has_table_privilege('sensors_ingest', c.oid, 'DELETE') OR "
                "has_table_privilege('sensors_ingest', c.oid, 'TRUNCATE'))")
            writes = {name for (name,) in cursor.fetchall()}
            cursor.execute("SELECT c.relname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
                           "WHERE c.relname = ANY(%s) AND t.tgname LIKE 'core\\_rev\\_%%'", [sorted(writes)])
            triggered = cursor.fetchall()
        self.assertEqual(writes, set(rev.NEVER_TRACKED))
        self.assertEqual(triggered, [])
        self.assertFalse(writes & {table for table, _scope in rev.TRACKED})


class PresenceTests(TestCase):
    def test_every_declared_trigger_is_there_and_enabled(self):
        self.assertEqual(rev.missing(), [])
        self.assertEqual(revision_triggers(None), [])
        tables = {model._meta.db_table for model in apps.get_models()}
        self.assertTrue({table for table, _scope in rev.TRACKED} <= tables)

    def test_a_disabled_dropped_or_replica_only_trigger_is_reported_and_check_warns(self):
        sql('SET CONSTRAINTS ALL IMMEDIATE')                     # a table with pending deferred events cannot be altered
        sql('ALTER TABLE water_limits DISABLE TRIGGER core_rev_water_limits_water_limits_note')
        sql('DROP TRIGGER core_rev_sensors_binding_sensors_binding_apply ON sensors_binding')
        sql('ALTER TABLE tanks ENABLE REPLICA TRIGGER core_rev_tanks_tanks_trunc')   # fires in replica sessions only
        self.assertEqual(rev.missing(), ['core_rev_water_limits_water_limits_note', 'core_rev_tanks_tanks_trunc',
                                         'core_rev_sensors_binding_sensors_binding_apply'])
        [warning] = revision_triggers(None)
        self.assertEqual(warning.id, 'core.W005')
        self.assertIn('3 revision trigger(s) are missing or disabled: core_rev_water_limits_water_limits_note, '
                      'core_rev_tanks_tanks_trunc, core_rev_sensors_binding_sensors_binding_apply', warning.msg)
        sql('ALTER TABLE tanks ENABLE ALWAYS TRIGGER core_rev_tanks_tanks_trunc')    # always fires: counts as there
        self.assertNotIn('core_rev_tanks_tanks_trunc', rev.missing())

    def test_the_check_is_quiet_before_the_revision_table_exists(self):
        sql("DELETE FROM django_migrations WHERE app = 'core' AND name = '0014_rev'")
        sql('SET CONSTRAINTS ALL IMMEDIATE')
        sql('ALTER TABLE water_limits DISABLE TRIGGER core_rev_water_limits_water_limits_note')
        self.assertEqual(revision_triggers(None), [])

    def test_the_declared_set_is_what_the_migrations_made(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT tgname FROM pg_trigger WHERE tgname LIKE 'core\\_rev\\_%%' AND NOT tgisinternal")
            made = {name for (name,) in cursor.fetchall()}
        self.assertEqual(made, {name for track in rev.TRACKED for name in rev.trigger_names(*track)})

    def test_the_declared_set_is_the_migrations_operations(self):
        self.assertEqual(sorted((operation.table, operation.scope) for operation in rev.operations()),
                         sorted(rev.TRACKED))


class EnsureTests(Gate, Farm, TestCase):
    """A key with no row is never valid: ensure() gives keys a row, and the migrations gave one to every key there was."""

    def test_ensure_gives_a_missing_key_a_row_above_the_floor_and_leaves_one_that_has_it(self):
        sql("SELECT core_rev_note('t', '1', '2026-03-05')")
        rev.settle()
        self.assertEqual(rev.ensure([('t', 1), ('t', 2), ('u', 'x'), ('t', 2)]), 2)
        self.assertEqual((row('t', 1), row('t', 2), row('u', 'x')),
                         ((1, 0, date(2026, 3, 5)), (1, 0, rev.EVERYTHING), (1, 0, rev.EVERYTHING)))
        self.assertEqual(rev.ensure([]), 0)
        target = rev.rebuild()
        rev.ensure([('t', 3)])
        self.assertEqual(row('t', 3), (target + 1, 0, rev.EVERYTHING))    # above the floor: never an old stamp
        sql("SELECT core_rev_note('t', '3', NULL)")
        rev.settle()
        self.assertEqual(row('t', 3)[0], target + 2)                         # a change moves an ensured key

    def test_the_migrations_backfill_gives_every_point_unit_batch_and_table_a_row(self):
        import importlib
        self.make_farm()
        batch = stock_fish(self.user, self.t1, 100, '50', 5, species=self.salmon)
        point = point_of(self.t1)
        rev.settle()
        sql('DELETE FROM core_rev')                     # as on a database the triggers have just been added to
        for module in rev.MIGRATIONS:
            for operation in importlib.import_module(module).Migration.operations:
                if str(getattr(operation, 'sql', '')).startswith('SELECT core_rev_ensure('):
                    with connection.cursor() as cursor:
                        cursor.execute(operation.sql)
        keys = set(rev_keys())
        wanted = {('water_point', str(point.pk)), ('unit_stock', str(self.t1.pk)), ('unit_stock', str(self.t2.pk)),
                  ('batch', str(batch.pk)), *((table, '0') for table in rev.WATER_TABLES)}
        self.assertEqual(wanted - keys, set())


class RepairTests(Gate, TestCase):
    """manage.py core_rev_repair makes a dropped, disabled or replica-only trigger again, on a table or a chunk, as its
    migration made it, and rebuilds every revision."""

    def test_the_command_makes_missing_triggers_again_and_rebuilds(self):
        user = get_user_model().objects.create_user('rev', 'rev@example.com', 'x')
        site = Site.objects.create(name='Bergen', code='BG')
        hall = ProductionDepartment.objects.create(site=site, name='Hall A', code='HA')
        unit = make_unit('T-01', hall)
        point = point_of(unit)
        may_record(user, 'add_watermeasurement')  # the water service asks (L-6)
        water.record(user, point=point, measured_at=timezone.now() - timedelta(hours=1), source='manual',
                     values={'temperature_c': D('12.0')})
        rev.settle()
        with connection.cursor() as cursor:
            cursor.execute("SELECT i.inhrelid::regclass::text FROM pg_inherits i "
                           "WHERE i.inhparent = 'water_measurements'::regclass LIMIT 1")
            chunk = cursor.fetchone()[0]
        sql('DROP TRIGGER core_rev_tanks_tanks_note ON tanks')
        sql('ALTER TABLE sites DISABLE TRIGGER core_rev_sites_sites_apply')
        sql('ALTER TABLE systems ENABLE REPLICA TRIGGER core_rev_systems_systems_note')
        sql(f'DROP TRIGGER core_rev_water_measurements_water_point_apply ON {chunk}')
        self.assertEqual(len(rev.missing()), 4)
        [warning] = revision_triggers(None)
        self.assertIn('manage.py core_rev_repair', warning.hint)
        before = max(value for _scope, _key, value in revs_now())
        out = StringIO()
        call_command('core_rev_repair', stdout=out, stderr=StringIO())
        self.assertEqual(rev.missing(), [])
        self.assertEqual(revision_triggers(None), [])
        self.assertIn('water_measurements (water_point)', out.getvalue())
        for table in ('tanks', 'systems', 'sites'):
            self.assertIn(f'{table} ({table})', out.getvalue())
        values = {value for _scope, _key, value in revs_now()}
        self.assertEqual(len(values), 1)                                 # rebuilt: every key at one value
        self.assertGreater(values.pop(), before)
        target = rev.rev('tanks')
        Tank.objects.filter(pk=unit.pk).update(name='Unit one')        # the triggers made again work
        water.record(user, point=point, measured_at=timezone.now() - timedelta(minutes=30), source='manual',
                     values={'temperature_c': D('12.5')})
        rev.settle()
        self.assertEqual((rev.rev('tanks'), rev.rev('water_point', point.pk)), (target + 1, target + 1))
        out = StringIO()
        call_command('core_rev_repair', stdout=out)
        self.assertIn('nothing was changed', out.getvalue())


def hypertables():
    with connection.cursor() as cursor:
        cursor.execute("SELECT hypertable_name FROM timescaledb_information.hypertables WHERE hypertable_schema = 'public'")
        return {name for (name,) in cursor.fetchall()}


def constraint_triggers_on_hypertables():
    with connection.cursor() as cursor:
        cursor.execute(rev.CONSTRAINT_TRIGGERS_ON_HYPERTABLES)
        return cursor.fetchall()


class HypertableTriggerTests(Gate, TestCase):
    """manage.py core_rev_drop_hypertable_triggers, before `ALTER EXTENSION timescaledb UPDATE`: the update renames a
    hypertable chunk's constraints and stops on a constraint trigger ("constraint ... does not exist"), so the revision
    triggers of every tracked hypertable are dropped first (found from TRACKED, never a list of their own), and
    core_rev_repair makes them again afterwards (deploy/scripts/timescaledb-move.sh)."""

    def setUp(self):
        super().setUp()
        user = get_user_model().objects.create_user('rev', 'rev@example.com', 'x')
        site = Site.objects.create(name='Bergen', code='BG')
        hall = ProductionDepartment.objects.create(site=site, name='Hall A', code='HA')
        point = point_of(make_unit('T-01', hall))
        for days in (1, 20):                                       # a chunk with the revision triggers
            water.record(user, point=point, measured_at=timezone.now() - timedelta(days=days), source='manual',
                         values={'temperature_c': D('12.0')})
        rev.settle()

    def test_the_triggers_of_every_tracked_hypertable_are_dropped_and_repair_makes_them_again(self):
        tracked = [(table, scope) for table, scope in rev.TRACKED if table in hypertables()]
        self.assertIn(('water_measurements', 'water_point'), tracked)
        self.assertNotEqual(constraint_triggers_on_hypertables(), [])
        out = StringIO()
        call_command('core_rev_drop_hypertable_triggers', stdout=out)
        self.assertEqual(constraint_triggers_on_hypertables(), [])
        dropped = {name.split(' on ')[0] for name in rev.missing()}
        self.assertEqual(dropped, {name for table, scope in tracked for name in rev.trigger_names(table, scope)})
        self.assertIn('water_measurements (water_point)', out.getvalue())
        out = StringIO()
        call_command('core_rev_drop_hypertable_triggers', stdout=out)  # again: nothing left to drop, no error
        self.assertIn('none', out.getvalue())
        call_command('core_rev_repair', stdout=StringIO())
        self.assertEqual(rev.missing(), [])
        self.assertNotEqual(constraint_triggers_on_hypertables(), [])

    def test_a_constraint_trigger_not_of_the_revisions_on_a_hypertable_is_refused_by_name(self):
        sql('CREATE FUNCTION test_noop() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NULL; END $$')
        sql('CREATE CONSTRAINT TRIGGER test_foreign AFTER INSERT ON water_measurements DEFERRABLE INITIALLY DEFERRED '
            'FOR EACH ROW EXECUTE FUNCTION test_noop()')
        with self.assertRaisesMessage(CommandError, 'test_foreign'):
            call_command('core_rev_drop_hypertable_triggers', stdout=StringIO())


def rev_keys():
    with connection.cursor() as cursor:
        cursor.execute('SELECT scope, key FROM core_rev')
        return cursor.fetchall()


def revs_now():
    with connection.cursor() as cursor:
        cursor.execute('SELECT scope, key, rev FROM core_rev')
        return cursor.fetchall()


class TrackRevOperationTests(TestCase):
    """The migration operation on a table of its own: forwards makes the three triggers, backwards removes them."""

    def test_forwards_truncate_and_backwards(self):
        operation = TrackRev('rev_probe', 'probe', keys='{row}.owner_id', day='{row}.on_day')
        sql('CREATE TABLE rev_probe (id serial PRIMARY KEY, owner_id bigint, on_day date, note text)')
        with connection.schema_editor(atomic=False) as editor:
            operation.database_forwards('core', editor, None, None)
        sql("INSERT INTO rev_probe (owner_id, on_day) VALUES (4, '2026-01-02'), (4, '2026-01-01'), (6, NULL)")
        rev.settle()
        self.assertEqual(row('probe', 4), (1, 0, date(2026, 1, 1)))
        self.assertEqual(row('probe', 6), (1, 0, rev.EVERYTHING))     # an unknown day: the whole history
        rev.mark_built('probe', 4, 1)
        sql('SET CONSTRAINTS ALL IMMEDIATE')
        sql('TRUNCATE rev_probe')                                    # no row trigger fires: every key of the scope moves
        self.assertEqual(row('probe', 4), (2, 1, rev.EVERYTHING))
        self.assertEqual(row('probe', 6), (2, 0, rev.EVERYTHING))
        with connection.schema_editor(atomic=False) as editor:
            operation.database_backwards('core', editor, None, None)
        sql("INSERT INTO rev_probe (owner_id, on_day) VALUES (5, '2026-01-02')")
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM pg_proc WHERE proname = 'core_rev_rev_probe_probe'")
            self.assertEqual(cursor.fetchone()[0], 0)
        rev.settle()
        self.assertIsNone(row('probe', 5))

    def test_a_select_of_keys_and_a_column_filter(self):
        operation = TrackRev('rev_probe', 'probe', keys='SELECT owner_id FROM rev_probe_owner WHERE probe_id = {row}.id',
                             columns=('note',), events=('UPDATE',))
        sql('CREATE TABLE rev_probe (id serial PRIMARY KEY, note text, other text)')
        sql('CREATE TABLE rev_probe_owner (probe_id int, owner_id int)')
        with connection.schema_editor(atomic=False) as editor:
            operation.database_forwards('core', editor, None, None)
        sql("INSERT INTO rev_probe (id, note) VALUES (1, 'a')")
        sql('INSERT INTO rev_probe_owner VALUES (1, 7), (1, 7), (1, 8)')
        rev.settle()
        self.assertIsNone(row('probe', 7))                          # an insert is not one of the events
        sql("UPDATE rev_probe SET other = 'x'")
        sql("UPDATE rev_probe SET note = 'a'")                      # the same value: not a change
        rev.settle()
        self.assertIsNone(row('probe', 7))
        sql("UPDATE rev_probe SET note = 'b'")
        rev.settle()
        self.assertEqual((row('probe', 7), row('probe', 8)), ((1, 0, rev.EVERYTHING), (1, 0, rev.EVERYTHING)))

    def test_names_postgresql_would_cut_and_bad_names_are_refused(self):
        with self.assertRaisesMessage(ValueError, 'longer than 63'):
            TrackRev('a_table_with_a_rather_long_name', 'and_a_scope_as_long_as_it')
        for table, scope in (('Tanks', 'x'), ('tanks', 'x1'), ('tanks;', 'x')):
            with self.subTest(table=table, scope=scope), self.assertRaises(ValueError):
                TrackRev(table, scope)
        with self.assertRaisesMessage(ValueError, 'a column filter needs'):
            TrackRev('tanks', 'x', columns=('name',))

    def test_the_operation_deconstructs_to_itself(self):
        operation = TrackRev('stock_movements', 'unit_stock', keys='{row}.unit_id', day='{row}.x')
        _name, args, kwargs = operation.deconstruct()
        self.assertEqual(TrackRev(*args, **kwargs).sql_forwards(), operation.sql_forwards())


class RebuildCommandTests(TestCase):
    def test_the_command_moves_every_revision_past_the_floor_and_names_missing_triggers(self):
        sql("SELECT core_rev_note('t', '1', NULL)")
        sql("SELECT core_rev_note('u', '2', NULL)")
        rev.settle()
        sql("UPDATE core_rev SET rev = 5 WHERE scope = 'u'")
        sql('ALTER TABLE batches DISABLE TRIGGER core_rev_batches_batch_note')
        out, err = StringIO(), StringIO()
        call_command('core_rev_rebuild', stdout=out, stderr=err)
        self.assertEqual((row('t', 1), row('u', 2), row('*', 0)), ((6, 6, None), (6, 6, None), (6, 6, None)))
        self.assertIn('Every revision is now 6', out.getvalue())
        self.assertIn('core_rev_batches_batch_note', err.getvalue())


class ConcurrencyTests(Gate, Farm, TransactionTestCase):
    """Writers on their own connections, or in real transactions, committing."""
    serialized_rollback = True      # the rows migrations write (the equipment types) come back for later tests

    def setUp(self):
        super().setUp()
        self.make_farm()
        self.b1 = stock_fish(self.user, self.t1, 1000, '50', 20, species=self.salmon)
        self.b2 = stock_fish(self.user, self.t2, 1000, '50', 20, species=self.salmon)
        self.ops = [self.operation(days) for days in range(1, 9)]

    def connect(self):
        params = connection.get_connection_params()
        params.pop('cursor_factory', None)
        params.pop('context', None)
        return psycopg.connect(**params)

    def revs(self, keys):
        return {key: rev.rev(*key) for key in keys}

    def test_one_transaction_moves_each_key_once_and_a_rolled_back_one_moves_nothing(self):
        keys = (('batch', self.b1.pk), ('unit_stock', self.t1.pk), ('tanks', 0))
        start = self.revs(keys)
        with transaction.atomic():
            for operation in self.ops[:3]:
                sql(*self.weighing_sql(operation, self.b1, self.t1))
            Tank.objects.filter(pk=self.t1.pk).update(name='Unit one')
            Tank.objects.filter(pk=self.t2.pk).update(name='Unit two')
            self.assertEqual(self.revs(keys), start)                      # nothing before the commit
        once = {key: value + 1 for key, value in start.items()}
        self.assertEqual(self.revs(keys), once)
        with self.assertRaises(RuntimeError), transaction.atomic():
            sql(*self.weighing_sql(self.ops[3], self.b1, self.t1))
            Tank.objects.filter(pk=self.t1.pk).update(name='Unit 1')
            raise RuntimeError('rolled back')
        self.assertEqual(self.revs(keys), once)
        with transaction.atomic():                                       # a savepoint rolled back takes its notes along
            sql(*self.weighing_sql(self.ops[4], self.b2, self.t2))
            with self.assertRaises(RuntimeError), transaction.atomic():
                sql(*self.weighing_sql(self.ops[5], self.b1, self.t1))
                raise RuntimeError('rolled back')
        self.assertEqual(self.revs(keys), once)
        self.assertEqual(rev.rev('batch', self.b2.pk), 2)

    def test_every_table_moves_at_its_own_commit_with_no_help(self):
        # The TestCases settle by hand (core_rev_flush), which would hide an apply trigger that never fires: here only
        # COMMIT applies the notes, for every tracked table in one transaction, the hypertable's chunks included.
        ras = System.objects.create(name='RAS 1', code='R1', site=self.t1.production_department.site)
        point = point_of(self.t1)
        pump = Equipment.objects.create(name='Pump', code='P1', equipment_type=EquipmentType.objects.get(code='pump-centrifugal'),
                                        production_department=self.t1.production_department,
                                        specifications={'flowRate': 100})
        EquipmentSystem.objects.create(equipment=pump, system=ras, is_primary=True)
        WaterLimit.objects.create(species=self.salmon, parameter='ph', water_type='any', warning_low=D('6.5'))
        device = make_device(make_connection(), make_format(), self.t1.production_department.site)
        Binding.objects.create(channel=make_channel(device, 'ph'), role='primary', point=point,
                               valid_from=timezone.now() - timedelta(days=1))
        PlatformSettings.get()
        models = {model._meta.db_table: model for model in apps.get_models()}
        keys = [(scope, '0') for scope in rev.WATER_TABLES] + [('water_point', str(point.pk))]
        start = self.revs(keys)
        with transaction.atomic():
            for table in rev.WATER_TABLES:
                column = models[table]._meta.pk.column
                sql(f'UPDATE {table} SET {column} = {column} WHERE {column} = (SELECT {column} FROM {table} LIMIT 1)')
            water.record(self.user, point=point, measured_at=timezone.now() - timedelta(hours=1), source='manual',
                         values={'temperature_c': D('12.0')})
            self.assertEqual(self.revs(keys), start)
        moved = self.revs(keys)
        self.assertEqual({key: moved[key] - (start[key] or 0) for key in keys}, {key: 1 for key in keys})

    def test_a_chunk_made_before_the_triggers_gets_them_and_moves_its_point(self):
        # On a database with samples, farm 0050 adds the triggers to a hypertable that already has chunks.
        point = point_of(self.t1)
        moment = timezone.now() - timedelta(hours=2)
        water.record(self.user, point=point, measured_at=moment, source='manual', values={'temperature_c': D('12.0')})
        [operation] = [each for each in rev.operations() if each.table == 'water_measurements']
        with connection.schema_editor() as editor:
            operation.database_backwards('farm', editor, None, None)
        self.assertIn('core_rev_water_measurements_water_point_note', rev.missing())
        with connection.schema_editor() as editor:
            operation.database_forwards('farm', editor, None, None)
        self.assertEqual(rev.missing(), [])
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM pg_inherits i JOIN pg_trigger t ON t.tgrelid = i.inhrelid "
                           "WHERE i.inhparent = 'water_measurements'::regclass AND t.tgname LIKE 'core\\_rev\\_%%'")
            self.assertGreaterEqual(cursor.fetchone()[0], 2)               # the chunk has the note and apply triggers
        before = rev.rev('water_point', point.pk)
        water.record(self.user, point=point, measured_at=moment + timedelta(minutes=5), source='manual',
                     values={'temperature_c': D('12.5')})
        self.assertEqual(rev.rev('water_point', point.pk), before + 1)
        # A chunk that loses its trigger is named. TimescaleDB refuses ALTER TABLE ... DISABLE TRIGGER on the hypertable
        # itself; whichever way a chunk can lose one (disabled, dropped) is tried, and the triggers are made again after.
        name = 'core_rev_water_measurements_water_point_apply'
        with connection.cursor() as cursor:
            cursor.execute("SELECT i.inhrelid::regclass::text FROM pg_inherits i "
                           "WHERE i.inhparent = 'water_measurements'::regclass LIMIT 1")
            chunk = cursor.fetchone()[0]
        broken = None
        try:
            for statement in (f'ALTER TABLE {chunk} DISABLE TRIGGER {name}', f'DROP TRIGGER {name} ON {chunk}'):
                try:
                    with transaction.atomic():
                        sql(statement)
                except DatabaseError as error:
                    print(f'core_rev: {statement!r} refused: {error}')
                    continue
                broken = statement
                break
            print(f'core_rev: a chunk trigger was broken by {broken!r}')
            if broken:
                self.assertEqual(rev.missing(), [f'{name} on {chunk}'])
        finally:
            with connection.schema_editor() as editor:
                operation.database_backwards('farm', editor, None, None)
                operation.database_forwards('farm', editor, None, None)
        self.assertEqual(rev.missing(), [])

    def test_an_open_writer_does_not_block_another_writer_of_the_same_batch(self):
        with self.connect() as first, self.connect() as second:
            first.execute(*self.weighing_sql(self.ops[0], self.b1, self.t1))    # open, not committed
            second.execute("SET statement_timeout = '3s'")
            second.execute(*self.weighing_sql(self.ops[1], self.b1, self.t1))
            second.commit()                                                     # the bump waits for no one
            first.commit()
        self.assertEqual(rev.rev('batch', self.b1.pk), 3)                       # the stocking, then two commits
        self.assertEqual(rev.rev('unit_stock', self.t1.pk), 3)

    def waiting(self, pid):
        """Until the backend `pid` waits for a lock (10 s at most)."""
        import time
        for _ in range(200):
            with connection.cursor() as cursor:
                cursor.execute('SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s', [pid])
                found = cursor.fetchone()
            if found and found[0] == 'Lock':
                return
            time.sleep(0.05)
        self.fail(f'backend {pid} never waited for a lock')

    def held(self, conn, scope, key):
        """Whether another transaction holds the row lock of (scope, key): a NOWAIT lock of it is refused."""
        try:
            conn.execute('SELECT 1 FROM core_rev WHERE scope = %s AND key = %s FOR UPDATE NOWAIT', [scope, str(key)])
        except psycopg.errors.LockNotAvailable:
            conn.rollback()
            return True
        conn.rollback()
        return False

    def test_a_commit_takes_its_keys_in_sorted_order_whatever_order_it_wrote_them_in(self):
        # Deterministic, where the two-writer test is a matter of chance: a commit's apply blocked on one key must
        # already hold every key sorted before it, and none sorted after it, whichever order its rows were written in.
        low, high = sorted((str(self.b1.pk), str(self.b2.pk)))
        first = self.b1 if str(self.b1.pk) == high else self.b2          # written first: the key sorted last
        second = self.b2 if first is self.b1 else self.b1
        units = {self.b1: self.t1, self.b2: self.t2}
        for blocked, before, after in ((high, low, None), (low, None, high)):
            with self.subTest(blocked=blocked), self.connect() as writer, self.connect() as blocker, \
                    self.connect() as probe:
                pid = writer.execute('SELECT pg_backend_pid()').fetchone()[0]
                writer.execute(*self.weighing_sql(self.ops[0], first, units[first]))
                writer.execute(*self.weighing_sql(self.ops[0], second, units[second]))
                blocker.execute('SELECT 1 FROM core_rev WHERE scope = %s AND key = %s FOR UPDATE', ['batch', blocked])
                failures = []

                def commit():
                    try:
                        writer.commit()
                    except psycopg.Error as error:
                        failures.append(error)
                thread = threading.Thread(target=commit)
                thread.start()
                try:
                    self.waiting(pid)
                    if before:
                        self.assertTrue(self.held(probe, 'batch', before), 'a key sorted first is taken first')
                    if after:
                        self.assertFalse(self.held(probe, 'batch', after), 'a key sorted last is not taken yet')
                finally:
                    blocker.rollback()
                    thread.join()
                self.assertEqual(failures, [])
                writer.execute('DELETE FROM stock_movements WHERE operation_id = %s', [self.ops[0].pk])
                writer.commit()

    def test_a_rebuild_waits_for_a_committing_writer_and_never_sets_it_back(self):
        # A writer holds one revision row (its commit has applied that key and not ended) and will take another; a
        # rebuild starting then must take no row before the writer ends: it locks the table first and reads the largest
        # revision only after, so the writer neither deadlocks with it nor has its revision set back. The rows are
        # chosen by their place in the table: a rebuild that updated rows in that order would hold the first one.
        with connection.cursor() as cursor:
            cursor.execute('SELECT scope, key FROM core_rev ORDER BY ctid')
            rows = cursor.fetchall()
        self.assertGreaterEqual(len(rows), 2)
        (first_scope, first_key), (last_scope, last_key) = rows[0], rows[-1]
        failures, done = [], {}
        with self.connect() as writer:
            writer.execute("SET lock_timeout = '10s'")
            writer.execute('UPDATE core_rev SET rev = rev + 100 WHERE scope = %s AND key = %s', [last_scope, last_key])
            pid = {}

            def rebuild():
                from django.db import connections
                try:
                    with connection.cursor() as cursor:
                        cursor.execute('SELECT pg_backend_pid()')
                        pid['rebuild'] = cursor.fetchone()[0]
                    done['target'] = rev.rebuild()
                except Exception as error:                    # noqa: BLE001 - reported below
                    failures.append(error)
                finally:
                    connections.close_all()
            thread = threading.Thread(target=rebuild)
            thread.start()
            try:
                for _ in range(200):
                    if 'rebuild' in pid or failures:
                        break
                    threading.Event().wait(0.05)
                self.waiting(pid['rebuild'])
                writer.execute('UPDATE core_rev SET rev = rev + 100 WHERE scope = %s AND key = %s',
                               [first_scope, first_key])         # a deadlock if the rebuild held this row
                writer.commit()
            finally:
                thread.join()
            committed = writer.execute('SELECT max(rev) FROM core_rev WHERE scope <> %s', ['*']).fetchone()[0]
        self.assertEqual(failures, [])
        self.assertGreater(done['target'], 100)
        self.assertEqual(committed, done['target'])                      # every key at the target, none set back

    def test_two_writers_in_opposite_order_never_deadlock(self):
        failures, rounds = [], 15
        for number in range(rounds):
            ops = [self.operation(30 + 2 * number), self.operation(31 + 2 * number)]
            with self.connect() as first, self.connect() as second:
                first.execute(*self.weighing_sql(ops[0], self.b1, self.t1))
                first.execute(*self.weighing_sql(ops[0], self.b2, self.t2))
                first.execute('UPDATE tanks SET name = name WHERE id = %s', [self.t1.pk])
                second.execute(*self.weighing_sql(ops[1], self.b2, self.t2))
                second.execute(*self.weighing_sql(ops[1], self.b1, self.t1))
                second.execute('UPDATE tanks SET name = name WHERE id = %s', [self.t2.pk])
                start = threading.Barrier(2)

                def commit(conn):
                    start.wait()
                    try:
                        conn.commit()
                    except psycopg.Error as error:
                        failures.append(error)
                threads = [threading.Thread(target=commit, args=(conn,)) for conn in (first, second)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()
        self.assertEqual(failures, [])
        self.assertEqual((rev.rev('batch', self.b1.pk), rev.rev('batch', self.b2.pk)), (1 + 2 * rounds, 1 + 2 * rounds))
        self.assertEqual((rev.rev('unit_stock', self.t1.pk), rev.rev('unit_stock', self.t2.pk)),
                         (1 + 2 * rounds, 1 + 2 * rounds))

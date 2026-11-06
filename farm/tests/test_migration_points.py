"""Migration farm/0019_water_points on a database that already has samples: every sample keeps its values, its void state
and its entry key and ends on the middle point of the unit or system it was in; the units and systems that existed get
their default points; and the migration goes back, or says why it cannot."""
import ast
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from importlib import import_module
from pathlib import Path

from django.db import connection
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.executor import MigrationExecutor
from django.test import SimpleTestCase, TransactionTestCase

from farm.water import points

BEFORE = [('farm', '0018_health')]
AFTER = [('farm', '0019_water_points')]
D = Decimal


def moment(day):
    return datetime(2026, 10, day, 9, 30, tzinfo=timezone.utc)


class WaterPointsMigrationTests(TransactionTestCase):
    # The rows migrations write (the equipment types) come back for the tests that follow.
    serialized_rollback = True

    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def applied(self):
        return ('farm', '0019_water_points') in MigrationExecutor(connection).loader.applied_migrations

    def setUp(self):
        self.old = self.migrate(BEFORE)
        self.addCleanup(lambda: self.migrate(MigrationExecutor(connection).loader.graph.leaf_nodes()))

    def columns(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT column_name, is_nullable FROM information_schema.columns "
                           "WHERE table_name = 'water_measurements'")
            return dict(cursor.fetchall())

    def indexes(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT indexname FROM pg_indexes WHERE tablename = 'water_measurements'")
            return {row[0] for row in cursor.fetchall()}

    def farm(self, apps):
        """A site with a hall, a RAS with a tank in it, a pond and a cage of no system, a deleted tank, a deleted
        system and a unit nobody ever sampled; samples in all but the last, one of them voided."""
        Site, Department = apps.get_model('farm', 'Site'), apps.get_model('farm', 'ProductionDepartment')
        System, Tank = apps.get_model('farm', 'System'), apps.get_model('farm', 'Tank')
        site = Site.objects.create(name='Bergen', code='BG')
        hall = Department.objects.create(site=site, name='Hall A', code='HA')
        tank_fields = {'shape': 'circular', 'material': 'fiberglass', 'diameter': D(2), 'depth': D('1.5'),
                       'max_density_kg_m3': D(60)}
        unit = lambda code, kind='tank', **fields: Tank.objects.create(
            name=f'Unit {code}', code=code, kind=kind, production_department=hall, water_type='freshwater',
            **{**tank_fields, **fields})
        ras = System.objects.create(site=site, name='RAS 1', code='R1')
        farm = {
            'ras': ras, 'tank': unit('T-01', system=ras),
            'pond': unit('P-01', 'pond', pond_type='earthen', surface_area_m2=D(1000), shape='', material='',
                         diameter=None, max_density_kg_m3=D(2)),
            'cage': unit('C-01', 'cage', cage_type='floating', shape='circular', material=''),
            'quiet': unit('T-02'),
            'gone': unit('T-09', is_deleted=True),
            'gone_system': System.objects.create(site=site, name='Old', code='OLD', is_deleted=True),
        }
        return farm

    def sample(self, apps, **fields):
        WaterMeasurement = apps.get_model('farm', 'WaterMeasurement')
        return WaterMeasurement.objects.create(source='manual', **fields)

    def test_every_sample_ends_on_the_middle_point_of_its_unit_or_system_with_all_it_had(self):
        farm = self.farm(self.old)
        key = uuid.uuid4()
        made = {
            'tank': self.sample(self.old, unit=farm['tank'], measured_at=moment(1), ph=D('7.25'), entry_key=key,
                                notes='Morning', temperature_c=D('9.5')),
            'voided': self.sample(self.old, unit=farm['tank'], measured_at=moment(2), tan_mg_l=D('0.125'),
                                  is_deleted=True, void_reason='Wrong unit'),
            'ras': self.sample(self.old, system=farm['ras'], measured_at=moment(3), co2_mg_l=D('12.5')),
            'pond': self.sample(self.old, unit=farm['pond'], measured_at=moment(4), oxygen_mg_l=D('9.25')),
            'cage': self.sample(self.old, unit=farm['cage'], measured_at=moment(5), salinity_ppt=D('33.0')),
            'gone': self.sample(self.old, unit=farm['gone'], measured_at=moment(6), ph=D('6.5')),
            'gone_system': self.sample(self.old, system=farm['gone_system'], measured_at=moment(7), ph=D('6.8')),
        }
        before = {name: sample.pk for name, sample in made.items()}
        new = self.migrate(AFTER)
        Sample = new.get_model('farm', 'WaterMeasurement')
        for name, owner_key, owner_type in (('tank', 'tank', 'unit'), ('voided', 'tank', 'unit'),
                                            ('ras', 'ras', 'system'), ('pond', 'pond', 'unit'),
                                            ('cage', 'cage', 'unit'), ('gone', 'gone', 'unit'),
                                            ('gone_system', 'gone_system', 'system')):
            with self.subTest(sample=name):
                sample = Sample.objects.get(pk=before[name])
                self.assertEqual((getattr(sample.point, owner_type).pk, sample.point.kind, sample.point.is_active),
                                 (farm[owner_key].pk, 'middle', True))
                self.assertEqual(sample.point.name, 'Loop' if owner_type == 'system' else 'Middle')
        tank, voided = Sample.objects.get(pk=before['tank']), Sample.objects.get(pk=before['voided'])
        self.assertEqual((tank.ph, tank.temperature_c, tank.entry_key, tank.notes, tank.measured_at, tank.is_deleted,
                          tank.void_reason, tank.source), (D('7.25'), D('9.5'), key, 'Morning', moment(1), False, '', 'manual'))
        self.assertEqual((voided.tan_mg_l, voided.is_deleted, voided.void_reason, voided.point_id),
                         (D('0.125'), True, 'Wrong unit', tank.point_id))
        self.assertEqual(Sample.objects.count(), 7)
        self.assertEqual(Sample.objects.get(pk=before['gone']).ph, D('6.5'))     # a deleted unit's, out of sight with it
        self.assertEqual(Sample.objects.get(pk=before['ras']).point.system_id, farm['ras'].pk)

    def test_every_unit_and_system_that_existed_gets_the_points_a_new_one_starts_with(self):
        farm = self.farm(self.old)
        new = self.migrate(AFTER)
        Point = new.get_model('farm', 'SamplingPoint')
        kinds = lambda **owner: sorted(Point.objects.filter(**{f'{key}_id': value.pk for key, value in owner.items()})
                                       .values_list('kind', 'name'))
        self.assertEqual(kinds(unit=farm['tank']), [('bottom_drain', 'Bottom drain'), ('inlet', 'Inlet'),
                                                    ('middle', 'Middle'), ('side_outlet', 'Side outlet')])
        self.assertEqual(kinds(unit=farm['quiet']), kinds(unit=farm['tank']))     # none was ever sampled in it
        self.assertEqual(kinds(unit=farm['gone']), kinds(unit=farm['tank']))      # a deleted unit too
        self.assertEqual(kinds(unit=farm['pond']), [('inlet', 'Inlet'), ('middle', 'Middle'), ('outlet', 'Outlet')])
        self.assertEqual(kinds(unit=farm['cage']), [('middle', 'Middle')])
        self.assertEqual(kinds(system=farm['ras']), [('middle', 'Loop')])
        self.assertEqual(kinds(system=farm['gone_system']), [('middle', 'Loop')])
        self.assertEqual(Point.objects.count(), 4 * 3 + 3 + 1 + 2)
        self.assertEqual(Point.objects.filter(is_deleted=True).count(), 0)         # hidden by their owner, not deleted

    def test_the_table_has_a_required_point_and_no_unit_or_system_and_is_still_a_hypertable(self):
        self.migrate(AFTER)
        columns = self.columns()
        self.assertEqual((columns['point_id'], 'unit_id' in columns, 'system_id' in columns), ('NO', False, False))
        self.assertEqual(self.indexes() & {'water_meas_point_time_idx', 'water_meas_unit_time_idx',
                                           'water_meas_system_time_idx'}, {'water_meas_point_time_idx'})
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM timescaledb_information.hypertables "
                           "WHERE hypertable_name = 'water_measurements'")
            self.assertEqual(cursor.fetchone(), (1,))
            cursor.execute("SELECT conname FROM pg_constraint WHERE conrelid = 'water_measurements'::regclass "
                           "AND contype = 'c' AND conname = 'chk_water_measurements_one_point'")
            self.assertIsNone(cursor.fetchone())

    def test_it_goes_back_to_the_unit_or_system_when_every_sample_is_at_a_middle_point(self):
        farm = self.farm(self.old)
        key = uuid.uuid4()
        self.sample(self.old, unit=farm['tank'], measured_at=moment(1), ph=D('7.25'), entry_key=key)
        self.sample(self.old, system=farm['ras'], measured_at=moment(3), co2_mg_l=D('12.5'), is_deleted=True,
                    void_reason='x')
        self.migrate(AFTER)
        self.assertTrue(self.applied())
        old = self.migrate(BEFORE)
        self.assertFalse(self.applied())
        Sample = old.get_model('farm', 'WaterMeasurement')
        self.assertEqual(Sample.objects.count(), 2)
        tank, ras = Sample.objects.get(ph=D('7.25')), Sample.objects.get(co2_mg_l=D('12.5'))
        self.assertEqual((tank.unit_id, tank.system_id, tank.entry_key), (farm['tank'].pk, None, key))
        self.assertEqual((ras.unit_id, ras.system_id, ras.is_deleted, ras.void_reason),
                         (None, farm['ras'].pk, True, 'x'))
        columns = self.columns()
        self.assertEqual(('point_id' in columns, 'unit_id' in columns, 'system_id' in columns), (False, True, True))
        self.assertEqual(self.indexes() & {'water_meas_point_time_idx', 'water_meas_unit_time_idx',
                                           'water_meas_system_time_idx'},
                         {'water_meas_unit_time_idx', 'water_meas_system_time_idx'})
        again = self.migrate(AFTER)            # and forward again: the same samples, on points made again
        self.assertEqual(again.get_model('farm', 'WaterMeasurement').objects.filter(point__kind='middle').count(), 2)

    def test_it_cannot_go_back_while_a_sample_is_at_a_point_the_old_table_could_not_name(self):
        farm = self.farm(self.old)
        self.sample(self.old, unit=farm['tank'], measured_at=moment(1), ph=D('7.25'))
        new = self.migrate(AFTER)
        Point, Sample = new.get_model('farm', 'SamplingPoint'), new.get_model('farm', 'WaterMeasurement')
        inlet = Point.objects.get(unit_id=farm['tank'].pk, kind='inlet')
        Sample.objects.create(point=inlet, measured_at=moment(2), source='manual', ph=D('7.5'))
        with self.assertRaisesMessage(IrreversibleError, '1 water samples are at a point the old table cannot name'):
            self.migrate(BEFORE)
        self.assertTrue(self.applied())                                       # nothing was changed
        self.assertEqual(Sample.objects.count(), 2)
        self.assertIn('point_id', self.columns())
        Sample.objects.filter(point=inlet).delete()
        self.migrate(BEFORE)                                                  # once it is gone, it goes back
        self.assertFalse(self.applied())


class FrozenTemplateTests(SimpleTestCase):
    """F-074: the migration makes the points a unit or system started with on its day from its own copy, never from the
    live app code (farm/water/points.py), so a later change to the template or to the models cannot change what an old
    migration does on a fresh database; the copy is the template as it still is."""

    def test_the_migration_imports_no_app_code_and_its_copy_is_the_template(self):
        path = Path(import_module('farm.migrations').__file__).parent / '0019_water_points.py'
        tree = ast.parse(path.read_text(encoding='utf-8'))
        modules = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        modules |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        self.assertEqual({module for module in modules if module.split('.')[0] not in ('django', 'uuid')}, set())
        migration = import_module('farm.migrations.0019_water_points')
        for owner_type, kind in (('unit', 'tank'), ('unit', 'pond'), ('unit', 'cage'), ('system', '')):
            with self.subTest(owner=owner_type, kind=kind):
                self.assertEqual(migration.template_for(owner_type, kind),
                                 [(str(each), str(name)) for each, name in points.template_for(owner_type, kind)])

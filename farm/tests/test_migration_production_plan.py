"""Migrations farm/0053–0055 (the production plan's growth) on a database that already has feeding protocols and
weighings: every protocol keeps the step at its bands' edges it always had (the rule is written on it), every
weighing line is given the manual source before the database asks for one, and the migrations go back."""
from datetime import date
from decimal import Decimal

from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

BEFORE = [('farm', '0052_probe_days_and_floors')]
AFTER = [('farm', '0055_weighing_names_its_source')]
D = Decimal


class ProductionPlanMigrationTests(TransactionTestCase):
    # The rows migrations write (the equipment types, the handling rules, the manual source) come back for the tests
    # that follow.
    serialized_rollback = True

    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def setUp(self):
        self.old = self.migrate(BEFORE)
        self.addCleanup(lambda: self.migrate(MigrationExecutor(connection).loader.graph.leaf_nodes()))

    def rows(self, apps):
        """A protocol, and a batch in a unit with its stocking line and a weighing line, as the old tables held them."""
        get = lambda name: apps.get_model('farm', name)       # noqa: E731
        species = get('Species').objects.create(code='SAL', common_name='Atlantic salmon', scientific_name='Salmo salar',
                                                freshwater=True, saltwater=True)
        protocol = get('FeedingProtocol').objects.create(name='Old table', species=species, expected_fcr=D('1.10'),
                                                         status='active')
        hall = get('ProductionDepartment').objects.create(
            site=get('Site').objects.create(name='Bergen', code='BG'), name='Hall A', code='HA')
        unit = get('Tank').objects.create(name='Unit T-01', code='T-01', kind='tank', production_department=hall,
                                          water_type='freshwater', shape='circular', material='fiberglass',
                                          diameter=D(2), depth=D('1.5'), max_density_kg_m3=D(60))
        batch = get('Batch').objects.create(code='B-2026-001', species=species, input_stage='smolt',
                                            origin='own_hatchery', provenance='farmed',
                                            input_date=date(2026, 11, 1))
        Operation, Line = get('StockOperation'), get('StockMovement')
        stocked = Line.objects.create(operation=Operation.objects.create(kind='input', date=date(2026, 11, 1)),
                                      batch=batch, unit=unit, kind='input', count_delta=100, avg_weight_g=D(50))
        weighed = Line.objects.create(operation=Operation.objects.create(kind='weighing', date=date(2026, 11, 10)),
                                      batch=batch, unit=unit, kind='weighing', count_delta=0, avg_weight_g=D(60))
        return protocol, stocked, weighed

    def test_old_protocols_keep_their_step_and_old_weighings_get_their_source(self):
        protocol, stocked, weighed = self.rows(self.old)
        new = self.migrate(AFTER)
        Protocol, Line = new.get_model('farm', 'FeedingProtocol'), new.get_model('farm', 'StockMovement')
        Source = new.get_model('farm', 'WeightSource')
        kept = Protocol.objects.get(pk=protocol.pk)
        # it keeps the rule it always followed, for every quantity: a step at the band's edge
        self.assertEqual((kept.fcr_between, kept.uneaten_between, kept.sfr_between, kept.expected_fcr, kept.uneaten_pct,
                          kept.mortality_pct_month), ('step', 'step', 'step', D('1.10'), None, None))
        manual = Source.objects.get()
        self.assertEqual((manual.code, manual.name), ('manual', 'Manual sample'))
        self.assertEqual(Line.objects.get(pk=weighed.pk).weight_source_id, manual.pk)
        self.assertIsNone(Line.objects.get(pk=stocked.pk).weight_source_id)
        # a protocol made after the migration is smooth between its bands
        made = Protocol.objects.create(name='New table', species_id=kept.species_id, expected_fcr=D('1.00'))
        self.assertEqual((made.fcr_between, made.uneaten_between, made.sfr_between), ('smooth',) * 3)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Protocol.objects.filter(pk=made.pk).update(sfr_between='linear')
        # the database holds the rule from now on: a weighing names its source, nothing else does
        with self.assertRaises(IntegrityError), transaction.atomic():
            Line.objects.filter(pk=weighed.pk).update(weight_source=None)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Line.objects.filter(pk=stocked.pk).update(weight_source=manual)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Source.objects.filter(pk=manual.pk).update(is_deleted=True)
        for field, value in (('uneaten_pct', D('50.1')), ('mortality_pct_month', D('30.01'))):
            with self.assertRaises(IntegrityError), transaction.atomic():
                Protocol.objects.filter(pk=kept.pk).update(**{field: value})

    def test_going_back_keeps_the_protocols_and_the_weighings(self):
        protocol, _stocked, weighed = self.rows(self.old)
        self.migrate(AFTER)
        old = self.migrate(BEFORE)
        self.assertEqual(old.get_model('farm', 'FeedingProtocol').objects.get(pk=protocol.pk).expected_fcr, D('1.10'))
        self.assertEqual(old.get_model('farm', 'StockMovement').objects.get(pk=weighed.pk).avg_weight_g, D(60))

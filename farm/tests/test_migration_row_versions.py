"""Migration farm/0056 (the rows a plan from a past start reads, kept in every version: core.versions) on a database that
already has them: each row gets one version from when it was made (a band and a cell from their protocol's making), a
row deleted by then two (as it was before its delete, and from it on), the triggers keep every change after, and the
migration goes back."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

BEFORE = [('farm', '0055_weighing_names_its_source')]
AFTER = [('farm', '0056_row_versions')]
D = Decimal
MADE = datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc)
DELETED = MADE + timedelta(days=20)


class RowVersionsMigrationTests(TransactionTestCase):
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
        """A protocol with a band and a cell, a profile with a point, and a protocol's row on a unit deleted since, all
        made on MADE, as the old tables held them."""
        get = lambda name: apps.get_model('farm', name)       # noqa: E731
        species = get('Species').objects.create(code='SAL', common_name='Atlantic salmon', scientific_name='Salmo salar',
                                                freshwater=True, saltwater=True)
        protocol = get('FeedingProtocol').objects.create(name='Old table', species=species, expected_fcr=D('1.10'),
                                                         status='active')
        feed = get('Feed').objects.create(name='Grower', code='GR', feed_type='grower')
        band = get('ProtocolBand').objects.create(protocol=protocol, min_weight_g=0, feed=feed, meals_per_day=4)
        cell = get('ProtocolRate').objects.create(band=band, temperature_c=D(10), sfr_pct=D(1))
        profile = get('TemperatureProfile').objects.create(name='Hall', species=species, status='active')
        point = get('TemperatureProfilePoint').objects.create(profile=profile, weight_g=0, temperature_c=D(10))
        hall = get('ProductionDepartment').objects.create(
            site=get('Site').objects.create(name='Bergen', code='BG'), name='Hall A', code='HA')
        unit = get('Tank').objects.create(name='Unit T-01', code='T-01', kind='tank', production_department=hall,
                                          water_type='freshwater', shape='circular', material='fiberglass',
                                          diameter=D(2), depth=D('1.5'), max_density_kg_m3=D(60))
        row = get('ProtocolAssignment').objects.create(protocol=protocol, unit=unit, valid_from=date(2026, 10, 1),
                                                       is_deleted=True, deleted_at=DELETED)
        for model, made in ((protocol, MADE), (profile, MADE), (point, MADE + timedelta(hours=1)), (row, MADE)):
            type(model).objects.filter(pk=model.pk).update(created_at=made)
        return protocol, band, cell, point, row

    def versions(self, apps, table, row_id):
        return list(apps.get_model('core', 'RowVersion').objects.filter(table_name=table, row_id=str(row_id))
                    .order_by('valid_from', 'id').values_list('valid_from', 'valid_to', 'data'))

    def test_the_rows_there_get_their_versions_and_every_change_after_is_kept(self):
        protocol, band, cell, point, row = self.rows(self.old)
        new = self.migrate(AFTER)
        [(since, until, data)] = self.versions(new, 'feeding_protocols', protocol.pk)
        self.assertEqual((since, until, data['name']), (MADE, None, 'Old table'))
        # a band and a cell are known from their protocol's making (the table is saved whole); a point from its own
        self.assertEqual([version[:2] for version in self.versions(new, 'feeding_protocol_bands', band.pk)],
                         [(MADE, None)])
        self.assertEqual([version[:2] for version in self.versions(new, 'feeding_protocol_rates', cell.pk)],
                         [(MADE, None)])
        self.assertEqual([version[:2] for version in self.versions(new, 'temperature_profile_points', point.pk)],
                         [(MADE + timedelta(hours=1), None)])
        # a row deleted by then: as it was before its delete, and from it on
        self.assertEqual([(since, until, data['is_deleted'], data['deleted_at'])
                          for since, until, data in self.versions(new, 'protocol_assignments', row.pk)],
                         [(MADE, DELETED, False, None), (DELETED, None, True, '2026-10-21T08:00:00+00:00')])
        # from now on the triggers keep every change
        new.get_model('farm', 'FeedingProtocol').objects.filter(pk=protocol.pk).update(name='Renamed')
        first, second = self.versions(new, 'feeding_protocols', protocol.pk)
        self.assertEqual((first[2]['name'], second[2]['name'], second[1]), ('Old table', 'Renamed', None))
        self.assertEqual(first[1], second[0])

    def test_going_back_takes_the_triggers_and_the_versions_away_and_coming_again_makes_them(self):
        protocol, *_rest = self.rows(self.old)
        self.migrate(AFTER)
        old = self.migrate(BEFORE)
        self.assertFalse(old.get_model('core', 'RowVersion').objects.filter(table_name='feeding_protocols').exists())
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM pg_trigger WHERE tgname LIKE 'core\\_versions\\_%%'")
            self.assertEqual(cursor.fetchone()[0], 0)
        old.get_model('farm', 'FeedingProtocol').objects.filter(pk=protocol.pk).update(name='Changed meanwhile')
        new = self.migrate(AFTER)
        [(since, until, data)] = self.versions(new, 'feeding_protocols', protocol.pk)
        self.assertEqual((since, until, data['name']), (MADE, None, 'Changed meanwhile'))

"""Migration farm/0039_fasting_acknowledgement_feeding on a database that already has acknowledged handling warnings
(review F-07 of the flow faults): every row is kept, a fasting acknowledgement can name the feeding its fast was
counted from and a withdrawal row cannot, and the migration goes back only while no row names a feeding: the
acknowledgements are the record of what a person was shown, so it refuses, saying why, rather than drop that."""
from datetime import date, datetime, timezone
from decimal import Decimal

from django.db import IntegrityError, connection, transaction
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from farm import withdrawal_gate

BEFORE = [('farm', '0038_cleaner_fish_no_size_check')]
AFTER = [('farm', '0039_fasting_acknowledgement_feeding')]
D = Decimal


class FeedingAcknowledgementMigrationTests(TransactionTestCase):
    # The rows migrations write (the equipment types, the handling rules) come back for the tests that follow.
    serialized_rollback = True

    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def applied(self):
        return AFTER[0] in MigrationExecutor(connection).loader.applied_migrations

    def columns(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT column_name FROM information_schema.columns "
                           "WHERE table_name = 'handling_acknowledgements'")
            return {row[0] for row in cursor.fetchall()}

    def setUp(self):
        self.old = self.migrate(BEFORE)
        self.addCleanup(lambda: self.migrate(MigrationExecutor(connection).loader.graph.leaf_nodes()))

    def acknowledged(self, apps):
        """A harvest with a fast and a withdrawal acknowledged (the two kinds of row the old table holds)."""
        Operation, Rule = apps.get_model('farm', 'StockOperation'), apps.get_model('farm', 'HandlingRule')
        Acknowledgement = apps.get_model('farm', 'HandlingAcknowledgement')
        operation = Operation.objects.create(kind='harvest', date=date(2026, 11, 3))
        fast = Acknowledgement.objects.create(
            operation=operation, warning='fasting', last_fed_at=datetime(2026, 11, 2, 18, 0, tzinfo=timezone.utc),
            rule=Rule.objects.get(kind='harvest', species__isnull=True), fasted_hours=D('6.0'), required_hours=72)
        held = Acknowledgement.objects.create(
            operation=operation, warning='withdrawal', withdrawal_until=date(2026, 11, 20),
            withdrawal_reason='Salmosan vet., bath from 01.11.2026 to 01.11.2026: withdrawal 7 days.')
        return fast, held

    @withdrawal_gate.opened('test fixture: a feeding straight in the database')
    def feeding(self, apps):
        Site, Department = apps.get_model('farm', 'Site'), apps.get_model('farm', 'ProductionDepartment')
        Tank, Feed = apps.get_model('farm', 'Tank'), apps.get_model('farm', 'Feed')
        hall = Department.objects.create(site=Site.objects.create(name='Bergen', code='BG'), name='Hall A', code='HA')
        unit = Tank.objects.create(name='Unit T-01', code='T-01', kind='tank', production_department=hall,
                                   water_type='freshwater', shape='circular', material='fiberglass', diameter=D(2),
                                   depth=D('1.5'), max_density_kg_m3=D(60))
        feed = Feed.objects.create(name='Grower 4', code='GR-4', feed_type='grower', pellet_size_mm=D(4))
        return apps.get_model('farm', 'FeedingRecord').objects.create(unit=unit, date=date(2026, 11, 2), feed=feed,
                                                                     amount_kg=D('12'))

    def test_every_row_is_kept_and_a_fast_can_name_its_feeding_a_withdrawal_cannot(self):
        fast, held = self.acknowledged(self.old)
        self.assertNotIn('feeding_id', self.columns())
        new = self.migrate(AFTER)
        self.assertIn('feeding_id', self.columns())
        Acknowledgement = new.get_model('farm', 'HandlingAcknowledgement')
        rows = {row.pk: row for row in Acknowledgement.objects.all()}
        self.assertEqual(set(rows), {fast.pk, held.pk})
        self.assertEqual((rows[fast.pk].warning, rows[fast.pk].fasted_hours, rows[fast.pk].required_hours,
                          rows[fast.pk].last_fed_at, rows[fast.pk].feeding_id),
                         ('fasting', D('6.0'), 72, datetime(2026, 11, 2, 18, 0, tzinfo=timezone.utc), None))
        self.assertEqual((rows[held.pk].warning, rows[held.pk].withdrawal_until, rows[held.pk].withdrawal_reason,
                          rows[held.pk].feeding_id),
                         ('withdrawal', date(2026, 11, 20),
                          'Salmosan vet., bath from 01.11.2026 to 01.11.2026: withdrawal 7 days.', None))
        feeding = self.feeding(new)
        Acknowledgement.objects.filter(pk=fast.pk).update(feeding=feeding)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Acknowledgement.objects.filter(pk=held.pk).update(feeding=feeding)

    def test_it_goes_back_while_no_row_names_a_feeding_and_forward_again(self):
        self.acknowledged(self.old)
        self.migrate(AFTER)
        self.assertTrue(self.applied())
        old = self.migrate(BEFORE)
        self.assertFalse(self.applied())
        self.assertNotIn('feeding_id', self.columns())
        self.assertEqual(old.get_model('farm', 'HandlingAcknowledgement').objects.count(), 2)
        again = self.migrate(AFTER)
        self.assertEqual(again.get_model('farm', 'HandlingAcknowledgement').objects.count(), 2)

    def test_it_refuses_to_go_back_while_a_row_names_the_feeding_it_was_counted_from(self):
        fast, _held = self.acknowledged(self.old)
        new = self.migrate(AFTER)
        Acknowledgement = new.get_model('farm', 'HandlingAcknowledgement')
        feeding = self.feeding(new)
        Acknowledgement.objects.filter(pk=fast.pk).update(feeding=feeding)
        with self.assertRaisesMessage(IrreversibleError, '1 fasting acknowledgement names the feeding its fast was '
                                                         'counted from'):
            self.migrate(BEFORE)
        self.assertTrue(self.applied())                                             # nothing was changed
        self.assertIn('feeding_id', self.columns())
        self.assertEqual(Acknowledgement.objects.get(pk=fast.pk).feeding_id, feeding.pk)

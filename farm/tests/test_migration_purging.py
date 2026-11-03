"""Migration farm/0022_purging_degree_days on a database that already has handling rules and acknowledged fasts: every
one keeps its values, the rules take degree-days (a harvest's) and may have no hours, and the migration goes back, or
says why it cannot."""
from datetime import date, datetime, timezone
from decimal import Decimal

from django.db import IntegrityError, connection, transaction
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

BEFORE = [('farm', '0021_medicine_withdrawals')]
AFTER = [('farm', '0022_purging_degree_days')]
D = Decimal


class PurgingMigrationTests(TransactionTestCase):
    # The rows migrations write (the equipment types, the handling rules) come back for the tests that follow.
    serialized_rollback = True

    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def applied(self):
        return ('farm', '0022_purging_degree_days') in MigrationExecutor(connection).loader.applied_migrations

    def setUp(self):
        self.old = self.migrate(BEFORE)
        self.addCleanup(lambda: self.migrate(MigrationExecutor(connection).loader.graph.leaf_nodes()))

    def acknowledged_fast(self, apps, **fields):
        """A stock operation with a fasting acknowledgement short in hours (the only kind the old table could hold)."""
        Operation, Rule = apps.get_model('farm', 'StockOperation'), apps.get_model('farm', 'HandlingRule')
        Acknowledgement = apps.get_model('farm', 'HandlingAcknowledgement')
        operation = Operation.objects.create(kind='harvest', date=date(2026, 11, 3))
        rule = Rule.objects.get(kind='harvest', species__isnull=True)
        moment = datetime(2026, 11, 2, 18, 0, tzinfo=timezone.utc)
        return Acknowledgement.objects.create(operation=operation, warning='fasting', last_fed_at=moment, rule=rule,
                                              fasted_hours=D('6.0'), required_hours=72, **fields)

    def test_the_rules_and_the_acknowledged_fasts_keep_their_values_and_the_rules_take_degree_days(self):
        ack = self.acknowledged_fast(self.old)
        new = self.migrate(AFTER)
        Rule = new.get_model('farm', 'HandlingRule')
        self.assertEqual(sorted(Rule.objects.filter(species__isnull=True).values_list('kind', 'min_fasting_hours',
                                                                                        'min_fasting_degree_days')),
                         [('grading', 24, None), ('harvest', 72, None), ('transport', 24, None),
                          ('treatment', 24, None)])
        row = new.get_model('farm', 'HandlingAcknowledgement').objects.get(pk=ack.pk)
        self.assertEqual((row.fasted_hours, row.required_hours, row.fasted_degree_days, row.required_degree_days),
                         (D('6.0'), 72, None, None))
        # A harvest rule can have degree-days alone; the other kinds cannot, and a rule needs one or the other.
        harvest = Rule.objects.get(kind='harvest', species__isnull=True)
        Rule.objects.filter(pk=harvest.pk).update(min_fasting_hours=None, min_fasting_degree_days=D(60))
        for fields in ({'kind': 'transport', 'min_fasting_hours': 24, 'min_fasting_degree_days': D(10)},
                       {'kind': 'harvest', 'min_fasting_hours': None, 'min_fasting_degree_days': None}):
            with self.subTest(fields=fields), self.assertRaises(IntegrityError), transaction.atomic():
                Rule.objects.filter(kind=fields['kind'], species__isnull=True).update(
                    **{key: value for key, value in fields.items() if key != 'kind'})

    def test_it_goes_back_when_nothing_needs_the_new_columns_and_forward_again(self):
        self.acknowledged_fast(self.old)
        self.migrate(AFTER)
        self.assertTrue(self.applied())
        old = self.migrate(BEFORE)
        self.assertFalse(self.applied())
        self.assertEqual(old.get_model('farm', 'HandlingRule').objects.filter(species__isnull=True).count(), 4)
        with connection.cursor() as cursor:
            cursor.execute("SELECT column_name FROM information_schema.columns "
                           "WHERE table_name = 'handling_rules'")
            self.assertNotIn('min_fasting_degree_days', {row[0] for row in cursor.fetchall()})
        again = self.migrate(AFTER)
        self.assertEqual(again.get_model('farm', 'HandlingAcknowledgement').objects.count(), 1)

    def test_it_cannot_go_back_with_a_rule_without_hours_or_a_fast_acknowledged_for_its_degree_days(self):
        self.acknowledged_fast(self.old)
        new = self.migrate(AFTER)
        Rule = new.get_model('farm', 'HandlingRule')
        Acknowledgement = new.get_model('farm', 'HandlingAcknowledgement')
        Rule.objects.filter(kind='harvest', species__isnull=True).update(min_fasting_hours=None,
                                                                         min_fasting_degree_days=D(60))
        with self.assertRaisesMessage(IrreversibleError, '1 handling rules have no hours, and 0 acknowledged fasts'):
            self.migrate(BEFORE)
        self.assertTrue(self.applied())                                             # nothing was changed
        Rule.objects.filter(kind='harvest', species__isnull=True).update(min_fasting_hours=72,
                                                                         min_fasting_degree_days=None)
        operation = new.get_model('farm', 'StockOperation').objects.create(kind='harvest', date=date(2026, 11, 4))
        harvest = Rule.objects.get(kind='harvest', species__isnull=True)
        Acknowledgement.objects.create(
            operation=operation, warning='fasting', last_fed_at=datetime(2026, 11, 3, 18, tzinfo=timezone.utc),
            rule=harvest, fasted_hours=D('90.0'), required_hours=72, fasted_degree_days=D(30),
            required_degree_days=D(60))                    # the hours were reached: acknowledged for the degree-days
        with self.assertRaisesMessage(IrreversibleError, '0 handling rules have no hours, and 1 acknowledged fasts'):
            self.migrate(BEFORE)
        Acknowledgement.objects.filter(operation=operation).delete()
        self.migrate(BEFORE)                                                        # once mended, it goes back
        self.assertFalse(self.applied())

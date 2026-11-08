"""Migration farm 0027 (the withdrawal acknowledgements): its append-only trigger is there, and it goes back to 0026 and
forward again (the cross-review's migration probe, adopted)."""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class WithdrawalAcknowledgementMigrationTests(TransactionTestCase):
    serialized_rollback = True        # the rows the migrations seed come back for the tests after it

    def found(self, sql):
        with connection.cursor() as cursor:
            cursor.execute(sql)
            return cursor.fetchone()[0]

    def test_the_trigger_is_there_and_0027_goes_back_and_forward(self):
        trigger = "SELECT count(*) FROM pg_trigger WHERE tgname = 'trg_withdrawal_acknowledgements_append_only'"
        table = "SELECT to_regclass('withdrawal_acknowledgements') IS NOT NULL"
        function = "SELECT count(*) FROM pg_proc WHERE proname = 'withdrawal_acknowledgement_append_only'"
        self.assertEqual((self.found(trigger), self.found(table)), (1, True))
        latest = MigrationExecutor(connection).loader.graph.leaf_nodes('farm')
        MigrationExecutor(connection).migrate([('farm', '0026_production_form_other')])
        self.assertEqual((self.found(table), self.found(function)), (False, 0))
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(latest)
        self.assertEqual((self.found(table), self.found(trigger)), (True, 1))

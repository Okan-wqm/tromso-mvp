"""The migrations of the Experiments app: what the database really holds after them (the catalogue, not the models),
that they go back and forward again, and that they depend on the farm's migrations only as far as the farm's
tables they read, so the order in which other branches add farm migrations cannot matter."""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

TABLES = ('experiments', 'experiment_factors', 'experiment_levels', 'experiment_groups', 'experiment_group_levels',
          'experiment_replicates', 'experiment_replicate_units', 'experiment_members')
COMPOSITE_KEYS = {
    'fk_experiment_levels_factor_kind': ('experiment_levels', 'experiment_factors'),
    'fk_experiment_group_levels_group': ('experiment_group_levels', 'experiment_groups'),
    'fk_experiment_group_levels_factor': ('experiment_group_levels', 'experiment_factors'),
    'fk_experiment_group_levels_level': ('experiment_group_levels', 'experiment_levels'),
}
FIRST = ('experiments', '0001_initial')


def rows(sql, params=None):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall()


def present(table):
    return rows('SELECT to_regclass(%s)', [table])[0][0] is not None


class ExperimentMigrationTests(TransactionTestCase):
    # The rows migrations write (the equipment types) come back for the tests that follow.
    serialized_rollback = True

    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)

    def tearDown(self):
        self.migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())

    def test_the_composite_keys_the_exclusion_and_the_unique_pairs_are_in_the_catalogue(self):
        keys = {name: (table, other) for name, table, other in rows(
            "SELECT c.conname, c.conrelid::regclass::text, c.confrelid::regclass::text FROM pg_constraint c "
            "WHERE c.contype = 'f' AND array_length(c.conkey, 1) = 2 AND c.conrelid::regclass::text ~ '^experiment'")}
        self.assertEqual(keys, COMPOSITE_KEYS)
        deferrable = rows("SELECT conname FROM pg_constraint WHERE conname ~ '^fk_experiment' AND condeferrable")
        self.assertEqual(deferrable, [])                      # nothing is circular: refused at the statement
        exclusions = rows("SELECT conname, conrelid::regclass::text FROM pg_constraint WHERE contype = 'x' "
                          "AND conrelid::regclass::text ~ '^experiment'")
        self.assertEqual(exclusions, [('excl_replicate_units_unit', 'experiment_replicate_units')])
        uniques = {name for (name,) in rows("SELECT conname FROM pg_constraint WHERE contype = 'u' "
                                            "AND conrelid::regclass::text ~ '^experiment'")}
        self.assertTrue({'uq_experiments_code', 'uq_experiment_factors_id_experiment',
                         'uq_experiment_factors_id_kind', 'uq_experiment_levels_id_factor',
                         'uq_experiment_groups_id_experiment', 'uq_experiment_group_levels_group_factor'} <= uniques)
        self.assertEqual(rows("SELECT 1 FROM pg_extension WHERE extname = 'btree_gist'"), [(1,)])

    def test_every_table_is_there_and_goes_with_the_migration_and_comes_back(self):
        self.assertTrue(all(present(table) for table in TABLES))
        self.migrate([('experiments', None)])
        self.assertFalse(any(present(table) for table in TABLES))
        self.assertEqual(rows("SELECT 1 FROM pg_extension WHERE extname = 'btree_gist'"), [(1,)])     # the farm's own
        self.assertTrue(present('feeding_protocols'))                                                 # and its tables
        self.migrate([FIRST])
        self.assertTrue(all(present(table) for table in TABLES))
        self.assertEqual({name for name, *_ in rows("SELECT conname FROM pg_constraint WHERE conname ~ "
                                                    "'^fk_experiment'")}, set(COMPOSITE_KEYS))

    def test_it_depends_on_the_farm_as_it_was_before_the_branches_that_add_to_it(self):
        loader = MigrationExecutor(connection).loader
        parents = {key for key in loader.graph.node_map[FIRST].parents if key[0] == 'farm'}
        self.assertEqual(parents, {('farm', '0018_health')})
        self.assertEqual(len(loader.graph.leaf_nodes('experiments')), 1)

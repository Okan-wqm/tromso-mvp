"""Before a release migrates (deploy/web/release.sh, docs/ops/upgrade.md): every CHECK constraint a migration not yet
applied adds, tried against the rows the database holds now, with the very SQL the migration will add. A row that
breaks one would stop that migration half-way through a release; this says so before anything is migrated, naming the
migration, the constraint and how many rows, and exits 1. Reads only."""
from django.core.management.base import BaseCommand, CommandError
from django.db import DEFAULT_DB_ALIAS, DatabaseError, connections, models, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.operations import AddConstraint


def pending_checks(connection, plan=None):
    """[(migration, constraint name, rows breaking it)] for every CheckConstraint an unapplied migration adds (or the
    migrations of `plan`, [(migration, backwards)]), each tried on the model as it stands just before that migration.
    The count is None when the rows cannot be tried yet: the table, or a column the condition reads, is made by a
    migration before it in the same release (a new table holds no rows; a new column is tried by the migration)."""
    executor = MigrationExecutor(connection)
    if plan is None:
        plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
    found = []
    tables = set(connection.introspection.table_names())
    if 'django_migrations' not in tables:
        return found                                    # a new database: every table is made by this release, empty
    for migration, backwards in plan:
        added = [operation for operation in migration.operations
                 if isinstance(operation, AddConstraint) and isinstance(operation.constraint, models.CheckConstraint)]
        if backwards or not added:
            continue
        state = executor.loader.project_state((migration.app_label, migration.name), at_end=False)
        for operation in added:
            model = state.apps.get_model(migration.app_label, operation.model_name)
            with connection.schema_editor(collect_sql=True, atomic=False) as editor:
                check = operation.constraint._get_check_sql(model, editor)
            if model._meta.db_table not in tables:
                found.append((migration, operation.constraint.name, None))
                continue
            table = connection.ops.quote_name(model._meta.db_table)
            try:
                with transaction.atomic(using=connection.alias), connection.cursor() as cursor:
                    # a CHECK holds when its condition is true or unknown: only a false one is a broken row
                    cursor.execute(f'SELECT count(*) FROM {table} WHERE NOT ({check})')
                    count = cursor.fetchone()[0]
            except DatabaseError:
                count = None
            found.append((migration, operation.constraint.name, count))
    return found


class Command(BaseCommand):
    help = 'Tries every CHECK constraint the unapplied migrations add against the rows there are now (reads only).'

    def add_arguments(self, parser):
        parser.add_argument('--database', default=DEFAULT_DB_ALIAS)

    def handle(self, *args, **options):
        found = pending_checks(connections[options['database']])
        broken = [(migration, name, count) for migration, name, count in found if count]
        for migration, name, count in found:
            self.stdout.write(f'{migration.app_label}.{migration.name} {name}: '
                              + ('tried by the migration itself (its table or column is made in this release)'
                                 if count is None else f'{count} row(s) break it' if count else 'every row holds'))
        if not found:
            self.stdout.write('No unapplied migration adds a CHECK constraint.')
        if broken:
            raise CommandError(f'{len(broken)} constraint(s) of the unapplied migrations would be refused by the rows '
                               'there are: correct those rows (through the pages, or the release notes say how) '
                               'before migrating.')

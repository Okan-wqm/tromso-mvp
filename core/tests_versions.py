"""Row versions (core.versions): every kept table's triggers keep each version of its rows, stamped with their
transaction's moment, and `as_of` reads a past moment's rows by their ids, typed as the table types them and sealed by
each version's own place and day as well as by the row now. A TestCase is one transaction, so every write in it has the
same stamp: a test moves what was kept so far back in time (`recorded_at`) before the changes it reads past."""
import json
from datetime import timedelta
from decimal import Decimal as D

from django.db import DatabaseError, IntegrityError, connection, transaction
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.operations import AddField, AlterField, RemoveField, RenameField
from django.test import TestCase
from django.utils import timezone

from core import rev, sealing
from core.crud import Resource
from core.models import KeptTable, RowVersion
from farm.models import FeedingProtocol, ProtocolAssignment, Species, TemperatureProfile, TemperatureProfilePoint
from farm.tests.helpers import make_species, recorded_at

from . import checks, versions
from .operations import DefinerTrigger, KeepVersions, RewriteVersions


def scalar(sql, params=()):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchone()[0]


class VersionsTests(TestCase):
    def setUp(self):
        self.salmon = make_species()

    def profile(self, name='Hall A', **fields):
        return TemperatureProfile.objects.create(name=name, species=self.salmon, status='active', **fields)

    def past(self, hours):
        return timezone.now() - timedelta(hours=hours)

    # ---- what is kept, and how it is kept ------------------------------------------------------------------------
    def test_every_kept_table_has_its_triggers_enabled_and_a_migration_that_keeps_it(self):
        loader = MigrationLoader(connection, ignore_no_migrations=True)
        kept = sorted(operation.table for migration in loader.disk_migrations.values()
                      for operation in migration.operations if isinstance(operation, KeepVersions))
        self.assertEqual(kept, sorted(versions.VERSIONED))
        self.assertEqual(sorted(operation.table for operation in versions.operations()), sorted(versions.VERSIONED))
        with connection.cursor() as cursor:
            cursor.execute("SELECT tgname FROM pg_trigger WHERE tgname LIKE 'core\\_versions\\_%%' "
                           "AND tgenabled IN ('O', 'A') AND NOT tgisinternal")
            found = sorted(name for (name,) in cursor.fetchall())
        self.assertEqual(found, sorted(name for table in versions.VERSIONED for name in KeepVersions.names_of(table)))
        self.assertEqual(sorted(KeptTable.objects.values_list('table_name', flat=True)), sorted(versions.VERSIONED))

    def test_a_version_is_stamped_with_its_transaction_so_a_transaction_lands_whole(self):
        profile = self.profile()
        TemperatureProfile.objects.filter(pk=profile.pk).update(name='Hall B')
        stamp = scalar('SELECT transaction_timestamp()')
        first, second = RowVersion.objects.filter(table_name='temperature_profiles', row_id=str(profile.pk)).order_by(
            'valid_from', 'id')
        self.assertEqual((first.valid_from, first.valid_to, second.valid_from, second.valid_to),
                         (stamp, stamp, stamp, None))

    def test_two_versions_of_a_row_never_overlap(self):
        with connection.cursor() as cursor, self.assertRaises(IntegrityError), transaction.atomic():
            cursor.execute("INSERT INTO core_row_versions (table_name, row_id, valid_from, valid_to, data) VALUES "
                           "('temperature_profiles', 'x', %s, %s, '{}'), ('temperature_profiles', 'x', %s, %s, '{}')",
                           [self.past(9), self.past(5), self.past(7), self.past(3)])

    # ---- the security of the history (review 2, H1) ----------------------------------------------------------------
    def test_the_trigger_functions_run_as_their_owner_for_public_tables_only_and_nobody_else_may_call_them(self):
        for name in ('core_row_version', 'core_row_versions_truncated'):
            self.assertFalse(scalar("SELECT has_function_privilege('public', %s, 'EXECUTE')", [f'public.{name}()']))
            self.assertEqual(scalar('SELECT prosecdef FROM pg_proc WHERE proname = %s', [name]), True)
            self.assertEqual(scalar('SELECT proconfig FROM pg_proc WHERE proname = %s', [name]),
                             ['search_path=pg_catalog, public, pg_temp'])

    def test_a_table_of_another_schema_cannot_forge_a_version(self):
        profile = self.profile()
        with connection.cursor() as cursor:
            cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
            cursor.execute('CREATE TEMP TABLE temperature_profiles (LIKE public.temperature_profiles)')
            cursor.execute('INSERT INTO pg_temp.temperature_profiles SELECT * FROM public.temperature_profiles')
            cursor.execute('CREATE TRIGGER forge AFTER UPDATE OR DELETE ON pg_temp.temperature_profiles FOR EACH ROW '
                           "EXECUTE FUNCTION public.core_row_version('id')")
            with self.assertRaises(DatabaseError), transaction.atomic():
                cursor.execute("UPDATE pg_temp.temperature_profiles SET name = 'FORGED'")
            cursor.execute('DROP TABLE pg_temp.temperature_profiles')
        self.assertEqual(scalar("SELECT data->>'name' FROM public.core_row_versions WHERE table_name = "
                                "'temperature_profiles' AND row_id = %s AND valid_to IS NULL", [str(profile.pk)]),
                         'Hall A')

    def test_a_shadow_versions_table_receives_nothing(self):
        profile = self.profile()
        with connection.cursor() as cursor:
            cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
            cursor.execute('CREATE TEMP TABLE core_row_versions (LIKE public.core_row_versions INCLUDING DEFAULTS)')
            cursor.execute("UPDATE public.temperature_profiles SET name = 'Hall seen' WHERE id = %s", [profile.pk])
            cursor.execute('SELECT count(*) FROM pg_temp.core_row_versions')
            shadowed = cursor.fetchone()[0]
            cursor.execute("SELECT data->>'name' FROM public.core_row_versions WHERE table_name = 'temperature_profiles' "
                           'AND row_id = %s AND valid_to IS NULL', [str(profile.pk)])
            kept = cursor.fetchone()[0]
            cursor.execute('DROP TABLE pg_temp.core_row_versions')
        self.assertEqual((shadowed, kept), (0, 'Hall seen'))

    def test_every_definer_trigger_function_is_made_by_the_one_helper(self):
        loader = MigrationLoader(connection, ignore_no_migrations=True)
        made = sorted(operation.function for migration in loader.disk_migrations.values()
                      for operation in migration.operations if isinstance(operation, DefinerTrigger))
        with connection.cursor() as cursor:
            cursor.execute("SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                           "WHERE n.nspname = 'public' AND p.prosecdef AND p.prorettype = 'trigger'::regtype")
            found = sorted(name for (name,) in cursor.fetchall())
        self.assertEqual(found, made)

    # ---- reading by identity ---------------------------------------------------------------------------------------
    def test_a_row_renamed_since_and_another_given_its_old_name_are_each_themselves(self):
        first = self.profile()
        recorded_at(self.past(10))
        then = self.past(5)
        TemperatureProfile.objects.filter(pk=first.pk).update(name='Hall old')
        second = self.profile()                                    # the old name, given to another row
        self.assertEqual([(row.pk, row.name) for row in versions.as_of(TemperatureProfile, then,
                                                                       id=[first.pk, second.pk])],
                         [(first.pk, 'Hall A')])
        self.assertEqual(sorted((str(row.pk), row.name) for row in versions.as_of(TemperatureProfile, timezone.now(),
                                                                                    id=[first.pk, second.pk])),
                         sorted([(str(first.pk), 'Hall old'), (str(second.pk), 'Hall A')]))
        self.assertEqual(versions.as_of(TemperatureProfile, then, name=['Hall A'])[0].pk, first.pk)

    def test_the_values_read_are_the_rows_own_typed_as_the_table_types_them_and_are_never_saved(self):
        profile = self.profile(notes='Cold hall')
        point = TemperatureProfilePoint.objects.create(profile=profile, weight_g=D('12.50'), temperature_c=D('8.5'))
        stored = TemperatureProfile.objects.get(pk=profile.pk)
        [read] = versions.as_of(TemperatureProfile, timezone.now(), id=[profile.pk])
        for field in TemperatureProfile._meta.concrete_fields:
            self.assertEqual(getattr(read, field.attname), getattr(stored, field.attname), field.name)
        [cell] = versions.as_of(TemperatureProfilePoint, timezone.now(), profile=[profile.pk])
        self.assertEqual((cell.pk, cell.weight_g, cell.temperature_c), (point.pk, D('12.50'), D('8.5')))
        self.assertIsInstance(cell.weight_g, D)
        for write in (read.save, read.delete, cell.save):
            with self.assertRaises(TypeError):
                write()

    def test_an_update_that_changes_nothing_keeps_no_version_and_one_that_does_closes_the_last(self):
        profile = self.profile()
        kept = RowVersion.objects.filter(table_name='temperature_profiles', row_id=str(profile.pk))
        self.assertEqual(kept.count(), 1)
        TemperatureProfile.objects.filter(pk=profile.pk).update(name='Hall A')
        self.assertEqual(kept.count(), 1)
        TemperatureProfile.objects.filter(pk=profile.pk).update(name='Hall B')
        first, second = kept.order_by('valid_from', 'id')
        self.assertEqual((first.data['name'], second.data['name'], second.valid_to), ('Hall A', 'Hall B', None))
        self.assertEqual(first.valid_to, second.valid_from)

    def test_a_deleted_row_is_read_before_its_delete_and_not_after(self):
        profile = self.profile()
        point = TemperatureProfilePoint.objects.create(profile=profile, weight_g=0, temperature_c=D(10))
        made = point.pk
        recorded_at(self.past(10))
        point.delete()
        self.assertEqual([row.pk for row in versions.as_of(TemperatureProfilePoint, self.past(5),
                                                           profile=[profile.pk])], [made])
        self.assertEqual(versions.as_of(TemperatureProfilePoint, timezone.now(), profile=[profile.pk]), [])

    def test_a_soft_deleted_row_is_left_out_unless_asked_for(self):
        profile = self.profile()
        recorded_at(self.past(10))
        TemperatureProfile.objects.filter(pk=profile.pk).update(is_deleted=True)
        now = timezone.now()
        self.assertEqual(versions.as_of(TemperatureProfile, now, id=[profile.pk]), [])
        self.assertEqual([row.is_deleted for row in versions.as_of(TemperatureProfile, now, deleted=True,
                                                                   id=[profile.pk])], [True])
        self.assertEqual([row.is_deleted for row in versions.as_of(TemperatureProfile, self.past(5), id=[profile.pk])],
                         [False])

    def test_a_truncate_closes_every_version_open(self):
        profile = self.profile()
        TemperatureProfilePoint.objects.create(profile=profile, weight_g=0, temperature_c=D(10))
        with connection.cursor() as cursor:
            cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')       # the pending deferred checks first
            cursor.execute('TRUNCATE temperature_profile_points')
        self.assertFalse(RowVersion.objects.filter(table_name='temperature_profile_points', valid_to__isnull=True)
                         .exists())

    def test_nothing_asked_reads_nothing_and_a_table_not_kept_is_refused(self):
        with self.assertNumQueries(0):
            self.assertEqual(versions.as_of(TemperatureProfile, None, id=[], species=[None]), [])
        with self.assertRaises(ValueError):
            versions.as_of(Species, None)

    # ---- the presence check and the repair, one with core_rev's (review 2, M3) -----------------------------------
    def test_a_disabled_version_trigger_is_named_and_the_repair_keeps_the_rows_from_then_on(self):
        profile = self.profile()
        name = KeepVersions.names_of('temperature_profile_points')[0]
        with connection.cursor() as cursor:
            cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
            cursor.execute(f'ALTER TABLE temperature_profile_points DISABLE TRIGGER {name}')
        self.assertIn(name, rev.missing())
        unseen = TemperatureProfilePoint.objects.create(profile=profile, weight_g=0, temperature_c=D(10))
        self.assertFalse(RowVersion.objects.filter(table_name='temperature_profile_points', row_id=str(unseen.pk))
                         .exists())
        made = rev.repair()
        self.assertIn(('temperature_profile_points', versions.SCOPE), made)
        self.assertNotIn(name, rev.missing())
        [opened] = RowVersion.objects.filter(table_name='temperature_profile_points', row_id=str(unseen.pk))
        self.assertEqual((opened.valid_to, opened.data['temperature_c']), (None, 10.0))
        self.assertEqual(versions.resync('temperature_profile_points'), 0)       # in step: nothing more to open

    # ---- schema changes of a kept table (review 2, M2) -------------------------------------------------------------
    def test_a_rewrite_adds_renames_retypes_and_drops_the_versions_keys_and_the_check_names_a_table_out_of_step(self):
        profile = self.profile(notes='Cold')
        self.assertEqual(checks.version_columns(None), [])
        operation = RewriteVersions('temperature_profiles', add={'colour': 'blue'}, rename={'notes': 'remarks'},
                                    retype={'version': 'to_jsonb(({value})::text)'}, drop=('updated_by_id',))
        with connection.schema_editor(atomic=False) as editor:
            operation.database_forwards('core', editor, None, None)
        data = RowVersion.objects.get(table_name='temperature_profiles', row_id=str(profile.pk)).data
        self.assertEqual((data['colour'], data['remarks'], data['version'], 'notes' in data, 'updated_by_id' in data),
                         ('blue', 'Cold', '1', False, False))
        warnings = checks.version_columns(None)
        self.assertEqual([warning.id for warning in warnings], ['core.W006'])
        self.assertIn('temperature_profiles', warnings[0].msg)
        self.assertEqual(operation.deconstruct()[0], 'RewriteVersions')
        self.assertEqual(json.loads(json.dumps(operation.deconstruct()[2]['add'])), {'colour': 'blue'})

    def test_every_schema_change_of_a_kept_table_after_its_keeping_rewrites_its_versions(self):
        """The migration graph: after a table's KeepVersions, an added, removed, renamed or retyped column of its model
        sits in a migration that rewrites the versions' keys (RewriteVersions) too."""
        loader = MigrationLoader(connection, ignore_no_migrations=True)
        tables = {(model._meta.app_label, model._meta.model_name): model._meta.db_table
                  for model in versions.kept_models()}
        kept, missing = set(), []
        for node in _plan(loader):
            migration = loader.graph.nodes[node]
            rewritten = {operation.table for operation in migration.operations if isinstance(operation, RewriteVersions)}
            for operation in migration.operations:
                if isinstance(operation, KeepVersions):
                    kept.add(operation.table)
                elif isinstance(operation, (AddField, RemoveField, RenameField, AlterField)):
                    table = tables.get((node[0], operation.model_name.lower()))
                    if table in kept and table not in rewritten and not _same_column(loader, node, operation):
                        missing.append(f'{node[0]}.{node[1]}: {operation.describe()}')
        self.assertEqual(missing, [])

    def test_the_tables_kept_hold_no_persons_private_text(self):
        """Kept forever and never erased (docs/erasure.md, What remains): a table whose tab declares private fields
        (a person's own words, core.crud.Resource.private_fields) is never kept."""
        private = sorted(f'{each.model._meta.db_table}: {each.private_fields}' for each in Resource.registry
                         if each.model._meta.db_table in versions.VERSIONED and each.private_fields)
        self.assertEqual(private, [])

    def test_the_versions_are_rows_about_other_records(self):
        self.assertEqual(sealing.seal_of(RowVersion).mode, sealing.ABOUT)


def _plan(loader):
    """Every migration of the project in an order the graph allows."""
    seen, order = set(), []
    for leaf in sorted(loader.graph.leaf_nodes()):
        for node in loader.graph.forwards_plan(leaf):
            if node not in seen:
                seen.add(node)
                order.append(node)
    return order


def _same_column(loader, node, operation):
    """Whether an AlterField keeps its column's name and type (nothing for the versions to rewrite)."""
    if not isinstance(operation, AlterField):
        return False
    before = loader.project_state(node, at_end=False).apps.get_model(node[0], operation.model_name)
    after = loader.project_state(node, at_end=True).apps.get_model(node[0], operation.model_name)
    old, new = before._meta.get_field(operation.name), after._meta.get_field(operation.name)
    return (old.column, old.db_type(connection)) == (new.column, new.db_type(connection))


class SealedVersionsTests(TestCase):
    """The seal over the versions (review 2, H2 and M1): a viewer without the cell's grant reads no version dated inside
    a sealed cell, though the row was moved out of it since, nor any version of such a row in the database viewer; a
    row outside the cell then and now is read; the cell's team reads every one."""

    @classmethod
    def setUpTestData(cls):
        from experiments.tests import world
        world.build_open(cls)
        world.build_sealed(cls)
        cls.protocol = FeedingProtocol.objects.create(name='XQZ diet', species=cls.salmon, expected_fcr=D('1.00'))
        inside = cls.today - timedelta(days=world.BEGAN - 1)
        cls.inside = ProtocolAssignment.objects.create(protocol=cls.protocol, unit=cls.sealed_tanks[0], valid_from=inside)
        cls.moved = ProtocolAssignment.objects.create(protocol=cls.protocol, unit=cls.sealed_tanks[2], valid_from=inside)
        cls.open = ProtocolAssignment.objects.create(protocol=cls.protocol, unit=cls.open_tank, valid_from=inside)
        cls.units = [cls.sealed_tanks[0], cls.sealed_tanks[2], cls.open_tank]

    def setUp(self):
        recorded_at(timezone.now() - timedelta(hours=10))
        self.then = timezone.now() - timedelta(hours=5)
        # since then the row on the third trial tank was moved before the cell's first day: it is outside the cell now
        before = self.today - timedelta(days=40)
        ProtocolAssignment.objects.filter(pk=self.moved.pk).update(valid_from=before,
                                                                   valid_until=before + timedelta(days=5))

    def read(self, user, moment):
        with sealing.as_viewer(user):
            return {row.pk for row in versions.as_of(ProtocolAssignment, moment, unit=[unit.pk for unit in self.units])}

    def test_a_viewer_without_the_grant_reads_no_version_dated_inside_the_cell(self):
        self.assertEqual(self.read(self.researcher, self.then), {self.open.pk})
        self.assertEqual(self.read(self.researcher, timezone.now()), {self.open.pk, self.moved.pk})

    def test_the_cells_team_reads_every_version(self):
        self.assertEqual(self.read(self.lead, self.then), {self.open.pk, self.moved.pk, self.inside.pk})

    def test_the_database_viewer_shows_no_version_of_a_row_with_a_sealed_past(self):
        ids = [str(row.pk) for row in (self.inside, self.moved, self.open)]
        for user, expected in ((self.researcher, {str(self.open.pk)}), (self.lead, set(ids))):
            with sealing.as_viewer(user):
                seen = set(RowVersion.objects.filter(table_name='protocol_assignments', row_id__in=ids)
                           .values_list('row_id', flat=True))
            self.assertEqual(seen, expected, user.username)

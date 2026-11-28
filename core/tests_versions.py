"""Row versions (core.versions): every kept table's triggers keep each version of its rows, and `as_of` reads a past
moment's rows by their ids, typed as the table types them. The moments are the database's own (clock_timestamp(),
which the triggers stamp with), read between the writes: a TestCase is one transaction, whose now() never moves."""
from decimal import Decimal as D

from django.db import connection
from django.db.migrations.loader import MigrationLoader
from django.test import TestCase

from core.models import RowVersion
from farm.models import Species, TemperatureProfile, TemperatureProfilePoint
from farm.tests.helpers import make_species

from . import versions
from .operations import KeepVersions


def moment():
    with connection.cursor() as cursor:
        cursor.execute('SELECT clock_timestamp()')
        return cursor.fetchone()[0]


class VersionsTests(TestCase):
    def setUp(self):
        self.salmon = make_species()

    def profile(self, name='Hall A', **fields):
        return TemperatureProfile.objects.create(name=name, species=self.salmon, status='active', **fields)

    def test_every_kept_table_has_its_triggers_and_a_migration_that_keeps_it(self):
        loader = MigrationLoader(connection, ignore_no_migrations=True)
        kept = sorted(operation.table for migration in loader.disk_migrations.values()
                      for operation in migration.operations if isinstance(operation, KeepVersions))
        self.assertEqual(kept, sorted(versions.VERSIONED))
        with connection.cursor() as cursor:
            cursor.execute("SELECT tgname FROM pg_trigger WHERE tgname LIKE 'core\\_versions\\_%%' AND tgenabled <> 'D'")
            found = sorted(name for (name,) in cursor.fetchall())
        self.assertEqual(found, sorted(name for table in versions.VERSIONED for name in KeepVersions.names_of(table)))

    def test_a_row_renamed_since_and_another_given_its_old_name_are_each_themselves(self):
        first = self.profile()
        then = moment()
        TemperatureProfile.objects.filter(pk=first.pk).update(name='Hall old')
        second = self.profile()                                    # the old name, given to another row
        now = moment()
        self.assertEqual([(row.pk, row.name) for row in versions.as_of(TemperatureProfile, then, id=[first.pk, second.pk])],
                         [(first.pk, 'Hall A')])
        self.assertEqual(sorted((str(row.pk), row.name) for row in versions.as_of(TemperatureProfile, now,
                                                                                    id=[first.pk, second.pk])),
                         sorted([(str(first.pk), 'Hall old'), (str(second.pk), 'Hall A')]))
        self.assertEqual(versions.as_of(TemperatureProfile, then, name=['Hall A'])[0].pk, first.pk)

    def test_the_values_read_are_the_rows_own_typed_as_the_table_types_them(self):
        profile = self.profile(notes='Cold hall')
        point = TemperatureProfilePoint.objects.create(profile=profile, weight_g=D('12.50'), temperature_c=D('8.5'))
        stored = TemperatureProfile.objects.get(pk=profile.pk)
        [read] = versions.as_of(TemperatureProfile, moment(), id=[profile.pk])
        for field in TemperatureProfile._meta.concrete_fields:
            self.assertEqual(getattr(read, field.attname), getattr(stored, field.attname), field.name)
        [cell] = versions.as_of(TemperatureProfilePoint, moment(), profile=[profile.pk])
        self.assertEqual((cell.pk, cell.weight_g, cell.temperature_c), (point.pk, D('12.50'), D('8.5')))
        self.assertIsInstance(cell.weight_g, D)

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
        before, made = moment(), point.pk
        point.delete()
        self.assertEqual([row.pk for row in versions.as_of(TemperatureProfilePoint, before, profile=[profile.pk])],
                         [made])
        self.assertEqual(versions.as_of(TemperatureProfilePoint, moment(), profile=[profile.pk]), [])

    def test_a_soft_deleted_row_is_left_out_unless_asked_for(self):
        profile = self.profile()
        alive = moment()
        TemperatureProfile.objects.filter(pk=profile.pk).update(is_deleted=True)
        self.assertEqual(versions.as_of(TemperatureProfile, moment(), id=[profile.pk]), [])
        self.assertEqual([row.is_deleted for row in versions.as_of(TemperatureProfile, moment(), deleted=True,
                                                                   id=[profile.pk])], [True])
        self.assertEqual([row.is_deleted for row in versions.as_of(TemperatureProfile, alive, id=[profile.pk])],
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

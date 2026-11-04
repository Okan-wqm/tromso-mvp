"""Migration farm/0021_medicine_withdrawals on a database that already has medicines: every medicine's days and
degree-days end in a row for every species with nothing lost (a deleted medicine's too); the old checks are gone and the
new ones hold; and the migration goes back, or says why it cannot."""
import uuid
from decimal import Decimal

from django.db import IntegrityError, connection, transaction
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

BEFORE = [('farm', '0020_species_withdrawal_temperature')]
AFTER = [('farm', '0021_medicine_withdrawals')]
D = Decimal


class MedicineWithdrawalsMigrationTests(TransactionTestCase):
    # The rows migrations write (the equipment types, the handling rules) come back for the tests that follow.
    serialized_rollback = True

    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def applied(self):
        return ('farm', '0021_medicine_withdrawals') in MigrationExecutor(connection).loader.applied_migrations

    def setUp(self):
        self.old = self.migrate(BEFORE)
        self.addCleanup(lambda: self.migrate(MigrationExecutor(connection).loader.graph.leaf_nodes()))

    def columns(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'medicines'")
            return {row[0] for row in cursor.fetchall()}

    def constraints(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT conname FROM pg_constraint WHERE conrelid = 'medicines'::regclass AND contype = 'c'")
            return {row[0] for row in cursor.fetchall()}

    def medicine(self, apps, name, degree_days=None, days=None, **fields):
        Medicine = apps.get_model('farm', 'Medicine')
        return Medicine.objects.create(name=name, kind='lice', administration='bath', active_substance='azamethiphos',
                                       lice_report_code='AZAMETHIPHOS', withdrawal_degree_days=degree_days,
                                       withdrawal_days=days, **fields)

    def medicines(self, apps):
        return {
            'both': self.medicine(apps, 'Salmosan vet.', 150, 7),
            'days': self.medicine(apps, 'Slice vet.', None, 14),
            'degrees': self.medicine(apps, 'Alpha Ject', 40, None),
            'none': self.medicine(apps, 'Vaccine', 0, 0),
            'gone': self.medicine(apps, 'Old vet.', 10, None, is_deleted=True),
        }

    def test_every_medicines_values_land_in_a_row_for_every_species_and_the_columns_go(self):
        made = self.medicines(self.old)
        ids = {name: medicine.pk for name, medicine in made.items()}
        new = self.migrate(AFTER)
        Row = new.get_model('farm', 'MedicineWithdrawal')
        self.assertEqual(Row.objects.count(), 5)
        found = {name: Row.objects.get(medicine_id=pk) for name, pk in ids.items()}
        self.assertEqual({name: (row.species_id, row.degree_days, row.days, row.safety_margin_pct, row.note)
                          for name, row in found.items()}, {
            'both': (None, D('150.0'), 7, D('0.0'), ''), 'days': (None, None, 14, D('0.0'), ''),
            'degrees': (None, D('40.0'), None, D('0.0'), ''), 'none': (None, D('0.0'), 0, D('0.0'), ''),
            'gone': (None, D('10.0'), None, D('0.0'), '')})                  # a deleted medicine's too, 0 kept as 0
        self.assertFalse({'withdrawal_days', 'withdrawal_degree_days'} & self.columns())
        self.assertFalse({'chk_medicines_withdrawal', 'chk_medicines_withdrawal_bounds'} & self.constraints())
        Medicine = new.get_model('farm', 'Medicine')
        self.assertEqual(Medicine.objects.count(), 5)

    def test_the_new_checks_hold_on_the_migrated_table(self):
        made = self.medicines(self.old)
        new = self.migrate(AFTER)
        Row = new.get_model('farm', 'MedicineWithdrawal')
        medicine = made['both']
        for fields in ({'species': None, 'days': 1},                                  # a second row for every species
                       {'species': None, 'days': None, 'degree_days': None}, {'species': None, 'days': 1001},
                       {'species': None, 'degree_days': D(10001)}, {'species': None, 'days': 1,
                                                                    'safety_margin_pct': D(201)}):
            with self.subTest(fields=fields), self.assertRaises(IntegrityError), transaction.atomic():
                Row.objects.create(medicine_id=medicine.pk, **fields)

    def test_it_goes_back_into_the_columns_and_forward_again(self):
        made = self.medicines(self.old)
        ids = {name: medicine.pk for name, medicine in made.items()}
        self.migrate(AFTER)
        self.assertTrue(self.applied())
        old = self.migrate(BEFORE)
        self.assertFalse(self.applied())
        Medicine = old.get_model('farm', 'Medicine')
        values = {name: Medicine.objects.get(pk=pk) for name, pk in ids.items()}
        self.assertEqual({name: (medicine.withdrawal_degree_days, medicine.withdrawal_days)
                          for name, medicine in values.items()},
                         {'both': (150, 7), 'days': (None, 14), 'degrees': (40, None), 'none': (0, 0),
                          'gone': (10, None)})
        self.assertTrue(values['gone'].is_deleted)
        self.assertTrue({'chk_medicines_withdrawal', 'chk_medicines_withdrawal_bounds'} <= self.constraints())
        with self.assertRaises(IntegrityError), transaction.atomic():              # the old check is back
            self.medicine(old, 'Nothing', None, None)
        again = self.migrate(AFTER)                                                # and forward again, the same rows
        self.assertEqual(again.get_model('farm', 'MedicineWithdrawal').objects.count(), 5)

    def test_it_cannot_go_back_while_a_row_is_of_a_species_of_its_own_or_a_medicine_has_none_for_every_species(self):
        made = self.medicines(self.old)
        new = self.migrate(AFTER)
        Row, Species = new.get_model('farm', 'MedicineWithdrawal'), new.get_model('farm', 'Species')
        salmon = Species.objects.create(id=uuid.uuid4(), common_name='Atlantic salmon', scientific_name='Salmo salar',
                                        code='SAL', freshwater=True)
        Row.objects.create(medicine_id=made['both'].pk, species=salmon, days=10)
        Row.objects.filter(medicine_id=made['days'].pk).delete()
        with self.assertRaisesMessage(IrreversibleError, '1 withdrawal rows are for a species of their own, and 1 '
                                                         'medicines have no withdrawal for every species'):
            self.migrate(BEFORE)
        self.assertTrue(self.applied())                                             # nothing was changed
        self.assertEqual(Row.objects.count(), 5)
        Row.objects.filter(species__isnull=False).delete()
        Row.objects.create(medicine_id=made['days'].pk, species=None, days=14)
        self.migrate(BEFORE)                                                        # once mended, it goes back
        self.assertFalse(self.applied())

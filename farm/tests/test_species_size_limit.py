"""The size limit of a species (Setup › Reference data › Species): how many times heavier, on average, one batch of the
species may be than another sharing a unit with it (the owner: fish of very different weights of the same species must
not be in the same tank). Reference data the farm edits, never a constant in the code: empty means no check, the
migration gives every species already there the default 2, and a new species is offered 2."""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.urls import reverse

from core.models import AuditLog, Profile

from ..models import Species
from .helpers import stock_fish
from .test_species import SpeciesTestCase, species_data, stored

D = Decimal
BEFORE = [('farm', '0033_oxygen_basis')]
AFTER = [('farm', '0034_species_max_weight_ratio')]


class SizeLimitSetupTests(SpeciesTestCase):
    def test_a_new_species_limit_is_typed_saved_changed_cleared_and_logged(self):
        form = self.client.get(reverse('farm:species_create'), headers={'X-Modal': '1'})
        self.assertIsNone(form.context['form']['max_weight_ratio'].value())     # empty: the offer of its kind
        self.assertContains(form, 'data-tab="stocking">Stocking</button>')
        self.assertContains(form, 'Left empty on a new species: 2 for a production species')
        self.create(max_weight_ratio='2')
        species = Species.objects.get()
        self.assertEqual(stored(species, 'max_weight_ratio'), (D('2.00'),))
        Profile.objects.create(user=self.user, language='nb')
        self.edit(species, max_weight_ratio='2,5')                          # typed the way the language writes it
        self.assertEqual(stored(species, 'max_weight_ratio'), (D('2.50'),))
        self.edit(species, max_weight_ratio='')
        self.assertEqual(stored(species, 'max_weight_ratio'), (None,))
        changes = [entry.changes for entry in AuditLog.objects.filter(entity_type='species', action='update')
                   .order_by('created_at')]
        label = 'Max weight ratio of batches in one unit'
        self.assertEqual([change[label] for change in changes], [['2.00', '2.50'], ['2.50', None]])

    def test_the_limit_is_1_to_1000_in_the_form_and_in_the_database(self):
        for value in ('0', '0.99', '-2', '1000.01', 'two'):
            with self.subTest(value=value):
                self.assertIn('max_weight_ratio', self.errors(self.create(max_weight_ratio=value)))
        self.assertFalse(Species.objects.exists())
        species = self.make(max_weight_ratio=D('1'))
        for value in (D('0.5'), D('1000.5')):
            with self.subTest(value=value), self.assertRaisesMessage(IntegrityError, 'chk_species_max_weight_ratio'), \
                    transaction.atomic():
                Species.objects.filter(pk=species.pk).update(max_weight_ratio=value)
        with self.assertRaises(ValidationError):
            Species(common_name='X', scientific_name='Xus yus', code='XY', freshwater=True,
                    max_weight_ratio=D('0.5')).full_clean()

    def test_the_list_says_the_limit_or_that_there_is_no_check(self):
        self.make(max_weight_ratio=D('2'))
        self.make('Rainbow trout', 'Oncorhynchus mykiss', 'RBT', max_weight_ratio=D('2.5'))
        self.make('Lumpfish', 'Cyclopterus lumpus', 'LUMP', saltwater=True, cleaner_fish_type='lumpfish')
        response = self.client.get(reverse('farm:species_list'))
        self.assertContains(response, '<th scope="col">Size limit</th>', html=True)
        self.assertContains(response, '<td class="nowrap">2×</td>', html=True)
        self.assertContains(response, '<td class="nowrap">2.5×</td>', html=True)
        self.assertContains(response, '<td class="nowrap">No check</td>', html=True)

    def test_the_limit_is_edited_with_fish_stocked_and_needs_no_withdrawal_question(self):
        """The withdrawal guard watches the species' assumed water temperature only: the size limit is not a withdrawal
        input, so editing it with fish stocked is an ordinary edit."""
        species = self.make('Atlantic salmon', 'Salmo salar', 'SAL', saltwater=True, max_weight_ratio=D('2'))
        from ..models import ProductionDepartment, Site, Tank
        site = Site.objects.create(name='Bergen', code='BG', timezone='UTC')
        hall = ProductionDepartment.objects.create(site=site, name='Hall', code='H')
        unit = Tank.objects.create(name='Unit', code='T-01', kind='tank', production_department=hall,
                                   water_type='freshwater', status='preparing', shape='rectangular', material='steel',
                                   length=10, width=5, depth=2, max_density_kg_m3=50)
        stock_fish(self.user, unit, 100, '50', 3, species=species)
        response = self.edit(species, common_name='Atlantic salmon', scientific_name='Salmo salar', code='SAL',
                             saltwater=True, max_weight_ratio='3')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(stored(species, 'max_weight_ratio'), (D('3.00'),))

    def test_the_setting_speaks_each_language(self):
        self.make(max_weight_ratio=None)
        for language, words in {'nb': ('Størrelsesgrense', 'Ingen kontroll'),
                                'tr': ('Boy sınırı', 'Denetim yok')}.items():
            Profile.objects.update_or_create(user=self.user, defaults={'language': language})
            with self.subTest(language=language):
                response = self.client.get(reverse('farm:species_list'))
                for word in words:
                    self.assertContains(response, word)


class SizeLimitMigrationTests(TransactionTestCase):
    """Migration farm/0034: every species already there gets the default 2 (deleted ones too, so a restored species
    keeps the rule); a species made afterwards has none unless it is given one."""
    serialized_rollback = True

    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def setUp(self):
        self.old = self.migrate(BEFORE)
        self.addCleanup(lambda: self.migrate(MigrationExecutor(connection).loader.graph.leaf_nodes()))

    def test_every_species_there_gets_2_and_going_back_and_forth_works(self):
        Old = self.old.get_model('farm', 'Species')
        live = Old.objects.create(common_name='Atlantic salmon', scientific_name='Salmo salar', code='SAL',
                                  freshwater=True)
        gone = Old.objects.create(common_name='Lumpfish', scientific_name='Cyclopterus lumpus', code='LUMP',
                                  saltwater=True, is_deleted=True)
        new = self.migrate(AFTER)
        Species = new.get_model('farm', 'Species')
        self.assertEqual({row.code: row.max_weight_ratio for row in Species._base_manager.all()},
                         {'SAL': D('2.00'), 'LUMP': D('2.00')})
        later = Species.objects.create(common_name='Cod', scientific_name='Gadus morhua', code='COD', saltwater=True)
        self.assertIsNone(Species._base_manager.get(pk=later.pk).max_weight_ratio)
        self.migrate(BEFORE)
        self.migrate(AFTER)
        self.assertEqual(new.get_model('farm', 'Species')._base_manager.get(pk=live.pk).max_weight_ratio, D('2.00'))
        self.assertTrue(new.get_model('farm', 'Species')._base_manager.filter(pk=gone.pk).exists())

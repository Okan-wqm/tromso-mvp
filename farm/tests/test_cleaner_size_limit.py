"""The size limit of a cleaner fish (owner decision, 2026-11-10): lumpfish and wrasses are topped up with fish of other
sizes, so for a species with a cleaner-fish type the default is no check (the limit empty), still editable. A top-up of
cleaner fish then asks nothing and shows no "Mixed sizes" chip; salmon is unchanged. Migration farm/0038 empties the
limit of the cleaner species that still hold the untouched default 2, each logged; a limit a person set stays."""
from decimal import Decimal
from importlib import import_module

from django.apps import apps
from django.db import connection
from django.urls import reverse

from core.models import AuditLog

from ..models import Batch, Species, StockOperation
from ..stock import read
from .helpers import role
from .test_cleaner_fish import CleanerFishTestCase
from .test_size_mix import TICK
from .test_species import SpeciesTestCase, species_data, stored
from .test_stock import DialogTests

D = Decimal
LABEL = 'Max weight ratio of batches in one unit'
NO_CHECK = ('No size check was set: a cleaner fish is topped up with fish of other sizes. Give it a limit on the '
            'Stocking tab if this farm wants one.')
DEFAULT_SET = ('The size limit was set to 2×, the default for a production species. Empty it on the Stocking tab if this '
               'species needs no check.')
LUMPFISH = {'common_name': 'Lumpfish', 'scientific_name': 'Cyclopterus lumpus', 'code': 'LUMP', 'freshwater': False,
            'saltwater': True}


def migration():
    return import_module('farm.migrations.0038_cleaner_fish_no_size_check')


class CleanerFishOfferTests(SpeciesTestCase):
    """A new species' size limit: the box is empty, and an empty box takes the offer of the species' kind (2 for a
    production species, no check for a cleaner fish), said after saving. Whatever is typed is kept, a 2 for a cleaner
    fish too: the form never has to guess whether a value was typed or only left standing (review R11)."""

    def messages(self, response):
        return [str(message) for message in response.context['messages']]

    def test_the_box_is_empty_on_a_new_species_and_the_form_says_what_empty_means(self):
        form = self.client.get(reverse('farm:species_create'), headers={'X-Modal': '1'})
        self.assertIsNone(form.context['form']['max_weight_ratio'].value())
        self.assertContains(form, 'Left empty on a new species: 2 for a production species, no check for a cleaner fish')

    def test_an_empty_box_on_a_new_cleaner_fish_is_no_check_and_the_person_is_told(self):
        response = self.client.post(reverse('farm:species_create'), species_data(
            **LUMPFISH, cleaner_fish_type='lumpfish', max_weight_ratio=''), follow=True)
        species = Species.objects.get()
        self.assertEqual(stored(species, 'cleaner_fish_type', 'max_weight_ratio'), ('lumpfish', None))
        self.assertIn(NO_CHECK, self.messages(response))
        self.assertNotIn(LABEL, AuditLog.objects.get(entity_id=str(species.pk)).changes)     # nothing stored, nothing said
        self.assertContains(self.client.get(reverse('farm:species_list')), '<td class="nowrap">No check</td>', html=True)

    def test_a_species_the_catalogue_knows_as_a_cleaner_fish_gets_no_check_too(self):
        """The type was not chosen: the catalogue fills it in from the scientific name when the species is saved."""
        response = self.client.post(reverse('farm:species_create'), species_data(**LUMPFISH), follow=True)
        self.assertEqual(stored(Species.objects.get(), 'cleaner_fish_type', 'max_weight_ratio'), ('lumpfish', None))
        self.assertIn(NO_CHECK, self.messages(response))

    def test_a_2_typed_for_a_new_cleaner_fish_is_kept(self):
        """The reviewer's case: a person who wants 2 for a wrasse says so on the create form, and it stands."""
        response = self.client.post(reverse('farm:species_create'), species_data(
            **LUMPFISH, cleaner_fish_type='lumpfish', max_weight_ratio='2'), follow=True)
        species = Species.objects.get()
        self.assertEqual(stored(species, 'max_weight_ratio'), (D('2.00'),))
        self.assertNotIn(NO_CHECK, self.messages(response))
        self.assertEqual(AuditLog.objects.get(entity_id=str(species.pk)).changes[LABEL], [None, '2.00'])
        self.edit(species, **LUMPFISH, cleaner_fish_type='lumpfish', max_weight_ratio='')      # an edit: empty is no check
        self.assertEqual(stored(species, 'max_weight_ratio'), (None,))

    def test_an_empty_box_on_a_new_production_species_is_2_and_the_person_is_told(self):
        response = self.client.post(reverse('farm:species_create'), species_data(max_weight_ratio=''), follow=True)
        species = Species.objects.get()
        self.assertEqual(stored(species, 'max_weight_ratio'), (D('2.00'),))
        self.assertIn(DEFAULT_SET, self.messages(response))
        self.assertEqual(AuditLog.objects.get(entity_id=str(species.pk)).changes[LABEL], [None, '2.00'])
        self.edit(species, max_weight_ratio='')                              # afterwards it can be emptied: no check
        self.assertEqual(stored(species, 'max_weight_ratio'), (None,))
        response = self.client.post(reverse('farm:species_create'), species_data(
            common_name='Rainbow trout', scientific_name='Oncorhynchus mykiss', code='RBT', max_weight_ratio='3'),
            follow=True)
        self.assertEqual(stored(Species.objects.get(code='RBT'), 'max_weight_ratio'), (D('3.00'),))
        self.assertNotIn(DEFAULT_SET, self.messages(response))


class CleanerFishTopUpTests(CleanerFishTestCase):
    """The cage of the cleaner-fish tests: 2,000 salmon of 125 g and 10,000 lumpfish of 50 g. Salmon may be 2 times
    apart. A wrasse is made on the species form as the farm would, the offered size limit left as it stands, and
    stocked beside them."""

    post = DialogTests.post
    input_data = DialogTests.input_data

    def setUp(self):
        super().setUp()
        self.salmon.max_weight_ratio = D(2)
        self.salmon.save()
        self.user.groups.add(role('Species maker', 'view_species', 'add_species'))
        made = self.client.post(reverse('farm:species_create'), species_data(
            common_name='Ballan wrasse', scientific_name='Labrus bergylta', code='USB', freshwater=False, saltwater=True,
            cleaner_fish_type='wrasse', max_weight_ratio=''))
        self.assertEqual(made.status_code, 302, made.context and made.context['form'].errors)
        self.wrasse = Species.objects.get(code='USB')
        self.url = reverse('farm:stock_input')

    def top_up(self, species, weight, days_ago=3):
        return self.post(self.url, self.input_data(
            [(self.cage, 500)], species=str(species.pk), count='500', avg_weight_g=weight,
            provenance='farmed' if species.cleaner_fish_type else '', input_date=self.day(days_ago).isoformat()))

    def test_a_top_up_of_cleaner_fish_of_another_size_asks_nothing_and_shows_no_chip(self):
        self.assertEqual(self.top_up(self.wrasse, '30', days_ago=8).status_code, 204)
        response = self.top_up(self.wrasse, '200')                              # 200 g beside 30 g: over six times as heavy
        self.assertEqual(response.status_code, 204, response.context and response.context['form'].errors)
        operation = StockOperation.objects.get(movements__avg_weight_g=D(200))
        self.assertFalse(operation.size_mix_ack)
        for entry in AuditLog.objects.filter(entity_id=str(operation.pk)):
            self.assertNotIn('Batches of different sizes, accepted', entry.changes)
        self.assertEqual(read.stock_of([self.cage])[self.cage.pk].size_mixes, [])
        for name in ('farm:meal_board', 'farm:production_units'):
            self.assertNotContains(self.client.get(reverse(name)), 'Mixed sizes')

    def test_salmon_of_another_size_still_asks(self):
        before = Batch.all_objects.count()
        response = self.top_up(self.salmon, '400')                              # 400 g beside 125 g
        self.assertEqual(response.status_code, 422)
        self.assertIn('C-01 would hold Atlantic salmon (SAL) of very different sizes',
                      response.context['form'].errors['size_mix_ack'][0])
        self.assertIn(TICK, response.context['form'].errors['size_mix_ack'][0])
        self.assertEqual(Batch.all_objects.count(), before)

    def test_a_limit_the_farm_gives_a_cleaner_fish_is_asked_about(self):
        self.lump.max_weight_ratio = D(2)
        self.lump.save()
        response = self.top_up(self.lump, '200')                                # 200 g beside the 50 g lumpfish
        self.assertEqual(response.status_code, 422)
        self.assertIn('C-01 would hold Lumpfish (LUM) of very different sizes',
                      response.context['form'].errors['size_mix_ack'][0])


class CleanerFishMigrationTests(SpeciesTestCase):
    """farm/0038, run on the rows as they are after 0034 gave every species 2."""

    def run_migration(self, direction='forward'):
        """Runs the migration's step and returns how many species it changed."""
        with connection.schema_editor() as editor:
            return getattr(migration(), direction)(apps, editor)

    def said(self, species):
        return [(entry.user_name, entry.action, entry.entity_label, entry.changes[LABEL])
                for entry in AuditLog.objects.filter(entity_type='species', entity_id=str(species.pk),
                                                     user_name='system').order_by('created_at')]

    def setUp(self):
        super().setUp()
        self.salmon = self.make('Atlantic salmon', 'Salmo salar', 'SAL', max_weight_ratio=D(2))
        self.lump = self.make('Lumpfish', 'Cyclopterus lumpus', 'LUMP', cleaner_fish_type='lumpfish',
                              max_weight_ratio=D(2))
        self.gone = self.make('Ballan wrasse', 'Labrus bergylta', 'USB', cleaner_fish_type='wrasse',
                              max_weight_ratio=D(2))
        self.gone.soft_delete(self.user)
        self.wide = self.make('Goldsinny wrasse', 'Ctenolabrus rupestris', 'GOL', cleaner_fish_type='wrasse',
                              max_weight_ratio=D('2.5'))
        self.chosen = self.make('Corkwing wrasse', 'Symphodus melops', 'COR', cleaner_fish_type='wrasse',
                                max_weight_ratio=D(3))
        self.edit(self.chosen, common_name='Corkwing wrasse', scientific_name='Symphodus melops', code='COR',
                  cleaner_fish_type='wrasse', max_weight_ratio='2')             # a person set 2: theirs, not the default
        self.unchecked = self.make('Cuckoo wrasse', 'Labrus mixtus', 'CUC', cleaner_fish_type='wrasse')
        self.client.post(reverse('farm:species_create'), species_data(
            common_name='Rock cook', scientific_name='Centrolabrus exoletus', code='ROC', freshwater=False,
            saltwater=True, cleaner_fish_type='wrasse', max_weight_ratio='2'))    # 2 from its create form: typed?
        self.typed = Species.objects.get(code='ROC')

    def limits(self):
        return {row.code: row.max_weight_ratio for row in Species.all_objects.all()}

    def test_a_cleaner_fish_still_at_the_untouched_default_loses_it_logged_and_every_other_limit_stays(self):
        self.assertEqual(stored(self.chosen, 'max_weight_ratio'), (D('2.00'),))
        before = AuditLog.objects.count()
        self.assertEqual([species.code for species in migration().sort(apps, connection)[1]], ['ROC'])
        self.assertEqual(self.run_migration(), 2)
        self.assertEqual(self.limits(), {'SAL': D('2.00'), 'LUMP': None, 'USB': None, 'GOL': D('2.50'),
                                         'COR': D('2.00'), 'CUC': None, 'ROC': D('2.00')})
        # a 2 that came with the species' own creation may have been typed: it is left, and reported
        self.assertEqual(self.said(self.typed), [])
        self.assertEqual(self.said(self.lump), [('system', 'update', 'Lumpfish (LUMP)', ['2.00', None])])
        self.assertEqual(self.said(self.gone), [('system', 'update', 'Ballan wrasse (USB)', ['2.00', None])])
        self.assertEqual(AuditLog.objects.count(), before + 2)                  # the two it changed, nothing else
        for species in (self.salmon, self.wide, self.chosen, self.unchecked):
            self.assertEqual(self.said(species), [])
        self.assertEqual(self.run_migration(), 0)                               # again: nothing left to change or say
        self.assertEqual(AuditLog.objects.count(), before + 2)

    def test_going_back_gives_2_back_only_where_it_took_it_and_nobody_chose_since(self):
        self.run_migration()
        self.edit(self.lump, common_name='Lumpfish',
                  scientific_name='Cyclopterus lumpus', code='LUMP', cleaner_fish_type='lumpfish',
                  max_weight_ratio='4')                                          # a person gave a limit, then took it away
        self.edit(self.lump, common_name='Lumpfish', scientific_name='Cyclopterus lumpus', code='LUMP',
                  cleaner_fish_type='lumpfish', max_weight_ratio='')
        self.assertEqual(self.run_migration('backward'), 1)
        self.assertEqual(self.limits(), {'SAL': D('2.00'), 'LUMP': None, 'USB': D('2.00'), 'GOL': D('2.50'),
                                         'COR': D('2.00'), 'CUC': None, 'ROC': D('2.00')})         # CUC never had one: not invented
        self.assertEqual(self.said(self.gone)[-1], ('system', 'update', 'Ballan wrasse (USB)', [None, '2.00']))
        self.assertEqual(len(self.said(self.lump)), 1)                           # only the forward's row
        self.run_migration()                                                     # forward again: the wrasse again
        self.assertIsNone(self.limits()['USB'])

    def test_the_migration_and_the_form_agree_on_the_default_and_the_log_label(self):
        from ..forms.species import OFFERED_WEIGHT_RATIO
        self.assertEqual(migration().DEFAULT, OFFERED_WEIGHT_RATIO)
        self.assertEqual(migration().LABEL, str(Species._meta.get_field('max_weight_ratio').verbose_name))
        self.assertEqual(migration().LABEL, LABEL)

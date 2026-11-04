import re
from decimal import Decimal
from itertools import product
from string import ascii_lowercase

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import translation

from core import database, navigation, softdelete
from core.audit import message
from core.models import AuditLog, Profile
from core.softdelete import plan_delete

from .. import species_catalog
from ..models import Species
from ..models.species import SCIENTIFIC_NAME, normalise_scientific_name
from ..resources import SpeciesResource
from .helpers import role

SPECIES_MANAGER = ('view_species', 'add_species', 'change_species', 'delete_species', 'view_auditlog')
WATERS = Species.WATER_FIELDS


def species_data(**overrides):
    """What the species dialog posts. A water flag or any check box is given as True/False."""
    data = {
        'common_name': 'Nile tilapia', 'local_name': '', 'scientific_name': 'Oreochromis niloticus', 'code': 'tln',
        'description': '', 'category': 'fish', 'family': '', 'freshwater': True, 'brackish': False,
        'saltwater': False, 'official_code': '', 'cleaner_fish_type': '', 'withdrawal_temperature_c': '',
        'status': 'active', 'notes': '',
    }
    data.update(overrides)
    return {key: 'on' if value is True else value for key, value in data.items() if value is not False}


def stored(species, *names):
    species.refresh_from_db()
    return tuple(getattr(species, name) for name in names)


class SpeciesTestCase(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('ali', 'ali@example.com', 'eski-sifre-123')
        self.user.groups.add(role('Species manager', *SPECIES_MANAGER))
        self.client.force_login(self.user)

    def make(self, common_name='Nile tilapia', scientific_name='Oreochromis niloticus', code='TLN', **fields):
        fields.setdefault('freshwater', True)
        return Species.objects.create(common_name=common_name, scientific_name=scientific_name, code=code, **fields)

    def create(self, **overrides):
        return self.client.post(reverse('farm:species_create'), species_data(**overrides))

    def edit(self, species, **overrides):
        overrides.setdefault('version', str(Species.all_objects.get(pk=species.pk).version))
        return self.client.post(reverse('farm:species_edit', args=[species.pk]), species_data(**overrides))

    def errors(self, response):
        return response.context['form'].errors


class SpeciesRoundTripTests(SpeciesTestCase):
    def test_create_read_edit_delete(self):
        # Create: every field typed (a species the catalogue does not know, so nothing is filled in)
        self.create(common_name=' Nile tilapia ', local_name='Tilapia', scientific_name='  oreochromis  NILOTICUS ',
                    code=' tln-1 ', description='Warm-water cichlid', category='fish', family='Cichlidae',
                    freshwater=True, brackish=True, official_code=' tln ', cleaner_fish_type='',
                    withdrawal_temperature_c='8.5', status='experimental', notes='Trial in RAS 2')
        species = Species.objects.get()
        self.assertEqual(
            stored(species, 'common_name', 'local_name', 'scientific_name', 'code', 'description', 'category', 'family',
                   'freshwater', 'brackish', 'saltwater', 'official_code', 'cleaner_fish_type',
                   'withdrawal_temperature_c', 'status', 'notes', 'created_by', 'version'),
            ('Nile tilapia', 'Tilapia', 'Oreochromis niloticus', 'TLN-1', 'Warm-water cichlid', 'fish', 'Cichlidae',
             True, True, False, 'TLN', '', Decimal('8.5'), 'experimental', 'Trial in RAS 2', self.user, 1))

        # Read: listed, and the edit form is filled from the database
        self.assertEqual(list(self.client.get(reverse('farm:species_list')).context['objects']), [species])
        form = self.client.get(reverse('farm:species_edit', args=[species.pk])).context['form']
        self.assertEqual(
            {name: form[name].value() for name in (
                'common_name', 'local_name', 'scientific_name', 'code', 'description', 'family', 'freshwater',
                'brackish', 'saltwater', 'official_code', 'cleaner_fish_type', 'withdrawal_temperature_c', 'status',
                'notes', 'version')},
            {'common_name': 'Nile tilapia', 'local_name': 'Tilapia', 'scientific_name': 'Oreochromis niloticus',
             'code': 'TLN-1', 'description': 'Warm-water cichlid', 'family': 'Cichlidae', 'freshwater': True,
             'brackish': True, 'saltwater': False, 'official_code': 'TLN', 'cleaner_fish_type': '',
             'withdrawal_temperature_c': Decimal('8.5'), 'status': 'experimental', 'notes': 'Trial in RAS 2',
             'version': 1})

        # Edit: every field changed
        self.edit(species, common_name='Tilapia', local_name='Tilapiya', scientific_name='Oreochromis aureus',
                  code='TLA', description='Blue tilapia', category='other', family='Cichlids', freshwater=False,
                  brackish=False, saltwater=True, official_code='TLP', cleaner_fish_type='wrasse',
                  withdrawal_temperature_c='12', status='inactive', notes='Moved to sea')
        self.assertEqual(
            stored(species, 'common_name', 'local_name', 'scientific_name', 'code', 'description', 'category', 'family',
                   'freshwater', 'brackish', 'saltwater', 'official_code', 'cleaner_fish_type',
                   'withdrawal_temperature_c', 'status', 'notes', 'updated_by', 'version'),
            ('Tilapia', 'Tilapiya', 'Oreochromis aureus', 'TLA', 'Blue tilapia', 'other', 'Cichlids', False, False,
             True, 'TLP', 'wrasse', Decimal('12.0'), 'inactive', 'Moved to sea', self.user, 2))

        # Delete: hidden, not erased
        self.client.post(reverse('farm:species_delete', args=[species.pk]))
        self.assertFalse(Species.objects.exists())
        self.assertEqual(stored(Species.all_objects.get(), 'is_deleted', 'deleted_by'), (True, self.user))
        self.assertEqual(list(self.client.get(reverse('farm:species_list')).context['objects']), [])

    def test_every_optional_field_can_be_cleared_when_editing(self):
        # A species of the catalogue: an edit that keeps its name fills nothing back in.
        salmon = self.make('Atlantic salmon', 'Salmo salar', 'SAL', local_name='Laks', description='Grow-out',
                           family='Salmonidae', saltwater=True, official_code='SAL', cleaner_fish_type='lumpfish',
                           withdrawal_temperature_c=Decimal('8.5'), notes='Main species')
        self.edit(salmon, common_name='Atlantic salmon', scientific_name='Salmo salar', code='SAL', saltwater=True)
        self.assertEqual(
            stored(salmon, 'local_name', 'description', 'family', 'official_code', 'cleaner_fish_type',
                   'withdrawal_temperature_c', 'notes', 'freshwater', 'saltwater'),
            ('', '', '', '', '', None, '', True, True))
        self.assertEqual(AuditLog.objects.get().changes, {
            'Local name': ['Laks', None], 'Description': ['Grow-out', None], 'Family': ['Salmonidae', None],
            'Official code': ['SAL', None], 'Cleaner fish': [message('Lumpfish'), None],
            'Assumed water temperature for withdrawal (°C)': ['8.5', None], 'Notes': ['Main species', None],
        })

    def test_the_form_opens_in_the_dialog_with_its_tabs(self):
        response = self.client.get(reverse('farm:species_create'), headers={'X-Modal': '1'})
        self.assertContains(response, 'class="modal-head"')
        self.assertNotContains(response, 'id="rail"')
        for key, label in (('basic', 'Basic info'), ('classification', 'Classification'),
                           ('regulatory', 'Regulatory'), ('status', 'Status and notes')):
            self.assertContains(response, f'data-tab="{key}">{label}</button>')
        self.assertContains(response, '<legend>Water environment</legend>', html=True)
        self.assertContains(response, '<legend>Medicine withdrawal</legend>', html=True)
        self.assertContains(response, 'Assumed water temperature for withdrawal (°C)')
        self.assertContains(response, 'a low value is the conservative choice')
        self.assertNotContains(response, 'Genus:')
        # On the Regulatory tab, under the official code and the cleaner-fish type.
        form = response.context['form']
        regulatory = next(tab for tab in form.tabs if tab[0] == 'regulatory')
        self.assertEqual([getattr(item, 'names', item) for item in regulatory[2]],
                         ['official_code', 'cleaner_fish_type', ['withdrawal_temperature_c']])

    def test_the_genus_is_shown_on_the_edit_form_and_follows_the_scientific_name(self):
        species = self.make()
        self.assertContains(self.client.get(reverse('farm:species_edit', args=[species.pk])),
                            'Genus: Oreochromis (the first word of the scientific name).')
        self.assertEqual(species.genus, 'Oreochromis')
        self.assertFalse(any(field.name == 'genus' for field in Species._meta.fields))

    def test_an_edit_based_on_an_old_version_is_refused(self):
        species = self.make()
        self.edit(species, common_name='First', version='1')
        response = self.edit(species, common_name='Second', version='1')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(stored(species, 'common_name', 'version'), ('First', 2))


class SpeciesValidationTests(SpeciesTestCase):
    def test_names_and_code_are_required(self):
        errors = self.errors(self.create(common_name='', scientific_name='', code=''))
        self.assertEqual(set(errors), {'common_name', 'scientific_name', 'code'})
        self.assertFalse(Species.objects.exists())

    def test_the_scientific_name_is_normalised(self):
        self.assertEqual(normalise_scientific_name('  salmo   SALAR '), 'Salmo salar')
        self.create(scientific_name='oncorhynchus MYKISS   irideus', code='RBT')
        self.assertEqual(Species.objects.get().scientific_name, 'Oncorhynchus mykiss irideus')
        species = Species.objects.get()
        species.scientific_name = 'gadus  MORHUA'
        species.save()     # however it is written
        self.assertEqual(stored(species, 'scientific_name'), ('Gadus morhua',))

    def test_the_scientific_name_must_be_a_binomial(self):
        for name in ('Salmo', 'Labrus sp.', 'Labrus spp.', 'Salmo salar x', 'Salmo salär', 'Salmo 2salar',
                     'Salmo salar trutta extra'):
            with self.subTest(name=name):
                self.assertEqual(self.errors(self.create(scientific_name=name))['scientific_name'], [
                    'Write the genus and the species in Latin letters, e.g. Salmo salar; a subspecies may follow '
                    'as a third word.'])
        self.assertFalse(Species.objects.exists())
        species = self.make()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Species.objects.filter(pk=species.pk).update(scientific_name='Labrus sp.')

    def test_the_code_is_upper_case_letters_digits_hyphens_and_underscores_of_at_least_two(self):
        self.assertEqual(self.errors(self.create(code='TL N'))['code'],
                         ['Use capital letters, digits, hyphens and underscores only.'])
        self.assertEqual(self.errors(self.create(code='TLÅ'))['code'],
                         ['Use capital letters, digits, hyphens and underscores only.'])
        self.assertEqual(self.errors(self.create(code='T'))['code'], ['Code must be at least 2 characters.'])
        self.create(code='tl_n-2')
        self.assertEqual(Species.objects.get().code, 'TL_N-2')
        with self.assertRaises(IntegrityError), transaction.atomic():
            Species.objects.update(code='tln')

    def test_the_code_is_unique_among_live_species(self):
        self.make(code='TLN')
        response = self.create(common_name='Other', scientific_name='Oreochromis aureus', code='tln')
        self.assertEqual(self.errors(response)['code'], ['Another species already uses this code.'])
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make(scientific_name='Oreochromis aureus', code='TLN')
        Species.objects.get().soft_delete(self.user)
        self.create(common_name='Other', scientific_name='Oreochromis aureus', code='tln')
        self.assertEqual(Species.objects.get().code, 'TLN')

    def test_the_scientific_name_is_unique_among_live_species_whatever_its_case(self):
        species = self.make()
        response = self.create(common_name='Other', scientific_name='OREOCHROMIS niloticus', code='OTH')
        self.assertEqual(self.errors(response)['scientific_name'],
                         ['Another species already has this scientific name.'])
        # The database refuses it too.
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make(scientific_name='Oreochromis niloticus', code='OTH')
        # Editing a species keeps its own name; a deleted species frees it.
        self.edit(species, common_name='Renamed', code='TLN', scientific_name='Oreochromis niloticus')
        self.assertEqual(stored(species, 'common_name'), ('Renamed',))
        species.soft_delete(self.user)
        self.create(common_name='Other', scientific_name='oreochromis niloticus', code='OTH')
        self.assertEqual(Species.objects.get().code, 'OTH')

    def test_the_official_code_is_three_capital_letters_or_empty(self):
        for code in ('SA', 'SA1', 'SALM', 'S-L'):
            with self.subTest(code=code):
                self.assertIn('official_code', self.errors(self.create(official_code=code)))
        self.assertEqual(self.errors(self.create(official_code='S1L'))['official_code'],
                         ['The official code is three capital letters, e.g. SAL.'])
        self.create(official_code=' tln ')
        species = Species.objects.get()
        self.assertEqual(species.official_code, 'TLN')
        for code in ('tln', 'TL1', 'T'):
            with self.subTest(database=code), self.assertRaises(IntegrityError), transaction.atomic():
                Species.objects.filter(pk=species.pk).update(official_code=code)
        Species.objects.filter(pk=species.pk).update(official_code='')

    def test_the_assumed_withdrawal_temperature_is_between_0_and_40_or_empty(self):
        for value in ('41', '-1', '40.1', 'abc', '8.55'):
            with self.subTest(value=value):
                self.assertIn('withdrawal_temperature_c', self.errors(self.create(withdrawal_temperature_c=value)))
        self.assertFalse(Species.objects.exists())
        for value, expected in (('0', Decimal('0.0')), ('40', Decimal('40.0')), ('', None)):
            with self.subTest(value=value):
                Species.objects.all().delete()
                self.create(withdrawal_temperature_c=value)
                self.assertEqual(Species.objects.get().withdrawal_temperature_c, expected)
        Profile.objects.create(user=self.user, language='nb')
        Species.objects.all().delete()
        self.create(withdrawal_temperature_c='8,5')            # typed the way the language writes it
        self.assertEqual(Species.objects.get().withdrawal_temperature_c, Decimal('8.5'))

    def test_the_assumed_withdrawal_temperature_is_a_database_check(self):
        species = self.make()
        for value in (Decimal('41'), Decimal('-1'), Decimal('40.1')):
            with self.subTest(database=value), self.assertRaises(IntegrityError), transaction.atomic():
                Species.objects.filter(pk=species.pk).update(withdrawal_temperature_c=value)
        for value in (Decimal('0'), Decimal('40'), None):         # the bounds are in, empty is allowed
            Species.objects.filter(pk=species.pk).update(withdrawal_temperature_c=value)
        self.assertIsNone(stored(species, 'withdrawal_temperature_c')[0])
        with self.assertRaises(ValidationError):
            Species(common_name='Blue tilapia', scientific_name='Oreochromis aureus', code='TLA', freshwater=True,
                    withdrawal_temperature_c=Decimal('41')).full_clean()

    def test_the_assumed_withdrawal_temperature_is_in_turkish_and_norwegian(self):
        self.addCleanup(translation.activate, 'en')
        species = self.make(withdrawal_temperature_c=Decimal('8.5'))
        for language, label, value, legend in (
                ('tr', 'Bekleme süresi için varsayılan su sıcaklığı (°C)', '8,5', 'İlaç bekleme süresi'),
                ('nb', 'Antatt vanntemperatur for tilbakeholdelsestid (°C)', '8,5', 'Tilbakeholdelsestid')):
            Profile.objects.update_or_create(user=self.user, defaults={'language': language})
            page = self.client.get(reverse('farm:species_edit', args=[species.pk]))
            self.assertContains(page, label, msg_prefix=language)
            self.assertContains(page, f'<legend>{legend}</legend>', html=True, msg_prefix=language)
            self.assertContains(page, f'value="{value}"', msg_prefix=language)
            self.assertNotContains(page, 'Assumed water temperature', msg_prefix=language)
            self.assertNotContains(page, 'a low value is the conservative choice', msg_prefix=language)

    def test_the_official_code_is_not_unique(self):
        self.make(code='TLN', official_code='TLN')
        self.create(common_name='Tilapia hybrid', scientific_name='Oreochromis aureus', code='TLH', official_code='TLN')
        self.assertEqual(Species.objects.filter(official_code='TLN').count(), 2)

    def test_at_least_one_water_environment(self):
        response = self.create(freshwater=False)
        self.assertEqual(self.errors(response)['freshwater'], ['Tick at least one water environment.'])
        self.assertContains(response, 'tab-error')
        species = self.make()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Species.objects.filter(pk=species.pk).update(freshwater=False)
        for water in WATERS:
            with self.subTest(water=water):
                self.edit(species, **{name: name == water for name in WATERS})
                self.assertEqual(stored(species, *WATERS), tuple(name == water for name in WATERS))

    def test_category_status_and_cleaner_fish_type_are_their_choices(self):
        for field in ('category', 'status', 'cleaner_fish_type'):
            with self.subTest(field=field):
                self.assertIn(field, self.errors(self.create(**{field: 'whale'})))
        species = self.make()
        for field in ('category', 'status', 'cleaner_fish_type'):
            with self.subTest(database=field), self.assertRaises(IntegrityError), transaction.atomic():
                Species.objects.filter(pk=species.pk).update(**{field: 'whale'})
        for status in ('active', 'inactive', 'experimental', 'discontinued'):
            self.edit(species, status=status)
            self.assertEqual(stored(species, 'status'), (status,))
        for category in ('fish', 'shrimp', 'prawn', 'crab', 'lobster', 'mollusk', 'seaweed', 'other'):
            self.edit(species, category=category)
            self.assertEqual(stored(species, 'category'), (category,))
        for kind in ('lumpfish', 'wrasse', ''):
            self.edit(species, cleaner_fish_type=kind)
            self.assertEqual(stored(species, 'cleaner_fish_type', 'is_cleaner_fish'), (kind, bool(kind)))

    def test_a_catalogue_species_keeps_its_verified_official_code(self):
        response = self.create(common_name='Atlantic salmon', scientific_name='Salmo salar', code='SAL',
                               official_code='TRR')
        self.assertEqual(self.errors(response)['official_code'], ['The official code of Salmo salar is SAL.'])
        # A cleaner fish's too: the source sent USB for the lumpfish, which is the ballan wrasse in ASFIS (REP-51).
        response = self.create(common_name='Lumpfish', scientific_name='Cyclopterus lumpus', code='LUMP',
                               official_code='USB')
        self.assertEqual(self.errors(response)['official_code'], ['The official code of Cyclopterus lumpus is LUM.'])
        self.create(common_name='Lumpfish', scientific_name='Cyclopterus lumpus', code='LUMP', official_code='LUM')
        self.assertEqual(Species.objects.get().official_code, 'LUM')

    def test_lengths_are_the_columns(self):
        errors = self.errors(self.create(common_name='x' * 101, local_name='x' * 101, family='x' * 101,
                                         code='X' * 21, description='x' * 1001, notes='x' * 2001))
        self.assertEqual(set(errors), {'common_name', 'local_name', 'family', 'code', 'description', 'notes'})


class SpeciesCatalogueTests(SpeciesTestCase):
    def messages(self, response):
        return [str(m) for m in response.context['messages']]

    def test_blank_fields_are_filled_in_and_the_message_says_what(self):
        response = self.client.post(reverse('farm:species_create'), species_data(
            common_name='Atlantic salmon', scientific_name='salmo salar', code='sal', freshwater=False), follow=True)
        species = Species.objects.get()
        self.assertEqual(
            stored(species, 'local_name', 'family', 'freshwater', 'brackish', 'saltwater', 'official_code',
                   'cleaner_fish_type'),
            ('Laks', 'Salmonidae', True, False, True, 'SAL', ''))
        self.assertIn('Filled in from the species catalogue: Local name: Laks; Family: Salmonidae; Water environment: '
                      'Fresh water, Sea water; Official code: SAL.', self.messages(response))
        # What was filled is in the activity log like any value.
        changes = AuditLog.objects.get().changes
        self.assertEqual((changes['Local name'], changes['Family'], changes['Sea water'], changes['Official code']),
                         ([None, 'Laks'], [None, 'Salmonidae'], [None, message('Yes')], [None, 'SAL']))

    def test_typed_values_are_never_replaced(self):
        response = self.client.post(reverse('farm:species_create'), species_data(
            common_name='Atlantic salmon', scientific_name='Salmo salar', code='SAL', local_name='Atlantisk laks',
            family='Salmonids', freshwater=False, brackish=True, official_code='SAL'), follow=True)
        self.assertEqual(stored(Species.objects.get(), 'local_name', 'family', 'freshwater', 'brackish', 'saltwater'),
                         ('Atlantisk laks', 'Salmonids', False, True, False))
        self.assertFalse(any('catalogue' in text for text in self.messages(response)))

    def test_a_cleaner_fish_gets_its_asfis_code_and_its_type(self):
        response = self.client.post(reverse('farm:species_create'), species_data(
            common_name='Lumpfish', scientific_name='Cyclopterus lumpus', code='LUMP', freshwater=False), follow=True)
        self.assertEqual(stored(Species.objects.get(), 'local_name', 'family', 'saltwater', 'official_code',
                                'cleaner_fish_type'),
                         ('Rognkjeks', 'Cyclopteridae', True, 'LUM', 'lumpfish'))
        self.assertIn('Filled in from the species catalogue: Local name: Rognkjeks; Family: Cyclopteridae; Water '
                      'environment: Sea water; Official code: LUM; Cleaner fish: Lumpfish.', self.messages(response))

    def test_renaming_to_a_catalogue_species_fills_its_blank_fields_and_keeps_the_waters_ticked(self):
        species = self.make()
        self.edit(species, common_name='Atlantic cod', scientific_name='Gadus morhua', code='COD')
        self.assertEqual(stored(species, 'local_name', 'family', 'official_code', 'freshwater', 'saltwater'),
                         ('Torsk', 'Gadidae', 'COD', True, False))

    def test_an_unknown_species_without_water_is_refused_and_nothing_is_filled(self):
        response = self.create(freshwater=False)
        self.assertIn('freshwater', self.errors(response))
        self.assertFalse(Species.objects.exists())

    def test_the_catalogue_is_consistent_with_the_model(self):
        self.assertEqual(len(species_catalog.CATALOGUE), 14)
        self.assertTrue(all(entry.official_code_verified for entry in species_catalog.CATALOGUE))
        # The cleaner fish's FAO ASFIS codes (docs/regulatory-reports.md, 3.4).
        self.assertEqual({entry.scientific_name: entry.official_code for entry in species_catalog.CATALOGUE
                          if entry.cleaner_fish_type},
                         {'Cyclopterus lumpus': 'LUM', 'Labrus bergylta': 'USB', 'Symphodus melops': 'YFM',
                          'Ctenolabrus rupestris': 'TBR', 'Centrolabrus exoletus': 'ENX'})
        codes = [entry.official_code for entry in species_catalog.CATALOGUE]
        self.assertEqual(len(codes), len(set(codes)))
        for entry in species_catalog.CATALOGUE:
            with self.subTest(entry=entry.scientific_name):
                self.assertTrue(re.match(SCIENTIFIC_NAME, entry.scientific_name))
                self.assertEqual(normalise_scientific_name(entry.scientific_name), entry.scientific_name)
                self.assertRegex(entry.official_code, r'^[A-Z]{3}$')
                self.assertIn(entry.cleaner_fish_type, Species.CleanerFishType.values)
                self.assertTrue(any(getattr(entry, name) for name in WATERS))
                self.assertIs(species_catalog.find(f'  {entry.scientific_name.upper()} '), entry)
        self.assertIsNone(species_catalog.find('Oreochromis niloticus'))


class SpeciesListTests(SpeciesTestCase):
    def setUp(self):
        super().setUp()
        self.salmon = self.make('Atlantic salmon', 'Salmo salar', 'SAL', local_name='Laks', family='Salmonidae',
                                saltwater=True, official_code='SAL')
        self.lumpfish = self.make('Lumpfish', 'Cyclopterus lumpus', 'LUMP', local_name='Rognkjeks', freshwater=False,
                                  saltwater=True, cleaner_fish_type='lumpfish', status='experimental')
        self.wrasse = self.make('Ballan wrasse', 'Labrus bergylta', 'BW', freshwater=False, saltwater=True,
                                cleaner_fish_type='wrasse', status='discontinued')
        self.shrimp = self.make('Whiteleg shrimp', 'Penaeus vannamei', 'PV', freshwater=False, brackish=True,
                                category='shrimp')

    def codes(self, **query):
        return [s.code for s in self.client.get(reverse('farm:species_list'), query).context['objects']]

    def test_listed_by_common_name(self):
        self.assertEqual(self.codes(), ['SAL', 'BW', 'LUMP', 'PV'])

    def test_columns_show_labels_and_the_missing_official_code(self):
        response = self.client.get(reverse('farm:species_list'))
        self.assertContains(response, '<i>Salmo salar</i>', html=True)
        self.assertContains(response, 'Salmonidae · <i>Salmo</i>')
        self.assertContains(response, '<span class="row-sub">Laks</span>', html=True)
        self.assertContains(response, '<td>Fresh water, Sea water</td>', html=True)
        self.assertContains(response, '<td>Brackish water</td>', html=True)
        self.assertContains(response, '<td>Lumpfish</td>', html=True)
        self.assertContains(response, '<td>Shrimp</td>', html=True)
        self.assertContains(response, '<span class="badge badge-experimental">Experimental</span>', html=True)
        self.assertContains(response, '<span class="badge badge-discontinued">Discontinued</span>', html=True)
        self.assertEqual(response.content.decode().count('>Missing</span>'), 3)

    def test_search_covers_names_codes_and_the_official_code(self):
        self.assertEqual(self.codes(q='laks'), ['SAL'])
        self.assertEqual(self.codes(q='rognkjeks'), ['LUMP'])
        self.assertEqual(self.codes(q='bergylta'), ['BW'])
        self.assertEqual(self.codes(q='pv'), ['PV'])
        Species.objects.filter(pk=self.shrimp.pk).update(official_code='PNV')
        self.assertEqual(self.codes(q='pnv'), ['PV'])
        self.assertEqual(self.codes(q='whiteleg'), ['PV'])

    def test_filters(self):
        self.assertEqual(self.codes(category='shrimp'), ['PV'])
        self.assertEqual(self.codes(status='experimental'), ['LUMP'])
        self.assertEqual(self.codes(water='freshwater'), ['SAL'])
        self.assertEqual(self.codes(water='brackish'), ['PV'])
        self.assertEqual(self.codes(water='saltwater'), ['SAL', 'BW', 'LUMP'])
        self.assertEqual(self.codes(cleaner_fish='any'), ['BW', 'LUMP'])
        self.assertEqual(self.codes(cleaner_fish='wrasse'), ['BW'])
        self.assertEqual(self.codes(cleaner_fish='none'), ['SAL', 'PV'])
        self.assertEqual(self.codes(cleaner_fish='any', water='saltwater', q='lump'), ['LUMP'])
        self.assertEqual(len(self.codes(category='whale', status='x', water='lava', cleaner_fish='shark')), 4)

    def test_the_list_is_paged_and_the_pages_keep_the_search_and_filters(self):
        names = [''.join(pair) for pair in product(ascii_lowercase, repeat=2)][:60]
        Species.objects.bulk_create([
            Species(common_name=f'Test {name}', scientific_name=f'Testus {name}', code=f'T-{name.upper()}',
                    category='crab', saltwater=True) for name in names])
        first = self.client.get(reverse('farm:species_list'), {'category': 'crab'})
        self.assertEqual(len(first.context['objects']), 50)
        self.assertContains(first, '1–50 of 60')
        self.assertContains(first, 'Page 1 of 2')
        self.assertContains(first, '?category=crab&amp;page=2')
        second = self.client.get(reverse('farm:species_list'), {'category': 'crab', 'page': '2'})
        self.assertEqual([s.code for s in second.context['objects']], [f'T-{name.upper()}' for name in names[50:]])
        self.assertContains(second, '51–60 of 60')
        self.assertEqual(len(self.client.get(reverse('farm:species_list'), {'page': 'x'}).context['objects']), 50)
        self.assertNotContains(self.client.get(reverse('farm:species_list'), {'category': 'fish'}), 'Page 1 of')

    def test_the_empty_list_invites_to_add_one(self):
        Species.objects.all().delete()
        response = self.client.get(reverse('farm:species_list'))
        self.assertContains(response, 'No species yet')
        self.assertContains(response, 'Add species')


class SpeciesDeleteAndRestoreTests(SpeciesTestCase):
    def test_nothing_points_at_a_species_so_it_deletes_plainly_and_is_logged(self):
        species = self.make()
        plan = plan_delete(species)
        self.assertTrue(plan.can_delete)
        self.assertEqual((plan.cascade, plan.detach, plan.unlinked), ([], [], []))
        page = self.client.get(reverse('farm:species_delete', args=[species.pk]))
        self.assertContains(page, 'Delete “Nile tilapia (TLN)”?')
        self.assertContains(page, 'restored from the admin')
        self.client.post(reverse('farm:species_delete', args=[species.pk]))
        self.assertEqual(list(AuditLog.objects.values_list('action', 'entity_type', 'entity_label')),
                         [('delete', 'species', 'Nile tilapia (TLN)')])

    def test_a_deleted_species_cannot_be_edited_or_deleted_again(self):
        species = self.make()
        species.soft_delete(self.user)
        for url in (reverse('farm:species_edit', args=[species.pk]), reverse('farm:species_delete', args=[species.pk])):
            self.assertEqual(self.client.get(url).status_code, 404, url)
            self.assertEqual(self.client.post(url, species_data()).status_code, 404, url)

    def test_restore_brings_it_back_unless_its_name_or_code_was_taken_meanwhile(self):
        species = self.make()
        species.soft_delete(self.user)
        other = self.make('Tilapia', 'Oreochromis niloticus', 'OTHER')
        with self.assertRaisesMessage(ValidationError, 'Another species already has this scientific name.'):
            softdelete.restore(Species.all_objects.get(pk=species.pk), self.user)
        other.soft_delete(self.user)
        self.make('Blue tilapia', 'Oreochromis aureus', 'TLN')
        with self.assertRaisesMessage(ValidationError, 'Another species already uses this code.'):
            softdelete.restore(Species.all_objects.get(pk=species.pk), self.user)
        Species.objects.filter(code='TLN').update(code='TLA')
        softdelete.restore(Species.all_objects.get(pk=species.pk), self.user)
        self.assertEqual(stored(species, 'is_deleted', 'version'), (False, 3))
        self.assertEqual(AuditLog.objects.get(action='restore').entity_label, 'Nile tilapia (TLN)')

    def test_the_admin_lists_deleted_species_and_restores_them(self):
        root = get_user_model().objects.create_superuser('root', 'root@example.com', 'x')
        self.client.force_login(root)
        species = self.make()
        species.soft_delete(root)
        self.assertIn(Species, admin.site._registry)
        self.assertEqual(admin.site._registry[Species].list_display, ['common_name', 'code', 'status', 'is_deleted'])
        page = self.client.get(reverse('admin:farm_species_changelist'), {'q': 'tilapia'})
        self.assertContains(page, 'Nile tilapia')
        self.assertNotContains(page, reverse('admin:farm_species_add'))
        self.make('Tilapia', 'Oreochromis niloticus', 'OTHER')
        response = self.client.post(reverse('admin:farm_species_changelist'),
                                    {'action': 'restore', '_selected_action': [str(species.pk)]}, follow=True)
        self.assertContains(response, 'was not restored: Another species already has this scientific name.')
        Species.objects.get(code='OTHER').soft_delete(root)
        response = self.client.post(reverse('admin:farm_species_changelist'),
                                    {'action': 'restore', '_selected_action': [str(species.pk)]}, follow=True)
        self.assertContains(response, '1 record restored.')
        self.assertTrue(Species.objects.filter(pk=species.pk).exists())


class SpeciesAuditTests(SpeciesTestCase):
    def test_create_edit_and_delete_are_logged_with_old_and_new_values(self):
        self.create(local_name='Tilapia', official_code='TLN')
        species = Species.objects.get()
        self.edit(species, local_name='Tilapia', official_code='TLN', status='discontinued', brackish=True,
                  cleaner_fish_type='wrasse')
        self.client.post(reverse('farm:species_delete', args=[species.pk]))
        created, edited, deleted = AuditLog.objects.order_by('created_at')
        self.assertEqual((created.action, created.entity_type, created.entity_label),
                         ('create', 'species', 'Nile tilapia (TLN)'))
        self.assertEqual(created.changes, {
            'Common name': [None, 'Nile tilapia'], 'Local name': [None, 'Tilapia'],
            'Scientific name': [None, 'Oreochromis niloticus'], 'Code': [None, 'TLN'],
            'Category': [None, message('Fish')], 'Fresh water': [None, message('Yes')],
            'Brackish water': [None, message('No')], 'Sea water': [None, message('No')],
            'Official code': [None, 'TLN'], 'Status': [None, message('Active')],
        })
        self.assertEqual(edited.changes, {
            'Brackish water': [message('No'), message('Yes')],
            'Cleaner fish': [None, message('Wrasse')],
            'Status': [message('Active'), message('Discontinued')],
        })
        self.assertEqual((deleted.action, deleted.entity_type), ('delete', 'species'))

    def test_the_log_is_english_whatever_the_language(self):
        Profile.objects.create(user=self.user, language='tr')
        response = self.client.post(reverse('farm:species_create'), species_data(
            common_name='Atlantic salmon', scientific_name='Salmo salar', code='SAL', freshwater=False), follow=True)
        self.assertContains(response, 'Balık türü kataloğundan dolduruldu: Yerel ad: Laks; Familya: Salmonidae; Su ortamı: '
                                       'Tatlı su, Deniz suyu; Resmî tür kodu: SAL.')
        entry = AuditLog.objects.get()
        self.assertEqual(entry.entity_type, 'species')
        self.assertEqual(entry.changes['Category'], [None, message('Fish')])
        self.assertEqual(entry.changes['Fresh water'], [None, message('Yes')])
        with translation.override('tr'):
            self.assertEqual(entry.shown_type(), 'balık türü')

    def test_the_history_tab_shows_the_changes(self):
        self.create()
        species = Species.objects.get()
        self.assertEqual(len(self.client.get(reverse('farm:species_edit', args=[species.pk])).context['history']), 1)


class SpeciesPermissionTests(SpeciesTestCase):
    def as_role(self, *codenames):
        person = get_user_model().objects.create_user(f'user{len(codenames)}', 'x@example.com', 'x')
        person.groups.add(role(f'Role {len(codenames)}', *codenames))
        self.client.force_login(person)

    def test_a_read_only_role_sees_species_but_cannot_change_them(self):
        species = self.make()
        self.as_role('view_species')
        response = self.client.get(reverse('farm:species_list'))
        self.assertContains(response, 'Nile tilapia')
        for url in (reverse('farm:species_create'), reverse('farm:species_edit', args=[species.pk]),
                    reverse('farm:species_delete', args=[species.pk])):
            self.assertNotContains(response, url)
            self.assertEqual(self.client.post(url, species_data()).status_code, 403, url)
        self.assertEqual(stored(species, 'is_deleted', 'version'), (False, 1))

    def test_each_action_needs_its_own_permission(self):
        species = self.make()
        self.as_role('view_species', 'add_species')
        self.create(common_name='Other', scientific_name='Oreochromis aureus', code='OTH')
        self.assertTrue(Species.objects.filter(code='OTH').exists())
        self.assertEqual(self.edit(species, common_name='Changed').status_code, 403)
        self.as_role('view_species', 'change_species', 'delete_species')
        self.assertEqual(self.create(code='NEW').status_code, 403)
        self.edit(species, common_name='Changed')
        self.assertEqual(stored(species, 'common_name'), ('Changed',))
        self.client.post(reverse('farm:species_delete', args=[species.pk]))
        self.assertTrue(Species.all_objects.get(pk=species.pk).is_deleted)

    def test_no_view_permission_no_tab_and_no_menu_entry(self):
        self.as_role()
        self.assertEqual(self.client.get(reverse('farm:species_list')).status_code, 403)
        self.assertNotContains(self.client.get(reverse('production_home')), reverse('farm:species_list'))

    def test_the_menu_and_the_role_matrix_place_it_under_reference_data(self):
        response = self.client.get(reverse('farm:species_list'))
        self.assertContains(response, f'href="{reverse("farm:species_list")}"')
        self.assertContains(response, '<p class="rail-group">Reference data</p>', html=True)
        self.assertEqual(str(response.context['group']), 'Reference data')
        self.assertEqual(str(navigation.place('farm.view_species').path), 'Production · Setup · Reference data')
        self.assertEqual(SpeciesResource.entity_type(), 'species')


class SpeciesLanguageTests(SpeciesTestCase):
    def test_the_tab_speaks_each_language_with_singular_and_plural_apart(self):
        self.make()
        for language, words in {'tr': ('<h1>Balık türleri</h1>', 'Yeni balık türü', 'Bilimsel ad', 'Tatlı su', 'Eksik'),
                                'nb': ('<h1>Arter</h1>', 'Legg til art', 'Vitenskapelig navn', 'Ferskvann',
                                       'Mangler')}.items():
            Profile.objects.update_or_create(user=self.user, defaults={'language': language})
            response = self.client.get(reverse('farm:species_list'))
            for word in words:
                self.assertContains(response, word, msg_prefix=language)


class SpeciesDatabaseViewerTests(TestCase):
    def test_the_table_is_shown_with_its_description_and_constraints(self):
        tables = {table.name: table for _, tables in database.sections() for table in tables}
        self.assertEqual(tables['species'].description,
                         'A species the farm grows or stocks, with its names, codes and the water it lives in.')
        structure = tables['species'].structure()
        names = {constraint.name for constraint in structure.constraints} | {index.name for index in structure.indexes}
        self.assertTrue({'uq_species_code_live', 'uq_species_scientific_name_live', 'chk_species_water',
                         'chk_species_official_code', 'chk_species_scientific_name'} <= names)
        unique_name = next(index for index in structure.indexes if index.name == 'uq_species_scientific_name_live')
        self.assertIn('lower((scientific_name)::text)', unique_name.definition)

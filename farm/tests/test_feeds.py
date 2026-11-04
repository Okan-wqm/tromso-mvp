from decimal import Decimal

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import translation

from core import access, database, navigation, softdelete
from core.audit import message
from core.models import AuditLog, Profile
from core.softdelete import plan_delete

from ..models import Feed, FeedSuitability, Species, Supplier
from ..resources import FeedResource
from .helpers import role, rows_data
from .test_suppliers import supplier_data

FEED_MANAGER = ('view_feed', 'add_feed', 'change_feed', 'delete_feed', 'view_auditlog')
TEXTS = ('name', 'code', 'feed_type', 'buoyancy', 'status', 'currency', 'notes')
NUMBERS = ('pellet_size_mm', 'protein_pct', 'fat_pct', 'nfe_pct', 'fibre_pct', 'ash_pct', 'moisture_pct',
           'phosphorus_pct', 'gross_energy_mj_kg', 'digestible_energy_mj_kg', 'price_per_kg')
FIELDS = TEXTS + NUMBERS


def feed_data(**overrides):
    """What the feed dialog posts."""
    data = {
        'name': 'Nutra Olympic 3 mm', 'code': 'nutra-3', 'manufacturer': '', 'feed_type': 'grower', 'feed_form': 'dry',
        'pellet_size_mm': '', 'buoyancy': '', 'status': 'active', 'protein_pct': '', 'fat_pct': '', 'nfe_pct': '',
        'fibre_pct': '', 'ash_pct': '', 'moisture_pct': '', 'phosphorus_pct': '', 'gross_energy_mj_kg': '',
        'digestible_energy_mj_kg': '', 'price_per_kg': '', 'currency': '', 'notes': '',
    }
    data.update(overrides)
    return data


def suitability_data(rows, initial=0, record=None):
    return rows_data('suitability', rows, initial, record)


def stored(record, *names):
    record.refresh_from_db()
    return tuple(getattr(record, name) for name in names)


class FeedTestCase(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('ali', 'ali@example.com', 'eski-sifre-123')
        self.user.groups.add(role('Feed manager', *FEED_MANAGER))
        self.client.force_login(self.user)
        self.mill = Supplier.objects.create(name='Fjord Feed AS', code='FJF', supplies=['feed', 'transport'])
        self.other_mill = Supplier.objects.create(name='Havfôr AS', code='HF', supplies=['feed'], status='suspended')
        self.vet = Supplier.objects.create(name='Havet Vet', code='HV', supplies=['veterinary'])
        self.salmon = Species.objects.create(common_name='Atlantic salmon', scientific_name='Salmo salar', code='SAL',
                                             freshwater=True, saltwater=True)
        self.trout = Species.objects.create(common_name='Rainbow trout', scientific_name='Oncorhynchus mykiss',
                                            code='RBT', freshwater=True)

    def make(self, name='Nutra Olympic 3 mm', code='NUTRA-3', feed_type='grower', **fields):
        return Feed.objects.create(name=name, code=code, feed_type=feed_type, **fields)

    def create(self, **overrides):
        return self.client.post(reverse('farm:feed_create'), feed_data(**overrides))

    def edit(self, feed, **overrides):
        overrides.setdefault('version', str(Feed.all_objects.get(pk=feed.pk).version))
        return self.client.post(reverse('farm:feed_edit', args=[feed.pk]), feed_data(**overrides))

    def errors(self, response):
        self.assertEqual(response.status_code, 200, 'the form was expected to be refused')
        return response.context['form'].errors

    def as_role(self, *codenames):
        person = get_user_model().objects.create_user(f'user{len(codenames)}', 'x@example.com', 'x')
        person.groups.add(role(f'Role {len(codenames)}', *codenames))
        self.client.force_login(person)
        return person


class FeedRoundTripTests(FeedTestCase):
    def test_create_read_edit_delete(self):
        # Create: every field typed
        self.create(name=' Nutra Olympic 3 mm ', code=' nutra-3 ', manufacturer=str(self.mill.pk), feed_type='grower',
                    feed_form='wet', pellet_size_mm='3', buoyancy='slow_sinking', status='inactive', protein_pct='45.5', fat_pct='24',
                    nfe_pct='12.5', fibre_pct='1.5', ash_pct='8', moisture_pct='8.5', phosphorus_pct='1.1',
                    gross_energy_mj_kg='22.5', digestible_energy_mj_kg='19.8', price_per_kg='14.75', currency=' nok ',
                    notes='Bags of 25 kg')
        feed = Feed.objects.get()
        self.assertEqual(stored(feed, 'manufacturer', 'created_by', 'version', 'feed_form'),
                         (self.mill, self.user, 1, 'wet'))
        self.assertEqual(stored(feed, *FIELDS), (
            'Nutra Olympic 3 mm', 'NUTRA-3', 'grower', 'slow_sinking', 'inactive', 'NOK', 'Bags of 25 kg',
            Decimal('3.00'), Decimal('45.50'), Decimal('24.00'), Decimal('12.50'), Decimal('1.50'), Decimal('8.00'),
            Decimal('8.50'), Decimal('1.10'), Decimal('22.50'), Decimal('19.80'), Decimal('14.75')))

        # Read: listed, and the edit form is filled from the database
        response = self.client.get(reverse('farm:feed_list'))
        self.assertEqual(list(response.context['objects']), [feed])
        form = self.client.get(reverse('farm:feed_edit', args=[feed.pk])).context['form']
        self.assertEqual({name: form[name].value() for name in TEXTS + ('manufacturer', 'version')}, {
            'name': 'Nutra Olympic 3 mm', 'code': 'NUTRA-3', 'feed_type': 'grower', 'buoyancy': 'slow_sinking',
            'status': 'inactive', 'currency': 'NOK', 'notes': 'Bags of 25 kg', 'manufacturer': self.mill.pk,
            'version': 1})
        self.assertEqual(form['feed_form'].value(), 'wet')
        self.assertEqual([form[name].value() for name in NUMBERS], [
            Decimal('3.00'), Decimal('45.50'), Decimal('24.00'), Decimal('12.50'), Decimal('1.50'), Decimal('8.00'),
            Decimal('8.50'), Decimal('1.10'), Decimal('22.50'), Decimal('19.80'), Decimal('14.75')])

        # Edit: every field changed
        self.edit(feed, name='Rapid 4 mm', code='RAPID-4', manufacturer=str(self.other_mill.pk), feed_type='finisher',
                  feed_form='dry', pellet_size_mm='4.5', buoyancy='sinking', status='active', protein_pct='40', fat_pct='30',
                  nfe_pct='15', fibre_pct='2', ash_pct='6', moisture_pct='7', phosphorus_pct='0.9',
                  gross_energy_mj_kg='24', digestible_energy_mj_kg='21.5', price_per_kg='16', currency='EUR',
                  notes='Winter feed')
        self.assertEqual(stored(feed, 'manufacturer', 'updated_by', 'version', 'feed_form'),
                         (self.other_mill, self.user, 2, 'dry'))
        self.assertEqual(stored(feed, *FIELDS), (
            'Rapid 4 mm', 'RAPID-4', 'finisher', 'sinking', 'active', 'EUR', 'Winter feed', Decimal('4.50'),
            Decimal('40.00'), Decimal('30.00'), Decimal('15.00'), Decimal('2.00'), Decimal('6.00'), Decimal('7.00'),
            Decimal('0.90'), Decimal('24.00'), Decimal('21.50'), Decimal('16.00')))

        # Delete: hidden, not erased
        self.client.post(reverse('farm:feed_delete', args=[feed.pk]))
        self.assertFalse(Feed.objects.exists())
        self.assertEqual(stored(Feed.all_objects.get(), 'is_deleted', 'deleted_by'), (True, self.user))
        self.assertEqual(list(self.client.get(reverse('farm:feed_list')).context['objects']), [])

    def test_every_optional_field_can_be_cleared_when_editing(self):
        feed = self.make(manufacturer=self.mill, pellet_size_mm=3, buoyancy='floating', protein_pct=45, fat_pct=20,
                         nfe_pct=15, fibre_pct=2, ash_pct=8, moisture_pct=8, phosphorus_pct=1,
                         gross_energy_mj_kg=21, digestible_energy_mj_kg=18, price_per_kg=Decimal('14.50'),
                         currency='NOK', notes='x')
        self.edit(feed, code='NUTRA-3')
        self.assertEqual(stored(feed, 'manufacturer', 'buoyancy', 'currency', 'notes', *NUMBERS),
                         (None, '', '', '') + (None,) * len(NUMBERS))
        self.assertEqual(AuditLog.objects.get().changes, {
            'Manufacturer': ['Fjord Feed AS (FJF)', None], 'Pellet size (mm)': ['3.00', None],
            'Buoyancy': [message('Floating'), None], 'Crude protein (%)': ['45.00', None],
            'Crude fat (%)': ['20.00', None], 'Carbohydrate, NFE (%)': ['15.00', None],
            'Crude fibre (%)': ['2.00', None], 'Ash (%)': ['8.00', None], 'Moisture (%)': ['8.00', None],
            'Phosphorus (%)': ['1.00', None], 'Gross energy (MJ/kg)': ['21.00', None],
            'Digestible energy (MJ/kg)': ['18.00', None], 'Price per kg': ['14.50', None], 'Currency': ['NOK', None],
            'Notes': ['x', None],
        })

    def test_decimals_are_typed_the_way_the_language_writes_them(self):
        Profile.objects.create(user=self.user, language='nb')
        self.create(protein_pct='45,5', pellet_size_mm='1,2', price_per_kg='14,75', currency='NOK')
        self.assertEqual(stored(Feed.objects.get(), 'protein_pct', 'pellet_size_mm', 'price_per_kg'),
                         (Decimal('45.50'), Decimal('1.20'), Decimal('14.75')))

    def test_the_form_opens_in_the_dialog_with_its_tabs(self):
        response = self.client.get(reverse('farm:feed_create'), headers={'X-Modal': '1'})
        self.assertContains(response, 'class="modal-head"')
        self.assertNotContains(response, 'id="rail"')
        for key, label in (('basic', 'Basic info'), ('analysis', 'Analysis'), ('price', 'Price and notes'),
                           ('suitability', 'Suitable for')):
            self.assertContains(response, f'data-tab="{key}">{label}</button>')
        self.assertContains(response, '<legend>Composition as fed</legend>', html=True)
        self.assertContains(response, '<legend>Energy</legend>', html=True)
        self.assertContains(response, 'Species and fish weights can be added once the feed is created.')
        form = response.context['form']
        self.assertEqual([label for _, label in form.fields['buoyancy'].choices],
                         ['Not stated', 'Floating', 'Slow sinking', 'Sinking'])
        self.assertEqual(form.fields['feed_type'].choices[0], ('', 'Select a feed type'))

    def test_an_edit_based_on_an_old_version_is_refused(self):
        feed = self.make()
        self.edit(feed, name='First', version='1')
        response = self.edit(feed, name='Second', version='1')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(stored(feed, 'name', 'version'), ('First', 2))


class FeedValidationTests(FeedTestCase):
    def test_name_code_and_feed_type_are_required(self):
        errors = self.errors(self.create(name='', code='', feed_type=''))
        self.assertEqual(set(errors), {'name', 'code', 'feed_type'})
        self.assertFalse(Feed.objects.exists())

    def test_the_code_is_upper_case_letters_digits_hyphens_and_underscores_of_at_least_two(self):
        self.assertEqual(self.errors(self.create(code='NU 3'))['code'],
                         ['Use capital letters, digits, hyphens and underscores only.'])
        self.assertEqual(self.errors(self.create(code='N'))['code'], ['Code must be at least 2 characters.'])
        feed = self.make()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Feed.objects.filter(pk=feed.pk).update(code='nu 3')

    def test_code_and_name_are_unique_among_live_feeds(self):
        feed = self.make()
        errors = self.errors(self.create(name='NUTRA olympic 3 MM', code='nutra-3'))
        self.assertEqual(errors['name'], ['Another feed already has this name.'])
        self.assertEqual(errors['code'], ['Another feed already uses this code.'])
        for fields in ({'code': 'NUTRA-3'}, {'name': 'nutra olympic 3 mm'}):
            values = {'name': 'Other', 'code': 'OTH', **fields}
            with self.subTest(fields=fields), self.assertRaises(IntegrityError), transaction.atomic():
                self.make(**values)
        self.edit(feed, notes='same name and code')
        self.assertEqual(stored(feed, 'notes'), ('same name and code',))
        # A deleted feed frees them.
        feed.soft_delete(self.user)
        self.create(name='Nutra Olympic 3 mm', code='nutra-3')
        self.assertEqual(Feed.objects.filter(code='NUTRA-3').count(), 1)

    def test_type_buoyancy_and_status_are_their_choices(self):
        errors = self.errors(self.create(feed_type='pizza', buoyancy='flying', status='low_stock'))
        self.assertEqual(set(errors), {'feed_type', 'buoyancy', 'status'})
        feed = self.make()
        for update in ({'feed_type': 'pizza'}, {'buoyancy': 'flying'}, {'status': 'out_of_stock'}):
            with self.subTest(update=update), self.assertRaises(IntegrityError), transaction.atomic():
                Feed.objects.filter(pk=feed.pk).update(**update)
        for value in Feed.Type.values:
            self.edit(feed, feed_type=value)
            self.assertEqual(stored(feed, 'feed_type'), (value,))
        for value in ('active', 'inactive', 'discontinued'):
            self.edit(feed, status=value)
            self.assertEqual(stored(feed, 'status'), (value,))

    def test_percentages_are_0_to_100_and_the_energy_0_to_40(self):
        fields = ('protein_pct', 'fat_pct', 'nfe_pct', 'fibre_pct', 'ash_pct', 'moisture_pct', 'phosphorus_pct')
        errors = self.errors(self.create(**{name: '100.5' for name in fields}, gross_energy_mj_kg='40.1',
                                         digestible_energy_mj_kg='-1'))
        self.assertEqual(set(errors), {*fields, 'gross_energy_mj_kg', 'digestible_energy_mj_kg'})
        feed = self.make()
        for name in (*fields, 'gross_energy_mj_kg', 'digestible_energy_mj_kg'):
            for value in (-1, 101 if name.endswith('pct') else 41):
                with self.subTest(field=name, value=value), self.assertRaises(IntegrityError), transaction.atomic():
                    Feed.objects.filter(pk=feed.pk).update(**{name: value})

    def test_the_parts_of_the_analysis_add_up_to_at_most_100(self):
        response = self.create(protein_pct='48', fat_pct='30', nfe_pct='15', ash_pct='8', moisture_pct='0.5')
        message_text = ('Protein, fat, carbohydrate, fibre, ash and moisture are parts of the feed as fed: together '
                        'they cannot add up to more than 100 per cent.')
        self.assertEqual(self.errors(response), {'moisture_pct': [message_text]})
        self.assertTrue(response.context['form'].tab_list()[1]['has_errors'])
        # Exactly 100 is a whole feed; phosphorus is inside the ash and not one of the parts.
        self.create(protein_pct='48', fat_pct='30', nfe_pct='5.5', fibre_pct='0.5', ash_pct='8', moisture_pct='8',
                    phosphorus_pct='1.2')
        feed = Feed.objects.get()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Feed.objects.filter(pk=feed.pk).update(fibre_pct=Decimal('0.51'))
        with self.assertRaisesMessage(ValidationError, message_text):
            feed.fibre_pct = Decimal('0.51')
            feed.full_clean()

    def test_phosphorus_is_part_of_the_ash(self):
        errors = self.errors(self.create(ash_pct='1', phosphorus_pct='1.5'))
        self.assertEqual(errors, {'phosphorus_pct': ['Phosphorus is part of the ash: it cannot be more than the ash.']})
        self.create(phosphorus_pct='1.5')    # without the ash nothing to compare with
        feed = Feed.objects.get()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Feed.objects.filter(pk=feed.pk).update(ash_pct=1)

    def test_the_digestible_energy_is_part_of_the_gross_energy(self):
        errors = self.errors(self.create(gross_energy_mj_kg='20', digestible_energy_mj_kg='21'))
        self.assertEqual(errors, {'digestible_energy_mj_kg': ['The digestible energy cannot be more than the gross '
                                                              'energy.']})
        self.create(gross_energy_mj_kg='20', digestible_energy_mj_kg='20')
        feed = Feed.objects.get()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Feed.objects.filter(pk=feed.pk).update(digestible_energy_mj_kg=21)

    def test_the_pellet_size_is_the_range_of_a_feeders_calibrations(self):
        for value in ('0', '100.01'):
            self.assertIn('pellet_size_mm', self.errors(self.create(pellet_size_mm=value)))
        self.create(pellet_size_mm='0.15', code='MICRO')
        self.assertEqual(Feed.objects.get().pellet_size_mm, Decimal('0.15'))
        with self.assertRaises(IntegrityError), transaction.atomic():
            Feed.objects.update(pellet_size_mm=0)

    def test_a_price_has_its_currency_and_a_currency_its_price(self):
        both = 'A price needs its currency, and a currency needs a price.'
        self.assertEqual(self.errors(self.create(price_per_kg='14')), {'currency': [both]})
        self.assertEqual(self.errors(self.create(currency='NOK')), {'price_per_kg': [both]})
        self.assertEqual(self.errors(self.create(price_per_kg='14', currency='NO')),
                         {'currency': ['The currency is a three-letter code, e.g. NOK or EUR.']})
        self.assertIn('price_per_kg', self.errors(self.create(price_per_kg='0', currency='NOK')))
        feed = self.make()
        for update in ({'price_per_kg': 14}, {'currency': 'NOK'}, {'price_per_kg': 14, 'currency': 'nok'},
                       {'price_per_kg': 0, 'currency': 'NOK'}):
            with self.subTest(update=update), self.assertRaises(IntegrityError), transaction.atomic():
                Feed.objects.filter(pk=feed.pk).update(**update)

    def test_lengths_are_the_columns(self):
        errors = self.errors(self.create(name='x' * 256, code='X' * 51, notes='x' * 2001))
        self.assertEqual(set(errors), {'name', 'code', 'notes'})


class FeedManufacturerTests(FeedTestCase):
    """Feed.manufacturer: the feed mill that makes it, a supplier of feed (a SupplierLink)."""

    def test_only_live_suppliers_of_feed_are_offered_with_the_status_of_those_not_active(self):
        gone = Supplier.objects.create(name='Gone Feed', code='GF', supplies=['feed'])
        gone.soft_delete(self.user)
        field = self.client.get(reverse('farm:feed_create')).context['form'].fields['manufacturer']
        self.assertEqual(list(field.queryset), [self.mill, self.other_mill])
        self.assertEqual([label for value, label in field.choices],
                         ['None', 'Fjord Feed AS (FJF)', 'Havfôr AS (HF) · Suspended'])
        for supplier in (self.vet, gone):
            self.assertEqual(self.errors(self.create(manufacturer=str(supplier.pk)))['manufacturer'],
                             ['Select a valid choice. That choice is not one of the available choices.'])
        self.assertFalse(Feed.objects.exists())

    def test_the_model_refuses_a_supplier_that_does_not_supply_feed(self):
        feed = self.make(manufacturer=self.mill)
        feed.manufacturer = self.vet
        with self.assertRaisesMessage(ValidationError, 'Choose a supplier of feed.'):
            feed.full_clean()
        feed.manufacturer = self.other_mill
        feed.full_clean()

    def test_a_supplier_keeps_feed_while_it_makes_live_feeds(self):
        self.user.groups.add(role('Purchaser', 'change_supplier'))
        self.make(manufacturer=self.mill)
        self.make('Rapid 4 mm', 'RAPID-4', manufacturer=self.mill)
        response = self.client.post(reverse('farm:supplier_edit', args=[self.mill.pk]), supplier_data(
            name='Fjord Feed AS', code='FJF', supplies=['transport'], version='1'))
        self.assertEqual(response.context['form'].errors['supplies'], [
            '2 feeds are made by it: keep “Feed” ticked, or choose another manufacturer for them first.'])
        self.assertEqual(stored(self.mill, 'supplies'), (['feed', 'transport'],))
        # A deleted feed does not count.
        for feed in Feed.objects.all():
            feed.soft_delete(self.user)
        self.client.post(reverse('farm:supplier_edit', args=[self.mill.pk]), supplier_data(
            name='Fjord Feed AS', code='FJF', supplies=['transport'], version='1'))
        self.assertEqual(stored(self.mill, 'supplies'), (['transport'],))

    def test_a_supplier_that_makes_live_feeds_cannot_be_deleted(self):
        self.user.groups.add(role('Purchaser', 'view_supplier', 'delete_supplier'))
        feed = self.make(manufacturer=self.mill)
        plan = plan_delete(self.mill)
        self.assertEqual(plan.blockers, ['1 feed still belongs to it.'])
        page = self.client.get(reverse('farm:supplier_delete', args=[self.mill.pk]))
        self.assertContains(page, 'This supplier cannot be deleted yet.')
        self.assertContains(page, '1 feed still belongs to it.')
        self.client.post(reverse('farm:supplier_delete', args=[self.mill.pk]))
        self.assertEqual(stored(self.mill, 'is_deleted'), (False,))
        # Another manufacturer for the feed (or deleting the feed) lets the supplier go.
        self.edit(feed, manufacturer=str(self.other_mill.pk))
        self.client.post(reverse('farm:supplier_delete', args=[self.mill.pk]))
        self.assertEqual(stored(self.mill, 'is_deleted'), (True,))

    def test_restoring_a_feed_needs_its_manufacturer_back_still_making_feed(self):
        feed = self.make(manufacturer=self.mill)
        feed.soft_delete(self.user)
        self.mill.soft_delete(self.user)
        with self.assertRaisesMessage(ValidationError, 'Manufacturer “Fjord Feed AS (FJF)” is deleted.'):
            softdelete.restore(Feed.all_objects.get(pk=feed.pk), self.user)
        softdelete.restore(Supplier.all_objects.get(pk=self.mill.pk), self.user)
        Supplier.objects.filter(pk=self.mill.pk).update(supplies=['transport'])
        with self.assertRaisesMessage(ValidationError, 'Choose a supplier of feed.'):
            softdelete.restore(Feed.all_objects.get(pk=feed.pk), self.user)
        Supplier.objects.filter(pk=self.mill.pk).update(supplies=['feed'])
        softdelete.restore(Feed.all_objects.get(pk=feed.pk), self.user)
        self.assertEqual(Feed.objects.get().manufacturer, self.mill)


class FeedSuitabilityTests(FeedTestCase):
    def setUp(self):
        super().setUp()
        self.feed = self.make()
        self.url = reverse('farm:feed_suitability', args=[self.feed.pk])

    def rows(self):
        return list(self.feed.suitability.values_list('species__code', 'growth_stage', 'min_weight_g', 'max_weight_g',
                                                      'notes'))

    def test_create_read_edit_delete(self):
        # Create
        response = self.client.post(self.url, suitability_data([
            {'species': str(self.salmon.pk), 'growth_stage': 'smolt', 'min_weight_g': '50', 'max_weight_g': '150',
             'notes': 'in fresh water'},
            {'species': str(self.trout.pk), 'growth_stage': 'all', 'min_weight_g': '', 'max_weight_g': '',
             'notes': ''},
            {'species': str(self.salmon.pk), 'growth_stage': 'adults', 'min_weight_g': '1000', 'max_weight_g': ''},
            {'species': '', 'growth_stage': '', 'min_weight_g': '', 'max_weight_g': '', 'notes': ''},   # left blank
        ], record=self.feed))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.rows(), [
            ('SAL', 'smolt', Decimal('50.00'), Decimal('150.00'), 'in fresh water'),
            ('SAL', 'adults', Decimal('1000.00'), None, ''),
            ('RBT', 'all', None, None, ''),
        ])
        self.assertEqual(set(self.feed.suitability.values_list('created_by', flat=True)), {self.user.pk})
        self.assertEqual(set(self.feed.species.all()), {self.salmon, self.trout})
        # Read: the edit page lists them on their tab, the list shows them
        page = self.client.get(reverse('farm:feed_edit', args=[self.feed.pk]))
        self.assertEqual([form['growth_stage'].value() for form in page.context['suitability'].forms],
                         ['smolt', 'adults', 'all'])
        self.assertContains(page, 'data-panel="suitability"')
        self.assertContains(page, 'Save suitability')
        listing = self.client.get(reverse('farm:feed_list'))
        self.assertContains(listing, '<span class="row-line">Atlantic salmon · Smolt, 50–150 g</span>', html=True)
        self.assertContains(listing, '<span class="row-line">Atlantic salmon · Adults, from 1000 g</span>', html=True)
        self.assertContains(listing, '<span class="row-line">Rainbow trout · Every stage</span>', html=True)
        # Edit: a band changes and an end is cleared; Delete: a row is removed
        smolt, adults, trout = self.feed.suitability.all()
        self.client.post(self.url, suitability_data([
            {'id': str(smolt.pk), 'species': str(self.salmon.pk), 'growth_stage': 'smolt', 'min_weight_g': '60',
             'max_weight_g': '', 'notes': ''},
            {'id': str(adults.pk), 'species': str(self.salmon.pk), 'growth_stage': 'adults', 'DELETE': True},
            {'id': str(trout.pk), 'species': str(self.trout.pk), 'growth_stage': 'juveniles', 'min_weight_g': '',
             'max_weight_g': '0.5'},
        ], initial=3, record=self.feed))
        self.assertEqual(self.rows(), [('SAL', 'smolt', Decimal('60.00'), None, ''),
                                       ('RBT', 'juveniles', None, Decimal('0.50'), '')])

    def test_rows_are_checked(self):
        response = self.client.post(self.url, suitability_data([
            {'species': '', 'growth_stage': '', 'min_weight_g': '10', 'max_weight_g': ''},
            {'species': str(self.salmon.pk), 'growth_stage': 'fry', 'min_weight_g': '-1', 'max_weight_g': '0'},
            {'species': str(self.salmon.pk), 'growth_stage': 'smolt', 'min_weight_g': '150', 'max_weight_g': '150'},
            {'species': str(self.trout.pk), 'growth_stage': 'grower', 'min_weight_g': '', 'max_weight_g': '1000001'},
        ], record=self.feed))
        formset = response.context['suitability']
        self.assertEqual(set(formset.forms[0].errors), {'species', 'growth_stage'})
        self.assertEqual(set(formset.forms[1].errors), {'min_weight_g', 'max_weight_g'})
        self.assertEqual(formset.forms[2].errors, {'max_weight_g': ['The lower weight must be below the upper weight.']})
        self.assertEqual(set(formset.forms[3].errors), {'growth_stage', 'max_weight_g'})
        self.assertEqual(response.context['open_tab'], 'suitability')
        self.assertFalse(FeedSuitability.all_objects.exists())

    def test_one_row_per_species_and_stage(self):
        response = self.client.post(self.url, suitability_data([
            {'species': str(self.salmon.pk), 'growth_stage': 'smolt', 'max_weight_g': '100'},
            {'species': str(self.salmon.pk), 'growth_stage': 'smolt', 'min_weight_g': '100'},
        ], record=self.feed))
        self.assertIn('Two rows have the same species and life stage.', response.context['suitability'].non_form_errors())
        self.assertFalse(FeedSuitability.all_objects.exists())
        FeedSuitability.objects.create(feed=self.feed, species=self.salmon, growth_stage='smolt')
        with self.assertRaises(IntegrityError), transaction.atomic():
            FeedSuitability.objects.create(feed=self.feed, species=self.salmon, growth_stage='smolt')
        # Keeping a species and stage while replacing its row is fine.
        row = self.feed.suitability.get()
        self.client.post(self.url, suitability_data([
            {'id': str(row.pk), 'species': str(self.salmon.pk), 'growth_stage': 'smolt', 'DELETE': True},
            {'species': str(self.salmon.pk), 'growth_stage': 'smolt', 'min_weight_g': '80'},
        ], initial=1, record=self.feed))
        self.assertEqual(self.rows(), [('SAL', 'smolt', Decimal('80.00'), None, '')])

    def test_the_database_checks_the_rows(self):
        row = FeedSuitability.objects.create(feed=self.feed, species=self.salmon, growth_stage='fry')
        for update in ({'growth_stage': 'grower'}, {'min_weight_g': -1}, {'max_weight_g': 0},
                       {'min_weight_g': 10, 'max_weight_g': 10}, {'max_weight_g': 1000001}):
            with self.subTest(update=update), self.assertRaises(IntegrityError), transaction.atomic():
                FeedSuitability.objects.filter(pk=row.pk).update(**update)

    def test_at_most_fifty(self):
        rows = [{'species': str(self.salmon.pk), 'growth_stage': 'all', 'min_weight_g': str(n)} for n in range(51)]
        response = self.client.post(self.url, suitability_data(rows, record=self.feed))
        self.assertIn('A feed has at most 50 rows.', response.context['suitability'].non_form_errors())

    def test_a_deleted_species_is_not_offered(self):
        self.trout.soft_delete(self.user)
        page = self.client.get(reverse('farm:feed_edit', args=[self.feed.pk]))
        self.assertEqual(list(page.context['suitability'].empty_form.fields['species'].queryset), [self.salmon])
        response = self.client.post(self.url, suitability_data([
            {'species': str(self.trout.pk), 'growth_stage': 'all'}], record=self.feed))
        self.assertIn('species', response.context['suitability'].forms[0].errors)

    def test_the_weight_band_runs_up_to_but_not_including_its_upper_weight(self):
        band = FeedSuitability(min_weight_g=Decimal(5), max_weight_g=Decimal(20))
        self.assertEqual([band.suits(Decimal(weight)) for weight in ('4.99', '5', '19.99', '20')],
                         [False, True, True, False])
        self.assertTrue(FeedSuitability().suits(Decimal(100000)))
        self.assertTrue(FeedSuitability(max_weight_g=Decimal(1)).suits(Decimal(0)))

    def test_saving_the_rows_is_logged_on_the_feed(self):
        self.client.post(self.url, suitability_data([
            {'species': str(self.salmon.pk), 'growth_stage': 'smolt', 'min_weight_g': '50', 'max_weight_g': '150.5',
             'notes': 'in fresh water'},
            {'species': str(self.trout.pk), 'growth_stage': 'fry', 'max_weight_g': '5'},
        ], record=self.feed))
        entry = AuditLog.objects.get()
        self.assertEqual((entry.action, entry.entity_type, entry.entity_id, entry.changes), (
            'update', 'feed', str(self.feed.pk),
            {'Suitable for': [None, 'Atlantic salmon (SAL): Smolt, 50–150.5 g (in fresh water); '
                                    'Rainbow trout (RBT): Fry, up to 5 g']}))

    def test_saving_rows_needs_the_change_permission(self):
        self.as_role('view_feed')
        self.assertEqual(self.client.post(self.url, suitability_data([
            {'species': str(self.salmon.pk), 'growth_stage': 'all'}], record=self.feed)).status_code, 403)
        self.assertFalse(FeedSuitability.all_objects.exists())

    def test_deleting_a_species_keeps_its_rows_out_of_sight_until_it_is_restored(self):
        self.user.groups.add(role('Biologist', 'view_species', 'delete_species'))
        FeedSuitability.objects.create(feed=self.feed, species=self.salmon, growth_stage='smolt')
        FeedSuitability.objects.create(feed=self.feed, species=self.trout, growth_stage='fry')
        page = self.client.get(reverse('farm:species_delete', args=[self.trout.pk]))
        self.assertContains(page, 'Feeds linked to it')
        self.assertContains(page, 'Nutra Olympic 3 mm (NUTRA-3)')
        self.client.post(reverse('farm:species_delete', args=[self.trout.pk]))
        self.assertEqual(self.rows(), [('SAL', 'smolt', None, None, '')])
        self.assertEqual(FeedSuitability.all_objects.filter(feed=self.feed).count(), 2)
        # Saving the list replaces the rows it shows and keeps the deleted species' row for its restore.
        salmon_row = self.feed.suitability.get()
        self.client.post(self.url, suitability_data([
            {'id': str(salmon_row.pk), 'species': str(self.salmon.pk), 'growth_stage': 'smolt', 'max_weight_g': '90'},
        ], initial=1, record=self.feed))
        softdelete.restore(Species.all_objects.get(pk=self.trout.pk), self.user)
        self.assertEqual(self.rows(), [('SAL', 'smolt', None, Decimal('90.00'), ''), ('RBT', 'fry', None, None, '')])

    def test_deleting_a_feed_keeps_its_rows_with_it(self):
        FeedSuitability.objects.create(feed=self.feed, species=self.salmon, growth_stage='smolt')
        plan = plan_delete(self.feed)
        self.assertTrue(plan.can_delete)
        self.assertEqual((plan.cascade, plan.detach, plan.unlinked), ([], [], []))
        self.client.post(reverse('farm:feed_delete', args=[self.feed.pk]))
        self.assertEqual(FeedSuitability.objects.filter(feed_id=self.feed.pk).count(), 1)
        self.assertEqual(list(self.salmon.feeds.filter(is_deleted=False)), [])


class FeedListTests(FeedTestCase):
    def setUp(self):
        super().setUp()
        self.grower = self.make('Nutra Olympic 3 mm', 'NUTRA-3', 'grower', manufacturer=self.mill, pellet_size_mm=3,
                                buoyancy='slow_sinking', protein_pct=Decimal('45.5'), fat_pct=24,
                                gross_energy_mj_kg=Decimal('22.5'), digestible_energy_mj_kg=Decimal('19.8'),
                                price_per_kg=Decimal('1234.5'), currency='NOK')
        self.start = self.make('Start 0.5 mm', 'START-05', 'starter', manufacturer=self.other_mill,
                               pellet_size_mm=Decimal('0.5'), status='inactive')
        self.cure = self.make('Medicated 4 mm', 'MED-4', 'medicated', status='discontinued')
        FeedSuitability.objects.create(feed=self.grower, species=self.salmon, growth_stage='smolt')
        FeedSuitability.objects.create(feed=self.grower, species=self.salmon, growth_stage='adults')
        FeedSuitability.objects.create(feed=self.start, species=self.trout, growth_stage='fry')

    def codes(self, **query):
        return [feed.code for feed in self.client.get(reverse('farm:feed_list'), query).context['objects']]

    def test_listed_by_name(self):
        self.assertEqual(self.codes(), ['MED-4', 'NUTRA-3', 'START-05'])

    def test_columns(self):
        response = self.client.get(reverse('farm:feed_list'))
        self.assertContains(response, '<td>Fjord Feed AS</td>', html=True)
        self.assertContains(response, '<td>Havfôr AS<span class="row-sub">Suspended</span></td>', html=True)
        self.assertContains(response, '<td>Grower feed</td>', html=True)
        self.assertContains(response, '<td class="nowrap">3 mm<span class="row-sub">Slow sinking</span></td>', html=True)
        self.assertContains(response, '<td class="nowrap">45.50 / 24 %</td>', html=True)
        self.assertContains(response, '<td class="nowrap">22.50 MJ/kg<span class="row-sub">19.80 MJ/kg digestible</span>'
                                      '</td>', html=True)
        self.assertContains(response, '<td class="nowrap">1,234.50 NOK</td>', html=True)
        self.assertContains(response, '<span class="badge badge-discontinued">Discontinued</span>', html=True)

    def test_search_covers_name_code_and_manufacturer(self):
        self.assertEqual(self.codes(q='olympic'), ['NUTRA-3'])
        self.assertEqual(self.codes(q='med-'), ['MED-4'])
        self.assertEqual(self.codes(q='havfôr'), ['START-05'])

    def test_filters(self):
        self.assertEqual(self.codes(type='starter'), ['START-05'])
        self.assertEqual(self.codes(manufacturer=self.mill.pk), ['NUTRA-3'])
        self.assertEqual(self.codes(species=self.salmon.pk), ['NUTRA-3'])    # once, though it suits two stages
        self.assertEqual(self.codes(status='discontinued'), ['MED-4'])
        self.assertEqual(self.codes(species=self.trout.pk, type='starter', q='start'), ['START-05'])
        self.assertEqual(len(self.codes(type='pizza', manufacturer='x', species=self.vet.pk, status='y')), 3)
        response = self.client.get(reverse('farm:feed_list'))
        self.assertEqual(list(response.context['manufacturers']), [self.mill, self.other_mill])
        self.assertEqual(list(response.context['species_list']), [self.salmon, self.trout])

    def test_the_list_is_paged_and_the_pages_keep_the_search_and_filters(self):
        Feed.objects.bulk_create([Feed(name=f'Bulk {n:02}', code=f'B{n:02}', feed_type='other') for n in range(60)])
        first = self.client.get(reverse('farm:feed_list'), {'type': 'other'})
        self.assertEqual(len(first.context['objects']), 50)
        self.assertContains(first, '?type=other&amp;page=2')
        second = self.client.get(reverse('farm:feed_list'), {'type': 'other', 'page': '2'})
        self.assertEqual([feed.code for feed in second.context['objects']], [f'B{n:02}' for n in range(50, 60)])

    def test_the_empty_list_invites_to_add_one(self):
        Feed.objects.all().delete()
        response = self.client.get(reverse('farm:feed_list'))
        self.assertContains(response, 'No feeds yet')
        self.assertContains(response, 'Add feed')


class FeedDeleteAndRestoreTests(FeedTestCase):
    def test_a_deleted_feed_cannot_be_edited_or_deleted_again(self):
        feed = self.make()
        feed.soft_delete(self.user)
        for url in (reverse('farm:feed_edit', args=[feed.pk]), reverse('farm:feed_delete', args=[feed.pk]),
                    reverse('farm:feed_suitability', args=[feed.pk])):
            self.assertEqual(self.client.post(url, feed_data()).status_code, 404, url)

    def test_the_confirmation_names_the_feed_and_the_delete_is_logged(self):
        feed = self.make()
        page = self.client.get(reverse('farm:feed_delete', args=[feed.pk]))
        self.assertContains(page, 'Delete “Nutra Olympic 3 mm (NUTRA-3)”?')
        self.client.post(reverse('farm:feed_delete', args=[feed.pk]))
        self.assertEqual(list(AuditLog.objects.values_list('action', 'entity_type', 'entity_label')),
                         [('delete', 'feed', 'Nutra Olympic 3 mm (NUTRA-3)')])

    def test_restore_brings_it_back_unless_its_name_or_code_was_taken_meanwhile(self):
        feed = self.make()
        feed.soft_delete(self.user)
        other = self.make('NUTRA OLYMPIC 3 MM', 'OTHER')
        with self.assertRaisesMessage(ValidationError, 'Another feed already has this name.'):
            softdelete.restore(Feed.all_objects.get(pk=feed.pk), self.user)
        other.soft_delete(self.user)
        self.make('Other', 'NUTRA-3')
        with self.assertRaisesMessage(ValidationError, 'Another feed already uses this code.'):
            softdelete.restore(Feed.all_objects.get(pk=feed.pk), self.user)
        Feed.objects.filter(code='NUTRA-3').update(code='OTHER-2')
        softdelete.restore(Feed.all_objects.get(pk=feed.pk), self.user)
        self.assertEqual(stored(feed, 'is_deleted', 'version'), (False, 3))
        self.assertEqual(AuditLog.objects.get(action='restore').entity_label, 'Nutra Olympic 3 mm (NUTRA-3)')

    def test_the_admin_lists_deleted_feeds_and_restores_them(self):
        root = get_user_model().objects.create_superuser('root', 'root@example.com', 'x')
        self.client.force_login(root)
        feed = self.make()
        feed.soft_delete(root)
        self.assertEqual(admin.site._registry[Feed].list_display, ['name', 'code', 'status', 'is_deleted'])
        self.assertNotIn(FeedSuitability, admin.site._registry)
        page = self.client.get(reverse('admin:farm_feed_changelist'), {'q': 'olympic'})
        self.assertContains(page, 'Nutra Olympic 3 mm')
        self.assertNotContains(page, reverse('admin:farm_feed_add'))
        response = self.client.post(reverse('admin:farm_feed_changelist'),
                                    {'action': 'restore', '_selected_action': [str(feed.pk)]}, follow=True)
        self.assertContains(response, '1 record restored.')
        self.assertTrue(Feed.objects.filter(pk=feed.pk).exists())


class FeedAuditTests(FeedTestCase):
    def test_create_edit_and_delete_are_logged_with_old_and_new_values(self):
        self.create(manufacturer=str(self.mill.pk), buoyancy='floating', protein_pct='45.5', price_per_kg='14',
                    currency='NOK')
        feed = Feed.objects.get()
        self.edit(feed, manufacturer=str(self.mill.pk), feed_type='medicated', buoyancy='sinking', protein_pct='45.50',
                  price_per_kg='14.00', currency='NOK', status='discontinued')
        self.client.post(reverse('farm:feed_delete', args=[feed.pk]))
        created, edited, deleted = AuditLog.objects.order_by('created_at')
        self.assertEqual((created.action, created.entity_type, created.entity_label),
                         ('create', 'feed', 'Nutra Olympic 3 mm (NUTRA-3)'))
        self.assertEqual(created.changes, {
            'Name': [None, 'Nutra Olympic 3 mm'], 'Code': [None, 'NUTRA-3'], 'Manufacturer': [None, 'Fjord Feed AS (FJF)'],
            'Feed type': [None, message('Grower feed')], 'Dry or wet': [None, message('Dry')],
            'Buoyancy': [None, message('Floating')],
            'Status': [None, message('Active')], 'Crude protein (%)': [None, '45.50'], 'Price per kg': [None, '14.00'],
            'Currency': [None, 'NOK'],
        })
        self.assertEqual(edited.changes, {
            'Feed type': [message('Grower feed'), message('Medicated feed')],
            'Buoyancy': [message('Floating'), message('Sinking')],
            'Status': [message('Active'), message('Discontinued')],
        })
        self.assertEqual((deleted.action, deleted.entity_type), ('delete', 'feed'))

    def test_the_log_is_english_and_shown_in_the_readers_language(self):
        Profile.objects.create(user=self.user, language='tr')
        self.create(feed_type='starter', buoyancy='slow_sinking')
        entry = AuditLog.objects.get()
        self.assertEqual(entry.changes['Feed type'], [None, message('Starter feed')])
        with translation.override('nb'):
            self.assertEqual(entry.shown_type(), 'fôr')
            self.assertIn(('Fôrtype', None, 'Startfôr'), entry.shown_changes())
            self.assertIn(('Flyteevne', None, 'Saktesynkende'), entry.shown_changes())

    def test_the_history_tab_shows_the_changes(self):
        self.create()
        feed = Feed.objects.get()
        self.assertEqual(len(self.client.get(reverse('farm:feed_edit', args=[feed.pk])).context['history']), 1)


class FeedPermissionTests(FeedTestCase):
    def test_a_read_only_role_sees_feeds_but_cannot_change_them(self):
        feed = self.make()
        self.as_role('view_feed')
        response = self.client.get(reverse('farm:feed_list'))
        self.assertContains(response, 'Nutra Olympic 3 mm')
        for url in (reverse('farm:feed_create'), reverse('farm:feed_edit', args=[feed.pk]),
                    reverse('farm:feed_delete', args=[feed.pk])):
            self.assertNotContains(response, url)
            self.assertEqual(self.client.post(url, feed_data()).status_code, 403, url)
        self.assertEqual(stored(feed, 'is_deleted', 'version'), (False, 1))

    def test_each_action_needs_its_own_permission(self):
        feed = self.make()
        self.as_role('view_feed', 'add_feed')
        self.create(name='Other', code='OTH')
        self.assertTrue(Feed.objects.filter(code='OTH').exists())
        self.assertEqual(self.edit(feed, name='Changed').status_code, 403)
        self.as_role('view_feed', 'change_feed', 'delete_feed')
        self.assertEqual(self.create(code='NEW').status_code, 403)
        self.edit(feed, name='Changed')
        self.assertEqual(stored(feed, 'name'), ('Changed',))
        self.client.post(reverse('farm:feed_delete', args=[feed.pk]))
        self.assertTrue(Feed.all_objects.get(pk=feed.pk).is_deleted)

    def test_no_view_permission_no_tab_and_no_menu_entry(self):
        self.as_role()
        self.assertEqual(self.client.get(reverse('farm:feed_list')).status_code, 403)
        self.assertNotContains(self.client.get(reverse('production_home')), reverse('farm:feed_list'))

    def test_the_menu_and_the_role_matrix_place_it_under_reference_data(self):
        response = self.client.get(reverse('farm:feed_list'))
        self.assertContains(response, f'href="{reverse("farm:feed_list")}"')
        self.assertContains(response, '<p class="rail-group">Reference data</p>', html=True)
        self.assertEqual((str(response.context['group']), str(response.context['title'])), ('Reference data', 'Feeds'))
        self.assertEqual(str(navigation.place('farm.view_feed').path), 'Production · Setup · Reference data')
        (area,) = [area for area in access.areas() if area.model == 'farm.Feed']
        self.assertEqual((str(area.label), str(area.group)), ('Feeds', 'Production · Setup · Reference data'))
        self.assertEqual(FeedResource.entity_type(), 'feed')


class FeedLanguageTests(FeedTestCase):
    def test_the_tab_speaks_each_language(self):
        feed = self.make(buoyancy='sinking', status='discontinued')
        FeedSuitability.objects.create(feed=feed, species=self.salmon, growth_stage='smolt', min_weight_g=50)
        for language, words in {
            'tr': ('<h1>Yemler</h1>', 'Yeni yem', 'Referans verileri', 'Büyütme yemi', 'Batan',
                   'Üretimden kaldırıldı', 'Atlantic salmon · Smolt, 50 g ve üstü'),
            'nb': ('<h1>Fôr</h1>', 'Legg til fôr', 'Referansedata', 'Vekstfôr', 'Synkende', 'Avviklet',
                   'Atlantic salmon · Smolt, fra 50 g'),
        }.items():
            Profile.objects.update_or_create(user=self.user, defaults={'language': language})
            response = self.client.get(reverse('farm:feed_list'))
            for word in words:
                self.assertContains(response, word, msg_prefix=language)


class FeedDatabaseViewerTests(TestCase):
    def test_the_tables_are_shown_with_their_descriptions_and_constraints(self):
        tables = {table.name: table for _, tables in database.sections() for table in tables}
        self.assertEqual(tables['feeds'].description,
                         'A feed the farm uses: its maker, what it is made for, its pellet and its analysis, and the '
                         'species and fish weights it suits.')
        self.assertEqual(tables['feed_suitability'].description,
                         'A species and life stage a feed suits, and the fish weights it suits them at.')
        structure = tables['feeds'].structure()
        names = {constraint.name for constraint in structure.constraints} | {index.name for index in structure.indexes}
        self.assertTrue({'uq_feeds_code_live', 'uq_feeds_name_live', 'chk_feeds_fractions', 'chk_feeds_phosphorus_in_ash',
                         'chk_feeds_digestible_energy', 'chk_feeds_price_currency', 'chk_feeds_pellet_size'} <= names)
        columns = {column.name: column for column in structure.columns}
        self.assertEqual((columns['manufacturer_id'].reference.table, columns['manufacturer_id'].nullable),
                         ('suppliers', True))
        rows = {column.name: column for column in tables['feed_suitability'].structure().columns}
        self.assertEqual((rows['feed_id'].reference.table, rows['species_id'].reference.table), ('feeds', 'species'))

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

from ..models import Equipment, EquipmentSystem, EquipmentType, ProductionDepartment, Site, Supplier, System
from ..resources import SupplierResource
from .helpers import contacts_data, role
from .test_equipment import equipment_data, link

SUPPLIER_MANAGER = ('view_supplier', 'add_supplier', 'change_supplier', 'delete_supplier', 'view_site',
                    'delete_site', 'view_auditlog')
ALL_CATEGORIES = ['live_fish', 'feed', 'equipment', 'consumables', 'chemicals', 'medicines', 'veterinary',
                  'laboratory', 'diving', 'transport', 'maintenance', 'consultancy', 'other']
FIELDS = ('name', 'code', 'organisation_number', 'supplies', 'status', 'rating', 'email', 'phone', 'website',
          'street', 'postal_code', 'city', 'country', 'payment_terms', 'notes')


def supplier_data(**overrides):
    """What the supplier dialog posts. `supplies` and `sites` are lists, posted as several values."""
    data = {
        'name': 'Fjord Feed AS', 'code': 'fjf', 'organisation_number': '', 'supplies': ['feed'], 'status': 'active',
        'rating': '', 'email': '', 'phone': '', 'website': '', 'street': '', 'postal_code': '', 'city': '',
        'country': '', 'sites': [], 'payment_terms': '', 'notes': '',
    }
    data.update(overrides)
    return data


def stored(supplier, *names):
    supplier.refresh_from_db()
    return tuple(getattr(supplier, name) for name in names)


class SupplierTestCase(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('ali', 'ali@example.com', 'eski-sifre-123')
        self.user.groups.add(role('Purchaser', *SUPPLIER_MANAGER))
        self.client.force_login(self.user)
        self.bergen = Site.objects.create(name='Bergen', code='BG')
        self.tromso = Site.objects.create(name='Tromso', code='TR')

    def make(self, name='Fjord Feed AS', code='FJF', supplies=('feed',), **fields):
        return Supplier.objects.create(name=name, code=code, supplies=list(supplies), **fields)

    def create(self, **overrides):
        return self.client.post(reverse('farm:supplier_create'), supplier_data(**overrides))

    def edit(self, supplier, **overrides):
        overrides.setdefault('version', str(Supplier.all_objects.get(pk=supplier.pk).version))
        return self.client.post(reverse('farm:supplier_edit', args=[supplier.pk]), supplier_data(**overrides))

    def errors(self, response):
        self.assertEqual(response.status_code, 200, 'the form was expected to be refused')
        return response.context['form'].errors


class SupplierRoundTripTests(SupplierTestCase):
    def test_create_read_edit_delete(self):
        # Create: every field typed
        self.create(name=' Fjord Feed AS ', code=' fjf-1 ', organisation_number=' no 923 456 789 mva ',
                    supplies=['transport', 'feed'], status='suspended', rating='4', email='orders@fjordfeed.no',
                    phone='+47 55 00 00 00', website='www.fjordfeed.no', street='Kaien 1', postal_code='5003',
                    city='Bergen', country='Norway', sites=[str(self.bergen.pk), str(self.tromso.pk)],
                    payment_terms='30 days net', notes='Delivers on Tuesdays')
        supplier = Supplier.objects.get()
        self.assertEqual(stored(supplier, *FIELDS, 'created_by', 'version'), (
            'Fjord Feed AS', 'FJF-1', 'NO923456789MVA', ['feed', 'transport'], 'suspended', 4, 'orders@fjordfeed.no',
            '+47 55 00 00 00', 'https://www.fjordfeed.no', 'Kaien 1', '5003', 'Bergen', 'Norway', '30 days net',
            'Delivers on Tuesdays', self.user, 1))
        self.assertEqual(set(supplier.sites.all()), {self.bergen, self.tromso})

        # Read: listed, and the edit form is filled from the database
        response = self.client.get(reverse('farm:supplier_list'))
        self.assertEqual(list(response.context['objects']), [supplier])
        self.assertContains(response, '<td>Feed, Wellboat and transport</td>', html=True)
        form = self.client.get(reverse('farm:supplier_edit', args=[supplier.pk])).context['form']
        self.assertEqual({name: form[name].value() for name in FIELDS + ('version',)}, {
            'name': 'Fjord Feed AS', 'code': 'FJF-1', 'organisation_number': 'NO923456789MVA',
            'supplies': ['feed', 'transport'], 'status': 'suspended', 'rating': 4, 'email': 'orders@fjordfeed.no',
            'phone': '+47 55 00 00 00', 'website': 'https://www.fjordfeed.no', 'street': 'Kaien 1',
            'postal_code': '5003', 'city': 'Bergen', 'country': 'Norway', 'payment_terms': '30 days net',
            'notes': 'Delivers on Tuesdays', 'version': 1})
        self.assertEqual(set(form['sites'].value()), {self.bergen.pk, self.tromso.pk})

        # Edit: every field changed
        self.edit(supplier, name='Fjord Aqua AS', code='FJA', organisation_number='987654321',
                  supplies=['equipment', 'maintenance', 'diving'], status='active', rating='2',
                  email='post@fjordaqua.no', phone='+47 1', website='https://fjordaqua.no', street='Bryggen 2',
                  postal_code='5004', city='Ålesund', country='Norge', sites=[str(self.tromso.pk)],
                  payment_terms='Prepayment', notes='Divers on call')
        self.assertEqual(stored(supplier, *FIELDS, 'updated_by', 'version'), (
            'Fjord Aqua AS', 'FJA', '987654321', ['equipment', 'diving', 'maintenance'], 'active', 2,
            'post@fjordaqua.no', '+47 1', 'https://fjordaqua.no', 'Bryggen 2', '5004', 'Ålesund', 'Norge',
            'Prepayment', 'Divers on call', self.user, 2))
        self.assertEqual(list(supplier.sites.all()), [self.tromso])

        # Delete: hidden, not erased
        self.client.post(reverse('farm:supplier_delete', args=[supplier.pk]))
        self.assertFalse(Supplier.objects.exists())
        self.assertEqual(stored(Supplier.all_objects.get(), 'is_deleted', 'deleted_by'), (True, self.user))
        self.assertEqual(list(self.client.get(reverse('farm:supplier_list')).context['objects']), [])

    def test_every_optional_field_can_be_cleared_when_editing(self):
        supplier = self.make(organisation_number='923456789', rating=5, email='a@b.no', phone='1',
                             website='https://a.no', street='s', postal_code='p', city='c', country='n',
                             payment_terms='t', notes='x')
        supplier.sites.add(self.bergen)
        self.edit(supplier, code='FJF')
        self.assertEqual(
            stored(supplier, 'organisation_number', 'rating', 'email', 'phone', 'website', 'street', 'postal_code',
                   'city', 'country', 'payment_terms', 'notes'),
            ('', None, '', '', '', '', '', '', '', '', ''))
        self.assertEqual(list(supplier.sites.all()), [])
        self.assertEqual(AuditLog.objects.get().changes, {
            'Organisation number': ['923456789', None], 'Rating': [message('5'), None], 'Email': ['a@b.no', None],
            'Phone': ['1', None], 'Website': ['https://a.no', None], 'Street address': ['s', None],
            'Postal code': ['p', None], 'City': ['c', None], 'Country': ['n', None],
            'Sites served': ['Bergen (BG)', None], 'Payment terms': ['t', None], 'Notes': ['x', None],
        })

    def test_the_form_opens_in_the_dialog_with_its_tabs(self):
        response = self.client.get(reverse('farm:supplier_create'), headers={'X-Modal': '1'})
        self.assertContains(response, 'class="modal-head"')
        self.assertNotContains(response, 'id="rail"')
        for key, label in (('basic', 'Basic info'), ('contact', 'Contact'), ('address', 'Address'),
                           ('sites', 'Sites'), ('terms', 'Terms and notes')):
            self.assertContains(response, f'data-tab="{key}">{label}</button>')
        self.assertContains(response, '<legend>Supplies</legend>', html=True)
        for value in ALL_CATEGORIES:
            self.assertContains(response, f'name="supplies" value="{value}"')
        self.assertContains(response, 'Contacts can be added once the supplier is created.')

    def test_an_edit_based_on_an_old_version_is_refused(self):
        supplier = self.make()
        self.edit(supplier, name='First', version='1')
        response = self.edit(supplier, name='Second', version='1')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(stored(supplier, 'name', 'version'), ('First', 2))


class SupplierValidationTests(SupplierTestCase):
    def test_name_code_and_what_it_supplies_are_required(self):
        errors = self.errors(self.create(name='', code='', supplies=[]))
        self.assertEqual(set(errors), {'name', 'code', 'supplies'})
        self.assertEqual(errors['supplies'], ['Tick at least one thing it supplies.'])
        self.assertFalse(Supplier.objects.exists())

    def test_every_category_can_be_ticked_and_nothing_else(self):
        self.create(supplies=ALL_CATEGORIES)
        self.assertEqual(Supplier.objects.get().supplies, ALL_CATEGORIES)
        self.assertIn('supplies', self.errors(self.create(code='X2', name='Other', supplies=['feed', 'pizza'])))

    def test_what_it_supplies_is_stored_once_each_in_the_order_of_the_categories(self):
        supplier = self.make(supplies=['other', 'feed', 'other', 'live_fish'])
        self.assertEqual(stored(supplier, 'supplies'), (['live_fish', 'feed', 'other'],))

    def test_the_database_checks_what_it_supplies(self):
        supplier = self.make()
        for supplies in ([], ['pizza'], ['feed', 'pizza']):
            with self.subTest(supplies=supplies), self.assertRaises(IntegrityError), transaction.atomic():
                Supplier.objects.filter(pk=supplier.pk).update(supplies=supplies)

    def test_the_code_is_upper_case_letters_digits_hyphens_and_underscores_of_at_least_two(self):
        self.assertEqual(self.errors(self.create(code='FJ F'))['code'],
                         ['Use capital letters, digits, hyphens and underscores only.'])
        self.assertEqual(self.errors(self.create(code='F'))['code'], ['Code must be at least 2 characters.'])
        self.create(code='fj_f-2')
        self.assertEqual(Supplier.objects.get().code, 'FJ_F-2')
        with self.assertRaises(IntegrityError), transaction.atomic():
            Supplier.objects.update(code='fj f')

    def test_code_name_and_organisation_number_are_unique_among_live_suppliers(self):
        supplier = self.make(organisation_number='923456789')
        errors = self.errors(self.create(name='FJORD FEED as', code='fjf', organisation_number='923 456 789'))
        self.assertEqual(errors['name'], ['Another supplier already has this name.'])
        self.assertEqual(errors['code'], ['Another supplier already uses this code.'])
        self.assertEqual(errors['organisation_number'], ['Another supplier already has this organisation number.'])
        for fields in ({'code': 'FJF'}, {'name': 'fjord feed as'}, {'organisation_number': '923456789'}):
            values = {'name': 'Other', 'code': 'OTH', **fields}
            with self.subTest(fields=fields), self.assertRaises(IntegrityError), transaction.atomic():
                self.make(**values)
        # Two suppliers without an organisation number are fine; editing keeps its own values.
        self.create(name='Other', code='OTH')
        self.edit(supplier, name='Fjord Feed AS', code='FJF', organisation_number='923456789', notes='same')
        self.assertEqual(stored(supplier, 'notes'), ('same',))
        # A deleted supplier frees them.
        supplier.soft_delete(self.user)
        self.create(name='Fjord feed AS', code='fjf', organisation_number='923456789')
        self.assertEqual(Supplier.objects.filter(code='FJF').count(), 1)

    def test_the_organisation_number_is_letters_digits_and_hyphens_without_spaces(self):
        self.assertEqual(self.errors(self.create(organisation_number='923.456.789'))['organisation_number'],
                         ['Use letters, digits and hyphens only, e.g. 923456789 or NO923456789MVA.'])
        supplier = self.make()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Supplier.objects.filter(pk=supplier.pk).update(organisation_number='923 456')
        supplier.organisation_number = ' tr 1234567890 '
        supplier.save()     # however it is written
        self.assertEqual(stored(supplier, 'organisation_number'), ('TR1234567890',))

    def test_status_and_rating_are_their_choices(self):
        errors = self.errors(self.create(status='bankrupt', rating='6'))
        self.assertEqual(set(errors), {'status', 'rating'})
        supplier = self.make()
        for update in ({'status': 'bankrupt'}, {'rating': 6}, {'rating': 0}):
            with self.subTest(update=update), self.assertRaises(IntegrityError), transaction.atomic():
                Supplier.objects.filter(pk=supplier.pk).update(**update)
        for status in ('active', 'inactive', 'suspended', 'blocked'):
            self.edit(supplier, status=status)
            self.assertEqual(stored(supplier, 'status'), (status,))
        for rating in ('1', '5', ''):
            self.edit(supplier, rating=rating)
            self.assertEqual(stored(supplier, 'rating'), (int(rating) if rating else None,))

    def test_email_and_website_are_checked(self):
        errors = self.errors(self.create(email='not an email', website='not a site'))
        self.assertEqual(set(errors), {'email', 'website'})

    def test_lengths_are_the_columns(self):
        errors = self.errors(self.create(
            name='x' * 201, code='X' * 21, organisation_number='9' * 51, phone='1' * 51, street='x' * 256,
            postal_code='x' * 21, city='x' * 101, country='x' * 101, payment_terms='x' * 101, notes='x' * 2001))
        self.assertEqual(set(errors), {'name', 'code', 'organisation_number', 'phone', 'street', 'postal_code', 'city',
                                       'country', 'payment_terms', 'notes'})

    def test_sites_must_be_live(self):
        self.tromso.soft_delete(self.user)
        self.assertIn('sites', self.errors(self.create(sites=[str(self.tromso.pk)])))


class SupplierContactTests(SupplierTestCase):
    def setUp(self):
        super().setUp()
        self.supplier = self.make()
        self.url = reverse('farm:supplier_contacts', args=[self.supplier.pk])

    def test_contact_create_read_edit_delete(self):
        # Create
        self.client.post(self.url, contacts_data([
            {'name': 'Kari', 'role': 'Sales', 'email': 'kari@fjordfeed.no', 'phone': '+47 1', 'is_primary': True},
            {'name': 'Ola', 'role': 'Vet on call', 'email': '', 'phone': '+47 2', 'is_primary': False},
        ], record=self.supplier))
        self.assertEqual(list(self.supplier.contacts.values_list('name', 'role', 'email', 'phone', 'is_primary',
                                                                 'created_by')),
                         [('Kari', 'Sales', 'kari@fjordfeed.no', '+47 1', True, self.user.pk),
                          ('Ola', 'Vet on call', '', '+47 2', False, self.user.pk)])
        # Read: the edit page lists them, the list shows the primary one
        page = self.client.get(reverse('farm:supplier_edit', args=[self.supplier.pk]))
        self.assertEqual([form['name'].value() for form in page.context['contacts'].forms], ['Kari', 'Ola'])
        self.assertContains(page, 'The people to contact at the supplier')
        listing = self.client.get(reverse('farm:supplier_list'))
        self.assertContains(listing, 'Kari<span class="row-sub">Sales</span>', html=True)
        # Edit: the primary mark moves, a field is cleared
        kari, ola = self.supplier.contacts.order_by('name')
        self.client.post(self.url, contacts_data([
            {'id': str(kari.pk), 'name': 'Kari', 'role': '', 'email': 'kari@fjordfeed.no', 'is_primary': False},
            {'id': str(ola.pk), 'name': 'Ola', 'role': 'Vet on call', 'phone': '+47 2', 'is_primary': True},
        ], initial=2, record=self.supplier))
        self.assertEqual(list(self.supplier.contacts.values_list('name', 'role', 'is_primary')),
                         [('Ola', 'Vet on call', True), ('Kari', '', False)])
        # Delete
        ola, kari = self.supplier.contacts.all()
        self.client.post(self.url, contacts_data([
            {'id': str(ola.pk), 'name': 'Ola', 'is_primary': True},
            {'id': str(kari.pk), 'name': 'Kari', 'DELETE': True}], initial=2, record=self.supplier))
        self.assertEqual(list(self.supplier.contacts.values_list('name', flat=True)), ['Ola'])

    def test_one_primary_contact_and_a_name_each(self):
        response = self.client.post(self.url, contacts_data([
            {'name': 'Kari', 'is_primary': True}, {'name': 'Ola', 'is_primary': True}], record=self.supplier))
        self.assertContains(response, 'Only one contact can be the primary contact; 2 are marked.')
        response = self.client.post(self.url, contacts_data([{'name': '', 'role': 'Sales'}], record=self.supplier))
        self.assertEqual(response.context['contacts'].forms[0].errors['name'], ['This field is required.'])
        self.assertFalse(self.supplier.contacts.exists())
        self.supplier.contacts.create(name='Kari', is_primary=True)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.supplier.contacts.create(name='Ola', is_primary=True)

    def test_saving_the_contacts_is_logged_on_the_supplier(self):
        self.client.post(self.url, contacts_data([{'name': 'Kari', 'role': 'Sales', 'is_primary': True}],
                                                 record=self.supplier))
        entry = AuditLog.objects.get()
        self.assertEqual((entry.action, entry.entity_type, entry.entity_id, entry.changes),
                         ('update', 'supplier', str(self.supplier.pk), {'Contacts': [None, [['Kari (Sales, primary)']]]}))

    def test_saving_contacts_needs_the_change_permission(self):
        reader = get_user_model().objects.create_user('ola', 'ola@example.com', 'x')
        reader.groups.add(role('Reader', 'view_supplier'))
        self.client.force_login(reader)
        data = contacts_data([{'name': 'Kari'}], record=self.supplier)
        self.assertEqual(self.client.post(self.url, data).status_code, 403)
        self.assertFalse(self.supplier.contacts.exists())


class SupplierListTests(SupplierTestCase):
    def setUp(self):
        super().setUp()
        self.feed = self.make('Fjord Feed AS', 'FJF', ['feed', 'transport'], city='Bergen', country='Norway',
                              email='orders@fjordfeed.no', rating=4)
        self.feed.sites.add(self.bergen)
        self.vet = self.make('Havet Vet', 'HV', ['veterinary', 'medicines', 'laboratory'], status='suspended',
                             organisation_number='998877665')
        self.vet.sites.add(self.bergen, self.tromso)
        self.parts = self.make('Pumpe Partner', 'PP', ['equipment'], status='blocked', country='Denmark')

    def codes(self, **query):
        return [s.code for s in self.client.get(reverse('farm:supplier_list'), query).context['objects']]

    def test_listed_by_name(self):
        self.assertEqual(self.codes(), ['FJF', 'HV', 'PP'])

    def test_columns(self):
        response = self.client.get(reverse('farm:supplier_list'))
        # In the order of the categories, whatever order they were ticked in.
        self.assertContains(response, '<td>Medicines and vaccines, Veterinary and fish health, Laboratory analyses</td>',
                            html=True)
        self.assertContains(response, '<span class="row-sub">HV · 998877665</span>', html=True)
        self.assertContains(response, '<td>Bergen, Norway</td>', html=True)
        self.assertContains(response, '<td>Bergen, Tromso</td>', html=True)
        self.assertContains(response, '4/5')
        self.assertContains(response, '<span class="badge badge-blocked">Blocked</span>', html=True)
        self.assertContains(response, '<span class="badge badge-suspended">Suspended</span>', html=True)

    def test_search_covers_name_code_organisation_number_email_and_place(self):
        self.assertEqual(self.codes(q='havet'), ['HV'])
        self.assertEqual(self.codes(q='pp'), ['PP'])
        self.assertEqual(self.codes(q='998877'), ['HV'])
        self.assertEqual(self.codes(q='orders@'), ['FJF'])
        self.assertEqual(self.codes(q='bergen'), ['FJF'])
        self.assertEqual(self.codes(q='denmark'), ['PP'])

    def test_filters(self):
        self.assertEqual(self.codes(supplies='transport'), ['FJF'])
        self.assertEqual(self.codes(supplies='medicines'), ['HV'])
        self.assertEqual(self.codes(supplies='diving'), [])
        self.assertEqual(self.codes(status='blocked'), ['PP'])
        self.assertEqual(self.codes(site=self.tromso.pk), ['HV'])
        self.assertEqual(self.codes(site=self.bergen.pk), ['FJF', 'HV'])
        self.assertEqual(self.codes(site=self.bergen.pk, supplies='feed', q='fjord'), ['FJF'])
        self.assertEqual(len(self.codes(supplies='pizza', status='x', site='y')), 3)

    def test_the_list_is_paged_and_the_pages_keep_the_search_and_filters(self):
        Supplier.objects.bulk_create([Supplier(name=f'Bulk {n:02}', code=f'B{n:02}', supplies=['other'])
                                      for n in range(60)])
        first = self.client.get(reverse('farm:supplier_list'), {'supplies': 'other'})
        self.assertEqual(len(first.context['objects']), 50)
        self.assertContains(first, '?supplies=other&amp;page=2')
        second = self.client.get(reverse('farm:supplier_list'), {'supplies': 'other', 'page': '2'})
        self.assertEqual([s.code for s in second.context['objects']], [f'B{n:02}' for n in range(50, 60)])

    def test_the_empty_list_invites_to_add_one(self):
        Supplier.objects.all().delete()
        response = self.client.get(reverse('farm:supplier_list'))
        self.assertContains(response, 'No suppliers yet')
        self.assertContains(response, 'Add supplier')


class SupplierSitesTests(SupplierTestCase):
    def test_deleting_a_site_keeps_the_link_and_restoring_it_brings_it_back(self):
        supplier = self.make()
        supplier.sites.add(self.bergen, self.tromso)
        page = self.client.get(reverse('farm:site_delete', args=[self.bergen.pk]))
        self.assertContains(page, 'Suppliers linked to it')
        self.assertContains(page, 'Fjord Feed AS (FJF)')
        self.client.post(reverse('farm:site_delete', args=[self.bergen.pk]))
        self.assertEqual(list(supplier.sites.all()), [self.tromso])
        # Saving the supplier keeps the link to the deleted site for its restore.
        self.edit(supplier, sites=[str(self.tromso.pk)], notes='edited')
        softdelete.restore(Site.all_objects.get(pk=self.bergen.pk), self.user)
        self.assertEqual(set(supplier.sites.all()), {self.bergen, self.tromso})


class EquipmentSupplierTests(TestCase):
    """Equipment.supplier: who a piece of equipment was bought from, a supplier of equipment and spare parts."""

    def setUp(self):
        self.user = get_user_model().objects.create_user('ali', 'ali@example.com', 'eski-sifre-123')
        self.user.groups.add(role('Manager', 'view_equipment', 'add_equipment', 'change_equipment',
                                  'delete_equipment', 'view_supplier', 'change_supplier', 'delete_supplier',
                                  'view_auditlog'))
        self.client.force_login(self.user)
        site = Site.objects.create(name='Bergen', code='BG')
        self.hall = ProductionDepartment.objects.create(site=site, name='Hall A', code='HA')
        self.ras = System.objects.create(site=site, name='RAS 1', code='R1')
        self.pump_type = EquipmentType.objects.get(code='pump-centrifugal')
        self.vendor = Supplier.objects.create(name='Pumpe Partner', code='PP', supplies=['equipment', 'maintenance'])
        self.idle = Supplier.objects.create(name='Old Pumps', code='OP', supplies=['equipment'], status='inactive')
        self.mill = Supplier.objects.create(name='Fjord Feed AS', code='FJF', supplies=['feed'])

    def data(self, **overrides):
        return equipment_data(self.pump_type, self.hall, [link(self.ras)], {'flowRate': '100'}, **overrides)

    def make(self, **fields):
        pump = Equipment.objects.create(name='Pump', code='P1', equipment_type=self.pump_type,
                                        production_department=self.hall, specifications={'flowRate': 100}, **fields)
        EquipmentSystem.objects.create(equipment=pump, system=self.ras, is_primary=True)
        return pump

    def test_choose_read_change_and_clear_the_supplier(self):
        # Choose
        self.client.post(reverse('farm:equipment_create'), self.data(supplier=str(self.vendor.pk)))
        pump = Equipment.objects.get()
        self.assertEqual(pump.supplier, self.vendor)
        # Read: the form shows it on the Details tab, the list in its own column
        form = self.client.get(reverse('farm:equipment_edit', args=[pump.pk])).context['form']
        self.assertEqual(form['supplier'].value(), self.vendor.pk)
        self.assertEqual(form.tab_of('supplier'), 'details')
        self.assertContains(self.client.get(reverse('farm:equipment_list')), '<td>Pumpe Partner</td>', html=True)
        # Change, then clear
        self.client.post(reverse('farm:equipment_edit', args=[pump.pk]), self.data(supplier=str(self.idle.pk),
                                                                                    version='1'))
        self.assertEqual(Equipment.objects.get().supplier, self.idle)
        self.client.post(reverse('farm:equipment_edit', args=[pump.pk]), self.data(supplier='', version='2'))
        self.assertIsNone(Equipment.objects.get().supplier)
        created, changed, cleared = AuditLog.objects.order_by('created_at')
        self.assertEqual(created.changes['Supplier'], [None, 'Pumpe Partner (PP)'])
        self.assertEqual(changed.changes, {'Supplier': ['Pumpe Partner (PP)', 'Old Pumps (OP)']})
        self.assertEqual(cleared.changes, {'Supplier': ['Old Pumps (OP)', None]})

    def test_only_live_suppliers_of_equipment_are_offered_with_the_status_of_those_not_active(self):
        deleted = Supplier.objects.create(name='Gone Pumps', code='GP', supplies=['equipment'])
        deleted.soft_delete(self.user)
        field = self.client.get(reverse('farm:equipment_create')).context['form'].fields['supplier']
        self.assertEqual(list(field.queryset), [self.idle, self.vendor])
        self.assertEqual([label for value, label in field.choices],
                         ['None', 'Old Pumps (OP) · Inactive', 'Pumpe Partner (PP)'])
        for supplier in (self.mill, deleted):
            response = self.client.post(reverse('farm:equipment_create'), self.data(supplier=str(supplier.pk)))
            self.assertIn('supplier', response.context['form'].errors)
        self.assertFalse(Equipment.objects.exists())

    def test_the_model_refuses_a_supplier_that_does_not_supply_equipment(self):
        pump = self.make()
        pump.supplier = self.mill
        with self.assertRaisesMessage(ValidationError, 'Choose a supplier of equipment and spare parts.'):
            pump.full_clean()
        pump.supplier = self.vendor
        pump.full_clean()

    def test_a_supplier_keeps_equipment_while_equipment_is_bought_from_it(self):
        self.make(supplier=self.vendor)
        response = self.client.post(reverse('farm:supplier_edit', args=[self.vendor.pk]), supplier_data(
            name='Pumpe Partner', code='PP', supplies=['maintenance'], version='1'))
        self.assertEqual(response.context['form'].errors['supplies'], [
            '1 piece of equipment is bought from it: keep “Equipment and spare parts” ticked, or choose another '
            'supplier for it first.'])
        self.assertEqual(stored(self.vendor, 'supplies'), (['equipment', 'maintenance'],))
        Equipment.objects.update(supplier=None)
        self.client.post(reverse('farm:supplier_edit', args=[self.vendor.pk]), supplier_data(
            name='Pumpe Partner', code='PP', supplies=['maintenance'], version='1'))
        self.assertEqual(stored(self.vendor, 'supplies'), (['maintenance'],))

    def test_deleting_the_supplier_leaves_its_equipment_without_one_and_logs_it(self):
        pump = self.make(supplier=self.vendor)
        page = self.client.get(reverse('farm:supplier_delete', args=[self.vendor.pk]))
        self.assertContains(page, 'Equipment that lose their supplier')
        self.assertContains(page, 'Pump (P1)')
        (group,) = plan_delete(self.vendor).detached_groups()
        self.assertEqual((group['label'], group['link'], group['records']), ('Equipment', 'supplier', [pump]))
        self.client.post(reverse('farm:supplier_delete', args=[self.vendor.pk]))
        pump.refresh_from_db()
        self.assertEqual((pump.supplier, pump.version, pump.updated_by, pump.is_deleted), (None, 2, self.user, False))
        self.assertEqual(sorted(AuditLog.objects.values_list('action', 'entity_type', 'entity_label', 'changes')), [
            ('delete', 'supplier', 'Pumpe Partner (PP)', {}),
            ('update', 'equipment', 'Pump (P1)', {'Supplier': ['Pumpe Partner (PP)', None]}),
        ])

    def test_restoring_equipment_needs_its_supplier_back(self):
        pump = self.make(supplier=self.vendor)
        pump.soft_delete(self.user)
        self.vendor.soft_delete(self.user)
        with self.assertRaisesMessage(ValidationError, 'Supplier “Pumpe Partner (PP)” is deleted.'):
            softdelete.restore(Equipment.all_objects.get(pk=pump.pk), self.user)
        softdelete.restore(Supplier.all_objects.get(pk=self.vendor.pk), self.user)
        softdelete.restore(Equipment.all_objects.get(pk=pump.pk), self.user)
        self.assertEqual(Equipment.objects.get().supplier, self.vendor)


class SupplierDeleteAndRestoreTests(SupplierTestCase):
    def test_a_supplier_without_equipment_deletes_plainly_and_keeps_its_contacts(self):
        supplier = self.make()
        supplier.contacts.create(name='Kari', is_primary=True)
        plan = plan_delete(supplier)
        self.assertTrue(plan.can_delete)
        self.assertEqual((plan.cascade, plan.detach, plan.unlinked), ([], [], []))
        page = self.client.get(reverse('farm:supplier_delete', args=[supplier.pk]))
        self.assertContains(page, 'Delete “Fjord Feed AS (FJF)”?')
        self.client.post(reverse('farm:supplier_delete', args=[supplier.pk]))
        self.assertEqual(list(AuditLog.objects.values_list('action', 'entity_type', 'entity_label')),
                         [('delete', 'supplier', 'Fjord Feed AS (FJF)')])
        self.assertEqual(Supplier.all_objects.get().contacts.count(), 1)

    def test_a_deleted_supplier_cannot_be_edited_or_deleted_again(self):
        supplier = self.make()
        supplier.soft_delete(self.user)
        for url in (reverse('farm:supplier_edit', args=[supplier.pk]), reverse('farm:supplier_delete', args=[supplier.pk]),
                    reverse('farm:supplier_contacts', args=[supplier.pk])):
            self.assertEqual(self.client.post(url, supplier_data()).status_code, 404, url)

    def test_restore_brings_it_back_unless_its_name_or_code_was_taken_meanwhile(self):
        supplier = self.make(organisation_number='923456789')
        supplier.soft_delete(self.user)
        other = self.make('FJORD FEED AS', 'OTH')
        with self.assertRaisesMessage(ValidationError, 'Another supplier already has this name.'):
            softdelete.restore(Supplier.all_objects.get(pk=supplier.pk), self.user)
        other.soft_delete(self.user)
        self.make('Other', 'X2', organisation_number='923456789')
        with self.assertRaisesMessage(ValidationError, 'Another supplier already has this organisation number.'):
            softdelete.restore(Supplier.all_objects.get(pk=supplier.pk), self.user)
        Supplier.objects.filter(code='X2').update(organisation_number='')
        softdelete.restore(Supplier.all_objects.get(pk=supplier.pk), self.user)
        self.assertEqual(stored(supplier, 'is_deleted', 'version'), (False, 3))
        self.assertEqual(AuditLog.objects.get(action='restore').entity_label, 'Fjord Feed AS (FJF)')

    def test_the_admin_lists_deleted_suppliers_and_restores_them(self):
        root = get_user_model().objects.create_superuser('root', 'root@example.com', 'x')
        self.client.force_login(root)
        supplier = self.make()
        supplier.soft_delete(root)
        self.assertEqual(admin.site._registry[Supplier].list_display, ['name', 'code', 'status', 'is_deleted'])
        page = self.client.get(reverse('admin:farm_supplier_changelist'), {'q': 'fjord'})
        self.assertContains(page, 'Fjord Feed AS')
        self.assertNotContains(page, reverse('admin:farm_supplier_add'))
        response = self.client.post(reverse('admin:farm_supplier_changelist'),
                                    {'action': 'restore', '_selected_action': [str(supplier.pk)]}, follow=True)
        self.assertContains(response, '1 record restored.')
        self.assertTrue(Supplier.objects.filter(pk=supplier.pk).exists())


class SupplierAuditTests(SupplierTestCase):
    def test_create_edit_and_delete_are_logged_with_old_and_new_values(self):
        self.create(supplies=['transport', 'feed'], rating='3', sites=[str(self.bergen.pk)])
        supplier = Supplier.objects.get()
        self.edit(supplier, supplies=['feed', 'live_fish'], rating='3', status='blocked',
                  sites=[str(self.bergen.pk), str(self.tromso.pk)])
        self.client.post(reverse('farm:supplier_delete', args=[supplier.pk]))
        created, edited, deleted = AuditLog.objects.order_by('created_at')
        self.assertEqual((created.action, created.entity_type, created.entity_label),
                         ('create', 'supplier', 'Fjord Feed AS (FJF)'))
        self.assertEqual(created.changes, {
            'Name': [None, 'Fjord Feed AS'], 'Code': [None, 'FJF'],
            'Supplies': [None, [message('Feed'), message('Wellboat and transport')]],
            'Status': [None, message('Active')], 'Rating': [None, message('3')], 'Sites served': [None, 'Bergen (BG)'],
        })
        self.assertEqual(edited.changes, {
            'Supplies': [[message('Feed'), message('Wellboat and transport')],
                         [message('Live fish and eggs'), message('Feed')]],
            'Status': [message('Active'), message('Blocked')],
            'Sites served': ['Bergen (BG)', 'Bergen (BG), Tromso (TR)'],
        })
        self.assertEqual((deleted.action, deleted.entity_type), ('delete', 'supplier'))

    def test_the_log_is_english_and_shown_in_the_readers_language(self):
        Profile.objects.create(user=self.user, language='tr')
        self.create(supplies=['feed', 'diving'])
        entry = AuditLog.objects.get()
        self.assertEqual(entry.changes['Supplies'], [None, [message('Feed'), message('Diving and ROV')]])
        with translation.override('en'):
            self.assertIn(('Supplies', None, 'Feed, Diving and ROV'), entry.shown_changes())
        with translation.override('nb'):
            self.assertEqual(entry.shown_type(), 'leverandør')
            self.assertIn(('Leveranser', None, 'Fôr, Dykking og ROV'), entry.shown_changes())

    def test_the_history_tab_shows_the_changes(self):
        self.create()
        supplier = Supplier.objects.get()
        self.assertEqual(len(self.client.get(reverse('farm:supplier_edit', args=[supplier.pk])).context['history']), 1)


class SupplierPermissionTests(SupplierTestCase):
    def as_role(self, *codenames):
        person = get_user_model().objects.create_user(f'user{len(codenames)}', 'x@example.com', 'x')
        person.groups.add(role(f'Role {len(codenames)}', *codenames))
        self.client.force_login(person)

    def test_a_read_only_role_sees_suppliers_but_cannot_change_them(self):
        supplier = self.make()
        self.as_role('view_supplier')
        response = self.client.get(reverse('farm:supplier_list'))
        self.assertContains(response, 'Fjord Feed AS')
        for url in (reverse('farm:supplier_create'), reverse('farm:supplier_edit', args=[supplier.pk]),
                    reverse('farm:supplier_delete', args=[supplier.pk])):
            self.assertNotContains(response, url)
            self.assertEqual(self.client.post(url, supplier_data()).status_code, 403, url)
        self.assertEqual(stored(supplier, 'is_deleted', 'version'), (False, 1))

    def test_each_action_needs_its_own_permission(self):
        supplier = self.make()
        self.as_role('view_supplier', 'add_supplier')
        self.create(name='Other', code='OTH')
        self.assertTrue(Supplier.objects.filter(code='OTH').exists())
        self.assertEqual(self.edit(supplier, name='Changed').status_code, 403)
        self.as_role('view_supplier', 'change_supplier', 'delete_supplier')
        self.assertEqual(self.create(code='NEW').status_code, 403)
        self.edit(supplier, name='Changed')
        self.assertEqual(stored(supplier, 'name'), ('Changed',))
        self.client.post(reverse('farm:supplier_delete', args=[supplier.pk]))
        self.assertTrue(Supplier.all_objects.get(pk=supplier.pk).is_deleted)

    def test_no_view_permission_no_tab_and_no_menu_entry(self):
        self.as_role()
        self.assertEqual(self.client.get(reverse('farm:supplier_list')).status_code, 403)
        self.assertNotContains(self.client.get(reverse('production_home')), reverse('farm:supplier_list'))

    def test_the_menu_and_the_role_matrix_place_it_under_purchasing(self):
        response = self.client.get(reverse('farm:supplier_list'))
        self.assertContains(response, f'href="{reverse("farm:supplier_list")}"')
        self.assertContains(response, '<p class="rail-group">Purchasing</p>', html=True)
        self.assertEqual(str(response.context['group']), 'Purchasing')
        self.assertEqual(str(navigation.place('farm.view_supplier').path), 'Production · Setup · Purchasing')
        (area,) = [area for area in access.areas() if area.model == 'farm.Supplier']
        self.assertEqual((str(area.label), str(area.group)), ('Suppliers', 'Production · Setup · Purchasing'))
        self.assertEqual(SupplierResource.entity_type(), 'supplier')


class SupplierLanguageTests(SupplierTestCase):
    def test_the_tab_speaks_each_language(self):
        self.make(supplies=['feed', 'veterinary'], status='blocked')
        for language, words in {
            'tr': ('<h1>Tedarikçiler</h1>', 'Yeni tedarikçi', 'Satın alma', 'Yem, Veteriner ve balık sağlığı',
                   'Engellendi'),
            'nb': ('<h1>Leverandører</h1>', 'Legg til leverandør', 'Innkjøp', 'Fôr, Veterinær og fiskehelse',
                   'Sperret'),
        }.items():
            Profile.objects.update_or_create(user=self.user, defaults={'language': language})
            response = self.client.get(reverse('farm:supplier_list'))
            for word in words:
                self.assertContains(response, word, msg_prefix=language)


class SupplierDatabaseViewerTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser('root', 'root@example.com', 'x'))

    def test_the_tables_are_shown_with_their_descriptions_and_constraints(self):
        tables = {table.name: table for _, tables in database.sections() for table in tables}
        self.assertEqual(tables['suppliers'].description,
                         'A company the farm buys from: what it supplies (goods, live fish, services), how to reach it '
                         'and on which terms.')
        self.assertEqual(tables['supplier_contacts'].description,
                         'A person to contact at a supplier: sales, orders, technical support, the vet on call.')
        self.assertEqual(tables['supplier_sites'].description, 'Which sites each supplier delivers to or works at.')
        structure = tables['suppliers'].structure()
        names = {constraint.name for constraint in structure.constraints} | {index.name for index in structure.indexes}
        self.assertTrue({'uq_suppliers_code_live', 'uq_suppliers_name_live', 'uq_suppliers_organisation_number_live',
                         'chk_suppliers_supplies', 'chk_suppliers_supplies_not_empty', 'chk_suppliers_rating'} <= names)
        self.assertEqual(next(column.type for column in structure.columns if column.name == 'supplies'), 'text[]')
        equipment = {column.name: column for column in tables['equipment'].structure().columns}
        self.assertEqual((equipment['supplier_id'].reference.table, equipment['supplier_id'].nullable),
                         ('suppliers', True))

    def test_what_it_supplies_is_shown_and_filtered_as_the_database_prints_it(self):
        Supplier.objects.create(name='Fjord Feed AS', code='FJF', supplies=['feed', 'transport'])
        Supplier.objects.create(name='Havet Vet', code='HV', supplies=['veterinary'])
        response = self.client.get(reverse('core:database_table', args=['suppliers']), {'f_supplies': 'transport'})
        grid = response.context['grid']
        index = [column.name for column in grid.columns].index('supplies')
        self.assertEqual([row.cells[index].text for row in grid.rows], ['{feed,transport}'])

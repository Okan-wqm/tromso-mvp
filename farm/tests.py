from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from core.models import AuditLog

from .models import Site, SiteContact


def site_data(**overrides):
    data = {
        'name': 'Main Production Site', 'code': 'mps-001', 'type': 'land_based', 'status': 'active',
        'lokalitetsnummer': '', 'organisation_number_override': '', 'description': '', 'area_m2': '',
        'timezone': '', 'country': 'Norway', 'region': 'Vestland', 'street': '', 'city': '', 'state': '',
        'postal_code': '', 'latitude': '', 'longitude': '', 'altitude': '', 'site_manager': '',
        'contact_email': '', 'contact_phone': '',
    }
    data.update(overrides)
    return data


def contacts_data(rows, initial=0):
    data = {
        'contacts-TOTAL_FORMS': str(len(rows)), 'contacts-INITIAL_FORMS': str(initial),
        'contacts-MIN_NUM_FORMS': '0', 'contacts-MAX_NUM_FORMS': '1000',
    }
    for i, row in enumerate(rows):
        for key, value in row.items():
            if value is True:
                data[f'contacts-{i}-{key}'] = 'on'
            elif value is not False:
                data[f'contacts-{i}-{key}'] = value
    return data


class SiteTestCase(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('ali', 'ali@example.com', 'eski-sifre-123')
        self.client.force_login(self.user)

    def make_site(self, **fields):
        fields.setdefault('name', 'Site A')
        fields.setdefault('code', 'SA')
        return Site.objects.create(**fields)


class SiteRoundTripTests(SiteTestCase):
    """Every field the site form shows is stored, read back, edited and deleted through the pages."""

    def test_site_create_read_edit_delete(self):
        full = site_data(
            name='Bergen Hatchery', code='bh-01', lokalitetsnummer='12345',
            organisation_number_override='987654321', description='Smolt production',
            type='hatchery', status='maintenance', area_m2='50000.50', timezone='Europe/Oslo',
            country='Norway', region='Vestland', street='Kaien 1', city='Bergen', state='Vestland',
            postal_code='5003', latitude='60.391300', longitude='5.322100', altitude='12.50',
            site_manager='Kari Nordmann', contact_email='kari@example.com', contact_phone='+47 123 45 678',
        )
        # Create
        self.client.post(reverse('farm:site_create'), full)
        site = Site.objects.get()
        stored = {field: str(getattr(site, field)) for field in full}
        expected = dict(full, code='BH-01')
        self.assertEqual(stored, expected)

        # Read: the list shows it and the edit form is filled from the database
        self.assertContains(self.client.get(reverse('farm:site_list')), 'Bergen Hatchery')
        form = self.client.get(reverse('farm:site_edit', args=[site.pk])).context['form']
        self.assertEqual(form['contact_email'].value(), 'kari@example.com')
        self.assertEqual(form['version'].value(), 1)

        # Edit: change values and clear optional ones
        self.client.post(reverse('farm:site_edit', args=[site.pk]), dict(
            full, name='Bergen Smolt', status='active', latitude='', longitude='', altitude='',
            lokalitetsnummer='', contact_email='', version='1',
        ))
        site.refresh_from_db()
        self.assertEqual((site.name, site.status, site.version), ('Bergen Smolt', 'active', 2))
        self.assertIsNone(site.latitude)
        self.assertIsNone(site.lokalitetsnummer)
        self.assertEqual(site.contact_email, '')

        # Delete
        self.client.post(reverse('farm:site_delete', args=[site.pk]))
        self.assertFalse(Site.objects.exists())
        self.assertEqual(list(self.client.get(reverse('farm:site_list')).context['sites']), [])
        self.assertTrue(Site.all_objects.get(pk=site.pk).is_deleted)

    def test_contact_create_read_edit_delete(self):
        site = self.make_site()
        url = reverse('farm:site_contacts', args=[site.pk])
        # Create
        self.client.post(url, contacts_data([
            {'name': 'Kari', 'role': 'Manager', 'email': 'kari@example.com', 'phone': '+47 1', 'is_primary': True},
        ]))
        kari = site.contacts.get()
        self.assertEqual((kari.name, kari.role, kari.email, kari.phone, kari.is_primary, kari.created_by),
                         ('Kari', 'Manager', 'kari@example.com', '+47 1', True, self.user))
        # Read: the edit page lists the stored contact
        page = self.client.get(reverse('farm:site_edit', args=[site.pk]))
        self.assertEqual(page.context['contacts'].forms[0]['email'].value(), 'kari@example.com')
        # Edit
        self.client.post(url, contacts_data([
            {'id': str(kari.pk), 'name': 'Kari N.', 'role': 'Vet', 'email': '', 'phone': '', 'is_primary': False},
        ], initial=1))
        self.assertEqual(list(site.contacts.values_list('name', 'role', 'email', 'is_primary')),
                         [('Kari N.', 'Vet', '', False)])
        # Delete
        edited = site.contacts.get()
        self.client.post(url, contacts_data([{'id': str(edited.pk), 'name': 'Kari N.', 'DELETE': True}], initial=1))
        self.assertFalse(site.contacts.exists())


class SiteAuditTests(SiteTestCase):
    def log(self):
        return list(AuditLog.objects.order_by('created_at').values_list('action', 'user_name', 'changes'))

    def test_create_edit_contacts_and_delete_are_logged_with_old_and_new_values(self):
        self.client.post(reverse('farm:site_create'), site_data(name='Bergen', code='bh', area_m2='100'))
        site = Site.objects.get()
        self.client.post(reverse('farm:site_edit', args=[site.pk]),
                         site_data(name='Bergen', code='bh', area_m2='250', status='maintenance', version='1'))
        self.client.post(reverse('farm:site_contacts', args=[site.pk]),
                         contacts_data([{'name': 'Kari', 'role': 'Vet', 'is_primary': True}]))
        self.client.post(reverse('farm:site_delete', args=[site.pk]))

        created, edited, contacts, deleted = self.log()
        self.assertEqual(created[:2], ('create', 'ali'))
        self.assertEqual(created[2]['Site code'], [None, 'BH'])
        self.assertEqual(created[2]['Total area (m²)'], [None, '100.00'])
        self.assertEqual(edited, ('update', 'ali', {
            'Total area (m²)': ['100.00', '250.00'], 'Status': ['Active', 'Under maintenance'],
        }))
        self.assertEqual(contacts, ('update', 'ali', {'Contacts': [None, 'Kari (Vet, primary)']}))
        self.assertEqual(deleted, ('delete', 'ali', {}))

    def test_saving_without_changes_logs_nothing(self):
        site = self.make_site(name='Same', code='SM', area_m2='100.00', latitude='60.391300', longitude='5.322100')
        # Same values typed differently (100 vs 100.00) are not a change.
        self.client.post(reverse('farm:site_edit', args=[site.pk]), site_data(
            name='Same', code='SM', country='', region='', area_m2='100', latitude='60.3913', longitude='5.3221',
            version='1',
        ))
        self.assertEqual(self.log(), [])

    def test_history_tab_shows_the_site_changes(self):
        self.client.post(reverse('farm:site_create'), site_data(name='Bergen', code='bh'))
        site = Site.objects.get()
        response = self.client.get(reverse('farm:site_edit', args=[site.pk]))
        self.assertEqual([entry.action for entry in response.context['history']], ['create'])
        self.assertContains(response, 'id="panel-history"')


class SiteAccessTests(TestCase):
    def test_site_pages_need_sign_in(self):
        response = self.client.get(reverse('farm:site_list'))
        self.assertRedirects(response, reverse('login') + '?next=' + reverse('farm:site_list'))


class SiteCreateTests(SiteTestCase):
    def test_create_uppercases_code_and_records_author(self):
        response = self.client.post(reverse('farm:site_create'), site_data())
        site = Site.objects.get()
        self.assertRedirects(response, reverse('farm:site_edit', args=[site.pk]))
        self.assertEqual(site.code, 'MPS-001')
        self.assertEqual(site.created_by, self.user)
        self.assertEqual(site.version, 1)
        self.assertEqual(site.timezone, '')

    def test_name_and_code_are_required_and_code_needs_two_characters(self):
        response = self.client.post(reverse('farm:site_create'), site_data(name=' ', code='x'))
        form = response.context['form']
        self.assertIn('name', form.errors)
        self.assertEqual(form.errors['code'], ['Code must be at least 2 characters.'])
        self.assertFalse(Site.objects.exists())

    def test_duplicate_code_and_name_rejected_among_live_sites(self):
        self.make_site(name='Main Production Site', code='MPS-001')
        response = self.client.post(reverse('farm:site_create'), site_data())
        form = response.context['form']
        self.assertEqual(form.errors['code'], ['Another site already uses this site code.'])
        self.assertEqual(form.errors['name'], ['Another site already uses this site name.'])
        self.assertEqual(Site.objects.count(), 1)

    def test_deleted_site_frees_its_code_and_name(self):
        self.make_site(name='Main Production Site', code='MPS-001').soft_delete(self.user)
        self.client.post(reverse('farm:site_create'), site_data())
        self.assertEqual(Site.objects.count(), 1)
        self.assertEqual(Site.all_objects.count(), 2)

    def test_lokalitetsnummer_must_be_five_digits_and_unique(self):
        response = self.client.post(reverse('farm:site_create'), site_data(lokalitetsnummer='9999'))
        self.assertIn('lokalitetsnummer', response.context['form'].errors)
        self.make_site(lokalitetsnummer=12345)
        response = self.client.post(reverse('farm:site_create'), site_data(lokalitetsnummer='12345'))
        self.assertEqual(response.context['form'].errors['lokalitetsnummer'],
                         ['Another site already uses this lokalitetsnummer.'])

    def test_sea_cage_needs_coordinates(self):
        response = self.client.post(reverse('farm:site_create'), site_data(type='sea_cage'))
        form = response.context['form']
        self.assertEqual(form.errors['latitude'], ['Latitude is required for a sea cage.'])
        self.assertEqual(form.errors['longitude'], ['Longitude is required for a sea cage.'])
        self.client.post(reverse('farm:site_create'), site_data(type='sea_cage', latitude='60.3913', longitude='5.3221'))
        self.assertEqual(Site.objects.get().type, 'sea_cage')

    def test_coordinates_come_in_pairs_and_stay_in_range(self):
        response = self.client.post(reverse('farm:site_create'), site_data(latitude='60.1'))
        self.assertEqual(response.context['form'].errors['longitude'],
                         ['Latitude and longitude must be provided together.'])
        response = self.client.post(reverse('farm:site_create'), site_data(latitude='91', longitude='5'))
        self.assertIn('latitude', response.context['form'].errors)

    def test_errors_mark_their_tab(self):
        response = self.client.post(reverse('farm:site_create'), site_data(type='sea_cage'))
        tabs = {tab['key']: tab['has_errors'] for tab in response.context['form'].tabs()}
        self.assertEqual(tabs, {'basic': False, 'location': True, 'contact': False})


class SiteDatabaseConstraintTests(SiteTestCase):
    def test_database_rejects_sea_cage_without_coordinates(self):
        with self.assertRaises(IntegrityError):
            self.make_site(type='sea_cage')

    def test_database_rejects_two_primary_contacts(self):
        site = self.make_site()
        SiteContact.objects.create(site=site, name='A', is_primary=True)
        with self.assertRaises(IntegrityError), transaction.atomic():
            SiteContact.objects.create(site=site, name='B', is_primary=True)


class SiteListTests(SiteTestCase):
    def test_list_searches_name_code_and_region_and_hides_deleted(self):
        self.make_site(name='Bergen Hatchery', code='BH', region='Vestland')
        self.make_site(name='Tromsø Smolt', code='TS', region='Troms')
        self.make_site(name='Old Site', code='OS').soft_delete(self.user)

        names = lambda response: [site.name for site in response.context['sites']]
        self.assertEqual(names(self.client.get(reverse('farm:site_list'))), ['Bergen Hatchery', 'Tromsø Smolt'])
        self.assertEqual(names(self.client.get(reverse('farm:site_list'), {'q': 'troms'})), ['Tromsø Smolt'])
        self.assertEqual(names(self.client.get(reverse('farm:site_list'), {'q': 'bh'})), ['Bergen Hatchery'])

    def test_empty_list_invites_to_add_a_site(self):
        self.assertContains(self.client.get(reverse('farm:site_list')), 'No sites yet')

    def test_rail_marks_sites_as_current(self):
        response = self.client.get(reverse('farm:site_list'))
        self.assertContains(response, f'href="{reverse("farm:site_list")}" title="Sites" aria-current="page"')


class SiteEditTests(SiteTestCase):
    def test_edit_saves_and_bumps_version(self):
        site = self.make_site()
        self.client.post(reverse('farm:site_edit', args=[site.pk]), site_data(name='Renamed', code='sa', version='1'))
        site.refresh_from_db()
        self.assertEqual((site.name, site.code, site.version, site.updated_by), ('Renamed', 'SA', 2, self.user))

    def test_stale_version_is_refused(self):
        site = self.make_site()
        Site.objects.filter(pk=site.pk).update(version=2, name='Changed elsewhere')
        response = self.client.post(reverse('farm:site_edit', args=[site.pk]),
                                    site_data(name='Mine', code='SA', version='1'), follow=True)
        self.assertContains(response, 'Someone else changed this site')
        site.refresh_from_db()
        self.assertEqual(site.name, 'Changed elsewhere')

    def test_deleted_site_cannot_be_opened(self):
        site = self.make_site()
        site.soft_delete(self.user)
        self.assertEqual(self.client.get(reverse('farm:site_edit', args=[site.pk])).status_code, 404)


class SiteContactTests(SiteTestCase):
    def setUp(self):
        super().setUp()
        self.site = self.make_site()
        self.url = reverse('farm:site_contacts', args=[self.site.pk])

    def test_save_contacts_with_one_primary(self):
        self.client.post(self.url, contacts_data([
            {'name': 'Kari', 'role': 'Manager', 'email': 'kari@example.com', 'is_primary': True},
            {'name': 'Ola', 'phone': '+47 123 45 678'},
        ]))
        contacts = list(self.site.contacts.values_list('name', 'is_primary'))
        self.assertEqual(contacts, [('Kari', True), ('Ola', False)])

    def test_two_primaries_are_rejected(self):
        response = self.client.post(self.url, contacts_data([
            {'name': 'Kari', 'is_primary': True}, {'name': 'Ola', 'is_primary': True},
        ]))
        self.assertContains(response, 'Only one contact can be the primary contact; 2 are marked.')
        self.assertFalse(self.site.contacts.exists())

    def test_primary_moves_and_removed_rows_go(self):
        kari = SiteContact.objects.create(site=self.site, name='Kari', is_primary=True)
        ola = SiteContact.objects.create(site=self.site, name='Ola')
        per = SiteContact.objects.create(site=self.site, name='Per')
        self.client.post(self.url, contacts_data([
            {'id': str(kari.pk), 'name': 'Kari', 'is_primary': False},
            {'id': str(ola.pk), 'name': 'Ola', 'is_primary': True},
            {'id': str(per.pk), 'name': 'Per', 'DELETE': True},
        ], initial=3))
        contacts = list(self.site.contacts.values_list('name', 'is_primary'))
        self.assertEqual(contacts, [('Ola', True), ('Kari', False)])

    def test_blank_name_is_rejected(self):
        response = self.client.post(self.url, contacts_data([{'name': '', 'role': 'Vet'}]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['open_tab'], 'contact')
        self.assertFalse(self.site.contacts.exists())


class SiteDeleteTests(SiteTestCase):
    def test_delete_asks_first_then_soft_deletes(self):
        site = self.make_site()
        self.assertContains(self.client.get(reverse('farm:site_delete', args=[site.pk])), 'Delete “Site A” (SA)?')
        response = self.client.post(reverse('farm:site_delete', args=[site.pk]))
        self.assertRedirects(response, reverse('farm:site_list'))
        site = Site.all_objects.get(pk=site.pk)
        self.assertTrue(site.is_deleted)
        self.assertEqual(site.deleted_by, self.user)
        self.assertIsNotNone(site.deleted_at)

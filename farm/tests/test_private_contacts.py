"""A contact's e-mail and phone are private in the activity log (owner decision F-059, 2026-11-10): the log is append-only,
so a contact person's address written into it could never be erased. A site's and a supplier's contact list and a
site's own contact e-mail and phone are logged with the keyed digest of core.audit: the log shows who the contact is
(name, role), that the e-mail or the phone changed and whether two were equal, never the address or the number."""
from django.urls import reverse

from core import audit
from core.models import AuditLog

from ..models import Site, SiteContact, Supplier
from .helpers import contacts_data, role, site_data
from .test_sites import SiteTestCase

KARI = {'name': 'Kari', 'role': 'Vet', 'email': 'kari@example.com', 'phone': '+47 98989898', 'is_primary': True}
OLA = {'name': 'Ola', 'role': '', 'email': 'kari@example.com', 'phone': '', 'is_primary': False}     # the same address


def said(email=None, phone=None):
    parts = ([f'email #{audit.digest(email)}'] if email else []) + ([f'phone #{audit.digest(phone)}'] if phone else [])
    return ', '.join(parts)


class ContactLogTests(SiteTestCase):
    def setUp(self):
        super().setUp()
        self.site = self.make_site()
        self.url = reverse('farm:site_contacts', args=[self.site.pk])

    def save(self, rows, url=None, record=None):
        return self.client.post(url or self.url, contacts_data(rows, record=record or self.site))

    def logged(self, record=None):
        return [entry.changes['Contacts'] for entry in AuditLog.objects.filter(
            entity_id=str((record or self.site).pk), changes__has_key='Contacts').order_by('created_at')]

    def assertNothingPlain(self):
        everything = str(list(AuditLog.objects.values_list('changes', 'entity_label')))
        for value in ('kari@example.com', 'kari@new.example', '98989898', '+47 1', '+47 2'):
            self.assertNotIn(value, everything)

    def test_the_log_names_the_contact_and_keeps_the_address_and_the_number_private(self):
        self.save([KARI, OLA])
        contact = SiteContact.objects.get(name='Kari')
        self.assertEqual((contact.email, contact.phone), ('kari@example.com', '+47 98989898'))     # the record keeps them
        self.assertEqual(self.logged(), [[None, (
            f'Kari (Vet, {said("kari@example.com", "+47 98989898")}, primary); Ola ({said("kari@example.com")})')]])
        # equal values read as equal: Kari and Ola share an address, and the log shows it without saying it
        self.assertEqual(self.logged()[0][1].count(f'email #{audit.digest("kari@example.com")}'), 2)
        self.assertNothingPlain()

    def test_a_changed_address_or_number_is_a_change_the_log_shows(self):
        self.save([KARI])
        self.save([{**KARI, 'email': 'kari@new.example'}])
        self.save([{**KARI, 'email': 'kari@new.example', 'phone': ''}])
        self.save([{**KARI, 'email': 'kari@new.example', 'phone': ''}])           # nothing changed: nothing logged
        first = f'Kari (Vet, {said("kari@example.com", "+47 98989898")}, primary)'
        second = f'Kari (Vet, {said("kari@new.example", "+47 98989898")}, primary)'
        third = f'Kari (Vet, {said("kari@new.example")}, primary)'
        self.assertEqual(self.logged(), [[None, first], [first, second], [second, third]])
        self.assertNothingPlain()

    def test_a_contact_without_an_address_or_a_number_reads_as_before(self):
        self.save([{'name': 'Kari', 'role': 'Vet', 'is_primary': True}])
        self.assertEqual(self.logged(), [[None, 'Kari (Vet, primary)']])

    def test_a_suppliers_contacts_are_logged_the_same_way(self):
        self.user.groups.add(role('Supplier manager', 'view_supplier', 'change_supplier'))
        supplier = Supplier.objects.create(name='Fjord Feed', code='FF', supplies=['feed'])
        self.save([{**KARI, 'role': 'Sales', 'phone': '+47 1'}], reverse('farm:supplier_contacts', args=[supplier.pk]),
                  supplier)
        self.assertEqual(self.logged(supplier),
                         [[None, f'Kari (Sales, {said("kari@example.com", "+47 1")}, primary)']])
        self.assertNothingPlain()

    def test_a_sites_own_contact_email_and_phone_are_private_too(self):
        self.client.post(reverse('farm:site_create'), site_data(
            contact_email='kari@example.com', contact_phone='+47 98989898', site_manager='Kari Nordmann'))
        site = Site.objects.get(code='MPS-001')
        self.assertEqual((site.contact_email, site.contact_phone), ('kari@example.com', '+47 98989898'))
        created = AuditLog.objects.get(entity_id=str(site.pk), action='create').changes
        self.assertEqual((created['Contact email'], created['Contact phone'], created['Site manager']),
                         ([None, audit.private('kari@example.com')], [None, audit.private('+47 98989898')],
                          [None, 'Kari Nordmann']))
        self.client.post(reverse('farm:site_edit', args=[site.pk]), site_data(
            contact_email='kari@new.example', contact_phone='+47 98989898', site_manager='Kari Nordmann', version='1'))
        edited = AuditLog.objects.get(entity_id=str(site.pk), action='update').changes
        self.assertEqual(edited, {'Contact email': [audit.private('kari@example.com'),
                                                    audit.private('kari@new.example')]})
        self.assertNothingPlain()

"""A contact's e-mail and phone are private in the activity log (owner decision F-059, 2026-11-10): the log is append-only,
so a contact person's address written into it could never be erased. A site's and a supplier's contact list and their
own contact e-mail and phone are logged as private values (core.audit.private): the log shows who the contact is (name,
role, primary), that the e-mail or the phone changed and whether two were probably the same, never the address or the
number. The digest that says so is stored, never shown: not in the activity log and not on the History tab of the
record, which anyone who may edit the record reads (review R2)."""
import re

from django.contrib.auth import get_user_model
from django.urls import reverse

from core import audit
from core.models import AuditLog

from ..models import Site, SiteContact, Supplier
from .helpers import contacts_data, role, site_data
from .test_sites import SiteTestCase

KARI = {'name': 'Kari', 'role': 'Vet', 'email': 'kari@example.com', 'phone': '+47 98989898', 'is_primary': True}
OLA = {'name': 'Ola', 'role': '', 'email': 'kari@example.com', 'phone': '', 'is_primary': False}     # the same address
VALUES = ('kari@example.com', 'kari@new.example', '98989898', '+47 1', '+47 2', 'orders@fjordfeed.no')


def email(value):
    return audit.private(value, 'Email')


def phone(value):
    return audit.private(value, 'Phone')


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
        for value in VALUES:
            self.assertNotIn(value, everything)

    def test_the_log_names_the_contact_and_keeps_the_address_and_the_number_private(self):
        self.save([KARI, OLA])
        contact = SiteContact.objects.get(name='Kari')
        self.assertEqual((contact.email, contact.phone), ('kari@example.com', '+47 98989898'))     # the record keeps them
        self.assertEqual(self.logged(), [[None, [
            ['Kari (Vet, primary)', email('kari@example.com'), phone('+47 98989898')],
            ['Ola', email('kari@example.com')]]]])
        # equal values are equal in the stored row: Kari and Ola share an address, and nothing says which
        (_before, (kari, ola)), = self.logged()
        self.assertEqual(kari[1], ola[1])
        self.assertNothingPlain()

    def test_a_changed_address_or_number_is_a_change_the_log_shows(self):
        self.save([KARI])
        self.save([{**KARI, 'email': 'kari@new.example'}])
        self.save([{**KARI, 'email': 'kari@new.example', 'phone': ''}])
        self.save([{**KARI, 'email': 'kari@new.example', 'phone': ''}])           # nothing changed: nothing logged
        first = [['Kari (Vet, primary)', email('kari@example.com'), phone('+47 98989898')]]
        second = [['Kari (Vet, primary)', email('kari@new.example'), phone('+47 98989898')]]
        third = [['Kari (Vet, primary)', email('kari@new.example')]]
        self.assertEqual(self.logged(), [[None, first], [first, second], [second, third]])
        self.assertNothingPlain()

    def test_a_contact_without_an_address_or_a_number_is_named_as_before(self):
        self.save([{'name': 'Kari', 'role': 'Vet', 'is_primary': True}, {'name': 'Per'}])
        self.assertEqual(self.logged(), [[None, [['Kari (Vet, primary)'], ['Per']]]])
        self.save([])
        self.assertEqual(self.logged()[-1], [[['Kari (Vet, primary)'], ['Per']], None])

    def test_a_suppliers_contacts_are_logged_the_same_way(self):
        self.user.groups.add(role('Supplier manager', 'view_supplier', 'change_supplier'))
        supplier = Supplier.objects.create(name='Fjord Feed', code='FF', supplies=['feed'])
        self.save([{**KARI, 'role': 'Sales', 'phone': '+47 1'}], reverse('farm:supplier_contacts', args=[supplier.pk]),
                  supplier)
        self.assertEqual(self.logged(supplier),
                         [[None, [['Kari (Sales, primary)', email('kari@example.com'), phone('+47 1')]]]])
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


class DigestIsNeverShownTests(SiteTestCase):
    """Review R2: the digest lets its reader test a guess (type a value, save, compare), so no page prints it. The
    History tab of a record is read by whoever may edit it, without the Activity log right."""

    HEX = re.compile(r'\b[0-9a-f]{8}\b')

    def setUp(self):
        super().setUp()
        self.site = self.make_site()

    def save(self, rows):
        return self.client.post(reverse('farm:site_contacts', args=[self.site.pk]), contacts_data(rows, record=self.site))

    def digests(self):
        """Every digest the log holds, read from the stored rows."""
        return set(re.findall(r"'rev': '([0-9a-f]{8})'", str(list(AuditLog.objects.values_list('changes', flat=True)))))

    def test_an_editor_without_the_log_right_cannot_compare_a_guess_with_a_removed_contact(self):
        editor = get_user_model().objects.create_user('edda', 'edda@example.com', 'x')
        editor.groups.add(role('Site editor', 'view_site', 'change_site'))
        self.save([KARI])
        self.save([])                                                        # Kari is removed ("erased")
        self.client.force_login(editor)
        self.assertEqual(self.client.get(reverse('core:activity_log')).status_code, 403)
        self.save([{'name': 'guess 1', 'email': 'someone@else.example'}, {'name': 'guess 2', 'email': 'kari@example.com',
                                                                         'phone': '+47 98989898'}])
        stored = self.digests()
        self.assertEqual(len(stored), 3)                                     # the log holds them (two addresses, a number)
        page = self.client.get(reverse('farm:site_edit', args=[self.site.pk])).content.decode()
        history = page[page.index('data-panel="history"'):]
        self.assertIn('Kari (Vet, primary), Email: Private text, Phone: Private text', history)
        self.assertIn('guess 1, Email: Private text; guess 2, Email: Private text, Phone: Private text', history)
        self.assertEqual(stored & set(self.HEX.findall(history)), set())     # and shows none of them
        for value in VALUES:
            self.assertNotIn(value, history)

    def test_the_activity_log_page_shows_none_either_and_says_what_is_private(self):
        self.save([KARI, OLA])
        page = self.client.get(reverse('core:activity_log')).content.decode()
        self.assertIn('Kari (Vet, primary), Email: Private text, Phone: Private text; Ola, Email: Private text', page)
        self.assertEqual(self.digests() & set(self.HEX.findall(page)), set())

    def test_the_words_follow_the_readers_language(self):
        from core.models import Profile
        self.save([KARI])
        for language, said in {'nb': 'Kari (Vet, primary), E-post: Privat tekst, Telefon: Privat tekst',
                               'tr': 'Kari (Vet, primary), E-posta: Özel metin, Telefon: Özel metin'}.items():
            Profile.objects.update_or_create(user=self.user, defaults={'language': language})
            self.assertContains(self.client.get(reverse('core:activity_log')), said)

"""After a row list is refused, the record's own Save still saves the record (flow fault B-04). A refused row list
(core.crud.RowListView) shows the record's edit page again from the row list's address, and the record's form posted to
"the address of this page": so "Save medicine" went to the withdrawal rows' address and answered "ManagementForm data is
missing". The record's form now posts to the record's own address whatever address the page came from
(core.crud.FormView.page gives it), for every tab with a row list: checked on a site's contacts (a row that is not
valid) and a medicine's withdrawal rows (a list its save asks about), and on a new record's form."""
import re

from django.urls import reverse

from ..models import Medicine, Site
from .helpers import contacts_data, rows_data
from .test_health import HealthTestCase
from .test_sites import SiteTestCase
from .test_withdrawal_gate import edit_data

ACTION = re.compile(r'<form method="post" action="([^"]+)" class="record-form"')


def record_action(response):
    """Where the record's own form of a page posts to."""
    [action] = ACTION.findall(response.content.decode())
    return action


class SiteContactsTests(SiteTestCase):
    def test_the_sites_save_still_saves_after_a_contact_row_was_refused(self):
        site = self.make_site()
        edit = reverse('farm:site_edit', args=[site.pk])
        refused = self.client.post(reverse('farm:site_contacts', args=[site.pk]), contacts_data(
            [{'name': 'Kari', 'role': 'Vet', 'email': 'not an address', 'phone': '', 'is_primary': True}], record=site))
        self.assertEqual(refused.status_code, 200)
        self.assertTrue(refused.context['contacts'].errors[0])               # the row list was refused
        self.assertFalse(site.contacts.exists())
        self.assertEqual(record_action(refused), edit)                       # not the contacts' address
        saved = self.client.post(record_action(refused), edit_data(refused.context['form'], name='Renamed site'))
        self.assertEqual(saved.status_code, 302)
        self.assertEqual(Site.objects.get(pk=site.pk).name, 'Renamed site')

    def test_a_new_records_form_posts_to_the_create_address_and_an_edit_to_its_own(self):
        site = self.make_site()
        self.assertEqual(record_action(self.client.get(reverse('farm:site_create'))), reverse('farm:site_create'))
        edit = reverse('farm:site_edit', args=[site.pk])
        self.assertEqual(record_action(self.client.get(edit)), edit)


class MedicineWithdrawalRowsTests(HealthTestCase):
    def test_the_medicines_save_still_saves_after_its_withdrawal_rows_asked_a_question(self):
        bath = self.medicine(days=7)
        self.treat(bath, 3, 3)                                               # holds the fish of T-01 today
        row = bath.withdrawals.get()
        edit = reverse('farm:medicine_edit', args=[bath.pk])
        refused = self.client.post(reverse('farm:medicine_withdrawals', args=[bath.pk]), rows_data('withdrawals', [
            {'id': str(row.pk), 'species': '', 'degree_days': '', 'days': '1', 'safety_margin_pct': '', 'note': ''},
        ], initial=1, record=bath))
        self.assertEqual(refused.status_code, 422)                           # the guard asks: the fish would be freed
        self.assertEqual(bath.withdrawals.get().days, 7)
        self.assertEqual(record_action(refused), edit)
        saved = self.client.post(record_action(refused), edit_data(refused.context['form'],
                                                                 active_substance='azamethiphos 50 %'))
        self.assertEqual(saved.status_code, 302)
        self.assertEqual(Medicine.objects.get(pk=bath.pk).active_substance, 'azamethiphos 50 %')

    def test_a_row_that_is_not_valid_leaves_the_medicines_form_on_its_own_address(self):
        bath = self.medicine(days=7)
        refused = self.client.post(reverse('farm:medicine_withdrawals', args=[bath.pk]), rows_data('withdrawals', [
            {'species': '', 'degree_days': 'many', 'days': '', 'safety_margin_pct': '', 'note': ''},
        ], record=bath))
        self.assertEqual(refused.status_code, 200)
        self.assertEqual(record_action(refused), reverse('farm:medicine_edit', args=[bath.pk]))

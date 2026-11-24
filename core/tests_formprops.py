"""The new look's record form and delete confirmation through the one CRUD layer (core.crud.FormView.page, DeleteView,
core/formprops.py), on the alarm deadbands' tab (crud/form.html, a select and a number): behind ?ui=next the same view
answers with the island and its props, which say everything the classic page says (core.pagesays); the form posts to the
same address, so validation, the CSRF check, the permissions and the activity log are the classic page's; a dialog and a
tab whose form the island cannot draw keep the classic page."""
import json
import re
from decimal import Decimal
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from alarms.models import ParameterDeadband
from core.models import AuditLog

from .pagesays import unsaid

MANIFEST = str(Path(__file__).resolve().parent / 'testdata' / 'islands-company-manifest.json')
CREATE, LIST = reverse('alarms:parameterdeadband_create'), reverse('alarms:parameterdeadband_list')


def props_of(html, name):
    found = re.search(r'<script id="island-' + name + r'-1" type="application/json">(.*?)</script>', html, re.S)
    return json.loads(found.group(1)) if found else None


@override_settings(ISLANDS_MANIFEST=MANIFEST)
class RecordFormNextTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser('former', 'f@example.com', 'x')
        self.client.force_login(self.admin)

    def page(self, url, look, **extra):
        return self.client.get(url, {'ui': look}, **extra).content.decode()

    def test_the_new_form_says_everything_the_classic_form_says_in_three_languages(self):
        for language in ('en', 'nb', 'tr'):
            with self.subTest(language=language):
                self.client.cookies['django_language'] = language
                old = self.page(CREATE, 'classic')
                new = self.page(CREATE, 'next')
                props = props_of(new, 'record-form')
                self.assertIsNotNone(props)
                self.assertNotIn('class="record-form"', new)
                self.assertEqual(unsaid(old, props, new_html=new), [])

    def edit_url(self):
        """The deadband of the pH (one per parameter is seeded by the migrations: a new one would clash)."""
        self.record = ParameterDeadband.objects.get(parameter='ph')
        return reverse('alarms:parameterdeadband_edit', args=[self.record.pk])

    def test_a_refused_form_comes_back_with_the_servers_errors_and_saves_nothing(self):
        self.client.get(LIST, {'ui': 'next'})                       # the cookie keeps the look
        before = ParameterDeadband.objects.count()
        response = self.client.post(CREATE, {'parameter': '', 'deadband': 'abc'})
        props = props_of(response.content.decode(), 'record-form')
        fields = {field['name']: field for tab in props['form']['tabs'] for fieldset in tab['fieldsets']
                  for field in fieldset['fields']}
        self.assertTrue(fields['parameter']['errors'])
        self.assertTrue(fields['deadband']['errors'])
        self.assertEqual(ParameterDeadband.objects.count(), before)

    def test_a_good_form_saves_through_the_same_view_and_is_logged(self):
        self.client.get(LIST, {'ui': 'next'})
        url = self.edit_url()
        before = AuditLog.objects.count()
        props = props_of(self.page(url, 'next'), 'record-form')
        version = next(each['value'] for each in props['form']['hidden'] if each['name'] == 'version')
        response = self.client.post(url, {'parameter': 'ph', 'deadband': '0.25', 'version': version})
        self.assertEqual(response.status_code, 302)
        self.record.refresh_from_db()
        self.assertEqual(self.record.deadband, Decimal('0.25'))
        self.assertEqual(AuditLog.objects.count(), before + 1)
        edit = self.page(url, 'next')
        props = props_of(edit, 'record-form')
        self.assertEqual(props['delete']['href'], reverse('alarms:parameterdeadband_delete', args=[self.record.pk]))
        self.assertEqual(props['history']['entries'][0]['action'], 'Changed')
        old = self.page(url, 'classic')
        self.assertEqual(unsaid(old, props, new_html=edit), [])

    def test_the_csrf_check_holds_and_the_props_token_passes_it(self):
        url = self.edit_url()
        guarded = Client(enforce_csrf_checks=True)
        guarded.force_login(self.admin)
        props = props_of(guarded.get(url, {'ui': 'next'}).content.decode(), 'record-form')
        version = next(each['value'] for each in props['form']['hidden'] if each['name'] == 'version')
        sent = {'parameter': 'ph', 'deadband': '0.3', 'version': version}
        self.assertEqual(guarded.post(url, sent).status_code, 403)
        response = guarded.post(url, {**sent, 'csrfmiddlewaretoken': props['csrfToken']})
        self.assertEqual(response.status_code, 302)

    def test_a_person_without_the_right_is_refused_in_both_looks(self):
        person = get_user_model().objects.create_user('reader', 'r@example.com')
        self.client.force_login(person)
        for look in ('classic', 'next'):
            self.assertEqual(self.client.get(CREATE, {'ui': look}).status_code, 403)

    def test_a_dialog_and_a_form_the_island_cannot_draw_keep_the_classic_page(self):
        dialog = self.client.get(CREATE, {'ui': 'next'}, HTTP_X_MODAL='1').content.decode()
        self.assertIn('class="record-form"', dialog)
        site_form = self.page(reverse('farm:site_create'), 'next')        # farm/site_form.html: panels of its own
        self.assertIn('class="record-form"', site_form)
        self.assertIsNone(props_of(site_form, 'record-form'))

    def test_the_delete_confirmation_says_what_the_classic_one_says_and_deletes_through_the_same_view(self):
        record = ParameterDeadband.objects.get(parameter='ph')
        url = reverse('alarms:parameterdeadband_delete', args=[record.pk])
        old, new = self.page(url, 'classic'), self.page(url, 'next')
        props = props_of(new, 'confirm-delete')
        self.assertTrue(props['canDelete'])
        self.assertEqual(unsaid(old, props, new_html=new), [])
        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertFalse(ParameterDeadband.objects.filter(pk=record.pk).exists())    # gone from every list (soft or hard)

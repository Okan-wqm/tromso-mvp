"""The error pages (templates/403.html, 404.html, 500.html): a refused, a missing or a broken page says what happened and
offers the way back, in the console's shell for a person signed in (the menu stays), never a bare "403 Forbidden"."""
from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import TestCase, override_settings
from django.urls import reverse


@override_settings(DEBUG=False)
class ErrorPageTests(TestCase):
    def setUp(self):
        self.person = get_user_model().objects.create_user('ali', 'ali@example.com', 'x')

    def test_a_refused_page_is_said_in_the_shell_with_the_way_back(self):
        self.client.force_login(self.person)
        response = self.client.get(reverse('farm:site_list'))
        self.assertEqual(response.status_code, 403)
        self.assertTemplateUsed(response, '403.html')
        self.assertContains(response, 'class="rail"', status_code=403)
        self.assertContains(response, 'You may not open this page', status_code=403)
        self.assertContains(response, f'href="{reverse("home")}"', status_code=403)

    def test_a_missing_page_is_said_in_the_shell_with_the_way_back(self):
        self.client.force_login(self.person)
        response = self.client.get('/no-such-page/')
        self.assertEqual(response.status_code, 404)
        self.assertTemplateUsed(response, '404.html')
        self.assertContains(response, 'class="rail"', status_code=404)
        self.assertContains(response, 'This page does not exist', status_code=404)

    def test_signed_out_a_missing_page_has_no_menu(self):
        response = self.client.get('/no-such-page/')
        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, 'class="rail"', status_code=404)
        self.assertContains(response, 'This page does not exist', status_code=404)

    def test_a_broken_page_is_a_page_of_its_own_with_the_way_back(self):
        html = render_to_string('500.html')
        self.assertIn('Something went wrong', html)
        self.assertIn('href="/"', html)

    def test_in_a_dialog_a_missing_or_refused_page_is_the_dialog_sized_error(self):
        """A stale row opened in the dialog (X-Modal) gets the error in the dialog's frame, not the whole console."""
        self.client.force_login(self.person)
        for address, status, words in (('/no-such-page/', 404, 'This page does not exist'),
                                       (reverse('farm:site_list'), 403, 'You may not open this page')):
            response = self.client.get(address, headers={'X-Modal': '1'})
            self.assertEqual(response.status_code, status)
            self.assertNotContains(response, 'class="rail"', status_code=status)
            self.assertContains(response, 'class="modal-head"', status_code=status)
            self.assertContains(response, words, status_code=status)

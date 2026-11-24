"""The delete confirmation of the new pages (core.formpayload.delete_payload) says what the old page says
(crud/confirm_delete.html, held by core.pagesays): the question, what goes with the record, what loses its link, what is
kept, and what deleting does; and what is in the way when something is."""
from decimal import Decimal as D

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from farm.models import ProductionDepartment, Site, System
from farm.resources.site import SiteResource

from .formpayload import delete_payload
from .pagesays import unsaid
from .softdelete import plan_delete


class DeletePayloadTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser('del', 'del@example.com', 'x')
        self.client.force_login(self.admin)
        self.site = Site.objects.create(name='Bergen', code='BG', altitude=D(0), timezone='UTC')
        self.hall = ProductionDepartment.objects.create(site=self.site, name='Hall A', code='HA')
        self.ras = System.objects.create(name='RAS 1', code='R1', site=self.site, production_department=self.hall)

    def said(self, obj):
        url = reverse('farm:site_delete', args=[obj.pk])
        old = self.client.get(url).content.decode()
        payload = delete_payload(obj, plan_delete(obj), SiteResource.name, action=url,
                                 cancel=reverse('farm:site_list'))
        # The page head (eyebrow and heading) is the shell's, outside the dialog; the dialog says it as its heading.
        head = {f'{SiteResource.group()} · {SiteResource.title()}'}
        return old, payload, head

    def test_the_payload_says_everything_the_old_confirmation_says(self):
        old, payload, head = self.said(self.site)
        self.assertTrue(payload['groups'])
        self.assertEqual(unsaid(old, payload, ignore=head), [])
        self.assertTrue(payload['canDelete'])

    def test_the_same_in_norwegian_and_turkish(self):
        for language in ('nb', 'tr'):
            with self.subTest(language=language):
                self.client.cookies['django_language'] = language
                from django.utils import translation
                with translation.override(language):
                    old, payload, head = self.said(self.site)
                    self.assertEqual(unsaid(old, payload, ignore=head), [])

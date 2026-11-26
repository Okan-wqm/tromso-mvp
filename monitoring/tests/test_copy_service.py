"""The data-layering audit, L-1: a card template's copy is made by monitoring.services.copy_template: one copy per
sending of the Copy button however often it arrives (its one-time key), a name of its own even when another copy takes
the name at the same moment (never a server error), and who may is asked by the service itself."""
import uuid
from unittest import mock

from django.core.exceptions import PermissionDenied
from django.urls import reverse

from .. import services
from ..cards import builtin
from ..models import CardTemplate
from .test_template_pages import TEMPLATES, PagesCase


class CopyServiceTests(PagesCase):
    def test_the_same_button_sent_twice_makes_one_copy(self):
        page = self.client.get(TEMPLATES)
        self.assertContains(page, 'name="entry_key"')
        key = str(uuid.uuid4())
        address = reverse('monitoring:cardtemplate_copy', args=[builtin.SIMPLE])
        first = self.client.post(address, {'entry_key': key})
        second = self.client.post(address, {'entry_key': key})
        self.assertEqual(first['Location'], second['Location'])
        self.assertEqual(CardTemplate.objects.filter(name__startswith='Simple (copy').count(), 1)

    def test_a_name_taken_meanwhile_is_not_a_server_error(self):
        source = CardTemplate.objects.get(pk=builtin.SIMPLE)
        self.template('Simple (copy)')
        with mock.patch.object(services, 'copy_name', side_effect=['Simple (copy)', 'Simple (copy 7)']):
            copy = services.copy_template(self.designer, source)
        self.assertEqual(copy.name, 'Simple (copy 7)')

    def test_who_may_not_add_templates_is_refused_by_the_service(self):
        looker = self.person('looker', 'view_cardtemplate')
        with self.assertRaises(PermissionDenied):
            services.copy_template(looker, CardTemplate.objects.get(pk=builtin.SIMPLE))
        self.assertFalse(CardTemplate.objects.filter(name__startswith='Simple (copy').exists())

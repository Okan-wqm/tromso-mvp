"""The Water section of the Production units drawer leads to the unit's Tank › Water (farm:tank_water, owner 2026-11-24)
in both looks: the new look opens the page, the classic look's address redirects to the unit's history on Water
chemistry, as before."""
import re
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse

from ..water.views import history_url
from .test_water import WaterTestCase


# the islands of both pages: Tank › Water's and the new look's list of units
MANIFEST = str(Path(__file__).resolve().parents[2] / 'core' / 'testdata' / 'islands-prodrest-manifest.json')


@override_settings(ISLANDS_MANIFEST=MANIFEST)
class DrawerWaterHistoryTests(WaterTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(get_user_model().objects.create_superuser('boss', 'boss@example.com', 'x'))
        self.sample(self.t1, hours=3, oxygen_mg_l='8.10')

    def history_link(self, look):
        html = self.client.get(reverse('farm:production_units'), {'unit': self.t1.pk, 'ui': look}).content.decode()
        return re.search(r'<a class="button button-ghost" href="([^"]+)">History</a>', html).group(1)

    def test_the_drawers_history_is_tank_water_in_both_looks_and_resolves(self):
        page = reverse('farm:tank_water', args=[self.t1.pk])
        for look in ('classic', 'next'):
            with self.subTest(look=look):
                self.assertEqual(self.history_link(look), page)
        self.assertEqual(self.client.get(page, {'ui': 'next'}).status_code, 200)
        self.assertRedirects(self.client.get(page, {'ui': 'classic'}), history_url(self.t1),
                             fetch_redirect_response=False)

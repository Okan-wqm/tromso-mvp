"""Production › Overview in the new look (?ui=next, config.views.production_home): the classic page's body
(templates/_production_overview.html) drawn by the server in the design system, plus what the design adds from real
sources: the fish's batch count on its card, the units under a medicine withdrawal today in Needs attention, and the
production team today as the HR board's bar (config.views.team_today). On THE test world (core/test_world.py, clock at
MOMENT) it says everything the classic page says in three languages (core.pagesays), the classic page is unchanged, and
its <main> is kept for the browser test (frontend/test/prodrest.pages.ts)."""
from datetime import timedelta
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from core.island_props import keep
from core.pagesays import says, unsaid
from core.test_world import MOMENT, world
from core.testing import FrozenClock

MANIFEST = str(Path(__file__).resolve().parents[2] / 'core' / 'testdata' / 'islands-prodrest-manifest.json')


def main_of(html):
    """A page's <main>, as the browser test lays it out."""
    return html[html.index('<main'):html.index('</main>') + len('</main>')]


def as_next(old):
    """The classic page as the new one would say its own address: a dialog's way back (`next`) is the page asked for,
    ?ui=classic on the one and ?ui=next on the other."""
    return old.replace('ui%3Dclassic', 'ui%3Dnext').replace('ui=classic', 'ui=next')


@override_settings(ISLANDS_MANIFEST=MANIFEST)
class ProductionOverviewNextTests(FrozenClock, TestCase):
    NOW = MOMENT

    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser('test.admin', 'test.admin@example.com', 'x')
        world(cls.admin, Client())

    def setUp(self):
        self.client.force_login(self.admin)

    def page(self, look, language='en'):
        from core.language import save_account_language
        save_account_language(self.admin, language)
        self.client.cookies['django_language'] = language
        response = self.client.get(reverse('production_home'), {'ui': look})
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_the_new_page_says_everything_the_classic_page_says_in_three_languages(self):
        for language in ('en', 'nb', 'tr'):
            with self.subTest(language=language):
                old, new = as_next(self.page('classic', language)), self.page('next', language)
                self.assertEqual(unsaid(old, {}, new_html=new), [])
                keep(f'production-overview-{language}', {'html': main_of(new)})

    def test_the_design_s_parts_from_their_real_sources(self):
        new = self.page('next')
        said = [value for _kind, value in says(new)]
        self.assertIn('Production team today', said)
        self.assertIn('Today & attendance', said)
        self.assertTrue(any(value.startswith('in ') and 'batch' in value for value in said), 'the batch count')
        self.assertIn('data-tone=', main_of(new))                         # the team's bar
        old = self.page('classic')
        self.assertNotIn('Production team today', old)
        self.assertNotIn('data-attention="withdrawal"', old)

    def test_a_unit_under_withdrawal_is_in_needs_attention_with_its_drawer(self):
        from farm import withdrawal_gate as gate
        from farm.health import services
        from farm.models import Medicine, MedicineWithdrawal, Tank
        from farm.stock.dates import local_today
        unit = Tank.objects.get(code='TT-01')
        medicine = Medicine.objects.create(name='Test medicine vet.', kind='lice', administration='bath',
                                           active_substance='azamethiphos', lice_report_code='AZAMETHIPHOS')
        with gate.opened('test fixture: a withdrawal row straight in the database'):
            MedicineWithdrawal.objects.create(medicine=medicine, species=None, days=30, safety_margin_pct=0)
        day = local_today(unit) - timedelta(days=2)
        seen = services.handling([unit], day, 'bath', medicine, 'sea_lice').fingerprint
        services.record_treatment(self.admin, units=[unit], method='bath', reason='sea_lice', start_date=day,
                                  end_date=day, medicine=medicine, handling_ack=seen or None)
        new = self.page('next')
        self.assertIn('data-attention="withdrawal"', new)
        self.assertIn(f'{reverse("farm:production_units")}?unit={unit.pk}', new)
        self.assertEqual(unsaid(as_next(self.page('classic')), {}, new_html=new), [])

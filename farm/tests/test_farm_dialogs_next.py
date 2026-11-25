"""The farm's operation dialogs in the new look (?ui=next, farm/dialogs.py): a feeding and a meal, a treatment, its last
day, a sea-lice count, a harvest and a transfer from their plans, and the voids of a feeding, a treatment, a health event,
a count and a stock operation, each opened as a page and drawn by the record-form island from the same form, view and
address as the classic dialog. On THE test world (world(), feeding_ops_world(), health_ops_world(),
harvest_ops_world(), clock at MOMENT) each page says everything its classic dialog says in three languages
(core.pagesays), the words before its fields read from the very partial the classic template includes. Things said
another way, named: the classic Save button and Cancel are the island's; the handling panel's heading and notes are one
line each ("Before handling: …"). A request for the classic dialog (X-Modal) keeps it. Saving through the new page
saves; a refused save is drawn again (422) with the server's reason on its field."""
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import translation
from django.utils.translation import gettext

from core.island_props import keep, props_of
from core.pagesays import unsaid
from core.test_world import MOMENT, feeding_ops_world, harvest_ops_world, health_ops_world, world
from core.testing import FrozenClock

from ..models import FeedingRecord, HandlingPlanItem, HealthEvent, LiceCount, StockOperation, Tank, Treatment

MANIFEST = str(Path(__file__).resolve().parents[2] / 'core' / 'testdata' / 'islands-prodrest-manifest.json')


def heading_said(language):
    """The handling panel's heading, said at the start of each of its notes' lines (and alone without notes)."""
    with translation.override(language):
        return {gettext('Before handling')}


@override_settings(ISLANDS_MANIFEST=MANIFEST)
class FarmDialogsNextTests(FrozenClock, TestCase):
    NOW = MOMENT

    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser('test.admin', 'test.admin@example.com', 'x')
        world(cls.admin, Client())
        feeding_ops_world(cls.admin)
        health_ops_world(cls.admin)
        harvest_ops_world(cls.admin)

    def setUp(self):
        self.client.force_login(self.admin)

    def dialogs(self):
        tank, cage = Tank.objects.get(code='TT-01'), Tank.objects.get(code='TM-01')
        harvest = HandlingPlanItem.objects.get(kind='harvest')
        transport = HandlingPlanItem.objects.get(kind='transport')
        harvested = StockOperation.objects.filter(kind='harvest').first()
        return {
            'feed': (reverse('farm:feeding_record', args=[tank.pk]), {}),
            'meal': (reverse('farm:feeding_record', args=[tank.pk]), {'meal': 'next'}),
            'feed-void': (reverse('farm:feeding_void', args=[FeedingRecord.objects.filter(unit=tank).first().pk]), {}),
            'treat': (reverse('farm:treatment_record'), {'unit': str(cage.pk)}),
            'last-day': (reverse('farm:treatment_last_day', args=[Treatment.objects.filter(medicine__isnull=False).get().pk]), {}),
            'treat-void': (reverse('farm:treatment_void', args=[Treatment.objects.filter(medicine__isnull=True).get().pk]), {}),
            'event-void': (reverse('farm:healthevent_void', args=[HealthEvent.objects.get(kind='observation').pk]), {}),
            'lice': (reverse('farm:lice_record'), {}),
            'lice-void': (reverse('farm:lice_void', args=[LiceCount.objects.get().pk]), {}),
            'harvest': (reverse('farm:stock_harvest', args=[cage.pk]), {'plan': str(harvest.pk)}),
            'transfer': (reverse('farm:stock_transfer', args=[tank.pk]), {'plan': str(transport.pk)}),
            'stock-void': (reverse('farm:stock_void', args=[harvested.pk]), {}),
        }

    def pages(self, url, query, language='en'):
        from core.language import save_account_language
        save_account_language(self.admin, language)
        self.client.cookies['django_language'] = language
        old = self.client.get(url, {**query, 'ui': 'classic'}).content.decode()
        old = old.replace('ui%3Dclassic', 'ui%3Dnext').replace('ui=classic', 'ui=next')
        new = self.client.get(url, {**query, 'ui': 'next'}).content.decode()
        return old, new

    def test_each_dialog_says_everything_the_classic_dialog_says(self):
        for key, (url, query) in self.dialogs().items():
            for language in (('en', 'nb', 'tr') if key == 'treat' else ('en',)):
                with self.subTest(dialog=key, language=language):
                    old, new = self.pages(url, query, language)
                    props = props_of(new, 'record-form')
                    self.assertNotIn('data-modal', new.split('<main', 1)[1].split('</main>', 1)[0])
                    self.assertEqual(unsaid(old, props, new_html=new, ignore=heading_said(language)), [])
                    keep(f'dialog-{key}-{language}', {'island': 'record-form', 'props': props})

    def test_a_void_says_what_it_voids_and_is_the_danger_button(self):
        url, query = self.dialogs()['feed-void']
        _old, new = self.pages(url, query)
        props = props_of(new, 'record-form')
        self.assertTrue(props['danger'])
        self.assertEqual(props['submit'], 'Void')
        self.assertRegex(props['intro'][0]['text'], r'^Void the feeding of \d{2}\.\d{2}\.\d{4} in TT-01\?$')

    def test_a_transfer_from_its_plan_posts_its_rows_with_its_form(self):
        url, query = self.dialogs()['transfer']
        _old, new = self.pages(url, query)
        grid = props_of(new, 'record-form')['grid']
        self.assertEqual(grid['prefix'], 'rows')
        self.assertTrue(grid['rows'])
        self.assertTrue(any(each['name'] == 'rows-TOTAL_FORMS' for each in grid['management']))

    def test_the_classic_dialog_stays_for_a_dialog_request(self):
        url, query = self.dialogs()['lice']
        answer = self.client.get(url, {**query, 'ui': 'next'}, HTTP_X_MODAL='1').content.decode()
        self.assertNotIn('data-island="record-form"', answer)

    def test_saving_through_the_new_page_saves_and_a_refused_save_says_why(self):
        url, query = self.dialogs()['lice-void']
        count = LiceCount.objects.get()
        refused = self.client.post(f'{url}?ui=next', {'reason': ''})
        self.assertEqual(refused.status_code, 422)
        reason = next(field for tab in props_of(refused.content.decode(), 'record-form')['form']['tabs']
                      for fieldset in tab['fieldsets'] for field in fieldset['fields'] if field['name'] == 'reason')
        self.assertTrue(reason['errors'])
        saved = self.client.post(f'{url}?ui=next', {'reason': 'Test: counted twice'})
        self.assertEqual(saved.status_code, 302)
        self.assertTrue(LiceCount.all_objects.get(pk=count.pk).is_deleted)

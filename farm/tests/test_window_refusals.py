"""A refusal by the correction window says what to do (flow fault B-07). "Operations can be dated at most 31 days back."
was a dead end: nothing said whose setting the window is, where it is changed, or that fish a farm already had are
registered as an opening balance. Every refusal by the window is now worded in one place (farm.stock.dates.too_old) and
ends with core.platform.window_way_out; a refused stocking names the opening balance first. Through the pages for a
stocking, an operation and a void; the feeding, water, plan and assignment refusals are asserted where they always
were (test_feeding, test_water, test_harvest, test_protocols), with the same sentence."""
import uuid

from django.core.management import call_command
from django.urls import reverse
from django.utils import translation

from core import platform

from ..models import Batch, StockMovement, StockOperation
from ..stock import dates
from .helpers import OPENING_WAY_OUT, WINDOW_WAY_OUT, correction_window
from .test_harvest_inside_withdrawal import HarvestInsideTestCase
from .test_stock import StockTestCase


def setUpModule():
    call_command('compile_catalogs', verbosity=0)    # the language tests read the built catalogs


class StockingTests(StockTestCase):
    def post(self, url, data):
        return self.client.post(url, data, headers={'X-Modal': '1'})

    def input_data(self, rows, **fields):
        """What the stocking dialog posts (as test_stock.DialogTests gives it)."""
        data = {'token': str(uuid.uuid4()), 'species': str(self.salmon.pk), 'input_stage': 'fry',
                'input_date': self.day(2).isoformat(), 'count': '5000', 'avg_weight_g': '2.5', 'origin': 'purchased',
                'supplier': str(self.supplier.pk), 'supplier_batch_ref': 'S-9', 'strain': '', 'name': '',
                'expected_harvest_date': '', 'notes': '', 'provenance': '', 'year_class': '',
                'units-TOTAL_FORMS': str(len(rows)),
                'units-INITIAL_FORMS': '0', 'units-MIN_NUM_FORMS': '1', 'units-MAX_NUM_FORMS': '20'}
        for index, (unit, count) in enumerate(rows):
            data[f'units-{index}-unit'] = str(unit.pk)
            data[f'units-{index}-count'] = str(count)
        data.update(fields)
        return data

    def test_a_stocking_older_than_the_window_is_told_of_the_opening_balance_and_of_the_setting(self):
        response = self.post(reverse('farm:stock_input'), self.input_data([(self.t1, 5000)],
                                                                          input_date=self.day(40).isoformat()))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.context['form'].errors['input_date'],
                         [f'Operations can be dated at most 31 days back. {OPENING_WAY_OUT} {WINDOW_WAY_OUT}'])
        self.assertContains(response, 'Company › Administration › Opening balances', status_code=422)
        self.assertContains(response, 'Company › Administration › Platform settings', status_code=422)
        self.assertFalse(Batch.all_objects.exists())

    def test_an_operation_older_than_the_window_is_told_of_the_setting_only(self):
        batch = self.stock(days_ago=31)
        url = reverse('farm:stock_mortality', args=[self.t1.pk])
        with correction_window(20):
            response = self.post(url, {'token': str(uuid.uuid4()), 'batch': str(batch.pk),
                                       'date': self.day(25).isoformat(), 'count': '3', 'cause': 'disease',
                                       'measured_weight_kg': '', 'notes': ''})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.context['form'].errors['date'],
                         [f'Operations can be dated at most 20 days back. {WINDOW_WAY_OUT}'])
        self.assertNotContains(response, 'opening balance', status_code=422)
        self.assertFalse(StockMovement.objects.filter(kind='mortality').exists())

    def test_a_void_older_than_the_window_is_told_of_the_setting(self):
        batch = self.stock(days_ago=31)
        died = self.mortality(batch, 1, days_ago=10)
        with correction_window(5):
            response = self.post(reverse('farm:stock_void', args=[died.pk]), {'reason': 'Typed twice'})
        self.assertEqual(response.status_code, 422)
        self.assertContains(response, f'Operations older than 5 days cannot be voided. {WINDOW_WAY_OUT}',
                            status_code=422)
        self.assertFalse(StockOperation.all_objects.get(pk=died.pk).is_deleted)


class OtherRecordsTests(HarvestInsideTestCase):
    def test_a_treatment_older_than_the_window_is_told_of_the_setting(self):
        with correction_window(5):
            errors = self.refused(self.treat, self.medicine(days=7), 8, 8)
        self.assertEqual(errors, {'date': [f'Operations can be dated at most 5 days back. {WINDOW_WAY_OUT}']})

    def test_the_sentence_is_worded_in_one_place_and_follows_the_menu_and_the_language(self):
        self.addCleanup(translation.activate, 'en')
        self.assertEqual(platform.window_way_out(), WINDOW_WAY_OUT)
        self.assertEqual(dates.opening_way_out(), OPENING_WAY_OUT)
        self.assertEqual(dates.too_old('Too old: %(days)d days.'), f'Too old: 31 days. {WINDOW_WAY_OUT}')
        for language, (settings, opening) in {
                'nb': ('Selskap › Administrasjon › Plattforminnstillinger', 'Selskap › Administrasjon › Åpningsbalanser'),
                'tr': ('Şirket › Yönetim › Platform ayarları', 'Şirket › Yönetim › Açılış bakiyeleri')}.items():
            with translation.override(language):
                self.assertIn(settings, platform.window_way_out(), language)
                self.assertNotIn('The correction window', platform.window_way_out(), language)
                self.assertIn(opening, dates.opening_way_out(), language)
                self.assertNotIn('Fish the farm', dates.opening_way_out(), language)

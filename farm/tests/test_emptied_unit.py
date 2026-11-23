"""A record of a day a unit held fish, entered once the unit is empty (flow fault S-04). The dialogs gated on the fish in
the unit TODAY, so a treatment given, a weighing taken or a death found before the harvest that emptied a unit could
never be entered, and a harvest inside the withdrawal of a forgotten course was never found. The gate is now the
record's own day inside the correction window (farm.stock.read.left_within): the dialogs offer the fish that left on a
day that may still be dated, the service decides on the record's day as it always did, every later figure follows, and
a record that would leave a later operation without its fish is refused, naming that operation."""
import io
import uuid
from decimal import Decimal

from django.core.management import call_command
from django.urls import reverse

from ..health import views as health_views
from ..models import StockMovement, Treatment, WithdrawalAcknowledgement
from ..stock import read as stock_read
from ..stock.dates import shown_date
from .helpers import correction_window
from .test_harvest_inside_withdrawal import HarvestInsideTestCase
from .test_health import treatment_data


class EmptiedUnitTestCase(HarvestInsideTestCase):
    """T-01 held 2,000 fish of 125 g from 10 days ago; all of them were harvested 3 days ago: it is empty today."""

    def setUp(self):
        super().setUp()
        self.emptied = self.harvest(3, count=2000, kilos='2400', everything=True)
        self.assertEqual(self.fish(self.t1), 0)

    def data(self, **fields):
        return {'token': str(uuid.uuid4()), 'batch': str(self.batch.pk), 'date': self.day(5).isoformat(), 'notes': '',
                **fields}


class StockDialogTests(EmptiedUnitTestCase):
    def test_the_dialog_offers_the_fish_that_left_and_assumes_no_day(self):
        response = self.client.get(reverse('farm:stock_mortality', args=[self.t1.pk]))
        form = response.context['form']
        self.assertEqual([share.batch for share in form.present.values()], [self.batch])
        self.assertEqual((form.only_batch.past, form.only_batch.until), (True, self.day(3)))
        self.assertIsNone(form.fields['date'].initial)                      # no fish today: today is not offered
        self.assertContains(response, f'Batch {self.batch.code}: in T-01 until {shown_date(self.day(3))}')
        self.assertContains(response, 'date the record on a day they were in the unit')
        self.assertNotContains(response, 'No fish are in T-01')

    def test_a_weighing_of_a_day_before_the_harvest_is_stored_and_the_harvest_follows(self):
        line = StockMovement.objects.get(kind='harvest')
        self.assertEqual(abs(stock_read.moved_grams({self.batch.pk})[line.id]), Decimal(250000))   # 2,000 at 125 g
        url = reverse('farm:stock_weighing', args=[self.t1.pk])
        response = self.client.post(url, self.data(sample_count='', sample_weight_kg='', avg_weight_g='150'))
        self.assertEqual(response.status_code, 302)
        weighed = StockMovement.objects.get(kind='weighing')
        self.assertEqual((weighed.operation.date, weighed.avg_weight_g, weighed.unit, weighed.batch),
                         (self.day(5), Decimal('150'), self.t1, self.batch))
        self.assertEqual(abs(stock_read.moved_grams({self.batch.pk})[line.id]), Decimal(300000))   # 2,000 at 150 g
        self.assertStockAddsUp()

    def test_a_mortality_the_harvest_would_be_short_of_is_refused_naming_the_harvest(self):
        url = reverse('farm:stock_mortality', args=[self.t1.pk])
        response = self.client.post(url, self.data(count='7', cause='disease', measured_weight_kg='',
                                                   health_event=''))
        self.assertEqual(response.status_code, 422)
        self.assertContains(response, f'The harvest of {shown_date(self.day(3))} in T-01 would be left without its '
                                      f'fish: only 1,993 fish of {self.batch.code} would be there that day. Void '
                                      'that operation first, or correct this one.', status_code=422)
        self.assertFalse(StockMovement.objects.filter(kind='mortality').exists())

    def test_a_record_dated_after_the_fish_left_is_refused_on_its_own_day(self):
        url = reverse('farm:stock_mortality', args=[self.t1.pk])
        response = self.client.post(url, self.data(date=self.day(1).isoformat(), count='7', cause='disease',
                                                   measured_weight_kg='', health_event=''))
        self.assertEqual(response.status_code, 422)
        self.assertContains(response, f'No fish of {self.batch.code} are in T-01 on {shown_date(self.day(1))}.',
                            status_code=422)

    def test_a_harvest_dialog_waits_for_its_day(self):
        response = self.client.get(reverse('farm:stock_harvest', args=[self.t1.pk]))
        self.assertContains(response, 'Choose the date first: the fast and the medicine withdrawal are checked for '
                                      'that day.')

    def test_the_drawer_of_the_emptied_unit_offers_the_dialogs(self):
        page = self.client.get(reverse('farm:production_units'), {'unit': self.t1.pk})
        self.assertContains(page, 'Records of the fish that left')
        self.assertContains(page, f'{self.batch.code} was here until {shown_date(self.day(3))}')
        for name in ('farm:stock_mortality', 'farm:stock_weighing', 'farm:stock_cull'):
            self.assertContains(page, reverse(name, args=[self.t1.pk]))
        never = self.client.get(reverse('farm:production_units'), {'unit': self.t2.pk})
        self.assertNotContains(never, 'Records of the fish that left')
        self.assertNotContains(never, reverse('farm:stock_mortality', args=[self.t2.pk]))

    def test_fish_that_left_before_the_window_are_not_offered_and_the_page_says_so(self):
        url = reverse('farm:stock_mortality', args=[self.t1.pk])
        with correction_window(2):
            response = self.client.get(url)
            self.assertNotIn('form', response.context)
            self.assertContains(response, 'No fish are in T-01, and none were in it in the last 2 days: there is '
                                          'nothing to record here.')
            posted = self.client.post(url, self.data(count='7', cause='disease'))
            self.assertEqual(posted.status_code, 422)                       # nothing saved is not a success
            self.assertNotIn(self.t1, health_views._units_with_fish())
        self.assertFalse(StockMovement.objects.filter(kind='mortality').exists())


class HealthDialogTests(EmptiedUnitTestCase):
    def test_a_course_given_before_the_harvest_is_recorded_and_the_harvest_inside_it_is_found(self):
        url = reverse('farm:treatment_record')
        self.assertIn(self.t1, self.client.get(url).context['form'].fields['units'].queryset)
        bath = self.medicine(days=7)
        data = treatment_data([self.t1], method='bath', medicine=str(bath.pk), start_date=self.day(5).isoformat(),
                              end_date=self.day(5).isoformat())
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 422)
        self.assertContains(response, 'lies inside this withdrawal', status_code=422)
        self.assertFalse(Treatment.all_objects.exists())
        fingerprint = response.context['form'].withdrawal_change.fingerprint
        self.assertEqual(self.client.post(url, {**data, 'withdrawal_ack': fingerprint}).status_code, 302)
        treatment = Treatment.objects.get()
        self.assertEqual((list(treatment.units.all()), treatment.start_date), ([self.t1], self.day(5)))
        row = WithdrawalAcknowledgement.objects.get()
        self.assertEqual((row.harvest, row.batch, row.warning), (self.emptied, self.batch, 'harvested'))
        out = io.StringIO()
        call_command('check_withdrawal', stdout=out)
        self.assertIn('1 harvest lies inside a medicine withdrawal.', out.getvalue())
        self.assertIn('Acknowledged when the treatment was recorded.', out.getvalue())

    def test_the_lice_count_dialog_offers_the_emptied_unit_too(self):
        self.assertIn(self.t1, health_views._units_with_fish(production=True))
        self.assertNotIn(self.t2, health_views._units_with_fish(production=True))     # never held fish

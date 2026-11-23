"""Where a second person must approve, the dialog says so before the tick (flow fault M-27). With the platform owner's
setting on, the harvest dialog first asked "Tick the box to go on despite these warnings." and only the ticked submit
answered "A second person must approve … and that approval cannot be given here yet.". The setting is now consulted
first: the dialog shows that sentence in the place of its box, and the save answers it whatever is ticked; the same for
the withdrawal guard's question. The setting still fails closed; with it off the box is there as before."""
import uuid

from django.urls import reverse

from core.models import PlatformSettings

from ..models import StockMovement, Treatment
from .test_harvest_inside_withdrawal import HarvestInsideTestCase
from .test_health import treatment_data

SECOND = ('A second person must approve going on past a medicine withdrawal (the platform owner’s setting), and that '
          'approval cannot be given here yet.')
TICK = 'Tick the box to go on despite these warnings.'


class HarvestDialogTests(HarvestInsideTestCase):
    def setUp(self):
        super().setUp()
        self.treat(self.medicine(days=7), 3, 3)                              # T-01 is held today
        self.url = reverse('farm:stock_harvest', args=[self.t1.pk])
        self.data = {'token': str(uuid.uuid4()), 'batch': str(self.batch.pk), 'date': self.today.isoformat(),
                     'count': '100', 'measured_weight_kg': '13', 'facility': str(self.facility.pk), 'notes': ''}

    def test_with_the_setting_on_the_dialog_says_it_before_any_tick_and_shows_no_box(self):
        PlatformSettings.get()
        PlatformSettings.objects.update(second_approval_withdrawal=True)
        shown = self.client.get(self.url)
        self.assertContains(shown, 'Not suitable for harvest')
        self.assertContains(shown, SECOND)
        self.assertNotContains(shown, 'name="handling_ack"')
        self.assertNotContains(shown, 'Go on despite these warnings')
        refused = self.client.post(self.url, self.data)                      # no tick: told the reason, not "tick"
        self.assertEqual(refused.status_code, 422)
        self.assertContains(refused, SECOND, status_code=422)
        self.assertNotContains(refused, TICK, status_code=422)
        fingerprint = refused.context['form'].handling.fingerprint
        ticked = self.client.post(self.url, {**self.data, 'handling_ack': fingerprint})   # a hand-made tick: the same
        self.assertEqual(ticked.status_code, 422)
        self.assertContains(ticked, SECOND, status_code=422)
        self.assertFalse(StockMovement.objects.filter(kind='harvest').exists())

    def test_with_the_setting_off_the_box_is_offered_and_asked_for(self):
        shown = self.client.get(self.url)
        self.assertContains(shown, 'name="handling_ack"')
        self.assertNotContains(shown, SECOND)
        self.assertContains(self.client.post(self.url, self.data), TICK, status_code=422)


class GuardQuestionTests(HarvestInsideTestCase):
    def test_the_guards_question_says_it_in_the_place_of_its_box(self):
        self.harvest(3)
        bath = self.medicine(days=7)
        url = reverse('farm:treatment_record')
        data = treatment_data([self.t1], method='bath', medicine=str(bath.pk), start_date=self.day(5).isoformat(),
                              end_date=self.day(5).isoformat())
        PlatformSettings.get()
        PlatformSettings.objects.update(second_approval_withdrawal=True)
        refused = self.client.post(url, data)
        self.assertEqual(refused.status_code, 422)
        self.assertContains(refused, 'lies inside this withdrawal', status_code=422)
        self.assertContains(refused, SECOND, status_code=422)
        self.assertNotContains(refused, 'name="withdrawal_ack"', status_code=422)
        self.assertNotContains(refused, TICK, status_code=422)
        self.assertFalse(Treatment.all_objects.exists())
        PlatformSettings.objects.update(second_approval_withdrawal=False)
        asked = self.client.post(url, data)
        self.assertContains(asked, 'name="withdrawal_ack"', status_code=422)
        self.assertNotContains(asked, SECOND, status_code=422)

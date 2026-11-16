"""Sentences that were not true where they showed (review F-09 of the flow faults): the batch choice of a dialog
counted the batches that had left the unit as held; "Fed on the day of the handling itself" did not name the unit
when the fish were fed in the unit they came out of that day; and the feeding, treatment and sea-lice dialogs of a unit
that is empty now still offered today, a day the service refuses for it (the stock dialogs offered none)."""
from datetime import time as clock
from decimal import Decimal

from django.urls import reverse
from django.utils import translation

from core.models import Profile

from ..handling import check
from ..stock import services as stock_services
from ..stock.dates import shown_date
from .helpers import role
from .test_emptied_unit import EmptiedUnitTestCase
from .test_fast_of_the_unit import FastTestCase
from .test_feeding import FEEDING_KEEPER

CHOSEN = 'the operation applies to the one chosen.'


class BatchChoiceTests(EmptiedUnitTestCase):
    """T-01's 2,000 fish were harvested out 3 days ago (inside the correction window: still offered)."""

    def help_text(self):
        form = self.client.get(reverse('farm:stock_mortality', args=[self.t1.pk])).context['form']
        return len(form.present), str(form.fields['batch'].help_text)

    def test_a_batch_that_left_is_not_counted_as_held(self):
        self.stock(self.t1, count=1000, days_ago=2)                    # a new batch, since the harvest
        self.assertEqual(self.help_text(), (2, f'This unit holds 1 batch: {CHOSEN} 1 batch that left it can still be '
                                               'chosen, for a day it was in the unit.'))

    def test_two_batches_now_and_one_that_left(self):
        self.stock(self.t1, count=1000, days_ago=2)
        self.stock(self.t1, count=500, days_ago=1)
        self.assertEqual(self.help_text(), (3, f'This unit holds 2 batches: {CHOSEN} 1 batch that left it can still be '
                                               'chosen, for a day it was in the unit.'))

    def test_a_unit_that_is_empty_now_holds_none(self):
        other = self.stock(self.t1, count=500, days_ago=2)
        stock_services.record_harvest(self.user, unit=self.t1, batch=other, day=self.day(1), count=500,
                                      measured_weight_kg=Decimal('65'), facility=self.facility, everything=True)
        self.assertEqual(self.help_text(), (2, 'This unit holds no fish now: choose the batch that was in it on the day '
                                               'of the record.'))

    def test_it_is_said_in_norwegian_and_turkish(self):
        self.addCleanup(translation.activate, 'en')
        self.stock(self.t1, count=1000, days_ago=2)
        for language, text in (
                ('nb', 'Denne enheten har 1 fiskegruppe: operasjonen gjelder den som velges. 1 fiskegruppe som har '
                       'forlatt enheten kan fortsatt velges, for en dag den sto i enheten.'),
                ('tr', 'Bu birimde 1 parti var: işlem seçilen partiye uygulanır. Birimden ayrılan 1 parti, birimde '
                       'bulunduğu bir gün için hâlâ seçilebilir.')):
            Profile.objects.update_or_create(user=self.user, defaults={'language': language})
            self.assertEqual(self.help_text(), (2, text), language)


class FedInTheUnitTheyCameFromTests(FastTestCase):
    """RULES case 5: T-01 is fed today at 09:00, and 500 of its fish are moved into T-02 today."""

    def setUp(self):
        super().setUp()
        self.fed(0, at=clock(9, 0))
        self.move(500, 0)

    def test_the_warning_names_the_unit_the_fish_were_fed_in_when_it_is_not_the_one_handled(self):
        [moved] = check.assess('harvest', self.t2, self.today).warnings
        self.assertEqual(moved.message(), f'Fed on the day of the handling itself (09:00 in T-01): no fast before '
                                          f'{shown_date(self.today)}; the harvest rule asks for 72 h.')
        [own] = check.assess('harvest', self.t1, self.today).warnings
        self.assertEqual(own.message(), f'Fed on the day of the handling itself (09:00): no fast before '
                                        f'{shown_date(self.today)}; the harvest rule asks for 72 h.')

    def test_the_note_names_it_too_when_no_fast_is_asked(self):
        self.rule('harvest', 0)
        self.assertIn('Fed on the day of the handling itself (09:00 in T-01).',
                      check.assess('harvest', self.t2, self.today).notes)
        self.assertIn('Fed on the day of the handling itself (09:00).',
                      check.assess('harvest', self.t1, self.today).notes)

    def test_it_is_said_in_norwegian_and_turkish(self):
        self.addCleanup(translation.activate, 'en')
        [moved] = check.assess('harvest', self.t2, self.today).warnings
        for language, start in (('nb', 'Fôret samme dag som håndteringen (09:00 i T-01): '),
                                ('tr', 'İşlemin yapıldığı gün yemlendi (09:00, T-01 biriminde): ')):
            with translation.override(language):
                self.assertTrue(moved.message().startswith(start), (language, moved.message()))


class EmptiedUnitDayTests(EmptiedUnitTestCase):
    """T-01 is empty today; T-02 holds fish."""

    def setUp(self):
        super().setUp()
        self.user.groups.add(role('Feeding keeper', *FEEDING_KEEPER))
        self.stock(self.t2, count=1000, days_ago=5)

    def test_the_feeding_dialog_of_an_emptied_unit_offers_no_day(self):
        emptied = self.client.get(reverse('farm:feeding_record', args=[self.t1.pk]))
        self.assertEqual(emptied.status_code, 200)
        self.assertIsNone(emptied.context['form'].initial['date'])
        stocked = self.client.get(reverse('farm:feeding_record', args=[self.t2.pk]))
        self.assertEqual(stocked.context['form'].initial['date'], self.today)

    def test_the_treatment_dialog_of_an_emptied_unit_offers_no_days(self):
        url = reverse('farm:treatment_record')
        emptied = self.client.get(url, {'unit': str(self.t1.pk)}).context['form']
        self.assertEqual((emptied.initial['start_date'], emptied.initial['end_date']), (None, None))
        self.assertEqual(emptied.handling.warnings, [])                # no day yet: no fast is checked
        stocked = self.client.get(url, {'unit': str(self.t2.pk)}).context['form']
        self.assertEqual((stocked.initial['start_date'], stocked.initial['end_date']), (self.today, self.today))

    def test_the_sea_lice_dialog_of_an_emptied_unit_offers_no_day(self):
        url = reverse('farm:lice_record')
        self.assertIsNone(self.client.get(url, {'unit': str(self.t1.pk)}).context['form'].initial['date'])
        self.assertEqual(self.client.get(url, {'unit': str(self.t2.pk)}).context['form'].initial['date'], self.today)

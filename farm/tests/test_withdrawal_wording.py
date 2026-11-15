"""One sentence for a medicine withdrawal's date on every page that says it (flow fault M-01): "harvest from <the first
day the fish may be harvested>", "harvest from about …" when projected, "end unknown" when it cannot be worked out. The
Treatments list said "until 09.11 (harvest from 10.11)" while the harvest dialog, the units row, the plans and
check_withdrawal said "until 10.11" for the same withdrawal: one day apart, and the later one a day the fish are free.
Every page, message and log line now takes the words from farm.handling.withdrawal.harvest_from, and none says "until"
with a withdrawal's date."""
import io
import uuid
from decimal import Decimal

from django.core.management import call_command
from django.urls import reverse
from django.utils import translation

from core.models import AuditLog, Profile

from ..handling import check, withdrawal as registry
from ..handling.withdrawal import WithdrawalBlock
from ..health import services
from ..models import HandlingAcknowledgement, HandlingPlanItem
from ..stock import services as stock_services
from ..stock.dates import shown_date
from ..templatetags import health as health_tags
from .helpers import role
from .test_harvest import HARVEST_KEEPER
from .test_harvest_inside_withdrawal import HarvestInsideTestCase


def setUpModule():
    call_command('compile_catalogs', verbosity=0)    # the language tests read the built catalogs


class OneFormatterTests(HarvestInsideTestCase):
    def words(self, *args, **kwargs):
        """The one formatter's words. It is looked up here, not imported at the top of the module: without the fix
        there is none, and a test must then FAIL on what it asserts, not make the whole module an ImportError that runs
        no assertion at all (review F-08)."""
        formatter = getattr(registry, 'harvest_from', None)
        self.assertIsNotNone(formatter, 'farm.handling.withdrawal has no one formatter of a withdrawal’s end')
        return formatter(*args, **kwargs)

    def test_the_three_forms(self):
        day = self.day(-5)
        self.assertEqual(self.words(day), f'harvest from {shown_date(day)}')
        self.assertEqual(self.words(day, True), f'harvest from about {shown_date(day)}')
        self.assertEqual(self.words(None), 'end unknown')
        self.assertEqual(self.words(None, True), 'end unknown')
        self.assertEqual(self.words(day, shown=lambda each: each.isoformat()), f'harvest from {day.isoformat()}')
        block = WithdrawalBlock(self.batch, day, True, '', None)
        self.assertEqual(health_tags.harvest_from(block), f'harvest from about {shown_date(day)}')

    def test_it_is_said_in_norwegian_and_turkish(self):
        self.addCleanup(translation.activate, 'en')
        day = self.day(-5)
        for language, (dated, about, unknown) in {
                'nb': ('høsting fra %s', 'høsting fra omtrent %s', 'slutt ukjent'),
                'tr': ('hasat %s tarihinden itibaren', 'hasat yaklaşık %s tarihinden itibaren', 'sonu bilinmiyor')}.items():
            with translation.override(language):
                self.assertEqual(self.words(day), dated % shown_date(day), language)
                self.assertEqual(self.words(day, True), about % shown_date(day), language)
                self.assertEqual(self.words(None), unknown, language)


class EveryPageTests(HarvestInsideTestCase):
    """A bath of T-01 3 days ago with a 7-day withdrawal: held to and including 4 days ahead, harvest from 5 days ahead."""

    def setUp(self):
        super().setUp()
        self.user.groups.add(role('Harvest keeper', *HARVEST_KEEPER))
        self.treatment = self.treat(self.medicine(days=7), 3, 3)
        self.first_free, self.last_held = self.day(-5), self.day(-4)
        self.words = f'harvest from {shown_date(self.first_free)}'
        HandlingPlanItem.objects.create(kind='harvest', date=self.day(-2), unit=self.t1, batch=self.batch,
                                        planned_count=100, facility=self.facility)

    def pages(self):
        return {
            'treatments': self.client.get(reverse('farm:treatments')),
            'units and drawer': self.client.get(reverse('farm:production_units'), {'unit': self.t1.pk}),
            'harvest dialog': self.client.get(reverse('farm:stock_harvest', args=[self.t1.pk])),
            'harvest plan': self.client.get(reverse('farm:handlingplanitem_list')),
            'production plans': self.client.get(reverse('farm:productionplan_list')),
        }

    def test_every_page_says_the_first_free_day_with_the_same_words(self):
        code = self.batch.code
        pages = self.pages()
        for name, page in pages.items():
            with self.subTest(page=name):
                self.assertContains(page, self.words)
                # No page says "until" with either day of the withdrawal: neither the last held nor the first free.
                for day in (self.first_free, self.last_held):
                    self.assertNotContains(page, f'until {shown_date(day)}')
                    self.assertNotContains(page, f'Until {shown_date(day)}')
                    self.assertNotContains(page, f'until about {shown_date(day)}')
        self.assertContains(pages['units and drawer'], f'{code}: {self.words}</span>')                # the row's mark
        self.assertContains(pages['units and drawer'],
                            f'Not suitable for harvest — medicine withdrawal of {code}: {self.words}.')
        self.assertContains(pages['harvest dialog'],
                            f'Not suitable for harvest — medicine withdrawal of {code}: {self.words}.')
        self.assertContains(pages['harvest dialog'], f'Medicine withdrawal decides: {self.words}.')
        self.assertContains(pages['harvest plan'], f'{code}: medicine withdrawal, {self.words}')
        self.assertContains(pages['production plans'], f'{code}: {self.words}')

    def test_the_stored_acknowledgement_the_log_line_and_the_check_say_it_too(self):
        url = reverse('farm:stock_harvest', args=[self.t1.pk])
        fingerprint = self.client.get(url).context['form'].handling.fingerprint
        data = {'token': str(uuid.uuid4()), 'batch': str(self.batch.pk), 'date': self.today.isoformat(), 'count': '100',
                'measured_weight_kg': '13', 'facility': str(self.facility.pk), 'notes': '', 'handling_ack': fingerprint}
        self.assertEqual(self.client.post(url, data).status_code, 302)
        row = HandlingAcknowledgement.objects.get()
        self.assertEqual((row.warning, row.withdrawal_until), ('withdrawal', self.first_free))   # the first free day
        entry = AuditLog.objects.get(entity_type='stock operation', action='create', entity_id=str(row.operation_id))
        logged = entry.changes['Handling warnings acknowledged'][1]
        self.assertIn(f'medicine withdrawal of {self.batch.code}: {self.words}.', logged)
        self.assertNotIn('until', logged.split('Salmosan')[0])
        out = io.StringIO()
        call_command('check_withdrawal', stdout=out)
        iso = f'harvest from {self.first_free.isoformat()}'
        self.assertIn(f'T-01 · {self.batch.code}: {iso}. Salmosan vet., bath', out.getvalue())
        self.assertIn(f'lies inside a withdrawal ({iso}): Salmosan vet., bath', out.getvalue())
        self.assertNotIn(' until ', out.getvalue())

    def test_the_guards_question_says_it(self):
        seen = check.assess('harvest', self.t1, self.day(1), self.batch).fingerprint
        stock_services.record_harvest(self.user, unit=self.t1, batch=self.batch, day=self.day(1), count=100,
                                      measured_weight_kg=Decimal('13'), facility=self.facility, handling_ack=seen)
        change = self.change_of(services.change_last_day, self.user, self.treatment, self.day(2))   # a day longer
        [message] = change.messages()
        self.assertIn(f'lies inside this withdrawal (harvest from {shown_date(self.day(-6))}): medicated fish may '
                      'have gone to food.', message)

    def test_an_unknown_and_a_projected_end(self):
        unknown = WithdrawalBlock(self.batch, None, False, '', None)
        about = WithdrawalBlock(self.batch, self.first_free, True, '', None)
        self.assertEqual(check.withdrawal_text(unknown),
                         f'Not suitable for harvest — medicine withdrawal of {self.batch.code}: end unknown.')
        self.assertEqual(check.withdrawal_text(about), f'Not suitable for harvest — medicine withdrawal of '
                                                       f'{self.batch.code}: harvest from about '
                                                       f'{shown_date(self.first_free)}.')

    def test_the_pages_say_it_in_norwegian_and_turkish(self):
        self.addCleanup(translation.activate, 'en')
        for language, words in (('nb', f'høsting fra {shown_date(self.first_free)}'),
                                ('tr', f'hasat {shown_date(self.first_free)} tarihinden itibaren')):
            Profile.objects.update_or_create(user=self.user, defaults={'language': language})
            for name, page in self.pages().items():
                with self.subTest(language=language, page=name):
                    self.assertContains(page, words)

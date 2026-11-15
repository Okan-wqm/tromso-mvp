"""The fasting warning names the feeding once, at a true moment (flow fault M-05). A feeding without a time counts from
the end of its day, and the warning printed that counted moment as if someone had fed then, beside a note that named
the same feeding by its day: "Last fed 21.10.2026, no time recorded: counted from the end of the day: 0.0 h before
22.10.2026. … Last fed 22.10.2026 00:00, 0.0 h before 22.10.2026"; back-dated, "Last fed 24.10.2026 00:00, 0.0 h before
23.10.2026": a moment after the handling. Only the second sentence went into the critical log. Now one line says it,
with the feeding's own day (and time when it has one); a feeding on the handling's own day says so instead of "0.0 h
before". Which feedings count, the hours and what is stored are unchanged."""
import re
from datetime import time as clock
from decimal import Decimal

from django.urls import reverse
from django.utils import translation

from core.models import AuditLog

from ..models import HandlingAcknowledgement
from ..stock.dates import shown_date, start_of
from .test_harvest import HarvestTestCase


class OneLineTests(HarvestTestCase):
    def test_a_feeding_without_a_time_is_named_by_its_day_once(self):
        self.fed(1)                                                          # yesterday, no time
        result = self.assess()
        [warning] = result.warnings
        self.assertEqual(warning.message(),
                         f'Last fed {shown_date(self.day(1))} (no time recorded: counted from the end of the day) in T-01, '
                         f'0.0 h before {shown_date(self.today)}: the harvest rule asks for 72 h.')
        self.assertNotIn('00:00', warning.message())                         # nobody fed at midnight
        self.assertFalse([note for note in result.notes if 'Last fed' in note or 'asks for' in note])
        # What it counts from, and what is stored, is unchanged: the end of the feeding's day.
        self.assertEqual((warning.last_fed_at, warning.fasted_hours), (start_of(self.today, self.t1), Decimal('0.0')))

    def test_a_feeding_with_a_time_is_named_by_its_moment_once(self):
        self.fed(1, at=clock(18, 0))
        result = self.assess()
        self.assertEqual(result.messages(), [f'Last fed {shown_date(self.day(1))} 18:00 in T-01, 6.0 h before '
                                             f'{shown_date(self.today)}: the harvest rule asks for 72 h.'])
        self.assertFalse([note for note in result.notes if 'Last fed' in note])

    def test_a_feeding_on_the_handling_day_says_so_and_names_no_moment_after_it(self):
        self.fed(0, at=clock(9, 0))
        [warning] = self.assess('transport').warnings
        self.assertEqual(warning.message(), f'Fed on the day of the handling itself (09:00): no fast before '
                                            f'{shown_date(self.today)}; the transport rule asks for 24 h.')
        # Back-dated, without a time: the handling of yesterday, the feeding of yesterday.
        self.fed(1)
        [dated] = self.assess('transport', days_ago=1).warnings
        self.assertEqual(dated.message(), f'Fed on the day of the handling itself (no time recorded): no fast before '
                                          f'{shown_date(self.day(1))}; the transport rule asks for 24 h.')
        self.assertNotIn(shown_date(self.today), dated.message())            # the day after the handling is not named
        self.assertEqual(dated.fasted_hours, 0)

    def test_a_fast_long_enough_is_a_note_with_the_same_words(self):
        self.fed(5)                                                          # 96 h before today
        result = self.assess()
        self.assertEqual(result.warnings, [])
        self.assertIn(f'Last fed {shown_date(self.day(5))} (no time recorded: counted from the end of the day) in T-01: '
                      f'96.0 h before {shown_date(self.today)}.', result.notes)
        self.assertIn('The harvest rule for Atlantic salmon asks for 72 h.', result.notes)

    def test_the_dialog_and_the_drawer_say_it_once(self):
        self.fed(1)
        for name, page in (('dialog', self.client.get(reverse('farm:stock_harvest', args=[self.t1.pk]))),
                           ('drawer', self.client.get(reverse('farm:production_units'), {'unit': self.t1.pk}))):
            with self.subTest(page=name):
                self.assertContains(page, f'Last fed {shown_date(self.day(1))} (no time recorded: counted from the '
                                          'end of the day) in T-01, 0.0 h before', count=1)
                self.assertNotContains(page, f'Last fed {shown_date(self.today)} 00:00')
                self.assertNotContains(page, 'counted from the end of the day:')

    def test_the_critical_log_line_says_the_feedings_day_and_the_row_keeps_what_it_counted(self):
        self.fed(1)
        operation = self.harvest(count=100, kilos='5.5', handling_ack=self.assess().fingerprint)
        entry = AuditLog.objects.get(entity_type='stock operation', action='create', entity_id=str(operation.pk))
        logged = entry.changes['Handling warnings acknowledged'][1]
        self.assertEqual(logged, f'Last fed {shown_date(self.day(1))} (no time recorded: counted from the end of the '
                                 f'day) in T-01, 0.0 h before {shown_date(self.today)}: the harvest rule asks for 72 h.')
        row = HandlingAcknowledgement.objects.get()
        self.assertEqual((row.warning, row.last_fed_at, row.fasted_hours, row.required_hours),
                         ('fasting', start_of(self.today, self.t1), Decimal('0.0'), 72))

    def test_the_sentences_are_translated(self):
        """The Norwegian and the Turkish sentences themselves (review F-08: "no English shows" passed on the old code,
        whose sentences were translated too)."""
        self.addCleanup(translation.activate, 'en')
        self.fed(1)
        untimed = self.assess().warnings[0]
        self.fed(0, at=clock(9, 0))
        same_day = self.assess('transport').warnings[0]
        with translation.override('nb'):
            fed, day = shown_date(self.day(1)), shown_date(self.today)
            self.assertRegex(untimed.message(), '^' + re.escape(
                f'Sist fôret {fed} (uten klokkeslett: regnet fra slutten av dagen) i T-01, ')
                + r'\S+ \S+ ' + re.escape(f'før {day}: regelen for ') + r'\S+ krever \S+ \S+\.$')
            self.assertRegex(same_day.message(), '^' + re.escape(
                f'Fôret samme dag som håndteringen (09:00): ingen sulting før {day}; regelen for ')
                + r'\S+ krever \S+ \S+\.$')
        with translation.override('tr'):
            fed, day = shown_date(self.day(1)), shown_date(self.today)
            self.assertRegex(untimed.message(), '^' + re.escape(
                f'Son yemleme {fed} (saat kaydedilmemiş: gün sonundan itibaren sayılır), T-01 biriminde, {day} '
                'öncesinden ') + r'\S+ \S+: \S+ kuralı \S+ \S+ istiyor\.$')
            self.assertRegex(same_day.message(), '^' + re.escape(
                f'İşlemin yapıldığı gün yemlendi (09:00): {day} öncesinde açlık yok; ')
                + r'\S+ kuralı \S+ \S+ istiyor\.$')

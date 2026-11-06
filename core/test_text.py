"""Lower case in the person's language (core/text.py, F-160): Python's str.lower() turns the Turkish dotted capital İ into
"i̇" (an i with a combining dot) and the dotless capital I into an i with a dot; a translated word put in the middle of a
sentence must read as Turkish writes it."""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase
from django.utils import timezone, translation

from farm.templatetags.water import limit_text
from farm.water import parameters
from farm.water.read import Observation, Origin, Reading
from monitoring.cards import render

from .text import lower


class LowerTests(SimpleTestCase):
    def test_turkish_capitals_lower_as_turkish_writes_them_and_other_languages_as_python_does(self):
        with translation.override('tr'):
            self.assertEqual(lower('İtlaf'), 'itlaf')
            self.assertEqual(lower('IŞIK'), 'ışık')
            self.assertEqual(lower('Kritik'), 'kritik')
        with translation.override('en'):
            self.assertEqual(lower('Ice'), 'ice')
        with translation.override('nb'):
            self.assertEqual(lower('Isfritt'), 'isfritt')
        self.assertEqual(lower('İtlaf', 'tr'), 'itlaf')

    def test_the_water_pages_and_the_cards_lower_through_it(self):
        """The two places in the water and monitoring code that put a translated word in a sentence."""
        row = SimpleNamespace(critical_low=None, warning_low=1, warning_high=None, critical_high=None,
                              measure=SimpleNamespace(decimals=0), species=SimpleNamespace(common_name='Laks'),
                              water_type='saltwater', get_water_type_display=lambda: 'Saltwater')
        now = timezone.now()
        sample = Observation(SimpleNamespace(name='Middle', kind='middle'), now - timedelta(hours=1), Origin.MANUAL,
                             {'ph': Decimal('7')}, sample=SimpleNamespace(get_source_display=lambda: 'Kit'))
        reading = Reading(parameters.get('ph'), Decimal('7'), sample, status='ok')
        reading.limits = [SimpleNamespace(critical_low=Decimal(6), warning_low=None, warning_high=None,
                                          critical_high=None)]
        with mock.patch('core.text.lower', side_effect=lambda value, language=None: f'<{value}>') as said:
            self.assertIn('(<Saltwater>)', limit_text(row))
            self.assertIn('<OK>', render.bar(render.face(reading, now)).sentence)
        self.assertEqual(said.call_count, 2)

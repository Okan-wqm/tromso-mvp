"""A converted pH says what was measured in visible text, not in a tooltip only (the independent review of 2026-11-16,
R6). A pH measured on another scale than NBS is stored and shown on the NBS scale; the water page, the history and a
unit's Deffeyes window print the measured value and its scale beside the NBS number (farm/_water_value.html, the one
template every water value is printed through), and the tooltip keeps the whole sentence."""
import re

from django.urls import reverse

from core.models import Profile

from ..water import read
from .test_ph_scale import SeaTestCase

VISIBLE = '<span class="wq-source wq-measured">measured 7.95 on the total scale</span>'


def text(page):
    """The page as a reader sees it: no tag, so no attribute."""
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', page.content.decode()))


class ShownTests(SeaTestCase):
    def setUp(self):
        super().setUp()
        self.record(ph='7.95', temperature_c='12', salinity_ppt='34', alkalinity_mg_l='115', tan_mg_l='1.000')

    def test_the_reading_carries_the_visible_words(self):
        reading = read.unit_water([self.sea])[self.sea.pk].get('ph')
        self.assertEqual(str(reading.measured), 'measured 7.95 on the total scale')
        self.assertIn('Measured 7.95 on the total scale; put on the NBS scale by formula 3', reading.provenance)

    def test_the_water_page_and_the_history_say_it_beside_the_nbs_number(self):
        for query in ({'unit': self.sea.pk}, {'unit': self.sea.pk, 'view': 'history'}, {}):
            with self.subTest(query=query):
                page = self.client.get(reverse('farm:water'), query)
                self.assertContains(page, VISIBLE)
                self.assertRegex(text(page), r'8\.08\s*measured 7\.95 on the total scale')
                # ... and the tooltip keeps the whole sentence.
                self.assertContains(page, 'Measured 7.95 on the total scale; put on the NBS scale by formula 3')

    def test_the_units_chart_window_says_it(self):
        page = self.client.get(reverse('farm:water_unit_chart', args=[self.sea.pk]))
        self.assertContains(page, VISIBLE)

    def test_an_nbs_ph_says_nothing(self):
        self.record(ph='7.80', ph_scale='nbs', temperature_c='12', salinity_ppt='34', hours=0)
        self.assertEqual(read.unit_water([self.sea])[self.sea.pk].get('ph').measured, '')
        # The NBS sample's row says nothing: the pages hold the words once, for the converted sample alone.
        for query in ({'unit': self.sea.pk}, {'unit': self.sea.pk, 'view': 'history'}):
            page = self.client.get(reverse('farm:water'), query)
            self.assertLessEqual(page.content.decode().count('wq-measured'), 1, query)
        history = self.client.get(reverse('farm:water'), {'unit': self.sea.pk, 'view': 'history'})
        self.assertEqual(history.content.decode().count('wq-measured'), 1)       # the converted sample's row only

    def test_every_scale(self):
        for hours, (scale, said) in enumerate((('sws', 'seawater scale (SWS)'), ('free', 'free scale')), start=2):
            self.record(ph='7.95', ph_scale=scale, temperature_c='12', salinity_ppt='34', hours=hours)
            self.assertIn(f'measured 7.95 on the {said}',
                          text(self.client.get(reverse('farm:water'), {'unit': self.sea.pk, 'view': 'history'})))

    def test_in_three_languages(self):
        for language, words in (('nb', 'målt 7,95 på totalskalaen'), ('tr', 'toplam ölçekte 7,95 ölçüldü')):
            with self.subTest(language=language):
                Profile.objects.update_or_create(user=self.user, defaults={'language': language})
                self.assertIn(words, text(self.client.get(reverse('farm:water'), {'unit': self.sea.pk})))

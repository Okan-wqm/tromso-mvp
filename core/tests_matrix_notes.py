"""What an area's Read also reaches is said where a platform admin grants it (owner decision F-168 / F-173, 2026-11-10):
the experiment and report pages show farm figures to a person without Read on the farm areas (a trial's own tanks, a
regulatory filing), on purpose, so the role matrix says it under those two areas, in every language."""
import re

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from . import access
from .models import Profile

SAID = {
    'en': {
        'Experiments': 'Read also shows the farm figures of an experiment’s own tanks (batches, fish, biomass, survival, '
                       'feed conversion) to a person without Read on the farm areas they come from.',
        'Regulatory reports': 'Read also shows and exports the farm figures a report is computed from (stock and '
                              'biomass, slaughter, smolt, cleaner fish, sea-lice counts) to a person without Read on '
                              'the farm areas they come from.',
    },
    'nb': {
        'Forsøk': 'Les viser også driftstallene for forsøkets egne kar (fiskegrupper, fisk, biomasse, overlevelse, '
                  'fôrfaktor) til en person uten Les på driftsområdene de kommer fra.',
        'Lovpålagte rapporter': 'Les viser og eksporterer også driftstallene en rapport beregnes fra (beholdning og '
                                'biomasse, slakt, smolt, rensefisk, lusetellinger) til en person uten Les på '
                                'driftsområdene de kommer fra.',
    },
    'tr': {
        'Deneyler': 'Görüntüle, bir deneyin kendi tanklarının çiftlik rakamlarını da (partiler, balık, biyokütle, hayatta '
                    'kalma, yem dönüşümü) geldikleri çiftlik alanlarında Görüntüle yetkisi olmayan kişiye gösterir.',
        'Yasal raporlar': 'Görüntüle, bir raporun hesaplandığı çiftlik rakamlarını da (stok ve biyokütle, kesim, smolt, '
                          'temizleyici balık, deniz biti sayımları) geldikleri çiftlik alanlarında Görüntüle yetkisi '
                          'olmayan kişiye gösterir ve dışa aktarır.',
    },
}
ROW = re.compile(r'<th scope="row">(?P<area>[^<]+)</th>.*?</tr>\s*(?P<note><tr class="matrix-note">.*?</tr>)?', re.S)


class AreaNoteTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser('root', 'root@example.com', 'x')
        self.client.force_login(self.admin)

    def notes(self, language):
        """{area as the matrix names it: the text of the note row under it} of the role form."""
        Profile.objects.update_or_create(user=self.admin, defaults={'language': language})
        page = self.client.get(reverse('core:group_create')).content.decode()
        return {found['area'].strip(): re.sub(r'<[^>]+>', '', found['note'] or '').strip()
                for found in ROW.finditer(page)}

    def test_the_matrix_says_under_experiments_and_reports_that_read_shows_farm_figures(self):
        for language, said in SAID.items():
            notes = self.notes(language)
            for area, sentence in said.items():
                with self.subTest(language=language, area=area):
                    self.assertIn(sentence, notes[area].replace('&#x27;', "'"))

    def test_only_those_two_areas_carry_such_a_note(self):
        noted = {str(area.label) for area in access.areas() if area.note}
        self.assertEqual(noted, {'Experiments', 'Regulatory reports'})
        notes = self.notes('en')
        self.assertEqual(notes['Sites'], '')

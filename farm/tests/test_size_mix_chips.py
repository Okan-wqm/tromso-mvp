"""A unit that already holds batches of one species further apart in weight than the species' size limit (stocked with
the acknowledgement, or weighed apart since) says so on the meal board and on Production units: a warning chip with the
heaviest and the lightest average and the limit, read from the stock now, gone when the mix is."""
from decimal import Decimal

from django.urls import reverse

from core.models import Profile

from ..stock import read, services
from .helpers import role
from .test_cleaner_fish import CleanerFishTestCase
from .test_size_mix import SizeMixTestCase, stocked

D = Decimal


class MixedSizesChipTests(SizeMixTestCase):
    def setUp(self):
        super().setUp()
        self.user.groups.add(role('Board reader', 'view_feedingrecord'))
        self.little = self.small(size_mix_ack=True)
        self.chip = (f'<span>Mixed sizes: {stocked("4,217 g", self.day(10))} and {stocked("78.0 g", self.day(5))} '
                     '(limit 2×)</span>')     # no feeding table: measured weights, with the day they were measured

    def pages(self):
        return self.client.get(reverse('farm:meal_board')), self.client.get(reverse('farm:production_units'))

    def test_the_board_and_production_units_show_the_mix_once_on_the_unit(self):
        mix, = read.stock_of([self.t1])[self.t1.pk].size_mixes
        self.assertEqual((mix.heavy, mix.light, mix.heavy_g, mix.light_g, mix.limit),
                         (self.big, self.little, D(4217), D(78), D(2)))
        for page in self.pages():
            with self.subTest(page=page.request['PATH_INFO']):
                self.assertContains(page, self.chip, count=1)
                self.assertContains(page, 'data-status="warning"')

    def test_no_chip_within_the_limit_without_a_limit_or_once_the_mix_has_gone(self):
        self.small(self.t2, weight='150', days_ago=6)
        self.small(self.t2, weight='100', days_ago=5)                      # 1.5 times: within
        self.assertEqual(read.stock_of([self.t2])[self.t2.pk].size_mixes, [])
        self.salmon.max_weight_ratio = None
        self.salmon.save()
        for page in self.pages():
            self.assertNotContains(page, 'Mixed sizes')
        self.salmon.max_weight_ratio = D(2)
        self.salmon.save()
        services.record_transfer(self.user, source=self.t1, batch=self.little, day=self.day(1), legs=[(self.t2, 1000)],
                                 reason='split')                           # 78 g beside 150 and 100 g: 1.9 times
        for page in self.pages():
            self.assertNotContains(page, 'Mixed sizes')

    def test_the_limit_is_shown_as_set(self):
        self.salmon.max_weight_ratio = D('2.5')
        self.salmon.save()
        self.assertContains(self.pages()[0], '(limit 2.5×)</span>', count=1)

    def test_the_chip_speaks_each_language(self):
        for language, word in {'nb': 'Blandede størrelser', 'tr': 'Karışık boylar'}.items():
            Profile.objects.update_or_create(user=self.user, defaults={'language': language})
            for page in self.pages():
                with self.subTest(language=language, page=page.request['PATH_INFO']):
                    self.assertContains(page, word, count=1)


class CleanerFishMakeNoMixTests(CleanerFishTestCase):
    def test_salmon_and_lumpfish_of_any_sizes_are_no_mix(self):
        for species in (self.salmon, self.lump):
            species.max_weight_ratio = D(2)
            species.save()
        self.assertEqual(read.stock_of([self.cage])[self.cage.pk].size_mixes, [])     # 125 g salmon, 50 g lumpfish
        self.assertNotContains(self.client.get(reverse('farm:meal_board')), 'Mixed sizes')
        self.assertNotContains(self.client.get(reverse('farm:production_units')), 'Mixed sizes')

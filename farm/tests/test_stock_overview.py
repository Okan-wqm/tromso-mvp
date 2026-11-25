"""The stock part of the redesigned Production overview (farm.stock.views.overview), from one read of the stock: the
tiles of today's overview with the number of batches the fish are in, and the units whose fish are held by a medicine
withdrawal today, each with its blocks (what Production units marks on the row); nothing for a person who may not read
the stock. The tiles of today's page (`overview_tiles`) are unchanged."""
from django.contrib.auth import get_user_model

from ..stock import views as stock_views
from .test_health import HealthTestCase


class StockOverviewTests(HealthTestCase):
    def test_the_fish_tile_counts_the_batches_and_the_tiles_are_todays(self):
        self.stock(self.t2)
        found = stock_views.overview(self.user)
        tiles = {tile['key']: tile for tile in found['tiles']}
        self.assertEqual(tiles['fish']['batches'], 2)
        self.assertEqual([tile['count'] for tile in found['tiles']],
                         [tile['count'] for tile in stock_views.overview_tiles(self.user)])

    def test_a_unit_held_by_a_withdrawal_is_listed_with_its_blocks(self):
        self.treat(self.medicine(days=7), 5, 3)
        holds = stock_views.overview(self.user)['holds']
        self.assertEqual([hold['unit'] for hold in holds], [self.t1])
        self.assertTrue(holds[0]['blocks'])
        self.assertIn(f'unit={self.t1.pk}', holds[0]['url'])

    def test_nothing_for_a_person_who_may_not_read_the_stock(self):
        self.assertIsNone(stock_views.overview(get_user_model().objects.create_user('nobody', 'n@example.com', 'x')))

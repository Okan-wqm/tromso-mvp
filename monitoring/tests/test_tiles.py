"""A fitted card's water: the design's tiles or a row a value, one column of rows or two: the server's one answer
(monitoring/cards/render.py tiled and columns_for), from the catalogue's measures of the water (tiles, tile_units,
rows_units: stated there once) and the place a template gives it (validate.fitted_place, as the validator measures
it). Near each threshold, on either side (review 2, N1 and N5); no database."""
from types import SimpleNamespace as N

from django.test import SimpleTestCase

from monitoring.cards import builtin, catalogue, render
from monitoring.cards.validate import fitted_place

WATER = catalogue.WIDGETS['water_table']


def card_of(measure=builtin.BIG_MEASURE, **water):
    """A card drawn with the built-in Big layout, its water widget (w6) changed by `water` (its w, h)."""
    widgets = [{**widget, **water} if widget['id'] == 'w6' else widget for widget in builtin.BIG_LAYOUT['widgets']]
    template = N(layout={'schema': 1, 'widgets': widgets}, rows=21, measure=measure, fill=measure[1] > measure[0])
    return N(template=template)


VIEW = N(id='w6')


def tiles(card, values, columns=1):
    return render.tiled(card, VIEW, tuple(tuple(range(values // columns)) for _ in range(columns)))


class TilesTests(SimpleTestCase):
    def test_the_measures_are_stated_once_in_the_catalogue(self):
        self.assertEqual(render.WATER_TILES, WATER.tiles[0] * WATER.tiles[1])
        self.assertEqual(WATER.tiles, (4, 2))

    def test_the_built_in_big_card_sets_eight_values_or_fewer_as_tiles_four_to_a_line(self):
        self.assertEqual(tiles(card_of(), 5), 4)
        self.assertEqual(tiles(card_of(), render.WATER_TILES), 4)
        self.assertEqual(tiles(card_of(), render.WATER_TILES + 1), 0)
        self.assertEqual(tiles(card_of(), 6, columns=2), 0)

    def test_the_place_decides_near_its_threshold(self):
        per, lines = WATER.tiles
        wide, high = WATER.tile_units
        # the height: the lowest water place that holds the lines of tiles, and the one under it
        holds = next(h for h in range(1, 13) if fitted_place({'w': 12, 'h': h}, 21, builtin.BIG_MEASURE)[1] >= lines * high)
        self.assertEqual(tiles(card_of(h=holds), 5), per)
        self.assertEqual(tiles(card_of(h=holds - 1), 5), 0)
        # the width: the narrowest place that holds a line of tiles, and the one under it
        fits = next(w for w in range(1, 13) if fitted_place({'w': w, 'h': 6}, 21, builtin.BIG_MEASURE)[0] >= per * wide)
        self.assertEqual(tiles(card_of(w=fits, x=0), 5), per)
        self.assertEqual(tiles(card_of(w=fits - 1, x=0), 5), 0)

    def test_a_card_that_is_not_full_height_has_no_tiles(self):
        self.assertEqual(tiles(card_of(measure=(61, 48)), 5), 0)


class FoldTests(SimpleTestCase):
    """What a Big card drawn at the size of its place folds of its reasons (render.fold): notes past FIT_NOTES; an alert
    (critical, warning, no recent data) only past what the card holds, FIT_ALERTS, and then said in words."""
    def state(self, key, count):
        return N(key=key, reasons=tuple(f'reason {number}' for number in range(count)))

    def test_notes_fold_past_the_first_few(self):
        for key in ('unjudged', 'note', 'ok'):
            folded = render.fold(self.state(key, 10))
            self.assertEqual((folded.shown, len(folded.rest), folded.alerts), (render.FIT_NOTES, 10 - render.FIT_NOTES, False))
        self.assertEqual(render.fold(self.state('note', render.FIT_NOTES)).rest, ())

    def test_an_alert_is_never_folded_while_the_card_holds_it(self):
        for key in ('critical', 'warning', 'blind'):
            folded = render.fold(self.state(key, render.FIT_ALERTS))
            self.assertEqual((folded.shown, folded.rest), (render.FIT_ALERTS, ()), key)
            past = render.fold(self.state(key, render.FIT_ALERTS + 2))
            self.assertEqual((len(past.rest), past.alerts), (2, True), key)
        self.assertGreater(render.FIT_ALERTS, render.FIT_NOTES)


class ColumnsTests(SimpleTestCase):
    def test_two_columns_of_rows_only_where_two_fit_side_by_side(self):
        """The built-in Big card's water (47 units wide) holds one column of rows: 15 and 17 values stand in it (two
        columns there lay over each other: review 2, N1). A card wide enough for two holds two, past WATER_ROWS only."""
        two = 2 * WATER.rows_units + render.ROWS_GAP
        self.assertLess(fitted_place({'w': 12, 'h': 6}, 21, builtin.BIG_MEASURE)[0], two)
        for count in (render.WATER_ROWS, render.WATER_ROWS + 1, 17):
            self.assertEqual(render.columns_for(card_of(), VIEW, count), 1, count)
        wide = (catalogue.MEASURE_W[1], catalogue.MEASURE_H[1])
        self.assertGreaterEqual(fitted_place({'w': 12, 'h': 6}, 21, wide)[0], two)
        self.assertEqual(render.columns_for(card_of(measure=wide), VIEW, render.WATER_ROWS), 1)
        self.assertEqual(render.columns_for(card_of(measure=wide), VIEW, render.WATER_ROWS + 1), 2)

    def test_a_card_that_flows_has_one_column(self):
        flowing = N(template=N(layout={'schema': 1, 'widgets': []}, rows=0, measure=None, fill=False))
        self.assertEqual(render.columns_for(flowing, VIEW, 20), 1)

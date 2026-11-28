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


def drawn(card):
    """`card` with what render._views reads of it besides its template: its unit, the sections its person may read, the
    sources that could not be read."""
    card.unit, card.sections, card.failed = N(pk=1), frozenset({'water', 'chart', 'stock', 'feeding', 'health'}), ()
    return card


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
    """What a fitted card shows of its reasons (render.fold), one rule for every size of card: notes past what it holds
    fold into "+N"; an alert (critical, warning, no recent data) only past what the card holds, and then said in words.
    A Big card drawn at the size of its place (the pane, a wall) holds LINES: FIT_ALERTS of an alert card's (measured:
    the browser test holds every card's chart a quarter of a line above its least height, frontend/test/
    monitoring.pages.ts) and FIT_NOTES of a note card's, the line that says how many more among them; a Small card's
    one line the worst reason."""
    def state(self, key, count, words='reason'):
        return N(key=key, reasons=tuple(f'{words} {number}' for number in range(count)))

    def test_what_each_size_holds(self):
        self.assertEqual(render.HOLDS, {'big': (render.FIT_ALERTS, render.FIT_NOTES), 'small': (1, 1)})
        # (measured: at eight lines of reasons the chart keeps half a line above its least height on every surface in
        # en, nb and tr; at nine it is at its least)
        self.assertEqual((render.FIT_ALERTS, render.FIT_NOTES), (8, 3))

    def test_a_reasons_lines_come_from_its_words_and_the_cards_width(self):
        per_line = int((builtin.BIG_MEASURE[0] - render.REASON_INSET) / render.REASON_CHAR_EM)
        self.assertEqual(render.reason_lines('x' * per_line, builtin.BIG_MEASURE[0]), 1)
        self.assertEqual(render.reason_lines('x' * (per_line + 1), builtin.BIG_MEASURE[0]), 2)
        self.assertEqual(render.reason_lines('x' * (per_line + 1), builtin.BIG_MEASURE[0] * 2), 1)

    def test_notes_fold_past_what_the_card_holds(self):
        for key in ('unjudged', 'note', 'ok'):
            folded = render.fold(self.state(key, 10))
            # (one of its lines is the "+N")
            self.assertEqual((folded.shown, len(folded.rest), folded.alerts, folded.lines),
                             (render.FIT_NOTES - 1, 10 - render.FIT_NOTES + 1, False, render.FIT_NOTES - 1), key)
        held = render.fold(self.state('note', render.FIT_NOTES))
        self.assertEqual((held.rest, held.lines), ((), render.FIT_NOTES))

    def test_an_alert_is_never_folded_while_the_card_holds_it(self):
        for key in ('critical', 'warning', 'blind'):
            folded = render.fold(self.state(key, render.FIT_ALERTS))
            self.assertEqual((folded.shown, folded.rest, folded.lines), (render.FIT_ALERTS, (), render.FIT_ALERTS), key)
            past = render.fold(self.state(key, render.FIT_ALERTS + 2))
            self.assertEqual((past.shown, len(past.rest), past.alerts, past.lines),
                             (render.FIT_ALERTS - 1, 3, True, render.FIT_ALERTS - 1), key)
        self.assertGreater(render.FIT_ALERTS, render.FIT_NOTES)

    def test_a_reason_of_two_lines_takes_two_of_what_the_card_holds(self):
        long = 'x' * 100                                       # two lines of the built-in Big card
        folded = render.fold(N(key='critical', reasons=(long,) * 5))
        self.assertEqual((folded.shown, len(folded.rest), folded.lines), (3, 2, 6))
        # the first is said, however long
        self.assertEqual(render.fold(N(key='critical', reasons=('x' * 2000, 'y'))).shown, 1)

    def test_a_small_card_says_its_worst_and_never_hides_that_there_are_more(self):
        for key in ('critical', 'warning', 'blind'):
            folded = render.fold(self.state(key, 8), 'small')
            self.assertEqual((folded.shown, len(folded.rest), folded.alerts), (1, 7, True), key)
            self.assertEqual(render.fold(self.state(key, 1), 'small').rest, (), key)
        notes = render.fold(self.state('unjudged', 4), 'small')
        self.assertEqual((notes.shown, len(notes.rest), notes.alerts), (1, 3, False))


class GivesTests(SimpleTestCase):
    def test_the_chart_of_a_full_height_card_gives_way_down_to_its_least_height(self):
        """The chart gives way to the reasons first, down to its give_units (never more than its place); the other
        widgets never do; a card that is not full height has no least height to give way to."""
        chart = catalogue.WIDGETS['chart']
        self.assertEqual(chart.give_units, 22.0)
        self.assertEqual([spec.type for spec in catalogue.WIDGETS.values() if spec.give_units], ['chart'])
        views = {view.type: view for view in render._views(drawn(card_of()), lambda spec: True)}
        self.assertEqual(views['chart'].give, 'cm-22')
        self.assertEqual({view.give for kind, view in views.items() if kind != 'chart'}, {''})
        low = card_of()
        low.template.layout = {'schema': 1, 'widgets': [{**widget, 'h': 2} if widget['type'] == 'chart' else widget
                                                        for widget in builtin.BIG_LAYOUT['widgets']]}
        place = fitted_place({'w': 12, 'h': 2}, 21, builtin.BIG_MEASURE)[1]
        self.assertEqual({view.type: view for view in render._views(drawn(low), lambda spec: True)}['chart'].give,
                         f'cm-{int(place)}')
        wide = drawn(card_of(measure=(61, 48)))
        self.assertEqual({view.type: view for view in render._views(wide, lambda spec: True)}['chart'].give, '')


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

"""The Big card (owner decisions 4, 10, 11, 12, 2026-11-12): `mode=big` draws EVERY card of the screen as the built-in Big
template, fitted; its chart is the unit's Deffeyes chart as a picture of the card's own size, drawn by the server from
the chemistry core's figure in one of two views: close (the rule of farm.water.deffeyes.close_window) by default, full
scale with `?chart=full`, and `?zoom=<unit>` for the cards that differ from the screen's view. The views are in the
address, canonical, and the poll's fragment answers the same view. Old inputs are "last known position"; a chart that
cannot be worked out says why; no dosing advice is given, and the box says why."""
from django.urls import reverse

from farm.water import calculation, deffeyes

from .. import read
from ..cards import builtin
from .test_band import band_of
from .test_small import SmallCase, card_of, nodes, text

PAGE, CARDS = reverse('monitoring:monitor'), reverse('monitoring:cards')
BIG = {'mode': 'big'}
# Raise it only with a reason; a card that grows is a wall that slows.
BIG_CARD_BYTES = 26000


class BigCase(SmallCase):
    def page(self, url=PAGE, **query):
        response = self.client.get(url, {**BIG, **query})
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def chart(self, html, unit):
        (found,) = nodes(card_of(html, unit), 'monitor-chart-svg')
        return found


class ViewTests(BigCase):
    def test_the_view_draws_every_card_big_and_fitted(self):
        self.good_water()
        html = self.page()
        for unit in (self.t1, self.t2):
            card = card_of(html, unit)
            self.assertEqual(card.attrs['data-template'], str(builtin.BIG))
            self.assertEqual(card.classes[2:5], ['is-fit', 'mw-48', 'mh-61'])
            self.assertEqual([each.classes for each in card.walk() if 'card-grid' in each.classes], [['card-grid', 'gr-21']])
        card = card_of(html, self.t2)
        placed = [each.classes[1:] for each in card.walk() if each.classes[:1] == ['w']]
        self.assertEqual([place[0] for place in placed],
                         ['w-value'] * 4 + ['w-chart', 'w-water_table', 'w-dosing', 'w-points', 'w-stock'])
        self.assertEqual(placed[4][1:], ['gx-0', 'gy-2', 'gw-12', 'gh-11'])           # the chart: eleven rows of 21
        self.assertIn('<option value="big" selected>Big</option>', html)
        self.assertNotIn(' style=', html[html.index('data-key="card:'):])             # nothing the policy would block

    def test_the_chart_is_the_cores_figure_in_the_close_view(self):
        self.good_water()
        html = self.page()
        drawn = self.chart(html, self.t2)
        self.assertEqual(drawn.classes, ['monitor-chart-svg', 'chart-view-close'])
        self.assertIsNone(drawn.attrs.get('viewbox'))                                # its text is the card's text
        (plot,) = nodes(drawn, 'chart-plot')
        self.assertEqual((plot.attrs['viewbox'], plot.attrs['preserveaspectratio']), ('0 0 1000 1000', 'none'))
        made = calculation.chart_of(self.t2)
        analysis = made.calculation.analysis
        figure = deffeyes.card_figure(analysis)
        limits = analysis.limits
        self.assertIsNotNone(limits.alkalinity_low_mg_l)
        window = deffeyes.close_window(figure, (limits.alkalinity_low_mg_l / 50.04, limits.alkalinity_high_mg_l / 50.04))
        self.assertFalse(window.full)
        picture = deffeyes.picture(figure, window)
        (water,) = nodes(drawn, 'chart-water')
        self.assertEqual((water.attrs['cx'], water.attrs['cy']), (f'{picture.water[0]}%', f'{picture.water[1]}%'))
        self.assertEqual([each.classes[-1] for each in drawn.walk() if 'chart-region' in each.classes],
                         ['chart-region-nh3', 'chart-region-co2', 'chart-region-safe'])
        said = [text(each) for each in drawn.walk() if each.tag == 'text']
        self.assertIn(f'CO₂ > {deffeyes.shown(limits.co2_mg_l, 1)} mg/L', said)
        self.assertIn(f'NH₃-N > {deffeyes.shown(limits.nh3_n_mg_l, 4)} mg/L', said)
        self.assertIn('safe', said)
        self.assertIn(f'close view · ×{window.zoom:.1f}', said)
        self.assertIn('this card’s own scale', said)
        self.assertTrue(nodes(drawn, 'chart-locator-window'))
        # its name says where the water is and every figure the picture is of
        self.assertRegex(drawn.attrs['aria-label'],
                         r'^Deffeyes chart, T-02: In the safe zone · \d\.\d\d pH to the CO₂ limit; pH 7\.20, '
                         r'alkalinity 95 mg/L, DIC \d\.\d\d mmol/L, calculated CO₂ \d+\.\d mg/L; close view · ×\d')
        caption = next(each for each in card_of(html, self.t2).walk() if each.tag == 'figcaption')
        self.assertIn('In the safe zone', text(caption))
        self.assertNotIn('truncate', ' '.join(' '.join(each.classes) for each in caption.walk()))   # nothing to cut

    def test_full_scale_for_the_screen_and_the_cards_that_differ(self):
        self.good_water()
        full = self.page(chart='full')
        drawn = self.chart(full, self.t2)
        self.assertEqual(drawn.classes, ['monitor-chart-svg', 'chart-view-full'])
        self.assertIn('full scale · axes from zero', [text(each) for each in drawn.walk() if each.tag == 'text'])
        self.assertFalse(nodes(drawn, 'chart-locator-window'))
        # one card differs from the screen's view, either way
        zoomed = self.page(zoom=str(self.t2.pk))
        self.assertIn('chart-view-full', self.chart(zoomed, self.t2).classes)
        back = self.page(chart='full', zoom=str(self.t2.pk))
        self.assertIn('chart-view-close', self.chart(back, self.t2).classes)
        # the fragment answers the same view (the poll keeps it)
        fragment = self.page(CARDS, chart='full')
        self.assertIn('chart-view-full', self.chart(fragment, self.t2).classes)

    def test_the_switches_are_links_and_the_address_is_canonical(self):
        self.good_water()
        html = self.page()
        band = band_of(html)
        (switch,) = nodes(band, 'monitor-view')
        links = [(text(each), each.attrs['href'], each.attrs.get('aria-current')) for each in switch.walk() if each.tag == 'a']
        self.assertEqual(links, [('Close-up', f'{PAGE}?mode=big', 'true'), ('Full scale', f'{PAGE}?chart=full&mode=big', None)])
        (own,) = nodes(card_of(html, self.t2), 'monitor-view')
        links = [(text(each), each.attrs['href'], each.attrs['data-poll-url'], each.attrs.get('aria-current'))
                 for each in own.walk() if each.tag == 'a']
        self.assertEqual(links, [('Close-up', f'{PAGE}?mode=big', f'{CARDS}?mode=big', 'true'),
                                 ('Full scale', f'{PAGE}?mode=big&zoom={self.t2.pk}',
                                  f'{CARDS}?mode=big&zoom={self.t2.pk}', None)])
        # the band's switch sets the whole screen and clears the cards that differ
        zoomed = band_of(self.page(zoom=str(self.t2.pk)))
        (switch,) = nodes(zoomed, 'monitor-view')
        self.assertEqual([each.attrs['href'] for each in switch.walk() if each.tag == 'a'],
                         [f'{PAGE}?mode=big', f'{PAGE}?chart=full&mode=big'])
        # a screen with no chart has no switch; a value that names nothing is dropped
        self.assertFalse(nodes(band_of(self.client.get(PAGE).content.decode()), 'monitor-view'))
        params = read.Params.from_query(self.client.get(PAGE, {'chart': 'sideways', 'zoom': 'x,' + str(self.t2.pk)}).wsgi_request.GET)
        self.assertEqual((params.chart, params.zoom), ('', frozenset({str(self.t2.pk)})))
        self.assertEqual(read.Params(mode='big', chart='full', zoom=frozenset({'b', 'a'})).canonical(),
                         'chart=full&mode=big&zoom=a%2Cb')

    def test_one_box_for_the_screens_charts_at_full_scale(self):
        (other,) = self.farm_of(1, fresh=False)
        self.good_water()
        self.good_water(other, alkalinity_mg_l='420')                 # a water whose own box is larger than T-02's
        cards = {card.unit.pk: card for card in read.cards(
            [self.t2, other], self.reader, read.resolve.Choice(view=builtin.BIG, chart='full'))}
        boxes = [deffeyes.card_figure(card.chart.calculation.analysis, card.chart_extent)['box']
                 for card in cards.values()]
        self.assertEqual(boxes[0], boxes[1])
        own = deffeyes.card_figure(cards[self.t2.pk].chart.calculation.analysis)['box']
        self.assertNotEqual(own, boxes[0])
        self.assertEqual({card.chart_view for card in cards.values()}, {deffeyes.FULL})


class BigCardTests(BigCase):
    def test_old_inputs_are_the_last_known_position(self):
        self.sample(self.t2, hours=1, temperature_c='13.2', oxygen_mg_l='8.1', alkalinity_mg_l='95')
        self.sample(self.t2, hours=100, ph='7.4', tan_mg_l='0.5')                    # a pH says something for 72 hours
        html = self.page()
        drawn = self.chart(html, self.t2)
        self.assertIn('is-old', drawn.classes)
        self.assertIn('last known position', [text(each) for each in drawn.walk() if each.tag == 'text'])
        caption = next(each for each in card_of(html, self.t2).walk() if each.tag == 'figcaption')
        self.assertTrue(text(caption).startswith('Last known position · old: pH'))
        self.assertTrue([each for each in caption.walk() if 'data-chart-old' in each.attrs])
        self.assertIn('Last known position', drawn.attrs['aria-label'])

    def test_water_past_the_co2_border_tints_its_region(self):
        self.good_water(ph='6.60')
        html = self.page()
        drawn = self.chart(html, self.t2)
        self.assertEqual(drawn.classes, ['monitor-chart-svg', 'chart-view-close', 'in-co2', 'is-critical'])
        caption = next(each for each in card_of(html, self.t2).walk() if each.tag == 'figcaption')
        self.assertRegex(text(caption), r'^In the CO₂ region: \d\.\d\d pH past the limit')

    def test_a_chart_that_cannot_be_worked_out_says_why_and_assumes_nothing(self):
        self.sample(self.t2, hours=1, temperature_c='13.2', oxygen_mg_l='8.1')
        html = self.page()
        card = card_of(html, self.t2)
        self.assertFalse(nodes(card, 'monitor-chart-svg'))
        (figure,) = nodes(card, 'monitor-chart')
        said = text(figure)
        self.assertIn('The chart cannot be drawn', said)
        self.assertIn('Missing: no value of pH (NBS scale), Alkalinity (mg/L as CaCO₃).', said)
        self.assertIn('Nothing is assumed for a missing value.', said)
        self.assertIn('No chart', said)

    def test_no_dosing_advice_and_why(self):
        self.good_water()
        card = card_of(self.page(), self.t2)
        (box,) = [each for each in card.walk() if 'w-dosing' in each.classes]
        self.assertEqual([text(each) for each in box.walk() if each.tag == 'p'],
                         ['Dosing advice', 'No dosing advice',
                          'No target, reagent or dosing volume is set for these fish yet.'])

    def test_the_stock_and_the_other_points(self):
        self.good_water()
        card = card_of(self.page(), self.t2)
        (stock,) = [each for each in card.walk() if 'w-stock' in each.classes]
        self.assertIn('12,000', text(stock))
        (points,) = [each for each in card.walk() if 'w-points' in each.classes]
        # the worked example's T-02 has other points with no value yet: each says so in words, never a dash
        names = [text(each) for each in points.walk() if each.tag == 'span' and 'tw:truncate' in each.classes]
        self.assertGreaterEqual(len(names), 1)
        self.assertIn('no data', text(points))
        self.assertNotIn('—', text(points))
        (bare,) = self.farm_of(1)                                      # a unit with its middle point alone
        alone = card_of(self.page(), bare)
        (none,) = [each for each in alone.walk() if 'w-points' in each.classes]
        self.assertEqual(text(none), 'No other sampling point')

    def test_every_value_is_a_row_with_its_strip_its_source_and_its_arrival(self):
        self.good_water()
        card = card_of(self.page(), self.t2)
        (rows,) = nodes(card, 'monitor-rows')
        labels = [text(each) for each in nodes(rows, 'monitor-row')]
        self.assertIn('O₂ (mg/L)', labels)
        self.assertIn('pH', labels)
        self.assertGreaterEqual(len(labels), 5)
        said = text(rows)
        self.assertRegex(said, r'Meter or test kit \d\d:\d\d · 1 h')              # the source whole, the clock, the age
        self.assertNotIn('truncate', ' '.join(' '.join(each.classes) for each in rows.walk()))
        self.assertTrue(nodes(rows, 'monitor-bar-svg'))                            # a strip where a limit row judges
        self.assertFalse([each for each in rows.walk() if 'data-old' in each.attrs])
        # the four large figures: the strip beside the figure, and under it the source and the age (review R1)
        tiles = [each for each in card.walk() if 'w-value' in each.classes]
        self.assertTrue(nodes(tiles[0], 'monitor-bar-svg'))
        self.assertEqual(text(nodes(tiles[0], 'monitor-under')[0]), 'sample · 1 h')
        self.assertEqual(text(nodes(tiles[3], 'monitor-under')[0]), 'calc. · 1 h')

    def test_an_old_row_says_old_and_its_day(self):
        self.sample(self.t2, hours=1, temperature_c='13.2', oxygen_mg_l='8.1', alkalinity_mg_l='95')
        self.sample(self.t2, hours=100, ph='7.4')
        card = card_of(self.page(), self.t2)
        (rows,) = nodes(card, 'monitor-rows')
        (old,) = [each for each in rows.walk() if 'data-old' in each.attrs]
        self.assertRegex(text(old.parent) if hasattr(old, 'parent') else text(rows), r'old · \d\d\.\d\d \d\d:\d\d · 4 d')

    def test_every_reason_is_on_the_card_in_full(self):
        self.good_water(oxygen_mg_l='5', ph='5.9')
        card = card_of(self.page(), self.t2)
        (reasons,) = nodes(card, 'monitor-reasons')
        lines = [text(each) for each in reasons.children if not isinstance(each, str)]
        self.assertEqual(len(lines), len(read.cards([self.t2], self.reader, read.resolve.Choice(view=builtin.BIG))[0].state.reasons))
        self.assertTrue(lines[0].startswith('O₂ (mg/L) 5.00 · critical limit 6.00'))
        self.assertTrue(any(line.startswith('pH 5.90 · critical limit 6.00') for line in lines), lines)

    def test_the_chart_says_what_the_farm_has_not_set(self):
        from farm.models import WaterLimit
        WaterLimit.objects.filter(parameter='nh3_n_mg_l').delete()
        self.good_water()
        drawn = self.chart(self.page(), self.t2)
        notes = [text(each) for each in nodes(drawn, 'chart-note')]
        self.assertEqual(notes, ['no NH₃ limit for these fish'])
        self.assertNotIn('chart-region-safe', ' '.join(' '.join(each.classes) for each in drawn.walk()))
        self.assertNotIn('chart-region-nh3', ' '.join(' '.join(each.classes) for each in drawn.walk()))

    def test_a_big_card_stays_within_its_weight(self):
        """What one Big card may weigh in the page (the mock-up's was 21.6 KB): pinned from what these cards weigh."""
        import re
        self.good_water(oxygen_mg_l='5', ph='5.9')
        html = self.page()
        card = re.search(rf'<article[^>]*card:{self.t2.pk}.*?</article>', html, re.S).group(0)
        self.assertLessEqual(len(card.encode()), BIG_CARD_BYTES)
        self.assertGreater(len(card.encode()), 8000)

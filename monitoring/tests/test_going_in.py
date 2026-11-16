"""Phase 1D on the server: going into a tank. A small card's code opens the unit's Big card in a pane beside the overview
(`?focus=<unit>`: a link, canonical, kept by the poll; the pane is a fragment of its own, polled like the grid); the
band's chips open the unit they name; everything in the band a key can stand on has an id, so a poll that replaces the
band gives the focus back (review R8). What the Small card only said in a title is in plain sight on the Big one
(review R11), the Small card keeps the oxygen's saturation when its mg/L is old, the pH window says in words that no
alkalinity band is set (review R6), and the window's words are placed by one rule and never touch (the weak point of
the 1C report)."""
import itertools

from django.http import QueryDict
from django.test import SimpleTestCase
from django.urls import reverse

from farm.models import WaterLimit

from .. import read
from ..cards import render
from .test_small import SmallCase, card_of, nodes, text
from .golden import Tree

PAGE, CARDS, PANE = reverse('monitoring:monitor'), reverse('monitoring:cards'), reverse('monitoring:pane')


def by_id(html):
    """{id: node} of a page; fails on an id that is there twice."""
    found = {}
    for node in Tree(html).root.walk():
        name = node.attrs.get('id')
        if name:
            assert name not in found, f'id {name} twice'
            found[name] = node
    return found


class AddressTests(SimpleTestCase):
    def test_the_focus_is_one_unit_and_one_spelling(self):
        unit = '5f1c2a6e-0000-4000-8000-0000000000aa'
        params = read.Params.from_query(QueryDict(f'mode=small&focus={unit.upper()}&wall=1'))
        self.assertEqual((params.focus, params.canonical()), (unit, f'focus={unit}&mode=small&wall=1'))
        self.assertEqual(params.canonical(focus=''), 'mode=small&wall=1')
        self.assertEqual(read.Params.from_query(QueryDict('focus=nonsense')).focus, '')


class PaneTests(SmallCase):
    def setUp(self):
        super().setUp()
        self.good_water()

    def test_a_small_cards_code_is_the_link_into_its_tank(self):
        html = self.page()
        ids = by_id(html)
        opener = ids[f'open-{self.t2.pk}']
        self.assertEqual((opener.tag, text(opener), opener.attrs['href'], opener.attrs['data-dock'],
                          opener.attrs['aria-expanded']),
                         ('a', 'T-02', f'{PAGE}?focus={self.t2.pk}&mode=small', str(self.t2.pk), 'false'))
        self.assertNotIn('is-open', card_of(html, self.t2).classes)
        # nothing is open: the dock is there for the script and holds no pane
        dock = ids['monitor-dock']
        self.assertEqual((dock.attrs['data-param'], dock.attrs['data-pane-url'], dock.attrs['data-grid-url'],
                          dock.attrs['data-mw'], dock.attrs['data-mh']), ('focus', PANE, CARDS, '48', '61'))
        self.assertFalse(nodes(dock, 'monitor-pane'))

    def test_the_address_with_a_focus_draws_the_big_card_beside_the_overview(self):
        html = self.page(focus=str(self.t2.pk))
        ids = by_id(html)                                           # (and no id is on the page twice)
        dock = ids['monitor-dock']
        (pane,) = nodes(dock, 'monitor-pane')
        self.assertEqual((pane.attrs['role'], pane.attrs['aria-label'], pane.attrs['data-dock-unit']),
                         ('region', 'Focus: T-02', str(self.t2.pk)))
        (big,) = [each for each in pane.walk() if each.tag == 'article']
        self.assertEqual(big.attrs['id'], f'pane-card-{self.t2.pk}')
        self.assertTrue({'is-fit', 'mw-48', 'mh-61'} <= set(big.classes))
        self.assertIn('data-fill', big.attrs)
        self.assertTrue(nodes(big, 'monitor-chart-svg'))
        # the pane is polled by itself, at its own address, merged by key as the grid is
        (body,) = [each for each in pane.walk() if 'data-window-body' in each.attrs]
        self.assertTrue(body.attrs['data-poll'].startswith(f'{PANE}?focus={self.t2.pk}&mode=small&after='))
        self.assertEqual(body.attrs['data-poll-merge'], 'data-key')
        self.assertEqual([each.attrs.get('data-key') for each in body.children if hasattr(each, 'attrs')],
                         [f'card:{self.t2.pk}'])
        # the overview stays: every small card is still there, the open one marked, its link now closing
        (grid,) = [node for node in Tree(html).root.walk() if 'monitor-grid' in node.classes]
        small = next(node for node in grid.walk() if node.attrs.get('data-key') == f'card:{self.t2.pk}')
        self.assertTrue({'is-open', 'mw-31'} <= set(small.classes))
        opener = ids[f'open-{self.t2.pk}']
        self.assertEqual((opener.attrs['href'], opener.attrs['aria-expanded']), (f'{PAGE}?mode=small', 'true'))
        other = ids[f'open-{self.t1.pk}']
        self.assertEqual(other.attrs['href'], f'{PAGE}?focus={self.t1.pk}&mode=small')
        # closing is a link too, and the grid's own poll keeps the focus
        close = ids['dock-close']
        self.assertEqual((close.tag, close.attrs['href']), ('a', f'{PAGE}?mode=small'))
        self.assertIn('data-dock-close', close.attrs)
        self.assertTrue(grid.attrs['data-poll'].startswith(f'{CARDS}?focus={self.t2.pk}&mode=small&after='))

    def test_the_grids_fragment_keeps_the_focus_through_its_polls(self):
        response = self.client.get(CARDS, {'mode': 'small', 'focus': str(self.t2.pk)})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response['X-Poll-Next'].startswith(f'{CARDS}?focus={self.t2.pk}&mode=small&after='))
        self.assertIn('is-open', card_of(response.content.decode(), self.t2).classes)
        self.assertEqual(self.client.get(response['X-Poll-Next']).status_code, 204)

    def test_the_pane_is_a_fragment_of_its_own(self):
        query = {'mode': 'small', 'focus': str(self.t2.pk)}
        response = self.client.get(PANE, query)
        self.assertEqual((response.status_code, response['Cache-Control']), (200, 'no-store'))
        html = response.content.decode()
        tops = [node for node in Tree(html).root.children if hasattr(node, 'attrs')]
        self.assertEqual([(node.tag, node.attrs.get('data-key')) for node in tops], [('article', f'card:{self.t2.pk}')])
        self.assertTrue(response['X-Poll-Next'].startswith(f'{PANE}?focus={self.t2.pk}&mode=small&after='))
        self.assertEqual(self.client.get(response['X-Poll-Next']).status_code, 204)
        # its chart's own switch asks the PANE again and keeps the focus in the page's address
        zoom = by_id(html)[f'pane-zoom-{self.t2.pk}']
        self.assertEqual(zoom.attrs['aria-current'], 'true')
        full = [each for each in Tree(html).root.walk() if each.tag == 'a' and each.attrs.get('data-poll-url', '').startswith(PANE)
                and 'aria-current' not in each.attrs]
        self.assertEqual([(each.attrs['href'], each.attrs['data-poll-url']) for each in full],
                         [(f'{PAGE}?focus={self.t2.pk}&mode=small&zoom={self.t2.pk}',
                           f'{PANE}?focus={self.t2.pk}&mode=small&zoom={self.t2.pk}')])
        drawn = self.client.get(PANE, {**query, 'zoom': str(self.t2.pk)}).content.decode()
        self.assertIn('chart-view-full', drawn)
        # a unit that is gone, no unit at all, a person without the page's right
        self.assertEqual(self.client.get(PANE, {'focus': '5f1c2a6e-0000-4000-8000-0000000000aa'}).status_code, 404)
        self.assertEqual(self.client.get(PANE).status_code, 404)
        self.as_person('outsider', 'view_tank')
        self.assertEqual(self.client.get(PANE, query).status_code, 403)

    def test_in_the_pane_the_code_goes_on_to_the_unit_and_what_was_a_title_is_in_sight(self):
        """Review R11: the department, what the state is from and which template draws the card were titles on the Small
        card; a wall has no pointer, and the way to them is into the tank."""
        html = self.client.get(PANE, {'mode': 'small', 'focus': str(self.t2.pk)}).content.decode()
        card = card_of(html, self.t2)
        (code,) = [each for each in card.walk() if each.tag == 'h3']
        (link,) = [each for each in code.walk() if each.tag == 'a']
        self.assertEqual(link.attrs['href'], f"{reverse('farm:production_units')}?unit={self.t2.pk}")
        self.assertNotIn('data-dock', link.attrs)
        said = text(card)
        self.assertIn(self.t2.production_department.name, said)
        self.assertIn('State from: Fish, Feeding, Water, Health', said)
        self.assertIn('Template: Big · the view chosen on this screen', said)
        self.assertFalse(nodes(card, 'monitor-flip'))               # (the pane is one card: no flip inside it)

    def test_a_full_height_wall_has_no_pane_and_its_switch_drops_the_focus(self):
        html = self.client.get(PAGE, {'mode': 'big'}).content.decode()
        self.assertNotIn(f'open-{self.t2.pk}', by_id(html))
        self.assertFalse([each for each in card_of(html, self.t2).walk() if 'data-dock' in each.attrs])
        ids = by_id(self.page(focus=str(self.t2.pk)))
        self.assertEqual(ids['mode-big'].attrs['href'], f'{PAGE}?mode=big')
        self.assertEqual(ids['mode-simple'].attrs['href'], f'{PAGE}?focus={self.t2.pk}')

    def test_the_old_cards_have_no_opener_and_lose_nothing(self):
        html = self.client.get(PAGE).content.decode()
        self.assertFalse([name for name in by_id(html) if name.startswith('open-')])
        (link,) = [each for each in card_of(html, self.t2).walk() if each.tag == 'a' and each.parent.tag == 'h3']
        self.assertEqual(link.attrs['href'], f"{reverse('farm:production_units')}?unit={self.t2.pk}")


class BandTests(SmallCase):
    def test_everything_a_key_can_stand_on_in_the_band_has_an_id(self):
        """Review R8: the poll gives the focus back to the element of the same id (frontend/poll.ts merge)."""
        self.good_water(oxygen_mg_l='5')
        html = self.page()
        ids = by_id(html)
        for name, turn in (('pages-prev', '-1'), ('pages-next', '1')):
            self.assertEqual((ids[name].tag, ids[name].attrs['data-page-turn']), ('button', turn))
        worst = ids['pages-worst']
        self.assertEqual((worst.tag, worst.attrs['aria-label']), ('button', 'Page of the worst card (Home)'))
        self.assertIn('hidden', worst.attrs)
        self.assertIn('data-page-worst', worst.attrs)
        self.assertEqual([ids[f'mode-{key}'].attrs.get('aria-current') for key in ('small', 'big', 'simple', 'detailed')],
                         ['page', None, None, None])
        big = by_id(self.client.get(PAGE, {'mode': 'big'}).content.decode())
        self.assertEqual((big['charts-close'].attrs.get('aria-current'), big['charts-full'].attrs.get('aria-current')),
                         ('true', None))

    def test_a_chip_opens_the_unit_it_names(self):
        self.good_water(oxygen_mg_l='5')
        ids = by_id(self.page())
        chip = ids[f'chip-{self.t2.pk}']
        self.assertEqual((text(chip), chip.attrs['href'], chip.attrs['data-dock']),
                         ('T-02', f'{PAGE}?focus={self.t2.pk}&mode=small#card-{self.t2.pk}', str(self.t2.pk)))
        # on a wall of full-height cards a chip is the way to the card's page, and opens nothing
        chip = by_id(self.client.get(PAGE, {'mode': 'big'}).content.decode())[f'chip-{self.t2.pk}']
        self.assertEqual((chip.attrs['href'], 'data-dock' in chip.attrs), (f'#card-{self.t2.pk}', False))


class LossesTests(SmallCase):
    def test_the_saturation_stays_beside_the_oxygen_when_the_mg_l_is_old(self):
        """Review R11."""
        self.good_water(hours=30, oxygen_saturation_pct='77.2')
        card = card_of(self.page(), self.t2)
        label = next(each for each in card.walk() if each.tag == 'dt')
        self.assertEqual(text(label), 'O₂ · 77.2 % old')
        (old,) = [each for each in label.walk() if 'data-old' in each.attrs]
        self.assertIn('tw:shrink-0', old.classes)


class WindowWordsTests(SmallCase):
    def test_no_alkalinity_limit_row_is_said_in_the_window_in_words(self):
        """Review R6."""
        self.good_water()
        (window,) = nodes(card_of(self.page(), self.t2), 'monitor-ph-window')
        self.assertFalse(nodes(window, 'chart-name-band'))
        self.assertNotIn('alkalinity band', window.attrs['aria-label'])
        WaterLimit.objects.filter(parameter='alkalinity_mg_l').delete()
        (window,) = nodes(card_of(self.page(), self.t2), 'monitor-ph-window')
        self.assertFalse(nodes(window, 'chart-region-safe'))
        (said,) = nodes(window, 'chart-name-band')
        self.assertIn(text(said), ('no alkalinity band', 'no alk. band'))
        self.assertIn('is-middle', said.classes)
        self.assertTrue(window.attrs['aria-label'].endswith('; no alkalinity band for these fish'))


LETTER = 100 * render.NAME_SIZE * render.NAME_EM / 31             # the Small card: 31 units wide, twelve columns


def spans(names, letter=LETTER):
    """[(key, start, end)] of the placed words, as place_names reckons a word's width."""
    found = []
    for key, said, x, anchor in names:
        width, x = len(said) * letter, float(x)
        start = {'start': x, 'end': x - width, 'middle': x - width / 2}[anchor]
        found.append((key, start, start + width))
    return found


class PlacingTests(SimpleTestCase):
    """render.place_names: the pH window's words stand by rule and never touch."""

    def test_both_words_stand_in_their_own_regions_when_there_is_room(self):
        names = render.place_names(30.0, 70.0, 50.0, ('CO₂ 7.06', True), ('7.94 NH₃', True), (), LETTER)
        self.assertEqual([(key, said, x, anchor) for key, said, x, anchor in names],
                         [('co2', 'CO₂ 7.06', '28.8', 'end'), ('nh3', '7.94 NH₃', '71.2', 'start')])

    def test_close_borders_never_put_one_word_over_the_other(self):
        """The 1C report's weak point (HA-R02, TG-M01): the two borders a few per cent apart."""
        for left, right, water in ((44.0, 49.0, 30.0), (44.0, 49.0, 46.5), (44.0, 49.0, 80.0), (3.0, 8.0, 50.0),
                                   (92.0, 97.0, 50.0), (48.0, 48.5, 48.2)):
            with self.subTest(left=left, right=right, water=water):
                names = render.place_names(left, right, water, ('CO₂ 7.37', True), ('7.48 NH₃', True), (), LETTER)
                self.assertEqual({key for key, *_rest in names}, {'co2', 'nh3'})
                self.assert_apart(names, water)

    def test_nothing_ever_touches_whatever_the_water_and_the_borders(self):
        steps = [index * 5.0 for index in range(21)]
        words = {'co2': (('CO₂ 7.37', True), ('CO₂', False), ('no CO₂ limit', False), None),
                 'nh3': (('7.48 NH₃', True), ('NH₃', False), ('no NH₃ limit', False), ('no TAN', False), None)}
        band = ('no alkalinity band', 'no alk. band')
        checked = 0
        for left, right in itertools.product(steps, steps):
            if right < left:
                continue
            for water in (*steps[::2], None):
                for co2, nh3 in itertools.product(words['co2'], words['nh3']):
                    if (co2 and co2[1] and left <= 0) or (nh3 and nh3[1] and right >= 100):
                        continue                                     # a border off the scale has no word at it
                    off = '' if water is not None else '◀ 6.10'
                    for letter in (LETTER, 2 * LETTER):               # the widget on twelve columns, and on six
                        names = render.place_names(left, right, water, co2, nh3, band, letter, off)
                        self.assert_apart(names, water, letter, off)
                        checked += 1
        self.assertGreater(checked, 50000)

    def test_a_word_at_a_border_stays_on_its_own_side_of_the_other_region(self):
        # the water in the CO₂ region against the border: the CO₂ word goes beyond the mark, still in its region
        names = render.place_names(40.0, 80.0, 38.0, ('CO₂ 7.28', True), ('8.16 NH₃', True), (), LETTER)
        ((_key, start, end),) = [each for each in spans(names) if each[0] == 'co2']
        self.assertLess(end, 38.0 - render.MARK_HALF)
        for water in (10.0, 50.0, 90.0):
            names = render.place_names(40.0, 60.0, water, ('CO₂ 7.28', True), ('7.72 NH₃', True), (), LETTER)
            for key, start, end in spans(names):
                self.assertTrue(end <= 60.0 if key == 'co2' else start >= 40.0, (water, key, start, end))

    def test_the_band_words_take_the_widest_free_run_between_the_borders_or_their_short_form_or_none(self):
        band = ('no alkalinity band', 'no alk. band')
        names = render.place_names(20.0, 80.0, 30.0, ('CO₂ 6.84', True), ('8.16 NH₃', True), band, LETTER)
        self.assertEqual([(said, x, anchor) for key, said, x, anchor in names if key == 'band'],
                         [('no alkalinity band', f'{(30 + render.MARK_HALF + 80) / 2:.1f}', 'middle')])
        names = render.place_names(40.0, 62.0, 10.0, ('CO₂ 7.28', True), ('7.76 NH₃', True), band, LETTER)
        self.assertEqual([said for key, said, *_rest in names if key == 'band'], ['no alk. band'])
        names = render.place_names(45.0, 55.0, 50.0, ('CO₂ 7.39', True), ('7.61 NH₃', True), band, LETTER)
        self.assertEqual([said for key, said, *_rest in names if key == 'band'], [])

    def assert_apart(self, names, water, letter=LETTER, off=''):
        boxes = spans(names, letter)
        if water is not None:
            boxes.append(('water', water - render.MARK_HALF, water + render.MARK_HALF))
        elif off:
            boxes.append(('off', 0.0, render.NAME_EDGE + len(off) * letter))
        for key, start, end in boxes:
            if key not in ('water', 'off'):
                self.assertGreaterEqual(start, render.NAME_EDGE - 0.06, (key, names))
                self.assertLessEqual(end, 100 - render.NAME_EDGE + 0.06, (key, names))
        for (a, a0, a1), (b, b0, b1) in itertools.combinations(boxes, 2):
            self.assertTrue(a1 + render.NAME_GAP <= b0 + 0.11 or b1 + render.NAME_GAP <= a0 + 0.11, (a, b, names, water))

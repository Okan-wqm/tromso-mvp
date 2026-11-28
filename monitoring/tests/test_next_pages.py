"""Operations › Monitoring in the new look (`?ui=next`), on THE test world (core/test_world.py: `world` and
`monitoring_world`, a unit in every state a card can be in) with the clock at its MOMENT, through the real views:

- the cards SAY in the new look what they say in the classic look, card for card and state for state (the golden
  extractor, monitoring/tests/golden.py: the state word, the reasons, every labelled figure and every link the same;
  every text and title of the classic card still there), on the Small, Simple, Detailed, Operator view and Big cards
  and in the pane;
- every card links its tank's water history (Tank › Water) in both looks, and the link resolves (the classic look's to
  the unit's history on Water chemistry); the cards that flow (Simple, Detailed, Operator view) are the design's card
  in the new look (monitoring/_card_next.html), the fitted ones the same markup in both looks (but an empty unit's Big
  card, which says the unit in the new look, as the design's), and a screen's change token is its look's own;
- the classic page loads none of the new look's sheets, the new one both;
- the pages are kept for the browser test (frontend/test/monitoring.pages.ts, `npm run test:pages`) under
  .build/monitor-pages/ (never committed: the repository is public, and nothing here comes from a real database):
  the shell of each screen as the server prints it, the fragments its polls are answered with, the pane, the strip, and
  the cards again after a unit got worse (for the announcer), in English, Norwegian and Turkish."""
import json
import re
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from core import ui
from core.language import save_account_language
from core.test_world import (MIXED_BIG, MIXED_FLOW, MIXED_OWN, MOMENT, MONITORING_UNITS, TEST_MIXED_BOARD, TEST_OPERATOR_BOARD,
                              TEST_WALL, monitoring_world, world)
from core.testing import FrozenClock
from farm.models import Tank
from farm.tests.helpers import point_of
from farm.water import services as water

from .golden import Normaliser, Tree, cards_say, multiset_missing

OUT = Path(settings.BASE_DIR) / '.build' / 'monitor-pages'
PAGE, CARDS, PANE = reverse('monitoring:monitor'), reverse('monitoring:cards'), reverse('monitoring:pane')
# The screens the browser test lays out: {name: the page's query}
SCREENS = {'small': {'mode': 'small', 'occupancy': 'all'}, 'simple': {'occupancy': 'all'},
           'detailed': {'mode': 'detailed', 'occupancy': 'all'}, 'big': {'mode': 'big', 'occupancy': 'all'},
           'wall': {'mode': 'small', 'occupancy': 'all', 'wall': '1'},
           'wall-big': {'mode': 'big', 'occupancy': 'all', 'wall': '1'}}
STATES = {'Critical', 'Warning', 'No recent data', 'No limit', 'Note', 'OK', 'Empty'}
# The screens whose cards flow (their templates have no measure): the design's card in the new look.
FLOWING = ('simple', 'detailed', 'operator')
# The screens of Big cards: an empty unit's Big card says more in the new look (the design's), every other card is the
# same markup in both looks.
BIG_SCREENS = ('big', 'wall-big')
# The units whose Big card the browser test opens in the pane too (beside TW-02): an old critical, many values, an
# old sample in the CO2 region of its chart, many criticals, more of them than a card holds, and five of two lines.
PANES = ('TW-08', 'TW-09', 'TW-12', 'TW-10', 'TW-11', 'TW-01', 'TW-14', 'TW-15', 'TW-16')
# What the design's Big card of an empty unit says that the classic one does not: the unit, the chart's place and why it
# is empty, what to dose, the other points, the stock (in English).
EMPTY_BIG = ('Status', 'Volume', 'Max density', 'Max biomass', 'No chart: there is no fish in this unit.', 'Dosing advice',
             'No fish: nothing to dose.', 'Other sampling points', 'Stock', 'No fish')


def _articles(html):
    """{the card's key (data-key): its markup} of the cards of a fragment, in its order."""
    return {re.search(r'data-key="([^"]+)"', article).group(1): article
            for article in re.findall(r'<article .*?</article>', html, re.S)}


def _visible(node):
    """The texts a node shows (not its screen reader's own words, .sr-only)."""
    for child in node.children:
        if isinstance(child, str):
            yield child
        elif 'sr-only' not in child.classes:
            yield from _visible(child)


def _stocked(html):
    """The markup without the cards of the units with no fish (each article whose state is empty)."""
    return re.sub(r'<article [^>]*data-state="empty".*?</article>\n?', '', html, flags=re.S)


# What the new look adds to a Big card's chart: its frame is a stop of the keyboard with an id of its own (on a phone the
# picture scrolls sideways in it: templates/monitoring/widgets/_chart.html); the classic card's never scrolls.
CHART_STOP = re.compile(r'(<figure class="monitor-chart [^"]*") id="[^"]*chart-[^"]*" tabindex="0"')
# ... and to its other points (each point's age beside its name, a point with no value said once:
# templates/monitoring/widgets/_points.html), and to its reasons where it is drawn at the size of its place (the first
# FIT_REASONS in sight, "+N" for the rest: _card_fit.html).
POINTS_BOX = re.compile(r'<section class="tw:grid tw:grid-cols-\[minmax\(0,1fr\)_auto_auto_auto\].*?</section>', re.S)
REASONS_MORE = re.compile(r'<p class="monitor-reasons-more .*?</p>', re.S)
# ... and a full-height card's region of reasons, its lines (rl-N), and the chart's least height (cm-N): the new look's
# sheet draws them (static/css/monitor-next.css).
REGION = re.compile(r' (?:rl|cm)-\d+(?=[" ])')


def _fitted(html):
    """The markup of fitted cards without what each look says its own way: CHART_STOP, the other points' box,
    REASONS_MORE and the reasons a Big card folds, REGION (the classic markup passes through unchanged but for the
    points' box)."""
    html = REASONS_MORE.sub('', REGION.sub('', CHART_STOP.sub(r'\1', html))).replace(' data-more>', '>')
    return POINTS_BOX.sub('<section points>', html)


def _more_alerts(count, language, band=False):
    """What a card says of the `count` alerts it folds, in `language` ("7 more alerts" on a Small card; "3 more alerts,
    see the band" on a Big one)."""
    from django.utils import translation
    with translation.override(language):
        if band:
            return translation.ngettext('%(count)s more alert, see the band', '%(count)s more alerts, see the band',
                                        count) % {'count': count}
        return translation.ngettext('%(count)s more alert', '%(count)s more alerts', count) % {'count': count}




class NextPagesTests(FrozenClock, TestCase):
    NOW = MOMENT

    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser('test.admin', 'test.admin@example.com', 'x')
        made = world(cls.admin, Client())
        # (what was posted answers with its status, 302 when saved; the people's parts say what they made)
        refused = [each for each in made if each.rpartition(': ')[2].isdigit() and not each.endswith(': 302')]
        if refused:
            raise AssertionError(f'the test world was not built: {refused}')
        monitoring_world(cls.admin)
        cls.units = {unit.code: unit for unit in Tank.objects.all()}
        # (and the board of Operator view cards: its address names the board's id)
        from monitoring.models import MonitorBoard
        operator = MonitorBoard.objects.get(name=TEST_OPERATOR_BOARD)
        mixed = MonitorBoard.objects.get(name=TEST_MIXED_BOARD)
        cls.screens = {**SCREENS, 'operator': {'board': str(operator.pk), 'occupancy': 'all'},
                       'mixed': {'board': str(mixed.pk), 'occupancy': 'all'}}

    def setUp(self):
        self.client.force_login(self.admin)
        self.norm = Normaliser(self.units.values(), [], MOMENT.date())

    def ask(self, url, query=None, look=ui.NEXT, language='en'):
        """The answer of `url` in a look and a language (the account's language wins over the cookie: both are set)."""
        save_account_language(self.admin, language)
        self.client.cookies[settings.LANGUAGE_COOKIE_NAME] = language
        if look == ui.NEXT:
            self.client.cookies[ui.COOKIE] = ui.NEXT
        elif ui.COOKIE in self.client.cookies:
            del self.client.cookies[ui.COOKIE]
        response = self.client.get(url, query or {})
        self.assertIn(response.status_code, (200, 204), f'{url} {query} {look} {language}')
        return response

    def fragment(self, query, look=ui.NEXT, language='en'):
        return self.ask(CARDS, query, look, language).content.decode()

    def test_the_world_has_a_card_in_every_state(self):
        said = cards_say(self.fragment(SCREENS['small']), self.norm)
        self.assertEqual({card['state'] for card in said.values()}, STATES)
        expected = {'TW-01': 'OK', 'TW-02': 'Critical', 'TW-03': 'Warning', 'TW-04': 'No recent data',
                    'TW-05': 'No limit', 'TW-06': 'Note', 'TW-07': 'Empty', 'TW-08': 'Critical',
                    'TW-09': 'No limit', 'TW-10': 'No limit', 'TW-11': 'No limit', 'TW-12': 'Critical',
                    'TW-13': 'Critical', 'TW-14': 'Critical', 'TW-15': 'Critical', 'TW-16': 'Critical'}
        self.assertEqual({code: said[code]['state'] for code in expected}, expected)
        self.assertEqual(len(MONITORING_UNITS), len(expected))

    def test_every_card_says_in_the_new_look_what_it_says_in_the_classic_one(self):
        for name, query in self.screens.items():
            for language in ('en', 'nb', 'tr'):
                classic = cards_say(self.fragment(query, look='', language=language), self.norm)
                new = cards_say(self.fragment(query, language=language), self.norm)
                self.assertEqual(list(new), list(classic), f'{name} {language}: the cards and their order')
                for code, was in classic.items():
                    now = new[code]
                    with self.subTest(screen=name, language=language, card=code):
                        for part in ('state', 'reasons', 'pairs', 'links'):
                            self.assertEqual(now[part], was[part], f'{name} {language} {code}: {part}')
                        self.assertEqual(multiset_missing(was['texts'], now['texts']), [], 'texts that are gone')
                        self.assertEqual(multiset_missing(was['titles'], now['titles']), [], 'titles that are gone')

    def test_the_pane_says_in_the_new_look_what_it_says_in_the_classic_one(self):
        for code in ('TW-02', 'TW-04', 'TW-07'):
            query = {**SCREENS['small'], 'focus': str(self.units[code].pk)}
            classic = cards_say(self.ask(PANE, query, look='').content.decode(), self.norm)
            new = cards_say(self.ask(PANE, query).content.decode(), self.norm)
            self.assertEqual(list(new), [code])
            for part in ('state', 'reasons', 'pairs', 'links'):
                self.assertEqual(new[code][part], classic[code][part], f'{code}: {part}')
            self.assertEqual(multiset_missing(classic[code]['texts'], new[code]['texts']), [])

    def links_of(self, html):
        """{unit code: the hrefs of its card's links to Tank › Water}."""
        found = {}
        for node in Tree(html).root.walk():
            if node.tag == 'article' and node.attrs.get('data-key', '').startswith('card:'):
                code = self.norm(node.attrs['data-key'][len('card:'):])
                found[code] = [each.attrs['href'] for each in node.walk()
                               if each.tag == 'a' and '/water/' in each.attrs.get('href', '')]
        return found

    def test_every_card_links_its_tanks_water_in_both_looks_and_the_link_resolves(self):
        for name, query in SCREENS.items():
            for look in ('', ui.NEXT):
                found = self.links_of(self.fragment(query, look=look))
                self.assertTrue(found, name)
                for code, hrefs in found.items():
                    self.assertEqual(hrefs, [reverse('farm:tank_water', args=[self.units[code].pk])],
                                     f'{name} {look or "classic"} {code}')
        pane = self.ask(PANE, {**SCREENS['small'], 'focus': str(self.units['TW-02'].pk)}).content.decode()
        self.assertIn(f'href="{reverse("farm:tank_water", args=[self.units["TW-02"].pk])}"', pane)
        self.assertIn('id="pane-water-', pane)                  # a second card of its unit on the page: its own id
        # where it leads: Tank › Water in the new look; in the classic look the unit's history on Water chemistry
        from farm.water.views import history_url
        for code in ('TW-01', 'TW-04', 'TW-07'):
            unit = self.units[code]
            address = reverse('farm:tank_water', args=[unit.pk])
            self.assertEqual(self.ask(address).status_code, 200, code)
            self.client.cookies.pop(ui.COOKIE, None)
            response = self.client.get(address)
            self.assertRedirects(response, history_url(unit), fetch_redirect_response=False)
            self.assertEqual(self.client.get(response['Location']).status_code, 200, code)

    def test_the_water_link_is_only_for_a_person_who_may_read_the_water(self):
        """Tank › Water needs the right to read water samples, which the cards do not: a person who may see the cards but
        not the water has no link to it (a link that would answer 403), in both looks; with the right, every card has one."""
        from django.contrib.auth.models import Group, Permission
        address = reverse('farm:tank_water', args=[self.units['TW-02'].pk])
        for codenames, shown in ((('view_stockoperation',), False), (('view_stockoperation', 'view_watermeasurement'), True)):
            person = get_user_model().objects.create_user(f'test.cards{len(codenames)}', f'test.cards{len(codenames)}@example.com')
            group = Group.objects.create(name=f'Test cards {len(codenames)}')
            group.permissions.set(Permission.objects.filter(codename__in=codenames))
            person.groups.add(group)
            self.client.force_login(person)
            for look in ('', ui.NEXT):
                for name in ('small', 'simple', 'big'):
                    with self.subTest(rights=codenames, look=look, screen=name):
                        self.assertEqual(address in self.fragment(SCREENS[name], look=look), shown)
            focus = {**SCREENS['small'], 'focus': str(self.units['TW-02'].pk)}
            self.assertEqual(address in self.ask(PANE, focus).content.decode(), shown)
            self.assertEqual(self.client.get(address).status_code in (200, 302), shown)

    def test_the_flowing_cards_are_the_designs_in_the_new_look_and_the_fitted_ones_the_same_markup(self):
        """A card that flows (Simple, Detailed, Operator view) is the design's card in the new look, every card of the
        screen, and never in the classic look (monitoring/_card_next.html: what it says is the classic card's, the test
        above; the classic card is the golden one, test_golden); a fitted card (Small, Big, the pane's, a wall's) is the
        same markup in both looks, byte for byte, the new look's sheet drawing it as the design does
        (static/css/monitor-next.css), but for what the design's Big card of an empty unit says that the classic one
        does not (the test below) and the chart's frame, a stop of the keyboard in the new look (CHART_STOP)."""
        for name, query in self.screens.items():
            new, classic = self.fragment(query), self.fragment(query, look='')
            cards = classic.count('<article class="monitor-card ')
            self.assertTrue(cards, name)
            self.assertNotIn(' is-next"', classic, name)
            if name in FLOWING:
                self.assertEqual(new.count(' is-next"'), cards, name)
            elif name == 'mixed':
                fitted = {key: article for key, article in _articles(classic).items() if ' is-fit ' in article}
                self.assertEqual({key: _fitted(article) for key, article in _articles(new).items() if key in fitted},
                                 {key: _fitted(article) for key, article in fitted.items()})
            elif name in BIG_SCREENS:
                self.assertEqual(_fitted(_stocked(new)), _fitted(_stocked(classic)), name)
                self.assertEqual(len(CHART_STOP.findall(new)), len(re.findall(r'<svg class="monitor-chart-svg', new)), name)
                self.assertGreaterEqual(cards - _stocked(classic).count('<article class="monitor-card '), 2, name)
            else:
                self.assertEqual(_fitted(new), _fitted(classic), name)
        focus = {**SCREENS['small'], 'focus': str(self.units['TW-02'].pk)}
        self.assertEqual(_fitted(self.ask(PANE, focus).content.decode()), _fitted(self.ask(PANE, focus, look='').content.decode()))

    def test_an_empty_units_big_card_says_the_unit_in_the_new_look(self):
        """The design's Big card of a unit with no fish says the unit itself, as the overview's Small card of an empty
        unit does (monitoring/_empty_cells.html: its status, volume, maximum density and maximum biomass), then the
        boxes the design draws on it with the template's own widgets (monitoring/cards/render.py shown): the chart's
        place saying there is no fish (no chart is drawn), what to dose, the other sampling points (their water as
        read) and the stock (no fish); on the Big screen, its wall and in the pane, in the three languages. The classic
        Big card is as it was (none of it), and a stocked unit's Big card has no cells in either look."""
        for name in BIG_SCREENS:
            for language in ('en', 'nb', 'tr'):
                for look in (ui.NEXT, ''):
                    articles = _articles(self.fragment(SCREENS[name], look=look, language=language))
                    empty = [key for key, article in articles.items() if 'data-state="empty"' in article]
                    self.assertGreaterEqual(len(empty), 2, f'{name} {language} {look}')
                    for key, article in articles.items():
                        with self.subTest(screen=name, language=language, look=look or 'classic', card=key):
                            self.assertEqual('class="monitor-cells' in article, look == ui.NEXT and key in empty)
                            for box in ('chart', 'dosing', 'points', 'stock'):
                                self.assertEqual(f'class="w w-{box} ' in article, key not in empty or look == ui.NEXT,
                                                 box)
        for look, says in ((ui.NEXT, True), ('', False)):
            said = cards_say(self.fragment(SCREENS['big'], look=look), self.norm)
            for code in ('TW-07', 'TX-01'):
                found = ' '.join([*said[code]['texts'], *(' '.join(pair) for pair in said[code]['pairs'])])
                for words in EMPTY_BIG:
                    self.assertEqual(words in found, says, f'{look or "classic"} {code}: {words}')
        focus = {**SCREENS['small'], 'focus': str(self.units['TW-07'].pk)}
        pane = self.ask(PANE, focus).content.decode()
        self.assertNotIn('class="monitor-cells', self.ask(PANE, focus, look='').content.decode())
        said = cards_say(pane, self.norm)['TW-07']
        self.assertEqual(said['state'], 'Empty')
        for words in EMPTY_BIG:
            self.assertIn(words, ' '.join(said['texts']))
        # (review 2, N6) nothing about fish it has not, and the chart's place says why once
        self.assertNotIn('for these fish', ' '.join(said['texts']))
        self.assertEqual(said['texts'].count('No chart: there is no fish in this unit.'), 1, said['texts'])

    def test_the_big_cards_water_says_whether_its_tiles_hold_it(self):
        """Whether a Big card's water is drawn as the design's tiles is the server's one answer (monitoring/cards/render.py
        tiled: one column of at most eight values, in a place of the template that holds two lines of four tiles), said
        on the rows' frame as `data-tiles="4"` (the tiles to a line) in both looks, which the new look's sheet draws
        from (never a count of a table's children). Five and eight values on the built-in Big card: tiles; ten (TW-09),
        fifteen and seventeen (TW-10, TW-11): none, ONE column of rows (two columns of rows do not fit side by side in
        the Big card's water place: render.water_rows; review 2, N1, they lay over each other); five values on a farm's
        full-height template whose water's place is low (the mixed board's TW-06): none. On the Big screen, its wall,
        the mixed board and in the pane."""
        from monitoring.cards import catalogue
        from monitoring.cards.render import WATER_TILES
        self.assertEqual(WATER_TILES, catalogue.WIDGETS['water_table'].tiles[0] * catalogue.WIDGETS['water_table'].tiles[1])
        built_in = {'TT-01': True, 'TW-01': True, 'TW-04': True, 'TW-09': False, 'TW-10': False, 'TW-11': False}
        for name, expected in (('big', built_in), ('wall-big', built_in),
                               ('mixed', {**{code: True for code in MIXED_BIG}, MIXED_OWN: False})):
            for look in (ui.NEXT, ''):
                articles = {self.norm(key[len('card:'):]): article
                            for key, article in _articles(self.fragment(self.screens[name], look=look)).items()}
                for code, tiles in expected.items():
                    frames = re.findall(r'<div class="monitor-rows[^"]*"([^>]*)>', articles[code])
                    with self.subTest(screen=name, look=look or 'classic', card=code):
                        self.assertTrue(frames)
                        self.assertEqual([' data-tiles="4"' in frame for frame in frames], [tiles] * len(frames))
                        values = len(re.findall(r'role="rowheader"', articles[code]))
                        if code in ('TW-10', 'TW-11'):
                            self.assertEqual((values, articles[code].count('role="table"')),
                                             (15 if code == 'TW-10' else 17, 1))
        for code, tiles in (('TW-02', True), ('TW-09', False)):
            pane = self.ask(PANE, {**SCREENS['small'], 'focus': str(self.units[code].pk)}).content.decode()
            self.assertEqual(' data-tiles="4"' in pane, tiles, code)

    def test_a_fitted_cards_markup_is_the_same_on_a_board_that_mixes_them(self):
        """The mixed board (core/test_world.py mixed_board): Small cards, two Big ones, one drawn with a farm's own
        full-height template and Simple cards that flow, in the farm's one order; every fitted card the same markup in
        both looks (none of them empty), but the Big cards' chart frames, a stop of the keyboard in the new look
        (CHART_STOP); the cards that flow are the design's card in the new look."""
        new, classic = self.fragment(self.screens['mixed']), self.fragment(self.screens['mixed'], look='')
        articles = {self.norm(key[len('card:'):]): article for key, article in _articles(new).items()}
        before = {self.norm(key[len('card:'):]): article for key, article in _articles(classic).items()}
        self.assertEqual(list(articles), list(before))
        for code, article in articles.items():
            with self.subTest(card=code):
                self.assertEqual(' data-fill' in article, code in (*MIXED_BIG, MIXED_OWN))
                self.assertEqual(' is-fit ' in article, code not in MIXED_FLOW)
                self.assertEqual(' is-next"' in article, code in MIXED_FLOW)
                if code not in MIXED_FLOW:
                    self.assertEqual(_fitted(article), _fitted(before[code]))

    def big_card(self, surface, code, language):
        """The markup of `code`'s Big card on a surface: the pane, a wall of Big cards, the desk's Big screen."""
        if surface == 'pane':
            return self.ask(PANE, {**SCREENS['small'], 'focus': str(self.units[code].pk)}, language=language).content.decode()
        articles = _articles(self.fragment(SCREENS['wall-big' if surface == 'wall' else 'big'], language=language))
        return next(article for key, article in articles.items() if self.norm(key[len('card:'):]) == code)

    def test_a_big_card_folds_only_its_notes_never_an_alert(self):
        """Where a Big card is drawn at the size of its place (the pane, a wall), its reasons hold LINES (render.fold):
        an alert (a critical, warning or no-recent-data card's reason) is never folded while the card holds it, and past
        that the card says in words how many more there are and where they are ("2 more alerts, see the band"); notes
        fold into "+N". What the card holds is fewer where its water's rows take room from the chart
        (render.water_lines). Its reasons are a region of their own as many lines as the fold shows (rl-N, the new
        look's). TW-14: five criticals, all; TW-15: ten, its fourteen water rows leave three ("7 more alerts"); TW-16:
        five of two lines each (its side outlet's long name), three ("2 more alerts"); TW-11: notes, its seventeen
        water rows leave one ("+8"). In the pane, on a wall and on the desk (whose card flows and shows every one: the
        words are there for the sheet to show where the card is fitted), in the three languages."""
        expected = {'TW-11': (1, 1, None), 'TW-14': (5, 5, None), 'TW-15': (3, 3, 'alerts'), 'TW-16': (3, 6, 'alerts')}
        for surface in ('pane', 'wall', 'desk'):
            for language in ('en', 'nb', 'tr'):
                for code, (shown, lines, said) in expected.items():
                    card = self.big_card(surface, code, language)
                    region = re.search(r'<ul class="monitor-reasons ([^"]*)"[^>]*>(.*?)</ul>', card, re.S)
                    items = region.group(2).count('<li ')
                    more = re.search(r'<p class="monitor-reasons-more([^"]*)"[^>]*><span aria-hidden="true">([^<]*)</span>',
                                     card)
                    with self.subTest(surface=surface, language=language, card=code):
                        self.assertIn(f'rl-{lines}', region.group(1).split())
                        self.assertEqual(items - region.group(2).count(' data-more'), shown)
                        if items == shown:
                            self.assertIsNone(more)
                        elif said:
                            self.assertIn(' is-alert', more.group(1))
                            self.assertEqual(more.group(2), _more_alerts(items - shown, language, band=True))
                        else:
                            self.assertNotIn('is-alert', more.group(1))
                            self.assertEqual(more.group(2), f'+{items - shown}')
        # the classic Big card says every reason, as it did, with no region of lines
        classic = _articles(self.fragment(SCREENS['wall-big'], look=''))
        self.assertFalse(re.search(r' rl-\d+', ''.join(classic.values())))

    def test_the_chart_of_a_full_height_card_is_the_one_that_gives_way(self):
        """In the new look the chart of a full-height card says the least height it gives way to (cm-22: the catalogue's
        give_units), its other widgets none: the reasons take their room from the chart first (the browser test holds
        a value's tile and a reason uncut, and the chart a quarter of a line above that height); the classic card has
        none of it."""
        for look, says in ((ui.NEXT, True), ('', False)):
            articles = {self.norm(key[len('card:'):]): article
                        for key, article in _articles(self.fragment(SCREENS['wall-big'], look=look)).items()}
            for code in ('TW-02', 'TW-15', 'TW-16'):
                with self.subTest(look=look or 'classic', card=code):
                    self.assertEqual(re.findall(r'class="w w-(\w+) [^"]*\bcm-(\d+)\b', articles[code]),
                                     [('chart', '22')] if says else [])

    def test_a_small_card_says_its_worst_alert_and_how_many_more(self):
        """A Small card stays one line (render.fold, 'small'): its worst reason by name and, when there are more alerts,
        how many in words in the card's tone ("4 more alerts"), never a bare "+N", IN BOTH LOOKS (the coordinator's rules
        of 2026-11-28: a Small card never hides that alerts exist; the classic look is the default, and a wall nobody
        can hover is one); its notes still fold into "+N" (TW-11), one reason is said alone (TW-02). On a wall of Small
        cards and the desk's, in the three languages."""
        for name in ('wall', 'small'):
            for language in ('en', 'nb', 'tr'):
                for look in (ui.NEXT, ''):
                    fragment = self.fragment(SCREENS[name], look=look, language=language)
                    articles = {self.norm(key[len('card:'):]): article for key, article in _articles(fragment).items()}
                    for code, count in (('TW-14', 4), ('TW-15', 9), ('TW-16', 4), ('TW-11', None), ('TW-02', 0)):
                        reasons = re.search(r'<ul class="monitor-reasons [^"]*"[^>]*>(.*?)</ul>', articles[code], re.S).group(1)
                        items = re.findall(r'<li class="([^"]*)"[^>]*>(?:<span aria-hidden="true">([^<]*)</span>)?', reasons)
                        with self.subTest(screen=name, language=language, look=look or 'classic', card=code):
                            if count == 0:                               # one reason: nothing folded
                                self.assertEqual(len(items), 1)
                                continue
                            self.assertEqual(len(items), 2)
                            (first, _), (last, said) = items
                            if count is None:                            # notes: "+N"
                                self.assertNotIn('is-alert', last)
                                self.assertRegex(said, r'^\+\d+$')
                                continue
                            self.assertIn('tw:text-crit-text', first)    # the worst first, a critical
                            self.assertTrue(last.startswith('monitor-reasons-more is-alert '), last)
                            self.assertIn('tw:text-crit-text', last.split())
                            self.assertEqual(said, _more_alerts(count, language))

    def test_a_reasons_short_form_is_never_said_twice_on_a_card(self):
        """A reason's short form (the value against the bound it is past) is said once on a card: a % of saturation judged
        through its mg/L row is the same crossing, so that reason is said whole (monitoring/read.py _alerts; review 2,
        N10: TT-01 said "O2 (mg/L) 5.00 · critical limit 6.00" twice). Every card of the Small, Big and wall screens."""
        from monitoring.tests.golden import Tree
        for name in ('small', 'big', 'wall-big'):
            for node in Tree(self.fragment(SCREENS[name])).root.walk():
                if node.tag != 'ul' or 'monitor-reasons' not in node.classes:
                    continue
                shown = [' '.join(' '.join(text for text in _visible(item)).split()) for item in node.children
                         if not isinstance(item, str) and item.tag == 'li']
                with self.subTest(screen=name, reasons=shown):
                    self.assertEqual(len(shown), len(set(shown)))

    def test_the_other_points_say_each_values_age_in_the_new_look(self):
        """The box of a Big card's other sampling points says each point's age beside its name in the new look (the
        oldest of its values: render.other_points), an old one with the clock (and "old" for a screen reader), the
        point's name whole in its title; the classic box keeps the age in each value's title (OTHER_POINTS: TW-01's
        inlet fresh, TW-08's bottom drain 30 hours old)."""
        for look in (ui.NEXT, ''):
            articles = {self.norm(key[len('card:'):]): article
                        for key, article in _articles(self.fragment(SCREENS['big'], look=look)).items()}
            for code, old in (('TW-01', False), ('TW-08', True)):
                box = re.search(r'<div class="w w-points [^"]*">(.*?)</section>', articles[code], re.S).group(1)
                with self.subTest(look=look or 'classic', card=code):
                    # one age, the point's (its values' oldest), for the one point with values
                    self.assertEqual(box.count('class="monitor-point-age'), 1 if look else 0)
                    self.assertEqual('monitor-shape-blind' in box, bool(look) and old)
                    self.assertEqual(box.count('class="monitor-point-name" title="'), 3 if look else 0)

    def test_a_screens_change_token_is_its_looks_own(self):
        """The cards of a screen are other markup in each look, so the token a poll of one look carries never answers
        "nothing changed" (204) to the other: a person who switches the look gets the cards drawn in it at once."""
        from urllib.parse import parse_qs, urlsplit
        for name in ('simple', 'small'):
            query = self.screens[name]
            for look, other in ((ui.NEXT, ''), ('', ui.NEXT)):
                after = parse_qs(urlsplit(self.ask(CARDS, query, look=look)['X-Poll-Next']).query)['after'][0]
                with self.subTest(screen=name, look=look):
                    self.assertEqual(self.ask(CARDS, {**query, 'after': after}, look=look).status_code, 204)
                    self.assertEqual(self.ask(CARDS, {**query, 'after': after}, look=other).status_code, 200)

    def test_every_widget_has_a_new_look(self):
        """Every widget a card that flows can hold (one that may be placed: the trend is catalogued, not yet drawn) is
        drawn in the new look: by its own markup where the design draws it otherwise (render.NEXT_LOOK), else its
        classic one; the Deffeyes chart's button in the card's foot."""
        from django.template.loader import get_template
        from monitoring.cards import catalogue
        from monitoring.cards.render import FOOT, NEXT_LOOK, WidgetView
        for spec in (spec for spec in catalogue.WIDGETS.values() if spec.enabled):
            view = WidgetView('w1', spec.type, 0, 0, 1, 1, spec.renderer, {}, {}, '', False, 'w-1-w1')
            get_template(view.next_renderer)
            self.assertEqual(view.next_renderer != spec.renderer, spec.type in NEXT_LOOK, spec.type)
            self.assertEqual(view.in_foot, spec.type in FOOT, spec.type)
        self.assertEqual(FOOT, {'deffeyes'})

    def test_the_classic_page_loads_none_of_the_new_looks_sheets(self):
        for look, expected in (('', False), (ui.NEXT, True)):
            html = self.ask(PAGE, SCREENS['small'], look=look).content.decode()
            for sheet in ('css/glyphs.css', 'css/monitor-next.css'):
                self.assertEqual(sheet in html, expected, f'{look or "classic"} {sheet}')

    def keep(self, name, response):
        """Writes an answer for the browser test: its body, and its next address."""
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / f'{name}.html').write_text(response.content.decode(), encoding='utf-8', newline='\n')
        return {'status': response.status_code, 'next': response.get('X-Poll-Next', '')}

    def test_the_pages_are_kept_for_the_browser_test(self):
        index = {}
        for language in ('en', 'nb', 'tr'):
            for name, query in self.screens.items():
                page = self.ask(PAGE, query, language=language)
                html = page.content.decode()
                self.assertIn('data-poll-state="loading"', html)                  # the shell: no card yet
                self.assertNotIn('data-key="card:', html)
                key = f'{name}-{language}'
                index[key] = {'page': self.keep(f'page-{key}', page), 'lang': language,
                              'cards': self.keep(f'cards-{key}', self.ask(CARDS, query, language=language)),
                              'nonce': re.search(r'nonce="([^"]+)"', html).group(1)}
            for code in ('TW-02', *PANES):
                # (the pane of TW-02 is "pane-<language>", the others "pane-tw08-<language>" …)
                name = 'pane' if code == 'TW-02' else f'pane-{code.replace("-", "").lower()}'
                focus = {**SCREENS['small'], 'focus': str(self.units[code].pk)}
                page = self.ask(PAGE, focus, language=language)
                index[f'{name}-{language}'] = {
                    'page': self.keep(f'page-{name}-{language}', page), 'lang': language,
                    'cards': self.keep(f'cards-{name}-{language}', self.ask(CARDS, focus, language=language)),
                    'pane': self.keep(f'pane-{name}-{language}', self.ask(PANE, focus, language=language)),
                    'nonce': re.search(r'nonce="([^"]+)"', page.content.decode()).group(1)}
            index[f'strip-{language}'] = self.keep(f'strip-{language}',
                                                   self.ask(reverse('core:ui_strip'), language=language))
            # the wall of Small cards in the classic look (the default): no card on it hides that alerts exist either
            classic = self.ask(PAGE, SCREENS['wall'], look='', language=language)
            index[f'wall-classic-{language}'] = {
                'page': self.keep(f'page-wall-classic-{language}', classic), 'lang': language,
                'cards': self.keep(f'cards-wall-classic-{language}', self.ask(CARDS, SCREENS['wall'], look='', language=language)),
                'nonce': re.search(r'nonce="([^"]+)"', classic.content.decode()).group(1)}
        # the wall of a board that is read from 2 m on a 55" TV: the grid is told its screen and distance
        from monitoring.models import MonitorBoard
        board = MonitorBoard.objects.get(name=TEST_WALL)
        wall = {'board': str(board.pk), 'mode': 'small', 'wall': '1'}
        page = self.ask(PAGE, wall)
        self.assertIn('data-screen-inches="55.0" data-distance-m="2.0"', page.content.decode())
        index['wall-board-en'] = {'page': self.keep('page-wall-board-en', page), 'lang': 'en',
                                  'cards': self.keep('cards-wall-board-en', self.ask(CARDS, wall)),
                                  'nonce': re.search(r'nonce="([^"]+)"', page.content.decode()).group(1)}
        # the same screen after TW-01 got worse: its oxygen now past the critical limit (the announcer's case)
        water.record(self.admin, point=point_of(self.units['TW-01']), measured_at=MOMENT, source='manual',
                     values={'oxygen_mg_l': Decimal('4.5')})
        for language in ('en', 'nb', 'tr'):
            worse = self.ask(CARDS, SCREENS['small'], language=language)
            self.assertEqual(cards_say(worse.content.decode(), self.norm)['TW-01']['state'],
                             {'en': 'Critical', 'nb': 'Kritisk', 'tr': 'Kritik'}[language])
            index[f'small-{language}']['worse'] = self.keep(f'cards-small-{language}-worse', worse)
        (OUT / 'index.json').write_text(json.dumps(index, indent=1), encoding='utf-8')

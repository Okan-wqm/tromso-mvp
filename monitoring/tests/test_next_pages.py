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
from core.test_world import (MIXED_BIG, MIXED_OWN, MOMENT, MONITORING_UNITS, TEST_MIXED_BOARD, TEST_OPERATOR_BOARD,
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
# The units whose Big card the browser test opens in the pane too (beside TW-02): an old critical, many values, and an
# old sample in the CO2 region of its chart.
PANES = ('TW-08', 'TW-09', 'TW-12')
# What the design's Big card of an empty unit says that the classic one does not: the unit, the chart's place and why it
# is empty, what to dose, the other points, the stock (in English).
EMPTY_BIG = ('Status', 'Volume', 'Max density', 'Max biomass', 'No chart: there is no fish in this unit.', 'Dosing advice',
             'No dosing advice', 'Other sampling points', 'Stock', 'No fish')


def _articles(html):
    """{the card's key (data-key): its markup} of the cards of a fragment, in its order."""
    return {re.search(r'data-key="([^"]+)"', article).group(1): article
            for article in re.findall(r'<article .*?</article>', html, re.S)}


def _stocked(html):
    """The markup without the cards of the units with no fish (each article whose state is empty)."""
    return re.sub(r'<article [^>]*data-state="empty".*?</article>\n?', '', html, flags=re.S)


# What the new look adds to a Big card's chart: its frame is a stop of the keyboard with an id of its own (on a phone the
# picture scrolls sideways in it: templates/monitoring/widgets/_chart.html); the classic card's never scrolls.
CHART_STOP = re.compile(r'(<figure class="monitor-chart [^"]*") id="[^"]*chart-[^"]*" tabindex="0"')


def _fitted(html):
    """The new look's markup of fitted cards without what only the new look adds to every Big card (CHART_STOP)."""
    return CHART_STOP.sub(r'\1', html)


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
                    'TW-09': 'No limit', 'TW-10': 'No limit', 'TW-11': 'No limit', 'TW-12': 'Critical'}
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
            elif name in BIG_SCREENS:
                self.assertEqual(_fitted(_stocked(new)), _stocked(classic), name)
                self.assertEqual(len(CHART_STOP.findall(new)), len(re.findall(r'<svg class="monitor-chart-svg', new)), name)
                self.assertGreaterEqual(cards - _stocked(classic).count('<article class="monitor-card '), 2, name)
            else:
                self.assertEqual(_fitted(new), classic, name)
        focus = {**SCREENS['small'], 'focus': str(self.units['TW-02'].pk)}
        self.assertEqual(_fitted(self.ask(PANE, focus).content.decode()), self.ask(PANE, focus, look='').content.decode())

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

    def test_the_big_cards_water_says_whether_its_tiles_hold_it(self):
        """Whether a Big card's water is drawn as the design's tiles is the server's one answer (monitoring/cards/render.py
        tiled: one column of at most eight values, in a place of the template that holds two lines of four tiles), said
        on the rows' frame as `data-tiles` in both looks, which the new look's sheet draws from (never a count of a
        table's children). Five and eight values on the built-in Big card: tiles; ten (TW-09), fifteen and seventeen
        (TW-10, TW-11: two columns of rows): none; five values on a farm's full-height template whose water's place is
        low (the mixed board's TW-06): none. On the Big screen, its wall, the mixed board and in the pane."""
        from monitoring.cards.render import WATER_TILES
        self.assertEqual(WATER_TILES, 8)
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
                        self.assertEqual([' data-tiles' in frame for frame in frames], [tiles] * len(frames))
                        values = len(re.findall(r'role="rowheader"', articles[code]))
                        if code in ('TW-10', 'TW-11'):
                            self.assertEqual((values, articles[code].count('role="table"')),
                                             (15 if code == 'TW-10' else 17, 2))
        for code, tiles in (('TW-02', True), ('TW-09', False)):
            pane = self.ask(PANE, {**SCREENS['small'], 'focus': str(self.units[code].pk)}).content.decode()
            self.assertEqual(' data-tiles' in pane, tiles, code)

    def test_a_fitted_cards_markup_is_the_same_on_a_board_that_mixes_them(self):
        """The mixed board (core/test_world.py mixed_board): Small cards, two Big ones and one drawn with a farm's own
        full-height template, in the farm's one order; every card the same markup in both looks (none of them empty), but
        the Big cards' chart frames, a stop of the keyboard in the new look (CHART_STOP)."""
        new, classic = self.fragment(self.screens['mixed']), self.fragment(self.screens['mixed'], look='')
        self.assertEqual(_fitted(new), classic)
        articles = {self.norm(key[len('card:'):]): article for key, article in _articles(new).items()}
        for code, article in articles.items():
            with self.subTest(card=code):
                self.assertEqual(' data-fill' in article, code in (*MIXED_BIG, MIXED_OWN))
                self.assertIn(' is-fit ', article)

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

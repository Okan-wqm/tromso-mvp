"""The band above the cards (monitoring/read.py band, templates/monitoring/_grid.html): when the cards were computed and
how many units are shown, the tally per state, a chip per thing that needs a look with the value and the bound it is
past, units with the same words sharing a chip, the server's cap with the rest counted, the switch of the screen's
cards and the page indicator. It replaces the head and the strip of one-line reasons; nothing they said is lost."""
import re
from types import SimpleNamespace

from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from farm.water.evaluate import Status

from .. import read
from ..models import MonitorBoard, MonitorBoardUnit
from . import MonitoringCase
from .golden import Tree
from .test_read import card, reading, water

PAGE, CARDS = reverse('monitoring:monitor'), reverse('monitoring:cards')


def text(node):
    return ' '.join(node.text().split())


def band_of(html):
    return next(node for node in Tree(html).root.walk() if node.attrs.get('data-key') == 'band')


def named(code, **changes):
    return card(unit=SimpleNamespace(code=code, pk=code), **changes)


def critical(code, parameter='oxygen_mg_l'):
    return named(code, water=(water(reading(parameter, 2, status=Status.CRITICAL)),))


class BandReadTests(SimpleTestCase):
    """On hand-made cards: the tally and the chips are worked out from the cards' states alone."""

    def cards(self):
        return [named('A'), critical('B'), named('C', water=()), named('D', stock=SimpleNamespace(over_capacity=True)),
                named('E', water=()), named('F', stock=SimpleNamespace(over_capacity=True)), named('G', stock=None),
                named('H', withdrawal=(SimpleNamespace(until=None),))]

    def test_the_tally_counts_every_card_worst_first(self):
        found = read.band(self.cards())
        self.assertEqual([(key, str(word), count) for key, word, count in found.tally],
                         [('critical', 'Critical', 1), ('warning', 'Warning', 2), ('blind', 'No recent data', 2),
                          ('note', 'Note', 1), ('ok', 'OK', 1), ('empty', 'Empty', 1)])
        self.assertEqual(sum(count for _key, _word, count in found.tally), 8)
        self.assertEqual(read.band([]).tally, ())

    def test_a_chip_per_thing_that_needs_a_look_and_units_with_the_same_words_share_one(self):
        found = read.band(self.cards())
        self.assertEqual([(chip.state, [each.unit.code for each in chip.cards], chip.text) for chip in found.chips],
                         [('critical', ['B'], 'Dissolved oxygen (mg/L O₂): Critical'),
                          ('warning', ['D', 'F'], 'Over capacity'),               # the same words: one chip
                          ('blind', ['C', 'E'], 'no recent data')])                # the state's words: the card says which
        self.assertEqual(found.more, 0)
        self.assertEqual([chip.word for chip in found.chips], ['Critical', 'Warning', 'No recent data'])

    def test_the_server_caps_the_chips_and_the_codes_and_counts_the_rest(self):
        cards = [critical(f'K-{number}', parameter) for number, parameter in enumerate(         # five different sentences
            ('oxygen_mg_l', 'temperature_c', 'ph', 'co2_mg_l', 'tan_mg_l'), start=1)]
        cards += [named(f'B-{number}', water=()) for number in range(7)]
        with override_settings(MONITOR_BAND_CHIPS=3, MONITOR_BAND_CODES=4):
            found = read.band(cards)
        self.assertEqual(len(found.chips), 3)
        self.assertEqual(found.more, 2 + 7)                              # two critical units and the seven blind ones
        self.assertEqual(sum(count for _key, _word, count in found.tally), 12)        # the tally still counts them all
        whole = read.band(cards, chips=10, codes=4)
        blind = whole.chips[-1]
        self.assertEqual(([each.unit.code for each in blind.shown], blind.more, blind.rest),
                         (['B-0', 'B-1', 'B-2', 'B-3'], 3, 'B-4, B-5, B-6'))
        self.assertEqual(whole.more, 0)

    def test_a_brief_is_the_value_against_the_bound_and_falls_back_to_the_whole_reason(self):
        self.assertEqual(read.brief_of('Over capacity'), read.Brief('Over capacity'))
        self.assertEqual(read.brief_of(read.Reason('Whole sentence')), read.Brief('Whole sentence'))
        short = read.Brief('O₂ (mg/L) 5.00', '<', 'critical limit 6.00', '6.00', True)
        reason = read.Reason('Dissolved oxygen (mg/L O₂): Critical', short)
        self.assertEqual((reason, read.brief_of(reason)), ('Dissolved oxygen (mg/L O₂): Critical', short))
        self.assertEqual(short.sentence, 'O₂ (mg/L) 5.00 < critical limit 6.00')
        self.assertEqual(read.Brief('CO₂ (mg/L) 18.8', '>', 'warning limit 15.0', '15.0').sentence, 'CO₂ (mg/L) 18.8 > 15.0')
        self.assertEqual(read.Brief('CO₂ (mg/L) 18.8', '>', 'warning limit 15.0, no recent data', '15.0', old=True).sentence,
                         'CO₂ (mg/L) 18.8 > 15.0, no recent data')
        self.assertEqual(read.brief_of('{}'.format(reason)), read.Brief(str(reason)))      # a copy: the whole sentence


class BandPageTests(MonitoringCase):
    def setUp(self):
        super().setUp()
        self.limit('oxygen_mg_l', critical_low=6, warning_low=7)
        self.limit('temperature_c', warning_high=15, critical_high=18)

    def test_the_band_is_one_keyed_child_before_the_cards_on_the_page_and_in_the_fragment(self):
        for url in (f'{PAGE}?full=1', CARDS):
            html = self.client.get(url).content.decode()
            self.assertEqual(re.findall(r'data-key="([^"]+)"', html)[:1], ['band'])
            self.assertEqual(html.count('data-key="band"'), 1)
            band = band_of(html)
            self.assertRegex(text(band), r'^computed at \d\d:\d\d · 2 of 3 units shown')
            # the clock is the band's one larger figure, an element with nothing but the time in it
            self.assertRegex(html, r'computed at <b>\d\d:\d\d</b> · 2 of 3')

    def test_the_clock_escapes_its_text(self):
        """The one piece of markup the band's template takes ready-made (core.tests_escaping: no template prints a
        value unescaped): whatever a time format would hold is text."""
        from unittest import mock

        from ..templatetags import cards
        with mock.patch.object(cards, 'date_format', return_value='<img src=x onerror=alert(1)>'):
            self.assertEqual(cards.clock(object()), '<b>&lt;img src=x onerror=alert(1)&gt;</b>')

    def test_the_tally_the_chips_and_their_links(self):
        self.sample(self.t2, hours=1, temperature_c='13.2', oxygen_mg_l='5')
        html = self.client.get(PAGE, {'full': '1'}).content.decode()
        band = band_of(html)
        tally = next(each for each in band.walk() if 'monitor-tally' in each.classes)
        # T-01 holds fish and has no point to read its water at: its oxygen has no fresh value, critical (owner decision
        # of 2026-11-23; review 2 of fresh-rule, R2: it was "no recent data")
        self.assertEqual([text(each) for each in tally.children if not isinstance(each, str)], ['2 Critical'])
        self.assertEqual([each.classes[0] for each in tally.children if not isinstance(each, str)], ['monitor-critical'])
        strip = next(each for each in band.walk() if 'monitor-strip' in each.classes)
        chips = [each for each in strip.children if not isinstance(each, str)]
        self.assertEqual([text(each) for each in chips],
                         ['Critical T-01 O₂ (mg/L): no recent data', 'Critical T-02 O₂ (mg/L) 5.00 < critical limit 6.00'])
        # the state is a shape and, for a screen reader, its word; each code opens its card
        self.assertTrue([each for each in chips[0].walk() if 'monitor-shape-critical' in each.classes])
        links = [(text(each), each.attrs['href']) for each in strip.walk() if each.tag == 'a']
        self.assertEqual(links, [('T-01', f'#card-{self.t1.pk}'), ('T-02', f'#card-{self.t2.pk}')])
        for unit in (self.t1, self.t2):
            self.assertIn(f'id="card-{unit.pk}"', html)

    def test_a_warning_chip_says_the_number_and_nothing_abnormal_shows_no_chip(self):
        self.sample(self.t1, hours=1, temperature_c='13.2', oxygen_mg_l='9')
        self.sample(self.t2, hours=1, oxygen_mg_l='6.5')                 # (T-02's temperature is the fixture's, 13.2 °C)
        band = band_of(self.client.get(PAGE, {'full': '1'}).content.decode())
        strip = next(each for each in band.walk() if 'monitor-strip' in each.classes)
        self.assertEqual([text(each) for each in strip.children if not isinstance(each, str)],
                         ['Warning T-02 O₂ (mg/L) 6.50 < 7.00'])
        self.sample(self.t2, hours=0.5, oxygen_mg_l='9')
        calm = band_of(self.client.get(PAGE, {'full': '1'}).content.decode())
        self.assertFalse([each for each in calm.walk() if 'monitor-strip' in each.classes])

    def test_the_cap_counts_the_units_no_chip_names(self):
        for unit in self.farm_of(3, fresh=False):
            self.sample(unit, hours=1, temperature_c=str(16 + 2 * int(unit.code[-1])), oxygen_mg_l='9')
        with override_settings(MONITOR_BAND_CHIPS=2):
            band = band_of(self.client.get(PAGE, {'full': '1'}).content.decode())
        (more,) = [each for each in band.walk() if 'monitor-strip-more' in each.classes]
        # (the two warning units are past the same bound: one chip; what is left over says its state. T-01 and T-02 hold
        # fish without a fresh oxygen (T-01 has no point at all): critical, one chip "O₂ (mg/L): no recent data", owner
        # decision of 2026-11-23, review 2 of fresh-rule R2)
        self.assertEqual(text(more), '+2 more units: 2 Warning')
        self.assertEqual(text(next(each for each in band.walk() if 'monitor-tally' in each.classes)),
                         '3 Critical 2 Warning')

    def test_the_switch_of_the_screens_cards(self):
        def switch(**query):
            band = band_of(self.client.get(PAGE, {**query, 'full': '1'}).content.decode())
            nav = next(each for each in band.walk() if 'monitor-modes' in each.classes)
            return [(text(each), each.attrs['href'], each.attrs.get('aria-current')) for each in nav.walk()
                    if each.tag == 'a']
        self.assertEqual(switch(), [('Small', f'{PAGE}?mode=small', None), ('Big', f'{PAGE}?mode=big', None),
                                    ('Simple', PAGE, 'page'), ('Detailed', f'{PAGE}?mode=detailed', None)])
        self.assertEqual([current for _label, _url, current in switch(mode='small')], ['page', None, None, None])
        self.assertEqual([current for _label, _url, current in switch(mode='big')], [None, 'page', None, None])
        self.assertEqual([current for _label, _url, current in switch(mode='detailed')], [None, None, None, 'page'])
        # the wall and the filters stay; a card flipped does not
        self.assertEqual([url for _label, url, _current in switch(wall='1', q='T', flip=str(self.t1.pk))],
                         [f'{PAGE}?mode=small&q=T&wall=1', f'{PAGE}?mode=big&q=T&wall=1', f'{PAGE}?q=T&wall=1',
                          f'{PAGE}?mode=detailed&q=T&wall=1'])
        board = MonitorBoard.objects.create(name='Hall A')
        MonitorBoardUnit.objects.create(board=board, unit=self.t1)
        self.assertEqual(switch(board=str(board.pk)),
                         [('Small', f'{PAGE}?board={board.pk}&mode=small', None),
                          ('Big', f'{PAGE}?board={board.pk}&mode=big', None),
                          ('As the board', f'{PAGE}?board={board.pk}', 'page')])

    def test_the_page_indicator_is_there_for_the_wall_script_and_hidden_until_it_is_needed(self):
        band = band_of(self.client.get(PAGE, {'full': '1', 'wall': '1'}).content.decode())
        (pages,) = [each for each in band.walk() if 'data-pages' in each.attrs]
        self.assertIn('hidden', pages.attrs)
        # (its third button is the way to the page of the worst card: Phase 1D, monitoring/tests/test_going_in.py)
        self.assertEqual([each.attrs.get('data-page-turn') for each in pages.walk() if each.tag == 'button'],
                         ['-1', '1', None])
        self.assertTrue(all(each.attrs.get('aria-label') for each in pages.walk() if each.tag == 'button'))
        self.assertTrue([each for each in pages.walk() if 'data-pages-text' in each.attrs])


class BandReviewTests(MonitoringCase):
    """The review of 1B (R2, R4, R5): the cap never hides a critical unit, units past one bound are one chip, no chip
    is cut, and a measured CO₂ says it is the probe's."""

    def setUp(self):
        super().setUp()
        self.limit('oxygen_mg_l', critical_low=6, warning_low=7)
        self.limit('temperature_c', warning_high=15, critical_high=18)
        self.limit('co2_mg_l', warning_high=10, critical_high=15)

    def cards(self, units):
        return read.cards(units, self.reader, read.resolve.Choice())

    def test_units_past_the_same_bound_are_one_chip_with_the_worst_figure(self):
        units = self.farm_of(10, fresh=False)
        for number, unit in enumerate(units):
            self.sample(unit, hours=1, temperature_c='9.5', oxygen_mg_l=f'5.{number:02d}')       # 5.00 ... 5.09
        warned = self.farm_of(4, prefix='W', fresh=False)
        for number, unit in enumerate(warned):
            self.sample(unit, hours=1, temperature_c='9.5', oxygen_mg_l=f'6.{number + 3}')        # 6.3 ... 6.6
        found = read.band(self.cards([*units, *warned]), chips=6, codes=4)
        self.assertEqual([(chip.state, chip.text, len(chip.cards), len(chip.shown), chip.more) for chip in found.chips],
                         [('critical', 'O₂ (mg/L) 5.00 < critical limit 6.00', 10, 4, 6),
                          ('warning', 'O₂ (mg/L) 6.30 < 7.00', 4, 4, 0)])
        self.assertEqual((found.more, found.rest, found.hidden), (0, (), ()))

    def test_the_cap_says_what_it_holds_by_state_and_links_to_the_critical_units_it_holds(self):
        units = self.farm_of(5, fresh=False)
        causes = [dict(oxygen_mg_l='5'), dict(temperature_c='19'), dict(co2_mg_l='16'),
                  dict(oxygen_mg_l='5', hours=30), dict(temperature_c='19', hours=30)]      # five causes, all critical
        for unit, cause in zip(units, causes):
            hours = cause.pop('hours', 1)
            self.sample(unit, hours=hours, **{'temperature_c': '9.5', 'oxygen_mg_l': '9', **cause})
        (warned,) = self.farm_of(1, prefix='W', fresh=False)
        self.sample(warned, hours=1, temperature_c='9.5', oxygen_mg_l='6.5')
        every = [*units, warned]
        found = read.band(self.cards(every), chips=3, codes=4)
        self.assertEqual([chip.state for chip in found.chips], ['critical'] * 3)       # every critical chip comes first
        self.assertEqual(found.more, 3)
        self.assertEqual([(key, str(word), count) for key, word, count in found.rest],
                         [('critical', 'Critical', 2), ('warning', 'Warning', 1)])
        self.assertEqual(sorted(card.unit.code for card in found.hidden), sorted(unit.code for unit in units[3:]))
        with override_settings(MONITOR_BAND_CHIPS=3):
            html = self.client.get(PAGE, {'full': '1', 'units': ','.join(str(unit.pk) for unit in every)}).content.decode()
        more = next(each for each in band_of(html).walk() if 'monitor-strip-more' in each.classes)
        self.assertEqual(text(more), '+3 more units: 2 Critical · 1 Warning')
        (link,) = [each for each in more.walk() if each.tag == 'a']
        wanted = '%2C'.join(sorted(str(unit.pk) for unit in units[3:]))
        self.assertEqual(link.attrs['href'], f'{PAGE}?units={wanted}')
        self.assertEqual(self.client.get(f"{link.attrs['href']}&full=1").content.decode().count('data-key="card:'), 2)

    def test_no_chip_and_no_reason_with_a_bound_can_be_cut(self):
        self.sample(self.t1, hours=1, temperature_c='9', oxygen_mg_l='9')   # T-01 fine (fish and its oxygen fresh)
        self.sample(self.t2, hours=30, oxygen_mg_l='5')                # critical and old: the longest chip there is
        html = self.client.get(PAGE, {'full': '1', 'mode': 'small', 'wall': '1'}).content.decode()
        band = band_of(html)
        self.assertNotIn('truncate', ' '.join(' '.join(each.classes) for each in band.walk()))
        self.assertNotIn('overflow-hidden', ' '.join(' '.join(each.classes) for each in band.walk()))
        strip = next(each for each in band.walk() if 'monitor-strip' in each.classes)
        self.assertIn('tw:flex-wrap', strip.classes)
        self.assertNotIn('tw:wall:flex-nowrap', strip.classes)
        chip = next(each for each in strip.walk() if 'monitor-chip-text' in each.classes)
        self.assertEqual(text(chip), 'O₂ (mg/L) 5.00 < critical limit 6.00, no recent data')
        card = next(node for node in Tree(html).root.walk() if node.attrs.get('data-key') == f'card:{self.t2.pk}')
        reasons = next(each for each in card.walk() if 'monitor-reasons' in each.classes)
        first = next(each for each in reasons.children if not isinstance(each, str))
        self.assertNotIn('tw:truncate', first.classes)
        self.assertIn('critical limit 6.00, no recent data', text(first))

    def test_a_measured_co2_says_it_is_the_probes(self):
        self.sample(self.t1, hours=1, temperature_c='9', oxygen_mg_l='9')   # T-01 fine (fish and its oxygen fresh)
        self.sample(self.t2, hours=1, oxygen_mg_l='9', co2_mg_l='16')
        html = self.client.get(PAGE, {'full': '1', 'mode': 'small'}).content.decode()
        chip = next(each for each in band_of(html).walk() if 'monitor-chip-text' in each.classes)
        self.assertEqual(text(chip), 'CO₂ probe (mg/L) 16.0 > critical limit 15.0')
        card = next(node for node in Tree(html).root.walk() if node.attrs.get('data-key') == f'card:{self.t2.pk}')
        reasons = next(each for each in card.walk() if 'monitor-reasons' in each.classes)
        self.assertTrue(text(reasons).startswith('CO₂ probe (mg/L) 16.0 · critical limit 15.0'))
        labels = [text(each) for each in card.walk() if each.tag == 'dt']
        self.assertEqual(labels[3], 'CO₂ calc.')                                  # never two bare "CO₂" on one card

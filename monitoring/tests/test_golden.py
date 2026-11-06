"""Golden cards: what every card of a fixed twenty-unit farm says, on the page and the fragment, in simple, detailed and a
board's mixed mode, flipped, for a person who may read everything and for two who may not, compared with the recording in
golden_cards.json (monitoring/tests/golden.py says what is compared and how). Recorded before card templates; the
built-in templates must keep it green, value for value."""
from datetime import timedelta
from unittest import mock

from django.urls import reverse

from farm.handling.withdrawal import WithdrawalBlock
from farm.models import Batch, HealthEvent, LiceCount, Tank, Treatment
from farm.tests.helpers import stock_fish
from farm.tests.test_stock import make_unit
from monitoring.models import MonitorBoard, MonitorBoardUnit
from tasks.models import Task

from . import golden
from .golden import Normaliser, cards_say, multiset_missing
from . import TEMPLATE, MonitoringCase
from ..cards.builtin import DETAILED

PAGE, CARDS = reverse('monitoring:monitor'), reverse('monitoring:cards')


class GoldenFarm(MonitoringCase):
    """T-01 (no water: no recent data), T-02 (the worked example's ration) and P-01 (an empty pond in maintenance), and
    eighteen more units G-00 to G-17, each in a state of its own (below). Every value but G-17's nitrite has a limit."""

    def setUp(self):
        super().setUp()
        self.limit('oxygen_mg_l', critical_low=6, warning_low=7)
        self.limit('ph', warning_low='6.5', warning_high='8.5')
        self.limit('co2_mg_l', warning_high=15, critical_high=20)
        self.limit('temperature_c', warning_high=15, critical_high=18)
        self.sample(self.t2, hours=1, temperature_c='13.2', oxygen_mg_l='8.1', ph='7.2')
        self.g = []
        for number in range(18):
            unit = make_unit(f'G-{number:02d}', self.hall)
            count = 120000 if number == 5 else 500 + 100 * number           # G-05 is over its capacity
            stock_fish(self.user, unit, count, str(60 + number), 5 + number, species=self.salmon, ack=number == 5)
            self.g.append(unit)
            if number != 13:                                                    # G-13 has no protocol
                self.assign(self.protocol, unit=unit)
        fresh = dict(temperature_c='13', oxygen_mg_l='9', ph='7.2')
        water = {0: fresh, 1: dict(temperature_c='13', oxygen_mg_l='5'),           # critical oxygen
                 2: dict(temperature_c='13', oxygen_mg_l='6.5'),                   # warning oxygen
                 3: None,                                                           # stale (below)
                 4: None,                                                           # never sampled
                 9: dict(temperature_c='13.1', oxygen_saturation_pct='95'),         # the saturation, not mg/L
                 12: dict(temperature_c='16', oxygen_mg_l='8.4', co2_mg_l='12'),    # a warm warning
                 17: dict(temperature_c='13', oxygen_mg_l='9', nitrite_n_mg_l='0.05'),   # no limit for the nitrite
                 }
        for number, unit in enumerate(self.g):
            values = water.get(number, fresh)
            if values:
                self.sample(unit, hours=1, **values)
        self.sample(self.g[3], hours=30, temperature_c='9.1', oxygen_mg_l='8.8')
        # G-06 tasks: one overdue, one due today
        for days in (-2, 0):
            task = Task(title='Clean the drum filter', due_date=self.today + timedelta(days=days))
            task.set_place(self.g[6])
            task.save()
        LiceCount.objects.create(unit=self.g[7], date=self.day(2), fish_counted=20, adult_females=3, mobile=8,
                                 attached=5)
        treatment = Treatment.objects.create(method='thermal', reason='sea_lice', start_date=self.day(4),
                                             end_date=self.day(3))
        treatment.units.set([self.g[8]])
        event = HealthEvent.objects.create(site=self.bergen, date=self.day(1), kind='observation')
        event.units.set([self.g[10]])
        withheld = Batch.objects.filter(movements__unit=self.g[11]).first()
        self.block = WithdrawalBlock(withheld, self.today + timedelta(days=5), False, 'Treated.', None)
        provider = mock.patch('farm.handling.withdrawal._providers',
                              [lambda units, day: {unit.pk: [self.block] for unit in units if unit.pk == self.g[11].pk}])
        provider.start()
        self.addCleanup(provider.stop)
        # a board as migration 0004 leaves one: its modes and the built-ins that draw them
        board = MonitorBoard.objects.create(name='Hall A wall', default_mode='detailed', default_template_id=DETAILED)
        for unit, mode in ((self.t1, ''), (self.t2, 'simple'), (self.g[1], ''), (self.g[6], 'simple'),
                           (self.g[7], 'detailed'), (self.g[11], '')):
            MonitorBoardUnit.objects.create(board=board, unit=unit, mode=mode, template_id=TEMPLATE.get(mode))
        self.board = board
        units = list(Tank.objects.all())
        self.norm = Normaliser(units, [batch.code for batch in Batch.objects.all()], self.today,
                               others=[(board.pk, '<board>')])

    def says(self, url, query=None):
        response = self.client.get(url, query or {})
        self.assertEqual(response.status_code, 200)
        return cards_say(response.content.decode(), self.norm)

    def scenarios(self):
        """{name: what each card of that screen says}."""
        found = {}
        found['simple'] = self.says(PAGE)
        found['detailed'] = self.says(PAGE, {'mode': 'detailed'})
        found['all-simple'] = self.says(PAGE, {'occupancy': 'all'})
        found['flipped'] = self.says(PAGE, {'flip': f'{self.t2.pk},{self.g[7].pk}'})
        found['board'] = self.says(PAGE, {'board': str(self.board.pk)})
        found['fragment-detailed'] = self.says(CARDS, {'mode': 'detailed'})
        self.as_person('stock-only', 'view_stockoperation')
        found['stock-only-detailed'] = self.says(PAGE, {'mode': 'detailed', 'occupancy': 'all'})
        self.as_person('stock-water', 'view_stockoperation', 'view_watermeasurement')
        found['stock-water-simple'] = self.says(PAGE)
        return found


class GoldenTests(GoldenFarm):
    def test_every_card_says_what_it_said_before_card_templates(self):
        found = self.scenarios()
        if golden.WRITE:
            golden.save(found)
        recorded = golden.load()
        self.assertEqual(sorted(found), sorted(recorded), 'the scenarios')
        for scenario, cards in recorded.items():
            self.assertEqual(list(found[scenario]), list(cards), f'{scenario}: the cards and their order')
            for code, was in cards.items():
                now = found[scenario][code]
                where = f'{scenario} {code}'
                with self.subTest(card=where):
                    self.assertEqual(now['state'], was['state'], f'{where}: state word')
                    self.assertEqual(now['reasons'], was['reasons'], f'{where}: reasons')
                    self.assertEqual(now['pairs'], was['pairs'], f'{where}: the labelled figures')
                    self.assertEqual(now['links'], was['links'], f'{where}: the links')
                    self.assertEqual(multiset_missing(was['texts'], now['texts']), [], f'{where}: texts that are gone')
                    self.assertEqual(multiset_missing(was['titles'], now['titles']), [], f'{where}: titles that are gone')

    def test_the_farm_has_every_state_a_card_can_be_in(self):
        states = {card['state'] for card in self.scenarios()['all-simple'].values()}
        self.assertEqual(states, {'Critical', 'Warning', 'No recent data', 'No limit', 'Note', 'OK', 'Empty'})

"""The monitoring read model: the address, the filters, the state ladder (each rung, with the blind
rule), and that every figure a card holds is the owning read's own, checked on one fixture against the pages that
show the same figure."""
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

from django.http import QueryDict
from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import timezone

from farm.harvest import views as harvest_views
from farm.models import HandlingPlanItem, HealthEvent
from farm.tests.helpers import make_facility
from farm.water import parameters, read as water_read
from farm.water.evaluate import Status
from farm.water.read import Observation, Origin, PointWater, Reading

from .. import read
from ..cards import builtin, resolve
from . import D, MonitoringCase, chosen

NOW = timezone.now()
SIMPLE = resolve.Resolved(None, builtin.SIMPLE_LAYOUT, resolve.FALLBACK)
DETAILED = resolve.Resolved(None, builtin.DETAILED_LAYOUT, resolve.ADDRESS)


# ---- the address -------------------------------------------------------------------------------------------------
class ParamsTests(SimpleTestCase):
    def test_a_value_that_names_nothing_is_dropped_and_the_defaults_are_left_out_of_the_canonical_query(self):
        unit = '9b0f6d5e-3c1e-4d6a-8c0d-0e1f2a3b4c5d'
        found = read.Params.from_query(QueryDict(f'site=not-a-uuid&kind=reef&occupancy=weird&mode=huge&units={unit},x'
                                                 f'&flip={unit}&q=%20T-0%20&board=nope'))
        self.assertEqual((found.site, found.kind, found.occupancy, found.mode, found.board), ('', '', 'stocked', '', ''))
        self.assertEqual((found.units, found.flip, found.q), ((unit,), frozenset({unit}), 'T-0'))
        self.assertEqual(found.canonical(), f'flip={unit}&q=T-0&units={unit}')
        self.assertEqual(read.Params().canonical(), '')

    def test_one_state_one_spelling(self):
        first = read.Params.from_query(QueryDict('kind=tank&q=a&occupancy=all'))
        second = read.Params.from_query(QueryDict('occupancy=all&q=a&kind=tank'))
        self.assertEqual(first.canonical(), second.canonical())
        self.assertEqual(first.canonical(), 'kind=tank&occupancy=all&q=a')
        self.assertEqual(first.canonical(kind=''), 'occupancy=all&q=a')


# ---- the state ladder, on hand-made cards ---------------------------------------------------------------------------
def reading(code, value, hours=1, status=Status.OK, point=None, judged=None):
    """A reading as farm/water/read.py judges one: `status` what the page shows (stale when old), `judged` what its
    limit says whatever its age (by default the status, and OK for a stale one)."""
    point = point or SimpleNamespace(name='Middle', kind='middle')
    sample = Observation(point, NOW - timedelta(hours=hours), Origin.MANUAL, {code: D(str(value))})
    found = Reading(parameters.get(code), D(str(value)), sample, status=status)
    found.judged = judged or (Status.OK if status == Status.STALE else status)
    found.uncovered = (1,) if found.judged == Status.NO_LIMIT else ()      # the species no row judges it for
    return found


def water(*readings, kind='middle', sensors_failed=False):
    point = SimpleNamespace(name='Middle', kind=kind)
    return PointWater(point, {each.code: each for each in readings}, sensors_failed=sensors_failed)


def card(**changes):
    values = dict(
        unit=SimpleNamespace(code='T-01'), template=SIMPLE, today=None, stock=SimpleNamespace(over_capacity=False),
        water=(water(reading('temperature_c', 9), reading('oxygen_mg_l', 9)),), sections=frozenset(read.SECTIONS),
        now=NOW)
    values.update(changes)
    return read.Card(**values)


class LadderTests(SimpleTestCase):
    def key(self, **changes):
        return card(**changes).state.key

    def test_no_fish_is_empty_whatever_the_water_says(self):
        self.assertEqual(self.key(stock=None), 'empty')
        self.assertEqual(self.key(stock=None, water=(water(reading('oxygen_mg_l', 1, status=Status.CRITICAL)),)), 'empty')

    def test_a_healthy_card_is_ok(self):
        state = card().state
        self.assertEqual((state.key, state.reasons), ('ok', ()))
        self.assertEqual(state.basis, ('stock', 'feeding', 'water', 'health'))

    def test_critical_beats_everything_below_it(self):
        bad = water(reading('oxygen_mg_l', 4, status=Status.CRITICAL), reading('temperature_c', 9))
        state = card(water=(bad,), stock=SimpleNamespace(over_capacity=True), drift='now').state
        self.assertEqual(state.key, 'critical')
        self.assertEqual(state.reasons, ('Dissolved oxygen (mg/L O₂): Critical',))

    def test_warning_is_a_warning_reading_the_unit_over_capacity_or_an_estimate_that_says_weigh_now(self):
        warn = water(reading('temperature_c', 16, status=Status.WARNING), reading('oxygen_mg_l', 9))
        self.assertEqual(self.key(water=(warn,)), 'warning')
        over = card(stock=SimpleNamespace(over_capacity=True)).state
        self.assertEqual((over.key, over.reasons), ('warning', ('Over capacity',)))
        self.assertEqual(self.key(drift='now'), 'warning')
        self.assertEqual(self.key(drift='soon'), 'note')                  # soon is a note, now is a warning

    def test_an_alert_of_another_point_does_not_change_the_state_and_so_not_with_the_template(self):
        drain = PointWater(SimpleNamespace(name='Bottom drain', kind='bottom_drain'),
                           {'oxygen_mg_l': reading('oxygen_mg_l', 2, status=Status.CRITICAL)})
        for template in (SIMPLE, DETAILED):
            with self.subTest(template=template.why):
                middle = water(reading('temperature_c', 9), reading('oxygen_mg_l', 9))
                state = card(template=template, water=(middle, drain)).state
                self.assertEqual(state.key, 'ok')
        # the middle point alone decides: the same reading at the middle is critical
        self.assertEqual(self.key(water=(water(reading('temperature_c', 9),
                                              reading('oxygen_mg_l', 2, status=Status.CRITICAL)),)), 'critical')

    def test_an_old_critical_or_warning_is_said_with_no_recent_data_never_hidden(self):
        """The water page's rule (PointWater.status): an old critical value keeps the middle point critical, so the card
        is critical with "Critical, no recent data", never ok because a fresh pH is fine; the same for a warning."""
        for judged, key in ((Status.CRITICAL, 'critical'), (Status.WARNING, 'warning')):
            with self.subTest(judged=judged):
                old = reading('co2_mg_l', 15.6, hours=80, status=Status.STALE)
                old.judged = judged
                mixed = water(reading('temperature_c', 9), reading('oxygen_mg_l', 9), reading('ph', 7.2), old)
                self.assertEqual((mixed.status, mixed.old_alert), (judged, True))
                state = card(water=(mixed,)).state
                label = Status(judged).label
                self.assertEqual((state.key, state.reasons),
                                 (key, (f'{parameters.get("co2_mg_l").label}: {label}, no recent data',)))

    def test_a_fresh_ph_does_not_hide_a_stale_oxygen(self):
        mixed = water(reading('ph', 7.2, hours=1), reading('temperature_c', 9),
                      reading('oxygen_mg_l', 9, hours=72, status=Status.STALE))
        self.assertEqual(mixed.status, Status.OK)                          # the water's own status ranks OK above stale
        self.assertNotEqual(mixed.status, Status.STALE)
        state = card(water=(mixed,)).state
        self.assertEqual(state.key, 'blind')
        self.assertEqual(len(state.stale), 1)
        self.assertIn('Dissolved oxygen (mg/L O₂): no recent data, 3 days old', state.stale[0].replace('\xa0', ' '))

    def test_blind_is_a_missing_or_old_temperature_or_oxygen_or_no_middle_point(self):
        for readings in ((reading('oxygen_mg_l', 9),), (reading('temperature_c', 9),),
                         (reading('temperature_c', 9, hours=25), reading('oxygen_mg_l', 9))):
            with self.subTest(readings=[each.code for each in readings]):
                self.assertEqual(self.key(water=(water(*readings),)), 'blind')
        self.assertEqual(self.key(water=()), 'blind')
        self.assertEqual(card(water=()).state.stale,
                         ('Temperature (°C): no recent data', 'Dissolved oxygen (mg/L O₂): no recent data'))
        self.assertEqual(self.key(water=(water(reading('temperature_c', 9), reading('oxygen_mg_l', 9), kind='inlet'),)),
                         'blind')                                          # the first point is not the middle one

    def test_the_oxygen_may_be_the_saturation_and_a_day_is_the_limit(self):
        percent = water(reading('temperature_c', 9, hours=23), reading('oxygen_saturation_pct', 95, hours=23))
        self.assertEqual(self.key(water=(percent,)), 'ok')
        self.assertEqual(parameters.get('temperature_c').fresh_hours, 24)      # the owner's 24 hours are the parameter's
        self.assertEqual(parameters.get('oxygen_mg_l').fresh_hours, 24)

    def test_blind_is_never_ok_and_never_worse_than_a_warning(self):
        blind = card(water=())
        self.assertGreater(read.RANK[blind.state.key], read.RANK['warning'])
        self.assertLess(read.RANK[blind.state.key], read.RANK['ok'])

    def test_a_card_that_may_not_see_the_water_is_not_blind_and_says_what_it_is_from(self):
        state = card(water=(), sections=frozenset({'stock', 'feeding'}), hidden=('water', 'health', 'tasks')).state
        self.assertEqual((state.key, state.basis), ('ok', ('stock', 'feeding')))
        self.assertEqual(state.stale, ())

    def test_a_withdrawal_alone_is_a_note_not_an_alarm(self):
        state = card(withdrawal=(SimpleNamespace(until=None),)).state
        self.assertEqual((state.key, state.reasons), ('note', ('Medicine withdrawal in force',)))

    def test_notes_are_a_ration_that_cannot_be_worked_out_and_an_open_event(self):
        lines = ({'why': 'No protocol applies to these fish.', 'drift': ''},)
        state = card(lines=lines, events=(SimpleNamespace(),)).state
        self.assertEqual(state.key, 'note')
        self.assertEqual(state.reasons, ('No protocol applies to these fish.', '1 open health event'))
        self.assertEqual(card(events=(1, 2)).state.reasons, ('2 open health events',))

    def test_attention_lists_the_worst_first_and_leaves_the_ok_ones(self):
        cards = [card(unit=SimpleNamespace(code='A')), card(unit=SimpleNamespace(code='B'), water=()),
                 card(unit=SimpleNamespace(code='C'), stock=SimpleNamespace(over_capacity=True)),
                 card(unit=SimpleNamespace(code='D'), water=(water(reading('oxygen_mg_l', 2, status=Status.CRITICAL),),)),
                 card(unit=SimpleNamespace(code='E'), withdrawal=(1,))]
        self.assertEqual([each.unit.code for each in read.attention(cards)], ['D', 'C', 'B'])

    # -- danger is never shown as OK (F-090, F-244, F-134) --
    def fine(self, *more, **changes):
        """The middle point's water: a fresh temperature and oxygen judged OK, and `more`."""
        return water(reading('temperature_c', 9), reading('oxygen_mg_l', 9), *more, **changes)

    def test_a_stale_critical_value_keeps_the_card_critical_and_says_it_is_old(self):
        nitrite = reading('nitrite_n_mg_l', '0.5', hours=200, status=Status.STALE, judged=Status.CRITICAL)
        state = card(water=(self.fine(nitrite),)).state
        self.assertEqual(state.key, 'critical')
        self.assertEqual(len(state.reasons), 1)
        said = state.reasons[0].replace('\xa0', ' ')
        self.assertEqual(said, 'Nitrite (mg/L NO₂ as N): Critical, no recent data')   # the water page's words
        self.assertEqual(state.stale, state.reasons)                   # the wall marks the card as old too

    def test_a_stale_warning_value_keeps_the_card_a_warning_and_says_it_is_old(self):
        tan = reading('tan_mg_l', '2', hours=200, status=Status.STALE, judged=Status.WARNING)
        state = card(water=(self.fine(tan),)).state
        self.assertEqual((state.key, len(state.stale)), ('warning', 1))
        self.assertIn('Warning, no recent data', state.reasons[0])

    def test_a_fresh_critical_value_is_not_marked_old_beside_a_stale_one(self):
        fresh = reading('ph', '5', status=Status.CRITICAL)
        old = reading('tan_mg_l', '2', hours=200, status=Status.STALE, judged=Status.CRITICAL)
        state = card(water=(self.fine(fresh, old),)).state
        self.assertEqual(state.key, 'critical')
        self.assertEqual(len(state.reasons), 2)
        self.assertEqual(len(state.stale), 1)

    def test_a_value_the_fish_have_no_limit_for_is_never_ok(self):
        ph = reading('ph', '4.1', status=Status.NO_LIMIT)
        state = card(water=(self.fine(ph),)).state
        self.assertEqual((state.key, state.reasons), ('unjudged', ('pH (NBS scale): no limit for these fish',)))
        self.assertEqual(card(water=(self.fine(ph),), withdrawal=(1,)).state.key, 'unjudged')    # above a note
        self.assertEqual(card(water=(self.fine(ph),), drift='now').state.key, 'warning')         # below a warning

    def test_an_oxygen_value_no_row_judges_in_either_unit_is_never_ok(self):
        """The owner's rule: the oxygen is one quantity; farm/water/read.py judges a % through the mg/L row (and the
        reverse) and leaves `uncovered` only the fish no row of either unit judges. What it leaves is "No limit"."""
        judged = reading('oxygen_saturation_pct', 35, status=Status.CRITICAL)                  # through the mg/L row
        self.assertEqual(self.key(water=(self.fine(judged),)), 'critical')
        unjudged = reading('oxygen_saturation_pct', 35, status=Status.NO_LIMIT)               # no temperature to convert
        self.assertEqual(card(water=(self.fine(unjudged),)).state.reasons,
                         ('Oxygen saturation (% of air saturation): no limit for these fish',))

    def test_no_limit_ranks_below_no_recent_data_and_the_strip_names_it(self):
        self.assertLess(read.RANK['blind'], read.RANK['unjudged'])
        self.assertLess(read.RANK['unjudged'], read.RANK['note'])
        unjudged = card(unit=SimpleNamespace(code='U'), water=(self.fine(reading('ph', 7, status=Status.NO_LIMIT)),))
        self.assertEqual([each.unit.code for each in read.attention([card(), unjudged])], ['U'])

    def test_live_sensors_that_could_not_be_read_are_never_ok(self):
        state = card(water=(self.fine(sensors_failed=True),)).state
        self.assertEqual((state.key, state.reasons), ('blind', ('Live sensor values could not be read: samples only.',)))

    def test_every_state_has_one_word(self):
        self.assertEqual([key for key, _word in read.STATES], list(read.RANK))
        self.assertEqual(read.State('unjudged').word, 'No limit')
        self.assertEqual(read.State('blind').word, 'No recent data')


# ---- against the database --------------------------------------------------------------------------------------------
class UnitsForTests(MonitoringCase):
    def test_the_farms_one_order_the_filters_and_one_query(self):
        self.assertEqual([unit.code for unit in read.units_for(read.Params())], ['T-01', 'T-02', 'P-01'])
        with self.assertNumQueries(1):
            read.units_for(read.Params(site=str(self.tromso.pk)))
        self.assertEqual([unit.code for unit in read.units_for(read.Params(site=str(self.tromso.pk)))], ['P-01'])
        self.assertEqual([unit.code for unit in read.units_for(read.Params(kind='pond'))], ['P-01'])
        self.assertEqual([unit.code for unit in read.units_for(read.Params(q='t-02'))], ['T-02'])
        self.assertEqual([unit.code for unit in read.units_for(read.Params(units=(str(self.t2.pk),)))], ['T-02'])
        self.assertEqual([unit.code for unit in read.units_for(read.Params(department=str(self.sea.pk)))], ['P-01'])

    def test_a_board_adds_its_units(self):
        board = SimpleNamespace(rows=SimpleNamespace(all=lambda: [SimpleNamespace(unit_id=self.p1.pk, mode='')]))
        self.assertEqual([unit.code for unit in read.units_for(read.Params(), board)], ['P-01'])


class CardsTests(MonitoringCase):
    def cards(self, occupancy='stocked', mode='simple', units=None, user=None):
        units = units or read.units_for(read.Params())
        return read.cards(units, user or self.reader, chosen({unit.pk: mode for unit in units}), occupancy)

    def test_occupancy_keeps_the_stocked_the_empty_or_all(self):
        self.assertEqual({card.unit.code for card in self.cards()}, {'T-01', 'T-02'})
        self.assertEqual({card.unit.code for card in self.cards('empty')}, {'P-01'})
        self.assertEqual([card.unit.code for card in self.cards('all')], ['T-01', 'T-02', 'P-01'])
        empty = self.cards('empty')[0]
        self.assertEqual((empty.stock, empty.day, empty.feeding, empty.state.key), (None, None, None, 'empty'))

    def test_the_states_of_a_small_farm_each_from_its_own_data(self):
        self.limit('oxygen_mg_l', critical_low=6, warning_low=7)
        self.sample(self.t1, hours=1, temperature_c='9', oxygen_mg_l='5', ph='7.2')           # critical oxygen
        self.sample(self.t2, hours=1, ph='7.2')                                               # fresh pH, no temperature
        states = {card.unit.code: card.state for card in self.cards()}
        self.assertEqual(states['T-01'].key, 'critical')
        self.assertEqual(states['T-02'].key, 'blind')

    def test_a_stocked_unit_whose_fish_have_no_limit_is_not_ok_and_an_old_critical_value_stays_critical(self):
        """F-090 and F-244 on the database: no limit row for the fish is said on the card; a critical nitrite of eight
        days ago keeps the card critical while the oxygen and the temperature are fresh and fine."""
        self.sample(self.t2, hours=1, temperature_c='9', oxygen_mg_l='9')
        self.assertEqual({card.unit.code: card.state.key for card in self.cards()}['T-02'], 'unjudged')
        self.limit('oxygen_mg_l', critical_low=6, warning_low=7)
        self.limit('temperature_c', warning_high=15, critical_high=18)
        self.limit('nitrite_n_mg_l', warning_high='0.1', critical_high='0.2')
        self.assertIn({card.unit.code: card.state.key for card in self.cards()}['T-02'], ('ok', 'note'))   # judged
        self.sample(self.t2, hours=200, nitrite_n_mg_l='0.5')
        state = {card.unit.code: card.state for card in self.cards()}['T-02']
        self.assertEqual(state.key, 'critical')
        self.assertIn('no recent data', state.reasons[0])

    def test_the_card_is_what_the_pages_say_for_the_same_unit(self):
        """No second computation: the card's figures are those the other pages print, on one fixture."""
        self.limit('oxygen_mg_l', critical_low=6, warning_low=7)
        self.sample(self.t2, hours=1, temperature_c='13.2', oxygen_mg_l='8', ph='7.2')
        cards = {card.unit.code: card for card in self.cards(mode='detailed')}
        # the stock: Production units' row and the drawer
        page = self.client.get(reverse('farm:production_units'), {'unit': self.t2.pk})
        row = next(row for row in page.context['rows'] if row['unit'] == self.t2)
        card = cards['T-02']
        for name in ('count', 'avg_weight_g', 'biomass_kg', 'density', 'capacity', 'over_capacity', 'survival', 'since',
                     'volume_m3'):
            self.assertEqual(getattr(card.stock, name), getattr(row['stock'], name), name)
        self.assertEqual(card.stock.days(card.today), page.context['drawer_days'])
        # the feeding: bFCR, eFCR, last fed, the week as Production units has them
        self.assertEqual((card.feeding.conversion.biological, card.feeding.conversion.economic, card.feeding.last_fed),
                         (row['feeding'].conversion.biological, row['feeding'].conversion.economic,
                          row['feeding'].last_fed))
        self.assertEqual(card.feeding.week, page.context['feeding'].week)
        # the ration, what was fed, what remains, the next meal: the meal board's line for the unit
        _response, board, line = self.board_line()
        for name in ('fed_kg', 'meals_done', 'ration_kg', 'remaining_kg', 'next_meal_kg', 'calculated_kg'):
            self.assertEqual(getattr(card.day, name), getattr(board['day'], name), name)
        self.assertEqual([(each['why'], each['drift'], each['estimate_days']) for each in card.lines],
                         [(each['why'], each['drift'], each['estimate_days']) for each in board['lines']])
        # the water: Production units' own value of the middle point
        shown = water_read.unit_water([self.t2])[self.t2.pk]
        self.assertEqual(card.water[0], shown)
        self.assertEqual(card.water[0].get('temperature_c').value, D('13.2'))
        # the withdrawal: the harvest module's registry answer
        self.assertEqual(card.withdrawal, tuple(harvest_views.withdrawals([self.t2]).get(self.t2.pk, ())))

    def test_a_withdrawal_in_force_is_on_the_card_exactly_as_production_units_has_it(self):
        from farm.handling.withdrawal import WithdrawalBlock
        self.limit('oxygen_mg_l', critical_low=6)
        self.limit('temperature_c', critical_high=18)
        for unit in (self.t1, self.t2):
            self.sample(unit, hours=1, temperature_c='10', oxygen_mg_l='9')
        block = WithdrawalBlock(self.fish, self.today + timedelta(days=5), False, 'Treated.', None)
        with mock.patch('farm.handling.withdrawal._providers', [lambda units, day: {unit.pk: [block] for unit in units}]):
            page = self.client.get(reverse('farm:production_units'))
            on_page = {row['unit'].code: list(row['withdrawal']) for row in page.context['rows'] if row['withdrawal']}
            found = self.cards()
        self.assertEqual({card.unit.code: list(card.withdrawal) for card in found}, on_page)
        self.assertEqual(set(on_page), {'T-01', 'T-02'})
        for card in found:
            self.assertEqual((card.state.key, 'Medicine withdrawal in force' in card.state.reasons), ('note', True))

    def test_an_open_event_and_the_detailed_extras(self):
        event = HealthEvent.objects.create(site=self.bergen, date=self.day(1), kind='observation')
        by_unit = {card.unit.code: card for card in self.cards(mode='detailed')}
        self.assertEqual(by_unit['T-02'].events, (event,))
        self.assertEqual(by_unit['T-02'].tasks, None)                       # no tasks: the reader defaults to nothing
        self.assertEqual(by_unit['T-02'].lice, None)
        simple = {card.unit.code: card for card in self.cards()}
        self.assertEqual(simple['T-02'].events, (event,))                   # the state needs it in every mode
        self.assertEqual((simple['T-02'].treatments, simple['T-02'].tasks, simple['T-02'].lice), ((), None, None))

    def test_a_fasting_unit_says_why_it_has_no_ration(self):
        self.limit('oxygen_mg_l', critical_low=6)
        self.limit('temperature_c', critical_high=18)
        self.sample(self.t2, hours=1, temperature_c='13.2', oxygen_mg_l='8')
        HandlingPlanItem.objects.create(kind='harvest', date=self.today + timedelta(days=2), unit=self.t2,
                                        batch=self.fish, facility=make_facility())
        card = next(each for each in self.cards() if each.unit.code == 'T-02')
        self.assertIn('Fasting before the harvest', card.lines[0]['why'])
        self.assertEqual(card.state.key, 'note')
        self.assertTrue(any('Fasting before the harvest' in reason for reason in card.state.reasons))

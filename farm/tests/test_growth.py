"""The growth rule on its own (farm/feeding/growth.py): every property the estimate between weighings and the plan
ahead rest on, over whole grids of values (itertools.product), in exact arithmetic (Fraction) where a property is an
equality and in the code's own Decimal where today's numbers must come out to the last digit.

- conservation: feed given = eaten + uneaten, and growth = eaten ÷ FCR;
- no uneaten feed is today's rule exactly (feed ÷ FCR), and one band is one FCR at every weight;
- the FCR over weight is continuous (no jump at a band's edge or anywhere else), stays between its neighbours' values,
  is each band's own value at the band's anchor and constant outside the first and last anchor;
- the weight never falls along a curve, more uneaten feed or a higher FCR never grows the fish more;
- mortality lowers the count and never the average weight, and a month of it takes exactly its share;
- a curve ends on the target day, at a stop or at the horizon, and its totals add up."""
from datetime import date, timedelta
from decimal import Decimal
from fractions import Fraction
from itertools import product

from django.test import SimpleTestCase

from ..feeding import growth
from ..feeding.growth import Stop, Terms, anchor, curve, economic_fcr, interpolate, step, survival_a_day

D, F = Decimal, Fraction
START = date(2026, 11, 26)

FEEDS = [F(0), F(1, 1000), F(5), F('12.5'), F(1000), F(123456789, 1000)]
FCRS = [F('0.5'), F('0.86'), F(1), F('1.25'), F(3)]
UNEATEN = [F(0), F('0.1'), F(5), F(20), F('33.3'), F(50)]


def terms(sfr='1', fcr='1', uneaten='0', mortality=None, fasting=False):
    return Terms(D(sfr), D(fcr), D(uneaten), None if mortality is None else D(mortality), D('10'), fasting)


def constant(**kwargs):
    made = terms(**kwargs)
    return lambda day, weight: made


class StepTests(SimpleTestCase):
    def test_feed_given_is_eaten_plus_uneaten_and_growth_is_eaten_over_fcr(self):
        for feed, fcr, uneaten in product(FEEDS, FCRS, UNEATEN):
            found = step(feed, fcr, uneaten)
            self.assertEqual(found.given, feed)
            self.assertEqual(found.eaten + found.uneaten, found.given)
            self.assertEqual(found.uneaten, feed * uneaten / 100)
            self.assertEqual(found.growth * fcr, found.eaten)
            self.assertGreaterEqual(found.eaten, 0)
            self.assertGreaterEqual(found.uneaten, 0)

    def test_without_uneaten_feed_it_is_todays_rule_to_the_last_digit(self):
        # main's projection: credit × 1000 ÷ FCR; main's forecast: weight × SFR ÷ 100 ÷ FCR. In Decimal, as the code runs.
        for credit, fcr in product(('0.150', '12.5', '10', '7.333333333333333333333333333', '0'),
                                   ('0.90', '1.00', '1.05', '1.2', '3.00')):
            self.assertEqual(step(D(credit) * 1000, D(fcr)).growth, D(credit) * 1000 / D(fcr))
            self.assertEqual(step(D(credit) * 1000, D(fcr), D(0)).growth, D(credit) * 1000 / D(fcr))
        for weight, sfr, fcr in product(('50', '85.4321', '4999.99'), ('1.00', '1.22', '0.6'), ('1.00', '1.05', '0.7')):
            self.assertEqual(step(D(weight) * D(sfr) / 100, D(fcr), D(0)).growth, D(weight) * D(sfr) / 100 / D(fcr))

    def test_more_uneaten_feed_or_a_higher_fcr_never_grows_the_fish_more(self):
        for feed, fcr in product(FEEDS, FCRS):
            grown = [step(feed, fcr, uneaten).growth for uneaten in UNEATEN]
            self.assertEqual(grown, sorted(grown, reverse=True))
        for feed, uneaten in product(FEEDS, UNEATEN):
            grown = [step(feed, fcr, uneaten).growth for fcr in FCRS]
            self.assertEqual(grown, sorted(grown, reverse=True))

    def test_the_economic_fcr_is_feed_given_over_growth(self):
        for feed, fcr, uneaten in product(FEEDS[1:], FCRS, UNEATEN):
            self.assertEqual(economic_fcr(fcr, uneaten), feed / step(feed, fcr, uneaten).growth)
        self.assertEqual(economic_fcr(D('1.00'), D(20)), D('1.25'))          # 1.00 ÷ 0.8
        self.assertEqual(economic_fcr(D('1.10'), D(0)), D('1.10'))


class InterpolationTests(SimpleTestCase):
    # bands 0–50, 50–100, 100–200 and from 200 g: anchors at 25, 75, 150 and 200 g
    BANDS = ((F(0), F(50)), (F(50), F(100)), (F(100), F(200)), (F(200), None))
    VALUES = [F('0.9'), F(1), F('1.2'), F('1.5')]

    def anchors(self, values):
        return tuple((anchor(low, high), value) for (low, high), value in zip(self.BANDS, values))

    def test_a_bands_value_sits_at_its_middle_and_an_open_band_at_its_lower_weight(self):
        self.assertEqual([anchor(low, high) for low, high in self.BANDS], [25, 75, 150, 200])
        found = self.anchors(self.VALUES)
        for at, value in found:
            self.assertEqual(interpolate(found, at), value)

    def test_it_is_linear_between_two_anchors_by_hand(self):
        found = self.anchors(self.VALUES)
        self.assertEqual(interpolate(found, F(50)), F('0.95'))      # the edge of the first two bands: half way 0.9 → 1.0
        self.assertEqual(interpolate(found, F(100)), 1 + F('0.2') * 25 / 75)   # 25 g of the 75 g from 75 to 150
        self.assertEqual(interpolate(found, F(175)), F('1.35'))     # half way 1.2 → 1.5
        self.assertEqual(interpolate(((D(50), D('1.00')), (D(150), D('1.50'))), D(100)), D('1.25'))

    def test_it_is_constant_before_the_first_anchor_and_after_the_last(self):
        found = self.anchors(self.VALUES)
        for at in (F(0), F(1, 100), F(24), F(25)):
            self.assertEqual(interpolate(found, at), F('0.9'))
        for at in (F(200), F(201), F(10**6)):
            self.assertEqual(interpolate(found, at), F('1.5'))

    def test_one_band_is_one_value_at_every_weight(self):
        for value, at in product(FCRS, (F(0), F(1), F(50), F(10**5))):
            self.assertEqual(interpolate(((F(0), value),), at), value)
            self.assertEqual(interpolate(((anchor(F(10), F(90)), value),), at), value)

    def test_equal_neighbours_give_that_value_everywhere_between_them(self):
        found = ((D(25), D('1.00')), (D(75), D('1.00')), (D(100), D('1.00')))
        for tenths in range(0, 1200):
            self.assertEqual(interpolate(found, D(tenths) / 10), D('1.00'))

    def test_no_jump_anywhere_and_never_outside_the_neighbours_for_every_order_of_values(self):
        # every arrangement of four values over the four bands, walked in steps of 0.5 g: two neighbouring weights
        # never differ by more than the steepest segment allows, so a band's edge is no step
        grid = [F(n, 2) for n in range(0, 501)]
        for values in product(self.VALUES, repeat=4):
            found = self.anchors(values)
            steepest = max(abs(high - low) / (high_at - low_at)
                           for (low_at, low), (high_at, high) in zip(found, found[1:]))
            read = [interpolate(found, at) for at in grid]
            for at, before, after in zip(grid, read, read[1:]):
                self.assertLessEqual(abs(after - before), steepest * F(1, 2), (values, at))
            self.assertGreaterEqual(min(read), min(values))
            self.assertLessEqual(max(read), max(values))
            for edge in (F(50), F(100), F(200)):                 # the bands' edges: both sides agree
                self.assertLess(abs(interpolate(found, edge - F(1, 10**9)) - interpolate(found, edge + F(1, 10**9))),
                                F(1, 10**6))

    def test_rising_values_rise_and_falling_values_fall(self):
        grid = [F(n) for n in range(0, 260)]
        rising = [interpolate(self.anchors(self.VALUES), at) for at in grid]
        self.assertEqual(rising, sorted(rising))
        falling = [interpolate(self.anchors(self.VALUES[::-1]), at) for at in grid]
        self.assertEqual(falling, sorted(falling, reverse=True))


class MortalityTests(SimpleTestCase):
    def test_a_month_takes_exactly_its_share(self):
        for percent in ('0.5', '1', '2.5', '10', '30'):
            alive = D(10000)
            for _day in range(growth.MONTH_DAYS):
                alive *= survival_a_day(D(percent))
            self.assertAlmostEqual(alive, 10000 * (1 - D(percent) / 100), places=15)

    def test_none_and_zero_take_nothing(self):
        self.assertEqual(survival_a_day(None), 1)
        self.assertEqual(survival_a_day(D(0)), 1)

    def test_it_lowers_the_count_and_the_feed_never_the_average_weight(self):
        for sfr, fcr, uneaten, mortality in product(('0.5', '1.3'), ('0.9', '1.2'), ('0', '15'), ('1', '5', '30')):
            plain = curve(START, D(50), D(10000), None, 60, constant(sfr=sfr, fcr=fcr, uneaten=uneaten))
            dying = curve(START, D(50), D(10000), None, 60,
                          constant(sfr=sfr, fcr=fcr, uneaten=uneaten, mortality=mortality))
            self.assertEqual([point.weight_g for point in dying.points], [point.weight_g for point in plain.points])
            counts = [dying.start_fish, *(point.fish for point in dying.points)]
            self.assertEqual(counts, sorted(counts, reverse=True))
            self.assertLess(dying.end_fish, plain.end_fish)
            self.assertEqual(plain.end_fish, 10000)
            self.assertEqual(dying.points[0].feed_kg, plain.points[0].feed_kg)      # the first day feeds every fish
            for one, other in zip(dying.points[1:], plain.points[1:]):
                self.assertLess(one.feed_kg, other.feed_kg)
                self.assertLess(one.biomass_kg, other.biomass_kg)


class CurveTests(SimpleTestCase):
    def test_one_per_cent_a_day_at_fcr_one_by_hand(self):
        # 50 g at 1 % a day, FCR 1.00, nothing uneaten: 50 × 1.01^n. 50 × 1.01^10 = 55.23 g ≥ 55 g on the tenth day.
        found = curve(START, D(50), D(10000), D(55), 730, constant())
        self.assertEqual(found.reached, START + timedelta(days=10))
        self.assertEqual(len(found.points), 10)
        self.assertEqual(found.points[0].weight_g, D('50.5'))
        self.assertEqual(found.points[1].weight_g, D('51.005'))
        self.assertEqual(found.end_g, D(50) * D('1.01') ** 10)
        self.assertEqual(found.points[0].feed_kg, D(5))                 # 10,000 fish × 0.5 g
        self.assertEqual(found.points[0].biomass_kg, D(505))
        self.assertEqual(found.economic_fcr, D(1))
        self.assertEqual(found.feed_kg, found.growth_kg)

    def test_a_fifth_uneaten_by_hand(self):
        # 60.8 g, 10,000 fish, 1 % a day, FCR 1.00, 20 % uneaten: each day 0.8 % growth.
        # day 1: fed 0.608 g a fish (6.08 kg), eaten 0.4864 → 61.2864 g
        # day 2: fed 0.612864 (6.12864 kg), eaten 0.4902912 → 61.7766912 g
        # day 3: fed 0.617766912 (6.17766912 kg), eaten 0.4942135296 → 62.2709047296 g ≥ 62 g
        found = curve(START, D('60.8'), D(10000), D(62), 730, constant(uneaten='20'))
        self.assertEqual(found.reached, START + timedelta(days=3))
        self.assertEqual([point.weight_g for point in found.points],
                         [D('61.2864'), D('61.7766912'), D('62.2709047296')])
        self.assertEqual([point.feed_kg for point in found.points], [D('6.08'), D('6.12864'), D('6.17766912')])
        self.assertEqual([point.feed_to_date_kg for point in found.points],
                         [D('6.08'), D('12.20864'), D('18.38630912')])
        self.assertEqual(found.feed_kg, D('18.38630912'))
        self.assertEqual(found.eaten_kg, D('14.709047296'))
        self.assertEqual(found.uneaten_kg, D('3.677261824'))
        self.assertEqual(found.economic_fcr, D('1.25'))                 # 1.00 ÷ 0.8

    def test_the_totals_add_up_on_every_curve(self):
        for sfr, fcr, uneaten, mortality in product(('0.4', '1', '2.5'), ('0.8', '1', '1.4'), ('0', '10', '50'),
                                                    (None, '3')):
            found = curve(START, D(100), D(2000), None, 45,
                          constant(sfr=sfr, fcr=fcr, uneaten=uneaten, mortality=mortality))
            self.assertEqual(len(found.points), 45)
            self.assertTrue(found.horizon)
            self.assertAlmostEqual(found.eaten_kg + found.uneaten_kg, found.feed_kg, places=18)
            self.assertAlmostEqual(found.growth_kg * D(fcr), found.eaten_kg, places=18)
            self.assertEqual(found.points[-1].feed_to_date_kg, found.feed_kg)
            self.assertAlmostEqual(found.economic_fcr, economic_fcr(D(fcr), D(uneaten)), places=18)
            weights = [found.start_g, *(point.weight_g for point in found.points)]
            self.assertEqual(weights, sorted(weights))                  # the weight never falls
            for before, point in zip(weights, found.points):
                self.assertAlmostEqual(point.weight_g - before,
                                       before * D(sfr) / 100 * (100 - D(uneaten)) / 100 / D(fcr), places=20)

    def test_the_weight_never_falls_even_when_the_terms_change_every_day(self):
        cycle = [terms(sfr, fcr, uneaten) for sfr, fcr, uneaten in product(('0', '0.7', '3'), ('0.6', '2.9'),
                                                                           ('0', '50'))]
        found = curve(START, D(10), D(500), None, 200, lambda day, weight: cycle[(day - START).days % len(cycle)])
        weights = [found.start_g, *(point.weight_g for point in found.points)]
        self.assertEqual(weights, sorted(weights))

    def test_a_fasting_day_gives_no_feed_and_no_growth_and_the_day_still_passes(self):
        def terms_of(day, weight):
            return terms(fasting=True) if (day - START).days in (2, 3) else terms()
        found = curve(START, D(50), D(10000), D(55), 730, terms_of)
        self.assertEqual(found.reached, START + timedelta(days=12))     # ten growing days and the two of the fast
        fast = found.points[1]
        self.assertEqual((fast.fasting, fast.feed_kg, fast.eaten_kg, fast.growth_kg, fast.fcr),
                         (True, 0, 0, 0, None))
        self.assertEqual(fast.weight_g, found.points[0].weight_g)

    def test_it_stops_with_the_reason_and_keeps_the_days_before(self):
        def terms_of(day, weight):
            return Stop('outside') if weight >= D(51) else terms()
        found = curve(START, D(50), D(100), D(60), 730, terms_of)
        self.assertEqual((found.reached, found.why, found.horizon), (None, 'outside', False))
        self.assertEqual([point.weight_g for point in found.points], [D('50.5'), D('51.005')])

    def test_a_target_already_reached_is_reached_today_with_no_day_planned(self):
        found = curve(START, D(60), D(100), D(55), 730, constant())
        self.assertEqual((found.reached, found.points, found.feed_kg, found.economic_fcr), (START, (), 0, None))

    def test_the_horizon_is_the_last_day_it_looks_at(self):
        # 50 × 1.01^10 ≥ 55: reached on the last day of a ten-day horizon, not within nine
        self.assertEqual(curve(START, D(50), D(100), D(55), 10, constant()).reached, START + timedelta(days=10))
        short = curve(START, D(50), D(100), D(55), 9, constant())
        self.assertEqual((short.reached, short.horizon, len(short.points)), (None, True, 9))
        self.assertEqual(curve(START, D(50), D(100), None, 0, constant()).points, ())

    def test_the_fcr_read_at_the_weight_reached_moves_without_a_jump_along_a_curve(self):
        anchors = ((D(50), D('1.00')), (D(150), D('1.50')))             # bands 0–100 g at 1.00 and 100–200 g at 1.50

        def terms_of(day, weight):
            return terms(fcr=str(interpolate(anchors, weight)))
        found = curve(START, D(95), D(100), D(110), 730, terms_of)
        fcrs = [point.fcr for point in found.points]
        self.assertEqual(fcrs, sorted(fcrs))
        for before, after in zip(fcrs, fcrs[1:]):
            self.assertLess(after - before, D('0.01'))                  # a step table jumps 0.50 at 100 g
        self.assertEqual(found.points[0].fcr, D('1.225'))               # at 95 g: 1.00 + 0.50 × 45 ÷ 100


class BetweenBandRuleTests(SimpleTestCase):
    """The table's three quantities over the weight under a protocol's two rules (ration.Table; owner decisions 13 and
    14): a step at the band's edge is the band's own value to the last digit, as every table was read before; smooth has
    no jump at any band's edge for the FCR, the uneaten share and the SFR at every temperature; and the values the
    protocol's page shows (Table.used) are those very readings."""
    COLUMNS = (D('8'), D('12'), D('16'))
    # bands 0–50, 50–100, 100–400 and from 400 g: FCR, uneaten share (%), SFR at 8, 12 and 16 °C
    ROWS = (((0, 50), '0.90', '5', ('2.0', '3.0', '3.6')), ((50, 100), '1.00', '8', ('1.5', '2.2', '2.6')),
            ((100, 400), '1.15', '12', ('1.0', '1.4', '1.8')), ((400, None), '1.30', '20', ('0.6', '0.9', '1.1')))
    TEMPERATURES = (D('8'), D('9.3'), D('12'), D('14.75'), D('16'))

    def table(self, between):
        from types import SimpleNamespace

        from ..feeding.ration import Band, Cell, Table
        protocol = SimpleNamespace(expected_fcr=D('1.00'), uneaten_pct=None, mortality_pct_month=None,
                                   fcr_between=between, uneaten_between=between, sfr_between=between)
        return Table(protocol, tuple(
            Band(index, D(low), None if high is None else D(high), 'GR-4', 4, D(fcr),
                 tuple(Cell(column, D(value)) for column, value in zip(self.COLUMNS, cells)), D(uneaten))
            for index, ((low, high), fcr, uneaten, cells) in enumerate(self.ROWS)))

    def readings(self, table, weight):
        return [table.fcr_at(weight), table.uneaten_at(weight),
                *(table.sfr_at(weight, temperature).value for temperature in self.TEMPERATURES)]

    def test_a_step_is_the_fishs_own_bands_value_to_the_last_digit(self):
        from ..feeding.ration import sfr_at
        table = self.table('step')
        for weight in (D(0), D('49.99'), D(50), D(75), D('99.9999'), D(100), D(250), D(400), D(5000)):
            band = table.band_for(weight)
            self.assertEqual(table.fcr_at(weight), band.fcr)
            self.assertEqual(table.uneaten_at(weight), band.uneaten_pct)
            for temperature in self.TEMPERATURES:               # main's reading: the band's row over the temperature
                self.assertEqual(table.sfr_at(weight, temperature).value, sfr_at(band.cells, temperature).value)

    def test_smooth_has_no_jump_at_any_bands_edge_for_the_three_quantities(self):
        table, step = self.table('smooth'), self.table('step')
        for edge in (D(50), D(100), D(400)):
            below, at = self.readings(table, edge - D('0.000001')), self.readings(table, edge)
            for one, other in zip(below, at):
                self.assertLess(abs(one - other), D('0.00001'), edge)
            # where the step table does jump: every quantity differs across the edge
            for one, other in zip(self.readings(step, edge - D('0.000001')), self.readings(step, edge)):
                self.assertGreater(abs(one - other), D('0.05'), edge)
        # walked in steps of 0.25 g from 0 to 600 g: no two neighbouring weights differ by more than the steepest
        # segment between two anchors allows (FCR 0.10 over 50 g, uneaten 3 over 50 g, SFR 1.0 over 50 g)
        weights = [D(n) / 4 for n in range(0, 2401)]
        read = [self.readings(table, weight) for weight in weights]
        for before, after in zip(read, read[1:]):
            self.assertLessEqual(abs(after[0] - before[0]), D('0.10') / 50 / 4 + D('1e-20'))
            self.assertLessEqual(abs(after[1] - before[1]), D(3) / D(50) / 4 + D('1e-20'))
            for one, other in zip(before[2:], after[2:]):
                self.assertLessEqual(abs(other - one), D('1.0') / 50 / 4 + D('1e-20'))

    def test_smooth_is_the_entered_value_at_each_bands_anchor_and_in_between_by_hand(self):
        table = self.table('smooth')
        for (low, high), fcr, uneaten, cells in self.ROWS:
            at = anchor(D(low), None if high is None else D(high))
            self.assertEqual(self.readings(table, at)[:2], [D(fcr), D(uneaten)])
            self.assertEqual([table.sfr_at(at, column).value for column in self.COLUMNS], [D(cell) for cell in cells])
        # 50 g, the edge of the first two bands, half way between their middles (25 g and 75 g):
        # FCR (0.90 + 1.00) ÷ 2 = 0.95; uneaten (5 + 8) ÷ 2 = 6.5 %; SFR at 12 °C (3.0 + 2.2) ÷ 2 = 2.6 %
        self.assertEqual((table.fcr_at(D(50)), table.uneaten_at(D(50)), table.sfr_at(D(50), D(12)).value),
                         (D('0.95'), D('6.5'), D('2.6')))
        # both ways at once: 50 g at 10 °C. Each band at 10 °C: (2.0 + 3.0) ÷ 2 = 2.5 and (1.5 + 2.2) ÷ 2 = 1.85; half
        # way between the bands: 2.175 %
        self.assertEqual(table.sfr_at(D(50), D(10)).value, D('2.175'))
        # never outside the temperature columns, whatever the weight; never outside the bands
        self.assertIsNone(table.sfr_at(D(50), D('7.9')))
        self.assertIsNone(table.sfr_at(D(50), D('16.1')))
        self.assertIsNone(self.table('smooth').fcr_at(D(-1)))

    def test_the_values_the_page_shows_are_the_readings_the_plan_uses(self):
        for between in ('smooth', 'step'):
            table = self.table(between)
            shown = table.used()
            self.assertEqual([used.weight_g for used in shown], [0, 25, 50, 75, 100, 250, 400])
            self.assertEqual([used.anchor for used in shown], [False, True, False, True, False, True, True])
            for used in shown:
                self.assertEqual((used.fcr, used.uneaten_pct), (table.fcr_at(used.weight_g),
                                                               table.uneaten_at(used.weight_g)))
                self.assertEqual(list(used.sfr), [table.sfr_at(used.weight_g, column).value for column in self.COLUMNS])
            # a curve fed from the table reads the same FCR at a weight the page shows
            found = curve(START, D(250), D(100), None, 1, lambda day, weight: Terms(
                table.sfr_at(weight, D(12)).value, table.fcr_at(weight), table.uneaten_at(weight)))
            at_250 = next(used for used in shown if used.weight_g == 250)
            self.assertEqual((found.points[0].fcr, found.points[0].uneaten_pct), (at_250.fcr, at_250.uneaten_pct))
            self.assertEqual(found.points[0].feed_kg, D(250) * at_250.sfr[1] / 100 * 100 / 1000)

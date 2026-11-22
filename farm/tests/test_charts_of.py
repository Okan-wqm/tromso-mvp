"""The Deffeyes chart of many units at once (calculation.charts_of, what a wall of monitoring cards reads): each answer
is `chart_of(unit)`'s, figure for figure, from the water the caller already holds; the fish's limits are read once for
all the units, so the queries do not grow with them. And owner decision 1 (2026-11-12): the chart is drawn from the
LATEST values received; an input that is no longer fresh does not refuse it, it is named old, by the result and by the
chart's window."""
from datetime import timedelta
from decimal import Decimal as D

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from farm import withdrawal_gate

from ..models import SamplingPoint, Tank
from ..water import calculation, deffeyes, read, services
from .helpers import point_of, stock_fish
from .test_calculator import UnitWaterCase
from .test_stock import make_unit


def said(result):
    """Everything a chart or a refusal says, as plain values: what two reads of the same water must agree on."""
    if isinstance(result, calculation.Refusal):
        return {'kind': 'refusal', 'unit': result.unit.pk, 'point': result.point.pk if result.point else None,
                'missing': [str(label) for label in result.missing], 'points': [point.pk for point in result.points],
                'impossible': result.impossible, 'no_point': result.no_point, 'sensors_failed': result.sensors_failed}
    made = result.calculation
    inputs = [(item.field, str(item.label), item.value, item.assumed, item.old,
               None if item.reading is None else (item.reading.value, item.reading.at, str(item.reading.status),
                                                  str(item.reading.judged), item.reading.point.pk,
                                                  str(item.reading.origin)))
              for item in result.inputs]
    limits = {name: (offer.value, [row.pk for row in offer.rows]) for name, offer in result.limits.items()}
    return {'kind': 'chart', 'unit': result.unit.pk, 'point': result.point.pk, 'now': result.now, 'inputs': inputs,
            'limits': limits, 'analysis': made.analysis, 'chart': made.chart,
            'figure': deffeyes.figure(made.analysis, deffeyes.geometry(made.analysis)),
            'recipes': (str(made.recipes_note), made.recipes, made.steps), 'air': made.air_co2_mg_l,
            'assumed': result.assumed, 'absent': [str(label) for label in result.absent],
            'points': [point.pk for point in result.points], 'sensors_failed': result.sensors_failed,
            'old': [item.field for item in result.old]}


class ChartsOfCase(UnitWaterCase):
    def make(self, code, water_type='freshwater', **fields):
        unit = make_unit(code, self.hall, **fields)
        Tank.objects.filter(pk=unit.pk).update(water_type=water_type)
        unit = Tank.objects.select_related('production_department__site', 'system').get(pk=unit.pk)
        stock_fish(self.user, unit, 500, '50', 10, species=self.salmon)
        return unit

    def sample(self, point, hours=1, **values):
        return services.record(self.user, point=point, measured_at=timezone.now() - timedelta(hours=hours),
                               source='manual', values={name: D(str(value)) for name, value in values.items()})

    def loaded(self, units):
        """The units as a page's read gives them (the site and the system loaded)."""
        found = Tank.objects.select_related('production_department__site', 'system').in_bulk([unit.pk for unit in units])
        return [found[unit.pk] for unit in units]


class ChartsOfTests(ChartsOfCase):
    @withdrawal_gate.opened('test fixture: withdrawal inputs written straight in the database')
    def farm(self):
        """T-01 (drawn), a fresh-water unit with no salinity (assumed 0), a sea unit with none (refused), a unit without
        a middle point (refused), an impossible pH and alkalinity (refused), a unit whose temperature is its loop's, a
        unit with an old pH (drawn, said old) and a unit nobody has measured (refused)."""
        fresh = self.make('T-02')
        self.sample(point_of(fresh), temperature_c=11, ph='7.3', alkalinity_mg_l=80)
        sea = self.make('S-01', 'saltwater')
        self.sample(point_of(sea), temperature_c=8, ph='7.9', alkalinity_mg_l=110)
        pointless = self.make('T-03')
        self.sample(point_of(pointless, 'inlet'), temperature_c=9, ph='7.2', alkalinity_mg_l=90, salinity_ppt='0.2')
        SamplingPoint.objects.filter(unit=pointless, kind='middle').update(is_active=False)
        odd = self.make('T-04')
        self.sample(point_of(odd), temperature_c=10, ph=11, alkalinity_mg_l=3, salinity_ppt='0.2')
        looped = self.make('T-05')
        Tank.objects.filter(pk=looped.pk).update(system=self.loop)
        self.sample(point_of(self.loop), temperature_c=13)
        self.sample(point_of(looped), ph='7.2', alkalinity_mg_l=90, salinity_ppt='0.2')
        old = self.make('T-06')
        self.sample(point_of(old), hours=1, temperature_c=10, alkalinity_mg_l=90, salinity_ppt='0.2')
        self.sample(point_of(old), hours=100, ph='7.4', tan_mg_l='0.5')            # a pH says something for 72 hours
        bare = self.make('T-07')
        point_of(bare)
        return self.loaded([self.unit, fresh, sea, pointless, odd, looped, old, bare])

    def test_each_chart_is_chart_of_the_unit_figure_for_figure(self):
        units = self.farm()
        now = timezone.now()
        bulk = calculation.charts_of(units, read.points_water(units, now), now, draw=True)
        self.assertEqual(list(bulk), [unit.pk for unit in units])
        kinds = []
        for unit in units:
            with self.subTest(unit=unit.code):
                single = calculation.chart_of(unit, now=now)
                self.assertEqual(said(bulk[unit.pk]), said(single))
                kinds.append(type(single).__name__ + (':old' if getattr(single, 'old', ()) else ''))
        # (the farm holds every answer there is, so the comparison above is not of refusals alone)
        self.assertEqual(kinds, ['UnitChart', 'UnitChart', 'Refusal', 'Refusal', 'Refusal', 'UnitChart',
                                 'UnitChart:old', 'Refusal'])

    def test_from_the_middle_points_water_alone_it_is_the_same_chart_and_names_only_that_point(self):
        units = self.farm()
        now = timezone.now()
        narrow = read.points_water(units, now, middle_only=[unit.pk for unit in units])
        bulk = calculation.charts_of(units, narrow, now, draw=True)
        for unit in units:
            with self.subTest(unit=unit.code):
                single, mine = said(calculation.chart_of(unit, now=now)), said(bulk[unit.pk])
                self.assertLessEqual(len(mine.pop('points')), 1)
                single.pop('points')
                self.assertEqual(mine, single)

    def test_without_the_svg_parts_everything_else_is_the_same(self):
        units = self.loaded([self.unit])
        now = timezone.now()
        water = read.points_water(units, now)
        drawn = calculation.charts_of(units, water, now, draw=True)[self.unit.pk]
        bare = calculation.charts_of(units, water, now)[self.unit.pk]
        self.assertIsNone(bare.calculation.chart)
        self.assertIsNotNone(drawn.calculation.chart)
        self.assertEqual((bare.calculation.analysis, bare.inputs, bare.limits, bare.assumed, bare.absent),
                         (drawn.calculation.analysis, drawn.inputs, drawn.limits, drawn.assumed, drawn.absent))

    def test_no_value_is_read_again_and_the_queries_do_not_grow_with_the_units(self):
        units = self.farm()
        now = timezone.now()
        water = read.points_water(units, now)

        def count(some):
            with CaptureQueriesContext(connection) as log:
                calculation.charts_of(some, water, now)
            return log

        count(units[:2])                                            # warm what the first call loads once
        two, eight = count(units[:2]), count(units)
        self.assertEqual(len(two), len(eight))
        self.assertLessEqual(len(eight), 6, [query['sql'][:90] for query in eight])
        sql = ' '.join(query['sql'] for query in eight)
        self.assertNotIn(read.WaterMeasurement._meta.db_table, sql)        # the water is the caller's: not read again
        self.assertNotIn(SamplingPoint._meta.db_table, sql)
        with CaptureQueriesContext(connection) as none:
            self.assertEqual(calculation.charts_of([], {}, now), {})
        self.assertEqual(len(none), 0)


class LimitsOfTests(ChartsOfCase):
    def test_the_limits_of_many_places_are_each_places_own(self):
        other = self.make('T-02')
        empty = make_unit('T-03', self.hall)
        places = self.loaded([self.unit, other, empty])
        found = read.limits_of(places)
        for place in places:
            with self.subTest(unit=place.code):
                self.assertEqual({code: [row.pk for row in rows] for code, rows in found[place.pk].items()},
                                 {code: [row.pk for row in rows] for code, rows in read.limits_now(place).items()})
        self.assertEqual(sorted(found[self.unit.pk]), ['alkalinity_mg_l', 'co2_mg_l', 'nh3_n_mg_l', 'ph'])
        self.assertEqual(found[empty.pk], {})                              # no fish: nothing to judge against
        point = point_of(self.unit, 'inlet')
        self.assertEqual(sorted(read.limits_of([point])[point.pk]), sorted(found[self.unit.pk]))

    def test_one_read_for_all_the_places(self):
        units = self.loaded([self.unit, *(self.make(f'T-{number:02d}') for number in range(2, 8))])
        read.limits_of(units[:2])
        with CaptureQueriesContext(connection) as two:
            read.limits_of(units[:2])
        with CaptureQueriesContext(connection) as seven:
            read.limits_of(units)
        self.assertEqual(len(two), len(seven))


class OldInputTests(ChartsOfCase):
    """Owner decision 1 (2026-11-12): "it should be drawn according to the latest data that came in"."""

    def setUp(self):
        super().setUp()
        self.old = self.make('T-06')
        self.sample(point_of(self.old), hours=1, temperature_c=10, alkalinity_mg_l=90, salinity_ppt='0.2')
        self.sample(point_of(self.old), hours=100, ph='7.4', tan_mg_l='0.5')       # a pH says something for 72 hours

    def test_an_old_input_does_not_refuse_the_chart_and_is_named(self):
        chart = calculation.chart_of(self.old)
        self.assertIsInstance(chart, calculation.UnitChart)
        self.assertEqual(chart.calculation.analysis.water.ph, 7.4)               # drawn from the latest value received
        self.assertEqual([item.field for item in chart.old], ['ph'])             # (a TAN says something for a week)
        self.assertEqual({item.field: item.old for item in chart.inputs},
                         {'temperature_c': False, 'ph': True, 'alkalinity_mg_l': False, 'salinity_ppt': False,
                          'tan_mg_l': False, 'altitude_m': False})
        self.assertEqual(calculation.chart_of(self.unit).old, ())                 # T-01: every input fresh

    def test_as_the_water_was_an_input_is_old_against_that_moment(self):
        then = timezone.now() - timedelta(hours=90)
        chart = calculation.chart_of(self.old, at=then)                           # the pH was 10 hours old then
        self.assertIsInstance(chart, calculation.Refusal)                        # (no temperature yet: refused, not old)
        self.sample(point_of(self.old), hours=95, temperature_c=9, alkalinity_mg_l=88, salinity_ppt='0.2')
        chart = calculation.chart_of(self.old, at=then)
        self.assertEqual(chart.old, ())

    def test_the_window_says_last_known_position_and_names_the_old_input(self):
        body = self.client.get(reverse('farm:water_unit_chart', args=[self.old.pk])).content.decode()
        self.assertIn('<svg class="deffeyes-chart"', body)
        self.assertIn('Last known position', body)
        notice = body[body.index('data-chart-old'):]
        notice = notice[:notice.index('</div>')]
        self.assertIn('pH (NBS scale)', notice)
        self.assertNotIn('Temperature', notice)
        self.assertIn('data-old>old<', body)                                      # and on the value's own row
        fresh = self.client.get(reverse('farm:water_unit_chart', args=[self.unit.pk])).content.decode()
        self.assertNotIn('Last known position', fresh)
        self.assertNotIn('data-old', fresh)

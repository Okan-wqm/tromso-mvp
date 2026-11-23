"""A place's water history (sensors/read.py `water_history`), the one reader behind Tank › Water and System › Water: every
quantity bound there and every parameter sampled there, each chart on the same window (one shared time axis), gaps
shown and never bridged, the NH₃-N worked out from each sample with its reason when it cannot be, and the fish's limits
as bands (the strictest bound of the species there; none where no row sets one, never an assumed band)."""
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from farm.models import System, WaterLimit
from farm.tests.helpers import make_species, point_of, stock_fish
from farm.tests.test_stock import make_unit
from farm.water import services as water_services

from sensors import bindings, read

from . import SensorsCase, make_channel
from .test_read import insert


class WaterHistoryTests(SensorsCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.ras = System.objects.create(name='RAS 1', code='R1', site=cls.site, production_department=cls.hall)
        cls.unit = make_unit('T-01', cls.hall, system=cls.ras)
        cls.empty = make_unit('T-09', cls.hall)
        cls.mid = point_of(cls.unit)
        cls.now = timezone.now().replace(microsecond=0)
        cls.start = cls.now - timedelta(hours=6)
        bindings.move(cls.user, cls.channel, point=cls.mid, at=cls.start - timedelta(days=1))   # temperature

    def sample(self, hours, **values):
        return water_services.record(self.user, point=self.mid, measured_at=self.now - timedelta(hours=hours),
                                     source='manual', values={key: Decimal(value) for key, value in values.items()})

    def test_every_bound_quantity_and_every_sampled_parameter_on_one_window(self):
        oxygen = make_channel(self.device, 'oxygen_mg_l', code='O2')
        bindings.move(self.user, oxygen, point=self.mid, at=self.start - timedelta(days=1))
        self.sample(2, ph='7.1')
        found = read.water_history(self.unit, self.start, self.now, now=self.now)
        codes = [chart.quantity.code for chart in found.charts]
        self.assertEqual(sorted(codes), ['oxygen_mg_l', 'ph', 'temperature_c'])
        self.assertEqual(codes, [code for code in read.quantities.CODES if code in codes])   # the catalogue's order
        self.assertEqual({(chart.start, chart.end) for chart in found.charts}, {(self.start, self.now)})

    def test_a_place_with_nothing_has_no_chart_never_an_ok_one(self):
        found = read.water_history(self.empty, self.start, self.now, now=self.now)
        self.assertEqual((found.charts, found.worked, found.bands), ([], {}, {}))

    def test_a_gap_is_shown_and_never_bridged(self):
        insert(self.channel.channel_no, [(self.start + timedelta(minutes=minute), 9.0) for minute in range(0, 30)]
               + [(self.start + timedelta(hours=3, minutes=minute), 9.5) for minute in range(0, 30)])
        found = read.water_history(self.unit, self.start, self.now, now=self.now, max_points=1500)
        chart = next(chart for chart in found.charts if chart.quantity.code == 'temperature_c')
        self.assertIn((self.start + timedelta(minutes=29), self.start + timedelta(hours=3)), chart.gaps)
        self.assertFalse([bucket for bucket in chart.buckets
                          if self.start + timedelta(minutes=30) <= bucket.start < self.start + timedelta(hours=3)])

    def test_the_nh3_of_each_sample_is_worked_out_or_says_why_not(self):
        self.sample(4, tan_mg_l='0.500', ph='7.20', temperature_c='12.0')
        self.sample(1, tan_mg_l='0.400')                                   # no pH of its own: not worked out
        found = read.water_history(self.unit, self.start, self.now, now=self.now)
        first, second = found.worked['nh3_n_mg_l']
        self.assertEqual(first.at, self.now - timedelta(hours=4))          # oldest first, as a chart draws
        self.assertGreater(first.value, 0)
        self.assertIsNone(second.value)
        self.assertTrue(second.note)
        self.assertNotIn('nh3_n_mg_l', [chart.quantity.code for chart in found.charts])   # worked out, never measured

    def test_a_voided_sample_is_not_drawn_as_worked_out(self):
        sample = self.sample(2, tan_mg_l='0.500', ph='7.20', temperature_c='12.0')
        water_services.void(self.user, sample, 'Wrong unit')
        self.assertEqual(read.water_history(self.unit, self.start, self.now, now=self.now).worked, {})

    def test_the_bands_are_the_strictest_of_the_fish_there(self):
        trout = make_species('TRO', 'Rainbow trout', 'Oncorhynchus mykiss', local_name='Regnbueørret')
        salmon = make_species()
        stock_fish(self.user, self.unit, 500, species=salmon)
        stock_fish(self.user, self.unit, 500, species=trout)
        WaterLimit.objects.create(species=salmon, parameter='oxygen_mg_l', water_type='any',
                                  critical_low=Decimal(6), warning_low=Decimal(7))
        WaterLimit.objects.create(species=trout, parameter='oxygen_mg_l', water_type='any',
                                  critical_low=Decimal(5), warning_low=Decimal(8), warning_high=Decimal(14))
        found = read.water_history(self.unit, self.start, self.now, now=self.now)
        self.assertEqual(found.bands, {'oxygen_mg_l': {'critical_low': 6.0, 'warning_low': 8.0, 'warning_high': 14.0}})

    def test_a_window_that_ends_before_it_starts_is_refused(self):
        with self.assertRaises(ValueError):
            read.water_history(self.unit, self.now, self.now)

"""The manual and lab samples a place's chart draws beside its sensors (sensors.read.water_history) are read through the
water's own reader (farm.water.read.measured, sampled), never by the sensors' code from the table (the data-layering
audit, rule R): live samples only, inside the window, one query for which parameters were sampled."""
from django.test.utils import CaptureQueriesContext
from django.db import connection

from ..water import read, services
from .test_water import WaterTestCase


class SampledTests(WaterTestCase):
    def test_measured_lists_the_live_values_of_one_parameter_in_the_window_oldest_first(self):
        self.sample(hours=5, oxygen_mg_l='8.10')
        self.sample(hours=3, oxygen_mg_l='7.20', ph='7.1')
        self.sample(hours=2, ph='7.0')                                     # no oxygen in it
        voided = self.sample(hours=1, oxygen_mg_l='4.00')
        services.void(self.user, voided, 'Probe not calibrated')
        self.sample(hours=30, oxygen_mg_l='9.00')                          # before the window
        found = read.measured([self.mid1], 'oxygen_mg_l', self.ago(hours=24), self.now)
        self.assertEqual([(at, str(value), source) for at, value, source in found],
                         [(self.ago(hours=5), '8.10', 'manual'), (self.ago(hours=3), '7.20', 'manual')])
        self.assertEqual(read.measured([self.mid2], 'oxygen_mg_l', self.ago(hours=24), self.now), [])

    def test_sampled_names_the_parameters_with_a_live_value_in_the_window_in_the_order_asked_in_one_query(self):
        self.sample(hours=3, ph='7.1')
        voided = self.sample(hours=2, temperature_c='9.5')
        services.void(self.user, voided, 'Wrong unit')
        self.sample(hours=30, oxygen_mg_l='9.00')                          # before the window
        self.sample(hours=1, oxygen_mg_l='8.00', point=self.t2)           # another place
        with CaptureQueriesContext(connection) as queries:
            found = read.sampled([self.mid1], self.ago(hours=24), self.now, ('temperature_c', 'ph', 'oxygen_mg_l'))
        self.assertEqual(found, ['ph'])
        self.assertEqual(len(queries), 1)
        self.assertEqual(read.sampled([], self.ago(hours=24), self.now, ('ph',)), [])

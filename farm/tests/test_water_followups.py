"""Owner decisions of 2026-11-08 after the second cross review of wip/fix-monitoring:

- A11: the ration is ALWAYS worked out from the newest temperature, however old (no 7-day cut-off); a stale one says so,
  "Based on the temperature from dd.mm.yyyy HH:MM (5 days old)". The one explicit exception to A9.3.
- The withdrawal's degree-days take, per day, the LOWEST daily mean among the unit's own-water points (middle, depth,
  outlets, drain; never the inlet), else its system's loop: the conservative side, a longer withdrawal.
- A "Judged as" note only where a conversion was made.
- A system without a loop point: its sensors stand in for the ration as they do on the water page."""
from decimal import Decimal


from .. import withdrawal_gate
from ..feeding.temperature import temperature_for
from ..models import SamplingPoint
from ..models.water_point import local_time
from ..stock.dates import local_today
from ..water import read
from ..water.degree_days import Temperatures
from ..water.evaluate import Status
from .helpers import point_of
from .test_water_sources import SourcesCase

D = Decimal


class RationTemperatureTests(SourcesCase):
    def test_the_newest_temperature_however_old_gives_the_ration_and_says_its_age(self):
        old = self.sample(hours=24 * 12, temperature_c='8.5')             # 12 days: beyond the old 7-day cut-off
        found = temperature_for([self.t1], self.now)[self.t1.pk]
        self.assertIsNotNone(found, 'A11: a ration from the newest temperature, however old')
        self.assertEqual((found.value_c, found.fresh), (D('8.5'), False))
        when = local_time(old.measured_at, self.mid1).strftime('%d.%m.%Y %H:%M')
        self.assertEqual(found.warning, f'Based on the temperature from {when} (12 days old)')

    def test_a_fresh_temperature_has_no_warning(self):
        self.sample(hours=2, temperature_c='9.0')
        self.assertEqual(temperature_for([self.t1], self.now)[self.t1.pk].warning, '')


class DegreeDayTests(SourcesCase):
    def test_the_lowest_daily_mean_of_the_units_own_water_and_never_the_inlet(self):
        today = local_today(self.t1)
        drain, inlet = point_of(self.t1, 'bottom_drain'), point_of(self.t1, 'inlet')
        self.sample(hours=0, temperature_c='9')
        self.sample(point=drain, hours=0, temperature_c='7')              # colder: the conservative side
        self.sample(point=inlet, hours=0, temperature_c='5')              # the supply stream: never the unit's
        self.sample(point=self.loop, hours=0, temperature_c='4')
        temperatures = Temperatures([self.t1, self.t2], today, today)
        self.assertEqual(temperatures.of(self.t1.pk, today).value, D(7))
        self.assertEqual(temperatures.of(self.t2.pk, today).value, D(4))        # nothing of its own: its loop's


class JudgedAsTests(SourcesCase):
    def test_no_judged_as_note_when_the_other_unit_was_measured_on_the_same_sample(self):
        self.stock()
        self.limit('oxygen_mg_l', critical_low=6)
        self.sample(hours=1, oxygen_mg_l='9', oxygen_saturation_pct='85', temperature_c='9', salinity_ppt='0')
        percent = self.latest().get('oxygen_saturation_pct')
        self.assertEqual(percent.judged, Status.OK)
        self.assertNotIn('Judged as', percent.note)

    def test_a_worked_out_value_says_it_was_worked_out_and_not_judged_as_its_own_entry(self):
        self.stock()
        self.limit('oxygen_mg_l', critical_low=6)
        self.sample(hours=1, oxygen_mg_l='9', temperature_c='9', salinity_ppt='0')
        percent = self.latest().get('oxygen_saturation_pct')                # worked out from the entered 9 mg/L
        self.assertTrue(percent.derived)
        self.assertNotIn('Judged as', percent.note)


class SystemWithoutLoopTests(SourcesCase):
    @withdrawal_gate.opened('test fixture: water samples and points written straight in the database')
    def test_the_ration_takes_the_system_sensor_as_the_water_page_does(self):
        SamplingPoint.all_objects.filter(pk=self.loop.pk).update(is_active=False)
        self.on(self.ras, self.value('temperature_c', 11.0, seconds=30))
        water = read.unit_water([self.t1], now=self.now)[self.t1.pk].get('temperature_c')
        self.assertEqual((water.value, water.origin), (D('11.0'), read.Origin.SYSTEM_SENSOR))
        ration = temperature_for([self.t1], self.now)[self.t1.pk]
        self.assertIsNotNone(ration, 'the system sensor stands in for the ration too')
        self.assertEqual((ration.value_c, ration.via, ration.fresh), (D('11.0'), read.SYSTEM, True))

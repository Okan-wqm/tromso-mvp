"""A pH scale per sensor pH channel (owner decision 1 of 2026-11-17; the water-chemistry audit of 2026-11-19, F1).

A probe calibrated with TRIS (ISFET and spectrophotometric sea-water sensors are) reports on the total scale. Taken as
NBS, its pH read 0.10 to 0.14 low in sea water and the judged NH₃ 5 to 16 % below the exact value: the unsafe side. A
pH channel now says its scale (`sensors.Channel.ph_scale`, NBS by default) and a value on another scale is put on the
NBS scale where the water is read (farm/water/read.py), exactly as a typed sample is (`read.ph_on_nbs`, the one
conversion `services.on_nbs` takes too): with a fresh temperature from the sensors (else the place's sample temperature
fresh at the pH's time, as the oxygen's other unit takes it) and the salinity of the same moment, for sea water of 5 ‰
or more only. Otherwise the pH and everything worked out from it cannot be evaluated, and the reason is said: the
unconverted number is never shown nor used.

A channel whose scale changed (`ph_scale_from`, set when it changes): what it measured before is on a scale not known
any more (a probe recalibrated, or a setting put right), so those values are used nowhere, neither on the old scale
nor on the new: they cannot be evaluated, said so, until the probe's next value."""
from datetime import timedelta
from decimal import Decimal as D
from unittest import mock

from ..models import Tank
from ..water import native, read, services, sources
from ..water.evaluate import Status
from .helpers import point_of
from .test_ph_scale import SeaTestCase
from .test_stock import make_unit
from .test_water_sources import FakeProvider

TOTAL = 'total'
# A reason the chemistry core gives for a water it cannot work out, stood in (the review of the water-chemistry audit,
# C5): whatever water it refuses, the pH says the core's reason, never "not sea water".
CORE_REFUSED = 'the water is outside what the constants hold for'


def core_refuses_the_conversion():
    """The core refuses the water a pH is put on the NBS scale in (read.ph_on_nbs: a temperature, a salinity and the
    water's origin alone), and works every other water out as it does."""
    real = read.chemistry.water_equilibria

    def equilibria(*args, **kwargs):
        if len(args) == 2 and set(kwargs) == {'water_origin'}:
            raise ValueError(CORE_REFUSED)
        return real(*args, **kwargs)
    return mock.patch.object(read.chemistry, 'water_equilibria', side_effect=equilibria)


class SensorPhCase(SeaTestCase):
    def setUp(self):
        super().setUp()
        self.provider = FakeProvider()
        sources.register(self.provider)
        self.addCleanup(sources.unregister, self.provider)
        # A second sea unit, where the same water is typed as a sample.
        self.typed = make_unit('S-03', self.hall)
        Tank.objects.filter(pk=self.typed.pk).update(water_type='saltwater', water_origin='seawater')
        self.typed.refresh_from_db()
        self.typed_point = point_of(self.typed)

    def value(self, code, value, seconds=10, fresh_for=900, channel_no=1, ph_scale='', ph_scale_from=None):
        return sources.SensorValue(code=code, value=value, at=self.now - timedelta(seconds=seconds),
                                   fresh_for=fresh_for, role=sources.PRIMARY, channel_no=channel_no,
                                   ph_scale=ph_scale, ph_scale_from=ph_scale_from)

    def on(self, point, *values):
        key = (sources.POINT, point.pk)
        for item in values:
            self.provider.now_values.setdefault(key, {}).setdefault(item.code, []).append(item)
            self.provider.history.setdefault(key, {}).setdefault(item.code, []).append(item)

    def probe(self, point, ph=7.95, scale=TOTAL, temperature=12.0, salinity=34.0, tan=1.0, **more):
        found = [self.value('ph', ph, channel_no=1, ph_scale=scale, **more)]
        if temperature is not None:
            found.append(self.value('temperature_c', temperature, channel_no=2))
        if salinity is not None:
            found.append(self.value('salinity_ppt', salinity, channel_no=3))
        if tan is not None:
            found.append(self.value('tan_mg_l', tan, channel_no=4))
        self.on(point, *found)

    def water(self, point):
        return read.latest([point], now=self.now)[point.pk]

    def limits(self, *units):
        for unit in units:
            self.stock(unit)
        self.limit('nh3_n_mg_l', warning_high='0.0050', critical_high='0.0500')
        self.limit('ph', warning_low='6.50', warning_high='8.50')


class TrisProbeTests(SensorPhCase):
    def test_a_tris_probe_is_judged_as_the_same_water_typed_as_a_total_scale_sample(self):
        """12 °C, S 34: the probe's 7.95 on the total scale gives the NBS pH, the NH₃-N and their judgements the same
        water typed as a total-scale sample gives."""
        self.limits(self.sea, self.typed)
        self.probe(self.sea_point)
        self.record(point=self.typed_point, ph='7.95', temperature_c='12.0', salinity_ppt='34.0', tan_mg_l='1.000')
        sensed, typed = self.water(self.sea_point), self.water(self.typed_point)
        for code in ('ph', 'nh3_n_mg_l', 'nh4_n_mg_l'):
            with self.subTest(code=code):
                self.assertIsNotNone(sensed.get(code).value)
                self.assertEqual(sensed.get(code).value, typed.get(code).value)
                self.assertEqual(sensed.get(code).judged_value, typed.get(code).judged_value)
                self.assertEqual(sensed.get(code).judged, typed.get(code).judged)
        self.assertEqual(sensed.get('ph').value, D('8.06'))
        self.assertEqual(sensed.get('nh3_n_mg_l').judged, Status.WARNING)
        # What was measured is said beside the NBS number, as for a typed sample.
        self.assertEqual(sensed.get('ph').measured, 'measured 7.95 on the total scale')
        self.assertIn('Measured 7.95 on the total scale by the sensor; put on the NBS scale by formula 4 with '
                      '12.0 °C and 34.0 ‰', sensed.get('ph').provenance)
        self.assertIn('The pH was measured on the total scale', sensed.get('nh3_n_mg_l').provenance)
        # Taken as NBS, as before, it read low: the NH₃-N of 7.95 itself is a quarter lower.
        eq = native.water_equilibria(12.0, 34.0, water_origin='seawater')
        self.assertLess(D(1) * D(eq.nh3_share(7.95)), sensed.get('nh3_n_mg_l').judged_value * D('0.8'))

    def test_the_conversion_is_the_typed_samples_one(self):
        """One conversion (read.ph_on_nbs): what the write path stores for a typed sample."""
        for ph, temperature, salinity in ((7.95, 12.0, 34.0), (7.60, 4.0, 30.0), (8.10, 0.5, 5.0)):
            with self.subTest(ph=ph, temperature=temperature, salinity=salinity):
                values = {'ph': D(str(ph)), 'temperature_c': D(str(temperature)), 'salinity_ppt': D(str(salinity))}
                stored, _measured = services.on_nbs(self.typed_point, values, TOTAL)
                found = read.ph_on_nbs(D(str(ph)), TOTAL, D(str(temperature)), D(str(salinity)), 'seawater')
                self.assertEqual((found.value, found.formula, found.refused), (stored['ph'], 4, ''))

    def test_the_seawater_and_free_scales_too(self):
        for scale in ('sws', 'free'):
            with self.subTest(scale=scale):
                self.provider.now_values.clear()
                self.provider.history.clear()
                self.probe(self.sea_point, scale=scale)
                values = {'ph': D('7.95'), 'temperature_c': D('12.0'), 'salinity_ppt': D('34.0')}
                stored, _measured = services.on_nbs(self.typed_point, values, scale)
                self.assertEqual(self.water(self.sea_point).get('ph').value, stored['ph'])

    def test_an_nbs_probe_is_as_before(self):
        """The default: a value as the probe sends it, nothing said, the NH₃ the NBS pH's."""
        self.limits(self.sea, self.typed)
        self.probe(self.sea_point, ph=8.08, scale='')
        self.record(point=self.typed_point, ph_scale='nbs', ph='8.08', temperature_c='12.0', salinity_ppt='34.0',
                    tan_mg_l='1.000')
        sensed, typed = self.water(self.sea_point), self.water(self.typed_point)
        self.assertEqual((sensed.get('ph').value, sensed.get('ph').measured, sensed.get('ph').provenance),
                         (D('8.08'), '', ''))
        self.assertEqual(sensed.get('nh3_n_mg_l').value, typed.get('nh3_n_mg_l').value)
        self.assertNotIn('The pH was measured on the', sensed.get('nh3_n_mg_l').provenance)


class NotConvertedTests(SensorPhCase):
    def assertUnevaluated(self, water, why):
        ph, nh3 = water.get('ph'), water.get('nh3_n_mg_l')
        self.assertIsNone(ph.value)                                     # never the unconverted number
        self.assertIn(why, ph.refused)
        self.assertEqual((ph.judged, ph.status), (Status.UNEVALUATED, Status.UNEVALUATED))
        self.assertIsNone(nh3.value)
        self.assertIn(why, nh3.refused)
        self.assertEqual(nh3.status, Status.UNEVALUATED)
        self.assertEqual(water.status, Status.UNEVALUATED)
        self.assertTrue(any(why in said for said in water.why_unevaluated))

    def test_a_fresh_water_unit(self):
        """A pH on the total scale is taken for sea water only: in a fresh-water unit (its salinity 0, measured or
        assumed) it cannot be evaluated, and says why."""
        self.limits(self.t1)
        self.probe(self.mid1, salinity=None)
        self.assertUnevaluated(self.water(self.mid1), 'sea water of 5 ‰ or more')
        self.provider.now_values.clear()
        self.probe(self.mid1, salinity=0.0)
        self.assertUnevaluated(self.water(self.mid1), 'sea water of 5 ‰ or more')

    def test_fresh_water_with_salt_added(self):
        self.stock(self.salted)
        self.limit('ph', warning_low='6.50', warning_high='8.50')
        self.probe(self.salted_point, salinity=20.0)
        ph = self.water(self.salted_point).get('ph')
        self.assertIsNone(ph.value)
        self.assertIn('not fresh water with salt added', ph.refused)

    def test_without_a_sensor_temperature_a_samples_fresh_at_its_time_converts_it(self):
        """The review of the audit, C2: as the oxygen's other unit, the replay and the trail, a probe without a fresh
        sensor temperature is put on the NBS scale with the place's sample temperature fresh at the pH's time, and says
        where that temperature came from. The same water typed as a total-scale sample gives the same pH."""
        self.limits(self.sea)
        sample = self.sample(point=self.sea_point, hours=1, temperature_c='12.0')
        self.probe(self.sea_point, temperature=None, tan=None)
        self.record(point=self.typed_point, ph='7.95', temperature_c='12.0', salinity_ppt='34.0')
        ph = self.water(self.sea_point).get('ph')
        self.assertEqual((ph.value, ph.refused, ph.judged), (self.water(self.typed_point).get('ph').value, '', 'ok'))
        self.assertEqual(ph.value, D('8.06'))
        self.assertEqual(ph.provenance, 'Measured 7.95 on the total scale by the sensor; put on the NBS scale by formula '
                                        f'4 with 12.0 °C and 34.0 ‰ of the same moment. The temperature is manual, '
                                        f'{sample.measured_at:%d.%m.%Y %H:%M}.')

    def test_without_a_temperature_fresh_at_its_time_it_cannot_be_evaluated(self):
        """No sensor temperature and the sample's no longer fresh (a temperature is fresh for 24 hours): refused, never
        converted with an old temperature nor shown unconverted."""
        self.limits(self.sea)
        self.sample(point=self.sea_point, hours=25, temperature_c='12.0')
        self.probe(self.sea_point, temperature=None)
        self.assertUnevaluated(self.water(self.sea_point), 'with a temperature of its moment, a sensor’s or a sample’s, '
                                                           'and none is fresh then')

    def test_without_a_salinity(self):
        self.limits(self.sea)
        self.probe(self.sea_point, salinity=None)
        self.assertUnevaluated(self.water(self.sea_point), 'the salinity')
        # A sample's fresh salinity at the point is the water's salinity (as for a sensor's TAN).
        self.sample(point=self.sea_point, hours=2, salinity_ppt='34.0')
        self.assertEqual(self.water(self.sea_point).get('ph').value, D('8.06'))

    def test_a_ph_no_longer_fresh_without_a_temperature_of_its_moment(self):
        """Owner decision of 2026-11-20: a pH no longer fresh is put on the NBS scale at its own moment (StaleTests);
        where no temperature was fresh then (the temperature probe only came later), it is a refusal as for a fresh one,
        never converted with today's temperature (PLAN A9.3). This test said "no longer fresh" before the decision."""
        self.limits(self.sea)
        self.on(self.sea_point, self.value('ph', 7.95, seconds=4000, ph_scale=TOTAL),
                self.value('temperature_c', 12.0, channel_no=2), self.value('salinity_ppt', 34.0, channel_no=3))
        ph = self.water(self.sea_point).get('ph')
        self.assertIsNone(ph.value)
        self.assertIn('with a temperature of its moment, a sensor’s or a sample’s, and none is fresh then', ph.refused)
        self.assertEqual(ph.status, Status.STALE)
        self.assertEqual(ph.judged, Status.UNEVALUATED)

    def test_a_water_the_core_cannot_work_out_says_the_cores_reason(self):
        """The review of the audit, C5: a sea water the core refuses is not "not sea water"; the pH, its NH₃ and a typed
        sample of that water say the core's own reason."""
        self.limits(self.sea)
        self.probe(self.sea_point)
        with core_refuses_the_conversion():
            water = self.water(self.sea_point)
            refused = self.refused(ph='7.95', temperature_c='12.0', salinity_ppt='34.0')
        self.assertUnevaluated(water, f'cannot work this water out: {CORE_REFUSED}')
        self.assertNotIn('sea water of 5 ‰', water.get('ph').refused)
        self.assertEqual(refused, {'ph_scale': [f'Cannot be worked out: {CORE_REFUSED}.']})
        # The same water and the same channel without the refusal: converted.
        self.assertEqual(self.water(self.sea_point).get('ph').value, D('8.06'))

    def test_a_typed_ph_still_counts_beside_it(self):
        """The newest fresh value is the probe's, which cannot be evaluated; a worse fresh sample still decides the
        status (the worst fresh value: never hidden behind it)."""
        self.limits(self.sea)
        self.record(ph_scale='nbs', ph='6.20', hours=1)
        self.probe(self.sea_point, temperature=None)
        ph = self.water(self.sea_point).get('ph')
        self.assertIsNone(ph.value)
        self.assertEqual(ph.status, Status.WARNING)


class StaleTests(SensorPhCase):
    """Owner decision of 2026-11-20 (the second review of the water-chemistry audit, question 3): a sensor pH on the
    total, seawater or free scale that is no longer fresh is treated as an NBS one. It is put on the NBS scale at its own
    moment, with the place's sensor temperature and salinity fresh THEN (each channel's value at that moment), and shown
    stale with its value and what the limits said of it; that its probe stopped is the channel's default "No fresh
    value" rule's to say (sensors/tests/test_fresh_rule.py), not a "cannot be evaluated"."""

    def past(self, point, *values):
        """Values the channels sent earlier: in their history (value_at), not their newest."""
        key = (sources.POINT, point.pk)
        for item in values:
            self.provider.history.setdefault(key, {}).setdefault(item.code, []).append(item)

    def stopped(self, scale=TOTAL, ph=7.95, temperature_then=4.0):
        """The pH probe stopped 4000 s ago (fresh for 900 s); the temperature and salinity probes go on sending, the
        temperature 12.0 now and `temperature_then` when the pH was measured."""
        self.on(self.sea_point, self.value('ph', ph, seconds=4000, ph_scale=scale),
                self.value('temperature_c', 12.0, channel_no=2), self.value('salinity_ppt', 34.0, channel_no=3))
        self.past(self.sea_point, self.value('temperature_c', temperature_then, seconds=4030, channel_no=2),
                  self.value('salinity_ppt', 34.0, seconds=4030, channel_no=3))
        return self.water(self.sea_point)

    def test_it_is_put_on_the_nbs_scale_with_the_temperature_of_its_own_moment_and_shown_stale(self):
        self.limits(self.sea)
        water = self.stopped()
        ph = water.get('ph')
        then = read.ph_on_nbs(D('7.95'), TOTAL, D('4.0'), D('34.0'), 'seawater').value
        now = read.ph_on_nbs(D('7.95'), TOTAL, D('12.0'), D('34.0'), 'seawater').value
        self.assertNotEqual(then, now)                          # the moment's temperature, never today's
        self.assertEqual((ph.value, ph.refused, ph.status, ph.judged, ph.unevaluated),
                         (then, '', Status.STALE, Status.OK, False))
        self.assertEqual(ph.measured, 'measured 7.95 on the total scale')
        self.assertIn('with 4.0 °C and 34.0 ‰ of the same moment', ph.provenance)
        self.assertEqual(water.why_unevaluated, [])

    def test_it_is_shown_as_the_same_probe_on_nbs_is(self):
        """One behaviour for every scale: the value, its status and its judgement, never "cannot be evaluated"."""
        self.limits(self.sea)
        tris = self.stopped().get('ph')
        self.provider.now_values.clear()
        self.provider.history.clear()
        nbs = self.stopped(scale='', ph=8.08).get('ph')
        self.assertEqual((tris.status, tris.judged, tris.unevaluated), (nbs.status, nbs.judged, nbs.unevaluated))
        self.assertEqual((nbs.value, nbs.status, nbs.judged), (D('8.08'), Status.STALE, Status.OK))

    def test_a_low_value_stays_what_the_limits_said_of_it(self):
        """A stale value judged a warning is shown as old and as what it was (F-244), the TRIS probe's as the NBS one's;
        the same water typed as a total-scale sample at that moment gives the same NBS value."""
        self.limits(self.sea)
        ph = self.stopped(ph=6.20).get('ph')
        self.record(point=self.typed_point, ph='6.20', temperature_c='4.0', salinity_ppt='34.0')
        self.assertEqual(ph.value, self.water(self.typed_point).get('ph').value)
        self.assertLess(ph.value, D('6.50'))
        self.assertEqual((ph.status, ph.judged, ph.old_alert), (Status.STALE, Status.WARNING, Status.WARNING))

    def test_without_a_salinity_of_its_moment_it_is_a_refusal_as_for_a_fresh_one(self):
        self.limits(self.sea)
        self.on(self.sea_point, self.value('ph', 7.95, seconds=4000, ph_scale=TOTAL),
                self.value('temperature_c', 12.0, channel_no=2))
        self.past(self.sea_point, self.value('temperature_c', 4.0, seconds=4030, channel_no=2))
        ph = self.water(self.sea_point).get('ph')
        self.assertIsNone(ph.value)
        self.assertIn('with the salinity of the same moment', ph.refused)
        self.assertEqual((ph.status, ph.judged), (Status.STALE, Status.UNEVALUATED))

    def test_the_water_at_a_past_moment_reads_it_the_same_way(self):
        """`latest(at=...)`: a pH stale at that moment is put on the NBS scale at its own moment too."""
        self.limits(self.sea)
        self.stopped()
        at = self.now - timedelta(seconds=2000)                 # the pH 2000 s old then, past its 900 s
        ph = read.latest([self.sea_point], at=at)[self.sea_point.pk].get('ph')
        self.assertEqual((ph.value, ph.status), (read.ph_on_nbs(D('7.95'), TOTAL, D('4.0'), D('34.0'),
                                                                'seawater').value, Status.STALE))


class ScaleChangedTests(SensorPhCase):
    """A channel's scale changed at `ph_scale_from`: its values from before are on a scale not known any more."""

    def test_a_value_from_before_the_change_is_used_nowhere(self):
        self.limits(self.sea)
        self.probe(self.sea_point, ph_scale_from=self.now - timedelta(seconds=5))     # the value is 10 s old
        water = self.water(self.sea_point)
        ph = water.get('ph')
        self.assertIsNone(ph.value)
        self.assertIn('measured before the channel’s pH scale was changed', ph.refused)
        self.assertEqual(ph.status, Status.UNEVALUATED)
        self.assertIsNone(water.get('nh3_n_mg_l').value)

    def test_the_next_value_is_converted_on_the_new_scale(self):
        self.probe(self.sea_point, ph_scale_from=self.now - timedelta(seconds=60))
        self.assertEqual(self.water(self.sea_point).get('ph').value, D('8.06'))

    def test_a_channel_put_back_on_nbs_neither_takes_its_older_values(self):
        self.probe(self.sea_point, ph=8.08, scale='', ph_scale_from=self.now - timedelta(seconds=5))
        ph = self.water(self.sea_point).get('ph')
        self.assertIsNone(ph.value)
        self.assertIn('measured before the channel’s pH scale was changed', ph.refused)
        self.provider.now_values.clear()
        self.provider.history.clear()
        self.probe(self.sea_point, ph=8.08, scale='', ph_scale_from=self.now - timedelta(seconds=60))
        self.assertEqual(self.water(self.sea_point).get('ph').value, D('8.08'))

    def test_the_water_as_it_was_at_a_past_moment_follows_the_same_rule(self):
        """`latest(at=...)` reads each sensor's value at the moment (value_at): converted as the live one."""
        self.probe(self.sea_point)
        at = self.now - timedelta(seconds=1)
        self.assertEqual(read.latest([self.sea_point], at=at)[self.sea_point.pk].get('ph').value, D('8.06'))

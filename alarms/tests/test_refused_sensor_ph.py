"""A sensor pH that cannot be put on the NBS scale is never silent for the alarms (the review of the water-chemistry audit
of 2026-11-19, M1). A pH channel on the total, seawater or free scale gives no value where its pH cannot be converted (no
temperature of its moment, no salinity, water that is not sea water, a value from before the channel's scale changed):
the page says "pH (NBS scale) cannot be evaluated: <why>". Before the fix the alarm system's "cannot be evaluated"
warning covered the NH₃ alone and a refused value judges no limit, so a TRIS probe reading a dangerously low pH raised no
alarm at all, where the same probe left on NBS raised the critical. The warning now covers every value the limits judge
(alarms/sources.py `REFUSABLE`). A pH that is only no longer fresh is no refusal (owner decision of 2026-11-20): it is put
on the NBS scale at its own moment and its probe's silence is its default "No fresh value" rule's (StoppedProbeTests).

Real sensor channels (the sensors app's provider, not a stand-in) and the real alarm engine; a sea unit whose salmon
have a pH limit."""
from datetime import timedelta

from django.db import connection

from farm.models import WaterLimit
from farm.tests.test_ph_scale import SeaTestCase
from farm.water import messages as water_messages, parameters, read as water_read
from sensors import bindings
from sensors.models import Channel, ChannelState
from sensors.tests import make_channel, make_connection, make_device, make_format

from .. import engine, read, rules as alarm_rules, sources
from ..models import Alarm, Severity

PH = 'ph'
SUMMARY = 'S-01: pH (NBS scale) cannot be evaluated: '
SYSTEM, SENSOR_RULE = 'system', 'sensor_rule'
OXYGEN = 'oxygen_mg_l'


def refused(why, scale='total'):
    """The reason a page and the warning give, in the words of farm/water/messages.py."""
    return str(water_messages.ph_sensor_refused(why, scale))


class RefusedSensorPhCase(SeaTestCase):
    def setUp(self):
        super().setUp()
        self.stock(self.sea)
        self.limit(PH, critical_low='6.20', warning_low='6.50', warning_high='8.50')
        device = make_device(make_connection(), make_format(), self.bergen)
        self.tris = make_channel(device, PH, code='PH-T', ph_scale='total')
        self.temperature = make_channel(device, parameters.TEMPERATURE, code='TEMP')
        self.salinity = make_channel(device, parameters.SALINITY, code='SAL')
        for channel in (self.tris, self.temperature, self.salinity):
            bindings.move(self.user, channel, point=self.sea_point, at=self.now - timedelta(hours=2))
        self.rules = alarm_rules.current()
        self.on_delay = self.rules.on_delay(Severity.WARNING)
        self.off_delay = self.rules.off_delay(Severity.WARNING)

    def send(self, channel, value, at):
        """The channel's value at `at`, as the ingest leaves it: its state and its reading."""
        ChannelState.objects.update_or_create(channel_no=channel.channel_no, defaults=dict(
            last_value=value, last_value_ts=at, last_good_at=at, last_seen_at=at))
        with connection.cursor() as cursor:
            cursor.execute('INSERT INTO sensors_reading (channel_no, ts, value) VALUES (%s, %s, %s)',
                           [channel.channel_no, at, value])

    def run_pass(self, at):
        summary = engine.run_once(at)
        self.assertEqual(summary.failed_steps, [])
        return summary

    def opened(self):
        """The open alarms of the water limits and the alarm system. The sensor rules' are left out: a channel of the
        fixture that never sends (the temperature here) raises its default "No fresh value" warning (owner decision of
        2026-11-20, sensors 0014), which StoppedProbeTests and sensors/tests/test_fresh_rule.py hold."""
        return sorted((alarm.source, alarm.severity, alarm.parameter)
                      for alarm in self.open().exclude(source=SENSOR_RULE))

    def open(self):
        """The open alarms but the alarm system's oxygen one: the fixture's unit holds fish and has no oxygen probe, so
        its oxygen with no fresh value is critical (owner decision of 2026-11-23; monitoring/tests/test_silent_oxygen.py
        holds it); these tests are about the pH."""
        return Alarm.objects.filter(clearance__isnull=True).exclude(source=SYSTEM, parameter=OXYGEN)

    def stopped(self):
        """The open "No fresh value" warnings of the sensor rules: {channel number: summary}."""
        return {alarm.sensor_event.channel_no: alarm.summary for alarm in Alarm.objects.filter(
            clearance__isnull=True, source=SENSOR_RULE, sensor_event__rule__kind='no_data').select_related('sensor_event')}

    def ph_reading(self, at):
        return water_read.unit_water([self.sea], at)[self.sea.pk].get(PH)


class WarningTests(RefusedSensorPhCase):
    def test_a_refused_sensor_ph_opens_the_warning_with_its_reason_after_the_on_delay(self):
        """A TRIS probe at 6.00 without a temperature: no value (never the raw number judged), and the warning of the
        alarm system for the unit, its on-delay counted from the value's time as a limit's is."""
        measured = self.now - timedelta(seconds=10)
        self.send(self.tris, 6.00, measured)
        self.send(self.salinity, 34.0, measured)
        reading = self.ph_reading(self.now)
        self.assertEqual((reading.value, reading.status, reading.unevaluated), (None, 'unevaluated', True))
        self.run_pass(measured + self.on_delay - timedelta(seconds=1))
        self.assertEqual(self.opened(), [])
        self.run_pass(measured + self.on_delay)
        self.assertEqual(self.opened(), [('system', 'warning', PH)])        # no limit alarm from the raw 6.00
        alarm = self.open().get(source=SYSTEM)
        self.assertEqual(alarm.summary, f'{SUMMARY}{refused("temperature")}.')
        self.assertEqual((alarm.site, alarm.production_department), (self.bergen, self.hall))

    def test_it_ends_restored_once_a_temperature_arrives_and_the_limit_then_judges_the_ph(self):
        measured = self.now - timedelta(seconds=10)
        self.send(self.tris, 6.00, measured)
        self.send(self.salinity, 34.0, measured)
        opened_at = measured + self.on_delay
        self.run_pass(opened_at)
        warning = self.open().get(source=SYSTEM)
        arrived = opened_at + timedelta(seconds=30)
        self.send(self.temperature, 12.0, arrived)
        reading = self.ph_reading(arrived)
        self.assertEqual(reading.value, water_read.ph_on_nbs(6.00, 'total', 12.0, 34.0, 'seawater').value)
        self.assertLess(reading.value, 6.20)                                   # 6.13 NBS: critical
        for seconds in (0, 1, self.off_delay.total_seconds() + 1):
            self.run_pass(arrived + timedelta(seconds=seconds))
        self.assertFalse(read.is_open(warning))
        self.assertEqual(warning.clearance.cause, 'restored')
        self.assertEqual(self.opened(), [('water_limit', 'critical', PH), ('water_limit', 'warning', PH)])

    def test_it_ends_with_that_cause_once_the_ph_limit_is_removed(self):
        measured = self.now - timedelta(seconds=10)
        self.send(self.tris, 6.00, measured)
        self.send(self.salinity, 34.0, measured)
        self.run_pass(measured + self.on_delay)
        warning = self.open().get(source=SYSTEM)
        WaterLimit.objects.filter(parameter=PH).delete()                     # nothing judges the pH any more
        self.run_pass(measured + self.on_delay + timedelta(seconds=1))
        self.assertFalse(read.is_open(warning))
        self.assertEqual(warning.clearance.cause, 'limit_removed')
        self.assertEqual(self.opened(), [])

    def test_an_open_low_ph_alarm_is_not_cleared_by_the_refused_value(self):
        """Converted while the temperature is fresh: the critical opens. The temperature probe then stops (a sensor
        temperature is fresh for 3 minutes) and the pH probe goes on: its next value has no temperature fresh at its
        time, so it is refused; the critical stays open (a refused value is no evidence that a level is over) and the
        warning says why the pH cannot be evaluated."""
        measured = self.now - timedelta(seconds=10)
        for channel, value in ((self.tris, 6.00), (self.temperature, 12.0), (self.salinity, 34.0)):
            self.send(channel, value, measured)
        self.run_pass(self.now)
        critical = Alarm.objects.get(source='water_limit', severity='critical')
        later = self.now + timedelta(minutes=5)
        self.send(self.tris, 7.95, later - timedelta(seconds=10))
        self.assertEqual(self.ph_reading(later).refused, refused('temperature'))
        for seconds in (0, 1, 60, 120):
            self.run_pass(later + timedelta(seconds=seconds))
        self.assertTrue(read.is_open(critical))
        self.assertIn(('system', 'warning', PH), self.opened())

    def test_the_same_probe_left_on_nbs_opens_the_critical_low_ph_alarm(self):
        """The contrast: an NBS channel's 6.00 is the water's pH, judged by the limits as before the audit."""
        nbs = make_channel(self.tris.device, PH, code='PH-N')
        self.assertEqual((nbs.ph_scale, nbs.ph_scale_from), ('nbs', None))
        bindings.move(self.user, self.tris, point=self.salted_point, at=self.now - timedelta(hours=1))
        bindings.move(self.user, nbs, point=self.sea_point, at=self.now - timedelta(hours=1))
        measured = self.now - timedelta(seconds=10)
        self.send(nbs, 6.00, measured)
        self.send(self.salinity, 34.0, measured)
        for seconds in (0, 60):
            self.run_pass(self.now + timedelta(seconds=seconds))
        self.assertEqual(self.opened(), [('water_limit', 'critical', PH), ('water_limit', 'warning', PH)])


class ScaleChangeTests(RefusedSensorPhCase):
    """A channel's scale changed: its value from before is used nowhere until the probe's next one. That is not a
    condition to raise and end a warning for in the minute the next value takes: the warning waits as long as the value
    from before would still be fresh (`sources._unevaluated_since`), and a probe that sends nothing after the change is
    warned of once it would be stale."""

    def change(self):
        measured = self.now - timedelta(seconds=30)
        for channel, value in ((self.tris, 7.95), (self.temperature, 12.0), (self.salinity, 34.0)):
            self.send(channel, value, measured)
        self.assertEqual(self.ph_reading(self.now).value, water_read.ph_on_nbs(7.95, 'total', 12.0, 34.0,
                                                                               'seawater').value)
        channel = Channel.objects.get(pk=self.tris.pk)
        channel.ph_scale = 'nbs'                                            # the probe recalibrated with NBS buffers
        channel.save()
        changed = Channel.objects.get(pk=self.tris.pk).ph_scale_from
        self.assertGreaterEqual(changed, self.now)
        return measured, changed

    def test_a_change_followed_by_the_probes_next_value_raises_nothing(self):
        measured, changed = self.change()
        next_value = changed + timedelta(minutes=4)
        # Longer than the warning's on-delay: counted from the value's own time, it would have raised.
        self.assertGreater(next_value - measured, self.on_delay)
        for minutes in (0, 1, 2, 3):
            at = changed + timedelta(minutes=minutes)
            self.assertIn('measured before the channel’s pH scale was changed', self.ph_reading(at).refused)
            self.run_pass(at)
        self.send(self.tris, 8.08, next_value)
        self.send(self.temperature, 12.0, next_value)
        for minutes in (0, 1, 10):
            self.run_pass(next_value + timedelta(minutes=minutes))
        self.assertEqual(self.ph_reading(next_value).value, water_read.as_parameter(PH, 8.08))
        self.assertFalse(Alarm.objects.filter(parameter=PH).exists())

    def test_a_probe_silent_after_the_change_is_warned_of_once_its_value_would_be_stale(self):
        measured, changed = self.change()
        stale_at = measured + timedelta(seconds=self.tris.fresh_s)
        self.run_pass(changed)
        self.run_pass(stale_at - timedelta(seconds=1))
        self.assertFalse(Alarm.objects.filter(parameter=PH).exists())
        self.run_pass(stale_at + self.on_delay - timedelta(seconds=1))
        self.assertFalse(Alarm.objects.filter(parameter=PH).exists())
        self.run_pass(stale_at + self.on_delay)
        warning = Alarm.objects.get(parameter=PH)
        self.assertEqual(warning.source, 'system')
        self.assertTrue(warning.summary.startswith(f'{SUMMARY}measured before the channel’s pH scale was changed'))


class CoverageTests(RefusedSensorPhCase):
    def test_every_value_the_limits_judge_has_its_warning_subject(self):
        """The class, not the case: whichever value the limits judge comes refused, its unit's warning is there."""
        self.assertEqual(set(sources.REFUSABLE), {parameter.code for parameter in parameters.LIMITED})
        found = water_read.unit_water([self.sea], self.now)
        subjects = sources._refused_subjects([self.sea], found, set(), False, self.now)
        self.assertEqual({subject.key for subject in subjects},
                         {f'system:unit:{self.sea.pk}:value_unevaluated:{parameter.code}'
                          for parameter in parameters.LIMITED})
        self.assertFalse(any(subject.holds for subject in subjects))


class StoppedProbeTests(RefusedSensorPhCase):
    """Owner decision of 2026-11-20 (the second review of the water-chemistry audit, question 3): a pH probe that stops
    sending is warned of by its channel's default "No fresh value" rule, whatever its scale, the moment its value is no
    longer fresh; a stale pH on the total scale is put on the NBS scale at its own moment and shown stale, as an NBS one,
    instead of the "cannot be evaluated" warning it raised before (that warning stays for a real refusal: WarningTests).
    The same probe on NBS and on the total scale gives the same alarms at the same moments."""

    def nbs_probe(self):
        """The same probe set to NBS (the TRIS channel taken to the other unit)."""
        nbs = make_channel(self.tris.device, PH, code='PH-N')
        bindings.move(self.user, self.tris, point=self.salted_point, at=self.now - timedelta(hours=1))
        bindings.move(self.user, nbs, point=self.sea_point, at=self.now - timedelta(hours=1))
        return nbs

    def stops(self, probe, value):
        """The probe sends `value` (longer before now than the warning's on-delay) and then nothing; the temperature
        and the salinity go on. What the alarms say at each pass: [(time since the value, the limits' and the system's
        alarms, whether the probe's "No fresh value" warning is open)], and that warning's summary."""
        measured = self.now - self.on_delay - timedelta(seconds=10)
        stale = timedelta(seconds=Channel.objects.get(pk=probe.pk).fresh_s)
        self.assertEqual(stale, timedelta(seconds=self.tris.fresh_s))       # 900 s: the same freshness either way
        for channel, sent in ((probe, value), (self.temperature, 12.0), (self.salinity, 34.0)):
            self.send(channel, sent, measured)
        seen = []
        for since in (self.now - measured, stale, stale + timedelta(seconds=1), stale + timedelta(minutes=1),
                      stale + timedelta(minutes=30)):
            at = measured + since
            if since > self.now - measured:
                self.send(self.temperature, 12.0, at)
                self.send(self.salinity, 34.0, at)
            self.run_pass(at)
            seen.append((since, self.opened(), probe.channel_no in self.stopped()))
        return seen, self.stopped().get(probe.channel_no, '')

    def expected(self, opened):
        stale = timedelta(seconds=self.tris.fresh_s)
        return [(self.on_delay + timedelta(seconds=10), opened, False), (stale, opened, False),
                (stale + timedelta(seconds=1), opened, True), (stale + timedelta(minutes=1), opened, True),
                (stale + timedelta(minutes=30), opened, True)]

    def test_a_stopped_tris_probe_raises_its_no_fresh_value_warning_and_no_cannot_be_evaluated(self):
        seen, summary = self.stops(self.tris, 7.95)
        self.assertEqual(seen, self.expected([]))
        self.assertTrue(summary.startswith('pH (NBS scale): No fresh value · PROBE-1 › PH-T: S-01 › '), summary)
        reading = self.ph_reading(self.now + timedelta(hours=1))
        self.assertEqual((reading.value, reading.status, reading.unevaluated),
                         (water_read.ph_on_nbs(7.95, 'total', 12.0, 34.0, 'seawater').value, 'stale', False))

    def test_a_stopped_nbs_probe_raises_the_same(self):
        nbs = self.nbs_probe()
        seen, summary = self.stops(nbs, 8.08)
        self.assertEqual(seen, self.expected([]))
        self.assertTrue(summary.startswith('pH (NBS scale): No fresh value · PROBE-1 › PH-N: S-01 › '), summary)

    def test_a_low_ph_raised_by_a_tris_probe_stays_open_when_it_stops_as_an_nbs_ones_does(self):
        """6.00 on the total scale is 6.13 NBS at 12 °C and S 34: the critical and the warning open while it is fresh;
        once the probe stops they stay open (a value that only goes stale ends nothing) beside its "No fresh value"
        warning, never a "cannot be evaluated"."""
        levels = [('water_limit', 'critical', PH), ('water_limit', 'warning', PH)]
        seen, _summary = self.stops(self.tris, 6.00)
        self.assertEqual(seen, self.expected(levels))

    def test_the_same_low_ph_on_an_nbs_probe(self):
        levels = [('water_limit', 'critical', PH), ('water_limit', 'warning', PH)]
        seen, _summary = self.stops(self.nbs_probe(), 6.00)
        self.assertEqual(seen, self.expected(levels))

"""The alarm engine judges a worked-out value's freshness as every reader does (farm/water/read.py `Reading.fresh`,
`freshness.derived_until`: never fresher than its oldest input): an NH₃ whose temperature has run out is stale, and a
stale value never ends an alarm, exactly as the stale temperature it was worked out from does not. T-01 stocked, NH₃-N
limits 0.0125 (warning) and 0.025 (critical), a temperature limit 11 °C (critical above) beside it as the measured
control (a critical opens the warning level beside it). Raised 40 h ago by a full sample (NH₃-N 0.8924, 12 °C); then a full sample inside both limits."""
from datetime import timedelta

from farm.tests.test_water import WaterTestCase

from .. import engine
from ..models import Alarm

BAD = {'ph': '9.00', 'temperature_c': '12.0', 'salinity_ppt': '0.0', 'alkalinity_mg_l': '80', 'tan_mg_l': '5.000'}
GOOD = {**BAD, 'ph': '7.00', 'tan_mg_l': '0.500', 'temperature_c': '10.0'}
NH3, TEMPERATURE = 'nh3_n_mg_l', 'temperature_c'
OPEN = 'open'


class DerivedStaleAlarmTests(WaterTestCase):
    def setUp(self):
        super().setUp()
        self.stock()
        self.limit(NH3, critical_high='0.025', warning_high='0.0125')
        self.limit(TEMPERATURE, critical_high='11.0')
        self.sample(self.t1, hours=40, **BAD)
        self.passes(-2380, -2379, -2320)
        self.assertEqual(self.outcome(NH3), {'critical': OPEN, 'warning': OPEN})
        self.assertEqual(self.outcome(TEMPERATURE), {'critical': OPEN, 'warning': OPEN})

    def passes(self, *minutes):
        for each in minutes:
            engine.run_once(self.now + timedelta(minutes=each))

    def outcome(self, parameter):
        found = {}
        for alarm in Alarm.objects.filter(source='water_limit', parameter=parameter):
            self.assertNotIn(alarm.severity, found, f'{parameter} {alarm.severity} opened twice')
            found[alarm.severity] = alarm.clearance.cause if hasattr(alarm, 'clearance') else OPEN
        return found

    def test_a_good_value_worked_out_from_an_expired_input_ends_nothing(self):
        """The good sample 30 h old when the passes run: its TAN (168 h), its pH (72 h) and the NH₃ row (168 h) are
        fresh, its temperature (24 h) is not. The NH₃ is stale and holds both levels, as the temperature holds its own."""
        self.sample(self.t1, hours=30, **GOOD)
        self.passes(0, 1, 60, 120, 600)
        self.assertEqual(self.outcome(TEMPERATURE), {'critical': OPEN, 'warning': OPEN})
        self.assertEqual(self.outcome(NH3), {'critical': OPEN, 'warning': OPEN})
        reading = self.unit_water().get(NH3)
        self.assertEqual(reading.status, 'stale')
        self.assertFalse(reading.fresh(self.now))

    def test_the_same_good_value_fresh_ends_them(self):
        """The control: the good sample 10 h old, every input fresh: both end, as the temperature's does."""
        self.sample(self.t1, hours=10, **GOOD)
        self.passes(0, 1, 60, 120, 600)
        self.assertEqual(self.outcome(TEMPERATURE), {'critical': 'returned', 'warning': 'returned'})
        self.assertEqual(self.outcome(NH3), {'critical': 'returned', 'warning': 'returned'})


class OwnPointEvidenceTests(WaterTestCase):
    """The review of 2026-11-26, F1 (the coordinator's rule): a worked-out alarm raised at one of the unit's own points
    ends only on new evidence from THAT point, a fresh value there back inside the limits; a newer OK value at another
    own point is not that evidence, and a late lab critical at a point still raises beside one. T-01 stocked, its middle
    point and an outlet (both its own water, A9.1), NH₃-N limits 0.0125 and 0.025."""

    def setUp(self):
        super().setUp()
        from farm.models import SamplingPoint
        self.stock()
        self.limit(NH3, critical_high='0.025', warning_high='0.0125')
        self.outlet = SamplingPoint.objects.create(unit=self.t1, name='Outlet', kind='outlet')

    passes = DerivedStaleAlarmTests.passes
    outcome = DerivedStaleAlarmTests.outcome

    def test_a_newer_ok_middle_does_not_end_the_outlets_critical(self):
        """The outlet critical 40 h ago (its temperature, so its NH₃, stale since 16 h ago; its TAN still fresh), the
        middle OK 2 h ago: both levels stay open, and the page says which point to measure. The outlet measured again,
        fresh and OK, ends them."""
        self.sample(self.outlet, hours=40, **BAD)
        self.passes(-2380, -2379, -2320)
        self.assertEqual(self.outcome(NH3), {'critical': OPEN, 'warning': OPEN})
        self.sample(self.t1, hours=2, **GOOD)
        self.passes(0, 1, 60, 120, 600)
        self.assertEqual(self.outcome(NH3), {'critical': OPEN, 'warning': OPEN})
        reading = self.unit_water().get(NH3)
        self.assertEqual((reading.point, reading.judged, reading.worse.point), (self.mid1, 'critical', self.outlet))
        self.assertIn('Last value at Outlet 0.8924 critical on ', reading.note)
        self.assertIn('no recent data: measure there', reading.note)
        self.sample(self.outlet, hours=1, **GOOD)
        self.passes(601, 602, 660, 720, 1200)
        self.assertEqual(self.outcome(NH3), {'critical': 'returned', 'warning': 'returned'})

    def test_a_late_lab_critical_at_the_outlet_raises_beside_a_newer_ok_middle(self):
        """The middle OK 2 h ago; the lab's outlet result, taken 30 h ago, keyed in now: critical, already stale. It
        raises both levels at once."""
        self.sample(self.t1, hours=2, **GOOD)
        self.sample(self.outlet, hours=30, source='lab', **BAD)
        self.passes(0, 1, 60)
        self.assertEqual(self.outcome(NH3), {'critical': OPEN, 'warning': OPEN})

    def test_a_newer_sample_at_the_outlet_that_cannot_be_worked_out_ends_nothing(self):
        """The outlet critical 40 h ago; then a TAN at the outlet without a pH or a temperature (3 h ago): its NH₃ cannot
        be worked out, which says nothing of the water being better. The middle OK 2 h ago. Both levels stay open, and
        the place says the outlet's newer sample lacks the inputs."""
        self.sample(self.outlet, hours=40, **BAD)
        self.passes(-2380, -2379, -2320)
        self.sample(self.outlet, hours=3, tan_mg_l='0.500')
        self.sample(self.t1, hours=2, **GOOD)
        self.passes(0, 1, 60, 120, 600)
        self.assertEqual(self.outcome(NH3), {'critical': OPEN, 'warning': OPEN})
        reading = self.unit_water().get(NH3)
        self.assertEqual((reading.judged, reading.worse.point, str(reading.worse.value)), ('critical', self.outlet,
                                                                                           '0.8924'))
        self.assertIn('Last value at Outlet 0.8924 critical on ', reading.note)
        self.assertIn('at Outlet gives no value (Needs the pH and the temperature of the same sample): measure there '
                      'again', reading.note)

    def test_a_late_lab_critical_raises_after_a_tan_only_outlet_sample_beside_a_newer_ok_middle(self):
        """Review 3, H1, case 1: the middle OK 2 h ago, the outlet's quick TAN without a pH 1 h ago (the place's newest
        TAN, so the one shown), the lab's outlet result of 30 h ago keyed in now, critical: it raises, and the place says
        the outlet's newer sample lacks its inputs."""
        self.sample(self.t1, hours=2, **GOOD)
        self.sample(self.outlet, hours=1, tan_mg_l='0.500')
        self.sample(self.outlet, hours=30, source='lab', **BAD)
        self.passes(0, 1, 60)
        self.assertEqual(self.outcome(NH3), {'critical': OPEN, 'warning': OPEN})
        reading = self.unit_water().get(NH3)
        self.assertEqual((reading.point, reading.judged, reading.worse.point), (self.mid1, 'critical', self.outlet))
        self.assertIn('Last value at Outlet 0.8924 critical on ', reading.note)
        self.assertIn('at Outlet gives no value', reading.note)

    def test_an_open_critical_stays_said_after_a_tan_only_sample_at_its_point(self):
        """Review 3, H1, case 2: the outlet critical and raised; the middle OK; then a TAN without a pH at the outlet,
        the place's newest: the level stays open AND the page says it, never "not measured"."""
        self.sample(self.outlet, hours=40, **BAD)
        self.passes(-2380, -2379, -2320)
        self.sample(self.t1, hours=3, **GOOD)
        self.sample(self.outlet, hours=1, tan_mg_l='0.500')
        self.passes(0, 1, 60, 120, 600)
        self.assertEqual(self.outcome(NH3), {'critical': OPEN, 'warning': OPEN})
        reading = self.unit_water().get(NH3)
        self.assertEqual((reading.point, reading.judged, reading.worse.point), (self.mid1, 'critical', self.outlet))
        self.assertIn('Last value at Outlet 0.8924 critical on ', reading.note)
        self.assertIn('at Outlet gives no value', reading.note)

    def test_more_samples_without_a_temperature_than_any_count_never_drop_the_hold(self):
        """Review 3, M3: the outlet critical; then 25 samples at the outlet with a TAN and a pH but no temperature (no
        probe anywhere), the middle OK newest: the outlet's critical still holds, looked back at through the whole
        window, never a count."""
        self.sample(self.outlet, hours=40, **BAD)
        self.passes(-2380, -2379, -2320)
        for hour in range(30, 5, -1):
            self.sample(self.outlet, hours=hour, tan_mg_l='0.500', ph='7.00')
        self.sample(self.t1, hours=2, **GOOD)
        self.passes(0, 1, 60, 120, 600)
        self.assertEqual(self.outcome(NH3), {'critical': OPEN, 'warning': OPEN})


class SinglePointEvidenceTests(WaterTestCase):
    """Review 3, H1, the unit with one point: T-01's middle alone, critical and raised, then a TAN without a pH there."""

    def setUp(self):
        super().setUp()
        self.stock()
        self.limit(NH3, critical_high='0.025', warning_high='0.0125')

    passes = DerivedStaleAlarmTests.passes
    outcome = DerivedStaleAlarmTests.outcome

    def test_a_tan_only_sample_does_not_hide_the_middles_critical(self):
        self.sample(self.t1, hours=40, **BAD)
        self.passes(-2380, -2379, -2320)
        self.sample(self.t1, hours=1, tan_mg_l='0.500')
        self.passes(0, 1, 60, 120, 600)
        self.assertEqual(self.outcome(NH3), {'critical': OPEN, 'warning': OPEN})
        reading = self.unit_water().get(NH3)
        self.assertEqual((str(reading.value), reading.judged, reading.status), ('0.8924', 'critical', 'stale'))
        self.assertIn('at Middle gives no value', reading.note)

    def tie(self, lab_first):
        """One bottle at T-01's middle 30 h ago: the lab's full result (critical) and the field kit's TAN alone, at the
        same minute, keyed in either order."""
        from farm.water import services as water_services
        from decimal import Decimal
        at = self.ago(hours=30)
        lab = {code: Decimal(value) for code, value in BAD.items()}
        kit = {'tan_mg_l': Decimal('0.500')}
        for source, values in (('lab', lab), ('manual', kit)) if lab_first else (('manual', kit), ('lab', lab)):
            water_services.record(self.user, point=self.mid1, measured_at=at, source=source, values=values)

    def test_a_same_minute_tie_lab_first_raises_and_is_shown(self):
        """Review 4, H1: the lab's critical and the kit's TAN alone at the same minute, the lab keyed first: the critical
        is the point's newest worked-out value, it raises, and the page shows it."""
        self.tie(lab_first=True)
        self.passes(0, 1, 60)
        self.assertEqual(self.outcome(NH3), {'critical': OPEN, 'warning': OPEN})
        reading = self.unit_water().get(NH3)
        self.assertEqual((str(reading.value), reading.judged), ('0.8924', 'critical'))
        self.assertIn('at Middle gives no value', reading.note)

    def test_a_same_minute_tie_kit_first_raises_and_is_shown(self):
        """The kit keyed first: the same verdict as the other order (the judge reads one minute's values alike), the kit's
        TAN alone said beside the lab's critical."""
        self.tie(lab_first=False)
        self.passes(0, 1, 60)
        self.assertEqual(self.outcome(NH3), {'critical': OPEN, 'warning': OPEN})
        reading = self.unit_water().get(NH3)
        self.assertEqual((str(reading.value), reading.judged), ('0.8924', 'critical'))
        self.assertIn('at Middle gives no value', reading.note)


class SystemTierTests(WaterTestCase):
    """Review 4, H2: a unit whose water is sampled at its system's loop only (RAS), the same rule at the system tier:
    the loop's newest worked-out value is its candidate; a newer quick TAN without a pH there never takes the slot."""

    def setUp(self):
        super().setUp()
        self.stock()
        self.limit(NH3, critical_high='0.025', warning_high='0.0125')

    passes = DerivedStaleAlarmTests.passes
    outcome = DerivedStaleAlarmTests.outcome

    def test_a_late_lab_critical_at_the_loop_raises_behind_a_quick_tan(self):
        """The loop's quick TAN 1 h ago, then the lab's loop result of 10 h ago keyed in, critical: it raises for T-01,
        and T-01's NH₃ shows it with the quick TAN's note."""
        self.sample(self.loop, hours=1, tan_mg_l='0.500')
        self.sample(self.loop, hours=10, source='lab', **BAD)
        self.passes(0, 1, 60)
        self.assertEqual(self.outcome(NH3), {'critical': OPEN, 'warning': OPEN})
        reading = self.unit_water().get(NH3)
        self.assertEqual((str(reading.value), reading.judged, reading.point), ('0.8924', 'critical', self.loop))
        self.assertIn(f'at {self.loop.name} gives no value', reading.note)

    def test_an_open_critical_at_the_loop_stays_open_and_shown_after_a_quick_tan(self):
        self.sample(self.loop, hours=40, **BAD)
        self.passes(-2380, -2379, -2320)
        self.assertEqual(self.outcome(NH3), {'critical': OPEN, 'warning': OPEN})
        self.sample(self.loop, hours=1, tan_mg_l='0.500')
        self.passes(0, 1, 60, 120, 600)
        self.assertEqual(self.outcome(NH3), {'critical': OPEN, 'warning': OPEN})
        reading = self.unit_water().get(NH3)
        self.assertEqual((str(reading.value), reading.judged), ('0.8924', 'critical'))
        self.assertIn(f'at {self.loop.name} gives no value', reading.note)


class Round6Tests(WaterTestCase):
    """Review 5 (the coordinator's round 6): T-01's middle alone, NH₃-N limits 0.0125 and 0.025."""

    def setUp(self):
        super().setUp()
        self.stock()
        self.limit(NH3, critical_high='0.025', warning_high='0.0125')

    passes = DerivedStaleAlarmTests.passes
    outcome = DerivedStaleAlarmTests.outcome

    def full_tie(self, lab_first, hours=3):
        """One bottle 3 h ago: the lab's full result (critical) and the field kit's full result (OK), at the same minute,
        keyed in either order."""
        from decimal import Decimal

        from farm.water import services as water_services
        at = self.ago(hours=hours)
        lab = {code: Decimal(value) for code, value in BAD.items()}
        kit = {code: Decimal(value) for code, value in GOOD.items()}
        for source, values in (('lab', lab), ('manual', kit)) if lab_first else (('manual', kit), ('lab', lab)):
            water_services.record(self.user, point=self.mid1, measured_at=at, source=source, values=values)

    def test_a_same_minute_critical_and_ok_raise_and_show_critical_lab_first(self):
        """H1 (1): the kit's OK keyed after the lab's critical never displaces it: raised, and the page says critical."""
        self.full_tie(lab_first=True)
        self.passes(0, 1, 60)
        self.assertEqual(self.outcome(NH3), {'critical': OPEN, 'warning': OPEN})
        self.assertEqual(self.unit_water().get(NH3).judged, 'critical')

    def test_a_same_minute_critical_and_ok_raise_and_show_critical_kit_first(self):
        self.full_tie(lab_first=False)
        self.passes(0, 1, 60)
        self.assertEqual(self.outcome(NH3), {'critical': OPEN, 'warning': OPEN})
        self.assertEqual(self.unit_water().get(NH3).judged, 'critical')

    def test_a_tie_never_clears(self):
        """A pass between the two entries raised it; the same-minute OK keyed after is no evidence: it stays open."""
        from decimal import Decimal

        from farm.water import services as water_services
        at = self.ago(hours=3)
        water_services.record(self.user, point=self.mid1, measured_at=at, source='lab',
                              values={code: Decimal(value) for code, value in BAD.items()})
        self.passes(-170, -169, -110)
        self.assertEqual(self.outcome(NH3), {'critical': OPEN, 'warning': OPEN})
        water_services.record(self.user, point=self.mid1, measured_at=at, source='manual',
                              values={code: Decimal(value) for code, value in GOOD.items()})
        self.passes(0, 1, 60, 120, 600)
        self.assertEqual(self.outcome(NH3), {'critical': OPEN, 'warning': OPEN})

    def test_a_late_result_before_newer_evidence_is_said_and_logged_not_alarmed(self):
        """The owner's decision: the middle's OK 2 h ago is the evidence; the lab's critical measured 10 h ago is keyed in
        now. No alarm; the point says it, and the activity log keeps it."""
        from core.models import AuditLog
        self.sample(self.t1, hours=2, **GOOD)
        self.sample(self.t1, hours=10, source='lab', **BAD)
        self.passes(0, 1, 60)
        self.assertEqual(self.outcome(NH3), {})
        reading = self.unit_water().get(NH3)
        self.assertEqual(reading.judged, 'ok')
        self.assertIn('Late result: critical 0.8924 at Middle on ', reading.note)
        self.assertIn(', superseded by ', reading.note)
        logged = ' '.join(str(entry.changes) for entry in AuditLog.objects.filter(entity_type='water sample'))
        self.assertIn('Late result', logged)

    def test_an_own_tan_newer_than_the_loops_value_is_attention_never_ok(self):
        """L5: T-01's own TAN alone 1 h ago, the loop's full OK 3 h ago: T-01's NH₃ is the loop's value, never plain OK:
        it needs attention (its own sample lacks the pH or the temperature)."""
        self.sample(self.loop, hours=3, **GOOD)
        self.sample(self.t1, hours=1, tan_mg_l='0.500')
        reading = self.unit_water().get(NH3)
        self.assertEqual((reading.point, reading.judged), (self.loop, 'unevaluated'))
        self.assertIn('at Middle gives no value', reading.note)


class Round7Tests(WaterTestCase):
    """Review 6 (the coordinator's round 7). T-01 stocked, its middle and an outlet, NH₃-N limits 0.0125 and 0.025."""
    WARNING_WATER = {'ph': '8.00', 'temperature_c': '12.0', 'salinity_ppt': '0.0', 'tan_mg_l': '0.700'}

    def setUp(self):
        super().setUp()
        from farm.models import SamplingPoint
        self.stock()
        self.limit(NH3, critical_high='0.025', warning_high='0.0125')
        self.outlet = SamplingPoint.objects.create(unit=self.t1, name='Outlet', kind='outlet')

    passes = DerivedStaleAlarmTests.passes
    outcome = DerivedStaleAlarmTests.outcome

    def test_a_stale_held_warning_never_clears_a_critical(self):
        """M2: the outlet critical 40 h ago, raised; the outlet's warning measured 30 h ago keyed in now (stale on entry:
        its temperature's 24 h are over); the middle OK 1 h ago. The warning is held (stale, worse than the OK), so it
        decides, and it is stale by its own freshness: the critical stays open."""
        self.sample(self.outlet, hours=40, **BAD)
        self.passes(-2380, -2379, -2320)
        self.sample(self.outlet, hours=30, source='lab', **self.WARNING_WATER)
        self.sample(self.t1, hours=1, **GOOD)
        reading = self.unit_water().get(NH3)
        self.assertEqual((reading.judged, reading.worse.point), ('warning', self.outlet))
        self.passes(0, 1, 60, 120, 600)
        self.assertEqual(self.outcome(NH3), {'critical': OPEN, 'warning': OPEN})

    def test_a_late_loop_critical_older_than_the_value_shown_is_said(self):
        """M7, the older way: T-01's own OK 2 h ago is shown; the loop's lab critical measured 30 h ago keyed in now is
        older than it: no alarm, and the unit says it as a late result."""
        self.sample(self.t1, hours=2, **GOOD)
        self.sample(self.loop, hours=30, source='lab', **BAD)
        self.passes(0, 1, 60)
        self.assertEqual(self.outcome(NH3), {})
        reading = self.unit_water().get(NH3)
        self.assertEqual(reading.judged, 'ok')
        self.assertIn(f'Late result: critical 0.8924 at {self.loop.name} on ', reading.note)


class Round7SeaTests(WaterTestCase):
    """M7, the newer way: a sea RAS; the loop's critical is newer than T-01's own OK shown but stale already (its salinity,
    looked up from a loop sample 177 h old, ended 9 h ago): it is held, and raises."""

    def setUp(self):
        super().setUp()
        from farm.models import Tank
        Tank.objects.filter(pk__in=[self.t1.pk, self.t2.pk]).update(water_type='saltwater', water_origin='seawater')
        self.t1.refresh_from_db()
        self.stock()
        self.limit(NH3, critical_high='0.025', warning_high='0.0125')

    passes = DerivedStaleAlarmTests.passes
    outcome = DerivedStaleAlarmTests.outcome

    def test_a_stale_loop_critical_newer_than_the_value_shown_is_held(self):
        sea = {'salinity_ppt': '30.0'}
        self.sample(self.t1, hours=20, **{**GOOD, **sea})
        self.sample(self.loop, hours=177, **sea)
        self.sample(self.loop, hours=10, source='lab', **{key: value for key, value in BAD.items()
                                                           if key != 'salinity_ppt'})
        reading = self.unit_water().get(NH3)
        self.assertEqual((reading.point, reading.judged, reading.worse.point), (self.mid1, 'critical', self.loop))
        self.passes(0, 1, 60)
        self.assertEqual(self.outcome(NH3), {'critical': OPEN, 'warning': OPEN})


class LiveEvidenceTests(WaterTestCase):
    """M6: a TAN analyser on T-01's middle (with its pH and temperature probes): its live NH₃ is evidence at the point, so
    a lab critical there 2 days old is superseded, not held."""

    def setUp(self):
        super().setUp()
        self.stock()
        self.limit(NH3, critical_high='0.025', warning_high='0.0125')

    def test_a_fresh_live_ok_supersedes_an_old_lab_critical_at_its_point(self):
        from django.db import connection
        from django.utils import timezone

        from farm.tests.helpers import may_record
        from sensors import bindings
        from sensors.models import ChannelState
        from sensors.tests import make_channel, make_connection, make_device, make_format
        self.sample(self.t1, hours=48, source='lab', **BAD)
        may_record(self.user, 'add_binding')
        device = make_device(make_connection(), make_format(), self.bergen, code='ANALYSER')
        now = timezone.now()
        for quantity, value in (('tan_mg_l', 0.5), ('ph', 7.0), ('temperature_c', 12.0)):
            channel = make_channel(device, quantity, code=quantity.upper())
            bindings.move(self.user, channel, point=self.mid1, at=now - timedelta(hours=2))
            at = now - timedelta(seconds=30)
            ChannelState.objects.update_or_create(channel_no=channel.channel_no, defaults=dict(
                last_value=value, last_value_ts=at, last_good_at=at, last_seen_at=at))
            with connection.cursor() as cursor:
                cursor.execute('INSERT INTO sensors_reading (channel_no, ts, value) VALUES (%s, %s, %s)',
                               [channel.channel_no, at, value])
        reading = self.unit_water().get(NH3)
        self.assertTrue(reading.sample.live)
        self.assertEqual((reading.judged, reading.worse), ('ok', None))

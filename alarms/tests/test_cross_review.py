"""The independent cross review of the owner-settings alarms (docs/reviews/2026-11-owner-settings.md): each finding pinned
by the safe behaviour it asked for. A missed critical alarm can kill fish: every test here is a way one was missed."""
from datetime import timedelta

from farm.water import read as water_read, sources as water_sources

from ..models import Alarm
from . import AlarmsCase


class Live:
    """A live provider of farm/water/sources.py whose values the test gives: {target: {code: [SensorValue]}}."""

    def __init__(self, values):
        self.values = values

    def latest(self, targets, now):
        return {target: found for target, found in self.values.items() if target in targets}

    def value_at(self, targets, code, moment):
        return {}

    def bound(self, targets, code, since, until):
        return set()


def sensor_value(code, number, at, fresh_for=60, channel_no=77):
    return water_sources.SensorValue(code, number, at, fresh_for, water_sources.PRIMARY, channel_no)


def open_levels(**filters):
    return sorted(alarm.severity for alarm in Alarm.objects.filter(clearance__isnull=True, source='water_limit',
                                                                    **filters))


class CrossReviewCase(AlarmsCase):
    def live(self, values):
        provider = Live(values)
        water_sources.register(provider)
        self.addCleanup(water_sources.unregister, provider)
        return provider

    def live_ph(self, number, at, point=None):
        return self.live({(water_sources.POINT, (point or self.mid1).pk): {'ph': [sensor_value('ph', number, at)]}})


class ClockAheadTests(CrossReviewCase):
    """F1 (blocker): a value stamped ahead of the server's clock decides the card's status (the read layer counts it up to
    the ingest contract's hour, evaluate.MAX_AHEAD), so its alarm is raised as soon as the card shows it: the on-delay is
    counted from the value's time or the pass's, whichever is earlier, never from a moment still to come."""

    def test_a_value_four_minutes_fast_raises_its_critical_at_once(self):
        self.live_ph(5.5, self.now + timedelta(minutes=4))         # inside the read layer's clock tolerance: fresh
        card = water_read.unit_water([self.t1], self.now)[self.t1.pk]
        self.assertEqual(card.status, 'critical')
        self.loop()
        self.assertIn('critical', open_levels())

    def test_a_probe_twenty_minutes_fast_beside_a_good_value_raises_its_critical_at_once(self):
        self.sample(7.0, hours=0.1)                                 # a correct clock, fine
        self.live_ph(5.5, self.now + timedelta(minutes=20))         # beyond the tolerance, inside the contract's hour
        card = water_read.unit_water([self.t1], self.now)[self.t1.pk]
        self.assertEqual(card.status, 'critical')
        self.loop()
        self.assertIn('critical', open_levels())

    def test_the_warning_on_delay_runs_from_the_pass_not_from_the_future_stamp(self):
        self.live_ph(6.2, self.now + timedelta(minutes=20))         # a warning, 20 min fast; warning on-delay 30 s
        self.loop()
        self.assertEqual(open_levels(), [])
        self.loop(seconds=31)
        self.assertEqual(open_levels(), ['warning'])

    def test_a_fast_value_that_comes_back_clears_after_the_off_delay_counted_from_the_pass(self):
        probe = self.live_ph(5.5, self.now + timedelta(minutes=4))
        self.loop()
        self.assertEqual(open_levels(), ['critical'])               # the warning waits for its own on-delay
        probe.values = {(water_sources.POINT, self.mid1.pk): {'ph': [sensor_value(
            'ph', 7.0, self.now + timedelta(minutes=4, seconds=1))]}}    # back, the same probe 4 min fast
        self.loop(seconds=1)
        self.assertEqual(open_levels(), ['critical'])
        self.loop(seconds=32)                                       # the off-delay (30 s) from the pass that saw it
        self.assertEqual(open_levels(), [])


class DeadbandAcrossCandidatesTests(CrossReviewCase):
    """F2: a level clears only when EVERY fresh value of the unit's water is back inside its limit by the deadband (alarm
    plan §2.1), not only the value that decided it: a depth point 0.02 over the critical pH limit, inside pH's deadband
    (0.05), keeps the critical open beside a newer warning value of the middle point, so the next 5.98 never re-raises
    it (no chatter)."""

    def test_another_points_value_inside_the_deadband_keeps_the_level(self):
        from farm.models import SamplingPoint
        depth = SamplingPoint.objects.create(unit=self.t1, kind='depth', name='Bottom', depth_m=1)
        self.sample(5.5, hours=1, point=depth)
        self.loop()
        self.loop(seconds=31)
        self.assertEqual(open_levels(), ['critical', 'warning'])
        self.sample(6.02, hours=0.6, point=depth)          # back over 6 by less than the deadband
        self.sample(6.4, hours=0.5)                         # the middle point: a warning, newer
        self.loop(seconds=32)
        self.loop(seconds=80)
        self.assertEqual(open_levels(), ['critical', 'warning'])

    def test_every_value_clear_by_the_deadband_clears(self):
        from farm.models import SamplingPoint
        depth = SamplingPoint.objects.create(unit=self.t1, kind='depth', name='Bottom', depth_m=1)
        self.sample(5.5, hours=1, point=depth)
        self.loop()
        self.sample(6.2, hours=0.6, point=depth)           # clear of the critical limit by more than the deadband
        self.sample(6.4, hours=0.5)
        self.loop(seconds=1)
        self.loop(seconds=40)
        self.assertEqual(open_levels(), ['warning'])

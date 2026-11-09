"""A device whose clock differs from the platform's is an alarm of its own (owner, 2026-11-09). The skew is measured per
device from what the ingest already stores (sensors_channel_state: `last_value_ts`, the device's time of the newest good
value, against `last_good_at`, when the platform received it), both ways: ahead and behind. Its warning and critical
limits, and their deadbands, are the user's rule data (alarms.SeverityPolicy), seeded at 60 s (the ingest contract's
default future skew: past it the ingest no longer trusts a device's time) and 300 s (the read layer's clock tolerance:
past it a value is no longer shown as fresh). It goes through the same raise, clear and deadband lifecycle as every alarm,
per device with its site, and shows as a data-quality note on the device list and the unit's card. A value from a skewed
device still decides its unit's status and its alarm is never delayed (cross review F1, test_cross_review)."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.urls import reverse

from farm.tests.helpers import role
from sensors import bindings
from sensors.models import ChannelState
from sensors.quality import CLOCK_SUSPECT, RECEIVE_TIME
from sensors.tests import make_channel, make_connection, make_device, make_format

from .. import read
from ..models import Alarm, AlarmClearance, SeverityPolicy
from . import AlarmsCase


class ClockCase(AlarmsCase):
    def setUp(self):
        super().setUp()
        self.device = make_device(make_connection(), make_format(), self.bergen)
        self.channel = make_channel(self.device, 'ph')
        bindings.move(self.keeper, self.channel, self.now - timedelta(days=1), point=self.mid1)

    def skew(self, seconds, received=0, quality=0):
        """The channel's newest good value: received `received` s after the test's now, stamped `seconds` off it."""
        received_at = self.now + timedelta(seconds=received)
        ChannelState.objects.update_or_create(channel_no=self.channel.channel_no, defaults={
            'last_value': 7.0, 'last_value_ts': received_at + timedelta(seconds=seconds), 'last_good_at': received_at,
            'last_seen_at': received_at, 'last_quality': quality})

    def levels(self):
        return sorted(alarm.severity for alarm in Alarm.objects.filter(parameter='device_clock', clearance__isnull=True))


class ClockSkewAlarmTests(ClockCase):
    def test_a_device_four_minutes_ahead_is_a_warning_on_its_site(self):
        self.skew(240)
        self.loop()
        self.assertEqual(self.levels(), [])                          # the warning's on-delay (30 s)
        self.skew(240, received=31)
        self.loop(seconds=31)
        self.assertEqual(self.levels(), ['warning'])
        alarm = Alarm.objects.get(parameter='device_clock')
        self.assertEqual((alarm.source, alarm.device, alarm.site), ('system', self.device, self.bergen))
        self.assertIn('PROBE-1', alarm.summary)
        self.assertIn('ahead', alarm.summary)

    def test_a_device_six_minutes_ahead_is_critical_at_once(self):
        self.skew(360)
        self.loop()
        self.assertEqual(self.levels(), ['critical'])

    def test_a_device_behind_is_measured_too(self):
        for seconds in range(0, 631, 30):                           # behind on every pass for the whole window
            self.skew(-120, received=seconds)
            self.loop(seconds=seconds)
        self.assertEqual(self.levels(), ['warning'])
        self.assertIn('behind', Alarm.objects.get(parameter='device_clock').summary)

    def test_it_clears_past_the_deadband_after_the_off_delay(self):
        self.skew(360)
        self.loop()
        self.skew(280, received=1)                                   # under 300 s, inside its deadband (30 s)
        self.loop(seconds=1)
        self.loop(seconds=40)
        self.assertEqual(self.levels(), ['critical', 'warning'])     # the warning's on-delay ran out meanwhile
        self.skew(30, received=41)
        self.loop(seconds=41)
        self.skew(30, received=80)
        self.loop(seconds=80)
        self.assertEqual(self.levels(), [])
        self.assertEqual({row.cause for row in AlarmClearance.objects.all()}, {'returned'})

    def test_no_recent_value_says_nothing_and_ends_nothing(self):
        self.skew(360)
        self.loop()
        self.loop(minutes=30)                                        # the value is long past its freshness
        self.assertEqual(self.levels(), ['critical'])

    def test_a_time_the_ingest_replaced_is_ahead_by_more_than_the_contract_allows(self):
        self.skew(0, quality=CLOCK_SUSPECT)                         # ahead by more than future_skew_s (60 s)
        self.loop()
        self.skew(0, received=31, quality=CLOCK_SUSPECT)
        self.loop(seconds=31)
        self.assertEqual(self.levels(), ['warning'])

    def test_a_message_without_a_device_time_measures_nothing(self):
        self.skew(0, quality=RECEIVE_TIME)
        self.loop()
        self.loop(seconds=31)
        self.assertEqual(self.levels(), [])

    def test_the_limits_are_the_users_rule_data(self):
        SeverityPolicy.objects.filter(severity='warning').update(clock_skew_seconds=600, clock_skew_deadband_seconds=60)
        SeverityPolicy.objects.filter(severity='critical').update(clock_skew_seconds=900, clock_skew_deadband_seconds=60)
        self.skew(360)
        self.loop()
        self.skew(360, received=31)
        self.loop(seconds=31)
        self.assertEqual(self.levels(), [])

    def test_its_warning_is_not_notified_under_its_critical(self):
        from ..models import Notification
        self.rule()
        self.skew(360)
        self.loop()
        self.skew(360, received=31)
        self.loop(seconds=31)
        self.assertEqual(self.levels(), ['critical', 'warning'])
        self.assertEqual({notification.alarm.severity for notification in Notification.objects.all()}, {'critical'})
        self.assertTrue(read.is_open(Alarm.objects.get(parameter='device_clock', severity='warning')))


class BehindWindowTests(ClockCase):
    """Round-2 review N1: a value received late is not a slow clock. "Behind" holds only when the device is behind on
    every pass of its severity's window (the user's rule data, `clock_behind_window_seconds`, 600 s by default: the
    minimum over the window), and never while the ingest says messages are waiting for its connection (a backlog being
    drained). "Ahead" is judged at once, as before."""

    def test_a_backlog_drained_after_a_ten_minute_outage_raises_no_clock_alarm(self):
        self.skew(-600)                                             # the first message of the backlog, read mid-drain
        self.loop()
        self.skew(-300, received=5)
        self.loop(seconds=5)
        for seconds in range(10, 700, 30):                          # drained: the device's own clock is right
            self.skew(-1, received=seconds)
            self.loop(seconds=seconds)
        self.assertFalse(Alarm.objects.filter(parameter='device_clock').exists())      # never raised, not even once

    def test_a_backlog_the_ingest_reports_is_never_a_slow_clock(self):
        from sensors.models import IngestStatus
        IngestStatus.objects.create(connection_id=self.device.connection_id, heartbeat_at=self.now, connected=True,
                                    queue_depth=5000)
        for seconds in range(0, 700, 30):                           # a long drain, behind on every pass
            self.skew(-400, received=seconds)
            self.loop(seconds=seconds)
        self.assertFalse(Alarm.objects.filter(parameter='device_clock').exists())

    def test_a_truly_slow_clock_still_raises_after_the_window(self):
        for seconds in range(0, 571, 30):
            self.skew(-360, received=seconds)
            self.loop(seconds=seconds)
        self.assertEqual(self.levels(), [])                         # inside the window: not yet
        for seconds in range(600, 661, 30):
            self.skew(-360, received=seconds)
            self.loop(seconds=seconds)
        self.assertEqual(self.levels(), ['critical', 'warning'])

    def test_ahead_is_still_at_once(self):
        self.skew(360)
        self.loop()
        self.assertEqual(self.levels(), ['critical'])

    def test_the_window_is_the_users(self):
        SeverityPolicy.objects.update(clock_behind_window_seconds=60)
        for seconds in range(0, 121, 30):
            self.skew(-360, received=seconds)
            self.loop(seconds=seconds)
        self.assertEqual(self.levels(), ['critical', 'warning'])


class ClockSkewRuleTests(ClockCase):
    def test_the_seeded_limits(self):
        self.assertEqual({policy.severity: (policy.clock_skew_seconds, policy.clock_skew_deadband_seconds)
                          for policy in SeverityPolicy.objects.all()}, {'warning': (60, 10), 'critical': (300, 30)})

    def test_the_database_refuses_nonsense(self):
        from django.db import IntegrityError, transaction
        for values in ({'clock_skew_seconds': 0}, {'clock_skew_seconds': 3601},
                       {'clock_skew_deadband_seconds': 300}, {'clock_skew_deadband_seconds': -1}):
            with self.subTest(values=values), self.assertRaises(IntegrityError), transaction.atomic():
                SeverityPolicy.objects.filter(severity='critical').update(**values)

    def test_the_warning_limit_is_below_the_critical(self):
        from django.core.exceptions import ValidationError
        policy = SeverityPolicy.objects.get(severity='warning')
        policy.clock_skew_seconds = 300
        with self.assertRaises(ValidationError) as refused:
            policy.full_clean()
        self.assertIn('clock_skew_seconds', refused.exception.message_dict)


class ClockNoteTests(ClockCase):
    def test_the_device_list_says_the_clock_is_ahead(self):
        viewer = get_user_model().objects.create_user('viewer', 'viewer@example.com', 'x')
        viewer.groups.add(role('Sensor viewer', 'view_device'))
        self.client.force_login(viewer)
        self.skew(240, received=-1)
        self.assertContains(self.client.get(reverse('sensors:device_list')), 'Device clock is 4 min ahead')

    def test_the_units_card_says_it_as_a_data_quality_note(self):
        from monitoring import read as monitoring_read
        from monitoring.tests import ALL_RIGHTS, chosen
        reader = get_user_model().objects.create_user('reader', 'reader@example.com', 'x')
        reader.groups.add(role('Reader', *ALL_RIGHTS))
        self.skew(-120, received=-1)                                 # its value fresh: on the card
        self.sample(7.0, hours=0.5)
        card, = monitoring_read.cards([self.t1], reader, chosen({self.t1.pk: 'simple'}), now=self.now)
        self.assertIn('Device clock is 2 min behind (PROBE-1)', monitoring_read.state_of(card).reasons)

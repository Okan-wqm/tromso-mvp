"""The Deffeyes replay (owner amendment A6): `sensors.read.deffeyes_frames(target, start, end, step)`, the unit's (or
system's) water at each step of a range, every input in the A1 order at that moment (a fresh sensor value at or before
it, carried no longer than the channel's freshness; else a fresh sample; else missing, never invented), the point on the
diagram worked out by farm/water/deffeyes.py, one query of the readings per tier; and its JSON endpoint with the static
diagram once (its box holding every frame) and at most 2000 frames on the step ladder."""
import json
from datetime import datetime, timedelta, timezone as tz
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from farm.models import System
from farm.tests.helpers import point_of, role
from farm.tests.test_stock import make_unit
from farm.water import chemistry, deffeyes, services as water_services

from sensors import bindings, read
from sensors.models import Channel

from . import SensorsCase, make_channel

START = datetime(2026, 10, 10, tzinfo=tz.utc)


def insert(channel_no, rows):
    with connection.cursor() as cursor:
        for at, value in rows:                                        # one row per statement
            cursor.execute('INSERT INTO sensors_reading (channel_no, ts, value) VALUES (%s, %s, %s)',
                           [channel_no, at, value])


class ReplayCase(SensorsCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.ras = System.objects.create(name='RAS 1', code='R1', site=cls.site, production_department=cls.hall)
        cls.t1 = make_unit('T-01', cls.hall, system=cls.ras)
        cls.t2 = make_unit('T-02', cls.hall, system=cls.ras)
        cls.mid1, cls.mid2, cls.loop = point_of(cls.t1), point_of(cls.t2), point_of(cls.ras)
        cls.ph = make_channel(cls.device, 'ph')                               # heartbeat 300 s: fresh 900 s
        Channel.objects.filter(pk=cls.channel.pk).update(heartbeat_s=60)      # temperature: fresh 180 s
        bindings.move(cls.user, cls.ph, point=cls.mid1, at=START - timedelta(days=1))
        bindings.move(cls.user, cls.channel, system=cls.ras, at=START - timedelta(days=1))
        water_services.record(cls.user, point=cls.mid1, measured_at=START - timedelta(days=1), source='manual',
                              values={'alkalinity_mg_l': Decimal('100'), 'salinity_ppt': Decimal('0')})

    def steady(self, minutes=60):
        """pH every 5 min and temperature every minute for `minutes` from START."""
        insert(self.ph.channel_no, [(START + timedelta(minutes=m), 7.0 + m / 1000) for m in range(0, minutes, 5)])
        insert(self.channel.channel_no, [(START + timedelta(minutes=m), 10.0 + m / 100) for m in range(minutes)])


class FrameTests(ReplayCase):
    def test_each_frame_holds_the_value_at_its_moment_and_the_diagrams_point(self):
        self.steady()
        frames = read.deffeyes_frames(self.t1, START + timedelta(minutes=5), START + timedelta(minutes=55),
                                      timedelta(minutes=5))
        self.assertEqual(len(frames.frames), 10)
        for frame in frames.frames:
            ph_at = read.value_at(self.ph.channel_no, frame.at)
            temperature_at = read.value_at(self.channel.channel_no, frame.at)
            self.assertEqual(frame.inputs['ph'].value, ph_at[1])
            self.assertEqual(frame.inputs['temperature_c'].value, temperature_at[1])
            self.assertEqual(frame.inputs['ph'].age_s, (frame.at - ph_at[0]).total_seconds())
            analysis = deffeyes.analyse(deffeyes.Water(temperature_c=temperature_at[1], salinity_ppt=0.0, ph=ph_at[1],
                                                       alkalinity_mg_l=100.0))
            self.assertAlmostEqual(frame.point.dic, analysis.dic, places=12)
            self.assertAlmostEqual(frame.point.alkalinity_meq, 100 / chemistry.MG_CACO3_PER_MEQ, places=12)
            self.assertAlmostEqual(frame.point.co2_mg_l, analysis.co2_mg_l, places=9)
            self.assertEqual(frame.missing, ())

    def test_mixed_origins_are_named(self):
        self.steady()
        frame = read.deffeyes_frames(self.t1, START + timedelta(minutes=30), START + timedelta(minutes=31),
                                     timedelta(minutes=1)).frames[0]
        self.assertEqual({code: item.origin for code, item in frame.inputs.items()},
                         {'ph': 'sensor', 'temperature_c': 'system_sensor', 'alkalinity_mg_l': 'manual',
                          'salinity_ppt': 'manual'})

    def test_a_gap_longer_than_the_freshness_is_missing_never_interpolated(self):
        self.steady(minutes=30)                                          # nothing after 30 min
        frames = read.deffeyes_frames(self.t1, START + timedelta(minutes=25), START + timedelta(minutes=60),
                                      timedelta(minutes=5)).frames
        late = [frame for frame in frames if frame.at >= START + timedelta(minutes=35)]
        self.assertTrue(late)
        for frame in late:
            self.assertIsNone(frame.point)
            self.assertIn('temperature_c', frame.missing)                   # fresh 180 s only
        self.assertIsNotNone(frames[0].point)

    def test_a_moved_sensor_counts_for_the_tank_it_was_in(self):
        self.steady()
        bindings.move(self.user, self.ph, point=self.mid2, at=START + timedelta(minutes=30))
        first = read.deffeyes_frames(self.t1, START + timedelta(minutes=20), START + timedelta(minutes=40),
                                     timedelta(minutes=10)).frames
        self.assertEqual([frame.inputs.get('ph') is not None for frame in first], [True, False])
        second = read.deffeyes_frames(self.t2, START + timedelta(minutes=20), START + timedelta(minutes=40),
                                      timedelta(minutes=10)).frames
        self.assertEqual([frame.inputs.get('ph') is not None for frame in second], [False, True])

    def test_one_query_of_the_readings_per_tier(self):
        self.steady()
        with CaptureQueriesContext(connection) as queries:
            read.deffeyes_frames(self.t1, START, START + timedelta(hours=1), timedelta(minutes=1))
        readings = [query for query in queries if 'sensors_reading' in query['sql'] or 'sensors_rollup' in query['sql']]
        self.assertEqual(len(readings), 1)

    def test_the_hour_tier_takes_the_last_value_of_each_hour_ended_before_the_frame(self):
        insert(self.ph.channel_no, [(START + timedelta(minutes=m), 7.0 + m / 1000) for m in range(0, 180, 5)])
        Channel.objects.filter(pk=self.ph.pk).update(heartbeat_s=3600)       # fresh for three hours
        Channel.objects.filter(pk=self.channel.pk).update(heartbeat_s=3600)
        insert(self.channel.channel_no, [(START + timedelta(minutes=m), 10.0) for m in range(0, 180, 30)])
        frames = read.deffeyes_frames(self.t1, START + timedelta(hours=1), START + timedelta(hours=3),
                                      timedelta(hours=1))
        self.assertEqual(frames.tier, read.ROLLUP_1H)
        first = frames.frames[0]                                              # at 01:00: the hour 00:00-01:00 ended
        self.assertEqual(first.inputs['ph'].value, 7.0 + 55 / 1000)

    def test_the_step_is_snapped_to_the_ladder_and_the_frames_capped(self):
        found = read.deffeyes_frames(self.t1, START, START + timedelta(days=30), timedelta(seconds=7))
        self.assertLessEqual(len(found.frames), read.FRAMES_CAP)
        self.assertIn(found.step, read.LADDER)


class EndpointTests(ReplayCase):
    def test_the_json_has_the_diagram_once_and_every_frame_inside_its_box(self):
        self.steady()
        user = get_user_model().objects.create_user('reader', 'reader@example.com', 'x')
        user.groups.add(role('Reader', 'view_reading', 'view_watermeasurement'))
        self.client.force_login(user)
        response = self.client.get(reverse('sensors:deffeyes_frames'), {
            'target': f'unit:{self.t1.pk}', 'start': '2026-10-10T00:05', 'end': '2026-10-10T00:55', 'step': '300'})
        self.assertEqual(response.status_code, 200)
        found = json.loads(response.content)
        self.assertTrue(found['diagram'].startswith('<'))
        self.assertEqual(len(found['frames']), 10)
        box = found['box']
        for frame in found['frames']:
            self.assertLessEqual(frame['point']['dic'], box['dic'])
            self.assertLessEqual(frame['point']['alkalinity_meq'], box['alkalinity'])
            self.assertEqual(set(frame['inputs']), {'ph', 'temperature_c', 'alkalinity_mg_l', 'salinity_ppt'})

    def test_it_needs_both_rights(self):
        user = get_user_model().objects.create_user('reader', 'reader@example.com', 'x')
        user.groups.add(role('Reader', 'view_reading'))
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse('sensors:deffeyes_frames'), {'target': f'unit:{self.t1.pk}'})
                         .status_code, 403)

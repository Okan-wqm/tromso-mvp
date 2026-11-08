"""The Deffeyes replay (owner amendments A6, A7, A8): `sensors.read.deffeyes_frames(target, start, end, step, cursor)`,
the unit's (or system's) water at each step of a range, a page of at most PAGE frames at a time: every input in the A1
order at that moment (a fresh sensor value at or before it, carried no longer than the channel's freshness; else a fresh
sample; else missing, never invented), and the whole diagram of that moment's water worked out by farm/water/deffeyes.py
(every frame its own geometry, frames whose diagram reads exactly the same inputs sharing one), one query of the readings
per tier and page; and its JSON endpoint: the page's figures once each, the frames as columns, the cursor of the next page."""
import gzip
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
from farm.water import calculation, chemistry, deffeyes, read as water_read, services as water_services

from sensors import bindings, read
from sensors.models import Channel

from . import SensorsCase, make_channel

START = datetime(2026, 10, 10, tzinfo=tz.utc)


def insert(channel_no, rows):
    with connection.cursor() as cursor:
        for at, value in rows:                                        # one row per statement
            cursor.execute('INSERT INTO sensors_reading (channel_no, ts, value) VALUES (%s, %s, %s)',
                           [channel_no, at, value])


def readings_queries(queries):
    return [query for query in queries if 'sensors_reading' in query['sql'] or 'sensors_rollup' in query['sql']]


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

    def figure_at(self, frames, frame):
        """The figure of the unit's own chart at the frame's moment (calculation.chart_of with `at`), in the page's box."""
        analysis = calculation.chart_of(frames.target, at=frame.at).calculation.analysis
        extent = [(each.point.dic, each.point.alkalinity_meq) for each in frames.frames if each.point is not None]
        # A page's figure leaves its point out (None): the diagram does not read the pH, the alkalinity or the oxygen
        # (sensors/tests/test_page_share.py proves it), so frames of one diagram share it and carry their own point.
        return {**deffeyes.figure(analysis, deffeyes.geometry(analysis, extent=extent)), 'point': None}


class FrameTests(ReplayCase):
    def test_each_frame_holds_the_value_at_its_moment_and_the_diagrams_point(self):
        self.steady()
        frames = read.deffeyes_frames(self.t1, START + timedelta(minutes=5), START + timedelta(minutes=55),
                                      timedelta(minutes=5))
        self.assertEqual(len(frames.frames), 10)
        for frame in frames.frames:
            # The value at the moment as the water parameter takes it (its decimals), as the unit's chart reads it.
            ph_at = read.value_at(self.ph.channel_no, frame.at)
            temperature_at = read.value_at(self.channel.channel_no, frame.at)
            ph = float(water_read.as_parameter('ph', ph_at[1]))
            temperature = float(water_read.as_parameter('temperature_c', temperature_at[1]))
            self.assertEqual(frame.inputs['ph'].value, ph)
            self.assertEqual(frame.inputs['temperature_c'].value, temperature)
            self.assertEqual(frame.inputs['ph'].age_s, (frame.at - ph_at[0]).total_seconds())
            analysis = deffeyes.analyse(deffeyes.Water(temperature_c=temperature, salinity_ppt=0.0, ph=ph, alkalinity_mg_l=100.0))
            self.assertAlmostEqual(frame.point.dic, analysis.dic, places=12)
            self.assertAlmostEqual(frame.point.alkalinity_meq, 100 / chemistry.MG_CACO3_PER_MEQ, places=12)
            self.assertAlmostEqual(frame.point.co2_mg_l, analysis.co2_mg_l, places=9)
            self.assertEqual(frame.missing, ())

    def test_every_frame_carries_the_whole_diagram_of_its_moment(self):
        # A8: the isolines, the regions, the borders, the Ω lines, the names and the notes are worked out from the water
        # of that moment, by farm/water/deffeyes.py: the unit's own chart at that moment, in the page's box.
        self.steady()
        frames = read.deffeyes_frames(self.t1, START + timedelta(minutes=5), START + timedelta(minutes=55),
                                      timedelta(minutes=5))
        for frame in frames.frames:
            with self.subTest(at=frame.at):
                self.assertEqual(frames.figures[frame.figure], self.figure_at(frames, frame))
        # One figure for each different diagram (the water but its pH, alkalinity and oxygen, at the parameters'
        # decimals): the frames of one diagram share it.
        waters = {}
        for frame in frames.frames:
            waters.setdefault(tuple(sorted((code, item.value) for code, item in frame.inputs.items()
                                           if code not in ('ph', 'alkalinity_mg_l', 'oxygen_mg_l'))), set()).add(
                frame.figure)
        self.assertEqual(len(frames.figures), len(waters))
        self.assertGreater(len(waters), 5)
        self.assertTrue(all(len(figures) == 1 for figures in waters.values()))
        boxes = {tuple(figure['box']) for figure in frames.figures}
        self.assertEqual(len(boxes), 1)                                     # one box a page: the points move, not the axes

    def test_frames_reading_exactly_the_same_water_share_one_figure(self):
        insert(self.ph.channel_no, [(START + timedelta(minutes=m), 7.2) for m in range(0, 60, 5)])
        insert(self.channel.channel_no, [(START + timedelta(minutes=m), 11.0) for m in range(60)])
        oxygen = make_channel(self.device, 'oxygen_mg_l')
        bindings.move(self.user, oxygen, point=self.mid1, at=START - timedelta(days=1))
        insert(oxygen.channel_no, [(START + timedelta(minutes=m), 9.0 + m / 10) for m in range(60)])
        frames = read.deffeyes_frames(self.t1, START + timedelta(minutes=5), START + timedelta(minutes=55),
                                      timedelta(minutes=5))
        # The oxygen moves, but the diagram never reads it: one figure, and it is each frame's own.
        self.assertEqual(len({frame.inputs['oxygen_mg_l'].value for frame in frames.frames}), 10)
        self.assertEqual(len(frames.figures), 1)
        for frame in frames.frames:
            self.assertEqual(frame.figure, 0)
            self.assertEqual(frames.figures[0], self.figure_at(frames, frame))

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
            self.assertIsNone(frame.figure)
            self.assertIn('temperature_c', frame.missing)                   # fresh 180 s only
        self.assertIsNotNone(frames[0].point)

    def test_a_water_that_cannot_be_has_no_diagram_and_says_why(self):
        insert(self.ph.channel_no, [(START, 12.4)])                         # pH 12.4 with 100 mg/L alkalinity
        insert(self.channel.channel_no, [(START, 10.0)])
        frame = read.deffeyes_frames(self.t1, START, START + timedelta(minutes=1), timedelta(minutes=1)).frames[0]
        self.assertEqual(frame.missing, ())
        self.assertIsNone(frame.point)
        self.assertIsNone(frame.figure)
        self.assertEqual(frame.impossible, deffeyes.why_impossible(10.0, 0.0, 12.4, 100.0))
        self.assertTrue(frame.impossible)

    def test_a_moved_sensor_counts_for_the_tank_it_was_in(self):
        self.steady()
        bindings.move(self.user, self.ph, point=self.mid2, at=START + timedelta(minutes=30))
        first = read.deffeyes_frames(self.t1, START + timedelta(minutes=20), START + timedelta(minutes=40),
                                     timedelta(minutes=10)).frames
        # At 00:30 the sensor is in T-02; T-01 keeps the value it measured there at 00:25, fresh for 15 min.
        self.assertEqual([frame.inputs['ph'].value for frame in first],
                         [float(water_read.as_parameter('ph', value)) for value in (7.020, 7.025)])
        second = read.deffeyes_frames(self.t2, START + timedelta(minutes=20), START + timedelta(minutes=40),
                                      timedelta(minutes=10)).frames
        self.assertEqual([frame.inputs.get('ph') is not None for frame in second], [False, True])

    def test_the_hour_tier_takes_the_last_value_of_each_hour_ended_before_the_frame(self):
        insert(self.ph.channel_no, [(START + timedelta(minutes=m), 7.0 + m / 1000) for m in range(0, 180, 5)])
        Channel.objects.filter(pk=self.ph.pk).update(heartbeat_s=3600)       # fresh for three hours
        Channel.objects.filter(pk=self.channel.pk).update(heartbeat_s=3600)
        insert(self.channel.channel_no, [(START + timedelta(minutes=m), 10.0) for m in range(0, 180, 30)])
        frames = read.deffeyes_frames(self.t1, START + timedelta(hours=1), START + timedelta(hours=3),
                                      timedelta(hours=1))
        self.assertEqual(frames.tier, read.ROLLUP_1H)
        first = frames.frames[0]                                              # at 01:00: the hour 00:00-01:00 ended
        self.assertEqual(first.inputs['ph'].value, float(water_read.as_parameter('ph', 7.0 + 55 / 1000)))


class PageTests(ReplayCase):
    def test_a_long_range_comes_in_pages_of_at_most_PAGE_frames(self):
        # A7: the user's step is kept (on the ladder), never widened to fit a cap: 5 000 minutes at one minute are 5 000
        # frames, in pages of 2 000, 2 000 and 1 000, each page's first frame at its cursor.
        end = START + timedelta(minutes=5000)
        cursor, sizes = 0, []
        while cursor is not None:
            page = read.deffeyes_frames(self.t1, START, end, timedelta(minutes=1), cursor=cursor)
            self.assertEqual((page.total, page.cursor, page.step), (5000, cursor, timedelta(minutes=1)))
            self.assertEqual(page.frames[0].at, START + cursor * timedelta(minutes=1))
            sizes.append(len(page.frames))
            cursor = page.next
        self.assertEqual(read.PAGE, 2000)
        self.assertEqual(sizes, [2000, 2000, 1000])

    def test_the_step_is_snapped_to_the_ladder(self):
        found = read.deffeyes_frames(self.t1, START, START + timedelta(hours=1), timedelta(seconds=7))
        self.assertEqual(found.step, timedelta(seconds=15))
        self.assertEqual(found.total, 240)

    def test_a_cursor_outside_the_range_is_refused(self):
        for cursor in (-1, 60):
            with self.subTest(cursor=cursor), self.assertRaises(ValueError):
                read.deffeyes_frames(self.t1, START, START + timedelta(hours=1), timedelta(minutes=1), cursor=cursor)

    def test_pages_give_the_frames_one_range_gives(self):
        # A page's first frames take the values from before the page (still fresh) exactly as one long page does.
        self.steady()
        start, end, step = START + timedelta(minutes=3), START + timedelta(minutes=58), timedelta(minutes=1)
        whole = read.deffeyes_frames(self.t1, start, end, step)
        paged, cursor = [], 0
        while cursor is not None:
            page = read.deffeyes_frames(self.t1, start, end, step, cursor=cursor, size=7)
            paged.extend(page.frames)
            cursor = page.next
        strip = lambda frame: (frame.at, frame.inputs, frame.point, frame.missing, frame.impossible)  # noqa: E731
        self.assertEqual([strip(frame) for frame in paged], [strip(frame) for frame in whole.frames])

    def test_one_query_of_the_readings_per_tier_and_page(self):
        self.steady()
        for step, size in ((timedelta(minutes=1), 20), (timedelta(hours=1), 2000)):
            with self.subTest(step=step), CaptureQueriesContext(connection) as queries:
                read.deffeyes_frames(self.t1, START, START + timedelta(hours=3), step, cursor=1, size=size)
            self.assertEqual(len(readings_queries(queries)), 1)


class EndpointTests(ReplayCase):
    def reader(self):
        user = get_user_model().objects.create_user('reader', 'reader@example.com', 'x')
        user.groups.add(role('Reader', 'view_reading', 'view_watermeasurement'))
        self.client.force_login(user)

    def get(self, **params):
        return self.client.get(reverse('sensors:deffeyes_frames'), {
            'target': f'unit:{self.t1.pk}', 'start': '2026-10-10T00:05', 'end': '2026-10-10T00:55', 'step': '300',
            **params})

    def test_a_page_is_sent_compressed_to_a_browser_that_takes_gzip(self):
        """Owner amendment B4: the replay endpoint compresses its page (the figures are geometry, no secret)."""
        self.steady()
        self.reader()
        plain = self.get()
        packed = self.client.get(reverse('sensors:deffeyes_frames'), {
            'target': f'unit:{self.t1.pk}', 'start': '2026-10-10T00:05', 'end': '2026-10-10T00:55', 'step': '300'},
            HTTP_ACCEPT_ENCODING='gzip')
        self.assertNotIn('Content-Encoding', plain)
        self.assertEqual(packed['Content-Encoding'], 'gzip')
        self.assertLess(len(packed.content), len(plain.content))
        self.assertEqual(json.loads(gzip.decompress(packed.content)), json.loads(plain.content))

    def test_a_page_has_each_figure_once_and_the_frames_as_columns(self):
        self.steady()
        self.reader()
        response = self.get()
        self.assertEqual(response.status_code, 200)
        found = json.loads(response.content)
        frames = read.deffeyes_frames(self.t1, START + timedelta(minutes=5), START + timedelta(minutes=55),
                                      timedelta(minutes=5))
        self.assertEqual((found['total'], found['cursor'], found['next'], found['step_s']), (10, 0, None, 300.0))
        self.assertEqual(found['first'], frames.frames[0].at.isoformat())
        self.assertEqual(found['figures'], frames.figures)
        columns = found['frames']
        self.assertEqual(columns['figure'], [frame.figure for frame in frames.frames])
        self.assertEqual(columns['dic'], [frame.point.dic for frame in frames.frames])
        self.assertEqual(columns['inputs']['ph']['value'], [frame.inputs['ph'].value for frame in frames.frames])
        self.assertEqual(columns['inputs']['ph']['origin'], ['sensor'] * 10)
        self.assertEqual(set(columns['inputs']), {'ph', 'temperature_c', 'alkalinity_mg_l', 'salinity_ppt'})
        # The server's SVG of a frame is drawn from the figure the player gets and the frame's own point.
        figure = {**found['figures'][columns['figure'][3]], 'point': [columns['dic'][3], columns['alkalinity_meq'][3]]}
        point = frames.frames[3].point
        self.assertEqual(deffeyes.render(figure), deffeyes.render({**frames.figures[frames.frames[3].figure],
                                                                   'point': [point.dic, point.alkalinity_meq]}))
        self.assertNotIn('diagram', found)

    def test_the_next_page_is_asked_by_its_cursor(self):
        self.steady()
        self.reader()
        first = json.loads(self.get(step='60', start='2026-10-10T00:00', end='2026-10-11T12:00').content)
        self.assertEqual((first['total'], first['next']), (2160, 2000))
        second = json.loads(self.get(step='60', start='2026-10-10T00:00', end='2026-10-11T12:00',
                                     cursor=str(first['next'])).content)
        self.assertEqual((second['cursor'], second['next'], len(second['frames']['figure'])), (2000, None, 160))
        self.assertEqual(self.get(cursor='2160').status_code, 400)
        self.assertEqual(self.get(cursor='x').status_code, 400)

    def test_it_needs_both_rights(self):
        user = get_user_model().objects.create_user('reader', 'reader@example.com', 'x')
        user.groups.add(role('Reader', 'view_reading'))
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse('sensors:deffeyes_frames'), {'target': f'unit:{self.t1.pk}'})
                         .status_code, 403)

    def test_a_range_outside_the_window_of_dates_is_refused_never_a_server_error(self):
        """`start` and `end` are typed into an address: the calendar's ends (an overflow on the site's clock) and
        anything outside 1900-2100 are refused (400) through core.dates.read_moment."""
        self.reader()
        for start, end in (('0001-01-01T00:30', '0001-01-02T00:30'), ('9999-12-30T00:00', '9999-12-31T00:00'),
                           ('1899-12-30T00:00', '1899-12-31T00:00'), ('2026-10-10', '2026-10-11')):
            with self.subTest(start=start, end=end):
                self.assertEqual(self.get(start=start, end=end).status_code, 400)

    def test_a_step_longer_than_any_time_is_refused_never_a_server_error(self):
        self.reader()
        for step in ('100000000000000000', '9' * 40):            # a short step is snapped up to the ladder, kept
            with self.subTest(step=step):
                self.assertEqual(self.get(step=step).status_code, 400)


def insert_many(channel_no, rows):
    """[(ts, value, quality)] of one channel in one statement."""
    with connection.cursor() as cursor:
        cursor.execute('INSERT INTO sensors_reading (channel_no, ts, value, quality) '
                       'SELECT %s, * FROM unnest(%s::timestamptz[], %s::float8[], %s::smallint[])',
                       [channel_no, [at for at, *_rest in rows], [value for _at, value, _q in rows],
                        [quality for *_rest, quality in rows]])


def scanned(sql):
    """How many rows of the readings' chunks a query reads (returned and filtered out), from its EXPLAIN ANALYZE."""
    with connection.cursor() as cursor:
        cursor.execute('EXPLAIN (ANALYZE, FORMAT JSON) ' + sql)
        plan = cursor.fetchone()[0]
    plan = json.loads(plan) if isinstance(plan, str) else plan
    total, nodes = 0, [plan[0]['Plan']]
    while nodes:
        node = nodes.pop()
        nodes.extend(node.get('Plans', []))
        if node.get('Relation Name', '').startswith('_hyper_'):
            total += (node['Actual Rows'] + node.get('Rows Removed by Filter', 0)) * node['Actual Loops']
    return total


class ValueAtTests(ReplayCase):
    """Each frame's sensor value is what the live view's rule gives at the frame's moment (`sensors.provider` value_at:
    the channel's newest clean reading at or before the moment, taken while it was bound there), within the channel's
    freshness: on irregular readings with bad ones among them, readings exactly on a frame's moment, gaps longer than the
    freshness, a backup channel and a sensor moved away and back, at every step of the raw tier, page by page."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from random import Random
        rng = Random(20261108)
        cls.backup = make_channel(cls.device, 'ph', code='PH-B')                  # fresh 900 s
        bindings.move(cls.user, cls.backup, point=cls.mid1, role='backup', at=START - timedelta(days=1))
        # The pH probe goes to T-02 for 40 minutes and comes back.
        bindings.move(cls.user, cls.ph, point=cls.mid2, at=START + timedelta(minutes=100, seconds=7))
        bindings.move(cls.user, cls.ph, point=cls.mid1, at=START + timedelta(minutes=140, seconds=3))
        gaps = {cls.channel.channel_no: (0.2, 0.7, 1, 1, 1, 2, 3, 5, 30, 200, 400),
                cls.ph.channel_no: (5, 20, 60, 120, 600, 1200),
                cls.backup.channel_no: (60, 300, 900, 1500)}
        cls.rows = {}
        for number, choices in gaps.items():
            at, made = START - timedelta(minutes=20), []
            while at < START + timedelta(hours=3, minutes=10):
                if rng.random() < 0.1:                                     # exactly on a frame's moment (pages())
                    at = at.replace(second=7, microsecond=250000) + timedelta(minutes=1)
                else:
                    at += timedelta(microseconds=int(rng.choice(choices) * rng.uniform(0.5, 1.5) * 1e6))
                quality = rng.choice((0,) * 16 + (1, 8, 32, 64, 16, 128))    # good, heartbeat, late, and bad ones
                made.append((at, round(rng.uniform(6.5, 12.5), 4), quality))
            insert_many(number, made)
            cls.rows[number] = made

    def pages(self):
        """Every page of the raw tier's steps over the readings, from a moment on no whole second."""
        start = START + timedelta(seconds=7, microseconds=250000)
        for step, frames, size in ((timedelta(seconds=1), 360, 150), (timedelta(seconds=5), 300, 120),
                                   (timedelta(seconds=15), 300, 120), (timedelta(minutes=1), 190, 70),
                                   (timedelta(minutes=5), 38, 2000), (timedelta(minutes=30), 6, 2000)):
            cursor = 0
            while cursor is not None:
                page = read.deffeyes_frames(self.t1, start, start + frames * step, step, cursor=cursor, size=size)
                self.assertEqual(page.tier, read.RAW)
                yield step, page
                cursor = page.next

    def test_each_frames_sensor_value_is_value_at_of_its_channel_at_its_moment(self):
        from farm.water import sources
        from sensors.provider import PROVIDER
        targets = {'sensor': (sources.POINT, self.mid1.pk), 'system_sensor': (sources.SYSTEM, self.ras.pk)}
        seen = {}
        for step, page in self.pages():
            for frame in page.frames:
                for code in ('ph', 'temperature_c'):
                    item = frame.inputs.get(code)
                    if item is None or item.channel_no is None:
                        continue
                    with self.subTest(step=step, at=frame.at, code=code):
                        target = targets[item.origin]
                        found = {value.channel_no: value
                                 for value in PROVIDER.value_at([target], code, frame.at).get(target, [])}
                        expected = found[item.channel_no]
                        self.assertLessEqual(frame.at - expected.at, timedelta(seconds=expected.fresh_for))
                        self.assertEqual(item.value, float(water_read.as_parameter(code, expected.value)))
                        self.assertEqual(item.age_s, (frame.at - expected.at).total_seconds())
                    seen[(step, code)] = seen.get((step, code), 0) + 1
        self.assertEqual(len(seen), 12)                                   # both inputs from a sensor at every step

    def test_the_rows_are_each_segments_newest_clean_reading_at_each_moment_within_its_freshness(self):
        """`replay_rows` gives, for every segment and moment, the segment's newest clean reading at or before the moment
        and inside its binding when it is no older than the channel's freshness; nothing else (a staler value is never
        used)."""
        from sensors.quality import BAD_MASK
        given = on_the_moment = 0
        for step, page in self.pages():
            first, count = page.frames[0].at, len(page.frames)
            found = [segment for code in read.REPLAY_INPUTS
                     for segment in read.segments(self.t1, code, first - read.CARRY, first + count * step)]
            rows = read.replay_rows(found, first, step, count, read.RAW)
            expected = {}
            for index, segment in enumerate(found):
                clean = [(at, value) for at, value, quality in self.rows.get(segment.channel_no, [])
                         if not quality & BAD_MASK and segment.start <= at < segment.end]
                for slot in range(count):
                    moment = first + slot * step
                    before = [row for row in clean if row[0] <= moment]
                    if before and moment - before[-1][0] <= timedelta(seconds=segment.fresh_s):
                        expected[(index, slot)] = before[-1]
                        on_the_moment += before[-1][0] == moment
            given += len(expected)
            with self.subTest(step=step, cursor=page.cursor):
                self.assertEqual(rows, expected)
        self.assertGreater(given, 1000)
        self.assertGreater(on_the_moment, 10)                            # a reading exactly at a frame counts for it

    def test_a_page_reads_about_one_reading_per_frame_and_channel_never_every_reading_of_its_span(self):
        """The readings query of a raw page reads about the readings it gives (one per frame and segment), not every
        reading of the page's span: at a minute's step over 1 Hz readings it read sixty times more."""
        dense = make_channel(self.device, 'temperature_c', code='T-DENSE', heartbeat_s=60)
        bindings.move(self.user, dense, point=self.mid1, at=START - timedelta(days=1))
        insert_many(dense.channel_no, [(START + timedelta(seconds=second), 10.0 + second / 1e4, 0)
                                       for second in range(4 * 3600)])
        first, count, step = START + timedelta(minutes=20), 200, timedelta(minutes=1)
        with CaptureQueriesContext(connection) as queries:
            read.deffeyes_frames(self.t1, first, first + count * step, step)
        (query,) = readings_queries(queries)
        # The dense probe and the system's temperature, the pH probe before and after its stay in T-02, the backup.
        segments = [segment for code in read.REPLAY_INPUTS
                    for segment in read.segments(self.t1, code, first - read.CARRY, first + count * step)]
        self.assertEqual(len(segments), 5)
        self.assertLessEqual(scanned(query['sql']), 2 * count * len(segments))

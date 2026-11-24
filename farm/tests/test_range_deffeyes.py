"""Deffeyes for the range (farm/water/views.py `range_deffeyes`, Tank › Water) on frames made here, so every branch is
reached whatever the world: the path's points are the one placing's (`deffeyes.pixel`) of the frames' DIC and alkalinity,
broken at a frame without a diagram and never bridged; a run of one frame is a dot (a polyline of one point draws
nothing); the star is the newest drawn water, named with its time; when the window's last frame has no diagram the chart
says so in words with what is missing (review of batch 1, F2), and without any diagram the reason alone; nothing for a
person who may not read the sensors. The diagram itself is the server's (`render`), tested in test_deffeyes."""
from datetime import datetime, timedelta, timezone as tz
from types import SimpleNamespace
from unittest import mock
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase, override_settings

from sensors.read import FramePoint, Frame, Frames

from ..water import deffeyes, views

START = datetime(2026, 11, 20, 0, 0, tzinfo=tz.utc)
STEP = timedelta(hours=3)
BOX = (6.0, 6.0, 1.0, 1.0)
DRAWING = {'isolines': [{'label': {'text': 'pH 5.0'}}, {'label': None}, {'label': {'text': 'pH 12.0'}}]}


def frame(index, dic=None, missing=(), impossible=''):
    point = None if dic is None else FramePoint(dic=dic, alkalinity_meq=dic - 0.2, ph=7.2, co2_mg_l=12.0)
    return Frame(START + index * STEP, {}, point, missing=missing, impossible=impossible,
                 figure=None if point is None else 0)


class Person:
    def __init__(self, *rights):
        self.rights = rights

    def has_perm(self, right):
        return right in self.rights


SENSORS = Person(views.SENSOR_READ)


@override_settings(LANGUAGE_CODE='en')
class RangeDeffeyesTests(SimpleTestCase):
    def drawn(self, frames, user=SENSORS):
        found = Frames(None, START, START + len(frames) * STEP, STEP, 'raw', len(frames), 0, None, frames,
                       [{'box': BOX}])
        with mock.patch('sensors.read.deffeyes_frames', return_value=found), \
                mock.patch.object(views, 'site_of', return_value=None), \
                mock.patch.object(views, 'zone_of', return_value=ZoneInfo('Europe/Oslo')), \
                mock.patch.object(deffeyes, 'render', return_value={}), \
                mock.patch.object(deffeyes, 'as_props', return_value=DRAWING):
            return views.range_deffeyes(user, SimpleNamespace(), START, START + len(frames) * STEP)

    def at(self, dic):
        x, y = deffeyes.pixel(deffeyes.Box(*BOX), dic, dic - 0.2)
        return f'{x:.2f},{y:.2f}'

    def test_the_path_is_the_placing_of_each_frame_broken_where_one_has_no_diagram(self):
        found = self.drawn([frame(0, 1.0), frame(1, 1.5), frame(2, missing=('alkalinity_mg_l',)), frame(3, 2.0),
                            frame(4, 2.5), frame(5, 3.0)])
        self.assertEqual(found['path'], [f'{self.at(1.0)} {self.at(1.5)}', f'{self.at(2.0)} {self.at(2.5)} {self.at(3.0)}'])
        self.assertEqual(found['dots'], [])
        self.assertEqual((found['first']['x'], found['first']['y']), tuple(self.at(1.0).split(',')))
        self.assertEqual(found['at'], int((START + 5 * STEP).timestamp()))
        self.assertEqual((found['stale'], found['now_status']), ('', ''))
        self.assertEqual(found['now'], 'The water at 20.11.2026 16:00')               # the site's clock
        self.assertEqual(found['words']['water'], found['now'])
        self.assertIn('pH isolines are those of the newest water drawn', found['caption'])
        self.assertIn('pH 5.0 to pH 12.0', found['scale'])

    def test_a_run_of_one_frame_is_a_dot(self):
        found = self.drawn([frame(0, 1.0), frame(1), frame(2, 2.0), frame(3, 2.5)])
        x, y = self.at(1.0).split(',')
        self.assertEqual(found['dots'], [{'x': x, 'y': y, 'at': int(START.timestamp())}])
        self.assertEqual(found['path'], [f'{self.at(2.0)} {self.at(2.5)}'])

    def test_a_window_whose_end_has_no_diagram_says_so_and_names_the_star_with_its_time(self):
        found = self.drawn([frame(0, 1.0), frame(1, 1.5), frame(2, missing=('alkalinity_mg_l',)),
                            frame(3, missing=('alkalinity_mg_l',))])
        self.assertEqual(found['now_status'], 'warning')
        self.assertEqual(found['stale'], 'No diagram after 20.11.2026 04:00: no fresh value of Alkalinity (mg/L as CaCO₃)')
        self.assertEqual(found['now'], found['stale'])
        self.assertEqual(found['words']['water'], 'The water at 20.11.2026 04:00')
        self.assertIn(['No diagram', found['stale']], found['said'])
        impossible = self.drawn([frame(0, 1.0), frame(1, impossible='pH and alkalinity cannot go together')])
        self.assertTrue(impossible['stale'].endswith(': pH and alkalinity cannot go together'))

    def test_without_any_diagram_the_reason_alone(self):
        found = self.drawn([frame(0, missing=('ph',)), frame(1, missing=('ph', 'alkalinity_mg_l'))])
        self.assertIsNone(found['chart'])
        self.assertEqual(found['reason'], 'No frame of this time has every value the chart needs: pH (NBS scale), '
                                          'Alkalinity (mg/L as CaCO₃).')

    def test_nothing_for_a_person_who_may_not_read_the_sensors(self):
        self.assertIsNone(self.drawn([frame(0, 1.0)], user=Person()))

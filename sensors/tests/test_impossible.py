"""A replay frame whose pH and alkalinity cannot go together (sensors/read.py `frame_analysis`): the core refuses such a
water (native.ImpossibleWaterError, the correction of 2026-11-10); the frame is refused first, by the same rule, with the
reason the calculator and a unit's chart say, so a page of frames never fails on one."""
import math

from django.test import SimpleTestCase

from farm.water import deffeyes, native, parameters
from sensors import read

LIMITS = {'nh3_n_limit_mg_l': 0.0103, 'co2_limit_mg_l': 15.0}


def values(ph, alkalinity_mg_l, **more):
    return {parameters.TEMPERATURE: 10.0, parameters.SALINITY: 0.0, parameters.PH: ph,
            'alkalinity_mg_l': alkalinity_mg_l, 'water_origin': '', **more}


class FrameAnalysisTests(SimpleTestCase):
    def test_an_impossible_frame_has_its_reason_and_no_analysis(self):
        analysis, why = read.frame_analysis(values(12.4, 100.0), LIMITS)
        self.assertIsNone(analysis)
        self.assertEqual(why, deffeyes.why_impossible(10.0, 0.0, 12.4, 100.0))
        self.assertIn('At this pH the alkalinity is above', why)
        with self.assertRaises(native.ImpossibleWaterError):                 # what the core says to anyone who asks
            deffeyes.analyse(deffeyes.Water(10.0, 0.0, 12.4, 100.0))

    def test_a_possible_frame_is_worked_out_above_0(self):
        analysis, why = read.frame_analysis(values(7.2, 100.0, tan_mg_l=0.5), LIMITS)
        self.assertEqual(why, '')
        self.assertGreater(analysis.dic, 0.0)
        self.assertGreater(analysis.co2_mg_l, 0.0)

    def test_the_reason_and_the_refusal_are_one_decision_beside_the_floor(self):
        """With the frame's own ions (a conductivity, a hardness), on both sides of the floor and a last digit from it."""
        for ions in ({}, {'conductivity_25_us_cm': 800.0}, {'hardness_mg_l': 150.0}):
            for ph in (9.5, 10.5, 11.5):
                floor = native.alkalinity_floor(10.0, 0.0, ph, 60.0, **ions)
                for alkalinity in (floor * 0.5, floor - 1e-9, math.nextafter(floor, 0), floor,
                                   math.nextafter(floor, math.inf), floor + 1e-9, floor * 2):
                    with self.subTest(ions=ions, ph=ph, alkalinity=alkalinity):
                        analysis, why = read.frame_analysis(values(ph, alkalinity, **ions), LIMITS)   # never raises
                        self.assertEqual(analysis is None, bool(why))

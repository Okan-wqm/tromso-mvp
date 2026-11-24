"""Feeding protocols, assignments, the ration and the projected weight: the table's lookup and interpolation, the
refusals outside it, the precedence of the assignment rows, a whole-batch row following a transfer, the projection
after each feeding and its reset at a weighing, the correction numbers and the worked example of
feeding-protocols §6.7; then the pages (Meal board, Records, Protocols, Assignments, the drawer, the weighing
dialog) against the stored rows, the permissions, the delete plan and the languages."""
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, transaction
from django.test import SimpleTestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from core import access, database, navigation
from core.models import AuditLog, Profile

from ..feeding import ration, read
from ..feeding.fold import Feeding, walk
from ..feeding.projection import Projector
from ..feeding.ration import Band, Cell, Policy, Table, sfr_at
from ..feeding.temperature import Temperature, TemperatureBook
from ..models import (
    Feed, FeedingProtocol, FeedingRecord, HandlingPlanItem, ProtocolAssignment, ProtocolBand, ProtocolRate, Site,
    StockOperation, System, Tank,
    WaterMeasurement,
)
from ..stock import read as stock_read, services as stock_services
from ..stock.dates import end_of, local_today
from ..stock.fold import Line, Op
from ..water import services as water_services, sources
from ..water.read import Found, Observation, Series
from .helpers import WINDOW_WAY_OUT, correction_window, make_facility, point_of, role
from .test_feeding import FeedingTestCase
from .test_stock import make_unit
from farm import withdrawal_gate

D = Decimal


def nov(day):
    return date(2026, 11, day)


def oct_(day):
    return date(2026, 10, day)


def cells(*pairs):
    return tuple(Cell(D(str(temperature)), D(str(sfr))) for temperature, sfr in pairs)


def band(low, high, meals=4, fcr=None, table=((12, '1.10'), (14, '1.30')), feed='GR-4', pk=1):
    return Band(pk, D(str(low)), None if high is None else D(str(high)), feed, meals,
                None if fcr is None else D(str(fcr)), cells(*table))


@dataclass
class Row:
    """An assignment row as the policy reads it (ProtocolAssignment's fields and covers())."""
    protocol_id: object
    unit_id: object = None
    batch_id: object = None
    valid_from: date = oct_(1)
    valid_until: date = None
    unit: object = None

    def covers(self, day):
        return self.valid_from <= day and (self.valid_until is None or day <= self.valid_until)

    @property
    def scope(self):
        return 'batch_in_unit' if self.unit_id and self.batch_id else 'unit' if self.unit_id else 'batch'


def protocol(name='Trout grow-out', species='S', fcr='1.00'):
    return SimpleNamespace(name=name, species_id=species, expected_fcr=D(fcr), pk=name, species=species,
                           __str__=lambda self: name)


def temperature(value='13.2', fresh=True):
    return Temperature(D(value), datetime(2026, 11, 2, 7, 40, tzinfo=dt_timezone.utc), 'T1', 'unit',
                       timedelta(hours=2), fresh)


def policy(rows=None, tables=None, species=None, temp=temperature()):
    tables = tables or {'P': Table(protocol(), (band(0, 50, fcr='0.90', pk=0), band(50, 100), band(100, None, pk=2)))}
    return Policy(rows if rows is not None else [Row('P', unit_id='T1')], tables, species or {'B1': 'S'},
                  lambda unit_id, day: temp)


class LookupTests(SimpleTestCase):
    def test_exact_column_and_linear_between_columns(self):
        table = cells((6, '0.60'), (12, '1.10'), (14, '1.30'))
        self.assertEqual(sfr_at(table, D('12')).value, D('1.10'))
        found = sfr_at(table, D('13.2'))
        self.assertEqual(found.value, D('1.22'))
        self.assertEqual((found.low.temperature_c, found.high.temperature_c, found.interpolated), (12, 14, True))
        self.assertEqual(sfr_at(table, D('9')).value, D('0.85'))
        self.assertFalse(sfr_at(table, D('6')).interpolated)

    def test_no_extrapolation_outside_the_table(self):
        table = cells((6, '0.60'), (14, '1.30'))
        self.assertIsNone(sfr_at(table, D('5.9')))
        self.assertIsNone(sfr_at(table, D('14.1')))
        self.assertIsNone(sfr_at((), D('10')))

    def test_a_band_is_from_its_lower_weight_up_to_not_including_its_upper_one(self):
        table = Table(protocol(), (band(0, 50, pk=0), band(50, 100), band(100, None, pk=2)))
        self.assertEqual(table.band_for(D('49.99')).id, 0)
        self.assertEqual(table.band_for(D('50')).id, 1)
        self.assertEqual(table.band_for(D('100')).id, 2)
        self.assertEqual(table.band_for(D('100000')).id, 2)
        lowest = Table(protocol(), (band(5, 50, pk=0),))
        self.assertIsNone(lowest.band_for(D('4.9')))                # below the first band: outside, not clamped
        self.assertIsNone(Table(protocol(), (band(5, 50),)).band_for(D('50')))

    def test_the_basis_says_why_there_is_no_ration(self):
        self.assertEqual(policy(rows=[]).basis('T1', 'B1', nov(2), D(80)).missing, ration.NO_PROTOCOL)
        narrow = {'P': Table(protocol(), (band(5, 50),))}
        self.assertEqual(policy(tables=narrow).basis('T1', 'B1', nov(2), D(80)).missing, ration.OUTSIDE_BANDS)
        self.assertEqual(policy(temp=None).basis('T1', 'B1', nov(2), D(80)).missing, ration.NO_TEMPERATURE)
        cold = policy(temp=temperature('4.0')).basis('T1', 'B1', nov(2), D(80))
        self.assertEqual((cold.missing, cold.fcr), (ration.OUTSIDE_TABLE, D('1.00')))   # the FCR needs the band only
        ok = policy().basis('T1', 'B1', nov(2), D(80))
        self.assertEqual((ok.missing, ok.sfr.value, ok.meals, ok.fcr, ok.fcr_source), ('', D('1.22'), 4, D('1.00'),
                                                                                         'protocol'))
        small = policy().basis('T1', 'B1', nov(2), D(20))
        self.assertEqual((small.fcr, small.fcr_source), (D('0.90'), 'band'))
        self.assertEqual(ok.ration_kg(D(1170)), D('14.274'))

    def test_precedence_batch_in_unit_then_unit_then_whole_batch(self):
        tables = {name: Table(protocol(name), (band(0, None),)) for name in ('pair', 'unit', 'batch')}
        rows = [Row('batch', batch_id='B1'), Row('unit', unit_id='T1'), Row('pair', unit_id='T1', batch_id='B1',
                                                                           valid_from=nov(1), valid_until=nov(1))]
        found = policy(rows, tables)
        self.assertEqual(found.basis('T1', 'B1', nov(1), D(10)).protocol.name, 'pair')
        self.assertEqual(found.basis('T1', 'B1', nov(2), D(10)).protocol.name, 'unit')
        self.assertEqual(found.basis('T2', 'B1', nov(2), D(10)).protocol.name, 'batch')     # wherever it is
        self.assertEqual(found.basis('T2', 'B9', nov(2), D(10)).missing, ration.NO_PROTOCOL)

    def test_a_units_row_for_another_species_is_read_past(self):
        tables = {'trout': Table(protocol('trout', species='RBT'), (band(0, None),)),
                  'salmon': Table(protocol('salmon'), (band(0, None),))}
        rows = [Row('trout', unit_id='T1', unit=SimpleNamespace(code='T-01')), Row('salmon', batch_id='B1')]
        self.assertEqual(policy(rows, tables).basis('T1', 'B1', nov(2), D(10)).protocol.name, 'salmon')
        alone = policy(rows[:1], tables).basis('T1', 'B1', nov(2), D(10))
        self.assertEqual((alone.missing, alone.skipped), (ration.NO_PROTOCOL, rows[0]))


# ---- the projection along the walk ---------------------------------------------------------------------
def op(seq, kind, day):
    return Op(f'op{seq}', kind, day, seq)


def line(line_id, operation, kind, delta, unit='T1', batch='B1', weight=None, pair=None):
    return Line(line_id, operation, unit, batch, kind, delta, None if weight is None else D(weight), pair)


def fed(day, kilos, unit='T1', name=None, meals=None, order=()):
    return Feeding(name or f'{unit}-{day.isoformat()}-{kilos}', unit, day, D(kilos), meals, order)


def project(lines, feedings, asked=(), found=None):
    projector = Projector(found or policy(), asked)
    walked = walk(lines, feedings, asked, projector=projector)
    return walked, projector


WEIGHED = [line(1, op(1, 'input', oct_(10)), 'input', 12000, weight='80'),
           line(2, op(2, 'weighing', oct_(20)), 'weighing', 0, weight='85')]
FIFTEEN_DAYS = [fed(oct_(20) + timedelta(days=n), 10) for n in range(15)]      # 150 kg, 20 Oct – 3 Nov


class ProjectionTests(SimpleTestCase):
    """The worked example of feeding-protocols §6.7: 12,000 fish weighed on 20 Oct at 85.0 g, 150 kg fed since in
    the 50–100 g band at FCR 1.00, 13.2 °C between the 12 °C (1.10 %) and 14 °C (1.30 %) columns."""

    def test_the_worked_example(self):
        _walked, projector = project(WEIGHED, FIFTEEN_DAYS, [('T1', nov(4))])
        today = projector.days[('T1', nov(4))]
        share = today.shares[0]
        self.assertEqual((share.fish, share.start_g, share.measured_g), (12000, D('97.5'), D('85')))
        self.assertEqual(share.end.sfr.value, D('1.22'))
        self.assertEqual(share.ration_kg, D('14.274'))                # 1,170 kg × 1.22 %
        self.assertEqual(share.next_meal_kg, D('3.5685'))             # 4 meals
        self.assertEqual((today.calculated_kg, today.fed_kg, today.deviation_kg), (D('14.274'), 0, D('-14.274')))

    def test_after_each_feeding_the_next_meal_is_computed_again(self):
        meal = fed(nov(4), '3.6', meals=1, name='first meal')
        _walked, projector = project(WEIGHED, [*FIFTEEN_DAYS, meal], [('T1', nov(4))])
        share = projector.days[('T1', nov(4))].shares[0]
        self.assertEqual(share.end_g, D('97.8'))                      # + 3.6 kg ÷ 1.00 over 12,000 fish
        self.assertEqual(share.ration_kg, D('14.31792'))
        self.assertEqual(share.next_meal_kg, D('3.57948'))
        self.assertEqual(share.remaining_kg, D('10.73844'))           # 3 meals left
        # The day's calculated ration: the first meal's portion at 97.5 g, the three to come at 97.8 g.
        self.assertEqual(share.calculated_kg, D('3.5685') + D('10.73844'))
        day = projector.days[('T1', nov(4))]
        self.assertEqual(day.deviation_kg, D('3.6') - D('14.30694'))

    def test_growth_is_credited_only_up_to_the_days_ration(self):
        big = fed(nov(4), '20', name='too much')                      # a day's 14.274 kg and 5.726 kg more
        _walked, projector = project(WEIGHED, [*FIFTEEN_DAYS, big], [('T1', nov(4))])
        share = projector.days[('T1', nov(4))].shares[0]
        self.assertEqual(share.credited_kg, D('14.274'))
        self.assertEqual(share.over_kg, D('5.726'))
        self.assertEqual(share.end_g, D('97.5') + D('14.274') * 1000 / 12000)

    def test_a_weighing_restarts_the_estimate_and_keeps_its_correction(self):
        weighing = line(3, op(3, 'weighing', nov(4)), 'weighing', 0, weight='94')
        _walked, projector = project([*WEIGHED, weighing], [*FIFTEEN_DAYS, fed(nov(4), '3.6')], [('T1', nov(4))])
        correction = projector.corrections[('T1', 'B1')][-1]
        self.assertEqual((correction.estimated_g, correction.measured_g, correction.fish), (D('97.5'), D('94'), 12000))
        self.assertEqual(correction.difference_g, D('-3.5'))
        self.assertEqual(correction.difference_kg, D('-42'))
        self.assertEqual(round(correction.difference_pct, 2), D('-3.59'))
        self.assertEqual((correction.since, correction.days, correction.expected_fcr), (oct_(20), 15, D('1.00')))
        # Realised: 150 kg fed from 20 Oct up to the weighing for (94.0 − 85.0) g × 12,000 fish = 108 kg grown.
        self.assertEqual(round(correction.realised_fcr, 4), D('1.3889'))
        share = projector.days[('T1', nov(4))].shares[0]
        self.assertEqual(share.start_g, D('94'))                      # weighed before the day's feeding
        self.assertEqual(share.end_g, D('94') + D('0.3'))

    def test_fish_that_leave_take_the_estimates_average(self):
        dead = line(3, op(3, 'mortality', nov(3)), 'mortality', -2000)
        _walked, projector = project([*WEIGHED, dead], FIFTEEN_DAYS[:-1], [('T1', nov(3))])
        share = projector.days[('T1', nov(3))].shares[0]
        # 14 days of 10 kg to 2 Nov: 85 g + 140 kg ÷ 12,000 = 96.667 g; the dead leave at it, 10,000 stay.
        self.assertEqual(share.fish, 10000)
        self.assertEqual(round(share.start_g, 3), D('96.667'))
        self.assertEqual(share.measured_g, D('85'))                   # the book keeps its measured average

    def test_a_whole_batch_row_follows_a_transfer_and_the_estimate_moves_with_the_fish(self):
        moved = op(3, 'transfer', nov(3))
        lines = [*WEIGHED, line(3, moved, 'transfer_out', -6000, pair=1),
                 line(4, moved, 'transfer_in', 6000, unit='T2', pair=1)]
        found = policy(rows=[Row('P', batch_id='B1')])
        _walked, projector = project(lines, [*FIFTEEN_DAYS[:-1], fed(nov(3), 5, unit='T2')],
                                     [('T1', nov(3)), ('T2', nov(3))], found)
        source, target = projector.days[('T1', nov(3))].shares[0], projector.days[('T2', nov(3))].shares[0]
        self.assertEqual(round(source.start_g, 3), round(target.start_g, 3))
        self.assertEqual(target.start.protocol.name, 'Trout grow-out')   # the batch's row, in the new unit
        self.assertEqual(target.measured_on, oct_(20))                   # the estimate's age came with the fish
        self.assertEqual(target.end_g, target.start_g + D(5) * 1000 / 6000)

    def test_feed_without_a_protocol_is_not_growth_and_is_counted(self):
        found = policy(rows=[Row('P', unit_id='T1', valid_from=nov(1))])
        _walked, projector = project(WEIGHED, FIFTEEN_DAYS, [('T1', nov(3))], found)
        share = projector.days[('T1', nov(3))].shares[0]
        self.assertEqual(share.blind_days, 12)                        # 20–31 Oct had no protocol
        self.assertEqual(share.end_g, D(85) + D(30) * 1000 / 12000)   # 1–3 Nov credited

    def test_no_temperature_still_credits_the_feed_without_a_ration(self):
        _walked, projector = project(WEIGHED, FIFTEEN_DAYS, [('T1', nov(3))], policy(temp=None))
        share = projector.days[('T1', nov(3))].shares[0]
        self.assertEqual((share.calculated_kg, share.end.missing), (None, ration.NO_TEMPERATURE))
        self.assertEqual(share.end_g, D('97.5'))


# ---- the database and the pages ---------------------------------------------------------------------------
PROTOCOL_KEEPER = ('view_feedingprotocol', 'add_feedingprotocol', 'change_feedingprotocol', 'delete_feedingprotocol',
                   'view_protocolassignment', 'add_protocolassignment', 'change_protocolassignment',
                   'delete_protocolassignment', 'view_watermeasurement', 'add_watermeasurement', 'view_species',
                   'delete_species', 'view_tank', 'delete_tank')


def table_data(version, temperatures, rows, initial=0):
    """What the feeding table's grid posts: its columns, its version and a row per band."""
    data = {'version': str(version), 'temperatures': temperatures, 'bands-TOTAL_FORMS': str(len(rows)),
            'bands-INITIAL_FORMS': str(initial), 'bands-MIN_NUM_FORMS': '0', 'bands-MAX_NUM_FORMS': '1000'}
    for index, row in enumerate(rows):
        for key, value in row.items():
            data[f'bands-{index}-{key}'] = value
    return data


class ProtocolTestCase(FeedingTestCase):
    """The feeding test case (10,000 salmon of 50 g in T-01 for 20 days, feed GR-4) with the protocol pages."""

    def setUp(self):
        super().setUp()
        self.user.groups.add(role('Protocol keeper', *PROTOCOL_KEEPER))
        self.user = type(self.user).objects.get(pk=self.user.pk)      # its rights read again (Django keeps them once read)

    def make_protocol(self, name='Salmon grow-out', bands=((0, 100, None), (100, None, '1.20')), columns=('12', '14'),
                      sfr=(('1.10', '1.30'), ('0.90', '1.00')), status='active', fcr='1.00', species=None):
        protocol = FeedingProtocol.objects.create(name=name, species=species or self.salmon, expected_fcr=D(fcr),
                                                  status=status)
        for (low, high, band_fcr), cells_ in zip(bands, sfr):
            band = ProtocolBand.objects.create(protocol=protocol, min_weight_g=D(str(low)),
                                               max_weight_g=None if high is None else D(str(high)), feed=self.feed,
                                               meals_per_day=4, expected_fcr=None if band_fcr is None else D(band_fcr))
            for column, value in zip(columns, cells_):
                ProtocolRate.objects.create(band=band, temperature_c=D(column), sfr_pct=D(value))
        return protocol

    def assign(self, protocol, unit=None, batch=None, days_ago=20, until=None):
        return ProtocolAssignment.objects.create(protocol=protocol, unit=unit, batch=batch,
                                                 valid_from=self.day(days_ago), valid_until=until)

    def water(self, value, unit=None, hours=2, system=None):
        return water_services.record(self.user, point=point_of(system or unit or self.t1),
                                     measured_at=timezone.now() - timedelta(hours=hours), source='manual',
                                     values={'temperature_c': D(value)})


class WorkedExampleTestCase(ProtocolTestCase):
    """feeding-protocols §6.7 through the services: 12,000 fish in T-02 weighed at 85.0 g 15 days ago, 10 kg a day
    since (150 kg) in the 50–100 g band at FCR 1.00, the unit at 13.2 °C two hours ago."""

    def setUp(self):
        super().setUp()
        self.protocol = self.make_protocol(bands=((50, 100, None), (100, None, None)), sfr=(('1.10', '1.30'),
                                                                                             ('0.90', '1.00')))
        self.fish = self.stock(self.t2, count=12000, weight='80', days_ago=20)
        stock_services.record_weighing(self.user, unit=self.t2, batch=self.fish, day=self.day(15),
                                       avg_weight_g=D(85))
        for days_ago in range(15, 0, -1):
            self.record(kilos='10', days_ago=days_ago, unit=self.t2)
        self.assign(self.protocol, unit=self.t2)
        self.water('13.2', unit=self.t2, hours=0)

    def board_line(self):
        response = self.client.get(reverse('farm:meal_board'))
        row = next(row for row in response.context['rows'] if row['unit'] == self.t2)
        return response, row, row['lines'][0]


class FastingOnTheBoardTests(WorkedExampleTestCase):
    """A planned harvest or transport asks its unit to fast for the handling rule's hours before it (Setup ›
    Handling rules, harvest 72 h from the data migration): on those days the meal board has no ration and says why;
    cancelling the plan gives the ration back."""

    def plan(self, kind='harvest', days_ahead=2, **fields):
        extra = {'facility': make_facility()} if kind == 'harvest' else {'destination_unit': self.t1}
        return HandlingPlanItem.objects.create(kind=kind, date=self.today + timedelta(days=days_ahead), unit=self.t2,
                                               batch=self.fish, **{**extra, **fields})

    def test_no_ration_before_a_planned_harvest_and_the_reason(self):
        item = self.plan()
        response, row, line = self.board_line()
        self.assertFalse(line['share'].end.has_ration)
        self.assertEqual(line['share'].end.missing, ration.FASTING)
        self.assertIn('Fasting before the harvest of', line['why'])
        self.assertIn('(72 h)', line['why'])
        self.assertContains(response, 'Fasting before the harvest of')
        # The water's temperature stays on the line of a fasting unit: the Water column still has it.
        self.assertIsNotNone(line['share'].end.temperature)
        item.cancelled_reason = 'Moved to next month'
        item.save()
        response, row, line = self.board_line()
        self.assertTrue(line['share'].end.has_ration)

    def test_a_harvest_beyond_the_fasting_window_leaves_today_fed(self):
        self.plan(days_ahead=5)                          # 72 h before day +5 starts on day +2
        response, row, line = self.board_line()
        self.assertTrue(line['share'].end.has_ration)

    def test_a_planned_transport_asks_for_its_own_rule(self):
        self.plan(kind='transport', days_ahead=2)       # transport 24 h: the fast starts tomorrow at 00:00
        response, row, line = self.board_line()
        self.assertTrue(line['share'].end.has_ration)
        self.plan(kind='transport', days_ahead=1)       # its fast starts today at 00:00: today is a fasting day
        response, row, line = self.board_line()
        self.assertIn('Fasting before the transport of', line['why'])


class BoardTests(WorkedExampleTestCase):
    def test_the_board_shows_the_worked_example(self):
        response, row, line = self.board_line()
        share = line['share']
        self.assertEqual((share.end_g, share.ration_kg, share.next_meal_kg), (D('97.5'), D('14.274'), D('3.5685')))
        self.assertEqual((share.end.protocol, share.end.scope, line['why']), (self.protocol, 'unit', ''))
        self.assertEqual(row['temperature'].value_c, D('13.2'))
        for text in ('97.5 g', '85.0 g weighed', '14.27 kg', '4 × 3.57 kg', '1.22 %', 'via unit T-02', '13.2 °C',
                     'Record meal', '50–100 g · GR-4 · 4 mm · FCR 1.00'):
            self.assertContains(response, text)
        self.assertContains(response, '1.10 % at 12.0 °C, 1.30 % at 14.0 °C')

    def test_record_meal_fills_in_the_next_meal_and_the_next_one_is_computed_again(self):
        _response, row, _line = self.board_line()
        form = self.client.get(row['record_url']).context['form']
        self.assertEqual((form.initial['amount_kg'], form.initial['meals'], form.initial['feed']),
                         (D('3.569'), 1, self.feed.pk))
        posted = self.client.post(row['record_url'], self.data(date=self.today.isoformat(), amount_kg='3.569',
                                                               meals='1'), headers={'X-Modal': '1'})
        self.assertEqual(posted['X-Modal-Redirect'], reverse('farm:meal_board'))
        record = FeedingRecord.objects.get(unit=self.t2, date=self.today)
        self.assertEqual((record.amount_kg, record.meals), (D('3.569'), 1))
        _response, _row, line = self.board_line()
        share = line['share']
        self.assertEqual(share.end_g, (D(1170000) + D(3569)) / 12000)        # 3.569 kg ÷ 1.00 on 12,000 fish
        self.assertEqual(share.next_meal_kg, D('1173.569') * D('1.22') / 100 / 4)
        self.assertEqual(share.calculated_kg, D('3.5685') + 3 * share.next_meal_kg)

    def test_why_there_is_no_ration(self):
        ProtocolAssignment.objects.all().delete()
        self.assertEqual(self.board_line()[2]['why'], 'No protocol is assigned to these fish.')
        self.assign(self.protocol, unit=self.t2)
        self.water('20', unit=self.t2, hours=0)
        self.assertEqual(self.board_line()[2]['why'], '20.0 °C is outside this table (12.0–14.0 °C).')
        self.water('13.2', unit=self.t2, hours=0)
        trout = self.make_protocol(name='Trout', species=self.trout)
        ProtocolAssignment.objects.all().delete()
        self.assign(trout, unit=self.t2)
        self.assertEqual(self.board_line()[2]['why'], 'Trout, assigned to T-02, is for Rainbow trout (RBT); these fish '
                                                      'are Atlantic salmon (SAL).')

    @withdrawal_gate.opened('test fixture: withdrawal inputs written straight in the database')
    def test_the_temperature_ages_and_falls_back_to_the_system(self):
        WaterMeasurement.all_objects.all().delete()
        ras = System.objects.create(site=self.bergen, name='RAS 1', code='RAS1', type='ras')
        Tank.objects.filter(pk=self.t2.pk).update(system=ras)
        self.water('13.0', unit=self.t2, hours=30)                         # the unit's own, stale
        self.water('12.5', system=ras, hours=3)                            # the loop's, fresh: it wins
        temperature = self.board_line()[1]['temperature']
        self.assertEqual((temperature.value_c, temperature.via, temperature.fresh), (D('12.5'), 'system', True))
        WaterMeasurement.all_objects.filter(point__system=ras).delete()
        temperature = self.board_line()[1]['temperature']
        self.assertEqual((temperature.value_c, temperature.via, temperature.fresh), (D('13.0'), 'unit', False))
        self.assertContains(self.client.get(reverse('farm:meal_board')), 'Based on the temperature from')
        WaterMeasurement.all_objects.all().delete()
        self.water('13.0', unit=self.t2, hours=24 * 8)                     # A11: however old, it gives the ration
        temperature = self.board_line()[1]['temperature']
        self.assertEqual((temperature.value_c, temperature.fresh), (D('13.0'), False))
        self.assertIn('(8 days old)', temperature.warning)
        WaterMeasurement.all_objects.all().delete()                        # none ever recorded: no ration
        self.assertEqual(self.board_line()[2]['why'], 'No temperature recorded here yet: record one.')

    @withdrawal_gate.opened('test fixture: withdrawal inputs written straight in the database')
    def test_the_board_prints_a_stale_temperatures_age_warning_under_its_chip(self):
        """A11 on the page: the stale chip (clock and word) and under it the sentence the ration is based on, with its age."""
        WaterMeasurement.all_objects.all().delete()
        self.water('13.0', unit=self.t2, hours=24 * 5)
        response, row, _line = self.board_line()
        warning = row['temperature'].warning
        self.assertIn('(5 days old)', warning)
        self.assertTrue(warning.startswith('Based on the temperature from '))
        self.assertContains(response, f'stale</span><span class="ui-why ui-mt">{warning}</span>', count=1)


class PrecedenceTests(ProtocolTestCase):
    def test_a_units_row_wins_over_the_batchs_and_a_whole_batch_row_follows_a_transfer(self):
        for_batch, for_unit = self.make_protocol(name='Batch protocol'), self.make_protocol(name='Unit protocol')
        self.assign(for_batch, batch=self.batch)
        self.assign(for_unit, unit=self.t1)
        self.water('13', unit=self.t1)
        self.water('13', unit=self.t2)
        stock_services.record_transfer(self.user, source=self.t1, batch=self.batch, day=self.today,
                                       legs=[(self.t2, 4000)], reason='density')
        rows = {row['unit']: row['lines'][0]['share'].end
                for row in self.client.get(reverse('farm:meal_board')).context['rows']}
        self.assertEqual((rows[self.t1].protocol, rows[self.t1].scope), (for_unit, 'unit'))
        self.assertEqual((rows[self.t2].protocol, rows[self.t2].scope), (for_batch, 'batch'))
        pair = self.make_protocol(name='Pair protocol')
        self.assign(pair, unit=self.t1, batch=self.batch, days_ago=0)
        rows = {row['unit']: row['lines'][0]['share'].end
                for row in self.client.get(reverse('farm:meal_board')).context['rows']}
        self.assertEqual((rows[self.t1].protocol, rows[self.t1].scope), (pair, 'batch_in_unit'))
        self.assertContains(self.client.get(reverse('farm:meal_board')), f'via {self.batch.code} in T-01')


class RecordsByDayTests(WorkedExampleTestCase):
    def test_calculated_given_and_the_deviation_per_unit_and_day_with_the_weighings_correction(self):
        stock_services.record_weighing(self.user, unit=self.t2, batch=self.fish, day=self.today, avg_weight_g=D(94))
        self.record(kilos='3', days_ago=0, unit=self.t2, meals=1)
        response = self.client.get(reverse('farm:feeding_records'), {'view': 'days', 'unit': self.t2.pk})
        rows = {row['day']: row for row in response.context['day_rows']}
        today = rows[self.today]
        self.assertEqual(today['given_kg'], D(3))
        # Weighed at 94.0 g before the day's meal: 1,128 kg × 1.22 %, a quarter at 94.0 g and three at 94.25 g.
        self.assertEqual(today['unit_day'].calculated_kg,
                         D('1128') * D('1.22') / 100 / 4 + 3 * D('1131') * D('1.22') / 100 / 4)
        self.assertEqual(today['unit_day'].deviation_kg, D(3) - today['unit_day'].calculated_kg)
        correction = today['corrections'][0]['correction']
        self.assertEqual((correction.estimated_g, correction.measured_g, correction.difference_kg),
                         (D('97.5'), D('94'), D('-42')))
        self.assertEqual(round(correction.realised_fcr, 2), D('1.39'))
        self.assertContains(response, f'{self.fish.code} weighed at 94.0 g, estimated 97.5 g')
        self.assertContains(response, '−3.5 g (−3.6 %, −42 kg)')
        self.assertContains(response, 'FCR 1.39 realised, 1.00 expected')
        # A past day: no temperature recorded by its end, so no calculated ration; the feed given is listed.
        yesterday = rows[self.day(1)]
        self.assertEqual((yesterday['given_kg'], yesterday['unit_day'].calculated_kg), (D(10), None))
        self.assertIn('No temperature', yesterday['shares'][0]['why'])

    def test_the_list_is_a_view_of_records(self):
        listing = self.client.get(reverse('farm:feeding_records'))
        self.assertEqual([str(item['label']) for item in listing.context['views']], ['Feeding records',
                                                                                    'By unit and day'])
        self.assertEqual(len(listing.context['rows']), 15)


class WeighingDialogTests(WorkedExampleTestCase):
    def test_the_dialog_shows_the_estimate_and_the_difference_before_saving(self):
        url = reverse('farm:stock_weighing', args=[self.t2.pk])
        response = self.client.get(url)
        self.assertEqual(response.context['estimate']['estimated_g'], D('97.5'))
        self.assertContains(response, f'Estimated 97.5 g on {stock_services.shown_date(self.today)} (15 days since the '
                                      'last measured weight)')
        self.assertContains(response, 'data-refresh="_draft"')
        draft = self.client.post(url, {'_draft': 'avg_weight_g', 'batch': str(self.fish.pk), 'avg_weight_g': '94',
                                       'date': self.today.isoformat(), 'token': str(uuid.uuid4())})
        self.assertContains(draft, 'you entered 94.0 g: −3.5 g, −3.6 %')
        self.assertEqual(draft.context['form']['avg_weight_g'].value(), '94')
        self.assertFalse(StockOperation.objects.filter(kind='weighing', date=self.today).exists())

    def test_the_drawer_shows_todays_ration_and_the_weighings_correction(self):
        stock_services.record_weighing(self.user, unit=self.t2, batch=self.fish, day=self.today, avg_weight_g=D(94))
        response = self.client.get(reverse('farm:production_units'), {'unit': self.t2.pk})
        self.assertContains(response, 'Today’s ration')
        self.assertContains(response, '1.22 % at 13.2 °C: 13.76 kg a day, 4 × 3.44 kg')
        self.assertContains(response, f'{self.fish.code} weighed at 94.0 g, estimated 97.5 g')


class ProtocolPageTests(ProtocolTestCase):
    def create(self, **fields):
        data = {'name': 'Salmon smolt', 'species': str(self.salmon.pk), 'status': 'draft', 'expected_fcr': '1.05',
                'notes': '', **fields}
        return self.client.post(reverse('farm:feedingprotocol_create'), data, headers={'X-Modal': '1'})

    def test_create_fill_the_table_activate_and_the_log(self):
        response = self.create()
        protocol = FeedingProtocol.objects.get()
        self.assertEqual(response['X-Modal-Load'], reverse('farm:feedingprotocol_edit', args=[protocol.pk]))
        self.assertEqual((protocol.status, protocol.expected_fcr, protocol.created_by), ('draft', D('1.05'), self.user))
        edit = self.client.get(reverse('farm:feedingprotocol_edit', args=[protocol.pk]))
        self.assertContains(edit, 'Feeding table')
        refused = self.client.post(reverse('farm:feedingprotocol_edit', args=[protocol.pk]),
                                   {'name': 'Salmon smolt', 'species': str(self.salmon.pk), 'status': 'active',
                                    'expected_fcr': '1.05', 'version': '1'})
        self.assertEqual(refused.context['form'].errors['status'],
                         ['Fill in its feeding table first: a protocol without one cannot be active.'])
        rows = [{'min_weight_g': '50', 'max_weight_g': '100', 'feed': str(self.feed.pk), 'meals_per_day': '4',
                 'expected_fcr': '', 'sfr_120': '1.1', 'sfr_140': '1.3'},
                {'min_weight_g': '100', 'max_weight_g': '', 'feed': str(self.feed.pk), 'meals_per_day': '3',
                 'expected_fcr': '1.2', 'sfr_120': '0.9', 'sfr_140': '1'}]
        url = reverse('farm:feedingprotocol_table', args=[protocol.pk])
        saved = self.client.post(url, table_data(1, '14 12', rows), headers={'X-Modal': '1'})
        self.assertEqual(saved.status_code, 204)
        bands = list(protocol.bands.order_by('min_weight_g'))
        self.assertEqual([(band.min_weight_g, band.max_weight_g, band.meals_per_day, band.expected_fcr)
                          for band in bands], [(50, 100, 4, None), (100, None, 3, D('1.2'))])
        self.assertEqual([(rate.temperature_c, rate.sfr_pct) for rate in bands[0].rates.all()],
                         [(D('12.0'), D('1.100')), (D('14.0'), D('1.300'))])
        logged = AuditLog.objects.filter(entity_type='feeding protocol', action='update').get()
        self.assertEqual(logged.changes['Feeding table'], [None, '50–100 g: GR-4, 4 meals; 12 °C 1.1 %, 14 °C 1.3 %\n'
                                                                 '100–… g: GR-4, 3 meals, FCR 1.2; 12 °C 0.9 %, '
                                                                 '14 °C 1 %'])
        protocol.refresh_from_db()
        self.assertEqual(protocol.version, 2)
        self.client.post(reverse('farm:feedingprotocol_edit', args=[protocol.pk]),
                         {'name': 'Salmon smolt', 'species': str(self.salmon.pk), 'status': 'active',
                          'expected_fcr': '1.05', 'version': '2'})
        protocol.refresh_from_db()
        self.assertEqual(protocol.status, 'active')
        listing = self.client.get(reverse('farm:feedingprotocol_list'))
        for text in ('Salmon smolt', '50–100 g · GR-4', 'from 100 g · GR-4', '12.0 °C – 14.0 °C', '2 columns'):
            self.assertContains(listing, text)

    def test_the_tables_rules(self):
        self.create()
        protocol = FeedingProtocol.objects.get()
        url = reverse('farm:feedingprotocol_table', args=[protocol.pk])
        band = {'feed': str(self.feed.pk), 'meals_per_day': '4', 'expected_fcr': '', 'sfr_120': '1', 'sfr_140': '1'}
        cases = [
            ([{**band, 'min_weight_g': '0', 'max_weight_g': '50'}, {**band, 'min_weight_g': '60', 'max_weight_g': ''}],
             'The bands must meet: one starts at 60 g, the band before it ends at 50 g.'),
            ([{**band, 'min_weight_g': '0', 'max_weight_g': ''}, {**band, 'min_weight_g': '50', 'max_weight_g': '90'}],
             'Only the last band can be without an upper weight.'),
            ([], 'A feeding table has at least one band.'),
        ]
        for rows, message in cases:
            response = self.client.post(url, table_data(protocol.version, '12 14', rows))
            self.assertEqual(response.status_code, 422)
            self.assertEqual(response.context['bands'].non_form_errors(), [message])
        whole = {**band, 'min_weight_g': '0', 'max_weight_g': ''}
        response = self.client.post(url, table_data(protocol.version, '12 41', [whole]))
        self.assertEqual(response.context['table_form'].errors['temperatures'],
                         ['A temperature column is between -3 and 40 °C.'])
        stopped = Feed.objects.create(name='Old', code='OLD', feed_type='grower', status='discontinued')
        response = self.client.post(url, table_data(protocol.version, '12 14', [{**whole, 'feed': str(stopped.pk)}]))
        self.assertEqual(response.context['bands'].forms[0].errors['feed'], ['Choose an active feed.'])
        response = self.client.post(url, table_data(protocol.version, '12 14', [{**whole, 'sfr_120': '16'}]))
        self.assertIn('sfr_120', response.context['bands'].forms[0].errors)
        stale = self.client.post(url, table_data(protocol.version - 1, '12 14', [whole]))
        self.assertIn('Someone else changed this feeding protocol', stale.context['table_form'].non_field_errors()[0])
        self.assertFalse(protocol.bands.exists())

    def test_changing_the_columns_renders_the_grid_again_and_saves_nothing(self):
        self.create()
        protocol = FeedingProtocol.objects.get()
        url = reverse('farm:feedingprotocol_table', args=[protocol.pk])
        row = {'min_weight_g': '0', 'max_weight_g': '', 'feed': str(self.feed.pk), 'meals_per_day': '4',
               'expected_fcr': '', 'sfr_120': '1.5'}
        response = self.client.post(url, {**table_data(protocol.version, '12 16', [row]), '_draft': 'temperatures'})
        self.assertEqual(response.status_code, 200)
        bands = response.context['bands']
        self.assertEqual(bands.columns, [D('12.0'), D('16.0')])
        self.assertEqual(bands.forms[0]['sfr_120'].value(), '1.5')
        self.assertIsNone(bands.forms[0]['sfr_160'].value())
        self.assertEqual(response.context['open_tab'], 'table')
        self.assertFalse(protocol.bands.exists())

    def test_an_assigned_protocol_keeps_its_table_species_and_fcr_and_duplicate_makes_a_draft(self):
        protocol = self.make_protocol()
        self.assign(protocol, unit=self.t1)
        edit = self.client.get(reverse('farm:feedingprotocol_edit', args=[protocol.pk]))
        self.assertTrue(edit.context['frozen'])
        self.assertTrue(edit.context['form'].fields['species'].disabled)
        self.assertContains(edit, 'The protocol is assigned, so its table is fixed')
        refused = self.client.post(reverse('farm:feedingprotocol_table', args=[protocol.pk]),
                                   table_data(protocol.version, '12 14', [{'min_weight_g': '0', 'max_weight_g': '',
                                                                        'feed': str(self.feed.pk),
                                                                        'meals_per_day': '4', 'expected_fcr': '',
                                                                        'sfr_120': '1', 'sfr_140': '1'}]))
        self.assertIn('its table is fixed', refused.context['table_form'].non_field_errors()[0])
        self.assertEqual(protocol.bands.count(), 2)
        retired = self.client.post(reverse('farm:feedingprotocol_edit', args=[protocol.pk]),
                                   {'name': protocol.name, 'status': 'retired', 'version': str(protocol.version)})
        self.assertEqual(retired.context['form'].errors['status'],
                         ['It is assigned for today or later: end those assignments first.'])
        copied = self.client.post(reverse('farm:feedingprotocol_duplicate', args=[protocol.pk]),
                                  headers={'X-Modal': '1'})
        copy = FeedingProtocol.objects.get(name='Salmon grow-out (copy)')
        self.assertEqual(copied['X-Modal-Load'], reverse('farm:feedingprotocol_edit', args=[copy.pk]))
        self.assertEqual((copy.status, copy.species, copy.expected_fcr), ('draft', self.salmon, D('1.00')))
        self.assertEqual([(band.min_weight_g, [rate.sfr_pct for rate in band.rates.all()])
                          for band in copy.bands.order_by('min_weight_g')],
                         [(0, [D('1.1'), D('1.3')]), (100, [D('0.9'), D('1.0')])])
        logged = AuditLog.objects.get(entity_type='feeding protocol', action='create', entity_id=str(copy.pk))
        self.assertTrue(logged.changes['Feeding table'][1].startswith('0–100 g: GR-4, 4 meals; 12 °C 1.1 %'))
        self.client.post(reverse('farm:feedingprotocol_duplicate', args=[protocol.pk]))
        self.assertTrue(FeedingProtocol.objects.filter(name='Salmon grow-out (copy 2)').exists())

    def test_names_are_unique_among_live_protocols_whatever_the_case(self):
        self.make_protocol()
        response = self.create(name='SALMON GROW-OUT')
        self.assertEqual(response.context['form'].errors['name'], ['Another feeding protocol already has this name.'])


class AssignmentPageTests(ProtocolTestCase):
    def setUp(self):
        super().setUp()
        self.protocol = self.make_protocol()

    def post(self, **fields):
        data = {'protocol': str(self.protocol.pk), 'valid_from': self.today.isoformat(), 'valid_until': '',
                'notes': '', 'batch': '', **fields}
        return self.client.post(reverse('farm:protocolassignment_create'), data, headers={'X-Modal': '1'})

    def test_the_dialog_sent_twice_assigns_once_and_the_second_sending_lands_where_the_first_did(self):
        # Cross review F7b: the dialog carried the form's key and ignored it.
        key = str(uuid.uuid4())
        first = self.post(units=[str(self.t1.pk), str(self.t2.pk)], entry_key=key)
        second = self.post(units=[str(self.t1.pk), str(self.t2.pk)], entry_key=key)
        self.assertEqual(ProtocolAssignment.objects.count(), 2)
        self.assertEqual(second['X-Modal-Redirect'], first['X-Modal-Redirect'])

    def test_units_a_whole_batch_and_a_batch_in_units(self):
        response = self.post(units=[str(self.t1.pk), str(self.t2.pk)])
        self.assertEqual(response['X-Modal-Redirect'], reverse('farm:protocolassignment_list'))
        rows = list(ProtocolAssignment.objects.order_by('unit__code'))
        self.assertEqual([(row.unit, row.batch, row.scope) for row in rows],
                         [(self.t1, None, 'unit'), (self.t2, None, 'unit')])
        self.assertEqual(len({row.group_id for row in rows}), 1)
        self.assertEqual(AuditLog.objects.filter(entity_type='protocol assignment', action='create').count(), 2)
        self.post(batch=str(self.batch.pk))
        self.assertEqual(ProtocolAssignment.objects.get(unit=None).scope, 'batch')
        self.post(batch=str(self.batch.pk), units=[str(self.t1.pk), str(self.t2.pk)])
        pairs = ProtocolAssignment.objects.filter(unit__isnull=False, batch__isnull=False)
        self.assertEqual(pairs.count(), 2)
        listing = self.client.get(reverse('farm:protocolassignment_list'))
        self.assertContains(listing, f'{self.batch.code} has not been in T-02 yet: the row applies once it is.')
        pair = pairs.get(unit=self.t1)
        self.assertEqual(listing.context['feeds_now'], {pair.pk: 10000})   # the most specific row feeds them
        self.assertContains(listing, 'Batch in unit')

    def test_the_refusals(self):
        self.assertEqual(self.post().status_code, 200)
        self.assertEqual(self.post().context['form'].errors['units'], ['Choose units, a batch, or a batch and units.'])
        self.post(units=[str(self.t1.pk)])
        response = self.post(units=[str(self.t1.pk)], valid_from=self.day(3).isoformat())
        self.assertEqual(response.context['form'].errors['units'],
                         ['T-01: Another protocol is assigned to this unit on some of these days.'])
        draft = self.make_protocol(name='Draft', status='draft')
        response = self.post(protocol=str(draft.pk), units=[str(self.t2.pk)])
        self.assertIn('protocol', response.context['form'].errors)
        trout = self.make_protocol(name='Trout', species=self.trout)
        response = self.post(protocol=str(trout.pk), batch=str(self.batch.pk))
        self.assertEqual(response.context['form'].errors['batch'],
                         [f'{self.batch.code} is Atlantic salmon (SAL); the protocol is for Rainbow trout (RBT).'])
        response = self.post(units=[str(self.t2.pk)], valid_from=self.day(40).isoformat())
        self.assertEqual(response.context['form'].errors['valid_from'],
                         [f'An assignment can start at most 31 days back. {WINDOW_WAY_OUT}'])
        with correction_window(60):
            response = self.post(units=[str(self.t2.pk)], valid_from=self.day(61).isoformat())
            self.assertEqual(response.context['form'].errors['valid_from'],
                             [f'An assignment can start at most 60 days back. {WINDOW_WAY_OUT}'])
        self.assertEqual(ProtocolAssignment.objects.count(), 1)

    def test_one_row_in_force_per_target_in_the_database(self):
        self.assign(self.protocol, unit=self.t1)
        self.assign(self.protocol, batch=self.batch)
        self.assign(self.protocol, unit=self.t1, batch=self.batch)
        for fields in ({'unit': self.t1}, {'batch': self.batch}, {'unit': self.t1, 'batch': self.batch}):
            with self.subTest(fields=fields), self.assertRaises(IntegrityError), transaction.atomic():
                self.assign(self.protocol, days_ago=5, **fields)
        self.assign(self.protocol, unit=self.t2, days_ago=30, until=self.day(21))      # before: fine
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProtocolAssignment.objects.create(protocol=self.protocol, valid_from=self.today)        # no target
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.assign(self.protocol, unit=self.p1, days_ago=1, until=self.day(2))

    def test_a_started_row_is_ended_not_changed_or_deleted(self):
        row = self.assign(self.protocol, unit=self.t1, days_ago=5)
        url = reverse('farm:protocolassignment_edit', args=[row.pk])
        form = self.client.get(url).context['form']
        self.assertTrue(form.fields['protocol'].disabled and form.fields['valid_from'].disabled)
        data = {'protocol': str(self.protocol.pk), 'unit': str(self.t1.pk), 'valid_from': self.day(5).isoformat(),
                'valid_until': self.day(3).isoformat(), 'notes': '', 'version': '1'}
        self.assertEqual(self.client.post(url, data).context['form'].errors['valid_until'],
                         ['The days before yesterday keep their protocol: the last day is yesterday at the earliest.'])
        self.client.post(url, {**data, 'valid_until': self.day(1).isoformat()})
        row.refresh_from_db()
        self.assertEqual(row.valid_until, self.day(1))
        self.assertContains(self.client.get(reverse('farm:protocolassignment_delete', args=[row.pk])),
                            'It has started: set its last day instead.')
        self.client.post(reverse('farm:protocolassignment_delete', args=[row.pk]))
        self.assertTrue(ProtocolAssignment.objects.filter(pk=row.pk).exists())
        later = self.assign(self.protocol, unit=self.t1, days_ago=-3)
        self.client.post(reverse('farm:protocolassignment_delete', args=[later.pk]))
        self.assertTrue(ProtocolAssignment.all_objects.get(pk=later.pk).is_deleted)
        # A row that overlaps another once changed is refused by the constraint, on its last field.
        overlapping = {**data, 'valid_until': ''}
        self.assign(self.protocol, unit=self.t1, days_ago=-10)
        response = self.client.post(url, overlapping)
        self.assertEqual(response.context['form'].errors['valid_until'],
                         ['Another protocol is assigned to this unit on some of these days.'])


class DeletePlanAndAccessTests(ProtocolTestCase):
    def test_a_feed_or_species_in_a_protocol_and_a_protocol_with_assignments_stay(self):
        protocol = self.make_protocol()
        self.assertContains(self.client.get(reverse('farm:feed_delete', args=[self.feed.pk])),
                            'The feeding table of 1 feeding protocol uses it: Salmon grow-out.')
        self.client.post(reverse('farm:feed_delete', args=[self.feed.pk]))
        self.assertFalse(Feed.all_objects.get(pk=self.feed.pk).is_deleted)
        self.assertContains(self.client.get(reverse('farm:species_delete', args=[self.salmon.pk])),
                            '1 feeding protocol still belongs to it.')
        row = self.assign(protocol, unit=self.t1, days_ago=-2)
        self.assertContains(self.client.get(reverse('farm:feedingprotocol_delete', args=[protocol.pk])),
                            '1 protocol assignment still belongs to it.')
        row.soft_delete(self.user)
        self.client.post(reverse('farm:feedingprotocol_delete', args=[protocol.pk]))
        self.assertTrue(FeedingProtocol.all_objects.get(pk=protocol.pk).is_deleted)
        self.assertEqual(Feed.objects.get(pk=self.feed.pk).delete_blockers(), [])    # a deleted protocol lets go

    def test_an_empty_unit_goes_and_keeps_its_assignments(self):
        protocol = self.make_protocol()
        row = self.assign(protocol, unit=self.t2)
        self.assertContains(self.client.get(reverse('farm:tank_delete', args=[self.t2.pk])), 'Protocol assignments')
        self.client.post(reverse('farm:tank_delete', args=[self.t2.pk]))
        self.assertTrue(Tank.all_objects.get(pk=self.t2.pk).is_deleted)
        self.assertTrue(ProtocolAssignment.objects.filter(pk=row.pk).exists())
        self.assertContains(self.client.get(reverse('farm:protocolassignment_list')), 'Deleted')

    def test_permissions_menu_and_role_matrix(self):
        person = get_user_model().objects.create_user('reader', 'reader@example.com')
        person.groups.add(role('Reader', 'view_feedingrecord', 'view_stockoperation'))
        self.client.force_login(person)
        self.assertEqual(self.client.get(reverse('farm:meal_board')).status_code, 200)
        for name in ('farm:feedingprotocol_list', 'farm:protocolassignment_list'):
            self.assertEqual(self.client.get(reverse(name)).status_code, 403)
        page = self.client.get(reverse('farm:meal_board'))
        self.assertNotContains(page, 'Record meal')
        self.assertNotContains(page, reverse('farm:feedingprotocol_list'))
        person.groups.add(role('Protocol reader', 'view_feedingprotocol', 'view_protocolassignment'))
        protocol = self.make_protocol()
        listing = self.client.get(reverse('farm:feedingprotocol_list'))
        self.assertContains(listing, 'Salmon grow-out')
        self.assertNotContains(listing, reverse('farm:feedingprotocol_create'))
        for url in (reverse('farm:feedingprotocol_create'), reverse('farm:feedingprotocol_table', args=[protocol.pk]),
                    reverse('farm:feedingprotocol_duplicate', args=[protocol.pk]),
                    reverse('farm:protocolassignment_create')):
            self.assertEqual(self.client.post(url, {}).status_code, 403, url)
        self.assertEqual({str(navigation.page(name).group.label) for name in (
            'farm:meal_board', 'farm:feeding_records', 'farm:feedingprotocol_list', 'farm:protocolassignment_list')},
            {'Feeding'})
        areas = {area.model: area for area in access.areas()}
        self.assertEqual(str(areas['farm.FeedingProtocol'].label), 'Feeding protocols')
        self.assertEqual(str(areas['farm.ProtocolAssignment'].group), 'Production · Operations · Feeding')
        rail = self.client.get(reverse('farm:feedingprotocol_list')).context['rail_sections']
        current = [entry['label'] for section in rail for group in section['groups'] for entry in group['entries']
                   if entry['current']]
        self.assertEqual([str(label) for label in current], ['Protocols'])

    def test_the_database_viewer_shows_the_tables_with_their_constraints(self):
        tables = {table.name: table for _, tables in database.sections() for table in tables}
        names = {constraint.name for constraint in tables['protocol_assignments'].structure().constraints}
        self.assertTrue({'excl_protocol_assignments_unit', 'excl_protocol_assignments_batch',
                         'excl_protocol_assignments_batch_in_unit', 'chk_protocol_assignments_target'} <= names)
        names = {constraint.name for constraint in tables['feeding_protocol_bands'].structure().constraints}
        self.assertIn('excl_feeding_protocol_bands_overlap', names)
        self.assertTrue(tables['feeding_protocols'].description.startswith('A feeding table for one species'))
        self.assertIn('feeding_protocol_rates', tables)

    def test_the_bands_of_a_protocol_never_overlap_in_the_database(self):
        protocol = self.make_protocol()
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProtocolBand.objects.create(protocol=protocol, min_weight_g=D(50), max_weight_g=D(150), feed=self.feed,
                                        meals_per_day=2)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProtocolRate.objects.create(band=protocol.bands.first(), temperature_c=D('12'), sfr_pct=D(1))


class LanguageTests(WorkedExampleTestCase):
    def test_the_pages_speak_each_language(self):
        for language, words in {'tr': ('Öğün panosu', 'Rasyon'), 'nb': ('Måltidstavle', 'Rasjon')}.items():
            Profile.objects.update_or_create(user=self.user, defaults={'language': language})
            response = self.client.get(reverse('farm:meal_board'))
            for word in words:
                self.assertContains(response, word, msg_prefix=language)


# ---- figures for many units in one walk -------------------------------------------------------------------
def old_week(unit, stock, today, days, walked):
    """The drawer's Week as read.figures built it for one unit (kept here as the oracle of the bulk `weeks`)."""
    first = days[0][1]
    records = list(FeedingRecord.objects.filter(unit=unit, date__gte=first, target='production')
                   .select_related('feed'))
    of_today = [record for record in records if record.date == today]
    meals = [record.meals for record in of_today]
    latest = (FeedingRecord.objects.filter(unit=unit, date__gte=stock.since, target='production')
              .select_related('feed').first()) if stock.since else None
    return read.Week(
        first=first,
        today_kg=sum((record.amount_kg for record in of_today), read.ZERO),
        today_meals=sum(meals) if meals and None not in meals else None,
        kg=sum((record.amount_kg for record in records if record.date <= today), read.ZERO),
        biomass_days_kg=sum((walked.days[key].production.biomass_kg for key in days), read.ZERO),
        feed=latest.feed if latest else None)


class BulkFiguresTests(WorkedExampleTestCase):
    """read.figures(stock, details, ration): the weeks of several units, the rations of all, in one walk."""

    def setUp(self):
        super().setUp()
        Site.objects.filter(pk=self.tromso.pk).update(timezone='Pacific/Auckland')
        self.s1 = make_unit('S-01', self.sea, 'pond', status=Tank.Status.ACTIVE)
        self.fish_s1 = self.stock(self.s1, count=3000, weight='80', days_ago=20)
        for unit in (self.t1, self.s1):
            self.assign(self.protocol, unit=unit)
            self.record(kilos='4', days_ago=2, unit=unit)
            self.record(kilos='3', days_ago=0, unit=unit, meals=2)
            self.water('13', unit=unit, hours=0)
        self.units = [Tank.objects.select_related('production_department__site').get(pk=unit.pk)
                      for unit in (self.t1, self.t2, self.s1)]
        self.t1, self.t2, self.s1 = self.units
        self.stock_now = stock_read.stock_of(self.units)

    def today_of(self, unit):
        return local_today(unit)

    def test_the_weeks_equal_the_one_unit_oracle_in_two_time_zones(self):
        found = read.figures(self.stock_now, details=[self.t1, self.s1])
        for unit in (self.t1, self.s1):
            today = self.today_of(unit)
            days = [(unit.pk, today - timedelta(days=6) + timedelta(days=n)) for n in range(7)]
            walked = read.project(list(self.stock_now), days).walked
            self.assertEqual(found[unit.pk].week, old_week(unit, self.stock_now[unit.pk], today, days, walked))
            self.assertGreater(found[unit.pk].week.kg, 0)
        self.assertIsNone(found[self.t2.pk].week)
        self.assertIsNone(found[self.t2.pk].ration)         # not a detailed unit, and no ration asked

    def test_every_units_ration_equals_the_meal_boards_for_it(self):
        found = read.figures(self.stock_now, ration=True)
        for unit in self.units:
            today = self.today_of(unit)
            own = read.project([unit.pk], [(unit.pk, today)]).days[(unit.pk, today)]
            ours = found[unit.pk].ration
            self.assertEqual([getattr(ours, name) for name in ('fed_kg', 'meals_done', 'ration_kg', 'remaining_kg',
                                                              'next_meal_kg', 'calculated_kg')],
                             [getattr(own, name) for name in ('fed_kg', 'meals_done', 'ration_kg', 'remaining_kg',
                                                             'next_meal_kg', 'calculated_kg')])
        self.assertIsNotNone(found[self.t2.pk].ration.ration_kg)        # the fixture does compute a ration
        self.assertEqual(found[self.t1.pk].ration.fed_kg, 3)

    def test_one_walk_serves_the_page_the_drawer_and_the_cards(self):
        with mock.patch.object(read, 'project', wraps=read.project) as project, \
                mock.patch('farm.feeding.read.walk', wraps=read.walk) as walking:
            read.figures(self.stock_now, details=[self.t1, self.s1], ration=True)
        self.assertEqual((project.call_count, walking.call_count), (1, 1))

    def test_the_queries_do_not_grow_with_the_units(self):
        def count(units, **kwargs):
            with CaptureQueriesContext(connection) as queries:
                read.figures(stock_read.stock_of(units), **kwargs)
            return len(queries)
        count([self.t1], details=[self.t1], ration=True)                 # warm the caches
        one = count([self.t1], details=[self.t1], ration=True)
        self.assertEqual(count([self.t1, self.t2], details=[self.t1, self.t2], ration=True), one)
        self.assertEqual(count(self.units, details=self.units, ration=True), one)

    def test_the_meal_boards_lines_are_meal_lines(self):
        response = self.client.get(reverse('farm:meal_board'))
        for row in response.context['rows']:
            today = local_today(row['unit'])
            batches = {share.batch.pk: share.batch for share in row['stock'].shares}
            again = read.meal_lines(row['day'], batches, today)
            self.assertEqual([(line['batch'], line['why'], line['drift'], line['estimate_days'])
                              for line in row['lines']],
                             [(line['batch'], line['why'], line['drift'], line['estimate_days']) for line in again])

    def test_drift_is_soon_after_the_soon_days_and_now_after_the_now_days(self):
        today, soon, now = self.today, settings.WEIGH_SOON_DAYS, settings.WEIGH_NOW_DAYS
        self.assertEqual([read.drift(today, None)] + [read.drift(today, today - timedelta(days=days))
                                                      for days in (0, soon, soon + 1, now, now + 1)],
                         ['', '', '', 'soon', 'soon', 'now'])


def live_as_main_asked_it(series, point_id, moment, window):
    """`Series._live` as main (56b7ea0) wrote it, verbatim but for `series` where it said `self`: each moment asked of the
    sources on its own, by `sources.value_at`, when it is first looked up. The oracle of SensorRationTemperatureTests:
    nothing of `Series.prefetch` or `sources.values_at` is in it."""
    if moment not in series.asked:
        targets = {pk: [(target, origin) for target, origin in found if target in series.bound]
                   for pk, found in series.targets.items()}
        if not any(targets.values()):
            series.asked[moment] = {}
            return []
        answer = sources.value_at([target for found in targets.values() for target, _origin in found], series.code,
                                  moment)
        by_point = {}
        for pk, found in targets.items():
            values = []
            for target, origin in found:
                for value in sources.ordered(answer.values.get(target, [])):
                    if value.at <= moment:
                        observed = Observation.of_sensor(series.points[pk], value, origin)
                        values.append(Found(value.at, observed.get(series.code), value.fresh_for, origin,
                                            series.points[pk]))
            by_point[pk] = values
        series.asked[moment] = by_point
    return [found for found in series.asked[moment].get(point_id, []) if window is None or moment - found.at <= window]


class SensorRationTemperatureTests(WorkedExampleTestCase):
    """The ration's temperature from a probe on T-02 (owner rule A9: a fresh sensor value counts as the unit's own): the
    walk reads the sensors at the days it may ask in ONE ask of the live sources (Series.prefetch), and every day's
    basis is what main's way gives: the prefetch OFF, each day asked of the sources on its own when the walk first looks
    it up (`live_as_main_asked_it`, a provider that answers one moment at a time). Before, a fifteen-day walk asked the
    sources fifteen times, and the sensors ran a query per channel at each (the monitoring wall's 161 reads of the
    hypertable, 2026-11-21). The reference shares nothing with the new reads (`Series.prefetch`, `sources.values_at`), so
    a fault in them, a day's answer swapped with another's, shows."""

    def setUp(self):
        super().setUp()
        from .test_water_sources import FakeProvider

        class Flaky(FakeProvider):
            """`broken_at`: the moments whose `value_at` fails (it is asked, and it raises)."""
            broken_at = ()

            def value_at(self, targets, code, moment):
                if moment in self.broken_at:
                    self.asked.append(('value_at', code))
                    raise RuntimeError('the sensors database dropped this ask')
                return FakeProvider.value_at(self, targets, code, moment)

        class Many(Flaky):
            """Also answers several moments in one ask; `values_at_broken`: that ask fails."""
            values_at_broken = False

            def values_at(self, targets, code, moments):
                self.asked.append(('values_at', code, len(moments)))
                if self.values_at_broken:
                    raise RuntimeError('the sensors database dropped the ask for all the days')
                found = []
                for moment in moments:
                    found.append(FakeProvider.value_at(self, targets, code, moment))
                    self.asked.pop()                                      # its own value_at is not an ask
                return found

        self.providers = {'many': Many(), 'one_by_one': Flaky()}
        target = (sources.POINT, point_of(self.t2).pk)
        now = self.pinned = timezone.now()
        for provider in self.providers.values():
            for hours in range(0, 24 * 18, 6):
                value = sources.SensorValue(code='temperature_c', value=12.0 + (hours % 37) / 10,
                                            at=now - timedelta(hours=hours, minutes=5), fresh_for=8 * 3600,
                                            role=sources.PRIMARY, channel_no=7)
                provider.history.setdefault(target, {}).setdefault('temperature_c', []).append(value)
        self.sources = sources

    @contextmanager
    def reading(self, name, as_main=False):
        """The named provider registered, the clock at ONE moment (today's temperature carries its age at `now`), and
        with `as_main` the walk reads the sensors main's way: the prefetch off and `Series._live` as main wrote it."""
        provider = self.providers[name]
        provider.asked.clear()
        self.sources.register(provider)
        try:
            with mock.patch('django.utils.timezone.now', return_value=self.pinned):
                if as_main:
                    with mock.patch.object(TemperatureBook, 'prefetch', lambda book, moments: None), \
                            mock.patch.object(Series, '_live', live_as_main_asked_it):
                        yield provider
                else:
                    yield provider
        finally:
            self.sources.unregister(provider)

    @staticmethod
    def asks(provider):
        return [ask for ask in provider.asked if ask[0] in ('value_at', 'values_at')]

    def figures(self, name, as_main=False):
        """(the figures of T-02 with this provider, the asks it was asked)."""
        with self.reading(name, as_main) as provider:
            found = read.figures(stock_read.stock_of([self.t2]), details=[self.t2], ration=True)[self.t2.pk]
        return found, self.asks(provider)

    def days(self, name, as_main=False, back=16):
        """{(unit id, day): UnitDay} of T-02 for each of its last `back` days: the basis of every share with the
        temperature it rests on, not only today's ration."""
        with self.reading(name, as_main):
            return read.project([self.t2.pk], [(self.t2.pk, self.today - timedelta(days=n)) for n in range(back)]).days

    def temperature_of(self, days, back):
        return days[(self.t2.pk, self.today - timedelta(days=back))].shares[0].end.temperature

    def assertSame(self, new, old):
        """The figures and the days of two readings are equal, field by field."""
        self.assertEqual(new[0].ration, old[0].ration)
        self.assertEqual(new[0].corrections, old[0].corrections)
        self.assertEqual(new[0].week, old[0].week)

    def test_one_ask_for_the_days_and_the_same_bases_as_main_asking_day_by_day(self):
        many, asked_once = self.figures('many')
        main, asked_daily = self.figures('one_by_one', as_main=True)
        self.assertEqual(len(asked_once), 1, asked_once)
        self.assertEqual(asked_once[0][:2], ('values_at', 'temperature_c'))
        self.assertGreater(sum(ask[0] == 'value_at' for ask in asked_daily), 10)   # main's way asks most days, one each
        self.assertSame((many,), (main,))
        self.assertEqual(self.days('many'), self.days('one_by_one', as_main=True))     # every day's basis, 16 days
        temperatures = {line.end.temperature for line in many.ration.shares}
        self.assertEqual({each.via for each in temperatures}, {'unit'})
        self.assertTrue(all(each.sampling_point is not None for each in temperatures))
        # the days differ from one another: a swapped or shifted answer could not pass for the right ones
        days = self.days('many')
        self.assertGreater(len({self.temperature_of(days, back).value_c for back in range(1, 12)}), 6)

    def test_only_the_days_a_protocol_covers_are_read_ahead_and_each_is_asked_for_by_the_walk(self):
        """The row of the protocol starts 8 days ago: a feeding day before it asks no temperature (no protocol, no
        ration, `Policy.basis`), so none of those days' moments is read ahead; and every day the walk does ask was read
        (none is asked of the sources a second time, on its own)."""
        ProtocolAssignment.objects.filter(unit=self.t2).update(valid_from=self.day(8))
        prefetched, asked = [], []
        real_prefetch, real_at = TemperatureBook.prefetch, TemperatureBook.at

        def prefetch(book, moments):
            moments = list(moments)
            prefetched.extend(moments)
            return real_prefetch(book, moments)

        def at(book, unit, moment):
            asked.append(moment)
            return real_at(book, unit, moment)
        with mock.patch.object(TemperatureBook, 'prefetch', prefetch), mock.patch.object(TemperatureBook, 'at', at):
            many, asks = self.figures('many')
        wanted = {end_of(self.day(back), self.t2) for back in range(1, 9)} | {self.pinned}      # days 8 .. today
        self.assertEqual(set(prefetched), wanted)
        self.assertTrue(asked)
        self.assertLessEqual(set(asked), wanted)
        self.assertEqual(len(asks), 1, asks)
        main, _asks = self.figures('one_by_one', as_main=True)
        self.assertSame((many,), (main,))
        self.assertEqual(self.days('many'), self.days('one_by_one', as_main=True))

    def test_a_unit_with_no_protocol_in_force_reads_no_temperature_ahead(self):
        ProtocolAssignment.objects.filter(unit=self.t2).update(valid_from=self.day(40), valid_until=self.day(30))
        many, asks = self.figures('many')
        self.assertEqual(asks, [])

    def test_a_failed_ask_for_all_the_days_costs_nothing_each_day_is_asked_on_its_own(self):
        """One failing ask fails every day of it together (`sources.values_at`); the walk then asks the days one by one,
        as it always did, and a failure that was only that ask's changes no figure."""
        self.providers['many'].values_at_broken = True
        with self.assertLogs('farm.water.sources', 'ERROR'):
            many, asked = self.figures('many')
            days = self.days('many')
        names = [ask[0] for ask in asked]
        self.assertEqual(names.count('values_at'), 1)                  # the one failed ask ...
        self.assertGreater(names.count('value_at'), 10)                # ... then the days, each on its own
        main, _asks = self.figures('one_by_one', as_main=True)
        self.assertSame((many,), (main,))
        self.assertEqual(days, self.days('one_by_one', as_main=True))
        self.assertIsNotNone(self.temperature_of(days, 3))

    def test_a_failure_costs_only_the_moment_it_hits_as_before(self):
        moment = end_of(self.day(3), self.t2)                          # the end of the day 3 days ago
        for provider in self.providers.values():
            provider.broken_at = {moment}
        self.providers['many'].values_at_broken = True
        with self.assertLogs('farm.water.sources', 'ERROR'):
            many, days = self.figures('many')[0], self.days('many')
            main_days = self.days('one_by_one', as_main=True)
        self.assertEqual(days, main_days)
        missing = [back for back in range(16) if days[(self.t2.pk, self.day(back))].shares[0].end.temperature is None]
        self.assertEqual(missing, [3])                                 # that day alone has no sensor temperature
        self.assertIsNotNone(self.temperature_of(days, 2))
        self.assertIsNotNone(self.temperature_of(days, 4))
        main, _asks = self.figures('one_by_one', as_main=True)
        self.assertSame((many,), (main,))

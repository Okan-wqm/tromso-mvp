"""The feeding records: the walk of the feed along the stock's timeline (the split, the measured points,
FCR and the feed rate, against the worked example of feeding-records §4.7), the one write path with the
fish rule both ways, the dialogs, the list, void, permissions and the integrations, each checked against
the stored rows."""
import io
import uuid
from datetime import date, datetime, time as clock, timedelta, timezone as dt_timezone
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import translation

from core import access, database, navigation
from core.dates import company_today
from core.models import AuditLog, Profile
from core.testing import FrozenClock

from ..feeding import read, services, views as feeding_views
from ..feeding.fold import Feeding, Point, PointKind, walk
from ..handling import check
from ..models import Equipment, EquipmentType, Feed, FeedingRecord, FeedSuitability, ProductionDepartment, Site, Tank
from ..stock import integrity, read as stock_read, services as stock_services
from ..stock.dates import local_today
from ..stock.fold import Line, Op
from ..templatetags.stock import tonnes
from .helpers import WINDOW_WAY_OUT, correction_window, make_facility, role
from .test_stock import StockTestCase, make_unit
from farm import withdrawal_gate


def setUpModule():
    call_command('compile_catalogs', verbosity=0)    # the language test reads the built catalogs


FEEDING_KEEPER = ('view_feedingrecord', 'add_feedingrecord', 'delete_feedingrecord', 'view_feed', 'delete_feed',
                  'view_equipment', 'delete_equipment')
DAY = timedelta(days=1)


# ---- the walk, without a database ------------------------------------------------------------------
def oct_(day):
    return date(2026, 10, day)


def op(seq, kind, day):
    return Op(f'op{seq}', kind, day, seq)


def line(line_id, operation, kind, delta, unit='T1', batch='B1', weight=None, pair=None, measured=None):
    return Line(line_id, operation, unit, batch, kind, delta, None if weight is None else Decimal(weight), pair,
                None if measured is None else Decimal(measured))


def fed(day, kilos, unit='T1', name=None):
    return Feeding(name or f'{unit}-{day.isoformat()}', unit, day, Decimal(kilos))


def worked_example():
    """feeding-records §4.7: 10,000 fish of 50 g stocked on 1 Oct, 200 found dead on 5 Oct (not weighed),
    12 kg fed a day from 1 to 14 Oct, 9,800 fish weighed at 70 g on 15 Oct."""
    lines = [line(1, op(1, 'input', oct_(1)), 'input', 10000, weight='50'),
             line(2, op(2, 'mortality', oct_(5)), 'mortality', -200),
             line(3, op(3, 'weighing', oct_(15)), 'weighing', 0, weight='70')]
    days = [('T1', oct_(day)) for day in range(1, 15)]
    return walk(lines, [fed(day, 12) for _unit, day in days], days), days


class WalkTests(SimpleTestCase):
    def test_the_worked_example_to_the_gram(self):
        walked, days = worked_example()
        stay = walked.stays[('T1', 'B1')][-1]
        self.assertEqual(stay.points, [
            Point(PointKind.START, oct_(1), Decimal(500), Decimal(0), Decimal(0), Decimal(0)),
            Point(PointKind.WEIGHING, oct_(15), Decimal(686), Decimal(10), Decimal(10), Decimal(0))])
        window = read.window(stay)
        self.assertEqual((window.feed_kg, window.gain_kg, window.economic_gain_kg), (168, 196, 186))
        conversion = read.Conversion([window])
        self.assertEqual(conversion.biological, Decimal(168) / Decimal(196))      # 0.857: bFCR 0.86
        self.assertEqual(conversion.economic, Decimal(168) / Decimal(186))        # 0.903: eFCR 0.90
        self.assertGreater(conversion.economic, conversion.biological)
        # SFR 1–14 Oct on the book: 500 kg (1 Oct at its end: empty that morning) × 5 days + 490 kg × 9 days.
        biomass_days = sum(walked.days[key].biomass_kg for key in days)
        self.assertEqual(biomass_days, 6910)
        self.assertEqual(round(100 * Decimal(168) / biomass_days, 2), Decimal('2.43'))
        self.assertEqual(walked.orphans, [])

    def test_a_mixed_unit_is_split_by_book_biomass_at_the_start_of_the_day(self):
        nov = lambda day: date(2026, 11, day)
        lines = [line(1, op(1, 'input', nov(1)), 'input', 1000, batch='A', weight='600'),
                 line(2, op(2, 'input', nov(1)), 'input', 2000, batch='B', weight='200'),
                 line(3, op(3, 'input', nov(2)), 'input', 100, batch='C', weight='100')]
        walked = walk(lines, [fed(nov(1), 10, name='first day'), fed(nov(2), 20, name='second day')])
        # 1 Nov: empty that morning, so by the end of the day; 2 Nov: A 600 kg and B 400 kg at its start,
        # C came in that day and is fed from the next.
        self.assertEqual(walked.split['first day'], {'A': 6, 'B': 4})
        self.assertEqual(walked.split['second day'], {'A': 12, 'B': 8})
        self.assertEqual(walked.stays[('T1', 'C')][-1].feed, {})

    def test_the_parts_of_a_record_add_up_to_it(self):
        lines = [line(1, op(1, 'input', oct_(1)), 'input', 3, batch='A', weight='1'),
                 line(2, op(2, 'input', oct_(1)), 'input', 7, batch='B', weight='1.3')]
        walked = walk(lines, [fed(oct_(2), '0.035', name='ration')])
        self.assertEqual(round(sum(walked.split['ration'].values()), 20), Decimal('0.035'))

    def test_a_feeding_needs_fish_at_the_start_or_the_end_of_its_day(self):
        lines = [line(1, op(1, 'input', oct_(2)), 'input', 10, weight='5'),
                 line(2, op(2, 'mortality', oct_(4)), 'mortality', -10)]
        feedings = [fed(oct_(1), 1, name='before'), fed(oct_(2), 1, name='stocking day'),
                    fed(oct_(4), 1, name='last day'), fed(oct_(5), 1, name='after'),
                    fed(oct_(3), 1, unit='T2', name='other unit')]
        walked = walk(lines, feedings)
        self.assertEqual([feeding.id for feeding in walked.orphans], ['before', 'other unit', 'after'])
        self.assertEqual(set(walked.split), {'stocking day', 'last day'})

    def test_no_fcr_without_a_weighing_without_feed_or_without_growth(self):
        stocked = line(1, op(1, 'input', oct_(1)), 'input', 1000, weight='100')
        unweighed = walk([stocked], [fed(oct_(1), 5)]).stays[('T1', 'B1')][-1]
        self.assertIsNone(read.window(unweighed))
        self.assertEqual(read.Conversion([]).why_no_biological, read.UNWEIGHED)
        weighed = line(2, op(2, 'weighing', oct_(9)), 'weighing', 0, weight='120')
        unfed = walk([stocked, weighed]).stays[('T1', 'B1')][-1]
        self.assertEqual(read.Conversion([read.window(unfed)]).why_no_biological, read.UNFED)
        shrunk = walk([stocked, line(2, op(2, 'weighing', oct_(9)), 'weighing', 0, weight='90')],
                      [fed(oct_(3), 5)]).stays[('T1', 'B1')][-1]
        conversion = read.Conversion([read.window(shrunk)])
        self.assertEqual((conversion.biological, conversion.why_no_biological), (None, read.NO_GAIN))

    def test_the_harvest_that_empties_the_unit_closes_the_window_with_its_day(self):
        lines = [line(1, op(1, 'input', oct_(1)), 'input', 1000, weight='100'),
                 line(2, op(2, 'harvest', oct_(10)), 'harvest', -1000, measured='120')]
        walked = walk(lines, [fed(oct_(day), 1) for day in range(1, 11)])
        window = read.window(walked.stays[('T1', 'B1')][-1])
        self.assertEqual((window.end.kind, window.end.biomass_kg, window.end.removed_kg), (PointKind.CLOSE, 0, 120))
        self.assertEqual((window.feed_kg, window.gain_kg), (10, 20))      # 0 − 100 + 120 kg; the harvest day fed

    def test_graded_fish_start_a_window_and_moved_fish_do_not(self):
        graded, moved = op(2, 'grading', oct_(5)), op(4, 'transfer', oct_(6))
        lines = [line(1, op(1, 'input', oct_(1)), 'input', 1000, weight='10'),
                 line(2, graded, 'transfer_out', -400, weight='20', pair=1),
                 line(3, graded, 'transfer_in', 400, unit='T2', pair=1),
                 line(4, graded, 'weighing', 0, weight='8'),
                 line(5, moved, 'transfer_out', -100, pair=1),
                 line(6, moved, 'transfer_in', 100, unit='T3', pair=1),
                 line(7, op(5, 'weighing', oct_(9)), 'weighing', 0, unit='T3', weight='9')]
        walked = walk(lines)
        source = walked.stays[('T1', 'B1')][-1].points
        self.assertEqual([(point.kind, point.biomass_kg, point.removed_kg) for point in source],
                         [(PointKind.START, 10, 0), (PointKind.WEIGHING, Decimal('4.8'), 8)])
        self.assertEqual(walked.stays[('T2', 'B1')][-1].points[0].kind, PointKind.START)
        self.assertEqual(walked.stays[('T2', 'B1')][-1].points[0].biomass_kg, 8)
        self.assertEqual([point.kind for point in walked.stays[('T3', 'B1')][-1].points], [PointKind.WEIGHING])
        self.assertIsNone(read.window(walked.stays[('T3', 'B1')][-1]))

    def test_weighed_dead_fish_are_removed_at_their_weight_and_counted_lost(self):
        lines = [line(1, op(1, 'input', oct_(1)), 'input', 1000, weight='100'),
                 line(2, op(2, 'mortality', oct_(3)), 'mortality', -50, measured='6'),
                 line(3, op(3, 'cull', oct_(4)), 'cull', -10),
                 line(4, op(4, 'weighing', oct_(9)), 'weighing', 0, weight='130')]
        end = walk(lines).stays[('T1', 'B1')][-1].points[-1]
        self.assertEqual((end.removed_kg, end.lost_kg), (7, 7))     # 6 kg weighed + 10 culls at 100 g
    def test_a_bounded_window_runs_between_the_measured_points_of_the_days_given(self):
        """Two consecutive windows add up to the whole stay's (the statistics will read consecutive windows)."""
        lines = [line(1, op(1, 'input', oct_(1)), 'input', 1000, weight='100'),
                 line(2, op(2, 'weighing', oct_(8)), 'weighing', 0, weight='120'),
                 line(3, op(3, 'weighing', oct_(15)), 'weighing', 0, weight='150')]
        stay = walk(lines, [fed(oct_(day), 5) for day in range(1, 15)]).stays[('T1', 'B1')][-1]
        whole, first = read.window(stay), read.window(stay, oct_(1), oct_(8))
        second = read.window(stay, oct_(8), oct_(15))
        self.assertEqual((whole.feed_kg, whole.gain_kg), (70, 50))
        self.assertEqual((first.feed_kg, first.gain_kg), (35, 20))            # the days 1 to 7 and 100 -> 120 kg
        self.assertEqual((second.feed_kg, second.gain_kg), (35, 30))          # the days 8 to 14 and 120 -> 150 kg
        self.assertEqual(read.window(stay, oct_(1), oct_(15)), whole)
        self.assertEqual(read.window(stay, None, oct_(8)), first)             # no bound: the stay's own end
        self.assertEqual(read.window(stay, oct_(8), None), second)
        self.assertEqual(read.Conversion([first, second]).biological, read.Conversion([whole]).biological)

    def test_a_bound_without_a_measured_point_that_day_gives_no_window_and_never_an_interpolated_one(self):
        lines = [line(1, op(1, 'input', oct_(1)), 'input', 1000, weight='100'),
                 line(2, op(2, 'weighing', oct_(8)), 'weighing', 0, weight='120'),
                 line(3, op(3, 'weighing', oct_(15)), 'weighing', 0, weight='150')]
        stay = walk(lines, [fed(oct_(day), 5) for day in range(1, 15)]).stays[('T1', 'B1')][-1]
        for first, last in ((oct_(2), oct_(15)), (oct_(1), oct_(9)), (oct_(2), None), (None, oct_(14)),
                            (oct_(16), None), (None, oct_(1)),            # a window ends after it starts
                            (oct_(8), oct_(8)), (oct_(15), oct_(8)), (oct_(15), None)):
            with self.subTest(first=first, last=last):
                self.assertIsNone(read.window(stay, first, last))

    def test_the_last_point_of_a_day_is_the_state_at_the_end_of_it(self):
        lines = [line(1, op(1, 'input', oct_(1)), 'input', 1000, weight='100'),
                 line(2, op(2, 'weighing', oct_(8)), 'weighing', 0, weight='120'),
                 line(3, op(3, 'weighing', oct_(8)), 'weighing', 0, weight='130'),
                 line(4, op(4, 'weighing', oct_(15)), 'weighing', 0, weight='150')]
        stay = walk(lines, [fed(oct_(day), 5) for day in range(1, 15)]).stays[('T1', 'B1')][-1]
        self.assertEqual(read.window(stay, oct_(1), oct_(8)).gain_kg, 30)     # 100 -> 130 kg, the second weighing
        self.assertEqual(read.window(stay, oct_(8), oct_(15)).gain_kg, 20)    # 130 -> 150 kg

    def test_the_harvest_that_closes_a_stay_ends_a_bounded_window_with_its_day_fed(self):
        lines = [line(1, op(1, 'input', oct_(1)), 'input', 1000, weight='100'),
                 line(2, op(2, 'weighing', oct_(5)), 'weighing', 0, weight='110'),
                 line(3, op(3, 'harvest', oct_(10)), 'harvest', -1000, measured='120')]
        stay = walk(lines, [fed(oct_(day), 1) for day in range(1, 11)]).stays[('T1', 'B1')][-1]
        closed = read.window(stay, oct_(5), oct_(10))
        self.assertEqual((closed.end.kind, closed.feed_kg), (PointKind.CLOSE, 6))        # the days 5 to 10
        self.assertEqual(read.window(stay, oct_(5)), closed)


# ---- the write path and the pages ------------------------------------------------------------------
class FeedingTestCase(StockTestCase):
    def setUp(self):
        super().setUp()
        self.user.groups.add(role('Feeding keeper', *FEEDING_KEEPER))
        self.feed = Feed.objects.create(name='Grower 4', code='GR-4', feed_type='grower', pellet_size_mm=Decimal(4))
        self.batch = self.stock(count=10000, weight='50', days_ago=20)          # 500 kg in T-01

    def record(self, kilos='12', days_ago=1, unit=None, **fields):
        return services.record_feeding(self.user, unit=unit or self.t1, day=self.day(days_ago),
                                       feed=fields.pop('feed', self.feed), amount_kg=Decimal(kilos), **fields)

    def data(self, **fields):
        return {'token': str(uuid.uuid4()), 'date': self.day(1).isoformat(), 'feed': str(self.feed.pk),
                'amount_kg': '12.5', 'meals': '3', 'time': '08:30', 'feeder': '', 'notes': '', **fields}

    def url(self, unit=None):
        return f'{reverse("farm:feeding_record", args=[(unit or self.t1).pk])}?unit={(unit or self.t1).pk}'

    def feeder(self, department=None, code='FD-1'):
        return Equipment.objects.create(name=f'Feeder {code}', code=code, production_department=department or self.hall,
                                        equipment_type=EquipmentType.objects.get(code='feeder-automatic'))


class RecordTests(FeedingTestCase):
    def test_a_feeding_through_the_drawers_dialog_is_stored_and_logged(self):
        form = self.client.get(self.url(), headers={'X-Modal': '1'})
        self.assertContains(form, 'Record feeding')
        self.assertEqual(form.context['form']['date'].value(), self.today)
        feeder = self.feeder()
        response = self.client.post(self.url(), self.data(feeder=str(feeder.pk), notes='Good appetite'),
                                    headers={'X-Modal': '1'})
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response['X-Modal-Redirect'], f'{reverse("farm:production_units")}?unit={self.t1.pk}')
        record = FeedingRecord.objects.get()
        self.assertEqual(
            (record.unit, record.date, record.time.isoformat(), record.feed, record.amount_kg, record.meals,
             record.feeder, record.notes, record.high_rate_ack, record.created_by),
            (self.t1, self.day(1), '08:30:00', self.feed, Decimal('12.500'), 3, feeder, 'Good appetite', False,
             self.user))
        logged = AuditLog.objects.get(entity_type='feeding record')
        self.assertEqual((logged.action, logged.entity_label),
                         ('create', f'Feeding · T-01 · {self.day(1).isoformat()} · 12.5 kg · GR-4'))
        self.assertEqual(logged.changes['Feed given (kg)'], [None, '12.500'])
        self.assertEqual(logged.changes['Feeder'], [None, str(feeder)])
        page = self.client.get(reverse('farm:production_units'), {'unit': self.t1.pk})
        self.assertContains(page, f'Feeding recorded: 12.5 kg of Grower 4 (GR-4) · 4 mm in T-01 on '
                                  f'{stock_services.shown_date(self.day(1))}.')

    def test_the_date_is_within_the_window_and_the_unit_holds_fish_that_day(self):
        self.assertEqual(self.refused(self.record, days_ago=-1), {'date': ['The date cannot be in the future.']})
        self.assertEqual(self.refused(self.record, days_ago=32),
                         {'date': [f'Operations can be dated at most 31 days back. {WINDOW_WAY_OUT}']})
        self.assertEqual(self.refused(self.record, days_ago=21),
                         {'date': [f'T-01 holds no fish on {stock_services.shown_date(self.day(21))}.']})
        self.assertEqual(self.refused(self.record, unit=self.t2),
                         {'date': [f'T-02 holds no fish on {stock_services.shown_date(self.day(1))}.']})
        self.record(days_ago=20)                       # the stocking day: fish at its end
        self.assertEqual(FeedingRecord.objects.count(), 1)

    def test_a_new_feeding_takes_an_active_feed_and_an_old_one_keeps_its_feed(self):
        record = self.record()
        self.feed.status = Feed.Status.DISCONTINUED
        self.feed.save()
        self.assertEqual(self.refused(self.record), {'feed': ['Grower 4 (GR-4) is discontinued: a new feeding takes '
                                                              'an active feed.']})
        form = self.client.get(self.url()).context['form']
        self.assertNotIn(self.feed, form.fields['feed'].queryset)
        record.refresh_from_db()
        self.assertEqual(record.feed, self.feed)
        self.assertContains(self.client.get(reverse('farm:feeding_records')), 'Grower 4')

    def test_the_feeder_is_on_the_units_site(self):
        elsewhere = self.feeder(self.sea, code='FD-SEA')
        here = self.feeder()
        pump = Equipment.objects.create(name='Pump', code='PU-1', production_department=self.hall,
                                        equipment_type=EquipmentType.objects.get(code='pump-centrifugal'))
        form = self.client.get(self.url()).context['form']
        self.assertEqual(list(form.fields['feeder'].queryset), [here])
        self.assertEqual(self.refused(self.record, feeder=elsewhere),
                         {'feeder': ['Choose a feeder on the site of T-01.']})
        self.assertIn('feeder', self.refused(self.record, feeder=pump))
        self.assertEqual(self.record(feeder=here).feeder, here)

    def test_above_the_usual_rate_only_with_the_acknowledgement(self):
        response = self.client.post(self.url(), self.data(amount_kg='60'), headers={'X-Modal': '1'})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.context['form'].errors['high_rate_ack'], [
            f'60 kg fed on {stock_services.shown_date(self.day(1))}, this feeding included, is 12.0 % of the 500.0 kg T-01 '
            'holds in the book; more than 10 % a day is unusual. Tick the box below to record it anyway.'])
        self.assertContains(response, 'name="high_rate_ack"', status_code=422)
        self.assertFalse(FeedingRecord.objects.exists())
        self.client.post(self.url(), self.data(amount_kg='60', high_rate_ack='on'), headers={'X-Modal': '1'})
        self.assertTrue(FeedingRecord.objects.get().high_rate_ack)
        # A tick that was not needed is not stored as an acknowledgement.
        self.assertFalse(self.record(kilos='5', days_ago=2, ack=True).high_rate_ack)

    def test_the_usual_rate_is_of_the_days_total_not_of_one_feeding(self):
        """Q-F5 asks about more than 10 % a day: two feedings of 6 % each are 12 % that day (audit F-081)."""
        self.record(kilos='30')
        errors = self.refused(self.record, kilos='30')
        self.assertIn('60 kg fed on', errors['high_rate_ack'][0])
        self.assertIn('is 12.0 % of the 500.0 kg T-01 holds', errors['high_rate_ack'][0])
        self.assertTrue(self.record(kilos='30', ack=True).high_rate_ack)
        self.assertFalse(self.record(kilos='30', days_ago=2).high_rate_ack)          # another day

    def test_the_same_form_sent_twice_records_once(self):
        data = self.data()
        self.client.post(self.url(), data, headers={'X-Modal': '1'})
        self.assertEqual(self.client.post(self.url(), data, headers={'X-Modal': '1'}).status_code, 204)
        self.assertEqual(FeedingRecord.objects.count(), 1)

    def test_amounts_to_the_gram_and_the_bounds(self):
        self.client.post(self.url(), self.data(amount_kg='0.035', meals=''))
        record = FeedingRecord.objects.get()
        self.assertEqual((record.amount_kg, record.meals, record.time.hour), (Decimal('0.035'), None, 8))
        response = self.client.post(self.url(), self.data(amount_kg='0', meals='49', date=''))
        self.assertEqual(set(response.context['form'].errors), {'amount_kg', 'meals', 'date'})
        self.assertContains(self.client.get(reverse('farm:feeding_records')), '0.035 kg')

    def test_the_feeds_that_suit_the_fish_come_first_and_another_is_only_noticed(self):
        other = Feed.objects.create(name='Starter 1', code='ST-1', feed_type='starter')
        FeedSuitability.objects.create(feed=self.feed, species=self.salmon, growth_stage='all', min_weight_g=20,
                                       max_weight_g=100)
        choices = self.client.get(self.url()).context['form'].fields['feed'].choices
        self.assertEqual([(str(group), [str(label) for _value, label in options]) for group, options in choices[1:]],
                         [('Suitable for these fish', ['Grower 4 (GR-4) · 4 mm']),
                          ('Other active feeds', ['Starter 1 (ST-1)'])])
        self.client.post(self.url(), self.data(feed=str(other.pk)))
        page = self.client.get(reverse('farm:production_units'), {'unit': self.t1.pk})
        self.assertContains(page, 'Starter 1 (ST-1) is not listed as suitable for Atlantic salmon (SAL) at 50.0 g')
        self.assertEqual(FeedingRecord.objects.get().feed, other)

    def test_a_deleted_unit_is_not_fed(self):
        Tank.all_objects.filter(pk=self.t1.pk).update(is_deleted=True)
        self.assertEqual(self.refused(self.record), {'unit': ['T-01 is deleted.']})


class SplitTests(FeedingTestCase):
    def test_a_unit_with_two_batches_feeds_both_by_their_biomass(self):
        second = self.stock(count=2500, weight='80', days_ago=10)            # 200 kg beside 500 kg
        early, both = self.record(kilos='10', days_ago=15), self.record(kilos='14', days_ago=5)
        self.assertEqual(read.split_of([early, both]), {early.pk: {self.batch.pk: 10},
                                                        both.pk: {self.batch.pk: 10, second.pk: 4}})
        form = self.client.get(self.url())
        self.assertContains(form, f'Split by the book biomass at the start of '
                                  f'{stock_services.shown_date(self.today)}:')
        self.assertContains(form, f'{self.batch.code} 71 %, {second.code} 29 %')
        listed = self.client.get(reverse('farm:feeding_records'))
        self.assertContains(listed, f'{self.batch.code} + {second.code}')
        only_second = self.client.get(reverse('farm:feeding_records'), {'batch': second.pk})
        self.assertEqual([row['record'] for row in only_second.context['rows']], [both])
        drawer = self.client.get(reverse('farm:production_units'), {'unit': self.t1.pk})
        self.assertEqual([(share.batch, fed.fed_kg) for share, fed in drawer.context['batch_rows']],
                         [(self.batch, 20), (second, 4)])


class FedInAPeriodTests(FeedingTestCase):
    """The feed of a period as the regulatory reports read it: each record split as split_of splits it, per unit,
    batch and feed (farm/feeding/read.py fed)."""

    def test_the_feed_of_a_period_per_unit_batch_and_feed(self):
        second = self.stock(count=2500, weight='80', days_ago=10)            # 200 kg beside 500 kg
        other = Feed.objects.create(name='Starter 1', code='ST-1', feed_type='starter')
        self.record(kilos='10', days_ago=15)
        self.record(kilos='14', days_ago=5)
        self.record(kilos='7', days_ago=5, feed=other)
        self.record(kilos='3', days_ago=1)
        self.assertEqual(read.fed([self.t1], self.day(15), self.day(5)), {
            (self.t1.pk, self.batch.pk, self.feed.pk): 20, (self.t1.pk, second.pk, self.feed.pk): 4,
            (self.t1.pk, self.batch.pk, other.pk): 5, (self.t1.pk, second.pk, other.pk): 2})
        self.assertEqual(read.fed([self.t1], self.day(4), self.today), {
            (self.t1.pk, self.batch.pk, self.feed.pk): Decimal('3') * 500 / 700,
            (self.t1.pk, second.pk, self.feed.pk): Decimal('3') * 200 / 700})
        self.assertEqual(read.fed([self.t2], self.day(30), self.today), {})

    def test_a_voided_record_is_not_fed(self):
        record = self.record(kilos='10', days_ago=2)
        services.void_feeding(self.user, record, 'Wrong unit')
        self.assertEqual(read.fed([self.t1], self.day(30), self.today), {})


class FishRuleTests(FeedingTestCase):
    def test_a_backdated_harvest_cannot_leave_a_feeding_without_fish(self):
        feeding = self.record(days_ago=1)
        facility = make_facility()
        harvest = lambda: stock_services.record_harvest(self.user, unit=self.t1, batch=self.batch, day=self.day(2),
                                                        count=10000, measured_weight_kg=Decimal(510),
                                                        facility=facility)
        self.assertEqual(self.refused(harvest), {'__all__': [
            f'The feeding of {stock_services.shown_date(self.day(1))} in T-01 would have no fish: void it first.']})
        services.void_feeding(self.user, feeding, 'Fed the wrong unit')
        harvest()
        self.assertEqual(self.fish(self.t1), 0)

    def test_the_stocking_that_brought_the_fish_is_not_voided_while_a_feeding_needs_them(self):
        self.record(days_ago=19)
        stocking = self.batch.movements.get().operation
        self.assertIn('would have no fish: void it first.',
                      self.refused(stock_services.void, self.user, stocking, 'Wrong species')['__all__'][0])

    def test_fish_that_leave_on_the_feeding_day_were_fed_that_morning(self):
        self.record(days_ago=1)
        self.mortality(self.batch, 10000, days_ago=1)
        self.assertEqual(self.fish(self.t1), 0)
        self.assertStockAddsUp()

    @withdrawal_gate.opened('test fixture: withdrawal inputs written straight in the database')
    def test_check_stock_reports_a_feeding_moved_past_the_service(self):
        feeding = self.record(days_ago=1)
        call_command('check_stock', stdout=io.StringIO())
        FeedingRecord.objects.filter(pk=feeding.pk).update(date=self.day(25))
        self.assertIn(f'Feeding {feeding.pk} of {self.day(25)} in unit T-01: no fish in the unit at the start or the '
                      'end of that day.', integrity.problems())


class VoidTests(FeedingTestCase):
    def test_void_through_its_dialog_keeps_the_record_with_its_reason(self):
        feeding = self.record()
        url = f'{reverse("farm:feeding_void", args=[feeding.pk])}?unit={self.t1.pk}'
        self.assertContains(self.client.get(url), f'Void the feeding of {stock_services.shown_date(self.day(1))} in '
                                                  'T-01?')
        self.assertEqual(self.client.post(url, {'reason': ' '}, headers={'X-Modal': '1'}).status_code, 422)
        response = self.client.post(url, {'reason': 'Typed 12 for 1.2'}, headers={'X-Modal': '1'})
        self.assertEqual(response['X-Modal-Redirect'], f'{reverse("farm:production_units")}?unit={self.t1.pk}')
        feeding = FeedingRecord.all_objects.get(pk=feeding.pk)
        self.assertEqual((feeding.is_deleted, feeding.void_reason, feeding.deleted_by),
                         (True, 'Typed 12 for 1.2', self.user))
        logged = AuditLog.objects.get(entity_type='feeding record', action='void')
        self.assertEqual(logged.changes, {'Reason for voiding': [None, 'Typed 12 for 1.2']})
        self.assertEqual(self.client.get(url).status_code, 404)
        drawer = self.client.get(reverse('farm:production_units'), {'unit': self.t1.pk})
        self.assertContains(drawer, 'voided by ali: Typed 12 for 1.2')
        self.assertEqual(self.client.get(reverse('farm:feeding_records')).context['rows'], [])
        self.assertContains(self.client.get(reverse('farm:feeding_records'), {'voided': '1'}), 'class="is-voided"')
        self.assertEqual(self.refused(services.void_feeding, self.user, feeding, 'again'),
                         {'__all__': ['This operation is already voided.']})

    def test_the_log_is_in_english_whatever_language_voids_it(self):
        feeding = self.record()
        Profile.objects.update_or_create(user=self.user, defaults={'language': 'tr'})
        self.client.post(reverse('farm:feeding_void', args=[feeding.pk]), {'reason': 'Yanlış birim'})
        logged = AuditLog.objects.get(entity_type='feeding record', action='void')
        self.assertEqual(logged.entity_label, f'Feeding · T-01 · {self.day(1).isoformat()} · 12 kg · GR-4')

    @withdrawal_gate.opened('test fixture: withdrawal inputs written straight in the database')
    def test_only_within_the_backdating_window(self):
        feeding = self.record(days_ago=20)
        FeedingRecord.objects.filter(pk=feeding.pk).update(date=self.day(32))
        self.assertEqual(self.refused(services.void_feeding, self.user, feeding, 'old'),
                         {'__all__': [f'Operations older than 31 days cannot be voided. {WINDOW_WAY_OUT}']})

    @correction_window(60)
    @translation.override('en')              # the test before it voided in Turkish: the language must not leak in
    @withdrawal_gate.opened('test fixture: withdrawal inputs written straight in the database')
    def test_the_window_is_the_platform_owners_setting(self):
        self.assertEqual(self.refused(self.record, days_ago=61),
                         {'date': [f'Operations can be dated at most 60 days back. {WINDOW_WAY_OUT}']})
        self.assertEqual(self.refused(self.record, days_ago=32),             # not the window: the fish
                         {'date': [f'T-01 holds no fish on {stock_services.shown_date(self.day(32))}.']})
        feeding = self.record(days_ago=20)
        FeedingRecord.objects.filter(pk=feeding.pk).update(date=self.day(61))
        self.assertEqual(self.refused(services.void_feeding, self.user, feeding, 'old'),
                         {'__all__': [f'Operations older than 60 days cannot be voided. {WINDOW_WAY_OUT}']})


class FiguresTests(FeedingTestCase):
    """The worked example of feeding-records §4.7 through the service and the pages: 10,000 fish of 50 g
    stocked 20 days ago, 200 dead 16 days ago (not weighed), 12 kg a day for 14 days, weighed at 70 g 6
    days ago; 10 kg in 3 meals today."""

    def setUp(self):
        super().setUp()
        self.mortality(self.batch, 200, days_ago=16)
        for days_ago in range(20, 6, -1):
            self.record(days_ago=days_ago)
        stock_services.record_weighing(self.user, unit=self.t1, batch=self.batch, day=self.day(6),
                                       avg_weight_g=Decimal(70))
        self.record(kilos='10', days_ago=0, meals=3)

    def test_bfcr_efcr_and_the_feed_rate_from_the_records_and_the_ledger(self):
        units = list(Tank.objects.all())
        figures = read.figures(stock_read.stock_of(units), details=[self.t1])[self.t1.pk]
        conversion = figures.conversion
        self.assertEqual((conversion.feed_kg, conversion.gain_kg, conversion.economic_gain_kg), (168, 196, 186))
        self.assertEqual((figures.last_fed, figures.week.today_kg, figures.week.today_meals, figures.week.kg),
                         (self.today, 10, 3, 10))
        # The last 7 days: 490 kg at the start of the weighing day, then 686 kg for 6 days.
        self.assertEqual(figures.week.biomass_days_kg, 490 + 6 * 686)
        self.assertEqual(figures.week.sfr, 100 * Decimal(10) / 4606)
        self.assertEqual(figures.week.feed, self.feed)
        self.assertEqual(figures.shares[0].fed_kg, 178)

    def test_the_page_and_the_drawer_show_them(self):
        response = self.client.get(reverse('farm:production_units'), {'unit': self.t1.pk})
        html = response.content.decode()
        row = next(row for row in response.context['rows'] if row['unit'] == self.t1)
        self.assertEqual(round(row['feeding'].conversion.biological, 2), Decimal('0.86'))
        for text in ('>0.86<', '>0.90<', '>Today<', '10 kg', '3 meals', 'Feed rate 0.22 % of the biomass a day over '
                     'the last 7 days', 'biomass as weighed 6 days ago', 'feed in use: Grower 4 (GR-4)',
                     f'{self.batch.code}: {stock_services.shown_date(self.day(20))} – '
                     f'{stock_services.shown_date(self.day(6))}, 168 kg fed, 196 kg grown', '178 kg',
                     'Recent feedings', 'All feeding records of T-01'):
            self.assertIn(text, html)
        self.assertEqual(response.context['actions'][0], {
            'label': 'Record feeding', 'url': f'{reverse("farm:feeding_record", args=[self.t1.pk])}?unit={self.t1.pk}',
            'primary': True})
        self.assertFalse(any(action['primary'] for action in response.context['actions'][1:]))

    def test_last_fed_and_an_unweighed_unit(self):
        self.stock(self.t2, count=1000, weight='100', days_ago=3)
        self.record(kilos='5', unit=self.t2, days_ago=1)
        response = self.client.get(reverse('farm:production_units'))
        row = next(row for row in response.context['rows'] if row['unit'] == self.t2)
        self.assertEqual(row['feeding'].last_fed, self.day(1))
        self.assertContains(response, '>Yesterday<')
        self.assertContains(response, 'title="Not weighed since the fish came in."', count=1)

    def test_the_overview_shows_the_feed(self):
        """Each site counts on its own day (the owner's decision of 12.11.2026): the 10 kg given today on T-01's site,
        which reads UTC, are in "Feed today" at once, also in the hours when the company's day (Oslo's) has turned
        and UTC's has not (core/tests_day_boundary.py holds the clock there)."""
        tiles = self.client.get(reverse('production_home')).context['feeding_tiles']
        self.assertEqual([(str(tile['label']), tile['count']) for tile in tiles],
                         [('Feed today', '10 kg'), ('Feed, last 7 days', '10 kg')])


class OverviewFeedOnSeveralClocksTests(FrozenClock, FeedingTestCase):
    """The overview's "Feed today" and "Feed, last 7 days" on a farm whose sites read several clocks: each site counts on
    its own day, and the figure is the sum of each site's own day (the owner's decision of 12.11.2026). 16:00 UTC on
    the 10th is the 10th in Bergen (the fixtures' site, UTC) and in Oslo (the company) and the 11th in Tokyo."""
    NOW = datetime(2026, 11, 10, 16, 0, tzinfo=dt_timezone.utc)

    def setUp(self):
        super().setUp()
        tokyo = Site.objects.create(name='Tokyo', code='TK', timezone='Asia/Tokyo')
        self.k1 = make_unit('K-01', ProductionDepartment.objects.create(site=tokyo, name='Hall T', code='HT'))
        self.stock(self.k1, count=1000, weight='100', days_ago=10)
        self.here, self.there = local_today(self.t1), local_today(self.k1)
        self.assertEqual((self.here, self.there, company_today()), (date(2026, 11, 10), date(2026, 11, 11), self.here))

    def fed(self, unit, day, kilos):
        services.record_feeding(self.user, unit=unit, day=day, feed=self.feed, amount_kg=Decimal(kilos))

    def tiles(self):
        return {tile['key']: tile for tile in self.client.get(reverse('production_home')).context['feeding_tiles']}

    def test_feed_given_on_a_sites_today_is_in_feed_today_whatever_the_companys_clock_says(self):
        self.fed(self.k1, self.there, '4')                         # Tokyo's today, the 11th: the company's tomorrow
        self.fed(self.k1, self.there - DAY, '2')                   # Tokyo's yesterday, though it is the company's today
        self.fed(self.t1, self.here, '10')                         # Bergen's today
        self.fed(self.t1, self.here - DAY, '1')
        tiles = self.tiles()
        self.assertEqual((tiles['today']['count'], tiles['week']['count']),
                         (tonnes(Decimal(14)), tonnes(Decimal(17))))

    def test_the_seven_days_are_each_sites_own_last_seven(self):
        self.fed(self.k1, self.there - 6 * DAY, '1')               # the 5th: the first of Tokyo's seven
        self.fed(self.k1, self.there - 7 * DAY, '9')               # the 4th: before them, though in the company's seven
        self.fed(self.t1, self.here - 6 * DAY, '3')                # the 4th: the first of Bergen's seven
        self.fed(self.t1, self.here - 7 * DAY, '20')               # the 3rd: before them
        tiles = self.tiles()
        self.assertEqual((tiles['today']['count'], tiles['week']['count']), (tonnes(Decimal(0)), tonnes(Decimal(4))))

    def test_the_cards_say_so_and_open_the_records_of_those_days(self):
        tiles = self.tiles()
        self.assertEqual({str(tile['sub']) for tile in tiles.values()}, {'Each site on its own day'})
        records = reverse('farm:feeding_records')
        self.assertEqual((tiles['today']['url'], tiles['week']['url']),
                         (f'{records}?from=2026-11-10&to=2026-11-11', f'{records}?from=2026-11-04&to=2026-11-11'))
        for language, words in (('en', 'Each site on its own day'), ('nb', 'Hver lokalitet på sin egen dag'),
                                ('tr', 'Her saha kendi gününde')):
            with self.subTest(language=language):
                self.assertContains(self.client.get(reverse('production_home'), headers={'Accept-Language': language}),
                                    words, count=2)

    def test_a_farm_of_one_clock_says_nothing_of_it(self):
        Site.objects.filter(code='TK').update(timezone=self.bergen.timezone)
        self.assertEqual({str(tile['sub']) for tile in self.tiles().values()}, {''})

class WindowsInTests(FeedingTestCase):
    """The windows of the units over days (read.windows_in), against the figures of the same worked example."""

    def setUp(self):
        super().setUp()
        self.mortality(self.batch, 200, days_ago=16)
        for days_ago in range(20, 6, -1):
            self.record(days_ago=days_ago)
        stock_services.record_weighing(self.user, unit=self.t1, batch=self.batch, day=self.day(6),
                                       avg_weight_g=Decimal(70))

    def move(self, source, target, days_ago):
        """All the batch's fish from one unit to the other (the handling warnings of the recent feeding read)."""
        day = self.day(days_ago)
        stock_services.record_transfer(
            self.user, source=source, batch=self.batch, day=day, legs=[(target, 9800)], reason='grading',
            handling_ack=check.assess('transport', source, day, self.batch).fingerprint)

    def test_unbounded_and_bounded_by_its_measured_days_they_are_the_figures_window(self):
        shown = read.figures(stock_read.stock_of([self.t1]))[self.t1.pk].conversion
        for first, last in ((None, None), (self.day(20), self.day(6)), (self.day(20), None), (None, self.day(6))):
            with self.subTest(first=first, last=last):
                found = read.windows_in([self.t1.pk], first, last)
                self.assertEqual(list(found), [(self.t1.pk, self.batch.pk)])
                conversion = read.Conversion(list(found.values()))
                self.assertEqual((conversion.feed_kg, conversion.gain_kg, conversion.economic_gain_kg),
                                 (shown.feed_kg, shown.gain_kg, shown.economic_gain_kg))
                self.assertEqual((conversion.feed_kg, conversion.gain_kg), (168, 196))
        for first, last in ((self.day(19), None), (None, self.day(5)), (self.day(6), None),
                            (self.day(20), self.day(7))):
            with self.subTest(first=first, last=last):
                self.assertEqual(read.windows_in([self.t1.pk], first, last), {})

    def test_the_measured_points_of_a_day_are_the_ones_a_window_can_start_or_end_on(self):
        self.assertEqual(read.measured_on([self.t1.pk], self.day(20)), {(self.t1.pk, self.batch.pk)})     # stocked
        self.assertEqual(read.measured_on([self.t1.pk], self.day(6)), {(self.t1.pk, self.batch.pk)})      # weighed
        for day in (self.day(19), self.day(10), self.day(5), self.day(21)):
            self.assertEqual(read.measured_on([self.t1.pk], day), set())
        self.assertEqual(read.measured_on([self.t2.pk], self.day(20)), set())
        self.assertEqual(read.measured_on([], self.day(20)), set())

    def test_only_the_units_asked_for_and_only_the_feed_of_their_days(self):
        self.assertEqual(read.windows_in([]), {})
        self.assertEqual(read.windows_in([self.t2.pk]), {})
        self.record(unit=self.t1, days_ago=5, kilos='7')              # after the weighing: not in the window
        found = read.windows_in([self.t1.pk], self.day(20))
        self.assertEqual(read.Conversion(list(found.values())).feed_kg, 168)
        # The fish moved on: the window is of the unit that fed them, not of the one they went to.
        self.move(self.t1, self.t2, 4)
        self.assertEqual(list(read.windows_in([self.t1.pk], self.day(20))), [(self.t1.pk, self.batch.pk)])
        self.assertEqual(read.windows_in([self.t2.pk], self.day(20)), {})        # no measured point in T-02 yet

    def test_a_batch_that_came_back_has_the_window_of_its_latest_stay_that_has_one(self):
        self.move(self.t1, self.t2, 5)
        self.move(self.t2, self.t1, 4)
        stock_services.record_weighing(self.user, unit=self.t1, batch=self.batch, day=self.day(2),
                                       avg_weight_g=Decimal(75))
        # The second stay in T-01 begins with a plain transfer: its first point is a weighing, so it has no window
        # (the figures page shows the same dash); the first stay still has its own.
        found = read.windows_in([self.t1.pk])
        self.assertEqual(read.Conversion(list(found.values())).feed_kg, 168)
        self.assertIsNone(read.figures(stock_read.stock_of([self.t1]))[self.t1.pk].shares[0].window)


class ListTests(FeedingTestCase):
    def test_filters_order_and_the_count_line(self):
        sea_unit = make_unit('S-01', self.sea)
        self.stock(sea_unit, count=1000, weight='100', days_ago=5)
        other = Feed.objects.create(name='Starter 1', code='ST-1', feed_type='starter')
        late = self.record(days_ago=2)
        morning = self.record(days_ago=2, time=clock(7))
        sea = self.record(kilos='3', days_ago=1, unit=sea_unit, feed=other)
        listed = lambda **query: [row['record'].pk for row in
                                  self.client.get(reverse('farm:feeding_records'), query).context['rows']]
        self.assertEqual(listed(), [sea.pk, morning.pk, late.pk])          # a record without a time after the day's
        self.assertEqual(listed(site=self.tromso.pk), [sea.pk])
        self.assertEqual(listed(unit=self.t1.pk), [morning.pk, late.pk])
        self.assertEqual(listed(feed=other.pk), [sea.pk])
        self.assertEqual(listed(**{'from': self.day(1).isoformat()}), [sea.pk])
        self.assertEqual(listed(to=self.day(2).isoformat()), [morning.pk, late.pk])
        self.assertEqual(listed(site='x', unit='y', feed='z', batch='w', **{'from': 'v'}),
                         [sea.pk, morning.pk, late.pk])
        response = self.client.get(reverse('farm:feeding_records'))
        self.assertContains(response, '3 records · 27 kg')
        self.assertContains(response, '<h1>Records</h1>', html=True)

    def test_record_feeding_from_the_list_goes_back_to_the_list(self):
        listing = f'{reverse("farm:feeding_records")}?unit={self.t1.pk}'
        chooser = self.client.get(self.client.get(listing).context['record_url'])
        unit_url = chooser.context['units'][0]['url']
        self.assertEqual([item['unit'] for item in chooser.context['units']], [self.t1])
        response = self.client.post(unit_url, self.data(), headers={'X-Modal': '1'})
        self.assertEqual(response['X-Modal-Redirect'], listing)
        elsewhere = f'{reverse("farm:feeding_record", args=[self.t1.pk])}?next=https://evil.example/'
        response = self.client.post(elsewhere, self.data(), headers={'X-Modal': '1'})
        self.assertEqual(response['X-Modal-Redirect'],                    # not a page of this site
                         f'{reverse("farm:production_units")}?unit={self.t1.pk}')


class PermissionTests(FeedingTestCase):
    def as_role(self, *codenames):
        person = get_user_model().objects.create_user(f'p{len(codenames)}', f'p{len(codenames)}@example.com')
        person.groups.add(role(f'Role {len(codenames)}', *codenames))
        self.client.force_login(person)

    def test_read_record_and_void_are_separate(self):
        feeding = self.record()
        void = reverse('farm:feeding_void', args=[feeding.pk])
        self.as_role('view_feedingrecord', 'view_stockoperation')
        page = self.client.get(reverse('farm:feeding_records'))
        self.assertEqual(page.status_code, 200)
        for text in ('Record feeding', '>Void</a>'):
            self.assertNotContains(page, text)
        self.assertNotContains(self.client.get(reverse('farm:production_units'), {'unit': self.t1.pk}),
                               'Record feeding')
        for url in (self.url(), reverse('farm:feeding_new'), void):
            self.assertEqual(self.client.post(url, {}).status_code, 403, url)
        self.as_role('view_feedingrecord', 'add_feedingrecord', 'view_stockoperation')
        self.assertContains(self.client.get(reverse('farm:production_units'), {'unit': self.t1.pk}), 'Record feeding')
        self.assertEqual(self.client.post(void, {'reason': 'x'}).status_code, 403)
        self.assertFalse(FeedingRecord.all_objects.filter(is_deleted=True).exists())

    def test_no_read_no_page_no_menu_entry_and_no_feeding_part_in_the_drawer(self):
        self.as_role('view_stockoperation')
        self.assertEqual(self.client.get(reverse('farm:feeding_records')).status_code, 403)
        drawer = self.client.get(reverse('farm:production_units'), {'unit': self.t1.pk})
        self.assertNotContains(drawer, reverse('farm:feeding_records'))
        self.assertNotContains(drawer, 'Recent feedings')

    def test_production_units_prints_no_feeding_figure_without_the_right_to_read_feeding(self):
        self.record()
        url = reverse('farm:production_units')
        self.as_role('view_stockoperation')
        page = self.client.get(url, {'unit': self.t1.pk})
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.context['feeding'], None)
        self.assertEqual(page.context['rows'][0]['feeding'], None)
        # (the drawer's harvest check says when the fish were last fed against the rule: not this figure)
        for text in ('>bFCR<', '>eFCR<', '>Last fed</th>', '<dt>Last fed</dt>', '>Yesterday<', '>Fed<', 'Recent feedings'):
            self.assertNotContains(page, text)
        self.assertContains(page, '>Fish<')                     # the stock figures stay
        self.as_role('view_stockoperation', 'view_feedingrecord')
        page = self.client.get(url, {'unit': self.t1.pk})
        for text in ('>bFCR<', '>eFCR<', '>Last fed</th>', '<dt>Last fed</dt>', '>Fed<', '>Yesterday<'):
            self.assertContains(page, text)
        self.assertIsNotNone(page.context['rows'][0]['feeding'])

    def test_unit_figures_is_empty_without_the_right_and_the_read_with_it(self):
        stock = stock_read.stock_of([self.t1])
        reader = get_user_model().objects.create_user('reader', 'reader@example.com')
        reader.groups.add(role('Reader', 'view_feedingrecord'))
        blind = get_user_model().objects.create_user('blind', 'blind@example.com')
        blind.groups.add(role('Blind', 'view_stockoperation'))
        self.assertEqual(feeding_views.unit_figures(blind, stock), {})
        self.assertEqual(feeding_views.unit_figures(reader, stock, details=[self.t1]).keys(),
                         read.figures(stock, details=[self.t1]).keys())

    def test_the_menu_and_the_role_matrix_place_it_under_operations(self):
        self.assertEqual(str(navigation.place('farm.view_feedingrecord').path), 'Production · Operations · Feeding')
        area = next(area for area in access.areas() if area.model == 'farm.FeedingRecord')
        self.assertEqual((str(area.label), area.actions), ('Feeding records', ('view', 'add', 'delete')))
        self.assertContains(self.client.get(reverse('farm:feeding_records')), 'aria-current="page"')


class DeletePlanTests(FeedingTestCase):
    def test_a_feed_or_feeder_with_feedings_stays_and_an_empty_unit_goes_with_its_history_kept(self):
        feeder = self.feeder()
        feeding = self.record(feeder=feeder)
        self.assertContains(self.client.get(reverse('farm:feed_delete', args=[self.feed.pk])),
                            '1 feeding record still belongs to it.')
        self.client.post(reverse('farm:feed_delete', args=[self.feed.pk]))
        self.client.post(reverse('farm:equipment_delete', args=[feeder.pk]))
        self.assertTrue(Feed.objects.filter(pk=self.feed.pk).exists())
        self.assertTrue(Equipment.objects.filter(pk=feeder.pk).exists())
        # Emptied, the unit can be deleted, as with its stock history (owner decision Q-F3); its feedings stay.
        self.mortality(self.batch, 10000, days_ago=0)
        self.client.post(reverse('farm:tank_delete', args=[self.t1.pk]))
        self.assertTrue(Tank.all_objects.get(pk=self.t1.pk).is_deleted)
        self.assertTrue(FeedingRecord.objects.filter(pk=feeding.pk).exists())
        # A voided feeding does not hold its feed back.
        services.void_feeding(self.user, feeding, 'Never fed')
        self.client.post(reverse('farm:feed_delete', args=[self.feed.pk]))
        self.assertTrue(Feed.all_objects.get(pk=self.feed.pk).is_deleted)


class ConstraintTests(FeedingTestCase):
    @withdrawal_gate.opened('test fixture: withdrawal inputs written straight in the database')
    def test_the_checks(self):
        good = {'unit': self.t1, 'date': self.today, 'feed': self.feed, 'amount_kg': Decimal(1)}
        for fields in ({'amount_kg': 0}, {'amount_kg': Decimal('-1')}, {'meals': 0}, {'meals': 49},
                       {'is_deleted': True}, {'void_reason': 'not voided'}):
            with self.subTest(fields=fields), self.assertRaises(IntegrityError), transaction.atomic():
                FeedingRecord.objects.create(**{**good, **fields})
        FeedingRecord.objects.create(**good, meals=48)


class IntegrationTests(FeedingTestCase):
    def test_the_database_viewer_shows_the_table_with_its_checks(self):
        tables = {table.name: table for _, tables in database.sections() for table in tables}
        self.assertTrue(tables['feeding_records'].description.startswith('Feed given to one unit on one day'))
        names = {constraint.name for constraint in tables['feeding_records'].structure().constraints}
        self.assertTrue({'chk_feeding_records_amount', 'chk_feeding_records_meals',
                         'chk_feeding_records_void_reason'} <= names)

    def test_the_pages_speak_each_language(self):
        self.record()
        for language, words in {'tr': ('Yemleme kayıtları', 'Verilen yem'), 'nb': ('Fôringer', 'Fôr gitt')}.items():
            Profile.objects.update_or_create(user=self.user, defaults={'language': language})
            response = self.client.get(reverse('farm:feeding_records'))
            for word in words:
                self.assertContains(response, word, msg_prefix=language)

    def test_a_refusal_in_the_service_is_a_validation_error(self):
        with self.assertRaises(ValidationError):
            self.record(kilos='0')

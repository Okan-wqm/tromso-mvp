"""Fish health: the medicine withdrawal worked out on read (days, degree-days with known temperatures, a missing
day counted as 0 °C, a running course, a void, the fish followed into another unit, medicated feed), the
registry the harvest side reads, the statutory sea-lice limits, the write paths, and every page and dialog
(medicines, treatments, health events, sea-lice counts, Production units) checked against the stored rows."""
import io
import uuid
from datetime import datetime, time
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase
from django.urls import reverse

from core import access, database, navigation
from core.models import AuditLog
from core.softdelete import plan_delete

from ..handling import check as handling_check, withdrawal as registry
from ..health import diseases, lice, services, withdrawal
from ..health.read import LiceWeek, lice_weeks
from ..models import (
    Feed, HandlingAcknowledgement, HandlingRule, HealthEvent, LiceCount, Medicine, Site, StockOperation, Supplier,
    System, Tank, Treatment, WaterMeasurement,
)
from ..models.site import zone_of
from ..stock import integrity, services as stock_services
from ..feeding import services as feeding_services
from .helpers import make_facility, point_of, role
from .test_stock import StockTestCase, make_unit


def setUpModule():
    call_command('compile_catalogs', verbosity=0)    # the language tests read the built catalogs


HEALTH_KEEPER = ('view_medicine', 'add_medicine', 'change_medicine', 'delete_medicine',
                 'view_treatment', 'add_treatment', 'change_treatment', 'delete_treatment',
                 'view_healthevent', 'add_healthevent', 'change_healthevent', 'delete_healthevent',
                 'view_licecount', 'add_licecount', 'delete_licecount', 'view_supplier')


class HealthTestCase(StockTestCase):
    def setUp(self):
        super().setUp()
        self.user.groups.add(role('Health keeper', *HEALTH_KEEPER))
        self.batch = self.stock()                  # 2,000 fish of 125 g in T-01, stocked 10 days ago
        self.vet = Supplier.objects.create(name='Havet Fiskehelse', code='HFH', supplies=['veterinary', 'laboratory'])
        self.pharma = Supplier.objects.create(name='Pharmaq AS', code='PHQ', supplies=['medicines'])

    def medicine(self, name='Salmosan vet.', degree_days=None, days=None, administration='bath', kind='lice',
                 **fields):
        values = {'active_substance': 'azamethiphos', 'lice_report_code': 'AZAMETHIPHOS' if kind == 'lice' else '',
                  **fields}
        return Medicine.objects.create(name=name, kind=kind, administration=administration,
                                       withdrawal_degree_days=degree_days, withdrawal_days=days, **values)

    def treat(self, medicine, start_ago, end_ago, units=None, reason='sea_lice', **fields):
        """A course from `start_ago` to `end_ago` days back (negative: ahead), through the service."""
        method = fields.pop('method', medicine.administration if medicine else 'thermal')
        return services.record_treatment(self.user, units=units or [self.t1], method=method, reason=reason,
                                         start_date=self.day(start_ago), end_date=self.day(end_ago), medicine=medicine,
                                         **fields)

    def temperature(self, point, days_ago, value):
        """A water sample of `value` °C at noon, `days_ago` days back, on the point's site clock."""
        site = point.site if isinstance(point, System) else point.production_department.site
        moment = datetime.combine(self.day(days_ago), time(12), tzinfo=zone_of(site))
        return WaterMeasurement.objects.create(point=point_of(point), measured_at=moment, source='manual',
                                               temperature_c=Decimal(value), created_by=self.user)

    def held(self, unit=None, day=None):
        """The withdrawals that hold the fish of the unit (default T-01) on `day` (default today)."""
        return withdrawal.of_units([unit or self.t1], day).get((unit or self.t1).pk, [])


# ---- the withdrawal, with worked numbers ----------------------------------------------------------------
class WithdrawalTests(HealthTestCase):
    def test_days_count_from_the_day_after_the_last_treatment_day(self):
        # Last day 3 days ago, 7 days: days 1–7 are the 7 days after it, so the fish may go on day 8.
        self.treat(self.medicine(days=7), 5, 3)
        [held] = self.held()
        self.assertEqual((held.until, held.last_day, held.estimated), (self.day(-5), self.day(-4), False))
        self.assertEqual(self.held(day=self.day(-4))[0].until, self.day(-5))    # still held on its last day
        self.assertEqual(self.held(day=self.day(-5)), [])                         # free on the first day

    def test_the_clock_starts_at_the_last_treatment_day_not_at_the_click(self):
        # Recorded today, given 10 to 8 days ago, 7 days: ended yesterday (the source said 7 days from now, HLT-02).
        self.treat(self.medicine(days=7), 10, 8)
        self.assertEqual(self.held(), [])
        self.assertEqual(self.held(day=self.day(1))[0].until, self.today)

    def test_degree_days_add_up_the_measured_daily_means(self):
        # 40 degree-days after a last day 6 days ago, 8 °C a day for 5 days: reached yesterday, free today.
        self.treat(self.medicine(degree_days=40), 6, 6)
        for days_ago in range(1, 6):
            self.temperature(self.t1, days_ago, '8')
        self.assertEqual(self.held(), [])
        [held] = self.held(day=self.day(1))
        self.assertEqual((held.until, held.estimated, held.days_without_temperature), (self.today, False, 0))

    def test_a_daily_mean_is_the_mean_of_the_days_samples(self):
        self.treat(self.medicine(degree_days=20), 3, 3)
        self.temperature(self.t1, 2, '6')
        self.temperature(self.t1, 2, '14')      # the same day: a mean of 10
        self.temperature(self.t1, 1, '10')
        self.assertEqual(self.held(day=self.day(1))[0].until, self.today)    # 10 + 10 = 20 by yesterday

    def test_the_rest_is_projected_at_the_mean_of_the_last_measured_days(self):
        # 50 degree-days, 8 °C for 5 days (40), today not measured yet: 10 to go at 8 °C a day is 2 days,
        # today and tomorrow, so about the day after tomorrow.
        self.treat(self.medicine(degree_days=50), 6, 6)
        for days_ago in range(1, 6):
            self.temperature(self.t1, days_ago, '8')
        [held] = self.held()
        self.assertEqual((held.until, held.estimated, held.remaining_degree_days), (self.day(-2), True, Decimal(10)))

    def test_a_day_without_a_temperature_counts_as_zero_and_is_said(self):
        # 45 degree-days; 10 °C on four of the five days since the last day, the fourth day back not measured:
        # 40 by yesterday, 5 to go, about tomorrow. Had the missing day been filled in with 10 °C the sum
        # would have been 50 by yesterday and the fish free today.
        self.treat(self.medicine(degree_days=45), 6, 6)
        for days_ago in (5, 3, 2, 1):
            self.temperature(self.t1, days_ago, '10')
        [held] = self.held()
        self.assertEqual((held.until, held.estimated, held.days_without_temperature), (self.day(-1), True, 1))
        self.assertIn('1 day without a water temperature is counted as 0 °C.', withdrawal.describe(held))

    def test_without_any_temperature_the_end_is_unknown(self):
        self.treat(self.medicine(degree_days=50), 6, 6)
        [held] = self.held()
        self.assertEqual((held.until, held.estimated, held.days_without_temperature), (None, True, 5))
        self.assertTrue(held.holds_on(self.day(-400)))
        self.assertIn('record the water temperature', withdrawal.describe(held))

    def test_the_later_of_days_and_degree_days_wins(self):
        for days_ago in range(1, 6):
            self.temperature(self.t1, days_ago, '8')
        both = self.medicine(degree_days=50, days=10)         # degree-days: about today+2; days: today+5
        self.treat(both, 6, 6)
        [held] = self.held()
        self.assertEqual((held.until, held.estimated), (self.day(-5), False))
        services.void_treatment(self.user, held.treatment, 'Recorded with the wrong medicine')
        later = self.medicine(name='Later by degree-days', degree_days=50, days=1)
        self.treat(later, 6, 6)
        [held] = self.held()
        self.assertEqual((held.until, held.estimated), (self.day(-2), True))

    def test_a_running_course_counts_from_its_planned_last_day(self):
        treatment = self.treat(self.medicine(days=7), 1, -3)          # yesterday to 3 days ahead
        self.assertEqual(self.held()[0].until, self.day(-11))
        services.change_last_day(self.user, treatment, self.day(-1))  # stopped earlier: tomorrow is its last day
        self.assertEqual(self.held()[0].until, self.day(-9))

    def test_a_running_course_in_degree_days_is_projected_from_its_last_day(self):
        for days_ago in range(1, 8):
            self.temperature(self.t1, days_ago, '10')
        self.treat(self.medicine(degree_days=50), 1, -3)
        [held] = self.held()
        self.assertEqual((held.until, held.estimated), (self.day(-9), True))    # 5 days at 10 °C after its last

    def test_voiding_the_treatment_lifts_its_withdrawal(self):
        treatment = self.treat(self.medicine(days=30), 2, 2)
        self.assertTrue(self.held())
        services.void_treatment(self.user, treatment, 'Recorded on the wrong site')
        self.assertEqual(self.held(), [])
        self.assertEqual(registry.blocks(self.t1, self.today), [])

    def test_the_withdrawal_follows_the_batch_into_another_unit(self):
        # Treated in T-01 4 days ago, 30 degree-days; all moved to T-02 2 days ago. T-01 12 °C, T-02 6 °C: the
        # day of the move counts the lower; after it, T-02's water. 12 + 6 + 6 = 24 by yesterday, 6 to go at
        # the mean 8 °C (12, 6, 6), about tomorrow. With T-01's water alone it would have been 36: free today.
        self.treat(self.medicine(degree_days=30), 4, 4)
        moving = handling_check.assess('transport', self.t1, self.day(2), self.batch)
        self.assertEqual([warning.warning for warning in moving.warnings], ['withdrawal'])
        stock_services.record_transfer(self.user, source=self.t1, batch=self.batch, day=self.day(2),
                                       legs=[(self.t2, 2000)], reason='density', handling_ack=moving.fingerprint)
        for days_ago, unit, value in ((3, self.t1, '12'), (2, self.t1, '12'), (2, self.t2, '6'), (1, self.t1, '12'),
                                      (1, self.t2, '6')):
            self.temperature(unit, days_ago, value)
        self.assertEqual(self.held(self.t1), [])
        [held] = self.held(self.t2)
        self.assertEqual((held.batch_id, held.until, held.estimated), (self.batch.pk, self.day(-1), True))
        [block] = registry.blocks(self.t2, self.today)
        self.assertEqual((block.batch, block.until, block.approximate, block.source), (self.batch, self.day(-1), True,
                                                                                        held.treatment))
        # A new batch in the emptied T-01 was never treated.
        self.t1.refresh_from_db()
        self.stock(self.t1, count=500, days_ago=1)
        self.assertEqual(self.held(self.t1), [])

    def test_a_unit_without_its_own_sample_takes_its_loops(self):
        loop = System.objects.create(name='RAS 1', code='R1', site=self.bergen, production_department=self.hall)
        Tank.objects.filter(pk=self.t1.pk).update(system=loop)
        self.treat(self.medicine(degree_days=20), 3, 3)
        self.temperature(loop, 2, '10')
        self.temperature(self.t1, 1, '10')
        self.temperature(loop, 1, '2')           # the unit's own value wins
        self.assertEqual(self.held(day=self.day(1))[0].until, self.today)

    def test_only_the_batches_in_the_treated_units_on_the_treatment_days_are_held(self):
        other = self.stock(self.t2, count=100, days_ago=5)
        self.treat(self.medicine(days=20), 3, 3)
        self.assertEqual({held.batch_id for held in self.held()}, {self.batch.pk})
        self.assertEqual(self.held(self.t2), [])
        self.assertNotEqual(other.pk, self.batch.pk)

    def test_medicated_feed_without_an_in_feed_treatment_has_an_unknown_end(self):
        feed = Feed.objects.create(name='Medisinfôr', code='MED-1', feed_type='medicated')
        record = feeding_services.record_feeding(self.user, unit=self.t1, day=self.day(2), feed=feed,
                                                 amount_kg=Decimal('2'))
        [held] = self.held()
        self.assertEqual((held.until, held.feeding, held.treatment), (None, record, None))
        self.assertIn('no in-feed treatment covers that day', withdrawal.describe(held))
        # Recorded as an in-feed treatment that covers the day: its own withdrawal replaces the unknown end.
        in_feed = self.medicine(name='Slice vet.', kind='lice', administration='in_feed', days=14,
                                active_substance='emamectin benzoate', lice_report_code='EMAMECTIN_BENZOAT')
        self.treat(in_feed, 3, 2)
        [held] = self.held()
        self.assertEqual((held.until, held.feeding), (self.day(-13), None))

    def test_the_feeding_dialog_says_when_medicated_feed_has_no_treatment(self):
        self.user.groups.add(role('Feeder', 'add_feedingrecord', 'view_feedingrecord'))
        feed = Feed.objects.create(name='Medisinfôr', code='MED-1', feed_type='medicated')
        url = reverse('farm:feeding_record', args=[self.t1.pk])
        data = {'token': str(uuid.uuid4()), 'date': self.day(1).isoformat(), 'feed': str(feed.pk), 'amount_kg': '2',
                'meals': '', 'time': '', 'feeder': '', 'notes': ''}
        page = self.client.post(url, data, follow=True)
        self.assertContains(page, 'No in-feed treatment covers this day')
        in_feed = self.medicine(name='Slice vet.', administration='in_feed', days=14,
                                active_substance='emamectin benzoate', lice_report_code='EMAMECTIN_BENZOAT')
        self.treat(in_feed, 2, 0)
        page = self.client.post(url, {**data, 'token': str(uuid.uuid4())}, follow=True)
        self.assertNotContains(page, 'No in-feed treatment covers this day')

    def test_a_treatment_without_a_medicine_holds_nothing(self):
        self.treat(None, 2, 2, method='thermal', notes='Thermolicer')
        self.assertEqual(self.held(), [])

    def test_zero_means_no_withdrawal(self):
        self.treat(self.medicine(name='Alpha Ject', kind='vaccine', administration='injection', days=0), 1, 1,
                   reason='vaccination')
        self.assertEqual(self.held(), [])
        self.assertEqual(self.held(day=self.day(1))[0].until, self.today)


class RegistryTests(SimpleTestCase):
    def test_without_a_provider_the_withdrawal_is_not_checked(self):
        kept = list(registry._providers)
        registry._providers.clear()
        try:
            self.assertIsNone(registry.blocks(None, None))
        finally:
            registry._providers.extend(kept)

    def test_the_health_records_are_registered_once(self):
        self.assertEqual(registry._providers.count(withdrawal.provider), 1)
        registry.register(withdrawal.provider)
        self.assertEqual(registry._providers.count(withdrawal.provider), 1)


# ---- the statutory lice limits --------------------------------------------------------------------------
class LiceLimitTests(SimpleTestCase):
    def test_the_limits_of_lakselusforskriften_section_8(self):
        cases = [(lice.SOUTH, 15, '0.5'), (lice.SOUTH, 16, '0.2'), (lice.SOUTH, 21, '0.2'), (lice.SOUTH, 22, '0.5'),
                 (lice.NORTH, 20, '0.5'), (lice.NORTH, 21, '0.2'), (lice.NORTH, 26, '0.2'), (lice.NORTH, 27, '0.5'),
                 ('', 18, '0.2'), ('', 24, '0.2'), ('', 30, '0.5')]
        for area, week, expected in cases:
            with self.subTest(area=area, week=week):
                self.assertEqual(lice.limit(area, week), Decimal(expected))

    def test_at_the_limit_is_over_it(self):
        self.assertTrue(lice.over(Decimal('0.5'), lice.SOUTH, 30))     # "færre enn 0,5"
        self.assertFalse(lice.over(Decimal('0.49'), lice.SOUTH, 30))

    def test_the_sample_of_vedlegg_1(self):
        self.assertEqual([lice.minimum_fish(lice.SOUTH, week) for week in (13, 14, 21, 22)], [10, 20, 20, 10])
        self.assertEqual([lice.minimum_fish(lice.NORTH, week) for week in (18, 19, 26, 27)], [10, 20, 20, 10])
        self.assertEqual(lice.minimum_fish('', 24), 20)

    def test_the_site_averages_the_cages_averages(self):
        # Vedlegg 1 point 6: cage A 6 adult females on 20 fish (0.30), cage B 1 on 10 (0.10): the site 0.20,
        # every cage weighing the same. The source pooled the fish: 7 / 30 = 0.233 (HLT-22).
        site = Site(name='Sea', code='SEA', lice_area=lice.SOUTH)
        week = LiceWeek(site, 2026, 18, counts=[
            LiceCount(fish_counted=20, adult_females=6, mobile=10, attached=4),
            LiceCount(fish_counted=10, adult_females=1, mobile=2, attached=0)])
        self.assertEqual((week.adult_females, week.mobile, week.attached), (Decimal('0.2'), Decimal('0.35'),
                                                                            Decimal('0.1')))
        self.assertEqual(week.limit, Decimal('0.2'))
        self.assertTrue(week.over_limit)                               # 0.20 is not below 0.2
        self.assertFalse(LiceWeek(site, 2026, 30, counts=week.counts).over_limit)
        self.assertEqual([count.fish_counted for count in week.small_samples], [10])   # 20 in week 18


# ---- the write paths ----------------------------------------------------------------------------------
class TreatmentServiceTests(HealthTestCase):
    def refused_treatment(self, medicine=None, **fields):
        values = {'units': [self.t1], 'method': medicine.administration if medicine else 'thermal',
                  'reason': 'sea_lice', 'start_date': self.day(1), 'end_date': self.day(1), 'medicine': medicine,
                  **fields}
        return self.refused(services.record_treatment, self.user, **values)

    def test_a_treatment_is_stored_with_every_field_and_logged(self):
        event = HealthEvent.objects.create(site=self.bergen, date=self.day(3), kind='observation')
        medicine = self.medicine(days=7, degree_days=100)
        treatment = services.record_treatment(
            self.user, units=[self.t1], method='bath', reason='sea_lice', start_date=self.day(2),
            end_date=self.day(1), medicine=medicine, dose_value=Decimal('0.2'), dose_unit='mg_l',
            amount_value=Decimal('1.5'), amount_unit='KILO', bath_minutes=60, prescribed_by='Dr. Hansen',
            prescription_ref='RX-77', vet=self.vet, health_event=event, notes='Calm sea', token=uuid.uuid4())
        treatment.refresh_from_db()
        self.assertEqual(
            (list(treatment.units.all()), treatment.method, treatment.medicine, treatment.reason, treatment.start_date,
             treatment.end_date, treatment.dose_value, treatment.dose_unit, treatment.amount_value,
             treatment.amount_unit, treatment.bath_minutes, treatment.prescribed_by, treatment.prescription_ref,
             treatment.vet, treatment.health_event, treatment.notes, treatment.created_by),
            ([self.t1], 'bath', medicine, 'sea_lice', self.day(2), self.day(1), Decimal('0.200'), 'mg_l',
             Decimal('1.500'), 'KILO', 60, 'Dr. Hansen', 'RX-77', self.vet, event, 'Calm sea', self.user))
        row = AuditLog.objects.get(entity_type='treatment', action='create')
        self.assertEqual(row.entity_label, f'Treatment · T-01 · Salmosan vet. · {self.day(2)}–{self.day(1)}')
        self.assertEqual(row.changes['Units'], [None, str(self.t1)])
        self.assertEqual(row.changes['Medicine'], [None, 'Salmosan vet.'])

    def test_the_rules_of_a_treatment(self):
        bath = self.medicine(days=7)
        vaccine = self.medicine(name='Alpha Ject', kind='vaccine', administration='injection', days=0)
        inactive = self.medicine(name='Old', days=1, status='inactive')
        cases = [
            ({'medicine': None, 'method': 'bath'}, 'medicine'),
            ({'medicine': bath, 'method': 'thermal'}, 'medicine'),
            ({'medicine': bath, 'method': 'in_feed'}, 'method'),
            ({'medicine': inactive}, 'medicine'),
            ({'medicine': vaccine, 'reason': 'sea_lice'}, 'reason'),
            ({'medicine': bath, 'reason': 'vaccination'}, 'reason'),
            ({'medicine': None, 'method': 'thermal', 'reason': 'vaccination'}, 'reason'),
            ({'medicine': None, 'method': 'other'}, 'notes'),
            ({'medicine': bath, 'reason': 'other'}, 'notes'),
            ({'medicine': None, 'method': 'mechanical', 'bath_minutes': 20}, 'bath_minutes'),
            ({'medicine': bath, 'end_date': self.day(2)}, 'end_date'),
            ({'medicine': bath, 'end_date': self.day(-29)}, 'end_date'),
            ({'medicine': bath, 'start_date': self.day(-1), 'end_date': self.day(-1)}, 'date'),
            ({'medicine': bath, 'start_date': self.day(40), 'end_date': self.day(39)}, 'date'),
            ({'medicine': bath, 'units': []}, 'units'),
            ({'medicine': bath, 'units': [self.t1, self.p1]}, 'units'),
            ({'medicine': bath, 'units': [self.t2]}, 'units'),             # no fish in T-02
            ({'medicine': bath, 'dose_value': Decimal('1')}, 'dose_unit'),
            ({'medicine': bath, 'amount_unit': 'KILO'}, 'amount_value'),
        ]
        for fields, field in cases:
            with self.subTest(fields=fields):
                medicine = fields.pop('medicine')
                if 'method' not in fields and medicine is not None:
                    fields['method'] = medicine.administration
                self.assertIn(field, self.refused_treatment(medicine, **fields))
        self.assertFalse(Treatment.all_objects.exists())

    def test_a_health_event_of_another_site_is_refused(self):
        event = HealthEvent.objects.create(site=self.tromso, date=self.day(3), kind='observation')
        self.assertIn('health_event', self.refused_treatment(self.medicine(days=1), health_event=event))

    def test_a_form_sent_twice_records_once(self):
        token = uuid.uuid4()
        medicine = self.medicine(days=1)
        self.treat(medicine, 1, 1, token=token)
        with self.assertRaises(stock_services.AlreadyRecorded):
            self.treat(medicine, 1, 1, token=token)
        self.assertEqual(Treatment.objects.count(), 1)

    def test_the_last_day_is_changed_and_logged(self):
        treatment = self.treat(self.medicine(days=7), 2, 2)
        services.change_last_day(self.user, treatment, self.day(-2))
        treatment.refresh_from_db()
        self.assertEqual((treatment.end_date, treatment.version), (self.day(-2), 2))
        row = AuditLog.objects.get(entity_type='treatment', action='update')
        self.assertEqual(row.changes, {'Last day': [str(self.day(2)), str(self.day(-2))]})
        self.assertIn('end_date', self.refused(services.change_last_day, self.user, treatment, self.day(3)))
        self.assertIn('end_date', self.refused(services.change_last_day, self.user, treatment, self.day(-40)))
        services.void_treatment(self.user, treatment, 'Wrong unit')
        self.assertTrue(self.refused(services.change_last_day, self.user, treatment, self.day(1)))

    def test_a_void_needs_its_reason_and_is_logged(self):
        treatment = self.treat(self.medicine(days=7), 2, 2)
        self.assertIn('reason', self.refused(services.void_treatment, self.user, treatment, '  '))
        services.void_treatment(self.user, treatment, 'Recorded twice')
        treatment = Treatment.all_objects.get(pk=treatment.pk)
        self.assertEqual((treatment.is_deleted, treatment.void_reason, treatment.deleted_by),
                         (True, 'Recorded twice', self.user))
        row = AuditLog.objects.get(entity_type='treatment', action='void')
        self.assertEqual(row.changes, {'Reason for voiding': [None, 'Recorded twice']})
        self.assertTrue(self.refused(services.void_treatment, self.user, treatment, 'Again'))

    def test_the_database_holds_the_rules_too(self):
        medicine = self.medicine(days=1)
        broken = [
            dict(method='bath', medicine=None),
            dict(method='thermal', medicine=medicine),
            dict(method='bath', medicine=medicine, start_date=self.day(1), end_date=self.day(2)),
            dict(method='bath', medicine=medicine, dose_value=Decimal(1)),
            dict(method='bath', medicine=medicine, amount_unit='GRAM'),
            dict(method='bath', medicine=medicine, is_deleted=True),
        ]
        for fields in broken:
            values = {'reason': 'sea_lice', 'start_date': self.day(1), 'end_date': self.day(1), **fields}
            with self.subTest(fields=fields), self.assertRaises(IntegrityError), transaction.atomic():
                Treatment.objects.create(**values)

    def test_the_stock_refuses_to_leave_a_treatment_without_fish(self):
        self.treat(self.medicine(days=7), 3, 3)
        self.assertEqual(registry.blocks(self.t1, self.day(5)), [])        # before the treatment: not held
        refused = self.refused(stock_services.record_harvest, self.user, unit=self.t1, batch=self.batch,
                               day=self.day(5), count=2000, measured_weight_kg=Decimal('250'),
                               facility=make_facility(), everything=True)
        self.assertEqual(refused['__all__'],
                         [f'The treatment of {stock_services.shown_date(self.day(3))} in T-01 would have no fish: '
                          'void it first.'])
        self.assertEqual(integrity.problems(), [])

    def test_check_withdrawal_lists_the_fish_held(self):
        self.treat(self.medicine(days=7), 3, 3)
        out = io.StringIO()
        call_command('check_withdrawal', stdout=out)
        self.assertIn(f'T-01 · {self.batch.code}: until {self.day(-5).isoformat()}. Salmosan vet., bath',
                      out.getvalue())
        self.assertIn('1 of 1 units with fish are under a medicine withdrawal.', out.getvalue())

    def test_check_stock_finds_a_treatment_without_fish(self):
        treatment = Treatment.objects.create(method='thermal', reason='sea_lice', start_date=self.day(2),
                                             end_date=self.day(2))
        treatment.units.set([self.t2])
        self.assertEqual(integrity.problems(),
                         [f'Treatment {treatment.pk} of {self.day(2)} in unit T-02: no fish in the unit at the start '
                          'or the end of that day.'])


class LiceCountServiceTests(HealthTestCase):
    def test_a_count_is_stored_and_one_a_day_and_unit(self):
        count = services.record_lice_count(self.user, unit=self.t1, day=self.day(1), fish_counted=20,
                                           adult_females=3, mobile=8, attached=5, notes='Calm')
        count.refresh_from_db()
        self.assertEqual((count.unit, count.date, count.fish_counted, count.adult_females, count.mobile,
                          count.attached, count.notes, count.created_by),
                         (self.t1, self.day(1), 20, 3, 8, 5, 'Calm', self.user))
        self.assertEqual(count.per_fish('adult_females'), Decimal('0.15'))
        self.assertIn('date', self.refused(services.record_lice_count, self.user, unit=self.t1, day=self.day(1),
                                           fish_counted=10, adult_females=0, mobile=0, attached=0))
        services.void_lice_count(self.user, count, 'Wrong cage')
        services.record_lice_count(self.user, unit=self.t1, day=self.day(1), fish_counted=10, adult_females=0,
                                   mobile=0, attached=0)
        self.assertEqual(LiceCount.all_objects.count(), 2)
        self.assertEqual(AuditLog.objects.filter(entity_type='sea-lice count').count(), 3)

    def test_a_count_needs_fish_and_a_date_in_the_window(self):
        self.assertIn('date', self.refused(services.record_lice_count, self.user, unit=self.t2, day=self.day(1),
                                           fish_counted=10, adult_females=0, mobile=0, attached=0))
        self.assertIn('date', self.refused(services.record_lice_count, self.user, unit=self.t1, day=self.day(-1),
                                           fish_counted=10, adult_females=0, mobile=0, attached=0))
        with self.assertRaises(ValidationError):
            services.record_lice_count(self.user, unit=self.t1, day=self.day(1), fish_counted=0, adult_females=0,
                                       mobile=0, attached=0)

    def test_the_weeks_of_the_stored_counts(self):
        tromso_cage = make_unit('M-01', self.sea, status=Tank.Status.PREPARING)
        self.stock(tromso_cage, count=1000, days_ago=8)
        for unit, fish, females in ((self.t1, 20, 6), (tromso_cage, 10, 1)):
            services.record_lice_count(self.user, unit=unit, day=self.day(1), fish_counted=fish,
                                       adult_females=females, mobile=0, attached=0)
        weeks = lice_weeks(LiceCount.objects.all())
        self.assertEqual({(week.site, len(week.counts)) for week in weeks}, {(self.bergen, 1), (self.tromso, 1)})


class DiseaseCatalogueTests(SimpleTestCase):
    def test_the_listed_diseases_are_notified_but_sea_lice(self):
        self.assertEqual(set(diseases.NOTIFIABLE), {
            'isa', 'vhs', 'ihn', 'ehn', 'pd', 'bkd', 'furunculosis', 'gyrodactylosis', 'flavobacteriosis',
            'francisellosis', 'vnn', 'piscirickettsiosis'})
        self.assertEqual(diseases.get('isa').listing, diseases.EU_C)      # endemic in Norway, listed (HLT-11)
        self.assertFalse(diseases.get('sea_lice').notifiable)
        self.assertEqual(len(diseases.BY_CODE), len(diseases.CATALOGUE))


# ---- the pages ----------------------------------------------------------------------------------------
def medicine_data(**overrides):
    data = {'name': 'Salmosan vet.', 'marketing_authorisation': '', 'kind': 'lice', 'administration': 'bath',
            'active_substance': 'azamethiphos', 'lice_report_code': 'AZAMETHIPHOS', 'strength_value': '',
            'strength_unit': '', 'manufacturer': '', 'status': 'active', 'withdrawal_degree_days': '',
            'withdrawal_days': '', 'notes': ''}
    data.update(overrides)
    return data


class MedicinePageTests(HealthTestCase):
    def create(self, **overrides):
        return self.client.post(reverse('farm:medicine_create'), medicine_data(**overrides))

    def edit(self, medicine, **overrides):
        overrides.setdefault('version', str(Medicine.all_objects.get(pk=medicine.pk).version))
        return self.client.post(reverse('farm:medicine_edit', args=[medicine.pk]), medicine_data(**overrides))

    def test_create_read_edit_delete(self):
        self.create(name='Salmosan vet.', marketing_authorisation='MT-12345', strength_value='500',
                    strength_unit='MILLIGRAM_PER_GRAM', manufacturer=str(self.pharma.pk), prescription_only='on',
                    status='active', withdrawal_degree_days='150', withdrawal_days='7', notes='Keep dry')
        medicine = Medicine.objects.get()
        self.assertEqual(
            (medicine.name, medicine.marketing_authorisation, medicine.kind, medicine.administration,
             medicine.active_substance, medicine.lice_report_code, medicine.strength_value, medicine.strength_unit,
             medicine.manufacturer, medicine.prescription_only, medicine.status, medicine.withdrawal_degree_days,
             medicine.withdrawal_days, medicine.notes, medicine.created_by),
            ('Salmosan vet.', 'MT-12345', 'lice', 'bath', 'azamethiphos', 'AZAMETHIPHOS', Decimal('500.000'),
             'MILLIGRAM_PER_GRAM', self.pharma, True, 'active', 150, 7, 'Keep dry', self.user))
        page = self.client.get(reverse('farm:medicine_list'))
        self.assertEqual(list(page.context['objects']), [medicine])
        self.assertContains(page, '150 degree-days or 7 days, whichever ends later')
        # Edit: every optional field cleared, the kind changed.
        self.edit(medicine, name='Aqui-S vet.', kind='anaesthetic', active_substance='isoeugenol',
                  lice_report_code='', withdrawal_degree_days='0', withdrawal_days='', status='inactive')
        medicine.refresh_from_db()
        self.assertEqual(
            (medicine.name, medicine.marketing_authorisation, medicine.kind, medicine.lice_report_code,
             medicine.strength_value, medicine.strength_unit, medicine.manufacturer, medicine.prescription_only,
             medicine.status, medicine.withdrawal_degree_days, medicine.withdrawal_days, medicine.notes,
             medicine.version),
            ('Aqui-S vet.', '', 'anaesthetic', '', None, '', None, False, 'inactive', 0, None, '', 2))
        self.client.post(reverse('farm:medicine_delete', args=[medicine.pk]))
        self.assertTrue(Medicine.all_objects.get(pk=medicine.pk).is_deleted)
        self.assertEqual(list(AuditLog.objects.filter(entity_type='medicine').values_list('action', flat=True)),
                         ['delete', 'update', 'create'])

    def test_the_rules_on_their_fields(self):
        cases = [
            ({'lice_report_code': ''}, 'lice_report_code'),
            ({'kind': 'antibacterial'}, 'lice_report_code'),
            ({}, 'withdrawal_degree_days'),
            ({'withdrawal_days': '-1'}, 'withdrawal_days'),
            ({'withdrawal_days': '1', 'strength_value': '5'}, 'strength_unit'),
            ({'withdrawal_days': '1', 'strength_unit': 'PROSENT'}, 'strength_value'),
            ({'withdrawal_days': '1', 'manufacturer': str(self.vet.pk)}, 'manufacturer'),
        ]
        for overrides, field in cases:
            with self.subTest(overrides=overrides):
                response = self.create(**overrides)
                self.assertIn(field, response.context['form'].errors)
        self.create(withdrawal_days='1')
        self.assertIn('name', self.create(name='SALMOSAN VET.', withdrawal_days='1').context['form'].errors)

    def test_a_medicine_a_treatment_used_is_not_deleted_and_its_maker_keeps_the_category(self):
        medicine = self.medicine(days=7, manufacturer=self.pharma)
        self.treat(medicine, 1, 1)
        self.assertEqual(plan_delete(medicine).blockers, ['1 treatment still belongs to it.'])
        self.assertEqual(plan_delete(self.pharma).blockers, ['1 medicine still belongs to it.'])
        self.pharma.supplies = ['feed']
        with self.assertRaises(ValidationError) as caught:
            self.pharma.full_clean()
        self.assertIn('1 medicine is made by it: keep “Medicines and vaccines” ticked.',
                      caught.exception.message_dict['supplies'])


def event_data(site, **overrides):
    data = {'site': str(site.pk), 'units': [], 'date': '', 'kind': 'observation', 'signs': [], 'diagnosis': '',
            'confirmation': '', 'authority_notified_at': '', 'examined_by': '', 'vet': '', 'lab': '',
            'lab_reference': '', 'findings': '', 'recommendations': '', 'closed_on': '', 'outcome': ''}
    data.update(overrides)
    return data


class HealthEventPageTests(HealthTestCase):
    def test_create_read_edit_void(self):
        response = self.client.post(reverse('farm:healthevent_create'), event_data(
            self.bergen, units=[str(self.t1.pk)], date=self.day(2).isoformat(), kind='vet_visit',
            signs=['reduced_appetite', 'pale_gills'], diagnosis='pd', confirmation='suspected',
            examined_by='Dr. Hansen', vet=str(self.vet.pk), lab=str(self.vet.pk), lab_reference='L-9',
            findings='Pale gills in T-01', recommendations='Sample again', closed_on='', outcome=''))
        self.assertEqual(response.status_code, 302)
        event = HealthEvent.objects.get()
        self.assertEqual(
            (event.site, list(event.units.all()), event.date, event.kind, event.signs, event.diagnosis,
             event.confirmation, event.authority_notified_at, event.examined_by, event.vet, event.lab,
             event.lab_reference, event.findings, event.recommendations, event.created_by),
            (self.bergen, [self.t1], self.day(2), 'vet_visit', ['reduced_appetite', 'pale_gills'], 'pd', 'suspected',
             None, 'Dr. Hansen', self.vet, self.vet, 'L-9', 'Pale gills in T-01', 'Sample again', self.user))
        page = self.client.get(reverse('farm:healthevent_list'))
        self.assertEqual(list(page.context['objects']), [event])
        self.assertContains(page, 'Notify Mattilsynet')
        self.assertContains(page, 'Reduced appetite, Pale gills')
        # Edit: notified, closed, then every optional field cleared.
        notified = f'{self.day(1).isoformat()}T09:30'
        self.client.post(reverse('farm:healthevent_edit', args=[event.pk]), event_data(
            self.bergen, units=[str(self.t1.pk)], date=self.day(2).isoformat(), kind='vet_visit', diagnosis='pd',
            confirmation='confirmed', authority_notified_at=notified, closed_on=self.day(1).isoformat(),
            outcome='Recovered', version='1'))
        event.refresh_from_db()
        self.assertEqual((event.confirmation, event.authority_notified_at,
                          event.closed_on, event.outcome, event.signs, event.examined_by, event.vet),
                         ('confirmed', datetime.combine(self.day(1), time(9, 30), tzinfo=zone_of(self.bergen)),
                          self.day(1), 'Recovered', [], '', None))
        self.assertNotContains(self.client.get(reverse('farm:healthevent_list')), 'Notify Mattilsynet')
        self.client.post(reverse('farm:healthevent_edit', args=[event.pk]), event_data(
            self.bergen, date=self.day(2).isoformat(), kind='observation', version='2'))
        event.refresh_from_db()
        self.assertEqual((list(event.units.all()), event.diagnosis, event.confirmation, event.authority_notified_at,
                          event.closed_on, event.outcome, event.version), ([], '', '', None, None, '', 3))
        # Void, with its reason.
        self.client.post(reverse('farm:healthevent_void', args=[event.pk]), {'reason': 'Wrong site'})
        event = HealthEvent.all_objects.get(pk=event.pk)
        self.assertEqual((event.is_deleted, event.void_reason), (True, 'Wrong site'))
        self.assertEqual(list(self.client.get(reverse('farm:healthevent_list')).context['objects']), [])
        self.assertEqual(list(self.client.get(reverse('farm:healthevent_list'), {'voided': '1'}).context['objects']),
                         [event])
        self.assertEqual(list(AuditLog.objects.filter(entity_type='health event').values_list('action', flat=True)),
                         ['void', 'update', 'update', 'create'])

    def test_the_rules_on_their_fields(self):
        cases = [
            ({'diagnosis': 'pd'}, 'confirmation'),
            ({'confirmation': 'confirmed'}, 'confirmation'),
            ({'closed_on': self.day(5).isoformat()}, 'closed_on'),
            ({'date': self.day(-1).isoformat()}, 'date'),
            ({'date': self.day(40).isoformat()}, 'date'),
            ({'units': [str(self.p1.pk)]}, 'units'),
            ({'authority_notified_at': f'{self.day(4).isoformat()}T10:00'}, 'authority_notified_at'),
            ({'vet': str(self.pharma.pk)}, 'vet'),
        ]
        for overrides, field in cases:
            with self.subTest(overrides=overrides):
                values = {'date': self.day(2).isoformat(), **overrides}
                response = self.client.post(reverse('farm:healthevent_create'), event_data(self.bergen, **values))
                self.assertIn(field, response.context['form'].errors)
        self.assertFalse(HealthEvent.all_objects.exists())

    def test_the_site_renders_the_form_again_with_its_units(self):
        response = self.client.post(reverse('farm:healthevent_create'),
                                    {**event_data(self.tromso), '_draft': 'site'})
        self.assertEqual(list(response.context['form'].fields['units'].queryset), [self.p1])

    def test_deaths_recorded_under_an_event_are_counted_and_hold_its_void(self):
        event = HealthEvent.objects.create(site=self.bergen, date=self.day(3), kind='mortality')
        response = self.client.post(reverse('farm:stock_mortality', args=[self.t1.pk]), {
            'token': str(uuid.uuid4()), 'batch': str(self.batch.pk), 'date': self.day(1).isoformat(), 'count': '40',
            'cause': 'treatment', 'measured_weight_kg': '', 'health_event': str(event.pk), 'notes': ''})
        self.assertEqual(response.status_code, 302)
        operation = StockOperation.objects.get(kind='mortality')
        self.assertEqual((operation.health_event, operation.movements.get().reason), (event, 'treatment'))
        page = self.client.get(reverse('farm:healthevent_list'))
        self.assertEqual(page.context['objects'][0].deaths, 40)
        self.assertTrue(self.refused(services.void_event, self.user, event, 'Wrong'))
        stock_services.void(self.user, operation, 'Recorded twice')
        services.void_event(self.user, event, 'Wrong')
        self.assertTrue(HealthEvent.all_objects.get(pk=event.pk).is_deleted)

    def test_a_mortality_takes_only_an_event_of_its_unit(self):
        other = HealthEvent.objects.create(site=self.tromso, date=self.day(3), kind='observation')
        later = HealthEvent.objects.create(site=self.bergen, date=self.today, kind='observation')
        self.assertIn('health_event', self.refused(stock_services.record_mortality, self.user, unit=self.t1,
                                                   batch=self.batch, day=self.day(1), count=1, cause='disease',
                                                   health_event=other))
        self.assertIn('health_event', self.refused(stock_services.record_mortality, self.user, unit=self.t1,
                                                   batch=self.batch, day=self.day(1), count=1, cause='disease',
                                                   health_event=later))
        form = self.client.get(reverse('farm:stock_mortality', args=[self.t1.pk])).context['form']
        self.assertEqual(list(form.fields['health_event'].queryset), [later])

    def test_a_deleted_site_keeps_its_events_out_of_sight(self):
        HealthEvent.objects.create(site=self.tromso, date=self.day(3), kind='observation')
        self.assertEqual(plan_delete(self.tromso).kept_groups(),
                         [{'label': 'Health events', 'count': 1, 'note': HealthEvent.kept_note}])


def treatment_data(units, **overrides):
    data = {'token': str(uuid.uuid4()), 'units': [str(unit.pk) for unit in units], 'method': '', 'medicine': '',
            'reason': 'sea_lice', 'start_date': '', 'end_date': '', 'dose_value': '', 'dose_unit': '',
            'amount_value': '', 'amount_unit': '', 'bath_minutes': '', 'prescribed_by': '', 'prescription_ref': '',
            'vet': '', 'health_event': '', 'notes': ''}
    data.update(overrides)
    return data


class TreatmentPageTests(HealthTestCase):
    def test_record_read_change_the_last_day_void(self):
        medicine = self.medicine(days=7)
        back = reverse('farm:treatments')
        response = self.client.post(f"{reverse('farm:treatment_record')}?next={back}", treatment_data(
            [self.t1], method='bath', medicine=str(medicine.pk), start_date=self.day(2).isoformat(),
            end_date=self.day(1).isoformat(), dose_value='0,2', dose_unit='mg_l', amount_value='1.5',
            amount_unit='KILO', bath_minutes='45', prescribed_by='Dr. Hansen', prescription_ref='RX-1',
            vet=str(self.vet.pk), notes='Calm'), headers={'Accept-Language': 'nb'})
        self.assertRedirects(response, back, fetch_redirect_response=False)
        treatment = Treatment.objects.get()
        self.assertEqual((list(treatment.units.all()), treatment.medicine, treatment.dose_value, treatment.dose_unit,
                          treatment.amount_value, treatment.bath_minutes, treatment.vet, treatment.notes),
                         ([self.t1], medicine, Decimal('0.200'), 'mg_l', Decimal('1.500'), 45, self.vet, 'Calm'))
        page = self.client.get(back)
        self.assertEqual([row['treatment'] for row in page.context['rows']], [treatment])
        [(batch, held)] = page.context['rows'][0]['batches']
        self.assertEqual((batch, held.until), (self.batch, self.day(-7)))     # the last day + 7 + 1
        self.assertContains(page, self.batch.code)
        # The last day, changed through its dialog.
        self.client.post(reverse('farm:treatment_last_day', args=[treatment.pk]),
                         {'end_date': self.day(-1).isoformat()})
        treatment.refresh_from_db()
        self.assertEqual(treatment.end_date, self.day(-1))
        # Voided through its dialog: struck through when asked for, and its withdrawal gone.
        self.client.post(reverse('farm:treatment_void', args=[treatment.pk]), {'reason': 'Wrong cage'})
        self.assertTrue(Treatment.all_objects.get(pk=treatment.pk).is_deleted)
        self.assertEqual(self.client.get(back).context['rows'], [])
        self.assertEqual(len(self.client.get(back, {'voided': '1'}).context['rows']), 1)
        self.assertEqual(self.held(), [])

    def test_the_service_reasons_land_on_their_fields(self):
        response = self.client.post(reverse('farm:treatment_record'), treatment_data(
            [self.t1], method='thermal', medicine=str(self.medicine(days=1).pk), start_date=self.day(1).isoformat(),
            end_date=self.day(1).isoformat()))
        self.assertEqual(response.status_code, 422)
        self.assertIn('medicine', response.context['form'].errors)
        response = self.client.post(reverse('farm:treatment_record'), treatment_data(
            [self.t1], method='thermal', start_date=self.day(-2).isoformat(), end_date=self.day(-2).isoformat()))
        self.assertIn('start_date', response.context['form'].errors)

    def test_the_drawers_unit_is_ticked_and_its_site_offered(self):
        self.stock(self.t2, count=100, days_ago=3)
        form = self.client.get(reverse('farm:treatment_record'), {'unit': self.t1.pk}).context['form']
        self.assertEqual(form.initial['units'], [self.t1.pk])
        self.assertEqual(set(form.fields['units'].queryset), {self.t1, self.t2})

    def test_the_filters(self):
        vaccine = self.medicine(name='Alpha Ject', kind='vaccine', administration='injection', days=0)
        bath = self.medicine(days=20)
        vaccination = self.treat(vaccine, 5, 5, reason='vaccination')
        lice_bath = self.treat(bath, 2, 2)
        page = lambda **query: [row['treatment'] for row in self.client.get(reverse('farm:treatments'),
                                                                             query).context['rows']]
        self.assertEqual(page(), [lice_bath, vaccination])
        self.assertEqual(page(show='vaccinations'), [vaccination])
        self.assertEqual(page(show='withdrawal'), [lice_bath])
        self.assertEqual(page(batch=str(self.batch.pk)), [lice_bath, vaccination])
        self.assertEqual(page(medicine=str(bath.pk)), [lice_bath])
        self.assertEqual(page(method='injection'), [vaccination])
        self.assertEqual(page(**{'from': self.day(3).isoformat()}), [lice_bath])


class LicePageTests(HealthTestCase):
    def test_record_read_void(self):
        back = reverse('farm:lice_counts')
        response = self.client.post(f"{reverse('farm:lice_record')}?next={back}", {
            'token': str(uuid.uuid4()), 'unit': str(self.t1.pk), 'date': self.day(1).isoformat(),
            'fish_counted': '20', 'adult_females': '14', 'mobile': '30', 'attached': '6', 'notes': 'Cage 1'})
        self.assertRedirects(response, back, fetch_redirect_response=False)
        count = LiceCount.objects.get()
        self.assertEqual((count.unit, count.date, count.fish_counted, count.adult_females, count.mobile,
                          count.attached, count.notes), (self.t1, self.day(1), 20, 14, 30, 6, 'Cage 1'))
        page = self.client.get(back)
        [week] = page.context['weeks']
        self.assertEqual((week.site, week.adult_females, week.over_limit), (self.bergen, Decimal('0.7'), True))
        self.assertContains(page, 'Over the limit')
        self.assertContains(page, 'Area not set: the stricter limit applies')
        self.client.post(reverse('farm:lice_void', args=[count.pk]), {'reason': 'Wrong cage'})
        self.assertTrue(LiceCount.all_objects.get(pk=count.pk).is_deleted)
        self.assertEqual(self.client.get(back).context['weeks'], [])

    def test_a_refused_count_says_why_on_its_field(self):
        response = self.client.post(reverse('farm:lice_record'), {
            'token': str(uuid.uuid4()), 'unit': str(self.t1.pk), 'date': self.day(-1).isoformat(),
            'fish_counted': '20', 'adult_females': '0', 'mobile': '0', 'attached': '0', 'notes': ''})
        self.assertEqual(response.status_code, 422)
        self.assertIn('date', response.context['form'].errors)

    def test_the_site_area_is_on_the_site_form(self):
        self.bergen.lice_area = 'north'
        self.bergen.full_clean()
        self.bergen.lice_area = 'west'
        with self.assertRaises(ValidationError):
            self.bergen.full_clean()


class ProductionUnitsHealthTests(HealthTestCase):
    def test_the_registry_puts_the_withdrawal_on_the_row_and_in_the_harvest_section_once(self):
        treatment = self.treat(self.medicine(days=7), 3, 3)
        page = self.client.get(reverse('farm:production_units'), {'unit': self.t1.pk})
        row = next(row for row in page.context['rows'] if row['unit'] == self.t1)
        [block] = row['withdrawal']
        self.assertEqual((block.batch, block.until, block.approximate, block.source),
                         (self.batch, self.day(-5), False, treatment))
        line = (f'Not suitable for harvest — medicine withdrawal of {self.batch.code} until '
                f'{stock_services.shown_date(self.day(-5))}.')
        self.assertContains(page, line, count=1)
        self.assertContains(page, 'Record treatment')
        self.assertContains(page, 'Record sea-lice count')
        self.assertContains(page, 'Treatments, last 90 days')
        other = next(row for row in page.context['rows'] if row['unit'] == self.t2)
        self.assertIsNone(other['withdrawal'])

    def test_the_withdrawal_shows_without_a_health_permission(self):
        self.treat(self.medicine(days=7), 3, 3)
        stock_keeper = get_user_model().objects.create_user('ola', 'ola@example.com', 'x')
        stock_keeper.groups.add(role('Units only', 'view_stockoperation'))
        self.client.force_login(stock_keeper)
        page = self.client.get(reverse('farm:production_units'), {'unit': self.t1.pk})
        self.assertContains(page, 'Not suitable for harvest')
        self.assertNotContains(page, 'Record treatment')
        self.assertNotContains(page, 'Treatments, last 90 days')

    def test_an_unknown_end_says_so(self):
        self.treat(self.medicine(degree_days=50), 2, 2)
        page = self.client.get(reverse('farm:production_units'), {'unit': self.t1.pk})
        self.assertContains(page, f'Not suitable for harvest — medicine withdrawal of {self.batch.code}, its end '
                                  'unknown.')

    def test_a_harvest_during_the_withdrawal_warns_and_keeps_what_was_shown(self):
        self.treat(self.medicine(days=7), 3, 3)
        warnings = handling_check.check('harvest', self.t1, self.today)
        self.assertEqual([(warning.warning, warning.block.until) for warning in warnings],
                         [('withdrawal', self.day(-5))])
        self.assertEqual(handling_check.check('harvest', self.t1, self.day(-5)), [])


class TreatmentHandlingTests(HealthTestCase):
    """The fast before a treatment: the shared handling check (kind treatment, the starting rule of 24 h)."""

    def fed(self, days_ago, hour):
        feed = Feed.objects.get_or_create(name='Grower 3 mm', code='GROWER-3', feed_type='grower')[0]
        return feeding_services.record_feeding(self.user, unit=self.t1, day=self.day(days_ago), feed=feed,
                                               amount_kg=Decimal('2'), time=time(hour))

    def test_too_short_a_fast_asks_and_the_answer_is_kept_on_the_treatment(self):
        self.fed(2, 18)                      # 6 h before the first day of the treatment
        bath = self.medicine(days=7)
        refused = self.refused(self.treat, bath, 1, 1)
        self.assertEqual(refused, {'handling_ack': ['Tick the box to go on despite these warnings.']})
        checked = services.handling([self.t1], self.day(1), 'bath')
        self.assertEqual([(warning.warning, warning.fasted_hours, warning.required_hours) for warning in checked.warnings],
                         [('fasting', Decimal('6.0'), 24)])
        self.assertEqual(self.refused(self.treat, bath, 1, 1, handling_ack='old')['handling_ack'],
                         ['The warnings changed since the form was shown: read them again, and tick the box to go on.'])
        treatment = self.treat(bath, 1, 1, handling_ack=checked.fingerprint)
        [row] = HandlingAcknowledgement.objects.all()
        self.assertEqual((row.treatment, row.operation, row.warning, row.fasted_hours, row.required_hours, row.kind),
                         (treatment, None, 'fasting', Decimal('6.0'), 24, 'treatment'))
        log = AuditLog.objects.get(entity_type='treatment', action='create')
        self.assertEqual(log.severity, AuditLog.Severity.CRITICAL)
        self.assertIn('Last fed', log.changes['Handling warnings acknowledged'][1])

    def test_a_fast_long_enough_or_medicated_feed_asks_nothing(self):
        self.fed(3, 6)                       # 42 h before
        treatment = self.treat(self.medicine(days=7), 1, 1)
        self.assertFalse(HandlingAcknowledgement.objects.exists())
        self.assertEqual(AuditLog.objects.get(entity_id=str(treatment.pk)).severity, AuditLog.Severity.NORMAL)
        self.fed(1, 20)
        in_feed = self.medicine(name='Slice vet.', administration='in_feed', days=14,
                                active_substance='emamectin benzoate', lice_report_code='EMAMECTIN_BENZOAT')
        self.treat(in_feed, 0, 0)            # fed the same day: the medicated feed is the feeding itself
        self.assertFalse(HandlingAcknowledgement.objects.exists())

    def test_the_dialog_shows_the_check_and_takes_its_box(self):
        self.fed(2, 18)
        bath = self.medicine(days=7)
        url = f"{reverse('farm:treatment_record')}?unit={self.t1.pk}"
        page = self.client.get(url)
        self.assertContains(page, 'Before handling')
        self.assertEqual(page.context['form']['start_date'].value(), self.today)
        self.assertContains(page, 'The treatment rule for Atlantic salmon asks for 24 h.')
        data = treatment_data([self.t1], method='bath', medicine=str(bath.pk), start_date=self.day(1).isoformat(),
                              end_date=self.day(1).isoformat())
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 422)
        self.assertIn('handling_ack', response.context['form'].errors)
        fingerprint = services.handling([self.t1], self.day(1), 'bath').fingerprint
        self.assertEqual(self.client.post(url, {**data, 'handling_ack': fingerprint}).status_code, 302)
        self.assertEqual(HandlingAcknowledgement.objects.get().treatment, Treatment.objects.get())
        self.assertContains(self.client.get(reverse('farm:treatments')), 'Handling warning acknowledged')

    def test_an_acknowledgement_belongs_to_one_record(self):
        rule = HandlingRule.objects.get(kind='treatment', species__isnull=True)
        operation = StockOperation.objects.first()
        treatment = self.treat(None, 1, 1, method='thermal', notes='Thermolicer')
        fasting = {'warning': 'fasting', 'last_fed_at': datetime(2026, 1, 1, 12, tzinfo=zone_of(self.bergen)),
                   'fasted_hours': Decimal('1'), 'required_hours': 24, 'rule': rule}
        for links in ({}, {'operation': operation, 'treatment': treatment}):
            with self.subTest(links=links), self.assertRaises(IntegrityError), transaction.atomic():
                HandlingAcknowledgement.objects.create(**links, **fasting)
        HandlingAcknowledgement.objects.create(treatment=treatment, **fasting)
        self.assertEqual(integrity.problems(), [])


class AccessTests(HealthTestCase):
    def test_the_pages_need_their_permissions(self):
        person = get_user_model().objects.create_user('nobody', 'n@example.com', 'x')
        self.client.force_login(person)
        treatment = self.treat(self.medicine(days=1), 1, 1)
        for url in (reverse('farm:treatments'), reverse('farm:treatment_record'),
                    reverse('farm:treatment_last_day', args=[treatment.pk]),
                    reverse('farm:treatment_void', args=[treatment.pk]), reverse('farm:lice_counts'),
                    reverse('farm:lice_record'), reverse('farm:healthevent_list'), reverse('farm:medicine_list')):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_the_menu_and_the_role_matrix(self):
        places = {perm: str(navigation.place(perm).path) for perm in (
            'farm.view_treatment', 'farm.view_healthevent', 'farm.view_licecount', 'farm.view_medicine')}
        self.assertEqual(places, {
            'farm.view_treatment': 'Production · Operations · Health',
            'farm.view_healthevent': 'Production · Operations · Health',
            'farm.view_licecount': 'Production · Operations · Health',
            'farm.view_medicine': 'Production · Setup · Reference data'})
        offered = {(area.model, area.actions) for area in access.areas()}
        self.assertIn(('farm.LiceCount', ('view', 'add', 'delete')), offered)
        self.assertIn(('farm.Treatment', ('view', 'add', 'change', 'delete')), offered)

    def test_the_database_viewer_describes_the_link_tables(self):
        found = {table.name: table.description for _section, tables in database.sections() for table in tables}
        self.assertEqual(found['treatment_units'], 'Which units each treatment was given in.')
        self.assertTrue({'medicines', 'treatments', 'health_events', 'lice_counts'} <= set(found))

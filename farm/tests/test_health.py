"""Fish health: the medicine withdrawal worked out on read (days, degree-days with known temperatures, a missing
day counted at the species' assumed temperature or as 0 °C, a running course, a void, the fish followed into another
unit, medicated feed, a withdrawal asked before a harvest only), the
registry the harvest side reads, the statutory sea-lice limits, the write paths, and every page and dialog
(medicines, treatments, health events, sea-lice counts, Production units) checked against the stored rows."""
import io
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.db.models import ProtectedError
from django.test import SimpleTestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import translation

from core import access, database, navigation, softdelete
from core.models import AuditLog, Profile
from core.softdelete import plan_delete
from core.testing import BAD_HOURS, FrozenClock

from ..handling import check as handling_check, withdrawal as registry
from ..handling.withdrawal import WithdrawalBlock
from ..harvest import views as harvest_views
from ..health import diseases, lice, notices, services, withdrawal
from ..health import read
from ..health.read import LiceWeek, lice_weeks
from ..models import (
    Batch, Feed, HandlingAcknowledgement, HandlingRule, HealthEvent, LiceCount, Medicine, MedicineWithdrawal,
    ProductionDepartment, Site, Species, StockOperation, Supplier, System, Tank, Treatment, WaterMeasurement,
)
from ..models.site import zone_of
from ..stock import integrity, services as stock_services
from ..stock.dates import local_today
from ..feeding import services as feeding_services
from .. import withdrawal_gate as gate
from .helpers import going_on, make_facility, make_species, point_of, role, rows_data
from .test_stock import StockTestCase, make_unit
from farm import withdrawal_gate

Status = Tank.Status


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
        """A medicine; with degree-days or days, its withdrawal for every species (its row without a species)."""
        values = {'active_substance': 'azamethiphos', 'lice_report_code': 'AZAMETHIPHOS' if kind == 'lice' else '',
                  **fields}
        medicine = Medicine.objects.create(name=name, kind=kind, administration=administration, **values)
        if degree_days is not None or days is not None:
            self.withdraw(medicine, None, degree_days=degree_days, days=days)
        return medicine

    @withdrawal_gate.opened('test fixture: withdrawal inputs written straight in the database')
    def withdraw(self, medicine, species, degree_days=None, days=None, margin=0, note=''):
        """A medicine's withdrawal row for a species (None: for every species)."""
        with gate.opened('test fixture: a withdrawal row straight in the database'):
            return MedicineWithdrawal.objects.create(medicine=medicine, species=species, degree_days=degree_days,
                                                     days=days, safety_margin_pct=margin, note=note)

    def treat(self, medicine, start_ago, end_ago, units=None, reason='sea_lice', **fields):
        """A course from `start_ago` to `end_ago` days back (negative: ahead), through the service."""
        method = fields.pop('method', medicine.administration if medicine else 'thermal')
        return services.record_treatment(self.user, units=units or [self.t1], method=method, reason=reason,
                                         start_date=self.day(start_ago), end_date=self.day(end_ago), medicine=medicine,
                                         **fields)

    @withdrawal_gate.opened('test fixture: withdrawal inputs written straight in the database')
    def temperature(self, point, days_ago, value):
        """A water sample of `value` °C at noon, `days_ago` days back, on the point's site clock."""
        site = point.site if isinstance(point, System) else point.production_department.site
        moment = datetime.combine(self.day(days_ago), time(12), tzinfo=zone_of(site))
        with gate.opened('test fixture: a water sample straight in the database'):
            return WaterMeasurement.objects.create(point=point_of(point), measured_at=moment, source='manual',
                                                   temperature_c=Decimal(value), created_by=self.user)

    def going_on(self, call, *args, **kwargs):
        """A write the withdrawal guard asks about (fish held today freed, a harvest brought inside), gone on with: as the
        person ticks the box (farm/tests/test_withdrawal_guard.py tests the question itself)."""
        return going_on(call, *args, **kwargs)

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

    def test_a_day_without_a_temperature_counts_as_zero_when_the_species_has_no_assumption_and_is_said(self):
        # 45 degree-days; 10 °C on four of the five days since the last day, the fourth day back not measured:
        # 40 by yesterday, 5 to go, about tomorrow. Had the missing day been filled in with 10 °C the sum
        # would have been 50 by yesterday and the fish free today.
        self.treat(self.medicine(degree_days=45), 6, 6)
        for days_ago in (5, 3, 2, 1):
            self.temperature(self.t1, days_ago, '10')
        [held] = self.held()
        self.assertEqual((held.until, held.estimated, held.days_without_temperature, held.assumed_temperature),
                         (self.day(-1), True, 1, None))
        self.assertIn('1 day without a measured water temperature is counted as 0 °C: set the species’ assumed '
                      'temperature in Reference data › Species.', withdrawal.describe(held))

    @withdrawal_gate.opened('test fixture: withdrawal inputs written straight in the database')
    def test_a_missing_day_counts_at_the_species_assumed_temperature_exactly_as_if_it_was_measured_there(self):
        # 55 degree-days; 10 °C on four of the five days since the last day, the fourth day back not measured.
        self.treat(self.medicine(degree_days=55), 6, 6)
        for days_ago in (5, 3, 2, 1):
            self.temperature(self.t1, days_ago, '10')
        [unset] = self.held()
        self.assertEqual((unset.until, unset.remaining_degree_days, unset.days_without_temperature),
                         (self.day(-2), Decimal(15), 1))                 # 40 by yesterday, 15 to go at 10: 2 days
        Species.objects.filter(pk=self.salmon.pk).update(withdrawal_temperature_c=Decimal('10.0'))
        [assumed] = self.held()
        self.assertEqual((assumed.until, assumed.estimated, assumed.remaining_degree_days,
                          assumed.days_without_temperature, assumed.assumed_temperature),
                         (self.day(-1), True, Decimal(5), 1, Decimal('10.0')))    # 50 by yesterday, 5 to go: 1 day
        self.assertIn('1 day without a measured water temperature is counted at the assumed 10.0 °C (the species’ '
                      'setting in Reference data).', withdrawal.describe(assumed))
        self.assertNotIn('set the species’ assumed temperature', withdrawal.describe(assumed))
        # A lower assumption is the conservative one: 4 °C for the missing day is 44 by yesterday, 11 to go.
        Species.objects.filter(pk=self.salmon.pk).update(withdrawal_temperature_c=Decimal('4.0'))
        [lower] = self.held()
        self.assertEqual((lower.until, lower.remaining_degree_days, lower.assumed_temperature),
                         (self.day(-2), Decimal(11), Decimal('4.0')))
        self.assertIn('1 day without a measured water temperature is counted at the assumed 4.0 °C',
                      withdrawal.describe(lower))
        self.temperature(self.t1, 4, '10')                               # the same day, measured at that value
        [measured] = self.held()
        self.assertEqual((measured.until, measured.estimated, measured.remaining_degree_days),
                         (assumed.until, assumed.estimated, assumed.remaining_degree_days))
        self.assertEqual((measured.days_without_temperature, measured.until), (0, self.day(-1)))

    @withdrawal_gate.opened('test fixture: withdrawal inputs written straight in the database')
    def test_a_species_assumption_of_zero_is_a_value_not_an_absence(self):
        self.treat(self.medicine(degree_days=45), 6, 6)
        for days_ago in (5, 3, 2, 1):
            self.temperature(self.t1, days_ago, '10')
        Species.objects.filter(pk=self.salmon.pk).update(withdrawal_temperature_c=Decimal('0.0'))
        [held] = self.held()
        self.assertEqual((held.until, held.assumed_temperature), (self.day(-1), Decimal('0.0')))
        self.assertIn('is counted at the assumed 0.0 °C (the species’ setting in Reference data)',
                      withdrawal.describe(held))

    @withdrawal_gate.opened('test fixture: withdrawal inputs written straight in the database')
    def test_without_any_temperature_the_end_is_unknown_unless_the_species_has_an_assumption(self):
        self.treat(self.medicine(degree_days=50), 6, 6)
        [held] = self.held()
        self.assertEqual((held.until, held.estimated, held.days_without_temperature, held.projected_at_assumed),
                         (None, True, 5, False))
        self.assertTrue(held.holds_on(self.day(-170)))
        self.assertTrue(held.holds_on(self.day(-400)))                  # no ceiling for degree-days (decision 11)
        self.assertIn('record the water temperature', withdrawal.describe(held))
        self.assertIn('5 days without a measured water temperature are counted as 0 °C: set the species’ assumed '
                      'temperature in Reference data › Species.', withdrawal.describe(held))
        # The assumption fills the five past days (40) and projects the 10 left at 8 °C a day: 2 days, about the
        # day after tomorrow.
        Species.objects.filter(pk=self.salmon.pk).update(withdrawal_temperature_c=Decimal('8.0'))
        [held] = self.held()
        self.assertEqual((held.until, held.estimated, held.days_without_temperature, held.projected_at_assumed,
                          held.remaining_degree_days), (self.day(-2), True, 5, True, Decimal(10)))
        text = withdrawal.describe(held)
        self.assertIn('Projected at the assumed 8.0 °C (the species’ setting in Reference data): no water '
                      'temperature was measured in the last 30 days.', text)
        self.assertIn('5 days without a measured water temperature are counted at the assumed 8.0 °C (the '
                      'species’ setting in Reference data).', text)
        self.assertNotIn('record the water temperature', text)
        # A measured temperature in the window is projected at, not the assumption.
        self.temperature(self.t1, 1, '10')
        [held] = self.held()
        self.assertFalse(held.projected_at_assumed)
        self.assertIn('Projected at the mean water temperature of the last days measured.', withdrawal.describe(held))
        # An assumed 0 °C cannot project an end.
        WaterMeasurement.objects.all().delete()
        Species.objects.filter(pk=self.salmon.pk).update(withdrawal_temperature_c=Decimal('0.0'))
        [held] = self.held()
        self.assertEqual((held.until, held.projected_at_assumed), (None, False))

    @withdrawal_gate.opened('test fixture: withdrawal inputs written straight in the database')
    def test_the_assumed_temperature_texts_are_in_turkish_and_norwegian(self):
        self.addCleanup(translation.activate, 'en')
        self.treat(self.medicine(degree_days=50), 6, 6)        # five past days, none measured
        words = {
            'tr': ('Ölçülmüş su sıcaklığı olmayan 5 gün 0 °C sayıldı: Referans verileri › Balık türleri altında '
                   'türün varsayılan sıcaklığını girin.',
                   'Ölçülmüş su sıcaklığı olmayan 5 gün, varsayılan 8,0 °C ile sayıldı (Referans verilerindeki türün '
                   'ayarı).',
                   'Varsayılan 8,0 °C ile öngörüldü (Referans verilerindeki türün ayarı): son 30 günde su sıcaklığı '
                   'ölçülmedi.'),
            'nb': ('5 dager uten målt vanntemperatur telles som 0 °C: legg inn artens antatte temperatur i '
                   'Referansedata › Arter.',
                   '5 dager uten målt vanntemperatur telles med den antatte 8,0 °C (artens innstilling i '
                   'Referansedata).',
                   'Anslått med den antatte 8,0 °C (artens innstilling i Referansedata): ingen vanntemperatur ble '
                   'målt de siste 30 dagene.'),
        }
        for language, (zero, assumed, projected) in words.items():
            Profile.objects.update_or_create(user=self.user, defaults={'language': language})
            Species.objects.filter(pk=self.salmon.pk).update(withdrawal_temperature_c=None)
            self.assertContains(self.client.get(reverse('farm:treatments')), zero, msg_prefix=language)
            Species.objects.filter(pk=self.salmon.pk).update(withdrawal_temperature_c=Decimal('8.0'))
            page = self.client.get(reverse('farm:treatments'))
            self.assertContains(page, assumed, msg_prefix=language)
            self.assertContains(page, projected, msg_prefix=language)
            self.assertNotContains(page, zero, msg_prefix=language)
        # The same words in the harvest section of the unit's drawer, whose warning carries the reason.
        page = self.client.get(reverse('farm:production_units'), {'unit': self.t1.pk})
        self.assertContains(page, 'Ikke egnet for høsting')
        self.assertContains(page, 'Anslått med den antatte 8,0 °C')

    def test_the_species_of_the_batches_are_read_in_one_query_whatever_their_number(self):
        other = self.stock(self.t2, count=500, species=self.trout)
        third = self.stock(make_unit('T-03', self.hall), count=500)
        self.treat(self.medicine(degree_days=50), 6, 6, units=[self.t1, self.t2])
        counts = []
        for ids in ({self.batch.pk}, {self.batch.pk, other.pk, third.pk}):
            with CaptureQueriesContext(connection) as queries:
                reader = withdrawal.Reader(ids, self.today)
                reader.withdrawals()
            counts.append(sum('FROM "batches"' in query['sql'] for query in queries.captured_queries))
            # The reader also reads the batches a course in force can have exposed (S-03: the lots, review F-3): here
            # the trout of T-02, in the course's units, whoever was asked. Still one query.
            self.assertLessEqual(ids, set(reader.batches))
            self.assertLessEqual(set(reader.batches), {self.batch.pk, other.pk, third.pk})
        self.assertEqual(counts, [1, 1])

    def test_the_later_of_days_and_degree_days_wins(self):
        for days_ago in range(1, 6):
            self.temperature(self.t1, days_ago, '8')
        both = self.medicine(degree_days=50, days=10)         # degree-days: about today+2; days: today+5
        self.treat(both, 6, 6)
        [held] = self.held()
        self.assertEqual((held.until, held.estimated), (self.day(-5), False))
        self.going_on(services.void_treatment, self.user, held.treatment, 'Recorded with the wrong medicine')
        later = self.medicine(name='Later by degree-days', degree_days=50, days=1)
        self.treat(later, 6, 6)
        [held] = self.held()
        self.assertEqual((held.until, held.estimated), (self.day(-2), True))

    # ---- the withdrawal per species (the rows of MedicineWithdrawal) ---------------------------------------
    def test_the_species_row_beats_the_row_for_every_species(self):
        # Treated 3 days ago: salmon 10 days, every other species 4 days. T-02 holds trout, treated with T-01.
        trout = self.stock(self.t2, count=500, species=self.trout)
        medicine = self.medicine(days=4)
        self.withdraw(medicine, self.salmon, days=10)
        self.treat(medicine, 3, 3, units=[self.t1, self.t2])
        by_batch = {held.batch_id: held for held in self.held() + self.held(self.t2)}
        self.assertEqual((by_batch[self.batch.pk].until, by_batch[trout.pk].until),
                         (self.day(-8), self.day(-2)))              # 3 days ago + 10 + 1, and + 4 + 1
        self.assertEqual(by_batch[self.batch.pk].rule.row.species, self.salmon)
        self.assertIsNone(by_batch[trout.pk].rule.row.species)
        self.assertEqual([each.until for each in registry.blocks(self.t1, self.today)], [self.day(-8)])

    def test_no_row_for_the_species_and_none_for_every_species_is_an_unknown_end_and_said(self):
        medicine = self.medicine()                                  # no row at all
        self.withdraw(medicine, self.trout, days=4)               # a row, but for another species
        self.treat(medicine, 3, 3)
        [held] = self.held()
        # Unknown: it holds, to the day the platform owner's setting gives (rule 8, the owner's decision 10: 180 days
        # after the course's last day, where it held without end before), and no longer.
        self.assertEqual((held.until, held.rule, held.holds_on(self.day(-170))), (None, None, True))
        self.assertFalse(held.holds_on(self.day(-400)))
        text = withdrawal.describe(held)
        self.assertIn('No withdrawal is recorded for Atlantic salmon of Salmosan vet.: add it in Reference data › '
                      'Medicines.', text)
        self.assertNotIn('record the water temperature', text)
        [block] = registry.blocks(self.t1, self.today)
        self.assertEqual((block.until, block.approximate), (None, False))
        # The harvest is warned: an unknown end is never clear.
        [warning] = handling_check.check('harvest', self.t1, self.today)
        self.assertIn(': end unknown.', warning.message())
        self.assertIn('No withdrawal is recorded for Atlantic salmon', warning.message())
        # Adding the row for every species gives it its end at once.
        self.withdraw(medicine, None, days=7)
        self.assertEqual(self.held()[0].until, self.day(-5))

    @gate.opened('test fixture: a withdrawal row read back and saved as it is')
    def test_the_safety_margin_is_added_to_both_values_and_rounded_up_and_the_label_value_is_kept(self):
        # 7 days + 20 % = 8.4, so 9 days; 30 degree-days + 20 % = 36, reached by 4 days at 10 °C: the days decide.
        medicine = self.medicine()
        row = self.withdraw(medicine, None, degree_days=30, days=7, margin=20)
        self.treat(medicine, 5, 5)
        for days_ago in range(1, 5):
            self.temperature(self.t1, days_ago, '10')
        [held] = self.held()
        self.assertEqual((held.rule.days, held.rule.degree_days), (9, Decimal(36)))
        self.assertEqual((held.until, held.estimated), (self.day(-5), False))        # by days: 5 days ago + 9 + 1
        row.refresh_from_db()
        self.assertEqual((row.days, row.degree_days, row.safety_margin_pct), (7, Decimal('30.0'), Decimal('20.0')))
        self.assertEqual(held.rule.text(), '30 degree-days + 20 % safety margin = 36 degree-days or 7 days + 20 % '
                                           'safety margin = 9 days, whichever ends later')
        self.assertIn('withdrawal 30 degree-days + 20 % safety margin = 36 degree-days or 7 days + 20 % safety '
                      'margin = 9 days, whichever ends later.', withdrawal.describe(held))
        # Without a margin the label value is used as it is, a value with a decimal too.
        row.safety_margin_pct, row.degree_days = 0, Decimal('30.5')
        row.save()
        [held] = self.held()
        self.assertEqual((held.rule.degree_days, held.rule.days), (Decimal('30.5'), 7))
        self.assertEqual(held.rule.text(), '30.5 degree-days or 7 days, whichever ends later')
        # Rounded up, never down: 35 + 10 % = 38.5, so 39.
        row.safety_margin_pct, row.degree_days = Decimal('10'), Decimal(35)
        row.save()
        self.assertEqual(self.held()[0].rule.degree_days, Decimal(39))

    def test_a_margin_on_the_degree_days_moves_the_end(self):
        # 40 degree-days at 8 °C a day is 5 days; with 25 % it is 50 and 10 are still to come after yesterday.
        medicine = self.medicine()
        self.withdraw(medicine, None, degree_days=40)
        self.treat(medicine, 6, 6)
        for days_ago in range(1, 6):
            self.temperature(self.t1, days_ago, '8')
        self.assertEqual(self.held(day=self.day(1))[0].until, self.today)             # reached by yesterday
        with gate.opened('test: a margin changed behind the services'):
            MedicineWithdrawal.objects.update(safety_margin_pct=25)
        [held] = self.held()
        self.assertEqual((held.rule.degree_days, held.estimated, held.remaining_degree_days),
                         (Decimal(50), True, Decimal(10)))

    def test_the_withdrawal_of_each_species_of_one_course_follows_its_own_row(self):
        medicine = self.medicine()
        self.withdraw(medicine, self.salmon, degree_days=50, margin=0)
        self.withdraw(medicine, self.trout, degree_days=20)
        trout = self.stock(self.t2, count=500, species=self.trout)
        self.treat(medicine, 3, 3, units=[self.t1, self.t2])
        for unit in (self.t1, self.t2):
            for days_ago in (1, 2):
                self.temperature(unit, days_ago, '10')
        salmon_held, trout_held = self.held()[0], self.held(self.t2, day=self.day(1))[0]
        self.assertEqual((salmon_held.batch_id, trout_held.batch_id), (self.batch.pk, trout.pk))
        self.assertEqual((salmon_held.rule.degree_days, trout_held.rule.degree_days), (Decimal(50), Decimal(20)))
        # 3 days ago is the last day: its 2 days after at 10 °C are 20, so the trout are free today...
        self.assertEqual((trout_held.until, trout_held.estimated), (self.today, False))
        self.assertEqual(self.held(self.t2), [])
        # ...and the salmon need 30 more: projected at 10 °C, 3 days.
        self.assertEqual((salmon_held.estimated, salmon_held.remaining_degree_days, salmon_held.until),
                         (True, Decimal(30), self.day(-3)))

    def test_the_rows_of_the_medicines_are_read_in_one_query(self):
        first, second = self.medicine(days=3), self.medicine(name='Slice vet.', days=5)
        self.treat(first, 4, 4)
        self.treat(second, 4, 4)
        with CaptureQueriesContext(connection) as queries:
            reader = withdrawal.Reader({self.batch.pk}, self.today)
            reader.withdrawals()
        self.assertEqual(sum('FROM "medicine_withdrawals"' in query['sql'] for query in queries.captured_queries), 1)
        self.assertEqual(sorted(reader.rows), sorted([first.pk, second.pk]))

    def test_there_is_one_resolution_of_the_row(self):
        medicine = self.medicine(days=3)
        self.withdraw(medicine, self.salmon, days=9)
        rows = list(medicine.withdrawals.all())
        self.assertEqual(withdrawal.row_for(rows, self.salmon.pk).days, 9)
        self.assertEqual(withdrawal.row_for(rows, self.trout.pk).days, 3)
        self.assertIsNone(withdrawal.row_for([row for row in rows if row.species_id], self.trout.pk))
        # The Reader asks it: the row it holds a batch by is the one row_for gives its species.
        self.treat(medicine, 3, 3)
        [held] = self.held()
        self.assertEqual(held.rule.row, withdrawal.row_for(rows, self.salmon.pk))

    def test_a_running_course_counts_from_its_planned_last_day(self):
        treatment = self.treat(self.medicine(days=7), 1, -3)          # yesterday to 3 days ahead
        self.assertEqual(self.held()[0].until, self.day(-11))
        self.going_on(services.change_last_day, self.user, treatment, self.day(-1))   # stopped earlier: asked (an earlier end)
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
        self.going_on(services.void_treatment, self.user, treatment, 'Recorded on the wrong site')
        self.assertEqual(self.held(), [])
        self.assertEqual(registry.blocks(self.t1, self.today), [])

    def test_the_withdrawal_follows_the_batch_into_another_unit(self):
        # Treated in T-01 4 days ago, 30 degree-days; all moved to T-02 2 days ago. T-01 12 °C, T-02 6 °C: the
        # day of the move counts the lower; after it, T-02's water. 12 + 6 + 6 = 24 by yesterday, 6 to go at
        # the mean 8 °C (12, 6, 6), about tomorrow. With T-01's water alone it would have been 36: free today.
        self.treat(self.medicine(degree_days=30), 4, 4)
        moving = handling_check.assess('transport', self.t1, self.day(2), self.batch)
        self.assertEqual(moving.warnings, [])           # live fish moved: a meat withdrawal is not asked
        stock_services.record_transfer(self.user, source=self.t1, batch=self.batch, day=self.day(2),
                                       legs=[(self.t2, 2000)], reason='density')
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

    def test_only_a_harvest_is_warned_of_a_withdrawal_a_transport_and_a_grading_are_not(self):
        # The same batch and treatment: held 3 days after its last, with 7 days of withdrawal.
        self.treat(self.medicine(days=7), 3, 3)
        harvest = handling_check.assess('harvest', self.t1, self.today, self.batch)
        self.assertEqual([(warning.warning, warning.block.until) for warning in harvest.warnings],
                         [('withdrawal', self.day(-5))])
        self.assertTrue(harvest.messages()[0].startswith('Not suitable for harvest — medicine withdrawal of '))
        for kind in ('transport', 'grading', 'treatment'):
            with self.subTest(kind=kind):
                result = handling_check.assess(kind, self.t1, self.today, self.batch)
                self.assertEqual(result.warnings, [])
                self.assertFalse([note for note in result.notes if 'withdrawal' in note.lower()])
        # Through the stock service: a grading goes ahead unasked, a harvest is asked for its box.
        stock_services.record_grading(self.user, source=self.t1, batch=self.batch, day=self.today,
                                      outputs=[(self.t2, 500, Decimal(140), 'Large')],
                                      remainder_avg_weight_g=Decimal(120))
        self.assertFalse(HandlingAcknowledgement.objects.exists())
        self.assertEqual(self.refused(stock_services.record_harvest, self.user, unit=self.t1, batch=self.batch,
                                      day=self.today, count=100, measured_weight_kg=Decimal(12),
                                      facility=make_facility()),
                         {'handling_ack': ['Tick the box to go on despite these warnings.']})

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
        self.going_on(self.treat, in_feed, 3, 2)          # the unknown end becomes a date: an earlier end, asked
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
        self.going_on(self.treat, in_feed, 2, 0)
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


class BulkRegistryTests(HealthTestCase):
    """The registry answers for many units at once; the old one-unit provider is kept here as the oracle."""

    def setUp(self):
        super().setUp()
        Site.objects.filter(pk=self.bergen.pk).update(timezone='America/Los_Angeles')
        Site.objects.filter(pk=self.tromso.pk).update(timezone='Pacific/Auckland')
        self.s1 = make_unit('S-01', self.sea, 'pond', status=Status.ACTIVE)
        self.t1, self.t2, self.s1 = (Tank.objects.select_related('production_department__site').get(pk=unit.pk)
                                     for unit in (self.t1, self.t2, self.s1))
        self.b2, self.b3 = self.stock(self.t2, count=500), self.stock(self.s1, count=300)
        self.treat(self.medicine(days=7), 5, 3, units=[self.t1])
        other = self.medicine(name='Other', days=12)
        self.treat(other, 5, 2, units=[self.t2])
        self.treat(other, 5, 2, units=[self.s1])
        self.units = [self.t1, self.t2, self.s1]

    def one_unit_provider(self, unit, day):
        """The provider as it was: one unit, one day."""
        withdrawals = withdrawal.of_units([unit], day).get(unit.pk, [])
        batches = Batch.all_objects.in_bulk({each.batch_id for each in withdrawals})
        return [WithdrawalBlock(batches[each.batch_id], each.until, each.estimated, withdrawal.describe(each),
                                each.source) for each in withdrawals]

    def test_blocks_of_equals_the_one_unit_answers_in_two_time_zones(self):
        for day in (None, self.day(-3), self.day(2)):
            with self.subTest(day=day):
                found = registry.blocks_of(self.units, day)
                self.assertEqual(set(found), {unit.pk for unit in self.units})
                for unit in self.units:
                    self.assertEqual(found[unit.pk], self.one_unit_provider(unit, day or local_today(unit)))
                    self.assertEqual(registry.blocks(unit, day or local_today(unit)), found[unit.pk])
        self.assertTrue(all(registry.blocks_of(self.units).values()))       # the fixture does hold every unit

    def test_in_force_of_equals_in_force_for_each_unit(self):
        for day in (None, self.day(-4)):
            found = handling_check.in_force_of(self.units, day)
            for unit in self.units:
                self.assertEqual(found[unit.pk], handling_check.in_force(unit, day or local_today(unit)))

    def test_the_row_badges_of_production_units_are_the_units_with_a_block_in_force(self):
        self.assertEqual(set(harvest_views.withdrawals(self.units)), {self.t1.pk, self.t2.pk, self.s1.pk})
        self.assertEqual(harvest_views.withdrawals([self.t1])[self.t1.pk][0].batch, self.batch)
        self.assertEqual(harvest_views.withdrawals([]), {})
        kept = list(registry._providers)
        registry._providers.clear()
        try:
            self.assertEqual(harvest_views.withdrawals(self.units), {})
            self.assertIsNone(handling_check.in_force_of(self.units))
        finally:
            registry._providers.extend(kept)

    def test_the_queries_do_not_grow_with_the_units_of_a_time_zone(self):
        with CaptureQueriesContext(connection) as one:
            registry.blocks_of([self.t1])
        with CaptureQueriesContext(connection) as two:
            registry.blocks_of([self.t1, self.t2])
        self.assertEqual(len(one), len(two))
        with CaptureQueriesContext(connection) as three:
            registry.blocks_of(self.units)
        self.assertLessEqual(len(three), 2 * len(one))        # a second time zone costs one more reader


class BulkHealthReadTests(HealthTestCase):
    """The treatments, open events and latest counts of many units, each against the per-unit code the drawer had."""

    @withdrawal_gate.opened('test fixture: withdrawal inputs written straight in the database')
    def setUp(self):
        super().setUp()
        Site.objects.filter(pk=self.tromso.pk).update(timezone='Pacific/Auckland')
        self.m1 = make_unit('M-01', self.sea, status=Tank.Status.PREPARING)
        self.stock(self.t2, count=500, days_ago=30)
        self.stock(self.m1, count=300, days_ago=30)
        bath = self.medicine(days=7)
        self.recent, self.running = self.treat(bath, 9, 5), self.treat(bath, 2, -3)
        self.old = self.treat(bath, 29, 28, units=[self.t2])
        Treatment.objects.filter(pk=self.old.pk).update(start_date=self.day(150), end_date=self.day(120))
        self.old.refresh_from_db()
        self.other_unit = self.treat(bath, 20, 18, units=[self.t2])
        self.at_sea = self.treat(bath, 4, 3, units=[self.m1])
        self.wide = HealthEvent.objects.create(site=self.bergen, date=self.day(3), kind='observation')
        self.named = HealthEvent.objects.create(site=self.bergen, date=self.day(2), kind='observation')
        self.named.units.add(self.t2)
        HealthEvent.objects.create(site=self.bergen, date=self.day(5), kind='observation', closed_on=self.day(1))
        self.sea_event = HealthEvent.objects.create(site=self.tromso, date=self.day(1), kind='observation')
        for unit, days_ago, females in ((self.t1, 3, 1), (self.t1, 1, 4), (self.m1, 2, 2)):
            services.record_lice_count(self.user, unit=unit, day=self.day(days_ago), fish_counted=10,
                                       adult_females=females, mobile=0, attached=0)
        self.units = [Tank.objects.select_related('production_department__site').get(pk=unit.pk)
                      for unit in (self.t1, self.t2, self.m1)]

    # The code the drawer ran for one unit, kept as the oracle.
    def old_treatments(self, unit):
        since = local_today(unit) - timedelta(days=90)
        return list(unit.treatments.filter(end_date__gte=since).select_related('medicine').order_by('-start_date'))

    def old_events(self, unit):
        site = unit.production_department.site
        events = HealthEvent.objects.filter(site=site, closed_on__isnull=True).prefetch_related('units')
        return [event for event in events if not event.units.all() or unit in event.units.all()]

    def test_one_rule_says_which_events_concern_a_unit(self):
        """The data-layering audit, L-9: read.concerning (the query the mortality, cull and treatment choices read) and
        read.open_events (the drawer) give the same events for each unit as the per-unit rule did."""
        for unit in self.units:
            with self.subTest(unit=unit.code):
                expected = {event.pk for event in self.old_events(unit)}
                self.assertEqual({event.pk for event in read.concerning([unit.pk])}, expected)
                self.assertEqual({event.pk for event in read.open_events([unit])[unit.pk]}, expected)
        self.assertNotIn(self.named.pk, {event.pk for event in read.concerning([self.t1.pk])})

    def old_latest(self, unit_ids):
        found = {}
        for count in LiceCount.objects.filter(unit_id__in=unit_ids).order_by('date', 'created_at'):
            found[count.unit_id] = count
        return found

    def test_recent_treatments_equal_the_one_unit_query(self):
        found = read.recent_treatments(self.units)
        for unit in self.units:
            self.assertEqual(found[unit.pk], self.old_treatments(unit))
        self.assertEqual(found[self.t1.pk], [self.running, self.recent])
        self.assertEqual(found[self.t2.pk], [self.other_unit])          # the course of 120 days ago is out
        self.assertEqual(found[self.m1.pk], [self.at_sea])
        self.assertEqual(read.recent_treatments([self.t2], days=200)[self.t2.pk], [self.other_unit, self.old])

    def test_open_events_equal_the_one_unit_filter(self):
        found = read.open_events(self.units)
        for unit in self.units:
            self.assertEqual(found[unit.pk], self.old_events(unit))
        self.assertEqual(found[self.t1.pk], [self.wide])
        self.assertEqual(found[self.t2.pk], [self.named, self.wide])      # the newest first
        self.assertEqual(found[self.m1.pk], [self.sea_event])

    def test_the_latest_counts_are_one_row_a_unit_and_equal_the_old_loop(self):
        ids = [unit.pk for unit in self.units]
        found = read.latest_counts(ids)
        self.assertEqual(found, self.old_latest(ids))
        self.assertEqual((found[self.t1.pk].date, found[self.t1.pk].adult_females), (self.day(1), 4))
        self.assertNotIn(self.t2.pk, found)
        self.assertEqual(read.latest_counts([]), {})

    def test_the_queries_do_not_grow_with_the_units(self):
        for name in ('recent_treatments', 'open_events'):
            function = getattr(read, name)
            function(self.units)                                          # warm the units' own relations
            counts = []
            for units in (self.units[:1], self.units[:2], self.units):
                with CaptureQueriesContext(connection) as queries:
                    function(units)
                counts.append(len(queries))
            self.assertEqual(counts[0], counts[1], name)
            self.assertLessEqual(counts[2], counts[0] + 1, name)          # the other site's events are one more filter
        counts = []
        for ids in ([self.t1.pk], [self.t1.pk, self.t2.pk], [unit.pk for unit in self.units]):
            with CaptureQueriesContext(connection) as queries:
                read.latest_counts(ids)
            counts.append(len(queries))
        self.assertEqual(counts, [1, 1, 1])

    def test_the_drawer_shows_the_same_lists(self):
        page = self.client.get(reverse('farm:production_units'), {'unit': self.t2.pk})
        self.assertEqual(page.context['health_treatments'], [self.other_unit])
        self.assertEqual({event.pk for event in page.context['health_events']}, {self.wide.pk, self.named.pk})


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
        self.going_on(services.void_treatment, self.user, treatment, 'Wrong unit')
        self.assertTrue(self.refused(services.change_last_day, self.user, treatment, self.day(1)))

    def test_a_void_needs_its_reason_and_is_logged(self):
        treatment = self.treat(self.medicine(days=7), 2, 2)
        self.assertIn('reason', self.refused(services.void_treatment, self.user, treatment, '  '))
        self.going_on(services.void_treatment, self.user, treatment, 'Recorded twice')   # its fish were held: asked
        treatment = Treatment.all_objects.get(pk=treatment.pk)
        self.assertEqual((treatment.is_deleted, treatment.void_reason, treatment.deleted_by),
                         (True, 'Recorded twice', self.user))
        row = AuditLog.objects.get(entity_type='treatment', action='void')
        self.assertEqual(row.changes['Reason for voiding'], [None, 'Recorded twice'])
        self.assertTrue(AuditLog.objects.filter(entity_type='treatment', entity_id=str(treatment.pk),
                                                severity=AuditLog.Severity.CRITICAL).exists())   # the guard's entry
        self.assertTrue(self.refused(services.void_treatment, self.user, treatment, 'Again'))

    @withdrawal_gate.opened('test fixture: withdrawal inputs written straight in the database')
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
        self.assertIn(f'T-01 · {self.batch.code}: harvest from {self.day(-5).isoformat()}. Salmosan vet., bath',
                      out.getvalue())
        self.assertIn('1 of 1 units with fish are under a medicine withdrawal.', out.getvalue())

    @withdrawal_gate.opened('test fixture: withdrawal inputs written straight in the database')
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


@dataclass
class FakeNotices:
    """A provider of farm/health/notices.py that knows the events it was given."""
    known: dict

    def told(self, events):
        return {event.pk: self.known[event.pk] for event in events if event.pk in self.known}

    def start_url(self, event, user):
        return f'/notice/{event.pk}/' if user.has_perm('farm.view_healthevent') else ''


class NoticesRegistryTests(HealthTestCase):
    """That Mattilsynet was told of a disease is read from the filed notices through a registry (D-4), never from a
    column of the event; with no provider it is "not checked", never "not notified"."""

    def setUp(self):
        super().setUp()
        self.pd = HealthEvent.objects.create(site=self.bergen, date=self.day(2), kind='vet_visit', diagnosis='pd',
                                             confirmation='suspected')
        self.isa = HealthEvent.objects.create(site=self.bergen, date=self.day(3), kind='vet_visit', diagnosis='isa',
                                              confirmation='confirmed')
        self.lice = HealthEvent.objects.create(site=self.bergen, date=self.day(1), kind='vet_visit',
                                               diagnosis='sea_lice', confirmation='confirmed')
        self.told_at = datetime.combine(self.day(1), time(9, 30), tzinfo=zone_of(self.bergen))

    def provider(self, *told):
        return mock.patch.object(notices, '_providers', [FakeNotices({
            event.pk: notices.Notified(self.told_at, 'AR-1') for event in told})])

    def test_with_no_provider_nothing_is_checked(self):
        with mock.patch.object(notices, '_providers', []):
            self.assertIsNone(notices.told([self.pd]))
            self.assertIsNone(notices.pending([self.pd]))
            self.assertEqual(notices.start_url(self.pd, self.user), '')
            page = self.client.get(reverse('farm:healthevent_list'))
            self.assertNotContains(page, 'Notify Mattilsynet')
            self.assertNotContains(page, 'Notify at once')

    def test_the_events_of_a_listed_disease_not_yet_told_are_pending_and_a_void_or_a_sea_lice_count_is_not(self):
        with self.provider(self.isa):
            self.assertEqual(notices.pending([self.pd, self.isa, self.lice]), [self.pd])
            self.assertEqual(notices.told([self.pd, self.isa]), {self.isa.pk: notices.Notified(self.told_at, 'AR-1')})
            self.pd.is_deleted = True
            self.assertEqual(notices.pending([self.pd]), [])
            self.pd.is_deleted = False
        with self.provider():
            self.assertEqual(notices.pending([self.pd, self.isa, self.lice]), [self.pd, self.isa])

    def test_the_earliest_telling_counts_when_providers_disagree(self):
        later = FakeNotices({self.pd.pk: notices.Notified(self.told_at.replace(hour=15), 'AR-2')})
        earlier = FakeNotices({self.pd.pk: notices.Notified(self.told_at, 'AR-1')})
        with mock.patch.object(notices, '_providers', [later, earlier]):
            self.assertEqual(notices.told([self.pd])[self.pd.pk].reference, 'AR-1')

    def test_the_list_offers_the_notice_and_shows_when_it_was_filed(self):
        with self.provider(self.isa):
            page = self.client.get(reverse('farm:healthevent_list'))
            self.assertContains(page, 'Notify Mattilsynet')
            self.assertContains(page, f'href="/notice/{self.pd.pk}/"')
            self.assertNotContains(page, f'href="/notice/{self.isa.pk}/"')
            self.assertContains(page, 'Notified')
            self.assertEqual([event for event, _url in page.context['to_notify']], [self.pd])
        with self.provider(self.pd, self.isa):
            self.assertNotContains(self.client.get(reverse('farm:healthevent_list')), 'Notify at once')

    def test_a_person_who_may_not_start_notices_is_told_to_notify_without_the_link(self):
        class Refusing(FakeNotices):
            def start_url(self, event, user):
                return ''
        with mock.patch.object(notices, '_providers', [Refusing({})]):
            page = self.client.get(reverse('farm:healthevent_list'))
            self.assertContains(page, 'Notify Mattilsynet')
            self.assertNotContains(page, '/notice/')

    def test_the_units_drawer_marks_its_pending_events(self):
        self.pd.units.add(self.t1)
        with self.provider():
            page = self.client.get(reverse('farm:production_units'), {'unit': self.t1.pk})
            self.assertEqual(page.context['health_notify'], {self.pd.pk, self.isa.pk})
        with self.provider(self.pd, self.isa):
            self.assertEqual(self.client.get(reverse('farm:production_units'),
                                             {'unit': self.t1.pk}).context['health_notify'], set())


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
            'strength_unit': '', 'manufacturer': '', 'status': 'active', 'notes': ''}
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
                    status='active', notes='Keep dry')
        medicine = Medicine.objects.get()
        self.assertEqual(
            (medicine.name, medicine.marketing_authorisation, medicine.kind, medicine.administration,
             medicine.active_substance, medicine.lice_report_code, medicine.strength_value, medicine.strength_unit,
             medicine.manufacturer, medicine.prescription_only, medicine.status, medicine.notes,
             medicine.created_by),
            ('Salmosan vet.', 'MT-12345', 'lice', 'bath', 'azamethiphos', 'AZAMETHIPHOS', Decimal('500.000'),
             'MILLIGRAM_PER_GRAM', self.pharma, True, 'active', 'Keep dry', self.user))
        # A medicine is made first, its withdrawal rows follow on their own tab: none yet.
        self.assertEqual(medicine.withdrawals.count(), 0)
        page = self.client.get(reverse('farm:medicine_list'))
        self.assertEqual(list(page.context['objects']), [medicine])
        self.assertContains(page, 'Not recorded')
        self.withdraw(medicine, None, degree_days=150, days=7)
        self.assertContains(self.client.get(reverse('farm:medicine_list')),
                            '150 degree-days or 7 days, whichever ends later')
        # Edit: every optional field cleared, the kind changed.
        self.edit(medicine, name='Aqui-S vet.', kind='anaesthetic', active_substance='isoeugenol',
                  lice_report_code='', status='inactive')
        medicine.refresh_from_db()
        self.assertEqual(
            (medicine.name, medicine.marketing_authorisation, medicine.kind, medicine.lice_report_code,
             medicine.strength_value, medicine.strength_unit, medicine.manufacturer, medicine.prescription_only,
             medicine.status, medicine.notes, medicine.version),
            ('Aqui-S vet.', '', 'anaesthetic', '', None, '', None, False, 'inactive', '', 2))
        self.assertEqual(medicine.withdrawals.get().days, 7)                # editing the medicine leaves its rows
        self.client.post(reverse('farm:medicine_delete', args=[medicine.pk]))
        self.assertTrue(Medicine.all_objects.get(pk=medicine.pk).is_deleted)
        self.assertEqual(list(AuditLog.objects.filter(entity_type='medicine').values_list('action', flat=True)),
                         ['delete', 'update', 'create'])

    def test_the_rules_on_their_fields(self):
        cases = [
            ({'lice_report_code': ''}, 'lice_report_code'),
            ({'kind': 'antibacterial'}, 'lice_report_code'),
            ({'strength_value': '5'}, 'strength_unit'),
            ({'strength_unit': 'PROSENT'}, 'strength_value'),
            ({'manufacturer': str(self.vet.pk)}, 'manufacturer'),
        ]
        for overrides, field in cases:
            with self.subTest(overrides=overrides):
                response = self.create(**overrides)
                self.assertIn(field, response.context['form'].errors)
        self.create()
        self.assertIn('name', self.create(name='SALMOSAN VET.').context['form'].errors)

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


class MedicineWithdrawalPageTests(HealthTestCase):
    """A medicine's withdrawal per species: the rows on the Withdrawal tab, saved as a list."""

    def setUp(self):
        super().setUp()
        self.slice = self.medicine(name='Slice vet.', administration='in_feed', active_substance='emamectin benzoate',
                                   lice_report_code='EMAMECTIN_BENZOAT')
        self.url = reverse('farm:medicine_withdrawals', args=[self.slice.pk])
        self.cod = make_species('COD', 'Atlantic cod', 'Gadus morhua', saltwater=True)

    def data(self, rows, initial=0):
        """What the Withdrawal tab posts: its rows, and the medicine's version as stored now (a list saved on an outdated
        record is refused)."""
        return rows_data('withdrawals', rows, initial, record=self.slice)

    def rows(self):
        return list(self.slice.withdrawals.values_list('species__code', 'degree_days', 'days', 'safety_margin_pct',
                                                       'note'))

    def test_create_read_edit_delete(self):
        # Create: one for every species, two of their own, and a row left blank.
        response = self.client.post(self.url, self.data([
            {'species': '', 'degree_days': '150', 'days': '7', 'safety_margin_pct': '20', 'note': 'SPC 2024'},
            {'species': str(self.salmon.pk), 'degree_days': '', 'days': '10', 'safety_margin_pct': '', 'note': ''},
            {'species': str(self.trout.pk), 'degree_days': '0', 'days': '', 'safety_margin_pct': '12.5',
             'note': 'Vet, Nov 2026'},
            {'species': '', 'degree_days': '', 'days': '', 'safety_margin_pct': '', 'note': ''},
        ]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.rows(), [
            (None, Decimal('150.0'), 7, Decimal('20.0'), 'SPC 2024'),
            ('SAL', None, 10, Decimal('0.0'), ''),
            ('RBT', Decimal('0.0'), None, Decimal('12.5'), 'Vet, Nov 2026'),
        ])
        self.assertEqual(set(self.slice.withdrawals.values_list('created_by', flat=True)), {self.user.pk})
        # Read: the edit page lists them on their tab, the list shows them per species.
        page = self.client.get(reverse('farm:medicine_edit', args=[self.slice.pk]))
        self.assertEqual([(form['species'].value(), form['days'].value()) for form in page.context['withdrawals'].forms],
                         [(None, 7), (self.salmon.pk, 10), (self.trout.pk, None)])
        self.assertContains(page, 'data-panel="withdrawal"')
        self.assertContains(page, 'Save withdrawal')
        listing = self.client.get(reverse('farm:medicine_list'))
        self.assertContains(listing, 'Other species</strong>: 150 degree-days + 20 % safety margin = 180 '
                                     'degree-days or 7 days + 20 % safety margin = 9 days, whichever ends later')
        self.assertContains(listing, 'Atlantic salmon</strong>: 10 days')
        self.assertContains(listing, 'Rainbow trout</strong>: 0 degree-days + 12.5 % safety margin = 0 degree-days')
        self.assertContains(listing, 'SPC 2024')
        # Edit: a value changes, a margin is cleared, a species is changed; Delete: a row is removed.
        every, salmon, trout = self.slice.withdrawals.all()
        self.client.post(self.url, self.data([
            {'id': str(every.pk), 'species': '', 'degree_days': '', 'days': '14', 'safety_margin_pct': '',
             'note': 'SPC 2025'},
            {'id': str(salmon.pk), 'species': str(self.cod.pk), 'degree_days': '', 'days': '10',
             'safety_margin_pct': '5', 'note': ''},
            {'id': str(trout.pk), 'species': str(self.trout.pk), 'degree_days': '0', 'days': '', 'DELETE': True},
        ], initial=3))
        self.assertEqual(self.rows(), [
            (None, None, 14, Decimal('0.0'), 'SPC 2025'),
            ('COD', None, 10, Decimal('5.0'), ''),
        ])
        entry = AuditLog.objects.filter(entity_type='medicine', action='update').latest('created_at')
        self.assertEqual(list(entry.changes), ['Withdrawal'])
        before, after = entry.changes['Withdrawal']
        self.assertIn('Rainbow trout: 0 degree-days + 12.5 % safety margin = 0 degree-days (Vet, Nov 2026)', before)
        self.assertEqual(after, 'Every species: 14 days (SPC 2025); Atlantic cod: 10 days + 5 % safety margin = 11 days')
        # Delete them all: the medicine has no withdrawal recorded.
        self.client.post(self.url, self.data([]))
        self.assertEqual(self.rows(), [])
        self.assertContains(self.client.get(reverse('farm:medicine_list')), 'Not recorded')

    def test_the_rules_of_the_rows_on_their_fields(self):
        def post(*rows):
            return self.client.post(self.url, self.data(list(rows)))

        every = {'species': '', 'degree_days': '', 'days': '3'}
        for row, field in (({'species': str(self.salmon.pk)}, 'degree_days'),                  # no value at all
                           ({**every, 'days': '-1'}, 'days'), ({**every, 'days': '1001'}, 'days'),
                           ({**every, 'degree_days': '10001'}, 'degree_days'),
                           ({**every, 'degree_days': '-1'}, 'degree_days'),
                           ({**every, 'safety_margin_pct': '200.1'}, 'safety_margin_pct'),
                           ({**every, 'safety_margin_pct': '-1'}, 'safety_margin_pct'),
                           ({**every, 'degree_days': '10.55'}, 'degree_days'),
                           ({**every, 'note': 'x' * 301}, 'note')):
            with self.subTest(row=row):
                response = post(row)
                self.assertEqual(response.status_code, 200)
                self.assertIn(field, response.context['withdrawals'].forms[0].errors)
        self.assertEqual(self.rows(), [])
        # The bounds themselves are in; 0 means none.
        self.assertEqual(post({**every, 'degree_days': '10000', 'days': '1000', 'safety_margin_pct': '200'}).status_code,
                         302)
        self.assertEqual(self.rows(), [(None, Decimal('10000.0'), 1000, Decimal('200.0'), '')])
        # One row per species, and one for every species.
        for rows in ([{'species': str(self.salmon.pk), 'days': '3'}, {'species': str(self.salmon.pk), 'days': '4'}],
                     [every, {**every, 'days': '4'}]):
            response = post(*rows)
            self.assertIn('Two rows are for the same species.', response.context['withdrawals'].non_form_errors())
            self.assertEqual(response.context['open_tab'], 'withdrawal')
        # At most 50 rows; a species that is deleted is not offered.
        response = post(*[{'species': '', 'days': '1'}] * 51)
        self.assertIn('A medicine has at most 50 rows.', response.context['withdrawals'].non_form_errors())
        self.cod.soft_delete(self.user)
        page = self.client.get(reverse('farm:medicine_edit', args=[self.slice.pk]))
        self.assertNotIn(self.cod, page.context['withdrawals'].empty_form.fields['species'].queryset)

    def test_the_database_holds_the_rules_too(self):
        @withdrawal_gate.opened('test fixture: withdrawal inputs written straight in the database')
        def make(**fields):
            return MedicineWithdrawal.objects.create(medicine=self.slice, **fields)

        for fields in ({'species': None}, {'species': self.salmon, 'degree_days': None, 'days': None},
                       {'species': None, 'days': -1}, {'species': None, 'days': 1001},
                       {'species': None, 'degree_days': Decimal(-1)}, {'species': None, 'degree_days': Decimal(10001)},
                       {'species': None, 'days': 1, 'safety_margin_pct': Decimal(-1)},
                       {'species': None, 'days': 1, 'safety_margin_pct': Decimal(200.1)}):
            with self.subTest(fields=fields), self.assertRaises(IntegrityError), transaction.atomic():
                make(**fields)
        make(species=None, days=1)
        make(species=self.salmon, degree_days=Decimal(10000), days=1000, safety_margin_pct=Decimal(200))
        make(species=self.trout, degree_days=Decimal(0))                         # 0 is a value: none
        for fields in ({'species': None, 'days': 2}, {'species': self.salmon, 'days': 2}):     # a second row
            with self.subTest(second=fields), self.assertRaises(IntegrityError), transaction.atomic():
                make(**fields)
        other = self.medicine(name='Other', days=1)
        self.assertEqual(other.withdrawals.count(), 1)                          # the same species on another medicine

    def test_the_rows_stay_with_their_medicine_when_it_is_deleted_and_come_back_when_it_is_restored(self):
        self.withdraw(self.slice, None, days=14)
        self.withdraw(self.slice, self.salmon, days=10, margin=10, note='x')
        softdelete.execute(plan_delete(self.slice), self.user)
        self.assertEqual(self.slice.withdrawals.count(), 2)                 # untouched: owned rows stay with the parent
        self.assertEqual(AuditLog.objects.filter(entity_type='medicine withdrawal').count(), 0)
        softdelete.restore(Medicine.all_objects.get(pk=self.slice.pk), self.user)
        self.assertEqual(sorted(self.rows(), key=str), sorted([(None, None, 14, Decimal('0.0'), ''),
                                                              ('SAL', None, 10, Decimal('10.0'), 'x')], key=str))

    def test_a_species_keeps_its_rows_while_it_is_deleted_and_a_hard_delete_is_refused(self):
        self.withdraw(self.slice, self.cod, days=10)
        with self.assertRaises(ProtectedError), transaction.atomic():
            Species.all_objects.get(pk=self.cod.pk).delete()
        self.cod.soft_delete(self.user)
        self.assertEqual(self.slice.withdrawals.count(), 0)                  # out of sight with the species
        self.assertEqual(MedicineWithdrawal.all_objects.filter(medicine=self.slice).count(), 1)
        softdelete.restore(Species.all_objects.get(pk=self.cod.pk), self.user)
        self.assertEqual(self.slice.withdrawals.count(), 1)                  # and back with it

    def test_it_needs_the_change_permission_of_the_medicine(self):
        viewer = get_user_model().objects.create_user('kari', 'kari@example.com', 'x')
        viewer.groups.add(role('Medicine viewer', 'view_medicine'))
        self.client.force_login(viewer)
        response = self.client.post(self.url, self.data([{'species': '', 'days': '3'}]))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.rows(), [])

    def test_the_withdrawal_tab_is_the_form_after_the_medicine_exists(self):
        page = self.client.get(reverse('farm:medicine_create'), headers={'X-Modal': '1'})
        self.assertContains(page, 'The withdrawal can be added once the medicine is created.')
        self.assertNotContains(page, 'Save withdrawal')
        self.assertContains(page, 'data-tab="withdrawal">Withdrawal</button>')

    def test_the_treatment_dialog_and_the_last_day_dialog_say_the_rule_of_the_medicine(self):
        self.withdraw(self.slice, None, degree_days=150, margin=20)
        self.withdraw(self.slice, self.trout, days=7)
        page = self.client.get(reverse('farm:treatment_record'), {'unit': self.t1.pk})
        self.assertContains(page, 'Slice vet. · emamectin benzoate · in feed · Other species: 150 degree-days + 20 % '
                                  'safety margin = 180 degree-days; Rainbow trout: 7 days')
        bare = self.medicine(name='Bare vet.')
        self.assertContains(self.client.get(reverse('farm:treatment_record'), {'unit': self.t1.pk}),
                            'Bare vet. · azamethiphos · bath · Not recorded')
        treatment = self.treat(self.slice, 3, 3, method='in_feed')
        self.assertContains(self.client.get(reverse('farm:treatment_last_day', args=[treatment.pk])),
                            'withdrawal Other species: 150 degree-days')
        self.assertIsNotNone(bare.pk)


def event_data(site, **overrides):
    data = {'site': str(site.pk), 'units': [], 'date': '', 'kind': 'observation', 'signs': [], 'diagnosis': '',
            'confirmation': '', 'examined_by': '', 'vet': '', 'lab': '',
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
             event.confirmation, event.examined_by, event.vet, event.lab,
             event.lab_reference, event.findings, event.recommendations, event.created_by),
            (self.bergen, [self.t1], self.day(2), 'vet_visit', ['reduced_appetite', 'pale_gills'], 'pd', 'suspected',
             'Dr. Hansen', self.vet, self.vet, 'L-9', 'Pale gills in T-01', 'Sample again', self.user))
        page = self.client.get(reverse('farm:healthevent_list'))
        self.assertEqual(list(page.context['objects']), [event])
        self.assertContains(page, 'Notify Mattilsynet')
        self.assertContains(page, 'Reduced appetite, Pale gills')
        # Edit: confirmed and closed, then every optional field cleared. That Mattilsynet was told is a notice's
        # filing (farm/health/notices.py), not a field of the event.
        self.assertNotIn('authority_notified_at', self.client.get(
            reverse('farm:healthevent_edit', args=[event.pk])).context['form'].fields)
        self.client.post(reverse('farm:healthevent_edit', args=[event.pk]), event_data(
            self.bergen, units=[str(self.t1.pk)], date=self.day(2).isoformat(), kind='vet_visit', diagnosis='pd',
            confirmation='confirmed', closed_on=self.day(1).isoformat(), outcome='Recovered', version='1'))
        event.refresh_from_db()
        self.assertEqual((event.confirmation, event.closed_on, event.outcome, event.signs, event.examined_by,
                          event.vet), ('confirmed', self.day(1), 'Recovered', [], '', None))
        self.client.post(reverse('farm:healthevent_edit', args=[event.pk]), event_data(
            self.bergen, date=self.day(2).isoformat(), kind='observation', version='2'))
        event.refresh_from_db()
        self.assertEqual((list(event.units.all()), event.diagnosis, event.confirmation, event.closed_on,
                          event.outcome, event.version), ([], '', '', None, '', 3))
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
        [part] = page.context['rows'][0]['batches']
        self.assertEqual((part.batch, part.withdrawal.until, part.held, part.units),
                         (self.batch, self.day(-7), True, ()))                # the last day + 7 + 1
        self.assertContains(page, self.batch.code)
        # The last day, changed through its dialog.
        self.client.post(reverse('farm:treatment_last_day', args=[treatment.pk]),
                         {'end_date': self.day(-1).isoformat()})
        treatment.refresh_from_db()
        self.assertEqual(treatment.end_date, self.day(-1))
        # Voided through its dialog: struck through when asked for, and its withdrawal gone.
        asked = self.client.post(reverse('farm:treatment_void', args=[treatment.pk]), {'reason': 'Wrong cage'})
        self.assertEqual(asked.status_code, 422)                    # its fish are held today: the guard asks
        self.client.post(reverse('farm:treatment_void', args=[treatment.pk]), {
            'reason': 'Wrong cage', 'withdrawal_ack': asked.context['form'].withdrawal_change.fingerprint})
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


class TreatmentPageSiteBehindTests(FrozenClock, HealthTestCase):
    """The Treatments page reads each treatment on its own site's today, as the unit's own withdrawal line does
    (withdrawal.of_units), not on the company's: at 23:30 UTC on the 10th it is the 10th on T-01's site (UTC) and already
    the 11th in Oslo. On the company's day the page freed the fish a day early and counted the site's running day as a
    past one without a temperature."""
    NOW = BAD_HOURS['WinterNight']

    def rows(self, **query):
        return self.client.get(reverse('farm:treatments'), query).context['rows']

    def test_fish_on_their_last_held_day_are_under_withdrawal_as_the_units_own_line_says(self):
        treatment = self.treat(self.medicine(days=1), 1, 1)        # given yesterday, 1 day: free tomorrow, held today
        [line] = self.held()
        self.assertEqual((self.today, line.until), (BAD_HOURS['WinterNight'].date(), self.day(-1)))
        [row] = self.rows(show='withdrawal')                       # "Under withdrawal today": the site's today
        [part] = row['batches']
        self.assertEqual((row['treatment'], part.today, part.batch, part.withdrawal.until, part.held),
                         (treatment, self.today, self.batch, line.until, True))
        self.assertContains(self.client.get(reverse('farm:treatments')), '<span class="over-text" title="')

    def test_the_sites_running_day_is_not_counted_as_a_past_day_without_a_temperature(self):
        self.treat(self.medicine(degree_days=50), 6, 6)            # five past days, none measured
        [line] = self.held()
        [row] = self.rows()
        [part] = row['batches']
        self.assertEqual((part.withdrawal.days_without_temperature, part.withdrawal.until), (5, line.until))
        self.assertEqual(line.days_without_temperature, 5)


class TokyoCase(HealthTestCase):
    """A second site on Tokyo's clock beside the fixtures' Bergen (UTC), with a unit K-01; the company's clock is
    Oslo's. `treated_there` stocks K-01 and treats its fish; `moved_here` moves them to Bergen's T-02. What the
    Treatments list says of fish on several clocks is in test_withdrawal_clocks.py."""

    def setUp(self):
        super().setUp()
        tokyo = Site.objects.create(name='Tokyo', code='TK', timezone='Asia/Tokyo')
        hall = ProductionDepartment.objects.create(site=tokyo, name='Hall T', code='HT')
        self.k1 = make_unit('K-01', hall)

    def treated_there(self, last_day_ago, days):
        """Fish in K-01 given a bath whose last day was `last_day_ago` days back on Tokyo's clock, `days` days of
        withdrawal: (the batch, the treatment, the first day the fish may be harvested)."""
        there = local_today(self.k1)
        batch = self.stock(self.k1, count=1000, weight='100', days_ago=10)
        last = there - timedelta(days=last_day_ago)
        treatment = services.record_treatment(self.user, units=[self.k1], method='bath', reason='sea_lice',
                                              start_date=last, end_date=last, medicine=self.medicine(days=days))
        return batch, treatment, last + timedelta(days=days + 1)

    def moved_here(self, batch):
        self.going_on(stock_services.record_transfer, self.user, source=self.k1, batch=batch,
                      day=local_today(self.t2), legs=[(self.t2, 1000)], reason='density')


class EarliestTodayTests(FrozenClock, TokyoCase):
    """farm.stock.dates.earliest_today: the EARLIEST today among the units' sites (the fish are held the longest so).
    16:00 UTC on the 10th is the 10th in Bergen and Oslo and the 11th in Tokyo."""
    NOW = datetime(2026, 11, 10, 16, 0, tzinfo=dt_timezone.utc)

    def test_it_is_the_earliest_day_of_the_units_and_the_companys_without_any(self):
        from ..stock.dates import earliest_today
        self.assertEqual((local_today(self.k1), local_today(self.t2), local_today()),
                         (date(2026, 11, 11), date(2026, 11, 10), date(2026, 11, 10)))
        for units in ([self.k1, self.t2], [self.t2, self.k1]):
            self.assertEqual(earliest_today(units), date(2026, 11, 10))       # never the later one
        self.assertEqual(earliest_today([self.k1]), date(2026, 11, 11))
        self.assertEqual(earliest_today([]), date(2026, 11, 10))               # no unit: the company's

    def test_the_write_guards_day_is_the_earliest_among_every_unit_the_fish_were_in(self):
        batch, _treatment, _until = self.treated_there(2, 1)
        self.assertEqual(withdrawal._reached([self.k1.pk]), ({batch.pk}, date(2026, 11, 11)))     # only in Tokyo yet
        self.moved_here(batch)
        self.assertEqual(withdrawal._reached([self.k1.pk])[1], date(2026, 11, 10))               # Bergen's, the earlier
        self.assertEqual(withdrawal._reached([self.t2.pk])[1], date(2026, 11, 10))


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
        line = (f'Not suitable for harvest — medicine withdrawal of {self.batch.code}: harvest from '
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
        self.assertContains(page, f'Not suitable for harvest — medicine withdrawal of {self.batch.code}: end '
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

"""Water chemistry: the parameters and their checks, the hypertable, the one write path and its void, the
limits, judging on read, the values worked out from a sample, the pages and dialogs, permissions, the
delete plan, the activity log and the database viewer, each checked against the stored rows."""
import math
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from core import access, database, navigation
from core.audit import message
from core.models import AuditLog, Profile
from core.softdelete import plan_delete, restore

from ..models import ProductionDepartment, SamplingPoint, Site, System, Tank, WaterLimit, WaterMeasurement
from ..stock.services import AlreadyRecorded
from ..water import chemistry, parameters, read, services
from ..water.evaluate import Limits, Status, judge, worst
from .helpers import make_species, point_of, role, stock_fish
from .test_stock import make_unit

WATER_KEEPER = ('view_watermeasurement', 'add_watermeasurement', 'delete_watermeasurement', 'view_tank',
                'delete_tank', 'view_system', 'delete_system', 'view_samplingpoint', 'view_species', 'delete_species', 'view_waterlimit',
                'add_waterlimit', 'change_waterlimit', 'delete_waterlimit', 'view_stockoperation', 'view_auditlog')
D = Decimal


def setUpModule():
    call_command('compile_catalogs', verbosity=0)    # the language tests read the built catalogs


# ---- chemistry, without a database -------------------------------------------------------------------------
def weiss_1970(temp_c, salinity):
    """Weiss (1970), Deep-Sea Res. 17: 721, in mL/L × 1.42903 mg/mL: an independent check of Benson & Krause."""
    t = (temp_c + 273.15) / 100
    ln_c = (-173.4292 + 249.6339 / t + 143.3483 * math.log(t) - 21.8492 * t
            + salinity * (-0.033096 + 0.014259 * t - 0.0017000 * t * t))
    return math.exp(ln_c) * 1.42903


class ChemistryTests(SimpleTestCase):
    def test_the_ammonium_constant_is_emersons_in_fresh_water(self):
        # Emerson et al. (1975), J. Fish. Res. Board Can. 32: 2379: pK = 0.09018 + 2729.92 / T; within 0.002 up to
        # 30 °C and 0.003 up to 40 °C, the top of the temperature's range (the two drift apart as it warms).
        for temp_c in range(0, 41):
            with self.subTest(temp_c=temp_c):
                self.assertAlmostEqual(chemistry.pk_nh4(temp_c, 0), 0.09018 + 2729.92 / (temp_c + 273.15),
                                       delta=0.002 if temp_c <= 30 else 0.003)
        self.assertAlmostEqual(chemistry.pk_nh4(10, 0), 9.7314, delta=0.002)
        self.assertAlmostEqual(chemistry.pk_nh4(25, 0), 9.2464, delta=0.002)

    def test_in_sea_water_the_constant_is_millero_1995s(self):
        self.assertAlmostEqual(chemistry.pk_nh4(10, 35), 9.790, delta=0.001)
        self.assertLess(chemistry.nh3_fraction(8.0, 10, 35), chemistry.nh3_fraction(8.0, 10, 0))

    def test_the_share_of_nh3_matches_emersons_table(self):
        # Emerson et al. (1975), Table 1: % un-ionised at 10 °C pH 7.0, 20 °C pH 8.0, 25 °C pH 8.0.
        for temp_c, ph, published in ((10, 7.0, 0.186), (20, 8.0, 3.82), (25, 8.0, 5.38)):
            with self.subTest(temp_c=temp_c, ph=ph):
                self.assertAlmostEqual(100 * chemistry.nh3_fraction(ph, temp_c, 0), published, delta=0.01)

    def test_oxygen_solubility_is_benson_and_krauses(self):
        # Standard Methods 4500-O, Table 4500-O:I, mg/L at 1 atm in fresh water.
        for temp_c, published in ((0, 14.621), (10, 11.288), (20, 9.092), (30, 7.559)):
            with self.subTest(temp_c=temp_c):
                self.assertAlmostEqual(chemistry.oxygen_solubility(temp_c, 0), published, delta=0.001)
        # In sea water: the salinity term of the same equation (the USGS tables: 9.02 mg/L at 10 °C and 35 ‰),
        # and Weiss (1970), an independent fit, within 0.5 % from 0 to 30 °C in fresh and sea water.
        self.assertAlmostEqual(chemistry.oxygen_solubility(10, 35), 9.024, delta=0.001)
        for temp_c in (0, 10, 20, 30):
            for salinity in (0, 35):
                with self.subTest(temp_c=temp_c, salinity=salinity):
                    benson_krause, weiss = chemistry.oxygen_solubility(temp_c, salinity), weiss_1970(temp_c, salinity)
                    self.assertLess(abs(benson_krause - weiss) / weiss, 0.005)

    def test_altitude_lowers_the_pressure_and_the_solubility(self):
        pressure = chemistry.pressure_atm(500)
        self.assertAlmostEqual(pressure * 760, 716.0, delta=0.1)          # mmHg, the standard atmosphere
        self.assertEqual(chemistry.pressure_atm(0), 1.0)
        self.assertAlmostEqual(chemistry.oxygen_solubility(10, 0, pressure), 10.627, delta=0.001)
        self.assertLess(chemistry.oxygen_solubility(10, 0, pressure), 11.288 * pressure)   # water vapour


class JudgeTests(SimpleTestCase):
    def limit(self, **bounds):
        values = {'critical_low': None, 'warning_low': None, 'warning_high': None, 'critical_high': None, **bounds}
        return SimpleNamespace(species_id=1, parameter='oxygen_saturation_pct', water_type='any',
                               **{key: None if value is None else D(value) for key, value in values.items()})

    def test_two_bands_and_a_value_on_a_bound_is_in_the_inner_band(self):
        limit = self.limit(critical_low=60, warning_low=80, warning_high=110, critical_high=120)
        cases = [('59.9', Status.CRITICAL), ('60', Status.WARNING), ('79.9', Status.WARNING), ('80', Status.OK),
                 ('110', Status.OK), ('110.1', Status.WARNING), ('120', Status.WARNING), ('120.1', Status.CRITICAL)]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(judge(D(value), limit), expected)
        self.assertEqual(judge(D(5), self.limit(critical_high=4)), Status.CRITICAL)      # open bounds are open
        self.assertEqual(judge(D(-1), self.limit(critical_high=4)), Status.OK)

    def test_the_worst_species_wins_and_a_water_type_row_beats_the_any_row(self):
        salmon = SimpleNamespace(species_id=1, parameter='ph', water_type='any', critical_low=D('6.5'),
                                 warning_low=D(7), warning_high=None, critical_high=None)
        salmon_sea = SimpleNamespace(species_id=1, parameter='ph', water_type='saltwater', critical_low=D('7.5'),
                                     warning_low=D('7.8'), warning_high=None, critical_high=None)
        lumpfish = SimpleNamespace(species_id=2, parameter='ph', water_type='any', critical_low=None,
                                   warning_low=D('7.2'), warning_high=None, critical_high=None)
        limits = Limits([salmon, salmon_sea, lumpfish])
        self.assertEqual(limits.assess('ph', D('7.1'), [(1, 'freshwater')]), (Status.OK, [salmon]))
        self.assertEqual(limits.assess('ph', D('7.1'), [(1, 'freshwater'), (2, 'freshwater')]),
                         (Status.WARNING, [salmon, lumpfish]))
        self.assertEqual(limits.assess('ph', D('7.1'), [(1, 'saltwater')]), (Status.CRITICAL, [salmon_sea]))
        self.assertEqual(limits.assess('ph', D('7.1'), []), (Status.NO_LIMIT, []))
        self.assertEqual(limits.assess('ph', D('7.1'), [(3, 'freshwater')]), (Status.NO_LIMIT, []))

    def test_the_order_of_worst(self):
        self.assertEqual(worst([Status.OK, Status.STALE, Status.WARNING]), Status.WARNING)
        self.assertEqual(worst([Status.NO_LIMIT, Status.STALE]), Status.NO_LIMIT)
        self.assertEqual(worst([Status.STALE]), Status.STALE)
        self.assertEqual(worst([]), Status.NOT_MEASURED)


# ---- the database ------------------------------------------------------------------------------------------
class WaterTestCase(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('ali', 'ali@example.com', 'eski-sifre-123')
        self.user.groups.add(role('Water keeper', *WATER_KEEPER))
        self.client.force_login(self.user)
        self.bergen = Site.objects.create(name='Bergen', code='BG', altitude=D(0), timezone='UTC')
        self.hall = ProductionDepartment.objects.create(site=self.bergen, name='Hall A', code='HA')
        self.ras = System.objects.create(name='RAS 1', code='R1', site=self.bergen, production_department=self.hall)
        self.t1 = make_unit('T-01', self.hall, system=self.ras)
        self.t2 = make_unit('T-02', self.hall, system=self.ras)
        self.mid1, self.mid2, self.loop = point_of(self.t1), point_of(self.t2), point_of(self.ras)
        self.salmon = make_species()
        self.now = timezone.now().replace(microsecond=0)

    def ago(self, hours=0, days=0):
        return self.now - timedelta(hours=hours, days=days)

    def point(self, place):
        """The sampling point of a place: a point as it is, the middle point of a unit or a system."""
        return place if isinstance(place, SamplingPoint) else point_of(place)

    def sample(self, point=None, hours=1, source='manual', notes='', **values):
        """A sample at a point, or at the middle point of the unit or system given (T-01's by default)."""
        return services.record(self.user, point=self.point(point or self.t1), measured_at=self.ago(hours=hours),
                               source=source, values={code: D(str(value)) for code, value in values.items()},
                               notes=notes)

    def unit_water(self, unit=None):
        return read.unit_water([unit or self.t1])[(unit or self.t1).pk]

    def refused(self, call, *args, **kwargs):
        with self.assertRaises(ValidationError) as caught:
            call(*args, **kwargs)
        return caught.exception.message_dict

    def stock(self, unit=None, species=None):
        return stock_fish(self.user, unit or self.t1, 1000, '50', 10, species=species or self.salmon)

    def limit(self, parameter, species=None, water_type='any', **bounds):
        return WaterLimit.objects.create(species=species or self.salmon, parameter=parameter, water_type=water_type,
                                         **{key: D(str(value)) for key, value in bounds.items()})


class SchemaTests(WaterTestCase):
    def test_every_parameter_is_a_typed_column_with_its_check(self):
        fields = {field.name: field for field in WaterMeasurement._meta.concrete_fields}
        checks = {constraint.name for constraint in WaterMeasurement._meta.constraints}
        for parameter in parameters.MEASURED:
            with self.subTest(parameter=parameter.code):
                field = fields[parameter.code]
                self.assertEqual((field.decimal_places, field.null, str(field.verbose_name)),
                                 (parameter.decimals, True, str(parameter.label)))
                self.assertLessEqual(len(str(int(parameter.high))) + parameter.decimals, field.max_digits)
                self.assertIn(f'chk_water_measurements_{parameter.code}', checks)
        self.assertEqual([code for code, _label in parameters.LIMIT_CHOICES][-1], 'nh3_n_mg_l')

    def test_it_is_a_hypertable_on_the_time_with_the_time_in_its_primary_key(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT extname FROM pg_extension WHERE extname = 'timescaledb'")
            self.assertEqual(cursor.fetchone(), ('timescaledb',))
            cursor.execute("SELECT column_name, time_interval FROM timescaledb_information.dimensions "
                           "WHERE hypertable_name = 'water_measurements'")
            self.assertEqual(cursor.fetchall(), [('measured_at', timedelta(days=90))])
            cursor.execute("""SELECT a.attname FROM pg_index i
                              JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                              WHERE i.indrelid = 'water_measurements'::regclass AND i.indisprimary
                              ORDER BY a.attname""")
            self.assertEqual([row[0] for row in cursor.fetchall()], ['id', 'measured_at'])
            cursor.execute("SELECT 1 FROM timescaledb_information.hypertables WHERE hypertable_name = 'water_limits'")
            self.assertIsNone(cursor.fetchone())

    def test_samples_land_in_chunks_and_read_back(self):
        old = self.sample(hours=24 * 20, temperature_c='8.5')
        self.sample(temperature_c='9.1')
        self.assertEqual(list(WaterMeasurement.objects.values_list('temperature_c', flat=True)), [D('9.1'), D('8.5')])
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM show_chunks('water_measurements')")
            self.assertGreaterEqual(cursor.fetchone()[0], 1)
        services.void(self.user, old, 'Wrong unit')       # an update by id finds the row in its chunk
        self.assertEqual(WaterMeasurement.all_objects.get(pk=old.pk).void_reason, 'Wrong unit')

    def test_the_database_refuses_what_the_service_refuses(self):
        base = {'point': self.mid1, 'measured_at': self.now, 'source': 'manual'}
        cases = [
            ({'ph': D(25)}, 'chk_water_measurements_ph'),
            ({'oxygen_mg_l': D(-3)}, 'chk_water_measurements_oxygen_mg_l'),
            ({'temperature_c': D('41')}, 'chk_water_measurements_temperature_c'),
            ({'tgp_pct': D(49)}, 'chk_water_measurements_tgp_pct'),
            ({}, 'chk_water_measurements_any_value'),
            ({'ph': D(7), 'source': 'guess'}, 'chk_water_measurements_source'),
            ({'ph': D(7), 'is_deleted': True}, 'chk_water_measurements_void_reason'),
        ]
        for values, name in cases:
            with self.subTest(name=name), self.assertRaisesMessage(IntegrityError, name), transaction.atomic():
                WaterMeasurement.objects.create(**{**base, **values})
        with self.assertRaises(IntegrityError), transaction.atomic():
            WaterMeasurement.objects.create(measured_at=self.now, source='manual', ph=D(7))      # no point
        key = uuid.uuid4()
        WaterMeasurement.objects.create(**base, ph=D(7), entry_key=key)
        with self.assertRaisesMessage(IntegrityError, 'uq_water_measurements_entry'), transaction.atomic():
            WaterMeasurement.objects.create(**base, ph=D(8), entry_key=key)


class RecordTests(WaterTestCase):
    def test_the_values_are_stored_in_their_columns_with_who_and_when(self):
        sample = services.record(self.user, point=self.mid1, measured_at=self.ago(hours=2), source='lab',
                                 values={'temperature_c': D('8.4'), 'oxygen_mg_l': D('10.25'), 'ph': D('7.15'),
                                         'tan_mg_l': D('0.125'), 'nitrite_n_mg_l': D('0.015'), 'turbidity_ntu': None},
                                 notes=' Morning ')
        stored = WaterMeasurement.objects.get()
        self.assertEqual((stored.point, stored.point.owner, stored.measured_at, stored.source, stored.created_by,
                          stored.notes),
                         (self.mid1, self.t1, self.ago(hours=2), 'lab', self.user, 'Morning'))
        self.assertEqual(stored.values(), {'temperature_c': D('8.4'), 'oxygen_mg_l': D('10.25'), 'ph': D('7.15'),
                                           'tan_mg_l': D('0.125'), 'nitrite_n_mg_l': D('0.015')})
        self.assertEqual(sample.pk, stored.pk)

    def test_a_loop_sample_is_taken_at_the_loop_point_of_a_system(self):
        services.record(self.user, point=self.loop, measured_at=self.ago(hours=1), source='manual',
                        values={'co2_mg_l': D('12.5')})
        self.assertEqual(WaterMeasurement.objects.get().point.owner, self.ras)

    def test_at_least_one_value_inside_its_range_and_precision(self):
        record = lambda **values: services.record(self.user, point=self.mid1, measured_at=self.ago(hours=1),
                                                  source='manual', values=values)
        self.assertEqual(self.refused(record), {'__all__': ['Enter at least one value.']})
        self.assertEqual(self.refused(record, temperature_c=None), {'__all__': ['Enter at least one value.']})
        self.assertEqual(self.refused(record, ph=D(25)), {'ph': ['Between 2 and 12: check the value.']})
        self.assertEqual(self.refused(record, oxygen_mg_l=D('7.123')), {'oxygen_mg_l': ['At most 2 decimals.']})
        self.assertFalse(WaterMeasurement.all_objects.exists())

    def test_the_time_is_not_in_the_future_nor_older_than_31_days_on_the_sites_clock(self):
        self.bergen.timezone = 'Asia/Tokyo'
        self.bergen.save()
        self.t1.refresh_from_db()
        record = lambda moment: services.record(self.user, point=self.mid1, measured_at=moment, source='manual',
                                                values={'ph': D(7)})
        self.assertEqual(self.refused(record, self.now + timedelta(minutes=5)),
                         {'measured_at': ['The time cannot be in the future.']})
        tokyo = ZoneInfo('Asia/Tokyo')
        first_day = timezone.localdate(timezone=tokyo) - timedelta(days=31)
        record(timezone.make_aware(datetime.combine(first_day, datetime.min.time()), tokyo))
        too_old = timezone.make_aware(datetime.combine(first_day, datetime.min.time()), tokyo) - timedelta(minutes=1)
        self.assertEqual(self.refused(record, too_old), {'measured_at': ['Samples can be dated at most 31 days back.']})
        self.assertEqual(WaterMeasurement.objects.count(), 1)

    def test_a_form_sent_twice_records_once_and_a_deleted_unit_takes_none(self):
        token = uuid.uuid4()
        values = {'point': self.mid1, 'measured_at': self.ago(hours=1), 'source': 'manual', 'values': {'ph': D(7)},
                  'token': token}
        first = services.record(self.user, **values)
        with self.assertRaises(AlreadyRecorded) as caught:
            services.record(self.user, **values)
        self.assertEqual(caught.exception.operation, first)
        self.assertEqual(WaterMeasurement.objects.count(), 1)
        self.t2.soft_delete(self.user)
        self.assertEqual(self.refused(services.record, self.user, point=self.mid2, measured_at=self.ago(hours=1),
                                      source='manual', values={'ph': D(7)}), {'point': ['T-02 is deleted.']})

    def test_each_sample_is_in_the_activity_log_in_english(self):
        Profile.objects.create(user=self.user, language='tr')
        self.sample(source='lab', notes='Before feeding', temperature_c='8', oxygen_saturation_pct='95.5')
        entry = AuditLog.objects.get()
        moment = self.ago(hours=1)
        self.assertEqual((entry.action, entry.entity_type, entry.entity_label),
                         ('create', 'water sample', f'Water sample · T-01 › Middle · {moment:%Y-%m-%d %H:%M}'))
        self.assertEqual(entry.changes, {
            'Measured at': [None, moment.isoformat()], 'Sampling point': [None, 'T-01 › Middle'],
            'Source': [None, message('Laboratory')],
            'Temperature (°C)': [None, '8.0'], 'Oxygen saturation (% of air saturation)': [None, '95.5'],
            'Notes': [None, 'Before feeding']})


class RoundServiceTests(WaterTestCase):
    def test_a_round_shares_its_time_and_source_skips_empty_rows_and_records_all_or_nothing(self):
        moment, token = self.ago(hours=1), uuid.uuid4()
        rows = [(self.mid1, {'temperature_c': D('8.1')}, ''), (self.mid2, {'temperature_c': None}, ''),
                (self.loop, {'oxygen_mg_l': D('9.5')}, 'Sump')]
        samples = services.record_round(self.user, measured_at=moment, source='manual', rows=rows, token=token)
        self.assertEqual([(sample.point, sample.measured_at, sample.source) for sample in samples],
                         [(self.mid1, moment, 'manual'), (self.loop, moment, 'manual')])
        with self.assertRaises(AlreadyRecorded):
            services.record_round(self.user, measured_at=moment, source='manual', rows=rows, token=token)
        bad = [(self.mid1, {'temperature_c': D('8.1')}, ''), (self.mid2, {'temperature_c': D('99')}, '')]
        self.assertEqual(self.refused(services.record_round, self.user, measured_at=moment, source='lab', rows=bad,
                                      token=uuid.uuid4()), {'1-temperature_c': ['Between -3 and 40: check the value.']})
        self.assertEqual(WaterMeasurement.objects.count(), 2)
        self.assertEqual(self.refused(services.record_round, self.user, measured_at=moment, source='lab',
                                      rows=[(self.mid1, {}, '')]), {'__all__': ['Enter at least one value.']})


class VoidTests(WaterTestCase):
    def test_a_void_hides_the_sample_keeps_its_reason_and_it_no_longer_counts_as_latest(self):
        self.sample(hours=3, oxygen_mg_l='9')
        wrong = self.sample(hours=1, oxygen_mg_l='2.1')
        self.assertEqual(self.unit_water().get('oxygen_mg_l').value, D('2.10'))
        self.assertEqual(self.refused(services.void, self.user, wrong, '  '), {'reason': ['Say why it is voided.']})
        services.void(self.user, wrong, 'Probe not calibrated')
        stored = WaterMeasurement.all_objects.get(pk=wrong.pk)
        self.assertEqual((stored.is_deleted, stored.void_reason, stored.deleted_by), (True, 'Probe not calibrated',
                                                                                      self.user))
        self.assertFalse(WaterMeasurement.objects.filter(pk=wrong.pk).exists())
        self.assertEqual(self.unit_water().get('oxygen_mg_l').value, D('9.00'))
        entry = AuditLog.objects.filter(action='void').get()
        self.assertEqual((entry.entity_type, entry.changes), ('water sample',
                                                              {'Reason for voiding': [None, 'Probe not calibrated']}))
        self.assertEqual(self.refused(services.void, self.user, wrong, 'Again'),
                         {'__all__': ['This sample is already voided.']})

    def test_only_within_the_backdating_window(self):
        old = self.sample(hours=24 * 30, ph='7')
        with mock.patch('django.utils.timezone.now', return_value=self.now + timedelta(days=3)):
            self.assertEqual(self.refused(services.void, self.user, old, 'Too late'),
                             {'__all__': ['Samples older than 31 days cannot be voided.']})


class LatestTests(WaterTestCase):
    def latest(self, place=None, now=None):
        point = self.point(place or self.t1)
        return read.latest([point], now=now)[point.pk]

    def test_the_newest_value_of_each_parameter_and_a_newer_sample_without_do_does_not_hide_a_critical_do(self):
        self.stock()
        self.limit('oxygen_mg_l', critical_low=6, warning_low=7)
        self.sample(hours=5, oxygen_mg_l='5.5', temperature_c='9')
        self.sample(hours=1, temperature_c='9.5')          # WQ-04: a temperature-only entry later
        water = self.latest()
        oxygen, temperature = water.get('oxygen_mg_l'), water.get('temperature_c')
        self.assertEqual((oxygen.value, oxygen.status), (D('5.50'), Status.CRITICAL))
        self.assertEqual((temperature.value, temperature.status), (D('9.5'), Status.NO_LIMIT))
        self.assertEqual(water.status, Status.CRITICAL)

    def test_an_empty_unit_shows_its_values_with_no_limit(self):
        self.limit('ph', critical_low=6)
        self.sample(ph='5.5')
        water = self.latest()
        self.assertEqual((water.get('ph').value, water.get('ph').status, water.status),
                         (D('5.50'), Status.NO_LIMIT, Status.NO_LIMIT))

    def test_a_stale_value_is_never_ok_and_the_unit_is_stale_when_nothing_is_fresh(self):
        self.stock()
        self.limit('temperature_c', warning_high=14)
        self.sample(hours=30, temperature_c='9')          # fresh for 24 h
        self.sample(hours=30, ph='7')                     # fresh for 72 h, no limit
        water = self.latest()
        self.assertEqual(water.get('temperature_c').status, Status.STALE)
        self.assertEqual(water.status, Status.STALE)      # a value with a limit aged: never "No limit" over it
        water = self.latest(now=self.now + timedelta(days=3))
        self.assertEqual(water.status, Status.STALE)

    def test_the_limits_follow_the_species_and_the_water_type_and_change_with_them(self):
        self.stock()
        any_water = self.limit('ph', warning_low='6.8')
        self.sample(ph='6.9')
        self.assertEqual(self.latest().get('ph').status, Status.OK)
        self.limit('ph', water_type='freshwater', warning_low='7.0')          # the unit's water type wins
        self.assertEqual(self.latest().get('ph').status, Status.WARNING)
        self.assertEqual(self.latest().get('ph').limits[0].water_type, 'freshwater')
        any_water.soft_delete(self.user)
        WaterLimit.objects.filter(water_type='freshwater').update(warning_low=D('6.5'))     # judged on read
        self.assertEqual(self.latest().get('ph').status, Status.OK)

    def test_a_loop_sample_is_judged_for_every_unit_of_the_loop(self):
        trout = make_species('RBT', 'Rainbow trout', 'Oncorhynchus mykiss', local_name='', saltwater=False)
        self.stock(self.t1)
        self.stock(self.t2, trout)
        self.limit('co2_mg_l', warning_high=15)
        self.limit('co2_mg_l', species=trout, warning_high=10, critical_high=12)
        services.record(self.user, point=self.loop, measured_at=self.ago(hours=1), source='manual',
                        values={'co2_mg_l': D('13')})
        reading = self.latest(self.ras).get('co2_mg_l')
        self.assertEqual((reading.status, {row.species for row in reading.limits}),
                         (Status.CRITICAL, {self.salmon, trout}))


class PointsWaterTests(WaterTestCase):
    """read.points_water: every active point of many units from one latest(), against unit_water for the middle."""

    def setUp(self):
        super().setUp()
        self.t3 = make_unit('T-03', self.hall)                      # no sampling point at all
        self.units = [self.t1, self.t2, self.t3]
        self.drain, self.inlet = point_of(self.t1, 'bottom_drain'), point_of(self.t1, 'inlet')
        self.stock()
        self.limit('oxygen_mg_l', critical_low=6, warning_low=7)
        self.sample(self.t1, hours=2, temperature_c='9', oxygen_mg_l='8')
        self.sample(self.drain, hours=3, temperature_c='9.4', oxygen_mg_l='5')
        self.sample(self.inlet, hours=1, temperature_c='8.8')
        self.sample(self.t2, hours=1, temperature_c='11')
        self.now = timezone.now()

    def test_the_middle_alone_is_unit_water(self):
        found = read.points_water(self.units, self.now, middle_only=[unit.pk for unit in self.units])
        oracle = read.unit_water(self.units, self.now)
        self.assertEqual(found[self.t1.pk], [oracle[self.t1.pk]])
        self.assertEqual(found[self.t2.pk], [oracle[self.t2.pk]])
        self.assertEqual(found[self.t3.pk], [])                    # no middle point: nothing stands in for it
        self.assertEqual(oracle[self.t3.pk].point, None)

    def test_a_detailed_unit_has_every_active_point_the_middle_first_the_others_by_name(self):
        found = read.points_water(self.units, self.now, middle_only=[self.t2.pk])
        names = [water.point.name for water in found[self.t1.pk]]
        self.assertEqual(names[0], self.mid1.name)
        self.assertEqual(names[1:], sorted(names[1:]))
        self.assertEqual(set(names), {point.name for point in SamplingPoint.objects.filter(unit=self.t1)})
        self.assertEqual(found[self.t1.pk][0], read.unit_water([self.t1], self.now)[self.t1.pk])
        by_name = {water.point.name: water for water in found[self.t1.pk]}
        self.assertEqual(by_name[self.drain.name].get('oxygen_mg_l').status, Status.CRITICAL)
        self.assertEqual(by_name[self.inlet.name].get('temperature_c').value, D('8.8'))
        self.assertEqual(len(found[self.t2.pk]), 1)                # narrowed to its middle

    def test_an_inactive_point_is_left_out(self):
        SamplingPoint.objects.filter(pk=self.drain.pk).update(is_active=False)
        found = read.points_water([self.t1], self.now)
        self.assertNotIn(self.drain.name, [water.point.name for water in found[self.t1.pk]])

    def test_the_queries_do_not_grow_with_the_units(self):
        def count(units, narrow):
            with CaptureQueriesContext(connection) as queries:
                read.points_water(units, self.now, middle_only=narrow)
            return len(queries)
        for narrow in (lambda units: [], lambda units: [unit.pk for unit in units]):
            count(self.units, narrow(self.units))
            one = count(self.units[:1], narrow(self.units[:1]))
            self.assertEqual(count(self.units[:2], narrow(self.units[:2])), one)
            self.assertEqual(count(self.units, narrow(self.units)), one)

    def test_the_assumed_salinity_is_one_rule_for_the_calculation_and_the_ammonia(self):
        fresh, sea = Tank.WaterType.FRESHWATER, Tank.WaterType.SALTWATER
        self.assertEqual([read.assumed_salinity(types) for types in ({fresh}, [fresh, fresh], {sea}, {fresh, sea}, ())],
                         [D(0), D(0), None, None, None])
        sample = self.sample(self.t1, hours=1, tan_mg_l='1', ph='7.5', temperature_c='10')
        context = read.Context([self.mid1], self.now - read.WINDOW)
        with mock.patch.object(read, 'assumed_salinity', return_value=D('35')) as rule:
            self.assertEqual(context.salinity_for(sample), D('35'))
        rule.assert_called_once_with({fresh})
        self.assertEqual(context.salinity_for(sample), D(0))


class DerivedTests(WaterTestCase):
    def reading(self, code, point=None):
        point = self.point(point or self.t1)
        return read.latest([point])[point.pk].get(code)

    def test_nh3_from_the_tan_ph_and_temperature_of_the_same_sample(self):
        self.stock()
        self.limit('nh3_n_mg_l', warning_high='0.01', critical_high='0.02')
        self.sample(hours=2, tan_mg_l='2', ph='7.5', temperature_c='12')
        nh3, nh4 = self.reading('nh3_n_mg_l'), self.reading('nh4_n_mg_l')
        expected = D(2) * D(chemistry.nh3_fraction(7.5, 12, 0))          # fresh water: salinity 0
        self.assertEqual((nh3.value, nh3.derived), (expected.quantize(D('0.0001')), True))
        self.assertEqual(nh3.value, D('0.0136'))                          # 0.68 % of 2 mg/L
        self.assertEqual(nh3.status, Status.WARNING)
        self.assertEqual(nh4.value, D('1.986'))
        self.sample(hours=1, tan_mg_l='2', ph='7.5')                      # no temperature in the newer sample
        nh3 = self.reading('nh3_n_mg_l')
        self.assertEqual((nh3.value, nh3.note, nh3.status),
                         (None, 'Needs the pH and the temperature of the same sample.', Status.NOT_MEASURED))

    def test_the_salinity_is_the_samples_else_the_units_latest_else_none_outside_fresh_water(self):
        Tank.objects.filter(pk=self.t1.pk).update(water_type='saltwater')
        self.t1.refresh_from_db()
        self.sample(hours=3, tan_mg_l='1', ph='8', temperature_c='10')
        self.assertEqual(self.reading('nh3_n_mg_l').note,
                         'Needs the salinity: none was recorded here in the 30 days before.')
        self.sample(hours=24 * 5, salinity_ppt='35')
        expected = (D(1) * D(chemistry.nh3_fraction(8, 10, 35))).quantize(D('0.0001'))
        self.assertEqual(self.reading('nh3_n_mg_l').value, expected)

    def test_oxygen_saturation_from_mg_l_at_the_sites_altitude_and_the_other_way_round(self):
        Site.objects.filter(pk=self.bergen.pk).update(altitude=D(500))
        self.t1.refresh_from_db()
        self.sample(hours=2, oxygen_mg_l='10.63', temperature_c='10')
        saturation = self.reading('oxygen_saturation_pct')
        self.assertEqual((saturation.value, saturation.derived, saturation.note), (D('100.0'), True, ''))
        self.sample(hours=1, oxygen_saturation_pct='80', temperature_c='20', salinity_ppt='0')
        mg_l = self.reading('oxygen_mg_l')
        self.assertEqual((mg_l.value, mg_l.derived), ((D(80) * D(chemistry.oxygen_solubility(
            20, 0, chemistry.pressure_atm(500))) / 100).quantize(D('0.01')), True))
        Site.objects.filter(pk=self.bergen.pk).update(altitude=None)
        self.t1.refresh_from_db()
        self.assertEqual(self.reading('oxygen_mg_l').note, 'At sea-level pressure: the site has no altitude.')

    def test_two_oxygen_values_that_disagree_are_kept_and_flagged(self):
        self.sample(oxygen_mg_l='11.3', oxygen_saturation_pct='70', temperature_c='10')
        reading = self.reading('oxygen_mg_l')
        self.assertEqual((reading.value, reading.derived), (D('11.30'), False))
        self.assertIn('disagree by more than 10 %', reading.note)
        self.sample(oxygen_mg_l='11.3', oxygen_saturation_pct='100', temperature_c='10')
        self.assertEqual(self.reading('oxygen_mg_l').note, '')

    def test_the_history_judges_each_sample_for_the_fish_of_its_day(self):
        self.limit('temperature_c', warning_high=12)
        before = self.sample(hours=24 * 15, temperature_c='14')            # before the fish came: no limit
        self.stock()                                                       # stocked 10 days ago
        during = self.sample(hours=24 * 2, temperature_c='14')
        rows = {row.sample.pk: row for row in read.history([during, before])}
        self.assertEqual(rows[before.pk].readings['temperature_c'].status, Status.NO_LIMIT)
        self.assertEqual(rows[during.pk].readings['temperature_c'].status, Status.WARNING)


class LimitTests(WaterTestCase):
    url = reverse('farm:waterlimit_create')

    def data(self, **fields):
        values = {'species': str(self.salmon.pk), 'parameter': 'oxygen_saturation_pct', 'water_type': 'any',
                  'critical_low': '60', 'warning_low': '80', 'warning_high': '', 'critical_high': '',
                  'reference': 'Vet, 2026-11'}
        values.update(fields)
        return values

    def test_create_read_edit_delete_through_the_pages(self):
        response = self.client.post(self.url, self.data())
        self.assertEqual(response.status_code, 302)
        limit = WaterLimit.objects.get()
        self.assertEqual((limit.species, limit.parameter, limit.water_type, limit.critical_low, limit.warning_low,
                          limit.warning_high, limit.reference, limit.created_by),
                         (self.salmon, 'oxygen_saturation_pct', 'any', D('60.0000'), D('80.0000'), None, 'Vet, 2026-11',
                          self.user))
        page = self.client.get(reverse('farm:waterlimit_list'))
        for text in ('Atlantic salmon', 'Oxygen saturation (% of air saturation)', 'Any water', '60.0', '80.0',
                     'Vet, 2026-11', '<h1>Water limits</h1>'):
            self.assertContains(page, text, html=text.startswith('<'))
        form = self.client.get(reverse('farm:waterlimit_edit', args=[limit.pk])).context['form']
        self.assertEqual(form['warning_low'].value(), D('80.0000'))
        self.client.post(reverse('farm:waterlimit_edit', args=[limit.pk]),
                         self.data(warning_low='', warning_high='110', water_type='saltwater', version='1'))
        limit.refresh_from_db()
        self.assertEqual((limit.warning_low, limit.warning_high, limit.water_type, limit.version),
                         (None, D('110.0000'), 'saltwater', 2))
        self.client.post(reverse('farm:waterlimit_delete', args=[limit.pk]))
        self.assertTrue(WaterLimit.all_objects.get().is_deleted)
        self.assertEqual(list(AuditLog.objects.order_by('created_at').values_list('action', 'entity_type')),
                         [('create', 'water limit'), ('update', 'water limit'), ('delete', 'water limit')])

    def test_the_bounds_go_up_inside_the_parameters_range_at_its_precision(self):
        ORDER = 'The bounds go up: critical below ≤ warning below ≤ warning above ≤ critical above.'
        cases = [
            ({'critical_low': '85'}, 'warning_low', ORDER),
            ({'warning_high': '70'}, 'warning_high', ORDER),
            ({'critical_low': '500'}, 'critical_low', 'Between 0 and 400 for this parameter.'),
            ({'parameter': 'ph', 'critical_low': '6.123', 'warning_low': ''}, 'critical_low',
             'At most 2 decimals for this parameter.'),
        ]
        for fields, field, error in cases:
            with self.subTest(fields=fields):
                response = self.client.post(self.url, self.data(**fields))
                self.assertEqual(response.context['form'].errors[field], [error])
        response = self.client.post(self.url, self.data(critical_low='', warning_low=''))
        self.assertIn('Give at least one bound.', response.context['form'].non_field_errors())
        self.assertFalse(WaterLimit.objects.exists())

    def test_the_database_holds_the_same_rules(self):
        base = {'species': self.salmon, 'parameter': 'ph'}
        cases = [({'critical_low': D(7), 'warning_low': D(6)}, 'chk_water_limits_order'),
                 ({'warning_low': D(6), 'critical_high': D(5)}, 'chk_water_limits_order'),
                 ({'critical_low': D(13)}, 'chk_water_limits_critical_low'),
                 ({'warning_high': D('7.125')}, 'chk_water_limits_warning_high'),
                 ({}, 'chk_water_limits_any_bound'),
                 ({'critical_low': D(6), 'water_type': 'lake'}, 'chk_water_limits_water_type')]
        for values, name in cases:
            with self.subTest(name=name), self.assertRaisesMessage(IntegrityError, name), transaction.atomic():
                WaterLimit.objects.create(**{**base, **values})
        with self.assertRaises(IntegrityError), transaction.atomic():     # NH₄-N takes no limit: no bound fits it
            WaterLimit.objects.create(**{**base, 'parameter': 'nh4_n_mg_l', 'critical_low': D(6)})
        WaterLimit.objects.create(**base, critical_low=D(6))
        with self.assertRaisesMessage(IntegrityError, 'uq_water_limits_live'), transaction.atomic():
            WaterLimit.objects.create(**base, critical_low=D(5))
        WaterLimit.objects.create(**base, water_type='saltwater', critical_low=D('7.5'))

    def test_one_live_row_per_species_parameter_and_water_type_on_the_form(self):
        self.client.post(self.url, self.data())
        response = self.client.post(self.url, self.data(critical_low='50'))
        self.assertEqual(response.context['form'].errors['water_type'],
                         ['This species already has limits for this parameter and water type.'])
        self.assertEqual(self.client.post(self.url, self.data(water_type='saltwater')).status_code, 302)
        WaterLimit.objects.get(water_type='any').soft_delete(self.user)
        self.assertEqual(self.client.post(self.url, self.data()).status_code, 302)       # a deleted row frees it

    def test_the_form_says_the_unit_of_the_parameter_chosen(self):
        response = self.client.post(self.url, {**self.data(parameter='tan_mg_l'), '_draft': 'parameter'})
        self.assertContains(response, 'Total ammonia nitrogen (mg/L TAN as N): bounds from 0 to 100, at most 3 '
                                      'decimals.')
        self.assertFalse(WaterLimit.objects.exists())

    def test_list_filters_by_species_and_parameter(self):
        trout = make_species('RBT', 'Rainbow trout', 'Oncorhynchus mykiss', local_name='', saltwater=False)
        self.limit('ph', critical_low=6)
        self.limit('ph', species=trout, critical_low='6.5')
        self.limit('co2_mg_l', warning_high=10)
        names = lambda **query: [(str(limit.species.code), limit.parameter) for limit in 
                                 self.client.get(reverse('farm:waterlimit_list'), query).context['objects']]
        self.assertEqual(names(), [('SAL', 'co2_mg_l'), ('SAL', 'ph'), ('RBT', 'ph')])
        self.assertEqual(names(species=trout.pk), [('RBT', 'ph')])
        self.assertEqual(names(parameter='co2_mg_l'), [('SAL', 'co2_mg_l')])

    def test_a_species_takes_its_limits_with_it(self):
        limit = self.limit('ph', critical_low=6)
        page = self.client.get(reverse('farm:species_delete', args=[self.salmon.pk]))
        self.assertContains(page, 'Water limits deleted with it')
        self.assertContains(page, str(limit))
        self.client.post(reverse('farm:species_delete', args=[self.salmon.pk]))
        self.assertTrue(WaterLimit.all_objects.get().is_deleted)
        self.assertIn(('delete', 'water limit'), list(AuditLog.objects.values_list('action', 'entity_type')))


class DeletePlanTests(WaterTestCase):
    def test_a_unit_or_system_keeps_its_points_and_their_samples_out_of_sight_and_brings_them_back(self):
        self.sample(point=self.t2, ph='7')
        self.sample(point=self.t2, hours=2, ph='7.1')
        loop = self.sample(point=self.ras, co2_mg_l='9')
        plan = plan_delete(self.t2)
        self.assertEqual((plan.can_delete, plan.cascade, plan.kept_groups()),
                         (True, [], [{'label': 'Sampling points', 'count': 4, 'note': SamplingPoint.kept_note},
                                     {'label': 'Water samples', 'count': 2, 'note': WaterMeasurement.kept_note}]))
        page = self.client.get(reverse('farm:tank_delete', args=[self.t2.pk]))
        self.assertContains(page, 'Sampling points kept with it <span class="count">4</span>', html=True)
        self.assertContains(page, 'Water samples kept with it <span class="count">2</span>', html=True)
        self.client.post(reverse('farm:tank_delete', args=[self.t2.pk]))
        self.assertEqual(WaterMeasurement.objects.filter(point__unit=self.t2).count(), 0)
        self.assertEqual(SamplingPoint.objects.filter(unit=self.t2).count(), 0)
        self.assertEqual(WaterMeasurement.all_objects.filter(point__unit=self.t2, is_deleted=False).count(), 2)
        self.assertEqual(SamplingPoint.all_objects.filter(unit=self.t2, is_deleted=False).count(), 4)
        self.assertFalse(AuditLog.objects.filter(entity_type='water sample', action='delete').exists())
        self.assertFalse(AuditLog.objects.filter(entity_type='sampling point', action='delete').exists())
        restore(Tank.all_objects.get(pk=self.t2.pk), self.user)
        self.assertEqual(WaterMeasurement.objects.filter(point__unit=self.t2).count(), 2)
        self.assertEqual(SamplingPoint.objects.filter(unit=self.t2).count(), 4)
        # A system's loop samples, and those of its units, the same way.
        self.ras.soft_delete(self.user)
        self.assertEqual(list(WaterMeasurement.objects.filter(point__system=self.ras)), [])
        self.ras.is_deleted = False
        self.ras.save()
        self.assertEqual(list(WaterMeasurement.objects.filter(point__system=self.ras)), [loop])


# ---- the pages -------------------------------------------------------------------------------------------
class PageTests(WaterTestCase):
    url = reverse('farm:water')

    def post(self, url, data):
        return self.client.post(url, data, headers={'X-Modal': '1'})

    def record_data(self, **values):
        local = timezone.localtime(self.ago(hours=1)).strftime('%Y-%m-%dT%H:%M')
        data = {'token': str(uuid.uuid4()), 'point': str(self.mid1.pk), 'measured_at': local, 'source': 'manual',
                'notes': '', **{code: '' for code in parameters.COLUMNS}}
        data.update(values)
        return data

    def test_the_latest_values_with_their_status(self):
        self.stock()
        self.limit('oxygen_mg_l', critical_low=6, warning_low=7)
        self.sample(hours=2, oxygen_mg_l='6.5', temperature_c='9.5')
        response = self.client.get(self.url)
        rows = {row['owner'].code: row for row in response.context['rows']}
        self.assertEqual(set(rows), {'T-01', 'T-02'})            # every unit; a loop once it has a sample
        self.assertEqual((rows['T-01']['water'].status, rows['T-02']['water'].status),
                         (Status.WARNING, Status.NOT_MEASURED))
        self.assertEqual([str(parameter.short) for parameter in response.context['columns']],
                         ['Temp. (°C)', 'O₂ (mg/L)', 'O₂ (%)'])
        html = response.content.decode()
        for text in ('6.50', '9.5', 'wq-warning', '2 sampling points', '1 warning', 'Nobody is alerted'):
            self.assertIn(text, html)
        self.assertContains(response, '<h1>Water chemistry</h1>', html=True)

    def test_the_history_with_its_filters(self):
        self.stock()
        self.limit('ph', critical_low=6)
        self.sample(point=self.t1, hours=24 * 3, ph='5.8', notes='After the storm')
        self.sample(point=self.t2, hours=1, ph='7.2')
        self.sample(point=self.ras, hours=2, co2_mg_l='8')
        history = lambda **query: [row.sample.point.owner.code for row in
                                   self.client.get(self.url, {'view': 'history', **query}).context['history']]
        self.assertEqual(history(), ['T-02', 'R1', 'T-01'])
        self.assertEqual(history(unit=self.t1.pk), ['T-01'])
        self.assertEqual(history(system=self.ras.pk), ['R1'])
        self.assertEqual(history(alerts='1'), ['T-01'])
        today = timezone.localdate()
        self.assertEqual(history(**{'from': (today - timedelta(days=1)).isoformat()}), ['T-02', 'R1'])
        self.assertEqual(history(to=(today - timedelta(days=2)).isoformat()), ['T-01'])
        page = self.client.get(self.url, {'unit': self.t1.pk})
        self.assertContains(page, 'History of T-01')
        self.assertContains(page, 'After the storm')
        self.assertContains(page, 'wq-row-critical')

    def test_a_voided_sample_stays_in_the_history_struck_through(self):
        wrong = self.sample(ph='4')
        services.void(self.user, wrong, 'Typed 4 for 7.4')
        response = self.client.get(self.url, {'unit': self.t1.pk})
        self.assertContains(response, 'is-voided')
        self.assertContains(response, 'voided by ali: Typed 4 for 7.4')
        self.assertNotContains(response, '>Void</a>')

    def test_record_a_sample_from_a_units_history_with_the_limits_in_the_help(self):
        self.stock()
        self.limit('oxygen_saturation_pct', critical_low=60, warning_low=80, warning_high=110)
        url = f'{reverse("farm:water_record")}?unit={self.t1.pk}&next=/operations/water/?unit={self.t1.pk}'
        form = self.client.get(url, headers={'X-Modal': '1'})
        self.assertContains(form, 'class="modal-head"')
        self.assertContains(form, 'Atlantic salmon: critical below 60.0, warning below 80.0, warning above 110.0')
        self.assertContains(form, 'Nitrite (mg/L NO₂ as N)')
        self.assertContains(form, 'A kit that reads NO₂⁻: divide by 3.29.')
        response = self.post(url, self.record_data(temperature_c='8.5', oxygen_mg_l='10.2', notes='Morning'))
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response['X-Modal-Redirect'], f'/operations/water/?unit={self.t1.pk}')
        sample = WaterMeasurement.objects.get()
        self.assertEqual((sample.point, sample.temperature_c, sample.oxygen_mg_l, sample.notes),
                         (self.mid1, D('8.5'), D('10.20'), 'Morning'))

    def test_the_time_is_read_on_the_sites_clock(self):
        Site.objects.filter(pk=self.bergen.pk).update(timezone='Europe/Oslo')
        oslo = timezone.localtime(self.ago(hours=1), ZoneInfo('Europe/Oslo'))
        self.post(reverse('farm:water_record'), self.record_data(measured_at=oslo.strftime('%Y-%m-%dT%H:%M'), ph='7'))
        self.assertEqual(WaterMeasurement.objects.get().measured_at, self.ago(hours=1).replace(second=0))

    def test_the_time_starts_now_on_the_sites_clock(self):
        Site.objects.filter(pk=self.bergen.pk).update(timezone='Asia/Tokyo')
        tokyo = timezone.localtime(timezone.now(), ZoneInfo('Asia/Tokyo')).replace(tzinfo=None)
        for url in (reverse('farm:water_record'), f'{reverse("farm:water_record")}?unit={self.t1.pk}',
                    f'{reverse("farm:water_round")}?site={self.bergen.pk}'):
            response = self.client.get(url)
            form = response.context.get('form') or response.context['header']
            self.assertLess(abs(tokyo - form['measured_at'].value()), timedelta(minutes=2), url)

    def test_the_servers_reasons_are_on_the_fields_and_the_form_is_refused(self):
        url = reverse('farm:water_record')
        response = self.post(url, self.record_data())
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.context['form'].non_field_errors(), ['Enter at least one value.'])
        response = self.post(url, self.record_data(ph='25', oxygen_mg_l='7.123'))
        self.assertEqual(response.context['form'].errors['ph'], ['Ensure this value is less than or equal to 12.'])
        self.assertEqual(response.context['form'].errors['oxygen_mg_l'],
                         ['Ensure that there are no more than 2 decimal places.'])
        future = timezone.localtime(self.now + timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M')
        response = self.post(url, self.record_data(measured_at=future, ph='7'))
        self.assertEqual(response.context['form'].errors['measured_at'], ['The time cannot be in the future.'])
        response = self.post(url, self.record_data(point='', ph='7'))
        self.assertIn('point', response.context['form'].errors)
        self.assertFalse(WaterMeasurement.all_objects.exists())

    def test_a_form_sent_twice_records_once(self):
        data = self.record_data(ph='7')
        self.post(reverse('farm:water_record'), data)
        self.assertEqual(self.post(reverse('farm:water_record'), data).status_code, 204)
        self.assertEqual(WaterMeasurement.objects.count(), 1)

    def test_a_round_through_its_page(self):
        url = f'{reverse("farm:water_round")}?site={self.bergen.pk}&columns=temperature_c&columns=ph'
        page = self.client.get(url)
        self.assertEqual([row.point.owner.code for row in page.context['rows']], ['T-01', 'T-02', 'R1'])
        local = timezone.localtime(self.ago(hours=1)).strftime('%Y-%m-%dT%H:%M')
        data = {'token': str(uuid.uuid4()), 'measured_at': local, 'source': 'lab',
                f'point-{self.mid1.pk}-temperature_c': '8.1', f'point-{self.mid1.pk}-ph': '',
                f'point-{self.mid2.pk}-temperature_c': '', f'point-{self.mid2.pk}-ph': '',
                f'point-{self.loop.pk}-temperature_c': '', f'point-{self.loop.pk}-ph': '7.4',
                f'point-{self.loop.pk}-notes': 'Sump'}
        response = self.client.post(url, {**data, f'point-{self.mid2.pk}-ph': '15'})
        self.assertEqual(response.status_code, 422)
        self.assertIn('ph', response.context['rows'][1].errors)
        self.assertFalse(WaterMeasurement.objects.exists())                 # one bad cell refuses all
        response = self.client.post(url, data)
        self.assertRedirects(response, f'{self.url}?site={self.bergen.pk}', fetch_redirect_response=False)
        stored = WaterMeasurement.objects.values_list('point__unit__code', 'point__system__code', 'point__kind',
                                                      'temperature_c', 'ph', 'source', 'notes')
        self.assertEqual(sorted(stored, key=str), sorted([('T-01', None, 'middle', D('8.1'), None, 'lab', ''),
                                                          (None, 'R1', 'middle', None, D('7.40'), 'lab', 'Sump')],
                                                         key=str))
        self.assertEqual(self.client.post(url, data).status_code, 302)      # sent twice: recorded once
        self.assertEqual(WaterMeasurement.objects.count(), 2)

    def test_a_round_by_department_or_system_and_without_inactive_units(self):
        Tank.objects.filter(pk=self.t2.pk).update(status=Tank.Status.INACTIVE)
        other = ProductionDepartment.objects.create(site=self.bergen, name='Hall B', code='HB')
        point_of(make_unit('T-09', other))
        rows = lambda **query: [row.point.owner.code for row in self.client.get(
            reverse('farm:water_round'), {'site': self.bergen.pk, **query}).context['rows']]
        self.assertEqual(rows(), ['T-01', 'T-09', 'R1'])
        self.assertEqual(rows(production_department=other.pk), ['T-09'])
        self.assertEqual(rows(system=self.ras.pk), ['T-01', 'R1'])
        self.assertEqual(self.client.get(reverse('farm:water_round')).context['rows'], [])

    def test_void_through_its_dialog(self):
        sample = self.sample(ph='4')
        listing = self.client.get(self.url, {'unit': self.t1.pk})
        void_url = listing.context['history'][0].void_url
        self.assertTrue(void_url.startswith(reverse('farm:water_void', args=[sample.pk])))
        self.assertContains(self.client.get(void_url), 'Void the sample of T-01')
        self.assertEqual(self.post(void_url, {'reason': ''}).status_code, 422)
        response = self.post(void_url, {'reason': 'Wrong unit'})
        self.assertEqual(response['X-Modal-Redirect'], f'/operations/water/?unit={self.t1.pk}')
        self.assertEqual(WaterMeasurement.all_objects.get().void_reason, 'Wrong unit')
        self.assertEqual(self.client.get(void_url).status_code, 404)

    def test_every_dialog_opens_as_a_page_too_and_the_menu_marks_water_chemistry(self):
        sample = self.sample(ph='7')
        for url in (reverse('farm:water_record'), f'{reverse("farm:water_record")}?system={self.ras.pk}',
                    reverse('farm:water_round'), reverse('farm:water_void', args=[sample.pk]), self.url):
            response = self.client.get(url)
            self.assertContains(response, 'id="rail"', msg_prefix=url)
            self.assertContains(response, f'href="{self.url}" title="Water chemistry" aria-current="page"',
                                msg_prefix=url)

    def test_the_page_speaks_each_language(self):
        self.stock()
        self.sample(oxygen_mg_l='9.25', ph='7.1')
        for language, words in {'tr': ('Su kimyası', 'Çözünmüş oksijen (mg/L O₂)', '9,25'),
                                'nb': ('Vannkjemi', 'Løst oksygen (mg/L O₂)', '9,25')}.items():
            Profile.objects.update_or_create(user=self.user, defaults={'language': language})
            self.assertContains(self.client.get(self.url), words[0], msg_prefix=language)
            self.assertContains(self.client.get(self.url), words[2], msg_prefix=language)
            self.assertContains(self.client.get(f'{reverse("farm:water_record")}?unit={self.t1.pk}'), words[1],
                                msg_prefix=language)


class PermissionTests(WaterTestCase):
    def as_role(self, *codenames):
        person = get_user_model().objects.create_user(f'p{len(codenames)}', f'p{len(codenames)}@example.com')
        person.groups.add(role(f'Role {len(codenames)}', *codenames))
        self.client.force_login(person)

    def test_read_record_and_void_are_separate(self):
        sample = self.sample(ph='7')
        record, round_, void = (reverse('farm:water_record'), reverse('farm:water_round'),
                                reverse('farm:water_void', args=[sample.pk]))
        self.as_role('view_watermeasurement')
        page = self.client.get(reverse('farm:water'), {'unit': self.t1.pk})
        self.assertEqual(page.status_code, 200)
        for text in ('Record sample', '>Void</a>', round_):
            self.assertNotContains(page, text)
        for url in (record, round_, void):
            self.assertEqual(self.client.post(url, {}).status_code, 403, url)
        self.as_role('view_watermeasurement', 'add_watermeasurement')
        page = self.client.get(reverse('farm:water'), {'unit': self.t1.pk})
        self.assertContains(page, 'Record sample')
        self.assertNotContains(page, '>Void</a>')
        self.assertEqual(self.client.post(void, {'reason': 'x'}).status_code, 403)
        self.assertEqual(self.client.get(record).status_code, 200)
        self.assertFalse(WaterMeasurement.all_objects.filter(is_deleted=True).exists())

    def test_no_read_no_page_and_no_menu_entry(self):
        self.as_role('view_tank')
        self.assertEqual(self.client.get(reverse('farm:water')).status_code, 403)
        home = self.client.get(reverse('production_home'))
        self.assertNotContains(home, reverse('farm:water'))
        self.assertNotContains(home, reverse('farm:waterlimit_list'))

    def test_the_menu_and_the_role_matrix_place_them(self):
        response = self.client.get(reverse('farm:water'))
        self.assertContains(response, reverse('farm:waterlimit_list'))
        self.assertEqual(str(navigation.place('farm.view_watermeasurement').path), 'Production · Operations')
        self.assertEqual(str(navigation.place('farm.view_waterlimit').path), 'Production · Setup · Reference data')
        areas = {area.model: area for area in access.areas()}
        self.assertEqual((str(areas['farm.WaterMeasurement'].label), areas['farm.WaterMeasurement'].actions),
                         ('Water chemistry', ('view', 'add', 'delete')))
        self.assertEqual((str(areas['farm.WaterLimit'].label), areas['farm.WaterLimit'].actions),
                         ('Water limits', ('view', 'add', 'change', 'delete')))


class ProductionUnitsTests(WaterTestCase):
    """The water on Operations › Production units: the Temp. and O₂ columns, the status dot, the count of
    critical units, the drawer's Water section and the overview's tile."""

    url = reverse('farm:production_units')

    def as_role(self, *codenames):
        person = get_user_model().objects.create_user(f'p{len(codenames)}', f'p{len(codenames)}@example.com')
        person.groups.add(role(f'Role {len(codenames)}', *codenames))
        self.client.force_login(person)

    def test_the_columns_the_status_dot_and_the_count_of_critical_units(self):
        self.stock()
        self.limit('oxygen_mg_l', critical_low=6, warning_low=7)
        self.sample(hours=2, temperature_c='9.5', oxygen_mg_l='5.2')
        self.sample(point=self.t2, hours=30, temperature_c='12')              # older than its 24 h: stale
        response = self.client.get(self.url)
        rows = {row['unit'].code: row for row in response.context['rows']}
        self.assertEqual((rows['T-01']['water'].status, rows['T-02']['water'].status),
                         (Status.CRITICAL, Status.STALE))
        self.assertEqual(response.context['water_critical'], 1)
        html = response.content.decode()
        for text in ('<th scope="col" class="num">Temp. (°C)</th>', '<th scope="col" class="num">O₂ (mg/L)</th>',
                     '>9.5</td>', '>5.20</td>', '>12.0</td>', 'wq-stale', '<span class="sr-only">Critical</span>',
                     '<strong class="over-text">1 critical</strong>'):
            self.assertIn(text, html)
        self.assertEqual(html.count('class="num wq wq-critical'), 1)

    def test_the_drawers_water_section(self):
        self.stock()
        self.limit('oxygen_saturation_pct', critical_low=60, warning_low=80)
        self.sample(hours=2, temperature_c='10', oxygen_mg_l='8.5', tan_mg_l='1', ph='7.5')
        response = self.client.get(self.url, {'unit': self.t1.pk})
        readings = {reading.code: reading for reading in response.context['water_readings']}
        self.assertEqual(list(readings), ['temperature_c', 'oxygen_mg_l', 'oxygen_saturation_pct', 'ph', 'tan_mg_l',
                                          'nh3_n_mg_l', 'nh4_n_mg_l'])
        self.assertEqual((readings['oxygen_saturation_pct'].value, readings['oxygen_saturation_pct'].status),
                         (D('75.3'), Status.WARNING))                         # 8.5 / 11.288 mg/L at 10 °C
        html = response.content.decode()
        for text in ('Atlantic salmon: critical below 60.0, warning below 80.0', 'Record water sample',
                     f'href="/operations/water/?unit={self.t1.pk}"', 'Un-ionised ammonia (mg/L NH₃ as N)'):
            self.assertIn(text, html)
        record = response.context['water_record_url']
        self.assertTrue(record.startswith(f'{reverse("farm:water_record")}?next='))
        self.assertIn(f'unit={self.t1.pk}', record)
        response = self.client.get(self.url, {'unit': self.t2.pk})
        self.assertContains(response, 'No water sample in the last 30 days.')

    def test_a_sample_recorded_from_the_drawer_goes_back_to_it(self):
        self.stock()
        record = self.client.get(self.url, {'unit': self.t1.pk}).context['water_record_url']
        local = timezone.localtime(self.ago(hours=1)).strftime('%Y-%m-%dT%H:%M')
        data = {'token': str(uuid.uuid4()), 'point': str(self.mid1.pk), 'measured_at': local, 'source': 'manual',
                'notes': '', **{code: '' for code in parameters.COLUMNS}, 'temperature_c': '9'}
        response = self.client.post(record, data, headers={'X-Modal': '1'})
        self.assertEqual(response['X-Modal-Redirect'], f'{self.url}?unit={self.t1.pk}')
        self.assertContains(self.client.get(self.url, {'unit': self.t1.pk}), '>9.0</td>')

    def test_read_shows_the_water_and_create_records_it(self):
        self.sample(temperature_c='9')
        self.as_role('view_stockoperation')
        response = self.client.get(self.url, {'unit': self.t1.pk})
        self.assertNotContains(response, 'Temp. (°C)')
        self.assertNotIn('water_readings', response.context)
        self.assertEqual(self.client.get(reverse('production_home')).context['water_tiles'], [])
        self.as_role('view_stockoperation', 'view_watermeasurement')
        response = self.client.get(self.url, {'unit': self.t1.pk})
        self.assertContains(response, 'Temp. (°C)')
        self.assertContains(response, '<h3>Water ', count=1)
        self.assertNotContains(response, 'Record water sample')

    def test_the_overview_counts_the_units_with_a_critical_water_value(self):
        self.stock()
        self.limit('temperature_c', critical_high=16)
        self.sample(temperature_c='18')
        tiles = self.client.get(reverse('production_home')).context['water_tiles']
        self.assertEqual([(str(tile['label']), tile['count'], tile['url']) for tile in tiles],
                         [('Sampling points with a critical water value', 1, reverse('farm:water'))])

    def test_the_overview_counts_what_the_water_page_counts_critical(self):
        """One count: the overview's figure is the water page's (every point it lists, a side outlet too), not a second
        reading of the middle points only."""
        self.stock()
        self.limit('co2_mg_l', critical_high=15)
        side = SamplingPoint.objects.create(unit=self.t1, name='East side outlet', kind='side_outlet')
        self.sample(co2_mg_l='8')                                      # the middle point is fine
        self.sample(point=side, co2_mg_l='15.6')                       # the side outlet is critical
        page = self.client.get(reverse('farm:water'))
        self.assertEqual(page.context['critical_count'], 1)
        tiles = self.client.get(reverse('production_home')).context['water_tiles']
        self.assertEqual([(str(tile['label']), tile['count']) for tile in tiles],
                         [('Sampling points with a critical water value', 1)])

    def test_an_old_critical_value_keeps_its_point_critical_with_no_recent_data_and_no_limit_says_why(self):
        """A point's status is the worst of its values. A critical value that grew old still counts: the point is
        "Critical, no recent data", never hidden by a fresh OK of another parameter, never "No limit" (HA-K02's side outlet,
        CO₂ 15.6 three days old). A value without a limit says why: no limit for the fish, or no fish that day."""
        self.stock()
        self.limit('co2_mg_l', critical_high=15)
        self.limit('ph', critical_low=6)
        side = SamplingPoint.objects.create(unit=self.t1, name='East side outlet', kind='side_outlet')
        self.sample(point=side, hours=80, co2_mg_l='15.6', alkalinity_mg_l='90')   # older than CO₂'s 72 fresh hours
        self.sample(point=side, hours=1, ph='7.2')                                  # a fresh OK of another parameter
        page = self.client.get(reverse('farm:water'))
        row = next(row for row in page.context['rows'] if row['point'] == side)
        co2 = row['water'].get('co2_mg_l')
        self.assertEqual((co2.status, co2.judged), (Status.STALE, Status.CRITICAL))
        self.assertEqual((row['water'].status, row['water'].old_alert), (Status.CRITICAL, True))
        self.assertContains(page, 'Critical, no recent data')
        self.assertEqual(page.context['critical_count'], 1)
        alkalinity = row['water'].get('alkalinity_mg_l')
        self.assertEqual(alkalinity.status, Status.NO_LIMIT)
        self.assertEqual(alkalinity.why_no_limit, 'No water limit is set for the fish in the unit.')
        self.sample(point=point_of(self.t2), alkalinity_mg_l='90')                # T-02 holds no fish
        empty = read.unit_water([self.t2])[self.t2.pk]
        self.assertEqual(empty.status, Status.NO_LIMIT)
        self.assertEqual(empty.why_no_limit, 'No fish in the unit: nothing to judge the water against.')
        # The water page says it under the point's status.
        self.assertContains(self.client.get(reverse('farm:water')), 'No fish in the unit: nothing to judge the water against.')

    def test_the_drawer_speaks_each_language(self):
        self.stock()
        self.sample(oxygen_mg_l='9.25', temperature_c='10')
        for language, words in {'tr': ('Su', 'Su numunesi kaydet', '9,25'),
                                'nb': ('Vann', 'Registrer vannprøve', '9,25')}.items():
            Profile.objects.update_or_create(user=self.user, defaults={'language': language})
            response = self.client.get(self.url, {'unit': self.t1.pk})
            for word in words:
                self.assertContains(response, word, msg_prefix=language)


class DatabaseViewerTests(TestCase):
    def test_the_water_tables_are_shown_with_their_descriptions_and_checks(self):
        tables = {table.name: table for _, tables in database.sections() for table in tables}
        self.assertTrue(tables['water_measurements'].description.startswith('A water sample: what a person measured'))
        self.assertTrue(tables['water_limits'].description.startswith('The water a species is kept in'))
        structure = tables['water_measurements'].structure()
        constraints = {constraint.name: constraint for constraint in structure.constraints}
        self.assertEqual(constraints['water_measurements_pkey'].definition, 'PRIMARY KEY (id, measured_at)')
        self.assertTrue({'chk_water_measurements_ph', 'uq_water_measurements_entry'} <= set(constraints))
        self.assertNotIn('chk_water_measurements_one_point', constraints)      # a sample has one point: a required key
        admin = get_user_model().objects.create_superuser('root', 'root@example.com', 'x')
        self.client.force_login(admin)
        for table in ('water_measurements', 'water_limits'):
            self.assertEqual(self.client.get(reverse('core:database_table', args=[table])).status_code, 200)

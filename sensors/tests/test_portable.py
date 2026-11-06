"""Portable sensors: a probe (a device with several channels) is taken from one tank or system to another, maybe at
another site, or out of the water. `bindings.move_device` moves every channel of the device from one moment, in one
transaction, with one entry on the device's log, each channel to the place its kind goes to at the target (a water value
to the unit's middle point, the point chosen or the system; a process value to the system or the piece of equipment),
and refuses the whole move, saying why for each channel, when one cannot go there. `bindings.unbind_device` takes it out:
its readings are stored and belong nowhere until it is placed again."""
from datetime import datetime, timedelta, timezone as tz
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection
from django.urls import reverse
from django.utils import timezone

from core.models import AuditLog
from farm.models import Equipment, EquipmentType, ProductionDepartment, Site, System
from farm.models.site import zone_of
from farm.tests.helpers import point_of, role
from farm.tests.test_stock import make_unit
from farm.water import read as water_read, sources

from sensors import bindings, read
from sensors.models import Binding, Channel, ChannelState, Device

from . import SensorsCase, make_channel, make_device, rows as rows_of


class PortableCase(SensorsCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.ras = System.objects.create(name='RAS 1', code='R1', site=cls.site, production_department=cls.hall)
        cls.t1 = make_unit('T-01', cls.hall, system=cls.ras)
        cls.t2 = make_unit('T-02', cls.hall, system=cls.ras)
        cls.mid1, cls.mid2, cls.loop = point_of(cls.t1), point_of(cls.t2), point_of(cls.ras)
        cls.temp = cls.channel                                         # the probe's temperature
        cls.ph = make_channel(cls.device, 'ph')
        cls.oxygen = make_channel(cls.device, 'oxygen_mg_l')
        cls.start = timezone.now().replace(microsecond=0) - timedelta(days=10)

    def open_places(self, device=None):
        """{channel code: target} of the device's open bindings."""
        return {binding.channel.code: binding.target for binding in Binding.objects.filter(
            channel__device=device or self.device, valid_to__isnull=True).select_related('channel')}

    def device_entries(self, device=None):
        return AuditLog.objects.filter(entity_id=str((device or self.device).pk), action='update')


class MoveDeviceTests(PortableCase):
    def test_every_channel_moves_from_one_moment_with_one_entry_on_the_device(self):
        bindings.move_device(self.user, self.device, self.start, self.t1)
        moved_at = self.start + timedelta(days=2)
        bindings.move_device(self.user, self.device, moved_at, self.t2, note='after the grading')
        self.assertEqual(self.open_places(), {'TEMPERATURE-C': self.mid2, 'PH': self.mid2, 'OXYGEN-MG-L': self.mid2})
        for channel in (self.temp, self.ph, self.oxygen):
            first, second = Binding.objects.filter(channel=channel).order_by('valid_from')
            self.assertEqual((first.point, first.valid_to, second.point, second.valid_from, second.note),
                             (self.mid1, moved_at, self.mid2, moved_at, 'after the grading'))
        entries = self.device_entries()
        self.assertEqual(entries.count(), 2)
        changes = next(entry.changes for entry in entries if 'T-02' in str(entry.changes))
        self.assertEqual(changes['Bound to (PH)'], ['T-01 › Middle (Primary)', 'T-02 › Middle (Primary)'])
        self.assertEqual(set(changes), {'Bound to (TEMPERATURE-C)', 'Bound to (PH)', 'Bound to (OXYGEN-MG-L)'})

    def test_each_channels_own_log_says_where_it_went_too(self):
        bindings.move_device(self.user, self.device, self.start, self.t1)
        entry = AuditLog.objects.get(entity_id=str(self.ph.pk), action='update')
        self.assertEqual(entry.changes, {'Bound to': [None, 'T-01 › Middle (Primary)']})

    def test_water_goes_to_the_point_chosen_or_the_system_and_process_values_to_the_system_or_the_equipment(self):
        flow = make_channel(self.device, 'flow_m3_h')
        bindings.move_device(self.user, self.device, self.start, self.ras)
        self.assertEqual(self.open_places(), {'TEMPERATURE-C': self.ras, 'PH': self.ras, 'OXYGEN-MG-L': self.ras,
                                              'FLOW-M3-H': self.ras})
        pump = Equipment.objects.create(name='Pump', code='P1', production_department=self.hall,
                                        equipment_type=EquipmentType.objects.order_by('code').first())
        Channel.objects.filter(device=self.device).exclude(pk=flow.pk).update(state='retired')
        bindings.move_device(self.user, self.device, self.start + timedelta(days=1), pump)
        self.assertEqual(self.open_places(), {'FLOW-M3-H': pump})

    def test_the_plan_says_where_each_channel_lands_or_why_it_cannot(self):
        flow = make_channel(self.device, 'flow_m3_h')
        steps = {step.channel.code: step for step in bindings.plan_device(self.device, self.t1, self.start)}
        self.assertEqual((steps['PH'].place, steps['PH'].reason), (self.mid1, ''))
        self.assertEqual(steps[flow.code].place, None)
        self.assertIn('A process value is bound to a piece of equipment or a system', steps[flow.code].reason)

    def test_one_channel_that_cannot_go_there_refuses_the_whole_move_and_nothing_moves(self):
        bindings.move_device(self.user, self.device, self.start, self.t1)
        other = make_device(self.connection, self.format, self.site, code='PROBE-2')
        resident = make_channel(other, 'ph')
        bindings.move(self.user, resident, self.start, point=self.mid2)
        with self.assertRaises(ValidationError) as caught:
            bindings.move_device(self.user, self.device, self.start + timedelta(days=1), self.t2)
        self.assertIn('PH', ' '.join(caught.exception.messages))
        self.assertIn('already has a primary', ' '.join(caught.exception.messages))
        self.assertEqual(self.open_places(), {'TEMPERATURE-C': self.mid1, 'PH': self.mid1, 'OXYGEN-MG-L': self.mid1})
        self.assertEqual(self.device_entries().count(), 1)

    def test_a_backup_role_takes_the_place_beside_a_primary(self):
        other = make_device(self.connection, self.format, self.site, code='PROBE-2')
        bindings.move(self.user, make_channel(other, 'ph'), self.start, point=self.mid2)
        bindings.move_device(self.user, self.device, self.start, self.t2, role='backup')
        self.assertEqual(set(Binding.objects.filter(channel__device=self.device).values_list('role', flat=True)),
                         {'backup'})

    def test_a_moment_before_a_channel_was_bound_refuses_the_whole_move(self):
        bindings.move_device(self.user, self.device, self.start, self.t1)
        bindings.move(self.user, self.ph, self.start + timedelta(days=2), point=self.mid2)
        with self.assertRaises(ValidationError) as caught:
            bindings.move_device(self.user, self.device, self.start + timedelta(days=1), self.ras)
        self.assertIn('PH', ' '.join(caught.exception.messages))
        self.assertEqual(self.open_places(), {'TEMPERATURE-C': self.mid1, 'PH': self.mid2, 'OXYGEN-MG-L': self.mid1})

    def test_two_channels_of_one_quantity_cannot_both_be_the_primary_there(self):
        make_channel(self.device, 'ph', code='PH-2')
        with self.assertRaises(ValidationError) as caught:
            bindings.move_device(self.user, self.device, self.start, self.t1)
        self.assertIn('PH-2', ' '.join(caught.exception.messages))
        self.assertEqual(self.open_places(), {})

    def test_a_water_value_needs_a_point_at_a_piece_of_equipment(self):
        pump = Equipment.objects.create(name='Pump', code='P1', production_department=self.hall,
                                        equipment_type=EquipmentType.objects.order_by('code').first())
        steps = bindings.plan_device(self.device, pump, self.start)
        self.assertTrue(all('A water value is bound to a sampling point or a system' in step.reason for step in steps))

    def test_a_retired_or_deleted_channel_leaves_the_place_and_goes_nowhere(self):
        bindings.move_device(self.user, self.device, self.start, self.t1)
        Channel.objects.filter(pk=self.oxygen.pk).update(state='retired')
        self.temp.soft_delete(self.user)
        bindings.move_device(self.user, self.device, self.start + timedelta(days=1), self.t2)
        self.assertEqual(self.open_places(), {'PH': self.mid2})
        self.assertEqual(Binding.all_objects.filter(channel__device=self.device, valid_to__isnull=True).count(), 1)

    def test_a_device_without_live_channels_has_nothing_to_move(self):
        empty = make_device(self.connection, self.format, self.site, code='PROBE-0')
        with self.assertRaises(ValidationError):
            bindings.move_device(self.user, empty, self.start, self.t1)


class UnbindDeviceTests(PortableCase):
    def test_taking_the_device_out_ends_every_open_binding_at_one_moment_with_one_entry(self):
        bindings.move_device(self.user, self.device, self.start, self.t1)
        out_at = self.start + timedelta(days=1)
        bindings.unbind_device(self.user, self.device, out_at)
        self.assertEqual(self.open_places(), {})
        self.assertEqual(set(Binding.objects.filter(channel__device=self.device).values_list('valid_to', flat=True)),
                         {out_at})
        changes = next(entry.changes for entry in self.device_entries() if entry.changes['Bound to (PH)'][1] is None)
        self.assertEqual(changes['Bound to (PH)'], ['T-01 › Middle (Primary)', None])

    def test_a_device_placed_nowhere_cannot_be_taken_out(self):
        with self.assertRaises(ValidationError):
            bindings.unbind_device(self.user, self.device, self.start)

    def test_where_each_device_is_placed_now(self):
        other = make_device(self.connection, self.format, self.site, code='PROBE-2')
        bindings.move_device(self.user, self.device, self.start, self.t1)
        placed = bindings.placements([self.device, other])
        self.assertEqual(sorted(str(place) for place in placed[self.device.pk]), ['T-01 › Middle'])
        self.assertEqual(placed[other.pk], [])

    def test_a_devices_placement_history_from_and_until(self):
        bindings.move_device(self.user, self.device, self.start, self.t1)
        bindings.move_device(self.user, self.device, self.start + timedelta(days=1), self.ras)
        bindings.unbind_device(self.user, self.device, self.start + timedelta(days=2))
        history = bindings.placement_history(self.device)
        self.assertEqual([(stay.start, stay.end, [str(place) for place in stay.places]) for stay in history], [
            (self.start + timedelta(days=1), self.start + timedelta(days=2), ['RAS 1 (R1)']),
            (self.start, self.start + timedelta(days=1), ['T-01 › Middle'])])


def insert(channel_no, rows):
    """(ts, value) readings, one row per statement."""
    with connection.cursor() as cursor:
        for at, value in rows:
            cursor.execute('INSERT INTO sensors_reading (channel_no, ts, value) VALUES (%s, %s, %s)',
                           [channel_no, at, value])


class ReadTests(PortableCase):
    def test_readings_taken_while_the_device_is_out_are_stored_and_belong_nowhere(self):
        start = datetime(2026, 10, 10, tzinfo=tz.utc)
        bindings.move_device(self.user, self.device, start, self.t1)
        bindings.unbind_device(self.user, self.device, start + timedelta(hours=1))
        bindings.move_device(self.user, self.device, start + timedelta(hours=2), self.t1)
        rows = [(start + timedelta(minutes=minute), 7 + minute / 1000) for minute in range(0, 180, 10)]
        insert(self.ph.channel_no, rows)
        out = [at for at, _value in rows if start + timedelta(hours=1) <= at < start + timedelta(hours=2)]
        self.assertEqual(len(out), 6)
        stored = {at for (at,) in rows_of('SELECT ts FROM sensors_reading WHERE channel_no = %s', [self.ph.channel_no])}
        self.assertTrue(set(out) <= stored)                                   # kept as evidence
        chart = read.series(self.mid1, 'ph', start, start + timedelta(hours=3), max_points=180)
        self.assertEqual([bucket.first_ts for bucket in chart.buckets], [at for at, _value in rows if at not in out])
        self.assertEqual(read.bound_quantities(self.t2, start, start + timedelta(hours=3)), [])
        answer = sources.value_at([(sources.POINT, self.mid1.pk)], 'ph', start + timedelta(minutes=90))
        self.assertEqual([value.at for value in answer.values[(sources.POINT, self.mid1.pk)]],
                         [start + timedelta(minutes=50)])                    # the last one taken there, never 01:20
        frames = read.deffeyes_frames(self.t1, start + timedelta(minutes=70), start + timedelta(minutes=110),
                                      timedelta(minutes=5)).frames
        self.assertEqual([frame.inputs.get('ph') for frame in frames], [None] * 8)

    def test_a_value_measured_before_the_device_came_is_not_the_new_places_latest(self):
        now = timezone.now()
        bindings.move_device(self.user, self.device, now - timedelta(hours=1), self.t1)
        measured = now - timedelta(seconds=60)                               # fresh: pH is fresh for 15 minutes
        ChannelState.objects.create(channel_no=self.ph.channel_no, last_value=7.4, last_value_ts=measured,
                                    last_good_at=measured, last_seen_at=measured)
        self.assertEqual(str(water_read.latest([self.mid1])[self.mid1.pk].get('ph').value), '7.40')
        bindings.move_device(self.user, self.device, now - timedelta(seconds=30), self.t2)
        self.assertIsNone(water_read.latest([self.mid2])[self.mid2.pk].get('ph'))
        self.assertIsNone(water_read.latest([self.mid1])[self.mid1.pk].get('ph'))
        later = now - timedelta(seconds=5)                                   # the probe's first value in T-02
        ChannelState.objects.filter(channel_no=self.ph.channel_no).update(last_value=7.1, last_value_ts=later,
                                                                          last_good_at=later)
        self.assertEqual(str(water_read.latest([self.mid2])[self.mid2.pk].get('ph').value), '7.10')

    def test_a_device_taken_out_gives_no_place_a_latest_value(self):
        now = timezone.now()
        bindings.move_device(self.user, self.device, now - timedelta(hours=1), self.t1)
        bindings.unbind_device(self.user, self.device, now - timedelta(minutes=5))
        ChannelState.objects.create(channel_no=self.ph.channel_no, last_value=7.4, last_value_ts=now,
                                    last_good_at=now, last_seen_at=now)
        self.assertIsNone(water_read.latest([self.mid1])[self.mid1.pk].get('ph'))


class SiteTests(PortableCase):
    """A device is at one site at a time: the site of the places its channels are bound to. Its site follows a move, a
    channel cannot go to another site without its device, and a placed device's site is not changed by hand."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.oslo = Site.objects.create(name='Oslo', code='OS', timezone='Europe/Oslo')
        cls.oslo_hall = ProductionDepartment.objects.create(site=cls.oslo, name='Hall O', code='HO')
        cls.r9 = System.objects.create(name='RAS 9', code='R9', site=cls.oslo, production_department=cls.oslo_hall)
        cls.t9 = make_unit('T-09', cls.oslo_hall, system=cls.r9)
        cls.mid9 = point_of(cls.t9)

    def test_moving_a_device_to_another_site_takes_its_site_with_it(self):
        bindings.move_device(self.user, self.device, self.start, self.t1)
        bindings.move_device(self.user, self.device, self.start + timedelta(days=1), self.t9)
        self.device.refresh_from_db()
        self.assertEqual(self.device.site, self.oslo)
        self.assertEqual(self.open_places(), {'TEMPERATURE-C': self.mid9, 'PH': self.mid9, 'OXYGEN-MG-L': self.mid9})
        changes = next(entry.changes for entry in self.device_entries() if 'Site' in entry.changes)
        self.assertEqual(changes['Site'], [str(self.site), str(self.oslo)])
        self.assertEqual(changes['Bound to (PH)'], ['T-01 › Middle (Primary)', 'T-09 › Middle (Primary)'])
        bindings.unbind_device(self.user, self.device, self.start + timedelta(days=2))
        self.device.refresh_from_db()
        self.assertEqual(self.device.site, self.oslo)                        # kept where it was taken out

    def test_a_channel_alone_cannot_go_to_another_site(self):
        with self.assertRaises(ValidationError) as caught:
            bindings.move(self.user, self.ph, self.start, point=self.mid9)
        self.assertIn('Move device', ' '.join(caught.exception.messages))
        self.refused('trg_sensors_binding_site',
                     lambda: Binding.objects.create(channel=self.ph, point=self.mid9, valid_from=self.start))
        self.refused('trg_sensors_binding_site',
                     lambda: Binding.objects.create(channel=self.ph, system=self.r9, valid_from=self.start))
        Binding.objects.create(channel=self.ph, point=self.mid9, valid_from=self.start,      # history: allowed
                               valid_to=self.start + timedelta(days=1))

    def test_a_placed_devices_site_is_not_changed_by_hand(self):
        bindings.move_device(self.user, self.device, self.start, self.t1)
        self.refused('trg_sensors_device_site', lambda: Device.objects.filter(pk=self.device.pk).update(site=self.oslo))
        bindings.unbind_device(self.user, self.device, self.start + timedelta(days=1))
        Device.objects.filter(pk=self.device.pk).update(site=self.oslo)    # out of the water: taken anywhere

    def test_a_deleted_channels_open_binding_still_holds_the_device_at_its_site(self):
        bindings.move(self.user, self.ph, self.start, point=self.mid1)
        self.ph.soft_delete(self.user)
        self.refused('trg_sensors_device_site', lambda: Device.objects.filter(pk=self.device.pk).update(site=self.oslo))
        bindings.move_device(self.user, self.device, self.start + timedelta(days=1), self.t9)
        self.assertFalse(Binding.all_objects.filter(channel=self.ph, valid_to__isnull=True).exists())

    def test_a_moment_is_on_the_clock_of_the_places_site(self):
        self.assertEqual(bindings.clock(self.device, self.t9), ZoneInfo('Europe/Oslo'))
        self.assertEqual(bindings.clock(self.device, self.mid9), ZoneInfo('Europe/Oslo'))
        self.assertEqual(bindings.clock(self.device), zone_of(self.site))

    def test_a_placed_devices_form_says_its_site_follows_it(self):
        user = get_user_model().objects.create_superuser('admin', 'admin@example.com', 'x')
        self.client.force_login(user)
        url = reverse('sensors:device_edit', args=[self.device.pk])
        self.assertFalse(self.client.get(url).context['form'].fields['site'].disabled)
        bindings.move_device(self.user, self.device, self.start, self.t1)
        self.assertTrue(self.client.get(url).context['form'].fields['site'].disabled)


JOURNEY = datetime(2026, 10, 10, tzinfo=tz.utc)
HOUR = timedelta(hours=1)


class JourneyTests(PortableCase):
    """A probe in T-01, moved to T-02 at 01:30 and to the system R1 at 03:20, sending a pH every minute until 05:00: each
    place has exactly the readings taken while it was there, at every tier of its charts and in its replay frames, the
    moves inside an hour included (the hour that holds a move is not given whole to the place where it began)."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.to_t2, cls.to_r1 = JOURNEY + timedelta(minutes=90), JOURNEY + timedelta(minutes=200)
        bindings.move_device(cls.user, cls.device, JOURNEY - timedelta(days=1), cls.t1)
        bindings.move_device(cls.user, cls.device, cls.to_t2, cls.t2)
        bindings.move_device(cls.user, cls.device, cls.to_r1, cls.ras)
        cls.rows = [(JOURNEY + timedelta(minutes=minute), 7 + minute / 1000) for minute in range(300)]
        cls.stays = {'T-01': (JOURNEY - timedelta(days=1), cls.to_t2), 'T-02': (cls.to_t2, cls.to_r1),
                     'R1': (cls.to_r1, JOURNEY + timedelta(days=1))}

    def setUp(self):
        insert(self.ph.channel_no, self.rows)

    def taken(self, stay):
        start, end = self.stays[stay]
        return [(at, value) for at, value in self.rows if start <= at < end]

    def places(self):
        return [(self.mid1, read.SENSOR, 'T-01'), (self.mid2, read.SENSOR, 'T-02'), (self.ras, read.SYSTEM_SENSOR, 'R1')]

    def test_each_places_chart_has_exactly_its_own_readings(self):
        end = JOURNEY + timedelta(hours=5)
        for place, origin, stay in self.places():
            with self.subTest(place=str(place)):
                chart = read.series(place, 'ph', JOURNEY, end, max_points=300)
                self.assertEqual(chart.tier, read.RAW)
                self.assertEqual([(bucket.first_ts, bucket.avg, bucket.origin) for bucket in chart.buckets],
                                 [(at, value, origin) for at, value in self.taken(stay)])

    def test_the_hour_that_holds_a_move_is_shared_by_the_two_places(self):
        end = JOURNEY + timedelta(hours=5)
        for place, _origin, stay in self.places():
            with self.subTest(place=str(place)):
                chart = read.series(place, 'ph', JOURNEY, end, max_points=5)
                self.assertEqual((chart.tier, chart.width), (read.ROLLUP_1H, HOUR))
                hours = {}
                for at, value in self.taken(stay):
                    hours.setdefault(at.replace(minute=0), []).append((at, value))
                self.assertEqual([(bucket.start, bucket.n, bucket.first_ts, bucket.last_ts) for bucket in chart.buckets],
                                 [(hour, len(found), found[0][0], found[-1][0]) for hour, found in sorted(hours.items())])
                for bucket in chart.buckets:
                    values = [value for _at, value in hours[bucket.start]]
                    self.assertAlmostEqual(bucket.avg, sum(values) / len(values), places=9)
                    self.assertEqual((bucket.vmin, bucket.vmax), (min(values), max(values)))

    def test_a_units_chart_has_its_own_readings_then_its_systems(self):
        chart = read.series(self.t1, 'ph', JOURNEY, JOURNEY + timedelta(hours=5), max_points=300)
        self.assertEqual([(bucket.first_ts, bucket.origin) for bucket in chart.buckets],
                         [(at, read.SENSOR) for at, _value in self.taken('T-01')]
                         + [(at, read.SYSTEM_SENSOR) for at, _value in self.taken('R1')])

    def expected(self, stays, at, hourly):
        """The A1 input a frame at `at` reads: the first place in order with a fresh reading taken while it was there (the
        newest at or before the frame; on the hour tier the last of the newest hour ended by the frame)."""
        for stay, origin in stays:
            found = [(ts, value) for ts, value in self.taken(stay) if ts <= at]
            if hourly:
                ended = [ts.replace(minute=0) for ts, _value in found if ts.replace(minute=0) + HOUR <= at]
                found = [(ts, value) for ts, value in found if ended and ts.replace(minute=0) == max(ended)]
            if found and at - found[-1][0] <= timedelta(seconds=self.ph.fresh_s):
                return float(water_read.as_parameter('ph', found[-1][1])), origin
        return None

    def test_the_replay_frames_read_the_same_at_both_tiers(self):
        self.ph.refresh_from_db()
        orders = {self.t1: [('T-01', read.SENSOR), ('R1', read.SYSTEM_SENSOR)],
                  self.t2: [('T-02', read.SENSOR), ('R1', read.SYSTEM_SENSOR)],
                  self.ras: [('R1', read.SYSTEM_SENSOR)]}
        for step, hourly in ((timedelta(minutes=5), False), (HOUR, True)):
            for target, stays in orders.items():
                with self.subTest(target=str(target), step=step):
                    frames = read.deffeyes_frames(target, JOURNEY + step, JOURNEY + timedelta(hours=5, minutes=1),
                                                  step).frames
                    got = [(frame.at, (frame.inputs['ph'].value, frame.inputs['ph'].origin)
                            if 'ph' in frame.inputs else None) for frame in frames]
                    self.assertEqual(got, [(frame.at, self.expected(stays, frame.at, hourly)) for frame in frames])


MOVER = ('view_device', 'view_binding', 'add_binding', 'change_binding', 'view_channel', 'view_samplingpoint',
         'view_system', 'view_equipment')


class PageTests(PortableCase):
    """The Move device dialog (from the device's page, the list, or a monitoring card's link `?device=&target=`), where a
    device is and was, which sensors a place has now and had before, and the overview's devices not placed."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.oslo = Site.objects.create(name='Oslo', code='OS', timezone='Europe/Oslo')
        cls.t9 = make_unit('T-09', ProductionDepartment.objects.create(site=cls.oslo, name='Hall O', code='HO'))
        cls.mid9 = point_of(cls.t9)

    def setUp(self):
        self.mover = get_user_model().objects.create_user('mover', 'mover@example.com', 'x')
        self.mover.groups.add(role('Mover', *MOVER))
        self.client.force_login(self.mover)
        self.url = reverse('sensors:device_move')

    def wall(self, moment, zone=None):
        return timezone.localtime(moment, zone or zone_of(self.site)).strftime('%Y-%m-%dT%H:%M')

    def test_a_cards_link_opens_the_dialog_with_each_channels_landing(self):
        response = self.client.get(self.url, {'device': self.device.pk, 'target': f'unit:{self.t1.pk}'})
        form = response.context['form']
        self.assertEqual((str(form['device'].value()), form['target'].value()), (str(self.device.pk), f'unit:{self.t1.pk}'))
        self.assertEqual([(step.channel.code, step.place, step.reason) for step in response.context['plan']],
                         [('OXYGEN-MG-L', self.mid1, ''), ('PH', self.mid1, ''), ('TEMPERATURE-C', self.mid1, '')])
        self.assertContains(response, 'T-01 › Middle')

    def test_the_dialog_moves_the_device_from_the_moment_on_the_places_clock(self):
        moment = timezone.now().replace(second=0, microsecond=0) - timedelta(days=1)
        response = self.client.post(self.url, {'device': self.device.pk, 'target': f'unit:{self.t9.pk}',
                                               'role': 'primary', 'valid_from': self.wall(moment, ZoneInfo('Europe/Oslo')),
                                               'note': 'to Oslo'})
        self.assertIn(response.status_code, (204, 302), response.context and response.context['form'].errors)
        self.assertEqual(self.open_places(), {'TEMPERATURE-C': self.mid9, 'PH': self.mid9, 'OXYGEN-MG-L': self.mid9})
        self.assertEqual(set(Binding.objects.values_list('valid_from', 'note', 'created_by')),
                         {(moment, 'to Oslo', self.mover.pk)})
        self.device.refresh_from_db()
        self.assertEqual(self.device.site, self.oslo)

    def test_a_refused_move_says_each_channels_reason_and_moves_nothing(self):
        make_channel(self.device, 'flow_m3_h')
        response = self.client.post(self.url, {'device': self.device.pk, 'target': f'unit:{self.t1.pk}',
                                               'role': 'primary', 'valid_from': self.wall(self.start)})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'FLOW-M3-H')
        self.assertContains(response, 'A process value is bound to a piece of equipment or a system')
        self.assertFalse(Binding.objects.exists())

    def test_a_draft_shows_the_landing_and_moves_nothing(self):
        response = self.client.post(self.url, {'device': self.device.pk, 'target': f'system:{self.ras.pk}',
                                               'role': 'primary', 'valid_from': self.wall(self.start), '_draft': 'target'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual({step.place for step in response.context['plan']}, {self.ras})
        self.assertFalse(Binding.objects.exists())

    def test_the_dialog_takes_the_device_out_of_the_water(self):
        bindings.move_device(self.user, self.device, self.start, self.t1)
        response = self.client.post(self.url, {'device': self.device.pk, 'target': 'out', 'role': 'primary',
                                               'valid_from': self.wall(self.start + timedelta(days=1))})
        self.assertIn(response.status_code, (204, 302))
        self.assertEqual(self.open_places(), {})

    def test_the_device_list_says_where_each_device_is_and_offers_the_move(self):
        other = make_device(self.connection, self.format, self.site, code='PROBE-2')
        bindings.move_device(self.user, self.device, self.start, self.t1)
        response = self.client.get(reverse('sensors:device_list'))
        self.assertContains(response, 'T-01 › Middle')
        self.assertContains(response, '<span class="badge badge-closed">Not placed</span>', count=1)
        self.assertContains(response, f'{self.url}?device={other.pk}')
        unplaced = self.client.get(reverse('sensors:device_list'), {'placed': 'no'})
        self.assertEqual([device.code for device in unplaced.context['objects']], ['PROBE-2'])

    def test_the_device_page_has_where_it_was_and_the_move(self):
        admin = get_user_model().objects.create_superuser('admin', 'admin@example.com', 'x')
        self.client.force_login(admin)
        bindings.move_device(self.user, self.device, self.start, self.t1)
        bindings.move_device(self.user, self.device, self.start + timedelta(days=1), self.ras)
        response = self.client.get(reverse('sensors:device_edit', args=[self.device.pk]))
        self.assertEqual([[str(place) for place in stay.places] for stay in response.context['placement_history']],
                         [['RAS 1 (R1)'], ['T-01 › Middle']])
        self.assertContains(response, f'{self.url}?device={self.device.pk}')

    def test_a_place_lists_the_sensors_there_now_and_before(self):
        other = make_device(self.connection, self.format, self.site, code='PROBE-2')
        make_channel(other, 'ph')
        bindings.move_device(self.user, other, self.start, self.t2)
        bindings.move_device(self.user, self.device, self.start, self.t1)
        bindings.move_device(self.user, self.device, self.start + timedelta(days=1), self.ras)
        listing = self.client.get(reverse('sensors:binding_list'), {'place': f'unit:{self.t1.pk}'})
        found = list(listing.context['objects'])
        self.assertEqual({(binding.channel.device.code, binding.point, binding.valid_to is None) for binding in found},
                         {('PROBE-1', self.mid1, False)})
        self.assertEqual(len(found), 3)
        system = self.client.get(reverse('sensors:binding_list'), {'place': f'system:{self.ras.pk}'})
        self.assertEqual({(binding.channel.device.code, binding.valid_to is None) for binding in system.context['objects']},
                         {('PROBE-1', True)})
        self.assertContains(system, 'RAS 1 (R1)')

    def test_the_overview_counts_the_devices_not_placed(self):
        make_device(self.connection, self.format, self.site, code='PROBE-2')
        bindings.move_device(self.user, self.device, self.start, self.t1)
        page = self.client.get(reverse('sensors:home'))
        tiles = {str(tile['label']): tile for tile in page.context['state_tiles']}
        self.assertEqual(tiles['Devices not placed']['count'], 1)
        self.assertEqual(tiles['Devices not placed']['url'], f'{reverse("sensors:device_list")}?placed=no')

    def test_without_the_right_to_bind_no_move(self):
        reader = get_user_model().objects.create_user('reader', 'reader@example.com', 'x')
        reader.groups.add(role('Reader', 'view_device', 'view_binding'))
        self.client.force_login(reader)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertNotContains(self.client.get(reverse('sensors:device_list')), self.url)

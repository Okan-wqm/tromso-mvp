"""A pH scale per sensor pH channel (owner decision 1 of 2026-11-17; the water-chemistry audit of 2026-11-19, F1): the
channel's column and its rules, what the provider says of a pH value, the channel's form and pages, and every place a
sensor pH is worked out from: the water's latest values (farm/tests/test_sensor_ph_scale.py has the rules), the
Deffeyes replay and the trail. A channel's values from before a change of its scale are used nowhere."""
from datetime import datetime, timedelta, timezone as tz
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.urls import reverse
from django.utils import formats, timezone

from core.models import AuditLog
from core.testing import FrozenClock
from farm.models import Tank
from farm.tests.helpers import point_of, role
from farm.tests.test_sensor_ph_scale import CORE_REFUSED, core_refuses_the_conversion
from farm.tests.test_stock import make_unit
from farm.water import read as water_read, services as water_services, sources

from sensors import bindings, chart, provider, read, trail
from sensors.models import Channel, ChannelState

from . import SensorsCase, make_channel, one

START = datetime(2026, 10, 10, tzinfo=tz.utc)
NOW = START + timedelta(days=7)


def insert(channel_no, rows):
    with connection.cursor() as cursor:
        for at, value in rows:
            cursor.execute('INSERT INTO sensors_reading (channel_no, ts, value) VALUES (%s, %s, %s)',
                           [channel_no, at, value])


class ChannelTests(SensorsCase):
    def test_a_channel_is_nbs_unless_set_and_only_a_ph_channel_takes_another_scale(self):
        ph = make_channel(self.device, 'ph')
        self.assertEqual((ph.ph_scale, ph.ph_scale_from), ('nbs', None))
        self.assertEqual((self.channel.ph_scale, self.channel.ph_scale_said), ('nbs', ''))
        self.assertEqual(ph.ph_scale_said, 'NBS (a meter calibrated with NBS/NIST buffers)')
        total = make_channel(self.device, 'ph', code='PH-2', ph_scale='total')
        self.assertEqual((total.ph_scale, total.ph_scale_from), ('total', None))     # made so: every value is total
        self.refused('chk_sensors_channel_ph_scale',
                     lambda: Channel.objects.filter(pk=self.channel.pk).update(ph_scale='total'))
        self.refused('chk_sensors_channel_ph_scale',
                     lambda: Channel.objects.filter(pk=self.channel.pk).update(ph_scale_from=timezone.now()))
        self.refused('chk_sensors_channel_ph_scale', lambda: Channel.objects.filter(pk=ph.pk).update(ph_scale='tris'))

    def test_the_ingests_own_insert_names_no_scale_and_gets_nbs(self):
        """The ingest's tests insert channels naming their columns (sensors-ingest/tests/common/mod.rs): the database
        default keeps them working."""
        number = one(
            "INSERT INTO sensors_channel (id, created_at, updated_at, version, is_deleted, code, name, quantity, unit, "
            "unit_factor, unit_offset, value_path, item_name, address_protocol, address, reduction, deadband, "
            "heartbeat_s, fresh_heartbeats, range_min, range_max, state, note, device_id) VALUES (gen_random_uuid(), "
            "now(), now(), 1, false, 'PH-RAW', 'pH', 'ph', '', 1, 0, '/ph', '', 'mqtt', '{}', 'all', 0, 60, 3, NULL, "
            "NULL, 'active', '', %s) RETURNING channel_no", [self.device.pk])
        self.assertEqual(Channel.objects.get(channel_no=number).ph_scale, 'nbs')

    def test_changing_the_scale_says_when_whichever_door_saves_it(self):
        ph = make_channel(self.device, 'ph')
        ph.name = 'pH, renamed'
        ph.save()
        self.assertIsNone(Channel.objects.get(pk=ph.pk).ph_scale_from)              # nothing changed of its scale
        before = timezone.now()
        ph.ph_scale = 'total'
        ph.save(update_fields=['ph_scale'])
        stored = Channel.objects.get(pk=ph.pk)
        self.assertEqual(stored.ph_scale, 'total')
        self.assertGreaterEqual(stored.ph_scale_from, before)
        first = stored.ph_scale_from
        stored.ph_scale = 'nbs'                                                    # back again: a change too
        stored.save()
        self.assertGreater(Channel.objects.get(pk=ph.pk).ph_scale_from, first)


class ProviderTests(SensorsCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.t1 = make_unit('T-01', cls.hall)
        cls.mid1 = point_of(cls.t1)
        cls.ph = make_channel(cls.device, 'ph', ph_scale='total')
        bindings.move(cls.user, cls.ph, point=cls.mid1, at=timezone.now() - timedelta(hours=1))
        bindings.move(cls.user, cls.channel, point=cls.mid1, at=timezone.now() - timedelta(hours=1))

    def test_a_ph_value_says_its_channels_scale_and_since_when(self):
        now = timezone.now()
        for channel, value in ((self.ph, 7.95), (self.channel, 12.0)):
            ChannelState.objects.create(channel_no=channel.channel_no, last_value=value,
                                        last_value_ts=now - timedelta(seconds=10), last_good_at=now)
            insert(channel.channel_no, [(now - timedelta(seconds=10), value)])
        target = (sources.POINT, self.mid1.pk)
        latest = provider.PROVIDER.latest([target], now)[target]
        self.assertEqual((latest['ph'][0].ph_scale, latest['ph'][0].ph_scale_from), ('total', None))
        self.assertEqual((latest['temperature_c'][0].ph_scale, latest['temperature_c'][0].ph_scale_from), ('', None))
        [at] = provider.PROVIDER.value_at([target], 'ph', now)[target]
        self.assertEqual((at.value, at.ph_scale), (7.95, 'total'))
        Channel.objects.get(pk=self.ph.pk).save()                                  # unchanged: nothing said
        self.ph.refresh_from_db()
        self.ph.ph_scale = 'nbs'
        self.ph.save()
        [moved] = provider.PROVIDER.latest([target], now)[target]['ph']
        self.assertEqual((moved.ph_scale, moved.ph_scale_from), ('', self.ph.ph_scale_from))


class SeaWaterCase(FrozenClock, SensorsCase):
    """A sea unit with a total-scale pH probe and a temperature probe on its middle point, and a sample's salinity and
    alkalinity, from START."""
    NOW = NOW

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.sea = make_unit('S-01', cls.hall)
        Tank.objects.filter(pk=cls.sea.pk).update(water_type='saltwater', water_origin='seawater')
        cls.sea.refresh_from_db()
        cls.point = point_of(cls.sea)
        cls.ph = make_channel(cls.device, 'ph', ph_scale='total')
        bindings.move(cls.user, cls.ph, point=cls.point, at=START - timedelta(days=1))
        bindings.move(cls.user, cls.channel, point=cls.point, at=START - timedelta(days=1))
        water_services.record(cls.user, point=cls.point, measured_at=START - timedelta(days=1), source='manual',
                              values={'alkalinity_mg_l': Decimal('115'), 'salinity_ppt': Decimal('34.0')})

    def steady(self, minutes=120, ph=7.95):
        insert(self.ph.channel_no, [(START + timedelta(minutes=m), ph) for m in range(0, minutes, 5)])
        insert(self.channel.channel_no, [(START + timedelta(minutes=m), 12.0) for m in range(minutes)])

    def nbs(self, ph=7.95):
        stored, _measured = water_services.on_nbs(self.point, {'ph': Decimal(str(ph)), 'temperature_c': Decimal('12.0'),
                                                               'salinity_ppt': Decimal('34.0')}, 'total')
        return float(stored['ph'])


class ReplayTests(SeaWaterCase):
    def test_each_frames_ph_is_put_on_the_nbs_scale_with_its_own_water(self):
        self.steady()
        frames = read.deffeyes_frames(self.sea, START + timedelta(minutes=5), START + timedelta(minutes=55),
                                      timedelta(minutes=5))
        self.assertTrue(frames.frames)
        for frame in frames.frames:
            with self.subTest(at=frame.at):
                self.assertEqual((frame.inputs['ph'].value, frame.inputs['ph'].as_measured), (self.nbs(), 7.95))
                self.assertEqual(frame.inputs['ph'].ph_scale, 'total')
                self.assertEqual(frame.point.ph, self.nbs())
                self.assertEqual(frame.impossible, '')

    def test_a_fresh_water_frame_has_no_ph_and_no_diagram_and_says_why(self):
        Tank.objects.filter(pk=self.sea.pk).update(water_type='freshwater', water_origin='')
        self.sea.refresh_from_db()
        water_services.record(self.user, point=self.point, measured_at=START - timedelta(hours=1), source='manual',
                              values={'salinity_ppt': Decimal('0.0')})
        self.steady(minutes=30)
        frames = read.deffeyes_frames(self.sea, START + timedelta(minutes=5), START + timedelta(minutes=25),
                                      timedelta(minutes=5))
        for frame in frames.frames:
            with self.subTest(at=frame.at):
                self.assertNotIn('ph', frame.inputs)                               # never the unconverted number
                self.assertIsNone(frame.point)
                self.assertIn('sea water of 5 ‰ or more', frame.impossible)

    def test_the_values_from_before_a_change_of_scale_are_used_nowhere(self):
        self.steady()
        Channel.objects.filter(pk=self.ph.pk).update(ph_scale_from=START + timedelta(minutes=30))
        frames = read.deffeyes_frames(self.sea, START + timedelta(minutes=5), START + timedelta(minutes=55),
                                      timedelta(minutes=5))
        before = [frame for frame in frames.frames if frame.at < START + timedelta(minutes=30)]
        after = [frame for frame in frames.frames if frame.at >= START + timedelta(minutes=30)]
        self.assertTrue(before and after)
        self.assertTrue(all('ph' in frame.missing for frame in before))
        self.assertTrue(all(frame.inputs['ph'].value == self.nbs() for frame in after))

    def test_a_frame_whose_water_the_core_cannot_work_out_says_the_cores_reason(self):
        self.steady()
        with core_refuses_the_conversion():
            frames = read.deffeyes_frames(self.sea, START + timedelta(minutes=5), START + timedelta(minutes=25),
                                          timedelta(minutes=5))
        self.assertTrue(frames.frames)
        for frame in frames.frames:
            with self.subTest(at=frame.at):
                self.assertNotIn('ph', frame.inputs)
                self.assertIn(f'cannot work this water out: {CORE_REFUSED}', frame.impossible)
                self.assertNotIn('sea water of 5 ‰', frame.impossible)


class TrailTests(SeaWaterCase):
    def test_an_hours_ph_is_put_on_the_nbs_scale(self):
        self.steady(minutes=180)
        found = trail.trail(self.sea, START, START + timedelta(hours=2))
        self.assertEqual([point.ph for point in found.points], [self.nbs(), self.nbs()])

    def test_where_the_water_takes_no_such_ph_the_hour_says_why(self):
        Tank.objects.filter(pk=self.sea.pk).update(water_type='brackish', water_origin='salt_added')
        self.sea.refresh_from_db()
        self.steady(minutes=180)
        found = trail.trail(self.sea, START, START + timedelta(hours=2))
        self.assertEqual(found.points, [])
        self.assertEqual(len(found.unworkable), 2)
        self.assertTrue(all('not fresh water with salt added' in why for _at, why in found.unworkable))

    def test_where_the_core_cannot_work_the_water_out_the_hour_says_the_cores_reason(self):
        """The review of the water-chemistry audit, C5: it said "not sea water" for every failed conversion."""
        self.steady(minutes=180)
        with core_refuses_the_conversion():
            found = trail.trail(self.sea, START, START + timedelta(hours=2))
        self.assertEqual(found.points, [])
        self.assertEqual([why for _at, why in found.unworkable], [
            'No diagram: the sensor’s pH cannot be put on the NBS scale (a pH on the total scale is put on the NBS scale '
            f'by the chemistry core, which cannot work this water out: {CORE_REFUSED}).'] * 2)


class LiveTests(SeaWaterCase):
    def test_the_units_water_reads_the_probes_ph_on_the_nbs_scale(self):
        at = NOW - timedelta(seconds=30)
        for channel, value in ((self.ph, 7.95), (self.channel, 12.0)):
            ChannelState.objects.create(channel_no=channel.channel_no, last_value=value, last_value_ts=at,
                                        last_good_at=at)
        water_services.record(self.user, point=self.point, measured_at=NOW - timedelta(days=1), source='manual',
                              values={'salinity_ppt': Decimal('34.0')})
        ph = water_read.latest([self.point])[self.point.pk].get('ph')
        self.assertEqual((ph.value, ph.measured), (Decimal(str(self.nbs())), 'measured 7.95 on the total scale'))


class ChartTests(SeaWaterCase):
    def test_the_chart_says_the_scale_and_leaves_out_the_values_from_before_a_change(self):
        self.steady()
        Channel.objects.filter(pk=self.ph.pk).update(ph_scale_from=START + timedelta(minutes=30))
        found = read.series(self.point, 'ph', START, START + timedelta(hours=2))
        self.assertTrue(found.buckets)
        self.assertTrue(all(bucket.start >= START + timedelta(minutes=30) for bucket in found.buckets))
        self.assertIn('ph_scale', [marker.kind for marker in found.markers])
        notes = [str(note) for note in chart.notes(found)]
        self.assertTrue(any('drawn as its probe measured it, on the total scale' in note for note in notes))
        self.assertIn(self.cut_note(START + timedelta(minutes=30)), notes)
        self.assertIn('pH scale changed', chart.draw(found, 'S-01'))

    def cut_note(self, changed):
        shown = formats.date_format(timezone.localtime(changed, tz.utc), 'DATETIME_FORMAT')
        return (f'Channel #{self.ph.channel_no}’s values before {shown} are not drawn: its pH scale was changed then, '
                'and the scale they were measured on is not known.')

    def test_a_window_wholly_before_a_change_is_blank_and_says_why(self):
        """The review of the water-chemistry audit, C4: a month's view from before the change drew nothing and said
        nothing; it says why its values are not drawn, and draws none of them."""
        self.steady()
        changed = START + timedelta(hours=5)
        Channel.objects.filter(pk=self.ph.pk).update(ph_scale_from=changed)
        found = read.series(self.point, 'ph', START, START + timedelta(hours=2))
        self.assertEqual((found.buckets, found.markers), ([], []))
        self.assertEqual(found.cuts, [(self.ph.channel_no, changed)])
        self.assertIn(self.cut_note(changed), [str(note) for note in chart.notes(found)])

    def test_a_channel_whose_scale_never_changed_says_nothing_of_it(self):
        self.steady()
        found = read.series(self.point, 'ph', START, START + timedelta(hours=2))
        self.assertEqual(found.cuts, [])
        self.assertFalse(any('are not drawn' in str(note) for note in chart.notes(found)))


class PageTests(SensorsCase):
    def setUp(self):
        self.keeper = get_user_model().objects.create_user('keeper', 'keeper@example.com', 'x')
        self.keeper.groups.add(role('Sensor keeper', 'view_channel', 'add_channel', 'change_channel', 'view_device'))
        self.client.force_login(self.keeper)

    def posted(self, channel, **changes):
        form = self.client.get(reverse('sensors:channel_edit', args=[channel.pk])).context['form']
        data = {name: '' if form[name].value() is None else form[name].value() for name in form.fields}
        return {**data, **changes}

    def test_the_form_asks_a_ph_channels_scale_and_no_other_channels(self):
        ph = make_channel(self.device, 'ph')
        self.assertIn('ph_scale', self.client.get(reverse('sensors:channel_edit', args=[ph.pk])).context['form'].fields)
        self.assertNotIn('ph_scale', self.client.get(reverse('sensors:channel_edit', args=[self.channel.pk]))
                         .context['form'].fields)
        self.assertIn('ph_scale', self.client.get(reverse('sensors:channel_create')).context['form'].fields)

    def test_a_scale_set_and_changed_through_the_page_is_stored_logged_and_shown(self):
        ph = make_channel(self.device, 'ph')
        response = self.client.post(reverse('sensors:channel_edit', args=[ph.pk]), self.posted(ph, ph_scale='total'))
        self.assertIn(response.status_code, (204, 302))
        ph.refresh_from_db()
        self.assertEqual(ph.ph_scale, 'total')
        self.assertIsNotNone(ph.ph_scale_from)
        entry = AuditLog.objects.filter(entity_id=str(ph.pk), action='update').latest('created_at')
        self.assertIn('Scale the pH is measured on', entry.changes)
        listed = self.client.get(reverse('sensors:channel_list'))
        self.assertContains(listed, 'pH scale: Total scale (calibrated with TRIS)')
        self.assertContains(listed, 'changed ')
        form = self.client.get(reverse('sensors:channel_edit', args=[ph.pk]))
        self.assertContains(form, 'The pH scale was changed on')
        # A form that does not send the scale changes nothing (as the fresh heartbeats).
        data = self.posted(ph, name='pH renamed')
        data.pop('ph_scale')
        self.client.post(reverse('sensors:channel_edit', args=[ph.pk]), data)
        ph.refresh_from_db()
        self.assertEqual((ph.name, ph.ph_scale), ('pH renamed', 'total'))

    def test_a_non_ph_channel_posted_with_a_scale_keeps_nbs(self):
        data = self.posted(self.channel, ph_scale='total')
        self.client.post(reverse('sensors:channel_edit', args=[self.channel.pk]), data)
        self.channel.refresh_from_db()
        self.assertEqual(self.channel.ph_scale, 'nbs')

    def test_the_live_values_say_a_ph_channels_scale(self):
        ph = make_channel(self.device, 'ph', ph_scale='total')
        ChannelState.objects.create(channel_no=ph.channel_no, last_value=7.95, last_value_ts=timezone.now(),
                                    last_good_at=timezone.now())
        self.keeper.groups.add(role('Sensor reader', 'view_reading'))
        page = self.client.get(reverse('sensors:live'))
        self.assertContains(page, 'As measured, on its pH scale: Total scale (calibrated with TRIS)')

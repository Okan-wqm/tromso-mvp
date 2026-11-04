"""Where a channel's values belong: a binding to a sampling point, a system or a piece of equipment over a time range
(owner rule A1: a water channel to a point or to a system, a process channel to a piece of equipment or a system). The
database holds every rule: one target, an end after the start, no two bindings of one channel overlapping (an exclusion
constraint), one primary and one backup per target and quantity at a time and the right kind of target (a constraint
trigger, serialized per target so two concurrent saves cannot both pass). History is never edited: `move` closes the
open binding and opens the next in one transaction with one log entry. The water read sees a bound channel's value with
its origin, skips a channel in maintenance, hides the bindings of a deleted point and shows them again when it is
restored; a moved sensor's history stays with the unit it was in."""
import threading
from datetime import timedelta

import psycopg
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from core.models import AuditLog
from core.softdelete import restore
from farm.models import ProductionDepartment, Site, System
from farm.tests.helpers import point_of, role
from farm.tests.test_stock import make_unit
from farm.water import read, sources

from sensors import bindings
from sensors.models import Binding, Channel, ChannelState

from . import SensorsCase, make_channel, make_connection, make_device, make_format

BINDER = ('view_binding', 'add_binding', 'change_binding', 'delete_binding', 'view_channel', 'view_samplingpoint',
          'view_system', 'view_equipment')


class BindingCase(SensorsCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.ras = System.objects.create(name='RAS 1', code='R1', site=cls.site, production_department=cls.hall)
        cls.t1 = make_unit('T-01', cls.hall, system=cls.ras)
        cls.t2 = make_unit('T-02', cls.hall, system=cls.ras)
        cls.mid1, cls.mid2, cls.loop = point_of(cls.t1), point_of(cls.t2), point_of(cls.ras)
        cls.ph = make_channel(cls.device, 'ph')
        cls.flow = make_channel(cls.device, 'flow_m3_h')
        cls.start = timezone.now().replace(microsecond=0) - timedelta(days=10)

    def bind(self, channel, start=None, end=None, role='primary', **target):
        return Binding.objects.create(channel=channel, role=role, valid_from=start or self.start, valid_to=end, **target)

    def state(self, channel, value, seconds=10):
        at = timezone.now() - timedelta(seconds=seconds)
        ChannelState.objects.update_or_create(channel_no=channel.channel_no, defaults={
            'last_value': value, 'last_value_ts': at, 'last_good_at': at, 'last_seen_at': at})


class RuleTests(BindingCase):
    def test_exactly_one_target(self):
        self.refused('chk_sensors_binding_one_target', lambda: self.bind(self.ph))
        self.refused('chk_sensors_binding_one_target', lambda: self.bind(self.ph, point=self.mid1, system=self.ras))

    def test_the_end_comes_after_the_start(self):
        self.refused('chk_sensors_binding_period', lambda: self.bind(self.ph, end=self.start, point=self.mid1))

    def test_a_channel_is_bound_once_at_a_time(self):
        self.bind(self.ph, end=self.start + timedelta(days=2), point=self.mid1)
        self.refused('ex_sensors_binding_channel_period',
                     lambda: self.bind(self.ph, start=self.start + timedelta(days=1), point=self.mid2))
        self.bind(self.ph, start=self.start + timedelta(days=2), point=self.mid2)        # touching ends: allowed

    def test_a_deleted_binding_does_not_count(self):
        first = self.bind(self.ph, point=self.mid1)
        first.soft_delete(self.user)
        self.bind(self.ph, point=self.mid2)

    def test_one_primary_per_target_and_quantity_at_a_time(self):
        other = make_channel(self.device, 'ph', code='PH-2')
        self.bind(self.ph, point=self.mid1)
        with self.assertRaisesMessage(Exception, 'already has a primary ph channel'):
            self.bind(other, point=self.mid1)
        self.bind(other, point=self.mid1, role='backup')
        third = make_channel(self.device, 'ph', code='PH-3')
        with self.assertRaisesMessage(Exception, 'already has a backup ph channel'):
            self.bind(third, point=self.mid1, role='backup')
        self.bind(third, point=self.mid2)                                     # another point: allowed

    def test_water_goes_to_a_point_or_a_system_and_process_values_to_equipment_or_a_system(self):
        from farm.models import Equipment, EquipmentType
        pump = Equipment.objects.create(name='Pump', code='P1', production_department=self.hall,
                                        equipment_type=EquipmentType.objects.order_by('code').first())
        with self.assertRaisesMessage(Exception, 'A water value is bound to a sampling point or a system'):
            self.bind(self.ph, equipment=pump)
        with self.assertRaisesMessage(Exception, 'A process value is bound to a piece of equipment or a system'):
            self.bind(self.flow, point=self.mid1)
        self.bind(self.ph, system=self.ras)
        self.bind(self.flow, equipment=pump, start=self.start)


class MoveTests(BindingCase):
    def test_moving_closes_the_open_binding_and_opens_the_next_with_one_log_entry(self):
        first = bindings.move(self.user, self.ph, point=self.mid1, at=self.start)
        moved_at = self.start + timedelta(days=3)
        second = bindings.move(self.user, self.ph, point=self.mid2, at=moved_at)
        first.refresh_from_db()
        self.assertEqual((first.valid_to, second.valid_from, second.valid_to), (moved_at, moved_at, None))
        self.assertEqual(AuditLog.objects.filter(entity_id=str(self.ph.pk), action='update').count(), 2)
        self.assertEqual(first.version, 2)

    def test_a_move_before_the_open_binding_started_is_refused(self):
        bindings.move(self.user, self.ph, point=self.mid1, at=self.start)
        with self.assertRaises(ValidationError):
            bindings.move(self.user, self.ph, point=self.mid2, at=self.start - timedelta(hours=1))

    def test_a_move_in_the_future_is_refused(self):
        with self.assertRaises(ValidationError):
            bindings.move(self.user, self.ph, point=self.mid1, at=timezone.now() + timedelta(hours=1))

    def test_unbinding_closes_the_open_binding(self):
        first = bindings.move(self.user, self.ph, point=self.mid1, at=self.start)
        bindings.unbind(self.user, self.ph, at=self.start + timedelta(days=1))
        first.refresh_from_db()
        self.assertEqual(first.valid_to, self.start + timedelta(days=1))


class WaterReadTests(BindingCase):
    def test_a_bound_fresh_channel_is_the_points_value_with_its_origin(self):
        bindings.move(self.user, self.ph, point=self.mid1, at=self.start)
        self.state(self.ph, 7.333)
        reading = read.latest([self.mid1])[self.mid1.pk].get('ph')
        self.assertEqual((str(reading.value), reading.sample.origin, reading.sample.channel_no),
                         ('7.33', read.Origin.SENSOR, self.ph.channel_no))
        self.assertEqual(reading.sample.fresh_for, self.ph.fresh_s)

    def test_the_systems_channel_is_the_units_and_its_loops(self):
        temperature = make_channel(self.device, 'temperature_c')
        bindings.move(self.user, temperature, system=self.ras, at=self.start)
        self.state(temperature, 9.46)
        water = read.latest([self.mid1, self.loop])
        self.assertEqual(water[self.mid1.pk].get('temperature_c').sample.origin, read.Origin.SYSTEM_SENSOR)
        self.assertEqual(str(water[self.loop.pk].get('temperature_c').value), '9.5')

    def test_a_channel_in_maintenance_or_retired_is_skipped(self):
        bindings.move(self.user, self.ph, point=self.mid1, at=self.start)
        self.state(self.ph, 7.3)
        for state in ('maintenance', 'retired'):
            Channel.objects.filter(pk=self.ph.pk).update(state=state)
            self.assertIsNone(read.latest([self.mid1])[self.mid1.pk].get('ph'), state)

    def test_an_ended_binding_or_a_deleted_channel_gives_no_value(self):
        binding = bindings.move(self.user, self.ph, point=self.mid1, at=self.start)
        self.state(self.ph, 7.3)
        bindings.unbind(self.user, self.ph, at=timezone.now() - timedelta(minutes=1))
        self.assertIsNone(read.latest([self.mid1])[self.mid1.pk].get('ph'))
        Binding.objects.filter(pk=binding.pk).update(valid_to=None)
        self.ph.soft_delete(self.user)
        self.assertIsNone(read.latest([self.mid1])[self.mid1.pk].get('ph'))

    def test_a_deleted_points_bindings_are_hidden_and_return_with_it(self):
        bindings.move(self.user, self.ph, point=self.mid1, at=self.start)
        self.state(self.ph, 7.3)
        self.t1.soft_delete(self.user)
        self.assertEqual(Binding.objects.visible().count(), 0)
        restore(type(self.t1).all_objects.get(pk=self.t1.pk), self.user)
        self.assertEqual(Binding.objects.visible().count(), 1)
        self.assertIsNotNone(read.latest([self.mid1])[self.mid1.pk].get('ph'))

    def test_a_moved_sensors_history_stays_with_the_unit_it_was_in(self):
        moved_at = timezone.now() - timedelta(days=2)
        bindings.move(self.user, self.ph, point=self.mid1, at=self.start)
        bindings.move(self.user, self.ph, point=self.mid2, at=moved_at)
        with connection.cursor() as cursor:
            cursor.execute('INSERT INTO sensors_reading (channel_no, ts, value) VALUES (%s, %s, 7.1), (%s, %s, 7.6)',
                           [self.ph.channel_no, moved_at - timedelta(hours=1), self.ph.channel_no,
                            moved_at + timedelta(hours=1)])
        before = moved_at - timedelta(minutes=30)
        after = moved_at + timedelta(hours=2)
        answer = sources.value_at([(sources.POINT, self.mid1.pk), (sources.POINT, self.mid2.pk)], 'ph', before)
        self.assertEqual([value.value for value in answer.values.get((sources.POINT, self.mid1.pk), [])], [7.1])
        self.assertEqual(answer.values.get((sources.POINT, self.mid2.pk), []), [])
        answer = sources.value_at([(sources.POINT, self.mid1.pk), (sources.POINT, self.mid2.pk)], 'ph', after)
        self.assertEqual([value.value for value in answer.values.get((sources.POINT, self.mid2.pk), [])], [7.6])
        self.assertEqual([value.value for value in answer.values.get((sources.POINT, self.mid1.pk), [])], [7.1])

    def test_a_bad_reading_is_never_the_value_at_a_moment(self):
        bindings.move(self.user, self.ph, point=self.mid1, at=self.start)
        moment = timezone.now() - timedelta(hours=1)
        with connection.cursor() as cursor:
            cursor.execute('INSERT INTO sensors_reading (channel_no, ts, value, quality) VALUES (%s, %s, 7.1, 0), '
                           '(%s, %s, 3.0, 16)', [self.ph.channel_no, moment - timedelta(minutes=5),
                                                 self.ph.channel_no, moment - timedelta(minutes=1)])
        answer = sources.value_at([(sources.POINT, self.mid1.pk)], 'ph', moment)
        self.assertEqual([value.value for value in answer.values[(sources.POINT, self.mid1.pk)]], [7.1])


class PageTests(BindingCase):
    def setUp(self):
        self.binder = get_user_model().objects.create_user('binder', 'binder@example.com', 'x')
        self.binder.groups.add(role('Binder', *BINDER))
        self.client.force_login(self.binder)

    def test_the_move_dialog_binds_and_the_list_shows_the_history(self):
        url = reverse('sensors:binding_create')
        response = self.client.post(url, {'channel': self.ph.pk, 'target': f'point:{self.mid1.pk}', 'role': 'primary',
                                           'valid_from': self.start.strftime('%Y-%m-%dT%H:%M'), 'note': 'probe in'})
        self.assertIn(response.status_code, (204, 302), response.context and response.context['form'].errors)
        binding = Binding.objects.get()
        self.assertEqual((binding.point, binding.role, binding.note, binding.created_by),
                         (self.mid1, 'primary', 'probe in', self.binder))
        listing = self.client.get(reverse('sensors:binding_list'))
        self.assertContains(listing, 'T-01 › Middle')
        response = self.client.post(url, {'channel': self.ph.pk, 'target': f'system:{self.ras.pk}', 'role': 'primary',
                                          'valid_from': (self.start + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M')})
        self.assertIn(response.status_code, (204, 302))
        self.assertEqual(Binding.objects.count(), 2)
        binding.refresh_from_db()
        self.assertIsNotNone(binding.valid_to)

    def test_the_form_offers_only_targets_the_channels_kind_allows(self):
        response = self.client.post(reverse('sensors:binding_create'), {
            'channel': self.flow.pk, 'target': f'point:{self.mid1.pk}', 'role': 'primary',
            'valid_from': self.start.strftime('%Y-%m-%dT%H:%M')})
        self.assertContains(response, 'A process value is bound to a piece of equipment or a system')

    def test_an_edit_changes_only_the_end_and_the_note(self):
        binding = bindings.move(self.user, self.ph, point=self.mid1, at=self.start)
        form = self.client.get(reverse('sensors:binding_edit', args=[binding.pk])).context['form']
        self.assertEqual(set(form.fields) - {'version'}, {'valid_to', 'note'})

    def test_without_the_right_no_binding(self):
        reader = get_user_model().objects.create_user('reader', 'reader@example.com', 'x')
        reader.groups.add(role('Reader', 'view_binding'))
        self.client.force_login(reader)
        self.assertEqual(self.client.get(reverse('sensors:binding_create')).status_code, 403)


class ConcurrencyTests(TransactionTestCase):
    """Two people binding a primary pH channel to the same point at the same moment: the trigger takes a lock per target
    and quantity before it looks, so the second waits and is refused."""
    serialized_rollback = True

    def test_two_concurrent_primaries_on_one_point_one_is_refused(self):
        site = Site.objects.create(name='Bergen', code='BG')
        hall = ProductionDepartment.objects.create(site=site, name='Hall', code='H')
        point = point_of(make_unit('T-09', hall))
        device = make_device(make_connection(), make_format(), site)
        first, second = make_channel(device, 'ph', code='PH-A'), make_channel(device, 'ph', code='PH-B')
        params = connection.get_connection_params()
        dsn = {key: params[key] for key in ('dbname', 'user', 'password', 'host', 'port') if key in params}
        results, barrier = [], threading.Barrier(2)

        def insert(channel):
            with psycopg.connect(**dsn) as conn:
                try:
                    with conn.transaction():
                        barrier.wait()
                        conn.execute(
                            'INSERT INTO sensors_binding (id, created_at, updated_at, version, is_deleted, channel_id, '
                            'point_id, role, valid_from, note) VALUES (gen_random_uuid(), now(), now(), 1, false, %s, %s, '
                            "'primary', now() - interval '1 day', '')", [channel.pk, point.pk])
                    results.append('ok')
                except psycopg.Error as error:
                    results.append(type(error).__name__)

        threads = [threading.Thread(target=insert, args=(channel,)) for channel in (first, second)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(20)
        self.assertEqual(sorted(results), ['CheckViolation', 'ok'])

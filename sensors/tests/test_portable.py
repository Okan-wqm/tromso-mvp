"""Portable sensors: a probe (a device with several channels) is taken from one tank or system to another, maybe at
another site, or out of the water. `bindings.move_device` moves every channel of the device from one moment, in one
transaction, with one entry on the device's log, each channel to the place its kind goes to at the target (a water value
to the unit's middle point, the point chosen or the system; a process value to the system or the piece of equipment),
and refuses the whole move, saying why for each channel, when one cannot go there. `bindings.unbind_device` takes it out:
its readings are stored and belong nowhere until it is placed again."""
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.utils import timezone

from core.models import AuditLog
from farm.models import Equipment, EquipmentType, System
from farm.tests.helpers import point_of
from farm.tests.test_stock import make_unit

from sensors import bindings
from sensors.models import Binding, Channel

from . import SensorsCase, make_channel, make_device


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

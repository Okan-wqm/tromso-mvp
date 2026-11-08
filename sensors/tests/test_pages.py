"""The sensors configuration pages (core.crud tabs), each checked against the stored row: every form field created, read,
edited and its edit kept; a stale version refused; the delete plan (a connection takes its devices and channels with it,
a payload format or a credential in use blocks) and the restore; the service rules a form says in words (a deadband finer
than the quantity's precision, a heartbeat shorter than the device's interval, a range outside the catalogue, a value path
on a list format); the calibration rows of a channel saved as a list; the credential's secret shown once and never stored
or logged; the menu panel, the role matrix and the rights of each area."""
import base64
import hashlib
import hmac
from datetime import datetime, timezone as tz

from django.contrib.auth import get_user_model
from django.urls import reverse

from core import access, navigation
from core.models import AuditLog
from core.softdelete import plan_delete, restore
from farm.models import Equipment, EquipmentType
from farm.tests.helpers import role, rows_data

from sensors import credentials, quantities
from sensors.models import Calibration, Channel, Connection, Credential, Device, PayloadFormat

from . import SensorsCase, make_channel, make_device

ALL = ('view', 'add', 'change', 'delete')
MODELS = ('connection', 'payloadformat', 'device', 'channel', 'credential')
CLASSES = {'connection': Connection, 'payloadformat': PayloadFormat, 'device': Device, 'channel': Channel,
           'credential': Credential}


def url(model, action, pk=None):
    name = {'list': 'list', 'create': 'create', 'edit': 'edit', 'delete': 'delete'}[action]
    return reverse(f'sensors:{model}_{name}', args=[pk] if pk else [])


class PagesCase(SensorsCase):
    def setUp(self):
        self.keeper = get_user_model().objects.create_user('keeper', 'keeper@example.com', 'x')
        self.keeper.groups.add(role('Sensor keeper', *[f'{action}_{model}' for model in MODELS for action in ALL],
                                    'view_site', 'view_equipment'))
        self.client.force_login(self.keeper)

    def posted(self, kind, obj, **changes):
        form = self.client.get(url(kind, 'edit', obj.pk)).context['form']
        data = {}
        for name in form.fields:
            value = form[name].value()
            data[name] = '' if value is None else ('on' if value is True else value)
            if value is False:
                data.pop(name)
        return {**data, **changes}

    def round_trip(self, model, created_values, check, changes, changed):
        """Creates through the page, reads the stored row, edits every field given and reads it again."""
        response = self.client.post(url(model, 'create'), created_values)
        self.assertIn(response.status_code, (302, 204), response.context and response.context['form'].errors)
        Model = CLASSES[model]
        obj = Model.objects.order_by('-created_at').first()
        self.assertEqual(obj.created_by, self.keeper)
        self.assertEqual(obj.version, 1)
        for name, value in check.items():
            self.assertEqual(getattr(obj, name), value, name)
        self.assertContains(self.client.get(url(model, 'list')), str(obj))
        self.assertEqual(AuditLog.objects.filter(entity_id=str(obj.pk), action='create').count(), 1)
        response = self.client.post(url(model, 'edit', obj.pk), self.posted(model, obj, **changes))
        self.assertEqual(response.status_code, 302, response.context and response.context['form'].errors)
        obj.refresh_from_db()
        for name, value in changed.items():
            self.assertEqual(getattr(obj, name), value, name)
        self.assertEqual(obj.version, 2)
        return obj

    def stale_refused(self, kind, obj, field, mine, theirs):
        stale = self.posted(kind, obj, **{field: mine})
        self.client.post(url(kind, 'edit', obj.pk), self.posted(kind, obj, **{field: theirs}))
        response = self.client.post(url(kind, 'edit', obj.pk), stale, follow=True)
        obj.refresh_from_db()
        self.assertEqual(getattr(obj, field), theirs)
        self.assertContains(response, 'Someone else changed this')


class ConnectionPageTests(PagesCase):
    def test_round_trip_stale_version_delete_and_restore(self):
        connection = self.round_trip(
            'connection',
            {'name': 'Sea broker', 'is_active': 'on', 'host': 'broker.local', 'port': '1883', 'username': 'ingest-sea',
             'secret_file': 'sea_password', 'client_id': 'ingest-sea', 'keepalive_s': '30'},
            {'name': 'Sea broker', 'is_active': True, 'host': 'broker.local', 'port': 1883, 'use_tls': False,
             'username': 'ingest-sea', 'secret_file': 'sea_password', 'client_id': 'ingest-sea', 'keepalive_s': 30},
            {'name': 'Sea broker 2', 'host': 'b2.local', 'port': '8883', 'use_tls': 'on', 'username': '', 'secret_file': '',
             'client_id': 'ingest-sea-2', 'keepalive_s': '60', 'is_active': ''},
            {'name': 'Sea broker 2', 'host': 'b2.local', 'port': 8883, 'use_tls': True, 'username': '', 'secret_file': '',
             'client_id': 'ingest-sea-2', 'keepalive_s': 60, 'is_active': False})
        self.stale_refused('connection', connection, 'host', 'mine.local', 'theirs.local')
        device = make_device(connection, self.format, self.site, code='SEA-1')
        channel = make_channel(device, 'oxygen_mg_l')
        plan = plan_delete(connection)
        self.assertEqual(plan.blockers, [])
        self.assertEqual({type(record) for record in plan.cascade}, {Device, Channel})
        self.client.post(url('connection', 'delete', connection.pk))
        for record in (connection, device, channel):
            self.assertTrue(type(record).all_objects.get(pk=record.pk).is_deleted)
        restore(type(connection).all_objects.get(pk=connection.pk), self.keeper)   # with what its delete took along
        for record in (connection, device, channel):
            self.assertFalse(type(record).all_objects.get(pk=record.pk).is_deleted)

    def test_the_rules_reach_the_person_as_messages(self):
        base = {'name': 'X', 'host': 'h', 'port': '8883', 'client_id': 'c-x', 'keepalive_s': '60'}
        for changes, text in (({'name': 'hall broker'}, 'Another connection already has this name.'),
                              ({'client_id': 'ingest-hall-broker'}, 'Another connection already uses this client id.'),
                              ({'port': '70000'}, 'less than or equal to 65535'),
                              ({'secret_file': '../x'}, 'A file name only'),
                              ({'keepalive_s': '1'}, 'greater than or equal to 5')):
            with self.subTest(changes=changes):
                response = self.client.post(url('connection', 'create'), {**base, **changes})
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, text)


class PayloadFormatPageTests(PagesCase):
    def test_round_trip_and_a_format_in_use_cannot_be_deleted(self):
        created = self.round_trip(
            'payloadformat',
            {'name': 'Oxygen array', 'encoding': 'json', 'shape': 'array', 'time_path': '/t', 'time_unit': 'epoch_ms',
             'seq_path': '/seq', 'items_path': '/items', 'name_key': 'n', 'value_key': 'v'},
            {'name': 'Oxygen array', 'encoding': 'json', 'shape': 'array', 'time_path': '/t', 'time_unit': 'epoch_ms',
             'seq_path': '/seq', 'items_path': '/items', 'name_key': 'n', 'value_key': 'v'},
            {'shape': 'object', 'time_path': '', 'time_unit': 'iso8601', 'seq_path': '', 'items_path': '',
             'name_key': '', 'value_key': ''},
            {'shape': 'object', 'time_path': '', 'time_unit': 'iso8601', 'seq_path': '', 'items_path': '',
             'name_key': '', 'value_key': ''})
        self.assertEqual(plan_delete(created).blockers, [])
        self.assertTrue(plan_delete(self.format).blockers)                      # the probe uses it

    def test_a_list_format_needs_its_keys_and_paths_are_pointers(self):
        response = self.client.post(url('payloadformat', 'create'), {
            'name': 'Bad', 'encoding': 'json', 'shape': 'array', 'time_path': 'ts', 'time_unit': 'iso8601'})
        self.assertContains(response, 'A list of items needs the key that names the channel and the key of the value.')
        self.assertContains(response, 'A JSON pointer: empty, or starting with “/”.')


class DevicePageTests(PagesCase):
    def test_round_trip(self):
        pump = Equipment.objects.create(name='Probe rack', code='RACK', production_department=self.hall,
                                        equipment_type=EquipmentType.objects.order_by('code').first())
        credential = Credential.objects.create(username='gateway-1')
        device = self.round_trip(
            'device',
            {'connection': self.connection.pk, 'code': 'o2-12', 'name': 'Oxygen probe 12', 'site': self.site.pk,
             'equipment': pump.pk, 'manufacturer': 'Oxyguard', 'model': 'Pacific', 'note': 'Tank T-12',
             'is_active': 'on', 'payload_format': self.format.pk, 'topic': 'farm/o2/+', 'expected_interval_s': '5',
             'credential': credential.pk, 'is_simulated': 'on'},
            {'connection': self.connection, 'code': 'O2-12', 'name': 'Oxygen probe 12', 'site': self.site,
             'equipment': pump, 'manufacturer': 'Oxyguard', 'model': 'Pacific', 'note': 'Tank T-12', 'is_active': True,
             'payload_format': self.format, 'topic': 'farm/o2/+', 'expected_interval_s': 5, 'credential': credential,
             'is_simulated': True},
            {'equipment': '', 'manufacturer': '', 'model': '', 'note': '', 'is_active': '', 'topic': 'farm/o2/12',
             'expected_interval_s': '10', 'credential': '', 'is_simulated': ''},
            {'equipment': None, 'manufacturer': '', 'model': '', 'note': '', 'is_active': False, 'topic': 'farm/o2/12',
             'expected_interval_s': 10, 'credential': None, 'is_simulated': False})
        self.stale_refused('device', device, 'name', 'Mine', 'Theirs')
        self.assertContains(self.client.get(url('device', 'edit', self.device.pk)), self.channel.code)   # its channels

    def test_whole_second_times_need_an_interval_of_two_seconds_or_more(self):
        seconds = PayloadFormat.objects.create(name='Seconds', time_path='/t', time_unit='epoch_s')
        response = self.client.post(url('device', 'create'), {
            'connection': self.connection.pk, 'code': 'S-1', 'name': 'S', 'site': self.site.pk, 'is_active': 'on',
            'payload_format': seconds.pk, 'topic': 'farm/s', 'expected_interval_s': '1'})
        self.assertContains(response, 'Times in whole seconds cannot tell apart messages sent every second')

    def test_the_interval_cannot_pass_a_channels_heartbeat(self):
        response = self.client.post(url('device', 'edit', self.device.pk),
                                    self.posted('device', self.device, expected_interval_s='120'))
        self.assertContains(response, 'TEMPERATURE-C stores at least every 60 seconds')

    def test_the_topic_rules_reach_the_person(self):
        response = self.client.post(url('device', 'edit', self.device.pk),
                                    self.posted('device', self.device, topic='farm/#'))
        self.assertContains(response, 'A device’s topic has no “#”.')


class ChannelPageTests(PagesCase):
    def create(self, **changes):
        data = {'device': self.device.pk, 'code': 'ph-1', 'name': 'pH T-01', 'note': '', 'value_path': '/ph',
                'item_name': '', 'quantity': 'ph', 'unit': '', 'unit_factor': '1', 'unit_offset': '0',
                'address_protocol': 'mqtt', 'address': '{}', 'reduction': 'deadband', 'deadband': '',
                'heartbeat_s': '', 'range_min': '', 'range_max': '', 'state': 'active', **changes}
        return self.client.post(url('channel', 'create'), data)

    def test_round_trip(self):
        channel = self.round_trip(
            'channel',
            {'device': self.device.pk, 'code': 'ph-1', 'name': 'pH T-01', 'note': 'on the inlet', 'value_path': '/ph',
             'item_name': '', 'quantity': 'ph', 'unit': 'pH', 'unit_factor': '1', 'unit_offset': '0',
             'address_protocol': 'modbus_tcp', 'address': '{"unit_id": 1, "function": 3, "register": 40001}',
             'reduction': 'deadband', 'deadband': '0.05', 'heartbeat_s': '120', 'range_min': '4', 'range_max': '10',
             'state': 'active'},
            {'device': self.device, 'code': 'PH-1', 'name': 'pH T-01', 'note': 'on the inlet', 'value_path': '/ph',
             'quantity': 'ph', 'unit': 'pH', 'address_protocol': 'modbus_tcp',
             'address': {'unit_id': 1, 'function': 3, 'register': 40001}, 'reduction': 'deadband', 'deadband': 0.05,
             'heartbeat_s': 120, 'range_min': 4.0, 'range_max': 10.0, 'state': 'active'},
            {'name': 'pH T-01 inlet', 'note': '', 'unit_factor': '0.01', 'unit_offset': '-1', 'address_protocol': 'mqtt',
             'address': '{}', 'reduction': 'all', 'deadband': '0', 'heartbeat_s': '600', 'range_min': '',
             'range_max': '', 'state': 'maintenance'},
            {'name': 'pH T-01 inlet', 'note': '', 'unit_factor': 0.01, 'unit_offset': -1.0, 'address': {},
             'reduction': 'all', 'deadband': 0.0, 'heartbeat_s': 600, 'range_min': None, 'range_max': None,
             'state': 'maintenance'})
        channel.refresh_from_db()
        self.assertEqual(channel.fresh_s, 1800)
        self.stale_refused('channel', channel, 'name', 'Mine', 'Theirs')
        self.client.post(url('channel', 'delete', channel.pk))
        self.assertTrue(Channel.all_objects.get(pk=channel.pk).is_deleted)

    def test_blank_reduction_fields_take_the_quantitys_defaults(self):
        self.create(quantity='oxygen_mg_l', code='o2-1', value_path='/o2', reduction='')
        channel = Channel.objects.get(code='O2-1')
        for name, value in quantities.defaults('oxygen_mg_l').items():
            self.assertEqual(getattr(channel, name), value, name)
        self.assertEqual(channel.reduction, 'all')

    def test_changing_the_quantity_on_a_new_channel_shows_its_defaults(self):
        response = self.client.post(url('channel', 'create'), {
            'device': self.device.pk, 'quantity': 'salinity_ppt', 'deadband': '9', '_draft': 'quantity'})
        form = response.context['form']
        self.assertEqual((form['deadband'].value(), form['heartbeat_s'].value(), form['unit'].value()),
                         (0.2, 600, '‰'))

    def test_the_service_rules(self):
        for changes, text in (
                ({'deadband': '0.001'}, 'finer than the precision of pH (NBS scale), 0.01'),
                ({'heartbeat_s': '10'}, None),
                ({'range_min': '1', 'range_max': '13'}, 'outside what pH (NBS scale) can be: 2 to 12'),
                ({'value_path': '', 'item_name': 'ph'}, 'the device’s payload format is one object'),
                ({'address_protocol': 'opcua', 'address': '{}'}, 'The address lacks a key its protocol needs.'),
                ({'address': '[1, 2]'}, 'The address is a JSON object')):
            with self.subTest(changes=changes):
                response = self.create(**changes)
                if text is None:
                    self.assertIn(response.status_code, (204, 302))
                    Channel.objects.filter(code='PH-1').delete()
                else:
                    self.assertEqual(response.status_code, 200)
                    self.assertContains(response, text)
        Device.objects.filter(pk=self.device.pk).update(expected_interval_s=30)
        self.assertContains(self.create(heartbeat_s='20'), 'shorter than the 30 seconds the device sends every')

    def test_calibrations_are_saved_as_a_list_and_logged_on_the_channel(self):
        rows = [{'valid_from': '2026-11-01 08:00', 'gain': '1.02', 'offset': '-0.1', 'performed_by': 'Kari',
                 'note': 'two-point'}, {'valid_from': '2026-11-20 08:00', 'gain': '1', 'offset': '0',
                                        'performed_by': '', 'note': ''}]
        data = {**rows_data('calibrations', rows, record=self.channel), 'version': self.channel.version}
        response = self.client.post(reverse('sensors:channel_calibrations', args=[self.channel.pk]), data)
        self.assertIn(response.status_code, (204, 302))
        stored = list(Calibration.objects.filter(channel=self.channel).order_by('valid_from'))
        self.assertEqual([(row.gain, row.offset, row.performed_by, row.created_by) for row in stored],
                         [(1.02, -0.1, 'Kari', self.keeper), (1.0, 0.0, '', self.keeper)])
        self.assertTrue(AuditLog.objects.filter(entity_id=str(self.channel.pk), action='update').exists())
        self.channel.refresh_from_db()
        self.assertEqual(self.channel.version, 2)


class CredentialPageTests(PagesCase):
    def test_the_secret_is_shown_once_stored_as_a_hash_and_never_logged(self):
        response = self.client.post(url('credential', 'create'), {'username': 'gateway-7', 'is_enabled': 'on'})
        secret = response.context['secret']
        self.assertContains(response, secret)
        credential = Credential.objects.get(username='gateway-7')
        self.assertTrue(credentials.verify(secret, credential.password_hash))
        self.assertFalse(credentials.verify(secret + 'x', credential.password_hash))
        self.assertIsNotNone(credential.rotated_at)
        logged = ' '.join(str(entry.changes) for entry in AuditLog.objects.filter(entity_id=str(credential.pk)))
        self.assertNotIn(secret, logged)
        self.assertNotIn(credential.password_hash, logged)
        self.assertNotIn('password_hash', self.client.get(url('credential', 'edit', credential.pk)).content.decode())
        # rotating makes a new secret, shown once; the old one no longer signs in
        rotated = self.client.post(reverse('sensors:credential_rotate', args=[credential.pk]),
                                   {'version': credential.version})
        new_secret = rotated.context['secret']
        credential.refresh_from_db()
        self.assertTrue(credentials.verify(new_secret, credential.password_hash))
        self.assertFalse(credentials.verify(secret, credential.password_hash))
        self.assertEqual(credential.version, 2)
        entry = AuditLog.objects.filter(entity_id=str(credential.pk), action='update').get()
        self.assertEqual(entry.changes, {'Secret': ['(replaced)', '(replaced)']})
        self.assertNotIn(new_secret, self.client.get(url('credential', 'edit', credential.pk)).content.decode())

    def test_a_rotation_on_an_old_version_is_refused(self):
        credential = Credential.objects.create(username='gateway-8')
        response = self.client.post(reverse('sensors:credential_rotate', args=[credential.pk]),
                                    {'version': credential.version + 1}, follow=True)
        self.assertContains(response, 'Someone else changed this sensor credential')
        credential.refresh_from_db()
        self.assertEqual(credential.password_hash, '')

    def test_the_hash_is_mosquittos_pbkdf2_sha512_line(self):
        # Lines written by mosquitto_passwd 2.0.20 (sensors-ingest/spikes/s0f_mosquitto_hash.py), read back here.
        line = ('$7$101$eNpewiJraEJc6yAU$FA/w3SuMmL8poIy/iwcWjnlXtjIl+310YExJ7J5vkS3urYVSaj0T/Q+MkNVuVkFnTxGOueGZ5hEm'
                'w/pDndsEiA==')
        self.assertTrue(credentials.verify('s3cret-Pw', line))
        made = credentials.hash_secret('abc')
        kind, iterations, salt, digest = made.split('$')[1:]
        self.assertEqual((kind, len(base64.b64decode(salt)), len(base64.b64decode(digest))), ('7', 12, 64))
        expected = hashlib.pbkdf2_hmac('sha512', b'abc', base64.b64decode(salt), int(iterations), 64)
        self.assertTrue(hmac.compare_digest(base64.b64decode(digest), expected))
        self.assertGreaterEqual(len(credentials.new_secret()), 32)

    def test_a_credential_in_use_cannot_be_deleted(self):
        credential = Credential.objects.create(username='gateway-9')
        Device.objects.filter(pk=self.device.pk).update(credential=credential)
        self.assertTrue(plan_delete(credential).blockers)


class RightsTests(PagesCase):
    def test_each_area_needs_its_own_right(self):
        reader = get_user_model().objects.create_user('reader', 'reader@example.com', 'x')
        reader.groups.add(role('Reader', 'view_connection'))
        self.client.force_login(reader)
        self.assertEqual(self.client.get(url('connection', 'list')).status_code, 200)
        self.assertEqual(self.client.get(url('connection', 'create')).status_code, 403)
        for model in ('device', 'channel', 'payloadformat', 'credential'):
            self.assertEqual(self.client.get(url(model, 'list')).status_code, 403, model)

    def test_the_matrix_and_the_menu_place_the_sensors_in_their_panel(self):
        groups = {area.model: str(area.group) for area in access.areas() if area.model.startswith('sensors.')}
        self.assertEqual(groups['sensors.Connection'], 'Sensors · Setup')
        self.assertEqual(groups['sensors.Credential'], 'Sensors · Administration')
        self.assertEqual(navigation.place('sensors.view_channel').workspace.key, 'sensors')
        panels = [panel['key'] for panel in self.client.get(url('channel', 'list')).context['workspaces']]
        self.assertIn('sensors', panels)

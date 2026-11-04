"""The rules the database holds for the sensors configuration: every CHECK, every unique-among-live constraint, the
channel number drawn from a sequence and never reused, and the generated columns. Each is refused by the database
itself (an IntegrityError naming the constraint), whatever wrote the row."""
from datetime import datetime, timezone as tz

from django.db import connection
from django.test import TestCase

from sensors import quantities
from sensors.models import Calibration, Channel, Connection, Credential, Device, PayloadFormat

from . import SensorsCase, make_channel, make_connection, make_device, make_format, one

INF, NAN = float('inf'), float('nan')


class ConnectionRulesTests(SensorsCase):
    def test_name_and_client_id_are_unique_among_live_connections(self):
        self.refused('uq_sensors_connection_name_live', lambda: make_connection('HALL BROKER', client_id='other'))
        self.refused('uq_sensors_connection_client_live', lambda: make_connection('Other', client_id='ingest-hall-broker'))
        self.connection.soft_delete(self.user)
        make_connection('Hall broker')                      # a deleted one frees its name and client id

    def test_checks(self):
        for constraint, fields in (
                ('chk_sensors_connection_name', {'name': ''}),
                ('chk_sensors_connection_host', {'host': ''}),
                ('chk_sensors_connection_client_id', {'client_id': ''}),
                ('chk_sensors_connection_port', {'port': 0}),
                ('chk_sensors_connection_port', {'port': 65536}),
                ('chk_sensors_connection_keepalive', {'keepalive_s': 4}),
                ('chk_sensors_connection_keepalive', {'keepalive_s': 601}),
                ('chk_sensors_connection_secret_file', {'secret_file': '../etc/passwd'}),
                ('chk_sensors_connection_secret_file', {'secret_file': 'a/b'}),
                ('chk_sensors_connection_secret_dots', {'secret_file': '..'})):
            with self.subTest(fields=fields):
                self.refused(constraint, lambda: Connection.objects.filter(pk=self.connection.pk).update(**fields))


class PayloadFormatRulesTests(SensorsCase):
    def test_checks(self):
        for constraint, fields in (
                ('chk_sensors_payload_format_name', {'name': ''}),
                ('chk_sensors_payload_format_encoding', {'encoding': 'xml'}),
                ('chk_sensors_payload_format_shape', {'shape': 'csv', 'name_key': 'n', 'value_key': 'v'}),
                ('chk_sensors_payload_format_time_unit', {'time_unit': 'epoch_us'}),
                ('chk_sensors_payload_format_array_keys', {'shape': 'array', 'name_key': '', 'value_key': 'v'}),
                ('chk_sensors_payload_format_array_keys', {'shape': 'array', 'name_key': 'n', 'value_key': ''}),
                ('chk_sensors_payload_format_time_path', {'time_path': 'ts'}),
                ('chk_sensors_payload_format_seq_path', {'seq_path': 'a/b'}),
                ('chk_sensors_payload_format_items_path', {'items_path': '/a/~2'})):
            with self.subTest(fields=fields):
                self.refused(constraint, lambda: PayloadFormat.objects.filter(pk=self.format.pk).update(**fields))

    def test_an_array_format_with_both_keys_and_pointers_with_escapes_are_accepted(self):
        PayloadFormat.objects.filter(pk=self.format.pk).update(shape='array', items_path='/data/~1items~0x', name_key='n',
                                                               value_key='v', time_path='')

    def test_the_name_is_unique_among_live_formats(self):
        self.refused('uq_sensors_payload_format_name_live', lambda: make_format('probe json'))


class CredentialRulesTests(SensorsCase):
    def test_the_username_is_unique_and_has_no_colon_or_space(self):
        Credential.objects.create(username='gateway-1', password_hash='')
        self.refused('uq_sensors_credential_username_live', lambda: Credential.objects.create(username='GATEWAY-1'))
        self.refused('chk_sensors_credential_username', lambda: Credential.objects.create(username='a:b'))
        self.refused('chk_sensors_credential_username', lambda: Credential.objects.create(username='a b'))

    def test_the_hash_is_mosquittos_format_or_empty(self):
        self.refused('chk_sensors_credential_hash',
                     lambda: Credential.objects.create(username='g2', password_hash='plain-secret'))
        Credential.objects.create(username='g3', password_hash='$7$101$c2FsdA==$aGFzaA==')


class DeviceRulesTests(SensorsCase):
    def test_code_and_topic_are_unique_per_connection_among_live_devices(self):
        self.refused('uq_sensors_device_code_live', lambda: make_device(self.connection, self.format, self.site,
                                                                         code='PROBE-1', topic='other'))
        self.refused('uq_sensors_device_topic_live', lambda: make_device(self.connection, self.format, self.site,
                                                                          code='PROBE-2', topic='farm/hall/probe-1'))
        other = make_connection('Sea broker')
        make_device(other, self.format, self.site, code='PROBE-1')        # another connection may reuse both

    def test_topic_rules(self):
        for constraint, topic in (
                ('chk_sensors_device_topic_given', ''),
                ('chk_sensors_device_topic_hash', 'farm/#'),
                ('chk_sensors_device_topic_system', '$SYS/broker'),
                ('chk_sensors_device_topic_plus', 'farm/+/x/+'),
                ('chk_sensors_device_topic_level', 'farm/probe+1')):
            with self.subTest(topic=topic):
                self.refused(constraint, lambda: Device.objects.filter(pk=self.device.pk).update(topic=topic))
        for topic in ('farm/+/probe', '+', '+/x', 'x/+'):
            Device.objects.filter(pk=self.device.pk).update(topic=topic)

    def test_checks(self):
        for constraint, fields in (
                ('chk_sensors_device_code', {'code': 'probe 1'}),
                ('chk_sensors_device_name', {'name': ''}),
                ('chk_sensors_device_interval', {'expected_interval_s': 0}),
                ('chk_sensors_device_interval', {'expected_interval_s': 86401})):
            with self.subTest(fields=fields):
                self.refused(constraint, lambda: Device.objects.filter(pk=self.device.pk).update(**fields))


class ChannelRulesTests(SensorsCase):
    def update(self, **fields):
        return lambda: Channel.objects.filter(pk=self.channel.pk).update(**fields)

    def test_checks(self):
        for constraint, fields in (
                ('chk_sensors_channel_code', {'code': 'a b'}),
                ('chk_sensors_channel_name', {'name': ''}),
                ('chk_sensors_channel_quantity', {'quantity': 'colour'}),
                ('chk_sensors_channel_unit_factor', {'unit_factor': 0}),
                ('chk_sensors_channel_unit_factor', {'unit_factor': INF}),
                ('chk_sensors_channel_unit_factor', {'unit_factor': NAN}),
                ('chk_sensors_channel_unit_offset', {'unit_offset': NAN}),
                ('chk_sensors_channel_source', {'value_path': '', 'item_name': ''}),
                ('chk_sensors_channel_source', {'value_path': '/t', 'item_name': 't'}),
                ('chk_sensors_channel_value_path', {'value_path': 'temperature'}),
                ('chk_sensors_channel_protocol', {'address_protocol': 'profibus'}),
                ('chk_sensors_channel_address', {'address_protocol': 'modbus_tcp', 'address': {'unit_id': 1}}),
                ('chk_sensors_channel_address', {'address_protocol': 's7', 'address': {'db': 1}}),
                ('chk_sensors_channel_address', {'address_protocol': 'opcua', 'address': {}}),
                ('chk_sensors_channel_reduction', {'reduction': 'swing'}),
                ('chk_sensors_channel_deadband', {'reduction': 'deadband', 'deadband': 0}),
                ('chk_sensors_channel_deadband', {'reduction': 'all', 'deadband': -1}),
                ('chk_sensors_channel_deadband', {'deadband': NAN}),
                ('chk_sensors_channel_heartbeat', {'heartbeat_s': 9}),
                ('chk_sensors_channel_heartbeat', {'heartbeat_s': 86401}),
                ('chk_sensors_channel_range', {'range_min': 1, 'range_max': None}),
                ('chk_sensors_channel_range', {'range_min': 5, 'range_max': 5}),
                ('chk_sensors_channel_range', {'range_min': -INF, 'range_max': 5}),
                ('chk_sensors_channel_state', {'state': 'broken'})):
            with self.subTest(fields=fields):
                self.refused(constraint, self.update(**fields))

    def test_accepted_addresses_and_open_ranges(self):
        self.update(address_protocol='modbus_tcp', address={'unit_id': 1, 'function': 3, 'register': 40001})()
        self.update(address_protocol='opcua', address={'node_id': 'ns=2;s=T1'})()
        self.update(address_protocol='mqtt', address={})()
        self.update(range_min=None, range_max=None, reduction='all', deadband=0)()

    def test_the_code_is_unique_per_device_among_live_channels(self):
        self.refused('uq_sensors_channel_code_live', lambda: make_channel(self.device, 'ph', code='temperature-c'))
        self.channel.soft_delete(self.user)
        make_channel(self.device, 'ph', code='TEMPERATURE-C')

    def test_channel_numbers_come_from_the_sequence_and_are_never_reused(self):
        second = make_channel(self.device, 'ph')
        self.assertGreater(second.channel_no, self.channel.channel_no)        # set on the instance after the insert
        number = second.channel_no
        Channel.all_objects.filter(pk=second.pk).delete()                   # even a hard delete frees no number
        third = make_channel(self.device, 'ph')
        self.assertGreater(third.channel_no, number)
        self.refused('sensors_channel_channel_no_key', lambda: Channel.objects.filter(pk=third.pk)
                     .update(channel_no=self.channel.channel_no))

    def test_is_water_and_fresh_s_are_worked_out_by_the_database(self):
        flow = make_channel(self.device, 'flow_m3_h')
        self.channel.refresh_from_db()
        flow.refresh_from_db()
        self.assertTrue(self.channel.is_water)
        self.assertFalse(flow.is_water)
        self.assertEqual(self.channel.fresh_s, 3 * self.channel.heartbeat_s)
        Channel.objects.filter(pk=flow.pk).update(heartbeat_s=100)
        flow.refresh_from_db()
        self.assertEqual(flow.fresh_s, 300)
        water = set(one("SELECT array_agg(quantity) FROM sensors_channel WHERE is_water") or [])
        self.assertEqual(water, {'temperature_c'})

    def test_every_catalogue_default_is_a_row_the_database_accepts(self):
        for number, quantity in enumerate(quantities.CODES):
            with self.subTest(quantity=quantity):
                channel = make_channel(self.device, quantity, code=f'Q{number}')
                channel.refresh_from_db()
                for name, value in quantities.defaults(quantity).items():
                    self.assertEqual(getattr(channel, name), value, name)


class CalibrationRulesTests(SensorsCase):
    def test_checks_and_one_row_per_moment(self):
        moment = datetime(2026, 11, 1, tzinfo=tz.utc)
        Calibration.objects.create(channel=self.channel, valid_from=moment, gain=1.02, offset=-0.1)
        self.refused('uq_sensors_calibration_from',
                     lambda: Calibration.objects.create(channel=self.channel, valid_from=moment))
        self.refused('chk_sensors_calibration_gain',
                     lambda: Calibration.objects.create(channel=self.channel, valid_from=moment.replace(day=2), gain=0))
        self.refused('chk_sensors_calibration_offset',
                     lambda: Calibration.objects.create(channel=self.channel, valid_from=moment.replace(day=3),
                                                        offset=INF))


class CatalogueTests(TestCase):
    def test_the_quantity_check_lists_the_catalogue(self):
        definition = one("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'chk_sensors_channel_quantity'")
        for code in quantities.CODES:
            self.assertIn(f"'{code}'", definition)

    def test_water_quantities_are_the_measured_water_parameters(self):
        from farm.water import parameters
        self.assertEqual(quantities.WATER_CODES, parameters.COLUMNS)
        for quantity in quantities.WATER:
            self.assertGreaterEqual(quantity.deadband, quantity.parameter.step, quantity.code)
            self.assertEqual((quantity.low, quantity.high), (quantity.parameter.low, quantity.parameter.high))

    def test_oxygen_and_temperature_keep_every_value_by_default(self):
        for code in ('temperature_c', 'oxygen_mg_l', 'oxygen_saturation_pct'):
            self.assertEqual(quantities.get(code).reduction, quantities.ALL)

    def test_the_sequence_belongs_to_the_column(self):
        owner = one("SELECT a.attname FROM pg_depend d JOIN pg_attribute a ON a.attrelid = d.refobjid "
                    "AND a.attnum = d.refobjsubid WHERE d.objid = 'sensors_channel_no_seq'::regclass "
                    "AND d.deptype = 'a'")
        self.assertEqual(owner, 'channel_no')

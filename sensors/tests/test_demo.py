"""manage.py sensors_demo_setup: the live demo's sensors for the tanks and systems a database already has (one connection,
the payload format, a device per tank and per system with 7-8 water channels, together every measured parameter, bound to
the tank's middle point or to the system, a simulator credential), idempotent, refused unless confirmed, removable with
`--remove` without touching any other configuration; and every parameter's reading shows on the water page with its
origin and age and in the tank's and the system's charts."""
from datetime import timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.db import connection
from django.urls import reverse
from django.utils import timezone

from farm.models import System
from farm.tests.helpers import point_of
from farm.tests.test_stock import make_unit
from farm.water import parameters, read as water_read

from sensors import demo, read
from sensors.models import Binding, Channel, ChannelState, Connection, Credential, Device, PayloadFormat

from . import SensorsCase


class DemoCase(SensorsCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.ras = System.objects.create(name='RAS 1', code='R1', site=cls.site, production_department=cls.hall)
        cls.units = [make_unit(f'T-{number:02d}', cls.hall, system=cls.ras) for number in range(1, 4)]
        cls.middles = [point_of(unit) for unit in cls.units]
        point_of(cls.ras)

    def setup_demo(self, *extra):
        out = StringIO()
        call_command('sensors_demo_setup', '--confirm', *extra, stdout=out)
        return out.getvalue()


class SetupTests(DemoCase):
    def test_it_refuses_without_a_flag(self):
        with self.assertRaises(CommandError):
            call_command('sensors_demo_setup', stdout=StringIO())

    def test_a_device_per_tank_and_system_with_every_measured_parameter_bound_in_place(self):
        out = self.setup_demo()
        devices = Device.objects.filter(connection__client_id=demo.CLIENT_ID)
        self.assertEqual(devices.count(), 4)                                     # three tanks and the system
        for device in devices:
            count = device.channels.count()
            self.assertIn(count, (7, 8, len(parameters.COLUMNS)), device.code)
            self.assertEqual(device.credential.username, demo.USERNAME)
            self.assertEqual(device.topic, f'{demo.TOPIC_ROOT}/{device.code.lower()}')
        codes = set(Channel.objects.filter(device__in=devices).values_list('quantity', flat=True))
        self.assertEqual(codes, set(parameters.COLUMNS))
        for unit, middle in zip(self.units, self.middles):
            bound = Binding.objects.filter(point=middle)
            self.assertTrue(bound.exists(), unit.code)
            self.assertEqual({binding.channel.device.code for binding in bound}, {f'{demo.CODE_PREFIX}{unit.code}'})
        self.assertTrue(Binding.objects.filter(system=self.ras).exists())
        self.assertIn('secret', out.lower())
        self.assertTrue(Credential.objects.get(username=demo.USERNAME).password_hash)

    def test_the_secret_file_holds_the_secret_and_one_line_feed_on_every_platform(self):
        # Readers take the first line; a carriage return written by Windows' text mode would become part of the
        # password and the simulator could not sign in.
        import re
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'sim_farm'
            out = self.setup_demo('--secret-file', str(path))
            secret = re.search(r'secret: (\S+) \(shown once\)', out).group(1)
            self.assertEqual(path.read_bytes(), secret.encode() + b'\n')

    def test_it_is_idempotent(self):
        self.setup_demo()
        counts = (Device.objects.count(), Channel.objects.count(), Binding.objects.count(), Connection.objects.count())
        out = self.setup_demo()
        self.assertEqual((Device.objects.count(), Channel.objects.count(), Binding.objects.count(),
                          Connection.objects.count()), counts)
        self.assertNotIn('secret:', out.lower())                                 # the secret is shown once

    def test_remove_takes_away_only_what_it_made(self):
        self.setup_demo()
        call_command('sensors_demo_setup', '--remove', stdout=StringIO())
        self.assertFalse(Device.all_objects.filter(connection__client_id=demo.CLIENT_ID).exists())
        self.assertFalse(Connection.all_objects.filter(client_id=demo.CLIENT_ID).exists())
        self.assertFalse(Credential.all_objects.filter(username=demo.USERNAME).exists())
        self.assertFalse(PayloadFormat.all_objects.filter(name=demo.FORMAT_NAME).exists())
        # what was there before is untouched
        self.assertTrue(Device.objects.filter(pk=self.device.pk).exists())
        self.assertTrue(Channel.objects.filter(pk=self.channel.pk).exists())
        self.assertTrue(Connection.objects.filter(pk=self.connection.pk).exists())

    def test_a_tank_without_a_middle_point_is_skipped_and_said(self):
        lonely = make_unit('T-99', self.hall)
        out = self.setup_demo()
        self.assertFalse(Device.objects.filter(code=f'{demo.CODE_PREFIX}T-99').exists())
        self.assertIn('T-99', out)
        self.assertIsNotNone(lonely)


class EveryParameterShowsTests(DemoCase):
    def test_each_parameter_shows_on_the_water_page_with_origin_and_age_and_in_the_charts(self):
        self.setup_demo()
        admin = get_user_model().objects.create_superuser('root', 'root@example.com', 'x')
        self.client.force_login(admin)
        now = timezone.now().replace(microsecond=0)
        devices = Device.objects.filter(connection__client_id=demo.CLIENT_ID)
        for channel in Channel.objects.filter(device__in=devices):
            parameter = parameters.get(channel.quantity)
            value = float((parameter.low + parameter.high) / 2)
            at = now - timedelta(seconds=5)
            ChannelState.objects.create(channel_no=channel.channel_no, last_value=value, last_value_ts=at, last_good_at=at,
                                        last_seen_at=at)
            with connection.cursor() as cursor:
                for seconds in (45, 35, 25):          # after the binding began (a minute before the setup ran)
                    cursor.execute('INSERT INTO sensors_reading (channel_no, ts, value) VALUES (%s, %s, %s)',
                                   [channel.channel_no, now - timedelta(seconds=seconds), value])
        page = self.client.get(reverse('farm:water')).content.decode()
        tank_device = Device.objects.get(code=f'{demo.CODE_PREFIX}{self.units[0].code}')
        for channel in tank_device.channels.all():
            self.assertRegex(page, rf'unit sensor #{channel.channel_no} · \d+ s ago', channel.quantity)
        system_device = Device.objects.get(code=f'{demo.CODE_PREFIX}{self.ras.code}')
        own = set(tank_device.channels.values_list('quantity', flat=True))
        for channel in system_device.channels.exclude(quantity__in=own):          # the tank's own sensors come first (A1)
            self.assertRegex(page, rf'system sensor #{channel.channel_no} · \d+ s ago', channel.quantity)
        loop = point_of(self.ras)
        water = water_read.latest([loop])[loop.pk]
        for channel in system_device.channels.all():
            reading = water.get(channel.quantity)
            self.assertEqual((reading.origin, reading.sample.channel_no),
                             (water_read.Origin.SYSTEM_SENSOR, channel.channel_no))
        start = now - timedelta(hours=1)
        for target, device in ((self.units[0], tank_device), (self.ras, system_device)):
            for code in device.channels.values_list('quantity', flat=True):
                with self.subTest(target=str(target), code=code):
                    chart = read.series(target, code, start, now)
                    self.assertEqual(sum(bucket.n for bucket in chart.buckets), 3)

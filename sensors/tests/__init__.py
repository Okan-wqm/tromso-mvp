"""Shared setup for the sensors tests: a site, a connection, a payload format, a device and channels made straight in
the database (the pages have their own tests), and raw SQL helpers for the tables the ingest writes."""
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.test import TestCase

from farm.models import ProductionDepartment, Site
from sensors import quantities
from sensors.models import Channel, Connection, Device, PayloadFormat


def make_connection(name='Hall broker', **fields):
    values = {'host': 'mosquitto', 'port': 8883, 'client_id': f'ingest-{name.lower().replace(" ", "-")}',
              'username': 'ingest', 'secret_file': 'ingest_password', **fields}
    return Connection.objects.create(name=name, **values)


def make_format(name='Probe JSON', **fields):
    values = {'shape': 'object', 'time_path': '/ts', 'time_unit': 'epoch_ms', 'seq_path': '/seq', **fields}
    return PayloadFormat.objects.create(name=name, **values)


def make_device(connection_, payload_format, site, code='PROBE-1', **fields):
    values = {'name': f'Probe {code}', 'topic': f'farm/hall/{code.lower()}', 'expected_interval_s': 1, **fields}
    return Device.objects.create(connection=connection_, payload_format=payload_format, site=site, code=code, **values)


def make_channel(device, quantity='temperature_c', code=None, **fields):
    values = {**quantities.defaults(quantity), 'name': quantity, 'value_path': f'/{quantity}', **fields}
    return Channel.objects.create(device=device, quantity=quantity, code=code or quantity.upper().replace('_', '-'),
                                  **values)


def rows(sql, params=()):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall()


def one(sql, params=()):
    found = rows(sql, params)
    return found[0][0] if found else None


class SensorsCase(TestCase):
    """A site with a hall, a connection, a payload format, a device on the site and a temperature channel."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user('tekniker', 'tekniker@example.com', 'x')
        cls.site = Site.objects.create(name='Bergen', code='BG')
        cls.hall = ProductionDepartment.objects.create(site=cls.site, name='Hall A', code='HA')
        cls.connection = make_connection()
        cls.format = make_format()
        cls.device = make_device(cls.connection, cls.format, cls.site)
        cls.channel = make_channel(cls.device)

    def refused(self, constraint, make):
        """`make()` is refused by the database with this constraint's name."""
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError) as caught, transaction.atomic():
            make()
        name = getattr(getattr(caught.exception.__cause__, 'diag', None), 'constraint_name', None)
        self.assertEqual(name, constraint, str(caught.exception))

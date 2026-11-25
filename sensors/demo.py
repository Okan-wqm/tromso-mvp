"""The live demo's sensor configuration (manage.py sensors_demo_setup): for the tanks and systems a database already has,
one connection, one payload format, one device per tank (with an active middle point) and per system, 7-8 water channels
per device that together cover every measured parameter of farm/water/parameters.py, bound to the tank's middle point or
to the system, and a simulator credential. Every row it makes is found again by its marker: the connection's client id
`CLIENT_ID`, the format's name `FORMAT_NAME`, the credential's user name `USERNAME`; devices, channels and bindings hang
off the connection. Nothing else is touched, and `remove()` deletes exactly these rows (the readings stored under their
channel numbers stay, unreachable, and leave with the raw retention).

The messages the Node-RED flow `farm` publishes (sensors-ingest/simulator): topic `demo/<device code in lower case>`, one
JSON object `{"ts": <epoch ms>, "seq": <n>, "<parameter code>": <value>, ...}` per message, each channel's value at
`/<parameter code>`. The devices are NOT marked simulated: the demo's values are meant to reach the water page, the
monitoring cards and the charts (a simulated device's values are used nowhere)."""
from dataclasses import dataclass, field
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from farm.models import System, Tank
from farm.water import parameters, read as water_read

from . import credentials, quantities
from .models import Binding, Channel, Connection, Credential, Device, PayloadFormat

CLIENT_ID = 'demo-simulator-ingest'
CONNECTION_NAME = 'Demo simulator broker'
FORMAT_NAME = 'Demo simulator (JSON object)'
USERNAME = 'demo-simulator'
TOPIC_ROOT = 'demo'
CODE_PREFIX = 'SIM-'
# Every device has these; the others are shared out, half to every other device, so two devices cover them all.
BASE = [parameters.TEMPERATURE, parameters.OXYGEN_MG_L, parameters.OXYGEN_PCT, parameters.PH]
# The ionic-strength inputs (the conductivity at 25 °C, the hardness) are left out: the simulator does not send them
# (sensors-ingest/simulator/build-flows.js), and a bound channel that never reports is a gap, not a demo.
IONIC = ('conductivity_25_us_cm', 'hardness_mg_l')
REST = [code for code in parameters.COLUMNS if code not in BASE and code not in IONIC]


@dataclass
class Report:
    devices: list = field(default_factory=list)       # codes made now
    kept: list = field(default_factory=list)          # codes that were there
    skipped: list = field(default_factory=list)       # (place, why)
    secret: str = ''                                  # the simulator credential's secret, when made now


def _codes(index, alone):
    if alone:
        return [*BASE, *REST]
    half = len(REST) // 2
    return [*BASE, *(REST[:half] if index % 2 == 0 else REST[half:])]


def _places():
    """[(place, site, target kwargs, code)]: live tanks with an active middle point and live systems, in code order."""
    tanks = list(Tank.objects.select_related('production_department__site').order_by('code'))
    middles = water_read.middle_points(tanks)
    found, skipped = [], []
    for tank in tanks:
        site = tank.production_department.site
        if tank.pk not in middles:
            skipped.append((tank.code, 'no active middle sampling point'))
        elif site is None:
            skipped.append((tank.code, 'its production department has no site'))
        else:
            found.append((tank, site, {'point': middles[tank.pk]}))
    for system in System.objects.select_related('site').order_by('code'):
        found.append((system, system.site, {'system': system}))
    return found, skipped


def demo_channels(channel_nos):
    """The channel numbers among these that belong to the live demo (a device of the demo's connection, found by its
    marker `CLIENT_ID`): values from the Node-RED flow, not from a probe in real water, which a chart says ("Simulated
    values"). A device marked simulated (`Device.is_simulated`) is another thing: its values are drawn nowhere."""
    return set(Channel.all_objects.filter(channel_no__in=list(channel_nos), device__connection__client_id=CLIENT_ID)
               .values_list('channel_no', flat=True))


def setup(at=None):
    """Makes what is missing; returns a Report. Safe to run again."""
    at = at or timezone.now() - timedelta(minutes=1)
    report = Report()
    with transaction.atomic():
        connection, _made = Connection.objects.get_or_create(client_id=CLIENT_ID, defaults={
            'name': CONNECTION_NAME, 'host': 'mosquitto', 'port': 1883, 'use_tls': False, 'username': 'ingest',
            'secret_file': 'mqtt_ingest'})
        payload_format, _made = PayloadFormat.objects.get_or_create(name=FORMAT_NAME, defaults={
            'shape': 'object', 'time_path': '/ts', 'time_unit': 'epoch_ms', 'seq_path': '/seq'})
        credential = Credential.objects.filter(username=USERNAME).first()
        if credential is None:
            credential = Credential.objects.create(username=USERNAME)
            report.secret = credentials.give_secret(credential)
        places, report.skipped = _places()
        taken = set(Device.all_objects.exclude(connection=connection).filter(code__startswith=CODE_PREFIX)
                    .values_list('code', flat=True))
        for index, (place, site, target) in enumerate(places):
            code = f'{CODE_PREFIX}{place.code}'
            if code in taken:
                report.skipped.append((place.code, f'the code {code} is used by another connection'))
                continue
            device = Device.objects.filter(connection=connection, code=code).first()
            if device is not None:
                report.kept.append(code)
                continue
            device = Device.objects.create(
                connection=connection, payload_format=payload_format, credential=credential, site=site, code=code,
                name=f'Simulated probes {place.code}', topic=f'{TOPIC_ROOT}/{code.lower()}', expected_interval_s=1,
                manufacturer='Node-RED', model='farm flow', note='Made by manage.py sensors_demo_setup.')
            for quantity in _codes(index, alone=len(places) == 1):
                channel = Channel.objects.create(
                    device=device, quantity=quantity, code=quantity.upper().replace('_', '-'),
                    name=str(quantities.get(quantity).label), value_path=f'/{quantity}', **quantities.defaults(quantity))
                Binding.objects.create(channel=channel, role=Binding.Role.PRIMARY, valid_from=at,
                                       note='Made by manage.py sensors_demo_setup.', **target)
            report.devices.append(code)
    return report


def remove():
    """Deletes what `setup` made (its connection with the devices, channels, calibrations and bindings under it, the
    format and the credential); returns how many devices went."""
    with transaction.atomic():
        devices = Device.all_objects.filter(connection__client_id=CLIENT_ID)
        count = devices.count()
        channels = Channel.all_objects.filter(device__in=devices)
        Binding.all_objects.filter(channel__in=channels).delete()
        channels.delete()
        devices.delete()
        Connection.all_objects.filter(client_id=CLIENT_ID).delete()
        PayloadFormat.all_objects.filter(name=FORMAT_NAME, devices__isnull=True).delete()
        Credential.all_objects.filter(username=USERNAME, devices__isnull=True).delete()
    return count

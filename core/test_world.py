"""The TEST WORLD: the one set of records the browser tests' fixtures and props are made from, never the development
database (owner's privacy rule, 2026-11-24: the repository is public). Every person, address and name is a fixture value
(names "Test …", addresses @example.com; core/tests_fixture_privacy.py guards the addresses). It is built in a test
database only: by scripts/record_test_world.py in the throwaway database test_world (scripts/record_test_world.sh), and
by the tests that make the islands' props in the test run's own database. The clock is pinned to MOMENT while it is
built and read.

    world(admin)                      every part below, in order, through a client signed in as `admin`
    company_world(admin, client)      the company's: sites, a hall, a loop, units with fish, a storage location, a
                                      library document, a knowledge entry, a person, a role and an employee
    water_world(admin, parts)         TT-01's water over the week before MOMENT: a probe (temperature, oxygen, pH) on
                                      its middle point with a ten-hour outage, meter and lab samples, the fish's
                                      temperature and pH limits, one water-limit alarm (Tank › Water, Sensors › Charts)"""
import math
from datetime import datetime, timedelta
from decimal import Decimal as D

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import Client
from django.urls import reverse

MOMENT = datetime.fromisoformat('2026-11-23T12:42:00+00:00')


def world(admin, client=None):
    """The test world, built through a client signed in as `admin`; [what was made: its answer] of the parts posted.
    `client`: the test's own (a test run allows only its own host); else one on localhost, as the recorder's server
    allows."""
    from farm.models import Tank
    client = client or Client(HTTP_HOST='localhost')
    client.force_login(admin)
    made = company_world(admin, client)
    water_world(admin, {'tank': Tank.objects.get(code='TT-01')})
    return made


def company_world(admin, client):
    """The test world: two sites, a hall, a loop, two units with fish, water past its limits, a storage location, a
    library document with its PDF, a knowledge entry, a person with an account, a role and an employee."""
    from farm.models import ProductionDepartment, Site, System, WaterLimit
    from farm.tests.helpers import make_species, point_of, site_data, stock_fish
    from farm.tests.test_stock import make_unit
    from hr.tests.helpers_people import employee
    from inventory.tests.helpers import location_data
    from knowledge.tests.helpers import document_data, make_pdf, upload
    made = []

    def post(url, data, what):
        response = client.post(url, data)
        made.append(f'{what}: {response.status_code}')
    post(reverse('farm:site_create'), site_data(name='Test Site North', code='TSN', contact_email='north@example.com'), 'site')
    north = Site.objects.get(code='TSN')
    south = Site.objects.create(name='Test Site South', code='TSS', altitude=D(0), timezone='UTC', type=Site.Type.SEA_CAGE,
                                latitude=D('69.6'), longitude=D('18.9'))
    hall = ProductionDepartment.objects.create(site=north, name='Test Hall A', code='THA')
    cages = ProductionDepartment.objects.create(site=south, name='Test Cages', code='TCG')
    loop = System.objects.create(name='Test Loop 1', code='TL1', site=north, production_department=hall)
    salmon = make_species()
    tank, cage = make_unit('TT-01', hall, system=loop), make_unit('TM-01', cages)
    stock_fish(admin, tank, 1000, '50', 10, species=salmon)
    stock_fish(admin, cage, 500, '900', 10, species=salmon)
    WaterLimit.objects.create(species=salmon, parameter='oxygen_mg_l', water_type='any', critical_low=D(6), warning_low=D(7))
    from datetime import timedelta
    from farm.water import services as water
    water.record(admin, point=point_of(tank), measured_at=MOMENT - timedelta(hours=1), source='manual',
                 values={'oxygen_mg_l': D('5'), 'temperature_c': D('10')}, notes='')
    post(reverse('inventory:storagelocation_create'), location_data(north, name='Test Store', code='ts-01'), 'location')
    post(reverse('knowledge:document_create'), {**document_data(title='Test document'), 'file': upload(make_pdf('Test page.'))},
         'document')
    from knowledge.models import Document
    document = Document.objects.first()
    from knowledge.tests.helpers import entry_data
    if document is not None:
        post(reverse('knowledge:knowledgeentry_create'), entry_data(document=str(document.pk), statement='A test statement.'),
             'entry')
    person = get_user_model().objects.create_user('test.person', 'test.person@example.com', first_name='Test', last_name='Person')
    group = Group.objects.create(name='Test role')
    group.permissions.set(Permission.objects.filter(codename__in=['view_site', 'add_site', 'view_tank']))
    person.groups.add(group)
    employee('E-9001', last='Person', first='Test')
    return made


PROBE_STEP = timedelta(minutes=10)                               # the probe's heartbeat: a value every 10 minutes
OUTAGE = (timedelta(days=3, hours=20), timedelta(days=3, hours=8))     # back from MOMENT: ten hours without a value


def water_world(admin, parts):
    """TT-01's water (`parts['tank']`) over the eight days before MOMENT: a probe (PROBE-TT01: temperature, oxygen, pH,
    a value every 10 minutes, a daily swing) bound to its middle point, silent for ten hours three and a half days back;
    a meter sample (TAN, pH, temperature, oxygen) two days back and a lab sample (TAN, pH, temperature, alkalinity) four
    days back; the salmon's temperature and pH limits (the oxygen's is the company world's); a critical water-limit alarm
    on its oxygen three days back."""
    from alarms.models import Alarm
    from farm.models import WaterLimit
    from farm.tests.helpers import point_of
    from farm.water import services as water
    from sensors import bindings
    from sensors.tests import make_channel, make_connection, make_device, make_format
    from sensors.tests.test_read import insert

    tank = parts['tank']
    site = tank.production_department.site
    salmon = WaterLimit.objects.filter(parameter='oxygen_mg_l').first().species
    for parameter, bounds in (('temperature_c', {'warning_high': 15, 'critical_high': 18}),
                              ('ph', {'critical_low': '6.5', 'warning_low': '6.8', 'warning_high': '7.8',
                                      'critical_high': '8.2'})):
        WaterLimit.objects.create(species=salmon, parameter=parameter, water_type='any',
                                  **{key: D(str(value)) for key, value in bounds.items()})
    middle = point_of(tank)
    device = make_device(make_connection('Test broker'), make_format('Test probe JSON'), site, code='PROBE-TT01')
    start = MOMENT - timedelta(days=8)
    for quantity, base, swing in (('temperature_c', 12.0, 1.2), ('oxygen_mg_l', 8.4, 0.9), ('ph', 7.3, 0.15)):
        channel = make_channel(device, quantity, code=quantity.upper(), heartbeat_s=int(PROBE_STEP.total_seconds()))
        bindings.move(admin, channel, point=middle, at=start)
        rows, moment = [], start + PROBE_STEP
        while moment <= MOMENT:
            if not OUTAGE[1] <= MOMENT - moment <= OUTAGE[0]:
                hours = (moment - start).total_seconds() / 3600
                rows.append((moment, round(base + swing * math.sin(hours / 24 * 2 * math.pi), 3)))
            moment += PROBE_STEP
        insert(channel.channel_no, rows)
    for days, source, values in ((2, 'manual', {'oxygen_mg_l': '7.80', 'temperature_c': '12.4', 'ph': '7.25',
                                                'tan_mg_l': '0.420'}),
                                 (4, 'lab', {'tan_mg_l': '0.610', 'ph': '7.40', 'temperature_c': '12.1',
                                             'alkalinity_mg_l': '85'})):
        water.record(admin, point=middle, measured_at=MOMENT - timedelta(days=days), source=source,
                     values={key: D(value) for key, value in values.items()})
    Alarm.objects.create(source='water_limit', point=middle, parameter='oxygen_mg_l', severity='critical', site=site,
                         opened_at=MOMENT - timedelta(days=3), summary='O₂ 5.8 mg/L, below 6.00 (critical)')

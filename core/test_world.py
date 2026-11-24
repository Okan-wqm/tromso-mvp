"""The TEST WORLD: the one set of records the browser tests' fixtures and props are made from, never the development
database (owner's privacy rule, 2026-11-24: the repository is public). Every person, address and name is a fixture value
(names "Test …", addresses @example.com; core/tests_fixture_privacy.py guards the addresses). It is built in a test
database only: by the tests that make the islands' props and pages in the test run's own database
(farm/tests/test_island_pages.py), and by a recorder of fixtures in a throwaway database, where one exists. The clock is pinned to MOMENT while it is
built and read.

    world(admin)                      every part below, in order, through a client signed in as `admin`
    company_world(admin, client)      the company's: sites, a hall, a loop, units with fish, a storage location, a
                                      library document, a knowledge entry, a person, a role and an employee
    hr_world(admin, client)           the people's: office departments, employees placed and one who left, shifts, a
                                      holiday, a leave type, leave requests and attendance
    water_world(admin, parts)         TT-01's water over the week before MOMENT: a probe (temperature, oxygen, pH) on
                                      its middle point with a ten-hour outage and a pH silent for the last two hours,
                                      meter and lab samples, the fish's temperature and pH limits, one water-limit alarm
                                      (Tank › Water, Sensors › Charts); then, each its own function:
      channel_states(channels)        the ingest's memory of the probe's channels as it would have written it: the
                                      temperature and oxygen fresh, the pH not (no recent data)
      harvest_world(admin, tank)      a harvest from TT-01 six days back
      treatment_world(admin, tank)    a thermal delousing of TT-01 five days back
      feeding_world(admin, tank)      a feeding of TT-01 the day before
      limits_world(tank)              the fish's NH₃-N and CO₂ limits, so the Deffeyes chart draws its regions
    roster_world(admin, client)       today's roster of the hall: one planned person in each state of the board
    sensors_world(admin)              after world(), for the Sensors pages' tests only: a simulated device, credentials,
                                      alarm rules and events, dead letters, the ingest's heartbeat"""
import math
from datetime import datetime, time, timedelta
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
    made = company_world(admin, client) + hr_world(admin, client) + roster_world(admin, client)
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
PH_SILENT = timedelta(hours=2)                                   # the pH's last value: two hours before MOMENT


def water_world(admin, parts):
    """TT-01's water (`parts['tank']`) over the eight days before MOMENT: a probe (PROBE-TT01: temperature, oxygen, pH,
    a value every 10 minutes, a daily swing) bound to its middle point, silent for ten hours three and a half days back;
    a meter sample (TAN, pH, temperature, oxygen) two days back and a lab sample (TAN, pH, temperature, alkalinity) four
    days back; the salmon's temperature and pH limits (the oxygen's is the company world's); a critical water-limit alarm
    on its oxygen three days back. The pH's last value is PH_SILENT back; the channels' state is the ingest's
    (`channel_states`). Then the fish's events of the week: a harvest, a treatment and a feeding."""
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
    channels = []
    for quantity, base, swing in (('temperature_c', 12.0, 1.2), ('oxygen_mg_l', 8.4, 0.9), ('ph', 7.3, 0.15)):
        channel = make_channel(device, quantity, code=quantity.upper(), heartbeat_s=int(PROBE_STEP.total_seconds()))
        channels.append(channel)
        bindings.move(admin, channel, point=middle, at=start)
        rows, moment = [], start + PROBE_STEP
        last = MOMENT - PH_SILENT if quantity == 'ph' else MOMENT
        while moment <= last:
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
    channel_states(channels)
    harvest_world(admin, tank)
    treatment_world(admin, tank)
    feeding_world(admin, tank)
    limits_world(tank)


def limits_world(tank):
    """The NH₃-N and CO₂ limits of TT-01's fish (any water): the Deffeyes charts then draw the regions where each is passed
    and their borders (Tank › Water's chart of the time, the calculator from TT-01)."""
    from farm.models import WaterLimit

    species = WaterLimit.objects.filter(parameter='oxygen_mg_l').first().species
    for parameter, bounds in (('nh3_n_mg_l', {'warning_high': '0.01', 'critical_high': '0.0125'}),
                              ('co2_mg_l', {'warning_high': '10', 'critical_high': '15'})):
        WaterLimit.objects.create(species=species, parameter=parameter, water_type='any',
                                  **{key: D(value) for key, value in bounds.items()})


def channel_states(channels):
    """The ingest's memory of `channels` (sensors.ChannelState) as it writes it in the transaction of their readings
    (sensors-ingest/src/db.rs, UPSERT_STATES): the newest clean reading is the last seen, the last good and the anchor,
    with nothing in an open run. What Sensors › Live, the charts' "now" and the cards read: a channel whose newest value
    is older than its freshness says "no recent data"."""
    from sensors.models import ChannelState
    from sensors.read import value_at

    for channel in channels:
        newest = value_at(channel.channel_no, MOMENT)
        if newest is None:
            continue
        at, value = newest
        ChannelState.objects.create(channel_no=channel.channel_no, last_seen_at=at, last_good_at=at, last_value=value,
                                    last_value_ts=at, last_quality=0, anchor_ts=at, anchor_value=value,
                                    anchor_quality=0, run_n=0, high_ts=at)


def _days_back(tank, days):
    from farm.stock.dates import local_today
    return local_today(tank) - timedelta(days=days)


def _batch_of(tank):
    from farm.models import Batch
    return Batch.objects.filter(movements__unit=tank).distinct().get()


def harvest_world(admin, tank):
    """100 of TT-01's fish harvested six days back (5.2 kg round weight) to a test slaughter facility, through the
    service (the handling check's warnings, if any, gone on past as a person would)."""
    from farm.handling import check
    from farm.stock import services
    from farm.tests.helpers import make_facility

    day, batch = _days_back(tank, 6), _batch_of(tank)
    seen = check.assess('harvest', tank, day, batch, with_earliest=False, operation='harvest').fingerprint
    services.record_harvest(admin, unit=tank, batch=batch, day=day, count=100, measured_weight_kg=D('5.2'),
                            facility=make_facility(name='Test Slaughterhouse', approval_number='T0001'),
                            handling_ack=seen or None)


def treatment_world(admin, tank):
    """A thermal delousing of TT-01 five days back, one day long, no medicine, through the service."""
    from farm.health import services

    day = _days_back(tank, 5)
    seen = services.handling([tank], day, 'thermal', None, 'sea_lice').fingerprint
    services.record_treatment(admin, units=[tank], method='thermal', reason='sea_lice', start_date=day, end_date=day,
                              handling_ack=seen or None)


def feeding_world(admin, tank):
    """0.8 kg of a test feed given to TT-01 at 08:00 the day before, through the service."""
    from farm.feeding.services import record_feeding
    from farm.models import Feed

    feed = Feed.objects.create(name='Test Feed 3 mm', code='TF-3', feed_type='grower', pellet_size_mm=D(3))
    record_feeding(admin, unit=tank, day=_days_back(tank, 1), feed=feed, amount_kg=D('0.8'), time=time(8, 0))


def hr_world(admin, client):
    """The people's part of the test world (Company › HR, Production › Team): an office department under another with a
    manager, the employee of company_world and a second one placed in them, a third who left, a shift, a holiday, a leave
    type, a pending and an approved leave request, a closed stretch of attendance and one left open (its clock-out
    forgotten). Made in the models (each list and form reads them), on MOMENT's days."""
    from datetime import date, time, timedelta

    from farm.models import ProductionDepartment, Site
    from hr.models import (AttendanceRecord, Employee, Holiday, LeaveRequest, LeaveType, OfficeDepartment, Shift)
    from hr.models.leave import LeaveStatus
    from hr.tests.helpers_people import employee, place
    north = Site.objects.get(code='TSN')
    office = OfficeDepartment.objects.create(site=north, name='Test Office', code='TOF', manager=admin)
    OfficeDepartment.objects.create(site=None, name='Test Accounts', code='TAC', parent=office)
    hall = ProductionDepartment.objects.get(code='THA')
    person = Employee.objects.get(employee_number='E-9001')
    place(person, office, title='Test coordinator')
    second = employee('E-9002', last='Second', first='Test')
    place(second, hall, title='Test technician')
    employee('E-9003', last='Former', first='Test', left_on=date(2026, 6, 30))
    Shift.objects.create(name='Test day shift', code='TD', starts_at=time(7), ends_at=time(15), break_minutes=30,
                         grace_minutes=10)
    Shift.objects.create(name='Test night shift', code='TN', starts_at=time(22), ends_at=time(6), break_minutes=30)
    Holiday.objects.create(day=date(2026, 12, 25), name='Test holiday', site=None)
    annual = LeaveType.objects.create(name='Test annual leave', code='TAL', annual_days=25)
    today = MOMENT.date()
    LeaveRequest.objects.create(employee=second, leave_type=annual, first_day=today + timedelta(days=7),
                                last_day=today + timedelta(days=9), reason='A test reason.')
    LeaveRequest.objects.create(employee=person, leave_type=annual, first_day=today - timedelta(days=10),
                                last_day=today - timedelta(days=8), status=LeaveStatus.APPROVED, decided_by=admin,
                                decided_at=MOMENT - timedelta(days=12))
    AttendanceRecord.objects.create(employee=second, clock_in=MOMENT - timedelta(days=1, hours=5),
                                    clock_out=MOMENT - timedelta(days=1), via=AttendanceRecord.Via.ENTERED,
                                    note='Test note')
    AttendanceRecord.objects.create(employee=person, clock_in=MOMENT - timedelta(days=2), via=AttendanceRecord.Via.ENTERED,
                                    note='Test note, left open')
    return [f'hr: {Employee.objects.count()} employees, {OfficeDepartment.objects.count()} office departments']


def sensors_world(admin):
    """The Sensors panel's part, for its pages in the new look (sensors/tests/test_pages_next.py), built after world() and
    called by those tests only (not by world(): its alarms would change the other pages' counts): a simulated device out
    of the water with a channel, an enabled and a disabled broker credential, three alarm rules on the probe of TT-01, an
    open alarm event of its oxygen and a closed one acknowledged, two dead letters (one resolved) and the ingest's
    heartbeat four seconds before MOMENT."""
    import hashlib

    from alarms import services as alarm_services, sources as alarm_sources
    from sensors.models import (AlarmEvent, AlarmRule, Binding, Channel, Connection, Credential, DeadLetter, Device,
                                IngestStatus)
    from sensors.tests import make_channel, make_device

    probe = Device.objects.get(code='PROBE-TT01')
    broker = probe.connection
    simulated = make_device(broker, probe.payload_format, probe.site, code='SIM-TT02', name='Test simulated probe',
                            is_simulated=True, manufacturer='Test maker', model='T1')
    make_channel(simulated, 'oxygen_mg_l', code='OXYGEN-SIM')
    Credential.objects.create(username='test-gateway', rotated_at=MOMENT - timedelta(days=3), is_enabled=True)
    Credential.objects.create(username='test-old-gateway', is_enabled=False)
    oxygen = Channel.objects.get(device=probe, quantity='oxygen_mg_l')
    temperature = Channel.objects.get(device=probe, quantity='temperature_c')
    silent = AlarmRule.objects.create(channel=oxygen, kind='no_data', for_s=600, severity='critical')
    AlarmRule.objects.create(channel=temperature, kind='rate', threshold=1.0, for_s=60, severity='warning',
                             is_active=False)
    AlarmRule.objects.create(quantity='oxygen_mg_l', kind='device_offline', for_s=900, severity='warning')
    binding = Binding.objects.filter(channel=oxygen).first()
    AlarmEvent.objects.create(rule=silent, channel_no=oxygen.channel_no, binding=binding,
                              opened_at=MOMENT - timedelta(minutes=12))
    closed = AlarmEvent.objects.create(rule=silent, channel_no=oxygen.channel_no, binding=binding,
                                       opened_at=MOMENT - timedelta(days=3, hours=20),
                                       closed_at=MOMENT - timedelta(days=3, hours=8), peak=0.0)
    alarm_services.acknowledge(alarm_sources.mirror(closed), admin, at=MOMENT - timedelta(days=3, hours=19))
    for topic, reason, payload, times, resolved in (
            ('test/probe-tt01', 'bad_value', b'{"ts":1795440480000,"oxygen_mg_l":"n/a"}', 3, False),
            ('test/unknown', 'no_route', b'{"ts":1795440000000,"x":1}', 12, True)):
        DeadLetter.objects.create(connection_id=broker.pk, topic=topic, reason=reason, payload=payload,
                                  payload_sha256=hashlib.sha256(payload).hexdigest(), payload_len=len(payload),
                                  count=times, first_at=MOMENT - timedelta(hours=5), last_at=MOMENT - timedelta(hours=1),
                                  resolved_at=MOMENT - timedelta(minutes=30) if resolved else None,
                                  resolved_by=admin if resolved else None)
    IngestStatus.objects.create(connection_id=broker.pk, heartbeat_at=MOMENT - timedelta(seconds=4), connected=True,
                                version='test')
    return [f'sensors: {Device.objects.count()} devices, {AlarmEvent.objects.count()} alarm events, '
            f'{Connection.objects.count()} connections']


def roster_world(admin, client):
    """Today's roster of the production hall (Test Site North, on Oslo's clock: MOMENT is 13:42 there): one planned
    person in each state of the board (hr.rules.status), so Today and the Shift schedule have planned people and the
    stacked bar has parts: upcoming (an evening shift), present (in since before the day shift), late (in 30 minutes
    after the start), not in yet (a shift that began 12 minutes ago), absent (the day shift, no clock-in), on leave (an
    approved leave over a planned day) and done (an early shift, clocked in and out)."""
    from datetime import date, time, timedelta
    from zoneinfo import ZoneInfo

    from farm.models import ProductionDepartment
    from hr.models import AttendanceRecord, LeaveRequest, LeaveType, Shift, ShiftAssignment
    from hr.models.leave import LeaveStatus
    from hr.tests.helpers_people import employee, place
    hall, today, oslo = ProductionDepartment.objects.get(code='THA'), MOMENT.date(), ZoneInfo('Europe/Oslo')

    def at(hour, minute=0):
        return datetime(today.year, today.month, today.day, hour, minute, tzinfo=oslo)

    def shift(code, name, start, end):
        return Shift.objects.create(name=name, code=code, starts_at=start, ends_at=end, break_minutes=0, grace_minutes=0)
    early, day = shift('TE1', 'Test early shift', time(6), time(10)), shift('TD1', 'Test morning shift', time(7), time(15))
    midday, later = shift('TM1', 'Test midday shift', time(12), time(20)), shift('TL1', 'Test later shift', time(13, 30), time(21))
    evening = shift('TV1', 'Test evening shift', time(18), time(23))
    annual = LeaveType.objects.filter(code='TAL').first() or LeaveType.objects.create(name='Test annual leave', code='TAL')
    made = {}
    for number, last, plan in (('E-9101', 'Upcoming', evening), ('E-9102', 'Present', day), ('E-9103', 'Late', midday),
                               ('E-9104', 'Waiting', later), ('E-9105', 'Absent', day), ('E-9106', 'Away', day),
                               ('E-9107', 'Done', early)):
        person = employee(number, last=last, first='Test', on=date(2026, 1, 1))
        place(person, hall, title='Test operator')
        ShiftAssignment.objects.create(employee=person, day=today, shift=plan)
        made[last] = person

    def punch(person, clock_in, clock_out=None):
        AttendanceRecord.objects.create(employee=person, clock_in=clock_in, clock_out=clock_out,
                                        via=AttendanceRecord.Via.ENTERED, note='Test roster punch')
    punch(made['Present'], at(6, 55))
    punch(made['Late'], at(12, 30))
    punch(made['Done'], at(5, 58), at(10, 2))
    LeaveRequest.objects.create(employee=made['Away'], leave_type=annual, first_day=today, last_day=today,
                                status=LeaveStatus.APPROVED, decided_by=admin, decided_at=MOMENT - timedelta(days=3))
    return [f'roster: {len(made)} planned today']

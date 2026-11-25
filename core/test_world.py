"""The TEST WORLD: the one set of records the browser tests' fixtures and props are made from, never the development
database (owner's privacy rule, 2026-11-24: the repository is public). Every person, address and name is a fixture value
(names "Test …", addresses @example.com; core/tests_fixture_privacy.py guards the addresses). It is built in a test
database only: by scripts/record_test_world.py in the throwaway database test_world (scripts/record_test_world.sh), and
by the tests that make the islands' props and pages in the test run's own database (farm/tests/test_island_pages.py).
The clock is pinned to MOMENT while it is
built and read.

    world(admin)                      every part below, in order, through a client signed in as `admin`
    company_world(admin, client)      the company's: sites, a hall, a loop, units with fish, a storage location, a
                                      library document, a knowledge entry, a person, a role and an employee
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
    hr_world(admin, client)           the people's: office departments, employees placed and one who left, shifts, a
                                      holiday, a leave type, leave requests, attendance and a week's plan
    roster_world(admin, client)       today's roster of the hall: one planned person in each state of the board
    forms_world(admin, client)        the rows of the forms with lists of their own: a site's and a supplier's contacts,
                                      a feeder's calibration, a feed's suitability, a medicine's withdrawal, a reorder
                                      level, a board's card, a task's and a recurring task's checklist, a device with a
                                      channel and its calibration, a sensor credential, a lice and a biomass report, a
                                      feeding protocol with its table, an experiment with its design; and (states_world)
                                      an assigned protocol, a started experiment, a reviewed entry, a placed device
    panel_world(admin, client)        the production panel's pages: tasks_world, questions_world, experiments_world,
                                      reports_world, storage_world, messages_world
    stale_water_world(admin)          after world(), for Production units' and Overview's tests only: TM-01's oxygen
                                      stale and critical when taken (80 hours back)
    sensors_world(admin)              after world(), for the Sensors pages' tests only: a simulated device, credentials,
                                      alarm rules and events, dead letters, the ingest's heartbeat
    monitoring_world(admin)           eight more units of Test Hall A, one in each state a monitoring card can be in
                                      (OK, critical, warning, no recent data, no limit, note, empty, an old critical),
                                      and a wall board of the hall's units on a 55" TV read from 2 m (wall_board); not part of world():
                                      the monitoring pages' test builds it after it (monitoring/tests/test_next_pages.py)
    feeding_ops_world(admin)          after world(), for Feeding's pages: a protocol in force on TT-01, a meal today, a
                                      voided feeding
    health_ops_world(admin)           after world(), for Health's pages: a medicated bath of TM-01, a lice count over the
                                      limit, a listed disease not notified, a closed observation
    harvest_ops_world(admin)          after health_ops_world(), for Harvest's pages: a harvest planned on TM-01's
                                      withdrawal, an overdue transport, a production plan"""
import math
from datetime import datetime, time, timedelta
from decimal import Decimal as D

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import Client
from django.urls import reverse

MOMENT = datetime.fromisoformat('2026-11-23T12:42:00+00:00')


def ticking():
    """A clock for building the test world: MOMENT, a microsecond later at each reading. Every record is stamped on
    MOMENT's minute, and two records made one after the other are never stamped alike, so a list in time order (the
    activity log, newest first) is the same on every run. Patch django.utils.timezone.now with it while the world is built;
    read the world with the clock pinned to MOMENT."""
    from itertools import count
    readings = count()
    return lambda: MOMENT + timedelta(microseconds=next(readings))


def world(admin, client=None):
    """The test world, built through a client signed in as `admin`; [what was made: its answer] of the parts posted.
    `client`: the test's own (a test run allows only its own host); else one on localhost, as the recorder's server
    allows."""
    from farm.models import Tank
    client = client or Client(HTTP_HOST='localhost')
    client.force_login(admin)
    made = company_world(admin, client) + hr_world(admin, client) + roster_world(admin, client)
    water_world(admin, {'tank': Tank.objects.get(code='TT-01')})
    # the panel's part first: its records keep the codes and the order its pages are recorded with
    return made + panel_world(admin, client) + forms_world(admin, client)


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


def stale_water_world(admin):
    """TM-01's oxygen gone stale while it was critical (F-244): a meter sample 80 hours before MOMENT, 5.2 mg/L under the
    salmon's critical 6. Production units must say it is stale AND what it was (the classic `wq-was-critical`)."""
    from farm.models import Tank
    from farm.tests.helpers import point_of
    from farm.water import services as water
    water.record(admin, point=point_of(Tank.objects.get(code='TM-01')), measured_at=MOMENT - timedelta(hours=80),
                 source='manual', values={'oxygen_mg_l': D('5.2')}, notes='')


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
    from hr.models import (AttendanceRecord, Employee, Holiday, LeaveRequest, LeaveType, OfficeDepartment, Shift,
                           ShiftAssignment)
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
    day_shift = Shift.objects.create(name='Test day shift', code='TD', starts_at=time(7), ends_at=time(15),
                                     break_minutes=30, grace_minutes=10)
    Shift.objects.create(name='Test night shift', code='TN', starts_at=time(22), ends_at=time(6), break_minutes=30)
    Holiday.objects.create(day=date(2026, 12, 25), name='Test holiday', site=None)
    # the week's plan of the production technician: today's day shift, tomorrow off (the Shift schedule, Today)
    ShiftAssignment.objects.create(employee=second, day=MOMENT.date(), shift=day_shift)
    ShiftAssignment.objects.create(employee=second, day=MOMENT.date() + timedelta(days=1), shift=None, note='Test day off')
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


def forms_world(admin, client):
    """The rows of the forms that have lists of their own (core.crud.RowList), each list saved through its own address as
    a person saves it (its RowListView, the record's version sent with it): a contact of the north site, a supplier with
    a contact, a feeder with a calibration, a feed suited to the salmon, a medicine with its withdrawal, a reorder level of
    the store, a monitoring board with a card, a task and a recurring task with a checklist, a device with a channel and
    its calibration, a sensor credential, and a draft lice report and biomass report. Made on MOMENT's day."""
    from core.crud import Resource
    from farm.models import Equipment, EquipmentType, Feed, Medicine, ProductionDepartment, Site, Species, Supplier, Tank
    from farm.tests.helpers import rows_data
    from inventory.models import ReorderLevel, StorageLocation
    from monitoring.models import MonitorBoard
    from sensors.models import Credential, Device
    from sensors.tests import make_channel, make_device
    from tasks.models import Frequency, Task, TaskSeries
    made = []

    def rows(record, key, items):
        resource = next(each for each in Resource.registry
                        if each.model is type(record) and any(listed.key == key for listed in each.row_lists))
        response = client.post(reverse(resource.url_name(key), args=[record.pk]), rows_data(key, items, record=record))
        made.append(f'{key} of {record}: {response.status_code}')
    north, salmon = Site.objects.get(code='TSN'), Species.objects.get(code='SAL')
    hall, tank = ProductionDepartment.objects.get(code='THA'), Tank.objects.get(code='TT-01')
    rows(north, 'contacts', [{'name': 'Test Contact', 'role': 'Test manager', 'email': 'contact@example.com', 'phone': '',
                              'is_primary': True}])
    supplier = Supplier.objects.create(name='Test Supplier', code='TSU', supplies=['feed'])
    rows(supplier, 'contacts', [{'name': 'Test Seller', 'role': 'Test sales', 'email': 'seller@example.com', 'phone': '',
                                 'is_primary': True}])
    feeder = Equipment.objects.create(name='Test Feeder', code='TFD', production_department=hall,
                                      equipment_type=EquipmentType.objects.get(code='feeder-automatic'),
                                      specifications={'capacity': 50, 'siloVolume': 200, 'controlType': 'timer',
                                                      'autoFilling': True})
    rows(feeder, 'calibrations', [{'feed_size_mm': '3', 'label': 'Test starter', 'grams_per_dispensing': '25',
                                   'silo_capacity_kg': '250', 'notes': ''}])
    feed = Feed.objects.create(name='Test Feed', code='TFE', feed_type='grower', manufacturer=supplier)
    rows(feed, 'suitability', [{'species': str(salmon.pk), 'growth_stage': 'all', 'min_weight_g': '50',
                                'max_weight_g': '150', 'notes': ''}])
    medicine = Medicine.objects.create(name='Test Medicine', kind='lice', administration='bath',
                                       active_substance='azamethiphos', lice_report_code='AZAMETHIPHOS')
    rows(medicine, 'withdrawals', [{'species': '', 'degree_days': '150', 'days': '7', 'safety_margin_pct': '20',
                                    'note': ''}])
    # a list is saved as a whole: the store's levels already set (storage_world's) are sent again with this one
    store = StorageLocation.objects.get(code='TS-01')
    rows(store, 'reorder', [*({'feed': str(level.item.feed_id), 'level': str(level.level)} for level in
                             ReorderLevel.objects.filter(location=store).select_related('item')),
                           {'feed': str(feed.pk), 'level': '600'}])
    board = MonitorBoard.objects.create(name='Test Board')
    rows(board, 'units', [{'unit': str(tank.pk), 'template': ''}])
    task = Task(title='Test task', due_date=MOMENT.date())
    task.set_place(tank)
    task.save()
    rows(task, 'checklist', [{'text': 'Test step one'}, {'text': 'Test step two'}])
    series = TaskSeries(title='Test round', frequency=Frequency.DAILY, starts_on=MOMENT.date())
    series.set_place(tank)
    series.save()
    rows(series, 'checklist', [{'text': 'Test round step'}])
    # on the probe's broker and format (company_world's): one broker, so the ingest's state is what its heartbeat says
    probe = Device.objects.get(code='PROBE-TT01')
    device = make_device(probe.connection, probe.payload_format, north, code='TEST-1')
    channel = make_channel(device, 'temperature_c', code='TEST-T')
    rows(channel, 'calibrations', [{'valid_from': '22.11.2026 10:00', 'gain': '1.02', 'offset': '-0.1', 'performed_by': '',
                                    'note': 'Test calibration'}])
    Credential.objects.create(username='test-forms-gateway')
    from reports.models import Report
    from reports.periods import month_start, week_start
    contact = {'contact_name': 'Test Contact', 'contact_email': 'contact@example.com', 'created_by': admin, 'updated_by': admin}
    Report.objects.create(kind='sea_lice', site=Site.objects.get(code='TSS'), period_start=week_start(MOMENT.date()),
                          **contact)
    Report.objects.create(kind='biomass', site=north, period_start=month_start(MOMENT.date()), **contact)
    # A draft feeding protocol with a table of two bands by two temperature columns, saved through its own address.
    from farm.models import FeedingProtocol
    protocol = FeedingProtocol.objects.create(name='Test grow-out', species=salmon, expected_fcr=D('1.00'))
    table = {'version': str(FeedingProtocol.objects.get(pk=protocol.pk).version), 'temperatures': '8 12',
             'bands-TOTAL_FORMS': '2', 'bands-INITIAL_FORMS': '0', 'bands-MIN_NUM_FORMS': '0', 'bands-MAX_NUM_FORMS': '1000'}
    for index, (low, high) in enumerate((('0', '100'), ('100', ''))):
        table.update({f'bands-{index}-min_weight_g': low, f'bands-{index}-max_weight_g': high,
                      f'bands-{index}-feed': str(feed.pk), f'bands-{index}-meals_per_day': '4',
                      f'bands-{index}-expected_fcr': '', f'bands-{index}-sfr_80': '1.1', f'bands-{index}-sfr_120': '1.3'})
    response = client.post(reverse('farm:feedingprotocol_table', args=[protocol.pk]), table)
    made.append(f'table of {protocol}: {response.status_code}')
    # A draft experiment (its creator leads it) with a design of one factor and one group, saved through its own address.
    from experiments.models import Experiment
    response = client.post(reverse('experiments:experiment_create'), {
        'name': 'Test trial', 'species': str(salmon.pk), 'site': str(north.pk), 'hypothesis': 'A test hypothesis.',
        'primary_endpoint': '', 'starts_on': '01.12.2026', 'duration_days': '28', 'notes': ''})
    made.append(f'experiment: {response.status_code}')
    trial = Experiment.objects.filter(name='Test trial').first()
    if trial is not None:
        response = client.post(reverse('experiments:experiment_design', args=[trial.pk]), {
            'version': str(trial.version), 'factors-TOTAL_FORMS': '1', 'factors-INITIAL_FORMS': '0',
            'factors-MIN_NUM_FORMS': '0', 'factors-MAX_NUM_FORMS': '1000', 'factors-0-id': '',
            'factors-0-name': 'Test temperature', 'factors-0-kind': 'other', 'factors-0-unit': '°C',
            'groups-TOTAL_FORMS': '1', 'groups-INITIAL_FORMS': '0', 'groups-MIN_NUM_FORMS': '0',
            'groups-MAX_NUM_FORMS': '1000', 'groups-0-id': '', 'groups-0-name': 'Test control', 'groups-0-role': 'control',
            'groups-0-label_0': 'Cold', 'groups-0-value_0': '8', 'groups-0-replicates': '2'})
        made.append(f'design of {trial}: {response.status_code}')
    return made + states_world(admin, client)


def states_world(admin, client):
    """The common states a form shows as it is, beside the drafts above (review B3): a feeding protocol assigned to a
    unit (its table fixed), a started experiment with a tank placed (its design and places fixed), a reviewed knowledge
    entry, and a device whose channel was placed and moved (a placement history). Each is a record of its own."""
    from datetime import timedelta

    from experiments.models import Experiment
    from farm.models import Feed, FeedingProtocol, ProductionDepartment, ProtocolAssignment, Site, Species
    from farm.tests.helpers import make_species, point_of
    from farm.tests.test_stock import make_unit
    from knowledge.models import Document, KnowledgeEntry
    from knowledge.tests.helpers import entry_data
    from sensors import bindings
    from sensors.models import Device
    from sensors.tests import make_channel, make_device
    made = []
    north = Site.objects.get(code='TSN')
    salmon, feed = Species.objects.get(code='SAL'), Feed.objects.get(code='TFE')
    # an assigned protocol: its table saved through its address, then given to the stocked tank
    protocol = FeedingProtocol.objects.create(name='Test assigned protocol', species=salmon, expected_fcr=D('1.10'))
    table = {'version': str(FeedingProtocol.objects.get(pk=protocol.pk).version), 'temperatures': '8 12',
             'bands-TOTAL_FORMS': '1', 'bands-INITIAL_FORMS': '0', 'bands-MIN_NUM_FORMS': '0',
             'bands-MAX_NUM_FORMS': '1000', 'bands-0-min_weight_g': '0', 'bands-0-max_weight_g': '',
             'bands-0-feed': str(feed.pk), 'bands-0-meals_per_day': '3', 'bands-0-expected_fcr': '1.05',
             'bands-0-sfr_80': '1.0', 'bands-0-sfr_120': '1.2'}
    response = client.post(reverse('farm:feedingprotocol_table', args=[protocol.pk]), table)
    made.append(f'table of {protocol}: {response.status_code}')
    # the states' own units, in a department of their own: the hall's units and their pages stay as the other parts made them
    trials = ProductionDepartment.objects.create(site=north, name='Test Trial Hall', code='TTH')
    spare = make_unit('TX-02', trials)
    ProtocolAssignment.objects.create(protocol=protocol, unit=spare,
                                      valid_from=MOMENT.date() - timedelta(days=5))
    # a started experiment: one group of one replicate, running since three days ago (no tank placed: a placed tank links
    # the Production units page to the experiment, which that page's new look does not say yet: reported, not hidden)
    first = MOMENT.date() - timedelta(days=3)
    tank = make_unit('TX-01', trials)
    trout = make_species(code='TRT', common_name='Test rainbow trout', scientific_name='Oncorhynchus testus')
    started = Experiment.objects.create(code='E-2026-090', name='Test started trial', site=north, species=trout,
                                        duration_days=28, starts_on=first)
    group = started.groups.create(name='Test group', role='control')
    group.replicates.create(number=1)
    Experiment.objects.filter(pk=started.pk).update(status='running', hypothesis='A test hypothesis.',
                                                    primary_endpoint='bfcr', allocation_method='manual',
                                                    allocation_note='Test placement')
    # a reviewed entry, beside the draft one
    document = Document.objects.first()
    if document is not None:
        client.post(reverse('knowledge:knowledgeentry_create'),
                    entry_data(document=str(document.pk), statement='A reviewed test statement.'))
        entry = KnowledgeEntry.objects.get(statement='A reviewed test statement.')
        response = client.post(reverse('knowledge:entry_review', args=[entry.pk]),
                               {'version': entry.version, 'status': 'reviewed'})
        made.append(f'review of an entry: {response.status_code}')
    # a device placed in the spare unit's water two days ago, then moved to the experiment's tank: two stays
    probe = Device.objects.get(code='PROBE-TT01')
    device = make_device(probe.connection, probe.payload_format, north, code='TEST-2')
    channel = make_channel(device, 'temperature_c', code='TEST-P')
    bindings.move(admin, channel, MOMENT - timedelta(days=2), point=point_of(spare))
    bindings.move(admin, channel, MOMENT - timedelta(days=1), point=point_of(tank))
    return made


def record_of(resource):
    """The record of `resource` its edit page is shown and recorded with: of a tab with row lists, the one whose lists
    hold the most rows (a site with contacts, not the one without), then the one with the most lists (a lice report's
    three); else the first by key."""
    records = list(resource.queryset().order_by('pk')[:50])
    if not records or not resource.row_lists:
        return records[0] if records else None
    return max(records, key=lambda record: (
        sum(rows.rows(record).count() for rows in resource.row_lists if rows.applies_to(record)),
        sum(1 for rows in resource.row_lists if rows.applies_to(record))))


def refused_rows_data(rows, record):
    """What a row list of `record` posts to be refused: one new row whose every box is wrong (a figure, a choice and a
    date '!', a text one character longer than it may be), with the record's version."""
    empty = rows.formset(instance=record, prefix=rows.key).empty_form

    def wrong(bound):
        longest = getattr(bound.field, 'max_length', None)
        return 'x' * (longest + 1) if longest else '!'
    version = getattr(type(record).all_objects.filter(pk=record.pk).first(), 'version', '')
    return {f'{rows.key}-TOTAL_FORMS': '1', f'{rows.key}-INITIAL_FORMS': '0', f'{rows.key}-MIN_NUM_FORMS': '0',
            f'{rows.key}-MAX_NUM_FORMS': '1000', 'version': str(version),
            **{f'{rows.key}-0-{bound.name}': wrong(bound) for bound in empty.visible_fields() if bound.name != 'DELETE'}}


def panel_world(admin, client):
    """The production panel's part of the test world (Tasks, Recurring tasks, Questions for the authority, Experiments,
    Regulatory reports, Storage, Messages): each part a function of its own."""
    return (tasks_world(admin, client) + questions_world(admin, client) + experiments_world(admin, client)
            + reports_world(admin, client) + storage_world(admin, client) + messages_world(admin, client))


def tasks_world(admin, client):
    """Operations › Tasks: a daily recurring task at TT-01 for the test admin (posted, so it plans its tasks) and a paused
    weekly one; a task overdue with a checklist, one due today for nobody, one in progress and one done, at the hall."""
    from datetime import time, timedelta

    from farm.models import ProductionDepartment, Tank
    from tasks import places, services
    from tasks.models import Task, TaskChecklistItem, TaskSeries
    from tasks.tests import form_data
    tank, hall = Tank.objects.get(code='TT-01'), ProductionDepartment.objects.get(code='THA')
    today = MOMENT.date()
    data = form_data(title='Test oxygen round', category='water_quality', priority='high', site=places.site_key(tank),
                     location=places.token(tank), assignees=[admin.pk], frequency='daily', interval='1',
                     due_time='10:00', starts_on=(today - timedelta(days=3)).isoformat(), ends_on='', is_active='on')
    for key in ('batch', 'due_date'):
        data.pop(key)
    answer = client.post(reverse('tasks:taskseries_create'), data)
    paused = TaskSeries(title='Test filter wash', category='cleaning', frequency='weekly', interval=1, weekdays=[1],
                        due_time=time(7, 30), starts_on=today, is_active=False)
    paused.set_place(hall)
    paused.save()

    def task(title, due, **fields):
        made = Task(title=title, due_date=due, **fields)
        made.set_place(hall)
        made.save()
        return made
    late = task('Test net check', today - timedelta(days=2), category='maintenance', priority='high', due_time=time(9))
    late.assignees.set([admin])
    for text in ('Test first line', 'Test second line'):
        TaskChecklistItem.objects.create(task=late, text=text)
    task('Test feed order', today, category='feeding')
    working = task('Test probe swap', today, priority='low')
    working.assignees.set([admin])
    services.start(admin, working)
    done = task('Test sample round', today - timedelta(days=1))
    done.assignees.set([admin])
    services.complete(admin, done)
    return [f'recurring task: {answer.status_code}', f'{Task.objects.count()} tasks']


def questions_world(admin, client):
    """Questions for the authority: one open, one answered."""
    from datetime import timedelta

    from reports.models import OpenQuestion, QuestionStatus
    today = MOMENT.date()
    OpenQuestion.objects.create(code='TQ1', question='Test question one?', authority='Test authority',
                                affects='Test rule one')
    OpenQuestion.objects.create(code='TQ2', question='Test question two?', authority='Test authority',
                                affects='Test rule two', status=QuestionStatus.ANSWERED, asked_by='Test Person',
                                asked_on=today - timedelta(days=20), answer='Test answer.',
                                answered_on=today - timedelta(days=5))
    return ['2 questions']


def experiments_world(admin, client):
    """Research › Experiments: a draft with a day 0 ahead, two groups and their replicates, led by the test admin; a draft
    with no day 0; a template."""
    from datetime import timedelta

    from core.codes import next_code
    from farm.models import Site, Species
    from experiments.models import Experiment, ExperimentGroup, Member, Replicate
    north, salmon, today = Site.objects.get(code='TSN'), Species.objects.order_by('pk').first(), MOMENT.date()

    def experiment(name, **fields):
        return Experiment.objects.create(name=name, site=north, species=salmon,
                                         code=next_code(Experiment, f'E-{today.year}-'), **fields)
    planned = experiment('Test diet trial', starts_on=today + timedelta(days=10), duration_days=56,
                         primary_endpoint='bfcr')
    for name in ('A', 'B'):
        group = ExperimentGroup.objects.create(experiment=planned, name=name, role='test')
        for number in (1, 2):
            Replicate.objects.create(group=group, number=number)
    Member.objects.create(experiment=planned, user=admin, role=Member.Role.LEAD)
    experiment('Test light trial', duration_days=84)
    experiment('Test design kept', duration_days=56, is_template=True)
    # the list is newest first (Meta.ordering): made a minute apart, in the order above, not all on MOMENT
    for minutes, code in enumerate(Experiment.objects.order_by('-code').values_list('code', flat=True)):
        Experiment.objects.filter(code=code).update(created_at=MOMENT - timedelta(minutes=minutes))
    return [f'{Experiment.objects.count()} experiments']


def reports_world(admin, client):
    """Regulatory reports: a draft of the monthly biomass of October 2026 for the sea site and a filed one of September for
    the north site (its frozen content, as a filing leaves it); the due list and the kinds' lines are what the reports read
    of the sites and their fish."""
    from datetime import date

    from farm.models import Site
    from reports.models import Report
    from reports.periods import MONTH, Period
    from reports.tests.test_due import filed
    north, south = Site.objects.get(code='TSN'), Site.objects.get(code='TSS')
    Report.objects.create(kind=Report.Kind.BIOMASS, site=south, period_start=date(2026, 10, 1), contact_name='Test Person',
                          contact_email='test.person@example.com', created_by=admin, updated_by=admin)
    filed(Report.Kind.BIOMASS, site=north, period=Period(MONTH, date(2026, 9, 1)), reference='TEST-1', submitted_by=admin)
    return [f'{Report.objects.count()} reports']


def storage_world(admin, client):
    """Operations › Storage, at Test Store (company_world's location): a feed mill, a feed, two lots delivered (one expiring
    within 30 days, both with their cost), an issue, a write-off voided again, a count with a difference, and a reorder
    level above what is left, so the overview says low stock."""
    from datetime import timedelta

    from farm.models import Feed, Supplier
    from inventory import services
    from inventory.models import InventoryItem, InventoryOperation, OperationKind, ReorderLevel, StorageLocation
    store, today = StorageLocation.objects.get(code='TS-01'), MOMENT.date()
    mill = Supplier.objects.create(name='Test Feed Mill', code='TFM', supplies=['feed'])
    feed = Feed.objects.create(name='Test Grower 4', code='TG-4', feed_type='grower', pellet_size_mm=D(4))
    services.receive(admin, supplier=mill, day=today - timedelta(days=10), reference='TEST-DN-1', lines=[
        (feed, 'TL-1', today + timedelta(days=20), store, D(500), D('12.50'), 'NOK'),
        (feed, 'TL-2', today + timedelta(days=200), store, D(1000), D('13.00'), 'NOK')])
    item = InventoryItem.objects.get(feed=feed)
    first, second = item.lots.get(number='TL-1'), item.lots.get(number='TL-2')
    services.issue(admin, location=store, lot=first, day=today - timedelta(days=5), quantity=D(20), reason='samples',
                   notes='Test samples')
    written = services.write_off(admin, location=store, lot=second, day=today - timedelta(days=4), quantity=D(10),
                                 reason='damaged', notes='Test bags')
    services.void(admin, written, 'Test: entered twice')
    services.count(admin, location=store, day=today - timedelta(days=2), lines=[(first, D(475)), (second, D(1000))],
                   notes='Test count')
    ReorderLevel.objects.create(location=store, item=item, level=D(2000), created_by=admin)
    return [f'storage operations: {InventoryOperation.all_objects.exclude(kind=OperationKind.COUNT).count()} and counts']


def messages_world(admin, client):
    """Messages: a person who may use them, a direct conversation with the test admin (two of its messages unread, one of
    the admin's deleted), a channel of the two and a long one (60 messages)."""
    from messaging import services
    from messaging.models import Conversation
    writer = get_user_model().objects.create_user('test.writer', 'test.writer@example.com', first_name='Test',
                                                  last_name='Writer')
    group = Group.objects.create(name='Test messages')
    group.permissions.set(Permission.objects.filter(content_type__app_label='messaging', codename='view_conversation'))
    writer.groups.add(group)
    direct = services.start_direct(admin, writer)
    services.post_as(admin, direct.pk, 'A test question?')
    gone = services.post_as(admin, direct.pk, 'A test message sent by mistake.')
    services.delete_message(admin, direct.pk, gone.pk)
    services.post_as(writer, direct.pk, 'A test answer.')
    services.post_as(writer, direct.pk, 'A second test answer,\non two lines.')
    channel = services.create_channel(admin, 'Test channel', [writer])
    services.post_as(writer, channel.pk, 'A test message to the channel.')
    long = services.create_channel(admin, 'Test long channel', [writer])
    for number in range(1, 61):      # a conversation longer than its plate: it opens at its newest message
        services.post_as(writer if number % 2 else admin, long.pk, f'Test message {number} of 60.')
    # a message's time is taken when it is made, on the real clock (Message.created_at's default): put it on MOMENT's, a
    # minute apart in the order they were written, so the pages say the same times on every run
    from datetime import timedelta
    from messaging.models import Message
    messages = list(Message.objects.order_by('pk'))
    for index, message in enumerate(messages):
        Message.objects.filter(pk=message.pk).update(created_at=MOMENT - timedelta(minutes=len(messages) - index))
    return [f'{Conversation.objects.count()} conversations']


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

    def shift(code, name, start, end, tone):
        return Shift.objects.create(name=name, code=code, starts_at=start, ends_at=end, break_minutes=0, grace_minutes=0,
                                    tone=tone)
    early, day = shift('TE1', 'Test early shift', time(6), time(10), 2), shift('TD1', 'Test morning shift', time(7), time(15), 3)
    midday = shift('TM1', 'Test midday shift', time(12), time(20), 4)
    later = shift('TL1', 'Test later shift', time(13, 30), time(21), 5)
    evening = shift('TV1', 'Test evening shift', time(18), time(23), 6)
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


# The cards of Operations › Monitoring in every state a card can be in (monitoring.read STATES), each a unit of its own in
# Test Hall A: (code, name, fish, protocol, hours back of its sample, the sample's values). The salmon's limits are the
# company and water worlds' (oxygen, temperature, pH) and this one's (alkalinity); the nitrite has none. The alkalinity
# draws each card's pH window and calculated CO₂.
MONITORING_UNITS = (
    ('TW-01', 'Test tank OK', True, True, 1, {'temperature_c': '13', 'oxygen_mg_l': '9', 'ph': '7.2', 'alkalinity_mg_l': '85'}),
    ('TW-02', 'Test tank critical', True, True, 1, {'temperature_c': '13', 'oxygen_mg_l': '5', 'ph': '7.2', 'alkalinity_mg_l': '85'}),
    ('TW-03', 'Test tank warning', True, True, 1, {'temperature_c': '13', 'oxygen_mg_l': '6.5', 'ph': '7.2', 'alkalinity_mg_l': '85'}),
    ('TW-04', 'Test tank old values', True, True, 30, {'temperature_c': '13', 'oxygen_mg_l': '9', 'ph': '7.2', 'alkalinity_mg_l': '85'}),
    ('TW-05', 'Test tank no limit', True, True, 1, {'temperature_c': '13', 'oxygen_mg_l': '9', 'ph': '7.2',
                                                   'nitrite_n_mg_l': '0.05'}),
    ('TW-06', 'Test tank no protocol', True, False, 1, {'temperature_c': '13', 'oxygen_mg_l': '9', 'ph': '7.2', 'alkalinity_mg_l': '85'}),
    ('TW-07', 'Test tank empty', False, False, 0, {}),
    # a critical oxygen that is old: the card stays critical and says the value is old (its second axis, the stale hatch)
    ('TW-08', 'Test tank old critical', True, True, 30, {'temperature_c': '13', 'oxygen_mg_l': '5', 'ph': '7.2',
                                                         'alkalinity_mg_l': '85'}),
)


TEST_WALL = 'Test wall, Hall A'
TEST_OPERATOR_BOARD = 'Test operator board, Hall A'


def monitoring_world(admin):
    """Eight more units of Test Hall A for the monitoring cards (MONITORING_UNITS), one in each state a card can be in:
    OK (fresh water inside its limits, a feeding protocol in force), critical and warning (the oxygen past its critical
    and its warning limit), no recent data (its water 30 hours old), no limit (a nitrite no limit row judges), a note (no
    feeding protocol: no ration, and why), empty (no fish), and a critical oxygen 30 hours old (critical, and stale).
    1,000 salmon of 50 g each, stocked ten days back; the
    protocol is a test table of one band (12 and 14 °C) fed with the water world's test feed; the salmon's alkalinity band
    (70 to 150 mg/L) is set here. Through the services where
    the record has one (stocking, the samples), straight into the tables otherwise (the protocol), as the tests do."""
    from farm.models import (Feed, FeedingProtocol, ProtocolAssignment, ProtocolBand, ProtocolRate,
                             ProductionDepartment, WaterLimit)
    from farm.tests.helpers import point_of, stock_fish
    from farm.tests.test_stock import make_unit
    from farm.water import services as water

    hall = ProductionDepartment.objects.get(code='THA')
    salmon = WaterLimit.objects.filter(parameter='oxygen_mg_l').first().species
    WaterLimit.objects.create(species=salmon, parameter='alkalinity_mg_l', water_type='any', warning_low=D(70),
                              warning_high=D(150))
    feed, _ = Feed.objects.get_or_create(code='TF-3', defaults={'name': 'Test Feed 3 mm', 'feed_type': 'grower',
                                                                'pellet_size_mm': D(3)})
    protocol = FeedingProtocol.objects.create(name='Test salmon table', species=salmon, expected_fcr=D('1.00'),
                                              status='active')
    band = ProtocolBand.objects.create(protocol=protocol, min_weight_g=D(0), max_weight_g=None, feed=feed,
                                       meals_per_day=4, expected_fcr=None)
    for column, sfr in (('12', '1.10'), ('14', '1.30')):
        ProtocolRate.objects.create(band=band, temperature_c=D(column), sfr_pct=D(sfr))
    for code, name, fish, fed, hours, values in MONITORING_UNITS:
        unit = make_unit(code, hall)
        unit.name = name
        unit.save(update_fields=['name'])
        if fish:
            stock_fish(admin, unit, 1000, '50', 10, species=salmon)
        if fed:
            ProtocolAssignment.objects.create(protocol=protocol, unit=unit, valid_from=_days_back(unit, 10))
        if values:
            water.record(admin, point=point_of(unit), measured_at=MOMENT - timedelta(hours=hours), source='manual',
                         values={key: D(value) for key, value in values.items()})
    wall_board(hall)
    operator_board(hall)


def wall_board(hall):
    """A wall board of Test Hall A's units (TEST_WALL): a 55-inch TV read from 2 m (its Wall screen tab), so its walls set
    their type for that distance and turn pages."""
    from farm.models import Tank
    from monitoring.models import MonitorBoard, MonitorBoardUnit

    board = MonitorBoard.objects.create(name=TEST_WALL, screen='55', screen_inches=D(55), distance_m=D(2))
    for unit in Tank.objects.filter(production_department=hall).order_by('code'):
        MonitorBoardUnit.objects.create(board=board, unit=unit)
    return board


def operator_board(hall):
    """A desk board of Test Hall A's units (TEST_OPERATOR_BOARD) whose cards are the built-in Operator view (the board's
    default template): the oxygen and the temperature first and large, then the fish, the feeding and the Deffeyes
    chart's button, so the monitoring pages and their browser test draw that template too."""
    from farm.models import Tank
    from monitoring.cards import builtin
    from monitoring.models import MonitorBoard, MonitorBoardUnit

    board = MonitorBoard.objects.create(name=TEST_OPERATOR_BOARD, default_template_id=builtin.OPERATOR)
    for unit in Tank.objects.filter(production_department=hall).order_by('code'):
        MonitorBoardUnit.objects.create(board=board, unit=unit)
    return board


def feeding_ops_world(admin):
    """Feeding's pages (farm/tests/test_feeding_pages_next.py), after world(): a protocol in force on TT-01 (one band of the
    water world's test feed, 8 and 14 °C, so TT-01's 12 °C reads between the columns), a meal given to TT-01 today, and a
    feeding of two days back entered twice and voided. TM-01 has no protocol: its line says why it has no ration. Through
    the services where the record has one (the feedings, the void), straight into the tables otherwise (the protocol)."""
    from farm.feeding import services
    from farm.models import Feed, FeedingProtocol, ProtocolAssignment, ProtocolBand, ProtocolRate, Tank

    tank = Tank.objects.get(code='TT-01')
    feed = Feed.objects.get(code='TF-3')
    protocol = FeedingProtocol.objects.create(name='Test hall table', species=_batch_of(tank).species,
                                              expected_fcr=D('1.00'), status='active')
    band = ProtocolBand.objects.create(protocol=protocol, min_weight_g=D(0), max_weight_g=None, feed=feed,
                                       meals_per_day=4, expected_fcr=None)
    for column, sfr in (('8', '1.00'), ('14', '1.40')):
        ProtocolRate.objects.create(band=band, temperature_c=D(column), sfr_pct=D(sfr))
    ProtocolAssignment.objects.create(protocol=protocol, unit=tank, valid_from=_days_back(tank, 10))
    services.record_feeding(admin, unit=tank, day=_days_back(tank, 0), feed=feed, amount_kg=D('0.15'), time=time(7, 30),
                            meals=1)
    twice = services.record_feeding(admin, unit=tank, day=_days_back(tank, 2), feed=feed, amount_kg=D('0.6'),
                                    time=time(9, 0), notes='Test entry')
    services.void_feeding(admin, twice, 'Entered twice')


def health_ops_world(admin):
    """Health's pages (farm/tests/test_health_pages_next.py), after world(): TM-01 bathed with the forms world's Test
    Medicine two days back (its withdrawal holds the fish), a sea-lice count of TM-01 yesterday over the limit (12 adult
    females on 20 fish), a vet's suspicion of pancreas disease on Test Site South not yet notified (Notify Mattilsynet)
    and a closed observation at Test Site North. Through the services where the record has one (the treatment, the
    count), straight into the table otherwise (the events, as the health tests do)."""
    from farm.health import services
    from farm.models import HealthEvent, Medicine, Site, Tank

    cage = Tank.objects.get(code='TM-01')
    day = _days_back(cage, 2)
    medicine = Medicine.objects.get(name='Test Medicine')
    seen = services.handling([cage], day, 'bath', medicine, 'sea_lice').fingerprint
    services.record_treatment(admin, units=[cage], method='bath', reason='sea_lice', start_date=day, end_date=day,
                              medicine=medicine, dose_value=D('0.1'), dose_unit='mg_l', prescribed_by='Test Vet',
                              prescription_ref='RX-TEST-1', handling_ack=seen or None)
    services.record_lice_count(admin, unit=cage, day=_days_back(cage, 1), fish_counted=20, adult_females=12, mobile=10,
                               attached=14)
    suspicion = HealthEvent.objects.create(site=Site.objects.get(code='TSS'), date=_days_back(cage, 3), kind='vet_visit',
                                           diagnosis='pd', confirmation='suspected', examined_by='Test Vet',
                                           findings='Test findings: lethargy in the cage.')
    suspicion.units.set([cage])
    HealthEvent.objects.create(site=Site.objects.get(code='TSN'), date=_days_back(cage, 9), kind='observation',
                               examined_by='Test Person', findings='Test findings: pale gills.',
                               closed_on=_days_back(cage, 7), outcome='Test outcome: recovered.')


def harvest_ops_world(admin):
    """Harvest's pages (farm/tests/test_harvest_pages_next.py), after world() and health_ops_world(): a harvest of TM-01
    planned in four days to the harvest world's Test Slaughterhouse (TM-01's withdrawal falls on it), a transport of TT-01
    planned yesterday and not done (overdue), and a production plan of TT-01's batch (250 g)."""
    from farm.models import HandlingPlanItem, ProductionPlan, SlaughterFacility, Tank

    cage, tank = Tank.objects.get(code='TM-01'), Tank.objects.get(code='TT-01')
    facility = SlaughterFacility.objects.get(name='Test Slaughterhouse')
    HandlingPlanItem.objects.create(kind='harvest', date=_days_back(cage, -4), unit=cage, batch=_batch_of(cage),
                                    planned_count=400, planned_kg=D('380'), facility=facility, vessel='Test Wellboat')
    HandlingPlanItem.objects.create(kind='transport', date=_days_back(tank, 1), unit=tank, batch=_batch_of(tank),
                                    planned_count=100, destination_unit=cage, notes='Test transport note')
    ProductionPlan.objects.create(batch=_batch_of(tank), target_weight_g=D('250'))

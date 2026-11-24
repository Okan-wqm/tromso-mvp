"""The TEST WORLD: the one set of records the browser tests' fixtures and props are made from, never the development
database (owner's privacy rule, 2026-11-24: the repository is public). Every person, address and name is a fixture value
(names "Test …", addresses @example.com; core/tests_fixture_privacy.py guards the addresses). It is built in a test
database only: by scripts/record_test_world.py in the throwaway database test_world (scripts/record_test_world.sh), and
by the tests that make the islands' props in the test run's own database. The clock is pinned to MOMENT while it is
built and read.

    world(admin)                      every part below, in order, through a client signed in as `admin`
    company_world(admin, client)      the company's: sites, a hall, a loop, units with fish, a storage location, a
                                      library document, a knowledge entry, a person, a role and an employee
    hr_world(admin, client)           the people's: office departments, employees placed and one who left, shifts, a
                                      holiday, a leave type, leave requests and attendance
    forms_world(admin, client)        the rows of the forms with lists of their own: a site's and a supplier's contacts,
                                      a feeder's calibration, a feed's suitability, a medicine's withdrawal, a reorder
                                      level, a board's card, a task's and a recurring task's checklist, a device with a
                                      channel and its calibration, a sensor credential, a lice and a biomass report"""
from datetime import datetime
from decimal import Decimal as D

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import Client
from django.urls import reverse

MOMENT = datetime.fromisoformat('2026-11-23T12:42:00+00:00')


def world(admin):
    """The test world, built through a client signed in as `admin`; [what was made: its answer] of the parts posted."""
    client = Client(HTTP_HOST='localhost')
    client.force_login(admin)
    return company_world(admin, client) + hr_world(admin, client) + forms_world(admin, client)


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


def forms_world(admin, client):
    """The rows of the forms that have lists of their own (core.crud.RowList), each list saved through its own address as
    a person saves it (its RowListView, the record's version sent with it): a contact of the north site, a supplier with
    a contact, a feeder with a calibration, a feed suited to the salmon, a medicine with its withdrawal, a reorder level of
    the store, a monitoring board with a card, a task and a recurring task with a checklist, a device with a channel and
    its calibration, a sensor credential, and a draft lice report and biomass report. Made on MOMENT's day."""
    from core.crud import Resource
    from farm.models import Equipment, EquipmentType, Feed, Medicine, ProductionDepartment, Site, Species, Supplier, Tank
    from farm.tests.helpers import rows_data
    from inventory.models import StorageLocation
    from monitoring.models import MonitorBoard
    from sensors.models import Credential
    from sensors.tests import make_channel, make_connection, make_device, make_format
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
    rows(StorageLocation.objects.get(code='TS-01'), 'reorder', [{'feed': str(feed.pk), 'level': '600'}])
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
    device = make_device(make_connection('Test broker'), make_format('Test format'), north, code='TEST-1')
    channel = make_channel(device, 'temperature_c', code='TEST-T')
    rows(channel, 'calibrations', [{'valid_from': '22.11.2026 10:00', 'gain': '1.02', 'offset': '-0.1', 'performed_by': '',
                                    'note': 'Test calibration'}])
    Credential.objects.create(username='test-gateway')
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

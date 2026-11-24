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
                                      holiday, a leave type, leave requests, attendance and a week's plan"""
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
    return company_world(admin, client) + hr_world(admin, client)


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

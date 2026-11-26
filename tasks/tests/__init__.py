"""Shared setup for the Tasks tests: a farm with every kind of place (a production department without a site among
them), people who may read, create, edit or delete tasks, and one who may not."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase

from farm.models import Equipment, EquipmentType, ProductionDepartment, Site, System
from farm.stock.dates import site_today
from farm.tests.helpers import leave_without_site, may_record, role
from farm.tests.test_stock import make_unit

from ..models import Task

READ = ('view_task',)
WORKER = ('view_task', 'view_taskseries')
SUPERVISOR = ('view_task', 'add_task', 'change_task', 'delete_task', 'view_taskseries', 'add_taskseries',
              'change_taskseries', 'delete_taskseries', 'view_auditlog')


def person(username, *codenames, **fields):
    user = get_user_model().objects.create_user(username, f'{username}@example.com', 'x', **fields)
    if codenames:
        user.groups.add(role(f'{username} role', *codenames))
    return user


class TasksTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.boss = person('boss', *SUPERVISOR, first_name='Berit', last_name='Sjef')
        cls.ali = person('ali', *WORKER, first_name='Ali', last_name='Kaya')
        cls.kari = person('kari', *READ, first_name='Kari', last_name='Nord')
        cls.gone = person('gone', *READ, first_name='Gone', last_name='Away', is_active=False)
        cls.outsider = person('olav', 'view_site')
        cls.stocker = may_record(person('stocker'))         # stocks the fish a task is about (the stock service asks)
        cls.bergen = Site.objects.create(name='Bergen', code='BG', timezone='Europe/Oslo')
        cls.tromso = Site.objects.create(name='Tromso', code='TR', timezone='Europe/Oslo')
        cls.hall = ProductionDepartment.objects.create(site=cls.bergen, name='Hall A', code='HA')
        cls.sea = ProductionDepartment.objects.create(site=cls.tromso, name='Sea', code='SE')
        # A department a deleted site left without one, from before that was refused (F-212).
        cls.loose = leave_without_site(ProductionDepartment.objects.create(site=cls.bergen, name='Old hall', code='OH'))
        cls.ras = System.objects.create(site=cls.bergen, production_department=cls.hall, name='RAS 1', code='R1')
        cls.t1 = make_unit('T-01', cls.hall)
        cls.t2 = make_unit('T-02', cls.sea)
        cls.t9 = make_unit('T-09', cls.loose)
        pump = EquipmentType.objects.filter(category='pump').first()
        cls.pump = Equipment.objects.create(name='Main pump', code='PMP-1', production_department=cls.hall,
                                            equipment_type=pump)
        cls.today = site_today(cls.bergen)

    def setUp(self):
        self.client.force_login(self.boss)

    def day(self, offset):
        return self.today + timedelta(days=offset)

    def make_task(self, place=None, assignees=None, **fields):
        values = {'title': 'Clean the drum filter', 'due_date': self.today, **fields}
        task = Task(**values)
        task.set_place(place or self.t1)
        task.save()
        task.assignees.set(assignees if assignees is not None else [self.ali])
        return task


def form_data(**overrides):
    """What the task form posts: a cleaning job; the test fills in where, when and for whom."""
    data = {'title': 'Clean the drum filter', 'description': '', 'category': 'cleaning', 'priority': 'medium',
            'site': '', 'location': '', 'batch': '', 'due_date': '', 'due_time': '', 'assignees': []}
    data.update(overrides)
    return data

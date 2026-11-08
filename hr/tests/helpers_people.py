"""People for the tests of the team scope: a site, departments of both kinds, employees placed in them and the people who
manage them."""
from datetime import date

from django.contrib.auth import get_user_model

from farm.models import ProductionDepartment, Site

from ..models import Employee, OfficeDepartment, Posting
from .helpers import HrTestCase, user

LEAD_PERMS = ('view_employee', 'view_officedepartment', 'view_shiftassignment', 'view_attendancerecord')
TOP = date(2026, 1, 1)


def employee(number, last='Nordmann', first='Kari', on=TOP, **fields):
    """A person without an account, joined on `on`."""
    return Employee.objects.create(employee_number=number, last_name=last, first_name=first, joined_on=on, **fields)


def place(person, department, start=TOP, until=None, title=''):
    field = 'production_department' if isinstance(department, ProductionDepartment) else 'office_department'
    return Posting.objects.create(employee=person, valid_from=start, valid_until=until, title=title,
                                  **{field: department})


class PeopleTestCase(HrTestCase):
    """Two production departments (A, B) with a manager each, an office tree (Administration > Finance), and a person
    placed in each; plus an HR administrator holding Everyone."""

    def setUp(self):
        super().setUp()
        self.site = Site.objects.create(name='Bergen', code='BG', timezone='UTC')     # the clock the tests count on
        self.lead_a = user('leada', *LEAD_PERMS, group='Lead A role')
        self.lead_b = user('leadb', *LEAD_PERMS, group='Lead B role')
        self.dept_a = ProductionDepartment.objects.create(site=self.site, name='Hatchery A', code='HAT-A',
                                                          manager=self.lead_a)
        self.dept_b = ProductionDepartment.objects.create(site=self.site, name='Nursery B', code='NUR-B',
                                                          manager=self.lead_b)
        self.admin_dept = OfficeDepartment.objects.create(site=self.site, name='Administration', code='ADM')
        self.finance = OfficeDepartment.objects.create(site=self.site, name='Finance', code='FIN',
                                                       parent=self.admin_dept)
        self.in_a = employee('E-1', 'Alfa', 'Ann')
        self.in_b = employee('E-2', 'Bravo', 'Bob')
        self.in_fin = employee('E-3', 'Charlie', 'Cy')
        place(self.in_a, self.dept_a, title='Technician')
        place(self.in_b, self.dept_b, title='Feeder')
        place(self.in_fin, self.finance, title='Accountant')
        self.hr = user('hradmin', 'view_employee', 'add_employee', 'change_employee', 'all_employee',
                       'view_officedepartment', group='HR admin role')

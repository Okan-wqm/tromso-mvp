"""What the HR pages show, read from the records on the viewer's behalf. Nothing here is stored: a department's
head count, who is present, on leave or late are worked out when a page is read (docs: Human resources)."""
from dataclasses import dataclass

from django.db.models import Count

from core.models import in_tree_order
from farm.models import ProductionDepartment
from farm.stock.dates import site_today

from . import scope
from .models import OfficeDepartment, Posting

PRODUCTION, OFFICE = 'production', 'office'


@dataclass
class DepartmentRow:
    """One line of the Departments page: a production department (the farm's own row, shown here by itself) or an
    office department (HR's). `depth` nests an office department under its parent."""
    kind: str
    obj: object
    depth: int = 0
    head_count: int = 0     # the people placed in it today that the viewer may reach

    @property
    def name(self):
        return self.obj.name

    @property
    def code(self):
        return self.obj.code

    @property
    def status(self):
        return self.obj.status

    @property
    def manager(self):
        return self.obj.manager

    @property
    def site(self):
        return self.obj.site

    @property
    def parent(self):
        return self.obj.parent if self.kind == OFFICE else None

    @property
    def pk(self):
        return self.obj.pk


def head_counts(user, day=None):
    """{(kind, department id): people placed in it on `day`} among the people `user` may reach: one grouped query."""
    day = day or site_today(None)
    rows = (Posting.objects.filter(scope.covering(day), employee__in=scope.team(user, day).values('pk'))
            .values('production_department', 'office_department').annotate(people=Count('pk')))
    return {(PRODUCTION if row['production_department'] else OFFICE,
             row['production_department'] or row['office_department']): row['people'] for row in rows}


def departments(user=None):
    """Every live department, production first (by site and name, flat) and then the office ones in tree order, each
    with the head count the viewer may see. A production department created, renamed or deleted on the farm side is
    here at once: this is the same row."""
    production = ProductionDepartment.objects.select_related('site', 'manager').order_by('site__name', 'name')
    office = OfficeDepartment.objects.select_related('site', 'manager', 'parent').order_by('name')
    counts = head_counts(user) if user is not None else {}
    return ([DepartmentRow(PRODUCTION, department, head_count=counts.get((PRODUCTION, department.pk), 0))
             for department in production]
            + [DepartmentRow(OFFICE, department, department.depth, counts.get((OFFICE, department.pk), 0))
               for department in in_tree_order(office)])


def placement_on(employee, day):
    """The placement that covers `day`, or None."""
    return Posting.objects.filter(scope.covering(day), employee=employee).select_related(
        'production_department', 'office_department').first()

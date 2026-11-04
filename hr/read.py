"""What the HR pages show, read from the records on the viewer's behalf. Nothing here is stored: a department's
head count, who is present, on leave or late are worked out when a page is read (docs: Human resources)."""
from dataclasses import dataclass

from core.models import in_tree_order
from farm.models import ProductionDepartment

from .models import OfficeDepartment

PRODUCTION, OFFICE = 'production', 'office'


@dataclass
class DepartmentRow:
    """One line of the Departments page: a production department (the farm's own row, shown here by itself) or an
    office department (HR's). `depth` nests an office department under its parent."""
    kind: str
    obj: object
    depth: int = 0

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


def departments():
    """Every live department, production first (by site and name, flat) and then the office ones in tree order. A
    production department created, renamed or deleted on the farm side is here at once: this is the same row."""
    production = ProductionDepartment.objects.select_related('site', 'manager').order_by('site__name', 'name')
    office = OfficeDepartment.objects.select_related('site', 'manager', 'parent').order_by('name')
    return ([DepartmentRow(PRODUCTION, department) for department in production]
            + [DepartmentRow(OFFICE, department, department.depth) for department in in_tree_order(office)])

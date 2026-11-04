"""What the HR pages show, read from the records on the viewer's behalf. Nothing here is stored: a department's
head count, who is present, on leave or late are worked out when a page is read (docs: Human resources)."""
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from django.core.paginator import Paginator
from django.db.models import Count, Q

from core.models import in_tree_order
from farm.models import ProductionDepartment
from farm.models.site import zone_of
from farm.stock.dates import site_today

from . import clock, rules, scope, units
from .models import Employee, Holiday, OfficeDepartment, Posting, SchedulingSettings, ShiftAssignment

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


# ---- the week's roster ------------------------------------------------------------------------------------------
WEEK_MARGIN = 15          # days read either side of a week for the rest across its border and a run of days


def monday(day):
    return day - timedelta(days=day.weekday())


def site_of_posting(posting):
    department = posting.department
    return getattr(department, 'site', None) if department is not None else None


def site_on(employee, day):
    """The site whose clock and holidays govern the person on `day`: the site of the department they are placed in
    then; None (the company's clock) when they have none or it has no site."""
    posting = placement_on(employee, day)
    return site_of_posting(posting) if posting is not None else None


@dataclass
class Cell:
    """One person on one day of the week. `visible` is false on the days the viewer does not reach the person on (a
    person who moved), so the cell says nothing; `findings` are the rules' findings for that day."""
    day: date
    visible: bool = True
    assignment: object = None
    holiday: object = None
    findings: list = field(default_factory=list)

    @property
    def shift(self):
        return self.assignment.shift if self.assignment is not None else None

    @property
    def is_off(self):
        return self.assignment is not None and self.assignment.shift_id is None

    @property
    def blocks(self):
        return any(item.blocks for item in self.findings)

    @property
    def finding_text(self):
        return ' '.join(rules.text(item) for item in self.findings)


@dataclass
class Row:
    employee: object
    department: object
    cells: list
    planned_minutes: int = 0
    week_findings: list = field(default_factory=list)

    @property
    def planned_hours(self):
        return Decimal(self.planned_minutes) / 60


@dataclass
class Week:
    start: date
    days: list
    rows: list
    shown: int
    total: int
    page: int
    pages: int

    @property
    def end(self):
        return self.days[-1]

    @property
    def previous(self):
        return self.start - timedelta(days=7)

    @property
    def next(self):
        return self.start + timedelta(days=7)


def week(user, week_start, department=None, page=1, per_page=50, query=''):
    """The roster of the ISO week starting `week_start` (a Monday) for the people `user` may reach, `per_page` of them:
    each person's cell per day (their shift, planned off, a holiday, or nothing planned) and the rules' findings. The
    queries do not depend on the number of people: the employees of the page, their plan from a fortnight either side,
    their placements and the holidays."""
    start = monday(week_start)
    days = [start + timedelta(days=n) for n in range(7)]
    visible = scope.visible_days(user, days[0], days[-1])
    people = Employee.objects.filter(joined_on__lte=days[-1]).filter(Q(left_on__isnull=True) | Q(left_on__gte=days[0]))
    if visible is not None:
        people = people.filter(pk__in=list(visible))
    if department is not None:
        field_name = units.field_of(department)
        people = people.filter(pk__in=Posting.objects.filter(
            scope.overlapping(days[0], days[-1]), **{field_name: department}).values('employee'))
    if query:
        people = people.filter(Q(employee_number__icontains=query) | Q(first_name__icontains=query)
                               | Q(last_name__icontains=query) | Q(user__username__icontains=query)
                               | Q(user__first_name__icontains=query) | Q(user__last_name__icontains=query))
    people = people.select_related('user').order_by('last_name', 'first_name', 'employee_number')
    paginator = Paginator(people, per_page)
    shown = paginator.get_page(page)
    employees = list(shown.object_list)
    ids = [employee.pk for employee in employees]
    settings = SchedulingSettings.get()
    window = (days[0] - timedelta(days=WEEK_MARGIN), days[-1] + timedelta(days=WEEK_MARGIN))
    plan = {}
    for row in ShiftAssignment.objects.filter(employee__in=ids, day__range=window).select_related('shift'):
        plan.setdefault(row.employee_id, {})[row.day] = row
    postings = {}
    for posting in Posting.objects.filter(scope.overlapping(days[0], days[-1]), employee__in=ids).select_related(
            'production_department__site', 'office_department__site').order_by('valid_from'):
        postings.setdefault(posting.employee_id, []).append(posting)
    holidays = list(Holiday.objects.filter(day__range=(days[0], days[-1])))
    rows = []
    for employee in employees:
        placed = postings.get(employee.pk, [])
        head = placed[0] if placed else None
        site = site_of_posting(head) if head is not None else None
        zone = zone_of(site)
        mine = plan.get(employee.pk, {})
        holiday_of = {holiday.day: holiday for holiday in holidays if holiday.site_id in (None, getattr(site, 'pk', None))}
        planned = []
        for day, assignment in sorted(mine.items()):
            if assignment.shift is not None:
                first, last = clock.span(day, assignment.shift, zone)
                planned.append(rules.Planned(day, first, last, clock.net_minutes(first, last,
                                                                                assignment.shift.break_minutes)))
        found = rules.findings(planned, set(), set(holiday_of), settings, [start])
        reach = visible.get(employee.pk, set()) if visible is not None else set(days)
        cells = []
        for day in days:
            cell = Cell(day, visible=day in reach, assignment=mine.get(day) if day in reach else None,
                        holiday=holiday_of.get(day) if day in reach else None)
            cell.findings = [item for item in found if item.day == day and day in reach]
            cells.append(cell)
        total = sum(item.net_minutes for item in planned if item.day in reach and monday(item.day) == start)
        rows.append(Row(employee, head.department if head is not None else None, cells, total,
                        [item for item in found if item.code == rules.WEEK_HOURS]))
    return Week(start, days, rows, len(rows), paginator.count, shown.number, paginator.num_pages)

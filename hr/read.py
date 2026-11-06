"""What the HR pages show, read from the records on the viewer's behalf. Nothing here is stored: a department's
head count, who is present, on leave or late are worked out when a page is read (docs: Human resources)."""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.utils import timezone
from django.utils.translation import gettext as _

from core.models import in_tree_order
from core.navigation import Badge
from farm.clocks import clocks
from farm.models import ProductionDepartment
from farm.models.site import zone_of
from farm.stock.dates import site_today

from . import clock, leave, rules, scope, units
from .models import (AttendanceRecord, Employee, Holiday, LeaveRequest, OfficeDepartment, Posting, SchedulingSettings,
                     ShiftAssignment)
from .models.leave import LeaveStatus
from .scope import OFFICE, PRODUCTION      # the two kinds of department are the two realms


@dataclass
class DepartmentRow:
    """One line of Company › HR › Departments: an office department (HR's own; the production departments are the farm's,
    under Production). `depth` nests it under its parent."""
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
        return self.obj.parent

    @property
    def pk(self):
        return self.obj.pk


def head_counts(user, day=None, realm=None):
    """{(kind, department id): people placed in it on `day`} among the people `user` may reach (in `realm`, if given): one
    grouped query."""
    day = day or site_today(None)
    rows = (Posting.objects.filter(scope.covering(day), employee__in=scope.team(user, day, realm).values('pk'))
            .values('production_department', 'office_department').annotate(people=Count('pk')))
    return {(PRODUCTION if row['production_department'] else OFFICE,
             row['production_department'] or row['office_department']): row['people'] for row in rows}


def departments(user=None):
    """Every live office department in tree order, each with the head count the viewer may see. The production departments
    are not here: they are the farm's rows, listed under Production (Setup, and Team's organisation chart)."""
    office = OfficeDepartment.objects.select_related('site', 'manager', 'parent').order_by('name')
    counts = head_counts(user, realm=OFFICE) if user is not None else {}
    return [DepartmentRow(department, department.depth, counts.get((OFFICE, department.pk), 0))
            for department in in_tree_order(office)]


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


def sites_of(pairs):
    """{(employee id, day): the site of the department they are placed in that day, or None}, for several pairs in one
    query."""
    pairs = list(pairs)
    if not pairs:
        return {}
    placed = defaultdict(list)
    low, high = min(day for _id, day in pairs), max(day for _id, day in pairs)
    for posting in Posting.objects.filter(scope.overlapping(low, high), employee__in={pk for pk, _day in pairs}
                                          ).select_related('production_department__site', 'office_department__site'):
        placed[posting.employee_id].append(posting)
    found = {}
    for pk, day in pairs:
        covering = next((p for p in placed[pk] if p.valid_from <= day and (p.valid_until is None or p.valid_until >= day)),
                        None)
        found[(pk, day)] = site_of_posting(covering) if covering is not None else None
    return found


@dataclass
class Cell:
    """One person on one day of the week. `visible` is false on the days the viewer does not reach the person on (a
    person who moved), so the cell says nothing; `findings` are the rules' findings for that day."""
    day: date
    visible: bool = True
    assignment: object = None
    holiday: object = None
    on_leave: bool = False
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


def week(user, week_start, department=None, page=1, per_page=50, query='', realm=None):
    """The roster of the ISO week starting `week_start` (a Monday) for the people `user` may reach, `per_page` of them:
    each person's cell per day (their shift, planned off, a holiday, or nothing planned) and the rules' findings. The
    queries do not depend on the number of people: the employees of the page, their plan from a fortnight either side,
    their placements and the holidays. With a realm (hr.scope), a person shows only on the days they were in it.
    Production › Team and Company › HR read the same week this way."""
    start = monday(week_start)
    days = [start + timedelta(days=n) for n in range(7)]
    visible = scope.visible_days(user, days[0], days[-1], realm)
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
    on_leave = leave.approved_days(ids, window[0], window[1])
    rows = []
    for employee in employees:
        placed = postings.get(employee.pk, [])
        reach = visible.get(employee.pk, set()) if visible is not None else set(days)
        # the department, site and clock are those of the first day the viewer reaches the person on, never another team's
        first_reached = min(reach) if reach else days[0]
        head = next((p for p in placed if p.valid_from <= first_reached and (p.valid_until is None
                                                                             or p.valid_until >= first_reached)), None)
        site = site_of_posting(head) if head is not None else None
        zone = zone_of(site)
        mine = plan.get(employee.pk, {})
        holiday_of = {holiday.day: holiday for holiday in holidays if holiday.site_id in (None, getattr(site, 'pk', None))}
        planned = []
        for day, assignment in sorted(mine.items()):
            # only what the viewer reaches goes into the rules, so a finding cannot show a shift of another team's days
            if assignment.shift is not None and (visible is None or day in reach):
                first, last = clock.span(day, assignment.shift, zone)
                planned.append(rules.Planned(day, first, last, clock.net_minutes(first, last,
                                                                                assignment.shift.break_minutes)))
        away = on_leave.get(employee.pk, set())
        found = rules.findings(planned, away, set(holiday_of), settings, [start])
        cells = []
        for day in days:
            cell = Cell(day, visible=day in reach, assignment=mine.get(day) if day in reach else None,
                        holiday=holiday_of.get(day) if day in reach else None, on_leave=day in reach and day in away)
            cell.findings = [item for item in found if item.day == day and day in reach]
            cells.append(cell)
        total = sum(item.net_minutes for item in planned if item.day in reach and monday(item.day) == start)
        rows.append(Row(employee, head.department if head is not None else None, cells, total,
                        [item for item in found if item.code == rules.WEEK_HOURS]))
    return Week(start, days, rows, len(rows), paginator.count, shown.number, paginator.num_pages)


# ---- the crew: what a production worker sees of their colleagues ---------------------------------------------------
@dataclass
class CrewCell:
    """A colleague working on a day: the shift's code, times and tone, and nothing else."""
    day: date
    shift_code: str
    starts_at: object
    ends_at: object
    tone: int


@dataclass
class CrewRow:
    """A colleague's week: their name, the department they share with the viewer, and a cell per day; None where they do not
    work (planned off, on leave, nothing planned, or not in the viewer's department that day: the same empty cell)."""
    name: str
    department: str
    cells: list


@dataclass
class CrewWeek:
    days: list
    rows: list


def crew_week(user, week_start):
    """The week of the viewer's crew (hr.scope.colleagues) for the Crew block of their schedule. Built from plain values, never
    from a plan, a leave request or a punch, so it cannot carry a note, a finding, a leave type, an absence or a number of
    hours, whatever a page does with it; and nothing in it opens a record. In a fixed number of queries."""
    start = monday(week_start)
    days = [start + timedelta(days=n) for n in range(7)]
    crew = scope.colleagues(user, days[0], days[-1])
    if not crew:
        return CrewWeek(days, [])
    people = list(Employee.objects.filter(pk__in=list(crew), joined_on__lte=days[-1]).filter(
        Q(left_on__isnull=True) | Q(left_on__gte=days[0])).select_related('user').order_by(
        'last_name', 'first_name', 'employee_number'))
    ids = [person.pk for person in people]
    plan = {(row.employee_id, row.day): row.shift for row in ShiftAssignment.objects.filter(
        employee__in=ids, day__range=(days[0], days[-1]), shift__isnull=False).select_related('shift')}
    away = leave.approved_days(ids, days[0], days[-1])
    placed = defaultdict(list)
    for posting in Posting.objects.filter(scope.overlapping(days[0], days[-1]), employee__in=ids,
                                          production_department__isnull=False).select_related(
            'production_department').order_by('valid_from'):
        placed[posting.employee_id].append(posting)
    rows = []
    for person in people:
        cells = []
        for day in days:
            shift = plan.get((person.pk, day))
            works = day in crew[person.pk] and shift is not None and day not in away.get(person.pk, set())
            cells.append(CrewCell(day, shift.code, shift.starts_at, shift.ends_at, shift.tone) if works else None)
        first = min(crew[person.pk])       # the department they share with the viewer, on the first day they do
        shared = next((p for p in placed[person.pk]
                       if p.valid_from <= first and (p.valid_until is None or p.valid_until >= first)), None)
        rows.append(CrewRow(person.full_name, shared.production_department.name if shared else '', cells))
    return CrewWeek(days, rows)


# ---- today: who is where ----------------------------------------------------------------------------------------
@dataclass
class BoardRow:
    """One person on today's board: their planned shift (or none: an unplanned presence), the span as instants and their
    standing now."""
    employee: object
    department: object
    shift: object
    span: tuple
    standing: object
    day: date
    zone: object

    @property
    def state(self):
        return self.standing.state

    @property
    def unscheduled(self):
        return self.shift is None and self.span is None


@dataclass
class Board:
    rows: list
    counts: dict
    planned: int
    moment: object

    def count(self, state):
        return self.counts.get(state, 0)

    @property
    def here(self):
        return self.count(rules.PRESENT) + self.count(rules.LATE)


def _clock_of(placed, low, high, by_site, company_clock):
    """(the placement that governs the person between `low` and `high`, today and the zone on its site's clock)."""
    head = next((p for p in placed if p.valid_from <= high and (p.valid_until is None or p.valid_until >= low)), None)
    site = site_of_posting(head) if head is not None else None
    clock_here = by_site.get(getattr(site, 'pk', None), company_clock)
    return head, clock_here.today, clock_here.zone


def current_shift(plan, employee_id, today, zone, moment):
    """The shift a person's plan has running or ahead at `moment`: (shift, its span, its day) of the night that began
    yesterday while it is still running, else of the shift that starts today; None when neither is planned. `plan` is
    {(employee id, day): ShiftAssignment}. The board and `on_shift` read this one rule."""
    options = {}
    for day in (today - timedelta(days=1), today):
        cell = plan.get((employee_id, day))
        if cell is not None and cell.shift is not None:
            options[day] = (cell.shift, clock.span(day, cell.shift, zone), day)
    yesterday = options.get(today - timedelta(days=1))
    return yesterday if yesterday is not None and yesterday[1][1] > moment else options.get(today)


def on_shift(moment=None):
    """The ids of the accounts whose planned shift runs at `moment` on their site's clock (current_shift), not on approved
    leave that day: who an alarm for the people on shift reaches (alarms/routing.py). People without an account are never
    in it. In a fixed number of queries whatever the number of people."""
    moment = moment or timezone.now()
    clocks_now = clocks(moment)
    by_site = {site: clock for clock in clocks_now if clock.sites is not None for site in clock.sites}
    company_clock = next(clock for clock in clocks_now if clock.sites is None)
    low, high = min(c.today for c in clocks_now), max(c.today for c in clocks_now)
    people = list(Employee.objects.filter(user__isnull=False, user__is_active=True, joined_on__lte=high)
                  .filter(Q(left_on__isnull=True) | Q(left_on__gte=low)))
    ids = [employee.pk for employee in people]
    postings = defaultdict(list)
    for posting in Posting.objects.filter(scope.overlapping(low, high), employee__in=ids).select_related(
            'production_department__site', 'office_department__site').order_by('valid_from'):
        postings[posting.employee_id].append(posting)
    plan = {(row.employee_id, row.day): row for row in ShiftAssignment.objects.filter(
        employee__in=ids, day__range=(low - timedelta(days=1), high)).select_related('shift')}
    away = leave.approved_days(ids, low, high)
    found = set()
    for employee in people:
        _head, today, zone = _clock_of(postings.get(employee.pk, []), low, high, by_site, company_clock)
        chosen = current_shift(plan, employee.pk, today, zone, moment)
        if chosen is None:
            continue
        _shift, (start, end), _day = chosen
        if start <= moment < end and today not in away.get(employee.pk, set()):      # the board's leave rule
            found.add(employee.user_id)
    return found


def board(user, moment=None, realm=None):
    """Who is where now, for the people `user` may reach: each person's planned shift today (or the night shift that began
    yesterday and is still running), their punches, their leave, and the state worked out from them (rules.status) on their
    site's clock. People planned off, on a holiday or with nothing planned are not listed, unless they are there all the
    same. In a fixed number of queries whatever the number of people. With a realm, only the people in it today."""
    moment = moment or timezone.now()
    clocks_now = clocks(moment)
    by_site = {site: clock for clock in clocks_now if clock.sites is not None for site in clock.sites}
    company_clock = next(clock for clock in clocks_now if clock.sites is None)
    low, high = min(c.today for c in clocks_now), max(c.today for c in clocks_now)
    settings = SchedulingSettings.get()
    people = list(scope.team(user, high, realm).filter(joined_on__lte=high).filter(Q(left_on__isnull=True) | Q(left_on__gte=low))
                  .select_related('user').order_by('last_name', 'first_name', 'employee_number'))
    ids = [employee.pk for employee in people]
    postings = defaultdict(list)
    for posting in Posting.objects.filter(scope.overlapping(low, high), employee__in=ids).select_related(
            'production_department__site', 'office_department__site').order_by('valid_from'):
        postings[posting.employee_id].append(posting)
    plan = {(row.employee_id, row.day): row for row in ShiftAssignment.objects.filter(
        employee__in=ids, day__range=(low - timedelta(days=1), high)).select_related('shift')}
    punches = defaultdict(list)
    for record in AttendanceRecord.objects.filter(employee__in=ids, clock_in__gte=moment - timedelta(days=2),
                                               clock_in__lte=moment):
        punches[record.employee_id].append(record)
    away = leave.approved_days(ids, low, high)
    rows = []
    counts = defaultdict(int)
    planned = 0
    for employee in people:
        head, today, zone = _clock_of(postings.get(employee.pk, []), low, high, by_site, company_clock)
        chosen = current_shift(plan, employee.pk, today, zone, moment)
        mine = [(record.clock_in, record.clock_out) for record in punches.get(employee.pk, [])]
        on_leave = today in away.get(employee.pk, set())
        shift, span, day = chosen if chosen is not None else (None, None, today)
        standing = rules.status(span, mine, on_leave, moment, shift.grace_minutes if shift else 0,
                                settings.absent_after_minutes, settings.punch_window_minutes)
        if standing is None:
            continue
        rows.append(BoardRow(employee, head.department if head is not None else None, shift, span, standing, day, zone))
        counts[standing.state] += 1
        planned += 1 if span is not None else 0
    return Board(rows, dict(counts), planned, moment)


# ---- the team overview and the organisation chart -------------------------------------------------------------------
@dataclass
class OverviewRow:
    """One person's week in numbers: days working, planned off and on leave, the planned minutes and how they stand against the
    standard week."""
    employee: object
    department: object
    working: int
    off: int
    leave: int
    planned_minutes: int
    over_minutes: int      # planned minutes above the standard week (negative: below it)

    @property
    def planned_hours(self):
        return Decimal(self.planned_minutes) / 60

    @property
    def over(self):
        return self.over_minutes > 0


@dataclass
class Overview:
    week: object
    rows: list
    footer: list           # per day: {'working': n, 'off': n, 'leave': n}, over the people shown
    standard_minutes: int

    @property
    def standard_hours(self):
        return Decimal(self.standard_minutes) / 60


def overview(user, week_start, department=None, page=1, per_page=50, query='', realm=None):
    """The week of the viewer's people as numbers: per person the days working, off and on leave and the planned hours against
    the standard week; per day how many work, are off or are away. Everything comes from `week` (the same cells, the same scope),
    so the two pages cannot disagree, and nothing is stored."""
    plan = week(user, week_start, department, page, per_page, query, realm)
    standard = SchedulingSettings.get().standard_week_minutes
    footer = [{'working': 0, 'off': 0, 'leave': 0} for _day in plan.days]
    rows = []
    for row in plan.rows:
        working = off = away = 0
        for index, cell in enumerate(row.cells):
            if not cell.visible:
                continue
            if cell.on_leave:
                away += 1
                footer[index]['leave'] += 1
            elif cell.shift is not None:
                working += 1
                footer[index]['working'] += 1
            elif cell.is_off:
                off += 1
                footer[index]['off'] += 1
        rows.append(OverviewRow(row.employee, row.department, working, off, away, row.planned_minutes,
                                row.planned_minutes - standard))
    return Overview(plan, rows, footer, standard)


PRODUCTION_ROOT = 'production_root'


@dataclass
class Node:
    """One box of the organisation chart: the company, a site, a department, or Company's one Production box (computed
    here, never a row, so there is nothing to delete). `direct` are the people placed in it, `total` those in it and below
    it, as far as the viewer may count them."""
    kind: str                  # company, site, production, office, production_root
    label: str
    obj: object = None
    manager: object = None
    direct: int = 0
    total: int = 0
    children: list = field(default_factory=list)


def org_tree(user, realm):
    """The company as a tree for a person to read, as each panel shows it, counted among the people the viewer may reach.
    Production (Production › Team): the sites with their production departments, each with its manager. Office (Company ›
    HR): the office departments by their parents, then one Production box with the production people the viewer may count,
    there even with no production department. Server-drawn nested lists; no layout algorithm and no script."""
    counts = head_counts(user, realm=realm)
    root = Node('company', '')
    if realm == PRODUCTION:
        sites = {}
        for department in ProductionDepartment.objects.select_related('site', 'manager').order_by('name'):
            sites.setdefault(department.site, []).append(department)
        for site in sorted(sites, key=lambda item: (item is None, item.name if item else '')):
            node = Node('site', site.name if site else '', site)
            for department in sites[site]:
                direct = counts.get((PRODUCTION, department.pk), 0)
                node.children.append(Node(PRODUCTION, department.name, department, department.manager, direct, direct))
            node.total = sum(child.total for child in node.children)
            root.children.append(node)
    else:
        offices = list(OfficeDepartment.objects.select_related('site', 'manager').order_by('name'))
        by_parent = defaultdict(list)
        for department in offices:
            by_parent[department.parent_id].append(department)

        def build(department):
            direct = counts.get((OFFICE, department.pk), 0)
            node = Node(OFFICE, department.name, department, department.manager, direct, direct)
            node.children = [build(child) for child in by_parent.get(department.pk, [])]
            node.total = direct + sum(child.total for child in node.children)
            return node

        root.children = [build(department) for department in by_parent.get(None, [])]
        production = sum(head_counts(user, realm=PRODUCTION).values())
        root.children.append(Node(PRODUCTION_ROOT, _('Production'), direct=production, total=production))
    root.total = sum(child.total for child in root.children)
    return root


# ---- deciding leave ------------------------------------------------------------------------------------------------
def leave_impact(user, leave_request):
    """[(day, shift)]: the shifts the person is planned on inside the request's days (as far as the viewer reaches them), for
    the decider to replace. Information only: an approval is never blocked by it (the rules refuse a shift on approved leave
    when the plan is saved, hr.rules)."""
    plans = ShiftAssignment.objects.filter(employee=leave_request.employee, shift__isnull=False,
                                           day__range=(leave_request.first_day, leave_request.last_day))
    return [(row.day, row.shift) for row in scope.by_day(user, plans, 'employee', 'day').select_related('shift')
            .order_by('day')]


LEAVE_DECIDER = 'hr.change_leaverequest'


def pending_leave_badge(user):
    """The number beside Production › Team › Leave requests: the pending requests of production people the viewer may decide
    (Edit on leave, in their reach on the request's first day, never their own: hr.services.can_decide). Not polled."""
    if not user.has_perm(LEAVE_DECIDER):
        return Badge(0, '')
    waiting = scope.by_day(user, LeaveRequest.objects.filter(status=LeaveStatus.PENDING), 'employee', 'first_day',
                           PRODUCTION).exclude(employee__user=user)
    return Badge(waiting.count(), '')

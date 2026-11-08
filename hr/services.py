"""What changes people's records in HR, each function one transaction with its audit row. A service takes the person
who acts, checks the verb and their scope itself (a page that already did is not trusted), and refuses with a
ValidationError (a sentence for the person) or PermissionDenied; a refusal leaves no row and no log entry."""
from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext as _

from core import audit
from core.models import AuditLog
from farm.models.site import zone_of
from farm.stock.dates import site_today

from . import clock, leave, read, rules, scope, units
from .models import (AttendanceRecord, Employee, Holiday, LeaveRequest, Posting, SchedulingSettings,
                     ShiftAssignment)
from .models.leave import LeaveStatus

POSTING_FIELDS = ['production_department', 'office_department', 'title', 'valid_from', 'valid_until']


def _allowed(user, employee, perms=('hr.change_employee', 'hr.add_employee')):
    """The verb (Edit, or Create for the placement a new person starts with) and the person in the user's team."""
    if not any(user.has_perm(perm) for perm in perms) or not scope.can_reach(user, employee):
        raise PermissionDenied


def _values(posting):
    with audit.source_language():
        return audit.snapshot(posting, POSTING_FIELDS)


def _log_new(user, posting):
    audit.record_create(user, posting, _values(posting), entity_type=audit.entity_type_of(Posting))


def _log_change(user, posting, before):
    audit.record_update(user, posting, before, _values(posting), entity_type=audit.entity_type_of(Posting))


def _save(user, posting):
    posting.updated_by = user
    posting.version += 1
    posting.save()


def move(user, employee, department, title, from_day):
    """Places `employee` in `department` with `title` from `from_day`. The open placement ends the day before; a
    first placement just starts. The same department and title is no change; a change dated the first day of the
    current placement corrects it in place (logged). Refuses a day before the current placement began, one before the
    person joined, and one after they left."""
    _allowed(user, employee)
    with transaction.atomic():
        employee = Employee.objects.select_for_update().get(pk=employee.pk)
        field = units.field_of(department)
        if from_day < employee.joined_on:
            raise ValidationError(_('A person cannot be placed before they joined.'))
        if employee.left_on is not None and from_day > employee.left_on:
            raise ValidationError(_('A person who has left cannot be placed after their last day.'))
        current = Posting.objects.filter(employee=employee).order_by('-valid_from').first()
        if current is not None and current.valid_until is not None and current.valid_until >= from_day:
            raise ValidationError(_('The new placement must start after the last one ended (%(day)s).')
                                  % {'day': current.valid_until})
        if current is not None and current.valid_until is None:
            if current.department == department and current.title == title:
                return current
            if from_day < current.valid_from:
                raise ValidationError(_('The change cannot start before the current placement did (%(day)s).')
                                      % {'day': current.valid_from})
            before = _values(current)
            if from_day == current.valid_from:
                current.production_department = department if field == 'production_department' else None
                current.office_department = department if field == 'office_department' else None
                current.title = title
                _save(user, current)
                _log_change(user, current, before)
                return current
            current.valid_until = from_day - timedelta(days=1)
            _save(user, current)
            _log_change(user, current, before)
        posting = Posting(employee=employee, title=title, valid_from=from_day, created_by=user, updated_by=user,
                          **{field: department})
        posting.save()
        _log_new(user, posting)
        return posting


def leave_company(user, employee, on):
    """Closes the person's record on `on`, their last day: `left_on`, and every placement ends with it (a later one
    is deleted, one that runs past it is cut). The account stays; deactivating it is the platform admin's choice."""
    _allowed(user, employee)
    with transaction.atomic():
        employee = Employee.objects.select_for_update().get(pk=employee.pk)
        if on < employee.joined_on:
            raise ValidationError(_('A person cannot leave before they joined.'))
        with audit.source_language():
            before = audit.snapshot(employee, ['left_on'])
        employee.left_on = on
        employee.updated_by = user
        employee.version += 1
        employee.save()
        with audit.source_language():
            audit.record_update(user, employee, before, audit.snapshot(employee, ['left_on']),
                                entity_type=audit.entity_type_of(Employee))
        align_placements(user, employee)
        return employee


def align_placements(user, employee):
    """Makes the placements agree with the person's last day: those that start after it are deleted, the one that runs
    past it ends on it. Nothing is done for a person who has not left."""
    if employee.left_on is None:
        return
    with transaction.atomic():
        for posting in Posting.objects.filter(employee=employee).order_by('valid_from'):
            before = _values(posting)
            if posting.valid_from > employee.left_on:
                posting.soft_delete(user)
                audit.record(user, AuditLog.Action.DELETE, posting, entity_type=audit.entity_type_of(Posting))
            elif posting.valid_until is None or posting.valid_until > employee.left_on:
                posting.valid_until = employee.left_on
                _save(user, posting)
                _log_change(user, posting, before)
        for plan in ShiftAssignment.objects.filter(employee=employee, day__gt=employee.left_on):
            plan.soft_delete(user)
            audit.record(user, AuditLog.Action.DELETE, plan, entity_type=audit.entity_type_of(ShiftAssignment))
        for pending in LeaveRequest.objects.filter(employee=employee, status=LeaveStatus.PENDING,
                                                   first_day__gt=employee.left_on):
            before = _leave_values(pending)
            pending.status = LeaveStatus.CANCELLED
            pending.updated_by, pending.version = user, pending.version + 1
            pending.save()
            audit.record_update(user, pending, before, _leave_values(pending),
                                entity_type=audit.entity_type_of(LeaveRequest))


# ---- the roster -------------------------------------------------------------------------------------------------
CLEAR = object()          # a cell cleared: the plan for that day is removed (a soft delete, logged)
MARGIN = 15               # days either side of a change read for the rest across a border and a run of days

def holiday_days(first, last, site):
    """The days between `first` and `last` that are holidays for `site` (None: only those of every site)."""
    return leave.holidays_for(first, last, site)




def evaluate(employee, changes):
    """The findings of the rules for `employee` if `changes` ({day: Shift, None (off) or CLEAR}) were applied to the
    plan: for the weeks the changed days fall in, with the neighbouring days read for the rest across a border. Nothing is
    written."""
    settings = SchedulingSettings.get()
    first, last = min(changes) - timedelta(days=MARGIN), max(changes) + timedelta(days=MARGIN)
    plan = {row.day: row.shift for row in ShiftAssignment.objects.filter(
        employee=employee, day__range=(first, last)).select_related('shift')}
    for day, shift in changes.items():
        if shift is CLEAR:
            plan.pop(day, None)
        else:
            plan[day] = shift
    site = read.site_on(employee, min(changes))
    zone = zone_of(site)
    planned = []
    for day, shift in sorted(plan.items()):
        if shift is not None:
            start, end = clock.span(day, shift, zone)
            planned.append(rules.Planned(day, start, end, clock.net_minutes(start, end, shift.break_minutes)))
    holidays = holiday_days(first, last, site)
    away = leave.approved_days([employee.pk], first, last).get(employee.pk, set())
    weeks = {rules.monday(day) for day in changes}
    return rules.findings(planned, away, holidays, settings, weeks, only=set(changes))


def _cell_permission(existing, shift):
    if shift is CLEAR:
        return 'hr.delete_shiftassignment'
    return 'hr.change_shiftassignment' if existing is not None else 'hr.add_shiftassignment'


def plan_shifts(user, cells, shift):
    """Sets `shift` (a Shift, None for planned off, or CLEAR) on every cell, (employee, day), or on none: the cells
    are checked first (the verb each needs, the person in the user's team on that day) and the rules run for each
    person; a blocking finding refuses the whole batch and names the first conflicting cells. Returns the warnings as
    [(employee, Finding)], which are also written into the audit rows."""
    by_person = {}
    for employee, day in cells:
        by_person.setdefault(employee.pk, (employee, {}))[1][day] = shift
    with transaction.atomic():
        warnings, blocking, writes = [], [], []
        list(Employee.objects.select_for_update().filter(pk__in=list(by_person)).order_by('pk').values_list('pk', flat=True))
        for employee, changes in by_person.values():
            if self_plan(user, employee):
                raise PermissionDenied
            existing = {row.day: row for row in ShiftAssignment.objects.select_for_update().filter(
                employee=employee, day__in=list(changes))}
            for day in changes:
                if not scope.can_reach(user, employee, day) or not user.has_perm(
                        _cell_permission(existing.get(day), shift)):
                    raise PermissionDenied
            if shift is CLEAR:
                # Clearing a selection clears its filled cells: an empty one has nothing to clear (F-024).
                changes = {day: value for day, value in changes.items() if day in existing}
                if not changes:
                    continue
            found = evaluate(employee, changes)
            blocking += [(employee, item) for item in found if item.blocks]
            warnings += [(employee, item) for item in found if not item.blocks]
            writes.append((employee, changes, existing))
        if blocking:
            raise ValidationError([
                _('%(person)s, %(day)s: %(what)s') % {'person': employee, 'day': item.day, 'what': rules.text(item)}
                for employee, item in blocking[:5]])
        codes = {}
        for employee, item in warnings:
            codes.setdefault(employee.pk, set()).add(item.code)
        for employee, changes, existing in writes:
            for day in changes:
                _write_cell(user, employee, day, shift, existing.get(day), codes.get(employee.pk, ()))
    return warnings


def _write_cell(user, employee, day, shift, row, warning_codes):
    """Writes one cell and its audit row (English at rest, like every row), with the warnings the plan went on past."""
    entity_type = audit.entity_type_of(ShiftAssignment)
    with audit.source_language():
        before = audit.snapshot(row, ['shift']) if row is not None else {}
        if shift is CLEAR:
            audit.record(user, AuditLog.Action.DELETE, row, before and {key: [value, None] for key, value in before.items()
                                                                       if value is not None}, entity_type=entity_type)
            row.soft_delete(user)
            return
        if row is None:
            row = ShiftAssignment(employee=employee, day=day, shift=shift, created_by=user, updated_by=user)
            row.save()
            audit.record_create(user, row, {**audit.snapshot(row, ['shift']), **_warnings_entry(warning_codes)},
                                entity_type=entity_type)
            return
        row.shift, row.updated_by, row.version = shift, user, row.version + 1
        row.save()
        changed = audit.diff(before, audit.snapshot(row, ['shift']))
        if changed:
            audit.record(user, AuditLog.Action.UPDATE, row, {**changed, **_warnings_entry(warning_codes)},
                         entity_type=entity_type)


def _warnings_entry(codes):
    """The warnings a plan was saved with, by their sentences (msgids, shown translated)."""
    return {'Warnings': [audit.message(rules.TEXT[code]) for code in sorted(codes)]} if codes else {}


# ---- leave --------------------------------------------------------------------------------------------------------
LEAVE_FIELDS = ['status', 'decision_note', 'decided_by']
PRIVATE_LEAVE = ['decision_note']


def _leave_values(request):
    with audit.source_language():
        return audit.snapshot(request, LEAVE_FIELDS, private=PRIVATE_LEAVE)


def self_plan(user, employee):
    """Whether `user` would be recording or planning their own row without holding Everyone: a lead does not write their own
    attendance or plan (a leave request has the same rule, by the service and by a trigger)."""
    return employee.user_id is not None and employee.user_id == user.pk and not user.has_perm(scope.ALL)


def _own(user, leave_request):
    return leave_request.employee.user_id is not None and leave_request.employee.user_id == user.pk


def can_decide(user, leave_request):
    """Whether `user` may approve or reject the request: Edit on Leave requests, the person in their team, and not their own
    request (one rule; a database trigger holds the last part whatever writes). One approval step."""
    return (leave_request.status == LeaveStatus.PENDING and user.has_perm('hr.change_leaverequest')
            and not _own(user, leave_request) and scope.can_reach(user, leave_request.employee, leave_request.first_day))


def can_cancel(user, leave_request, today=None, listed=False):
    """Whether `user` may cancel the request: the person, or a decider; a pending request any time, an approved one only
    while its first day has not started on the site's clock. `listed`: the request came from the viewer's own team already
    (a list), so the team is not asked again."""
    if leave_request.status == LeaveStatus.APPROVED:
        today = today or site_today(read.site_on(leave_request.employee, leave_request.first_day))
        if leave_request.first_day <= today:
            return False
    elif leave_request.status != LeaveStatus.PENDING:
        return False
    if _own(user, leave_request):
        return True
    if not user.has_perm('hr.change_leaverequest'):
        return False
    return listed or scope.can_reach(user, leave_request.employee, leave_request.first_day)


def _lock(leave_request):
    return LeaveRequest.objects.select_for_update(of=('self',)).select_related('employee__user', 'leave_type').get(
        pk=leave_request.pk)


def decide_leave(user, leave_request, approve, note=''):
    """Approves or rejects a pending request, with the decider and the time. Refused (nothing changes, nothing is logged)
    for someone who may not decide it, for the person's own request, and for one that is no longer pending."""
    note = (note or '').strip()
    if len(note) > LeaveRequest._meta.get_field('decision_note').max_length:
        raise ValidationError(_('The note is too long.'))
    with transaction.atomic():
        current = _lock(leave_request)
        if not can_decide(user, current):
            raise PermissionDenied
        before = _leave_values(current)
        current.status = LeaveStatus.APPROVED if approve else LeaveStatus.REJECTED
        current.decided_by, current.decided_at = user, timezone.now()
        current.decision_note = note
        current.updated_by, current.version = user, current.version + 1
        current.save()
        audit.record_update(user, current, before, _leave_values(current),
                            entity_type=audit.entity_type_of(LeaveRequest))
        return current


def cancel_leave(user, leave_request):
    """Cancels a request (the person's, or a decider's): the days are free again for another request."""
    with transaction.atomic():
        current = _lock(leave_request)
        if not can_cancel(user, current):
            raise PermissionDenied
        before = _leave_values(current)
        current.status = LeaveStatus.CANCELLED
        current.updated_by, current.version = user, current.version + 1
        current.save()
        audit.record_update(user, current, before, _leave_values(current),
                            entity_type=audit.entity_type_of(LeaveRequest))
        return current


# ---- attendance ---------------------------------------------------------------------------------------------------
PUNCH_FIELDS = ['employee', 'clock_in', 'clock_out', 'via', 'note']
PRIVATE_PUNCH = ['note']


def own_employee(user):
    """The employee row of the person's account, or None (a login with no employee: an administrator)."""
    return Employee.objects.filter(user=user).first()


def _punch_values(record):
    with audit.source_language():
        return audit.snapshot(record, PUNCH_FIELDS, private=PRIVATE_PUNCH)


def _save_punch(user, record, created, before=None):
    try:
        with transaction.atomic():
            record.save()
    except IntegrityError as error:
        if getattr(getattr(error.__cause__, 'diag', None), 'constraint_name', '') == 'excl_attendance_employee_span':
            raise ValidationError(_('This person is already clocked in for some of this time.')) from error
        raise
    if created:
        audit.record_create(user, record, _punch_values(record), entity_type=audit.entity_type_of(AttendanceRecord))
    else:
        audit.record_update(user, record, before, _punch_values(record), entity_type=audit.entity_type_of(AttendanceRecord))


def clock_in(user):
    """The person clocks in at the server's time (never the browser's). Needs Read on Attendance and an employee row of
    one's own; refused while a punch is open (the database refuses a second open one as well)."""
    if not user.has_perm('hr.view_attendancerecord'):
        raise PermissionDenied
    with transaction.atomic():
        employee = own_employee(user)
        if employee is None:
            raise PermissionDenied
        employee = Employee.objects.select_for_update().get(pk=employee.pk)
        if AttendanceRecord.objects.filter(employee=employee, clock_out__isnull=True).exists():
            raise ValidationError(_('You are already clocked in.'))
        record = AttendanceRecord(employee=employee, clock_in=timezone.now(), via=AttendanceRecord.Via.SELF,
                                  created_by=user, updated_by=user)
        _save_punch(user, record, True)
        return record


def clock_out(user):
    """The person clocks out of their open punch at the server's time."""
    if not user.has_perm('hr.view_attendancerecord'):
        raise PermissionDenied
    with transaction.atomic():
        employee = own_employee(user)
        if employee is None:
            raise PermissionDenied
        employee = Employee.objects.select_for_update().get(pk=employee.pk)
        record = AttendanceRecord.objects.filter(employee=employee, clock_out__isnull=True).first()
        if record is None:
            raise ValidationError(_('You are not clocked in.'))
        before = _punch_values(record)
        record.clock_out = max(timezone.now(), record.clock_in + timedelta(seconds=1))
        record.updated_by, record.version = user, record.version + 1
        _save_punch(user, record, False, before)
        return record


def enter_presence(user, employee, clock_in_at, clock_out_at, note):
    """A lead records presence for a person of their team: times already on the site's clock as instants, and a reason
    (required: the CHECK on the table says so too). Needs Create on Attendance and the person in the user's team."""
    if not user.has_perm('hr.add_attendancerecord') or not scope.can_reach(
            user, employee, read.local_day(employee, clock_in_at)[0]) or self_plan(user, employee):
        raise PermissionDenied
    note = (note or '').strip()
    if not note:
        raise ValidationError(_('Say why the time was entered by hand.'))
    if clock_out_at is not None and clock_out_at <= clock_in_at:
        raise ValidationError(_('The person cannot clock out before they clocked in.'))
    with transaction.atomic():
        employee = Employee.objects.select_for_update().get(pk=employee.pk)
        record = AttendanceRecord(employee=employee, clock_in=clock_in_at, clock_out=clock_out_at,
                                  via=AttendanceRecord.Via.ENTERED, note=note, created_by=user, updated_by=user)
        _save_punch(user, record, True)
        return record

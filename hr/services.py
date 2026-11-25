"""What changes people's records in HR, each function one transaction with its audit row. A service takes the person
who acts, checks the verb and their scope itself (a page that already did is not trusted), and refuses with a
ValidationError (a sentence for the person) or PermissionDenied; a refusal leaves no row and no log entry."""
from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.translation import gettext as _

from core import audit
from core.models import AuditLog
from farm.models.site import zone_of
from farm.stock.dates import site_today

from . import clock, leave, read, rules, scope, units
from .models import (AttendanceRecord, Employee, LeaveRequest, Posting, SchedulingSettings,
                     ShiftAssignment)
from .models.leave import LeaveStatus

POSTING_FIELDS = ['production_department', 'office_department', 'title', 'valid_from', 'valid_until']


EMPLOYEE_VERBS = ('hr.change_employee', 'hr.add_employee')


def _verb(user, perms):
    """Who holds none of `perms` is refused before anything else is read (the data-layering audit, L-6)."""
    if user is None or not user.is_active or not any(user.has_perm(perm) for perm in perms):
        raise PermissionDenied


def _allowed(user, employee, perms=EMPLOYEE_VERBS):
    """The verb (Edit, or Create for the placement a new person starts with), the person in the user's team, and not the
    user's own record unless they hold Everyone (`own_record`)."""
    _verb(user, perms)
    if not scope.can_reach(user, employee) or own_record(user, employee):
        raise PermissionDenied


def check_employed(employee, first, last=None):
    """Refuses a record of `employee` on a day between `first` and `last` (one day by default) outside their employment:
    before they joined or after their last day. The one rule for plans, presence, punches and leave, whoever writes."""
    last = last or first
    if first < employee.joined_on:
        raise ValidationError(_('%(person)s joined on %(day)s.') % {'person': employee.full_name,
                                                                     'day': date_format(employee.joined_on)})
    if employee.left_on is not None and last > employee.left_on:
        raise ValidationError(_('%(person)s left on %(day)s.') % {'person': employee.full_name,
                                                                   'day': date_format(employee.left_on)})


# HR's lock order: the person first, then the person's records (a plan, a punch, a leave request). The person is locked
# FOR NO KEY UPDATE, which a record being added for them (holding a key-share lock on the person) does not wait for.
def lock_person(employee_id):
    """Locks the person's row (HR's lock order: before any record of theirs) and returns it as it is now."""
    return Employee.objects.select_for_update(no_key=True).get(pk=employee_id)


def lock_employed(employee, first, last=None):
    """`check_employed` on the person's row locked first: a last day being set at the same moment waits, or this does, so
    a record is never written past a last day committed meanwhile. Returns the locked row."""
    employee = lock_person(employee.pk)
    check_employed(employee, first, last)
    return employee


class PersonFirst:
    """For a tab of a person's records: an edit locks the person before the record (`Resource.edited`, HR's lock order)."""

    @classmethod
    def edited(cls, request, record, write, seen):
        lock_person(record.employee_id)
        return write()


def punch_day(employee, moment):
    """The day of a punch on its site's clock (hr.read.local_day): the day the employment rule reads."""
    return read.local_day(employee, moment)[0]


def employment_conflicts(employee, joined_on, left_on):
    """The records of `employee` that would lie outside the employment from `joined_on` to `left_on` (None: still here),
    as sentences: live plans before the first day (those after a last day are removed with it, `align_placements`),
    pending or approved leave before it, approved leave or pending leave begun before a last day that runs past it
    (pending leave that starts after it is cancelled with it), and punches outside it on their site's clock."""
    found = []
    plans = ShiftAssignment.objects.filter(employee=employee, day__lt=joined_on)
    if plans.exists():
        found.append(_('planned shifts before %(day)s') % {'day': date_format(joined_on)})
    held = LeaveRequest.objects.filter(employee=employee, status__in=[LeaveStatus.PENDING, LeaveStatus.APPROVED])
    late = held.filter(last_day__gt=left_on).exclude(status=LeaveStatus.PENDING, first_day__gt=left_on)         if left_on is not None else held.none()
    if held.filter(first_day__lt=joined_on).exists() or late.exists():
        found.append(_('leave outside these days'))
    punches = AttendanceRecord.objects.filter(employee=employee)
    if any(punch_day(employee, record.clock_in) < joined_on
           or (left_on is not None and punch_day(employee, record.clock_in) > left_on) for record in punches):
        found.append(_('attendance outside these days'))
    if found:
        return ValidationError(_('%(person)s has %(records)s: correct them first.')
                               % {'person': employee.full_name, 'records': ', '.join(found)})
    return None


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
    person joined, and one after they left. The department must be one the user manages (`scope.can_manage`): a lead does
    not hand a person to another manager or into the office."""
    _allowed(user, employee)
    if not scope.can_manage(user, department):
        raise PermissionDenied
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
        conflict = employment_conflicts(employee, employee.joined_on, on)
        if conflict is not None:
            raise conflict
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
    past it ends on it. Nothing is done for a person who has not left. For who may create or edit people (the employee
    tab's save and `leave_company` call it after their own check)."""
    _verb(user, EMPLOYEE_VERBS)
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


# The rights that write a cell of the schedule: setting a new one, changing one, clearing one.
PLAN_PERMISSIONS = ('hr.add_shiftassignment', 'hr.change_shiftassignment', 'hr.delete_shiftassignment')


def can_plan(user):
    """Whether `user` may write any cell of the schedule; which cells is decided per cell (`_cell_permission`)."""
    return any(user.has_perm(permission) for permission in PLAN_PERMISSIONS)


def _cell_permission(existing, shift):
    if shift is CLEAR:
        return 'hr.delete_shiftassignment'
    return 'hr.change_shiftassignment' if existing is not None else 'hr.add_shiftassignment'


def plan_shifts(user, cells, shift):
    """Sets `shift` (a Shift, None for planned off, or CLEAR) on every cell, (employee, day), or on none: the cells
    are checked first (the verb each needs, the person in the user's team on that day) and the rules run for each
    person; a blocking finding refuses the whole batch and names the first conflicting cells. Returns the warnings as
    [(employee, Finding)], which are also written into the audit rows."""
    _verb(user, PLAN_PERMISSIONS)              # who may plan no cell at all is refused before the cells are read
    by_person = {}
    for employee, day in cells:
        by_person.setdefault(employee.pk, (employee, {}))[1][day] = shift
    with transaction.atomic():
        warnings, blocking, writes = [], [], []
        list(Employee.objects.select_for_update().filter(pk__in=list(by_person)).order_by('pk').values_list('pk', flat=True))
        for employee, changes in by_person.values():
            if own_record(user, employee):
                raise PermissionDenied
            existing = {row.day: row for row in ShiftAssignment.objects.select_for_update().filter(
                employee=employee, day__in=list(changes))}
            for day in changes:
                if not scope.can_reach(user, employee, day) or not user.has_perm(
                        _cell_permission(existing.get(day), shift)):
                    raise PermissionDenied
                if shift is not CLEAR:
                    check_employed(employee, day)
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
LEAVE_FIELDS = ['status', 'last_day', 'decision_note', 'decided_by']     # last_day: a started leave shortened
PRIVATE_LEAVE = ['decision_note']


def _leave_values(request):
    with audit.source_language():
        return audit.snapshot(request, LEAVE_FIELDS, private=PRIVATE_LEAVE)


def own_record(user, employee):
    """Whether `user` would be writing their own record without holding Everyone: a lead does not write their own
    attendance, plan, placement, title or last day (a leave request has the same rule, by the service and by a trigger)."""
    return employee.user_id is not None and employee.user_id == user.pk and not user.has_perm(scope.ALL)


def _own(user, leave_request):
    return leave_request.employee.user_id is not None and leave_request.employee.user_id == user.pk


def _decider(user, leave_request, listed=False):
    """Edit on Leave requests, the person in the user's team (not asked again for a request `listed` from it), and not the
    user's own request (one rule; a database trigger holds the last part whatever writes)."""
    return (user.has_perm('hr.change_leaverequest') and not _own(user, leave_request)
            and (listed or scope.can_reach(user, leave_request.employee, leave_request.first_day)))


def can_decide(user, leave_request):
    """Whether `user` may approve or reject the request: a pending one, by a decider. One approval step."""
    return leave_request.status == LeaveStatus.PENDING and _decider(user, leave_request)


def correction_window_days():
    """How many days after a record's last day it may still be corrected: the platform owner's correction window, a
    setting of the platform (31 days by default). Read here, in one place, so a leave correction follows the setting."""
    return 31


def _leave_today(leave_request):
    return site_today(read.site_on(leave_request.employee, leave_request.first_day))


def past_correction(leave_request, today=None):
    """The refusal of a correction to a leave whose last day lies more than the window behind today, or None."""
    today = today or _leave_today(leave_request)
    window = correction_window_days()
    if (today - leave_request.last_day).days > window:
        return ValidationError(_('This leave ended on %(day)s, more than %(days)s days ago: it can no longer be '
                                 'corrected.') % {'day': date_format(leave_request.last_day), 'days': window})
    return None


def can_correct(user, leave_request, listed=False, today=None):
    """Whether `user` may shorten or cancel an approved request that has begun: a decider only, never the person (the
    days are history now; a lead or HR puts them right when the person came back early or never went), and only within
    the correction window after its last day."""
    return (leave_request.status == LeaveStatus.APPROVED and _decider(user, leave_request, listed)
            and past_correction(leave_request, today) is None)


def _refuse_correction(user, current):
    """A decider correcting a leave past the window is told why; anyone else is refused."""
    if current.status == LeaveStatus.APPROVED and _decider(user, current):
        refusal = past_correction(current)
        if refusal is not None:
            raise refusal
    raise PermissionDenied


def can_cancel(user, leave_request, today=None, listed=False):
    """Whether `user` may cancel the request: the person, or a decider; a pending request any time, an approved one only
    while its first day has not started on the site's clock. `listed`: the request came from the viewer's own team already
    (a list), so the team is not asked again."""
    if leave_request.status == LeaveStatus.APPROVED:
        today = today or _leave_today(leave_request)
        if leave_request.first_day <= today:
            return can_correct(user, leave_request, listed, today)
    elif leave_request.status != LeaveStatus.PENDING:
        return False
    if _own(user, leave_request):
        return True
    if not user.has_perm('hr.change_leaverequest'):
        return False
    return listed or scope.can_reach(user, leave_request.employee, leave_request.first_day)


def _lock(leave_request):
    """The request locked, after its person (HR's lock order)."""
    lock_person(leave_request.employee_id)
    return LeaveRequest.objects.select_for_update(of=('self',)).select_related('employee__user', 'leave_type').get(
        pk=leave_request.pk)


def decide_leave(user, leave_request, approve, note=''):
    """Approves or rejects a pending request, with the decider and the time. Refused (nothing changes, nothing is logged)
    for someone who may not decide it, for the person's own request, and for one that is no longer pending."""
    _verb(user, ('hr.change_leaverequest',))   # only a decider holds it (_decider); the request is read after
    note = (note or '').strip()
    if len(note) > LeaveRequest._meta.get_field('decision_note').max_length:
        raise ValidationError(_('The note is too long.'))
    with transaction.atomic():
        current = _lock(leave_request)
        if not can_decide(user, current):
            raise PermissionDenied
        if approve:
            lock_employed(current.employee, current.first_day, current.last_day)
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
            _refuse_correction(user, current)
        before = _leave_values(current)
        current.status = LeaveStatus.CANCELLED
        current.updated_by, current.version = user, current.version + 1
        current.save()
        audit.record_update(user, current, before, _leave_values(current),
                            entity_type=audit.entity_type_of(LeaveRequest))
        return current


def shorten_leave(user, leave_request, last_day):
    """Ends an approved request earlier: `last_day` from its first day to the day before its last (the person came back
    early). A decider only, within the correction window (`can_correct`); logged; the days after it are free again."""
    _verb(user, ('hr.change_leaverequest',))   # only a decider corrects (can_correct); the request is read after
    with transaction.atomic():
        current = _lock(leave_request)
        if not can_correct(user, current):
            _refuse_correction(user, current)
        if not current.first_day <= last_day < current.last_day:
            raise ValidationError(_('The new last day must lie between %(first)s and the day before %(last)s.')
                                  % {'first': date_format(current.first_day), 'last': date_format(current.last_day)})
        before = _leave_values(current)
        current.last_day = last_day
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


def open_stretch(employee):
    """The person's open stretch (at most one: the table's exclusion constraint), or None."""
    return AttendanceRecord.objects.filter(employee=employee, clock_out__isnull=True).select_related('employee').first()


def forgotten_refusal(record, now=None):
    """What a person is told when their open clock-in counts as a forgotten clock-out (rules.forgotten, HR's limit), or
    None while it does not. They neither clock in (a second stretch cannot stand beside an open one) nor clock out (the
    stretch would run up to now: hours nobody worked): whoever may correct their attendance closes it on the Attendance
    page with the real time and a reason, and then they clock in again."""
    hours = SchedulingSettings.get().forgotten_after_hours
    if record is None or not rules.forgotten(record.clock_in, record.clock_out, now or timezone.now(), hours):
        return None
    _day, zone = read.local_day(record.employee, record.clock_in)
    return ValidationError(
        _('Your clock-in of %(since)s was never closed: it has been open more than %(hours)s hours and counts as a '
          'forgotten clock-out. Ask your lead, or whoever keeps attendance for you, to close it on the Attendance page '
          'with the time you really left; then you can clock in again.')
        % {'since': date_format(timezone.localtime(record.clock_in, zone), 'DATETIME_FORMAT'), 'hours': hours})


def clock_in(user):
    """The person clocks in at the server's time (never the browser's). Needs Read on Attendance and an employee row of
    one's own; refused while a punch is open (the database refuses a second open one as well), with the way forward when
    that punch is a forgotten clock-out (`forgotten_refusal`)."""
    if not user.has_perm('hr.view_attendancerecord'):
        raise PermissionDenied
    with transaction.atomic():
        employee = own_employee(user)
        if employee is None:
            raise PermissionDenied
        employee = Employee.objects.select_for_update().get(pk=employee.pk)
        still_open = open_stretch(employee)
        if still_open is not None:
            raise forgotten_refusal(still_open) or ValidationError(_('You are already clocked in.'))
        check_employed(employee, punch_day(employee, timezone.now()))
        record = AttendanceRecord(employee=employee, clock_in=timezone.now(), via=AttendanceRecord.Via.SELF,
                                  created_by=user, updated_by=user)
        _save_punch(user, record, True)
        return record


def clock_out(user):
    """The person clocks out of their open punch at the server's time. Not out of a forgotten one (`forgotten_refusal`):
    the time they left is not now."""
    if not user.has_perm('hr.view_attendancerecord'):
        raise PermissionDenied
    with transaction.atomic():
        employee = own_employee(user)
        if employee is None:
            raise PermissionDenied
        employee = Employee.objects.select_for_update().get(pk=employee.pk)
        record = open_stretch(employee)
        if record is None:
            raise ValidationError(_('You are not clocked in.'))
        refusal = forgotten_refusal(record)
        if refusal is not None:
            raise refusal
        before = _punch_values(record)
        record.clock_out = max(timezone.now(), record.clock_in + timedelta(seconds=1))
        record.updated_by, record.version = user, record.version + 1
        _save_punch(user, record, False, before)
        return record


def check_times(clock_in_at, clock_out_at, now=None):
    """The rule of a stretch's two times when a person types them, on the form and in the service: the clock-out after
    the clock-in, and neither later than the server's now. A time typed by hand is a time that has been: a clock-out
    ahead would close a stretch with hours nobody has worked yet, keep the person from clocking in and take them out
    of the emergency count while the record says they are in (review R6). Raises a ValidationError by field."""
    now = now or timezone.now()
    if clock_out_at is not None and clock_out_at <= clock_in_at:
        raise ValidationError({'clock_out': _('The person cannot clock out before they clocked in.')})
    if clock_in_at > now:
        raise ValidationError({'clock_in': _('The clock-in cannot be later than now.')})
    if clock_out_at is not None and clock_out_at > now:
        raise ValidationError({'clock_out': _('The clock-out cannot be later than now: give the time the person really '
                                              'left.')})


def enter_presence(user, employee, clock_in_at, clock_out_at, note):
    """A lead records presence for a person of their team: times already on the site's clock as instants, and a reason
    (required: the CHECK on the table says so too). Needs Create on Attendance and the person in the user's team."""
    if not user.has_perm('hr.add_attendancerecord') or not scope.can_reach(
            user, employee, read.local_day(employee, clock_in_at)[0]) or own_record(user, employee):
        raise PermissionDenied
    note = (note or '').strip()
    if not note:
        raise ValidationError(_('Say why the time was entered by hand.'))
    check_times(clock_in_at, clock_out_at)
    with transaction.atomic():
        employee = lock_employed(employee, punch_day(employee, clock_in_at),
                                 punch_day(employee, clock_out_at) if clock_out_at is not None else None)
        record = AttendanceRecord(employee=employee, clock_in=clock_in_at, clock_out=clock_out_at,
                                  via=AttendanceRecord.Via.ENTERED, note=note, created_by=user, updated_by=user)
        _save_punch(user, record, True)
        return record

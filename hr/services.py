"""What changes people's records in HR, each function one transaction with its audit row. A service takes the person
who acts, checks the verb and their scope itself (a page that already did is not trusted), and refuses with a
ValidationError (a sentence for the person, on the field it is about when there is one) or PermissionDenied; a refusal
leaves no row and no log entry.

These are the only writers of HR's people and their records (the models say `service_written`): the tabs of employees,
attendance, leave requests and the roster hand their saves here (core.crud.Resource.service_writes), the
demonstration's seed calls these functions, and the admin has no restore of such a record, so each rule is written once
and every page, command or later caller runs the same one. Rule S of core/tests_data_access.py reads every production
module for another writer. The person's form, the attendance form, the
leave form and the plan's dialog only read what was typed."""
from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.translation import gettext as _

from core import audit, softdelete
from core.crud import changed_meanwhile
from core.models import AuditLog
from core.platform import correction_window_days, plan_batch_cells
from farm.stock.dates import site_today

from . import leave, read, rules, scope, units
from .models import (AttendanceRecord, Employee, LeaveRequest, LeaveType, Posting, SchedulingSettings,
                     ShiftAssignment)
from .models.leave import LeaveStatus
from .placed import placements

POSTING_FIELDS = ['production_department', 'office_department', 'title', 'valid_from', 'valid_until']
# A person's own columns: what their form writes (`add_employee`, `change_employee`); the last day is `leave_company`'s.
PERSON_FIELDS = ['employee_number', 'user', 'first_name', 'last_name', 'employment_type', 'joined_on']


EMPLOYEE_VERBS = ('hr.change_employee', 'hr.add_employee')
KEEP = object()           # a value left as it is (a reason the editor may not read)


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


def as_confirmed(current, confirmed):
    """The record a delete confirmed (`confirmed`, crud's read at the version the person confirmed) is still the one
    locked now (`current`, read again under the person's lock: None when it is gone), else refused with the sentence
    of a record changed while the person looked at it. The one step of HR's deletes (clear_day, void_presence)."""
    if current is None or current.pk != confirmed.pk or current.version != confirmed.version:
        raise ValidationError(changed_meanwhile(confirmed._meta.verbose_name, deleting=True))


class NotReached(PermissionDenied):
    """A person the user does not reach at all: not theirs to hear about (a 403; the batch plan's page answers it as a
    record that is not there, a 404)."""


def reached(user, cells, refusal):
    """Each (employee, day) of `cells` has its person in the user's team on that day (scope.cells_reached, asked once for
    all of them), else refused: with `refusal`, a sentence or {field: sentence}, when every person missed is the user's
    today (the page offered them, and the day is another lead's), else NotReached. The one refusal of a day, for a cell's
    dialog, the batch plan and leave alike."""
    asked = {(employee.pk, day) for employee, day in cells}
    missed = asked - scope.cells_reached(user, asked)
    if not missed:
        return
    today = site_today(None)
    theirs = scope.cells_reached(user, {(pk, today) for pk, _day in missed})
    if all((pk, today) in theirs for pk, _day in missed):
        raise ValidationError(refusal)
    raise NotReached


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
# One helper, one strength: no service locks a person's row another way (a test reads the code for it).
def lock_person(employee_id):
    """Locks the person's row (HR's lock order: before any record of theirs) and returns it as it is now."""
    return Employee.objects.select_for_update(no_key=True).get(pk=employee_id)


def lock_people(employee_ids):
    """`lock_person` for several people, in primary-key order (two batches take them in the same order)."""
    return list(Employee.objects.select_for_update(no_key=True).filter(pk__in=list(employee_ids)).order_by('pk'))


def lock_employed(employee, first, last=None):
    """`check_employed` on the person's row locked first: a last day being set at the same moment waits, or this does, so
    a record is never written past a last day committed meanwhile. Returns the locked row."""
    employee = lock_person(employee.pk)
    check_employed(employee, first, last)
    return employee


class PersonFirst:
    """For a tab of a person's records: an edit locks the person before the record (`Resource.edited`, HR's lock order),
    before crud locks the record and hands the edit to the service."""

    @classmethod
    def edited(cls, request, record, write, seen):
        lock_person(record.employee_id)
        return write()


def punch_day(employee, moment):
    """The day of a punch on the clock that governs it (hr.read.governing): the day the employment rule reads."""
    return read.governing(employee, moment).day


def employment_conflicts(employee, joined_on, left_on):
    """The records of `employee` that would lie outside the employment from `joined_on` to `left_on` (None: still here),
    as sentences: live plans before the first day (those after a last day are removed with it, `_align_placements`),
    pending or approved leave before it, approved leave or pending leave begun before a last day that runs past it
    (pending leave that starts after it is cancelled with it), and punches outside it on their site's clock."""
    found = []
    plans = ShiftAssignment.objects.filter(employee=employee, day__lt=joined_on)
    if plans.exists():
        found.append(_('planned shifts before %(day)s') % {'day': date_format(joined_on)})
    held = LeaveRequest.objects.filter(employee=employee, status__in=[LeaveStatus.PENDING, LeaveStatus.APPROVED])
    late = held.filter(last_day__gt=left_on).exclude(status=LeaveStatus.PENDING, first_day__gt=left_on) \
        if left_on is not None else held.none()
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


# ---- people and their placements --------------------------------------------------------------------------------------
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


def _person_values(employee, fields=PERSON_FIELDS):
    with audit.source_language():
        return audit.snapshot(employee, fields)


def _check_account(user, account, linked=None):
    """Who links or unlinks a person's account: a holder of Everyone only. Whose account a person is decides who reads
    their private words (a leave reason is the account's own)."""
    if getattr(account, 'pk', None) != getattr(linked, 'pk', None) and not user.has_perm(scope.ALL):
        raise PermissionDenied


def check_bounds(joined_on, left_on):
    """The employment runs from the first day to the last, which may be the same day (the person form asks it first, so
    the field says it; the service again)."""
    if left_on is not None and left_on < joined_on:
        raise ValidationError({'left_on': _('A person cannot leave before they joined.')})


def _named(employee):
    """A person with an account is named by it: their own first and last name stay empty (a database check as well)."""
    if employee.user_id is not None:
        employee.first_name = employee.last_name = ''


def add_employee(user, values, placement=None):
    """A new person from the person form: their own columns (`values`, PERSON_FIELDS and `left_on`), their last day when
    it is known already (`leave_company`) and the placement they start in (`placement`: department, title, first day;
    `move`, which refuses a start after the last day), in one transaction, each logged. Needs Create on Employees; the
    placement and the last day ask the rest (a department the user places in, the person in their team)."""
    _verb(user, ('hr.add_employee',))
    _check_account(user, values.get('user'))
    check_bounds(values['joined_on'], values.get('left_on'))
    with transaction.atomic():
        employee = Employee(created_by=user, updated_by=user, **{name: values[name] for name in PERSON_FIELDS
                                                                  if name in values})
        _named(employee)
        employee.save()
        audit.record_create(user, employee, _person_values(employee), entity_type=audit.entity_type_of(Employee))
        if values.get('left_on') is not None:
            employee = leave_company(user, employee, values['left_on'])
        if placement is not None:
            move(user, employee, *placement)
        _align_placements(user, employee)
        return employee


def change_employee(user, employee, values, placement=None):
    """Saves the person form: the person's own columns (`values`, PERSON_FIELDS and `left_on`), then a new placement
    (`placement`, `move`), one transaction. A first or last day is refused while records of theirs lie outside it
    (`employment_conflicts`); a changed last day is `leave_company`'s, written in the order that keeps the employment's
    days in order at every step."""
    _allowed(user, employee)
    with transaction.atomic():
        current = lock_person(employee.pk)
        _check_account(user, values.get('user', current.user), current.user)
        joined = values.get('joined_on', current.joined_on)
        left = values.get('left_on', current.left_on)
        check_bounds(joined, left)
        if joined != current.joined_on:
            conflict = employment_conflicts(current, joined, left)
            if conflict is not None:
                raise ValidationError({'joined_on': conflict.messages})
        # The new last day first when the old first day allows it (the database keeps the last day after the first at
        # every write), else the new first day first.
        last_first = left != current.left_on and (left is None or left >= current.joined_on)
        if last_first:
            current = leave_company(user, current, left)
        before = _person_values(current)
        for name in PERSON_FIELDS:
            if name in values:
                setattr(current, name, values[name])
        _named(current)
        current.updated_by, current.version = user, current.version + 1
        current.save()
        audit.record_update(user, current, before, _person_values(current), entity_type=audit.entity_type_of(Employee))
        if left != current.left_on:
            current = leave_company(user, current, left)
        if placement is not None:
            move(user, current, *placement)
            _align_placements(user, current)          # a placement that starts on a last day ends on it
        return current


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
        employee = lock_person(employee.pk)
        field = units.field_of(department)
        if from_day < employee.joined_on:
            raise ValidationError({'from_day': _('A person cannot be placed before they joined.')})
        if employee.left_on is not None and from_day > employee.left_on:
            raise ValidationError({'from_day': _('A person who has left cannot be placed after their last day.')})
        current = Posting.objects.filter(employee=employee).order_by('-valid_from').first()
        if current is not None and current.valid_until is not None and current.valid_until >= from_day:
            raise ValidationError({'from_day': _('The new placement must start after the last one ended (%(day)s).')
                                   % {'day': current.valid_until}})
        if current is not None and current.valid_until is None:
            if current.department == department and current.title == title:
                return current
            if from_day < current.valid_from:
                raise ValidationError({'from_day': _('The change cannot start before the current placement did '
                                                     '(%(day)s).') % {'day': current.valid_from}})
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
    """Sets the person's last day, `on` (None: they work here again, with no last day): `left_on`, and every placement ends
    with it (a later one is deleted, one that runs past it is cut), as do the plans after it and the pending leave that
    starts after it. Refused before the first day, and while approved leave or punches lie past it. The one writer of a
    last day, from the person form (`change_employee`) or any other caller. The account stays; deactivating it is the
    platform admin's choice."""
    _allowed(user, employee)
    with transaction.atomic():
        employee = lock_person(employee.pk)
        check_bounds(employee.joined_on, on)
        conflict = employment_conflicts(employee, employee.joined_on, on)
        if conflict is not None:
            raise ValidationError({'left_on': conflict.messages})
        before = _person_values(employee, ['left_on'])
        employee.left_on = on
        employee.updated_by = user
        employee.version += 1
        employee.save()
        audit.record_update(user, employee, before, _person_values(employee, ['left_on']),
                            entity_type=audit.entity_type_of(Employee))
        _align_placements(user, employee)
        return employee


def _align_placements(user, employee):
    """Makes the placements agree with the person's last day: those that start after it are deleted, the one that runs
    past it ends on it; the plans after it are removed and the pending leave that starts after it is cancelled. Nothing
    is done for a person who has not left. A step of `leave_company`, inside its checked call."""
    if employee.left_on is None:
        return
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
PLAN_FIELDS = ['employee', 'day', 'shift', 'note']
PRIVATE_PLAN = ['note']


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
    # each day on the clock, and with the holidays, of the site the person is placed on that day (read.planned_shifts)
    placed = placements([employee.pk], first, last)[employee.pk]
    planned = read.planned_shifts({day: shift for day, shift in plan.items() if shift is not None}, placed)
    holidays = set(leave.holidays_on(leave.holiday_table([first], [last]), placed))
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
    are checked first (the verb each needs, the person in the user's team on that day, never the user's own days) and the
    rules run for each person; a blocking finding refuses the whole batch and names the first conflicting cells. At most
    the platform's number of cells in one call (core.platform.plan_batch_cells). Returns the warnings as
    [(employee, Finding)], which are also written into the audit rows."""
    return _plan(user, cells, shift, most=plan_batch_cells)[1]


def clear_day(user, record):
    """Clears the plan `record` as the person confirmed it (its dialog's Delete: crud has refused a record whose version
    moved since the confirmation, core.crud.DeleteView): that row at that version, read again under the person's lock. A
    cell cleared, replanned or changed meanwhile is left as it is, with the reason."""
    _verb(user, PLAN_PERMISSIONS)              # before the record is read (core/tests_service_rights.py)
    _plan(user, [(record.employee, record.day)], CLEAR, expected=record)


def plan_day(user, employee, day, shift, note, expected=None):
    """One cell from its own dialog: `shift` (a Shift, or None for planned off) and the lead's `note`, by the rules of
    `plan_shifts`. `expected` is the cell as the caller knows it: None from a new plan's dialog (the cell is empty), the
    plan being edited from its own. A live plan there that is not the expected one was saved meanwhile (another lead, a
    batch) and is not overwritten: refused with the table's sentence. Returns (the plan as saved, its warnings
    [Finding])."""
    rows, warnings = _plan(user, [(employee, day)], shift, note, expected)
    return rows[(employee.pk, day)], [finding for _person, finding in warnings]


WHATEVER = object()       # the batch plan sets whatever is in a cell (its documented meaning)
ONE_PLAN = next(constraint for constraint in ShiftAssignment._meta.constraints
                if constraint.name == 'uq_shift_assignments_employee_day')


def _plan(user, cells, shift, note=KEEP, expected=WHATEVER, most=None):
    _verb(user, PLAN_PERMISSIONS)              # who may plan no cell at all is refused before the cells are read
    bound = most() if most is not None else None
    if bound is not None and len(cells) > bound:
        raise ValidationError(_('At most %(most)s days can be planned at once: select fewer and repeat.')
                              % {'most': bound})
    by_person = {}
    for employee, day in cells:
        by_person.setdefault(employee.pk, (employee, {}))[1][day] = shift
    with transaction.atomic():
        warnings, blocking, writes = [], [], []
        lock_people(by_person)
        # the reach of every cell, asked once for all of them (a fixed number of queries)
        reached(user, [(employee, day) for employee, changes in by_person.values() for day in changes],
                _('You do not plan this person on this day.'))
        for employee, changes in by_person.values():
            if own_record(user, employee):
                raise ValidationError(_('You do not plan your own days.'))
            existing = {row.day: row for row in ShiftAssignment.objects.select_for_update().filter(
                employee=employee, day__in=list(changes))}
            for day in changes:
                row = existing.get(day)
                if expected is not WHATEVER and shift is CLEAR:
                    as_confirmed(row, expected)
                elif expected is not WHATEVER and row is not None and row.pk != getattr(expected, 'pk', None):
                    raise ValidationError({'day': ONE_PLAN.violation_error_message})
                if not user.has_perm(_cell_permission(existing.get(day), shift)):
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
            # One cell (its own dialog) is told the rule; several name the person and the day of each.
            raise ValidationError([rules.text(item) for _employee, item in blocking] if len(cells) == 1 else [
                _('%(person)s, %(day)s: %(what)s') % {'person': employee, 'day': item.day, 'what': rules.text(item)}
                for employee, item in blocking[:5]])
        codes = {}
        for employee, item in warnings:
            codes.setdefault(employee.pk, set()).add(item.code)
        rows = {}
        for employee, changes, existing in writes:
            for day in changes:
                rows[(employee.pk, day)] = _write_cell(user, employee, day, shift, existing.get(day),
                                                       codes.get(employee.pk, ()), note)
    return rows, warnings


def _plan_values(row):
    with audit.source_language():
        return audit.snapshot(row, PLAN_FIELDS, private=PRIVATE_PLAN)


def _write_cell(user, employee, day, shift, row, warning_codes, note=KEEP):
    """Writes one cell and its audit row (English at rest, like every row), with the warnings the plan went on past.
    Returns the row."""
    entity_type = audit.entity_type_of(ShiftAssignment)
    before = _plan_values(row) if row is not None else {}
    if shift is CLEAR:
        audit.record(user, AuditLog.Action.DELETE, row, {key: [value, None] for key, value in before.items()
                                                         if value is not None}, entity_type=entity_type)
        row.soft_delete(user)
        return row
    if row is None:
        row = ShiftAssignment(employee=employee, day=day, shift=shift, note='' if note is KEEP else note,
                              created_by=user, updated_by=user)
        row.save()
        audit.record_create(user, row, {**_plan_values(row), **_warnings_entry(warning_codes)}, entity_type=entity_type)
        return row
    row.shift, row.updated_by, row.version = shift, user, row.version + 1
    if note is not KEEP:
        row.note = note
    row.save()
    changed = audit.diff(before, _plan_values(row))
    if changed:
        audit.record(user, AuditLog.Action.UPDATE, row, {**changed, **_warnings_entry(warning_codes)},
                     entity_type=entity_type)
    return row


def _warnings_entry(codes):
    """The warnings a plan was saved with, by their sentences (msgids, shown translated)."""
    with audit.source_language():
        return {'Warnings': [audit.message(rules.TEXT[code]) for code in sorted(codes)]} if codes else {}


# ---- leave --------------------------------------------------------------------------------------------------------
LEAVE_FIELDS = ['employee', 'leave_type', 'first_day', 'last_day', 'reason', 'status', 'decision_note', 'decided_by']
PRIVATE_LEAVE = ['reason', 'decision_note']


def _leave_values(request):
    with audit.source_language():
        return audit.snapshot(request, LEAVE_FIELDS, private=PRIVATE_LEAVE)


def own_record(user, employee):
    """Whether `user` would be writing their own record without holding Everyone: a lead does not write their own
    attendance, plan, placement, title or last day (a leave request has the same rule, by the service and by a trigger)."""
    return employee.user_id is not None and employee.user_id == user.pk and not user.has_perm(scope.ALL)


def _own(user, leave_request):
    return leave_request.employee.user_id is not None and leave_request.employee.user_id == user.pk


def check_days(first_day, last_day):
    """The days of a request in order (the form asks it first, so the field says it; the service again)."""
    if last_day < first_day:
        raise ValidationError({'last_day': _('The last day cannot be before the first.')})


def _check_leave(employee, leave_type, first_day, last_day, exclude=None):
    """What a request for these days must keep, with the person's row locked: the days inside the employment, at least one
    day charged, and the type's yearly allowance (the other requests of the year, `exclude` left out)."""
    check_days(first_day, last_day)
    if leave_type.status != LeaveType.Status.ACTIVE:
        raise ValidationError({'leave_type': _('This leave type is no longer offered.')})
    check_employed(employee, first_day, last_day)
    # each day by the holidays of the site the person is placed on that day (hr.leave.holidays_on)
    charged = leave.charged_by_year(first_day, last_day, placements([employee.pk], first_day, last_day)[employee.pk])
    if not charged:
        raise ValidationError({'last_day': _('These days are all weekends or holidays: nothing would be charged.')})
    if leave_type.annual_days is not None:
        for year, days in charged.items():
            used = leave.used(employee, leave_type, year, exclude=exclude)
            if used + days > leave_type.annual_days:
                raise ValidationError({'leave_type': _('This is %(days)s days of %(kind)s in %(year)s and %(left)s are '
                                                       'left.') % {'days': days, 'kind': leave_type.name, 'year': year,
                                                                   'left': leave_type.annual_days - used}})


def file_leave(user, employee, leave_type, first_day, last_day, reason=''):
    """Files a request for leave: for oneself, or by a lead for a person of their team. It is pending, or granted at once
    for a type that needs no approval (no decider: `decided_at` only). The reason is the person's own words: what anyone
    else types for them is dropped. Needs Create on Leave requests and the person in the user's team on the request's
    first day, the day it is listed and decided by (themselves always)."""
    _verb(user, ('hr.add_leaverequest',))
    reached(user, [(employee, first_day)], {'first_day': _('You do not see this person on this day.')})
    with transaction.atomic():
        employee = lock_employed(employee, first_day, last_day)
        _check_leave(employee, leave_type, first_day, last_day)
        request = LeaveRequest(employee=employee, leave_type=leave_type, first_day=first_day, last_day=last_day,
                               reason=reason if employee.user_id == user.pk else '', created_by=user, updated_by=user)
        if not leave_type.needs_approval:
            request.status, request.decided_at = LeaveStatus.APPROVED, timezone.now()
        request.save()
        audit.record_create(user, request, _leave_values(request), entity_type=audit.entity_type_of(LeaveRequest))
        return request


def change_leave(user, leave_request, leave_type, first_day, last_day, reason=KEEP):
    """Changes a pending request: its type, its days and, for who may read it (scope.sees_reason), its reason. Needs Edit
    on Leave requests and the person in the user's team on its first day, as it is and as it would be (a request is not
    moved onto another lead's list); a decided request is not changed (a started one is corrected: `shorten_leave`,
    `cancel_leave`)."""
    _verb(user, (scope.LEAVE_DECIDER,))
    with transaction.atomic():
        current = _lock(leave_request)
        if not scope.can_reach(user, current.employee, current.first_day):
            raise PermissionDenied
        reached(user, [(current.employee, first_day)], {'first_day': _('You do not see this person on this day.')})
        if reason is not KEEP and not scope.sees_reason(user, current.employee):
            raise PermissionDenied
        if current.status != LeaveStatus.PENDING:
            raise ValidationError(_('Only a pending request can be changed.'))
        _check_leave(current.employee, leave_type, first_day, last_day, exclude=current)
        before = _leave_values(current)
        current.leave_type, current.first_day, current.last_day = leave_type, first_day, last_day
        if reason is not KEEP:
            current.reason = reason
        current.updated_by, current.version = user, current.version + 1
        current.save()
        audit.record_update(user, current, before, _leave_values(current), entity_type=audit.entity_type_of(LeaveRequest))
        return current


def deciders_of(user, leave_requests):
    """The ids of those among `leave_requests` that `user` decides (scope.deciding), in one query: what a list hands back
    to the questions below as `decider`, for the same user."""
    return set(scope.deciding(user, LeaveRequest.objects.filter(pk__in=[item.pk for item in leave_requests]))
               .values_list('pk', flat=True))


def _decider(user, leave_request, known=None):
    """Edit on Leave requests, the person in the user's team on the request's first day, and not the user's own request:
    scope.deciding, the one rule, asked of this request; `known` is its answer when the caller has asked it for this
    user already (`deciders_of`). A database trigger holds the last part whatever writes."""
    if known is not None:
        return known
    return scope.deciding(user, LeaveRequest.objects.filter(pk=leave_request.pk)).exists()


def can_decide(user, leave_request, decider=None):
    """Whether `user` may approve or reject the request: a pending one, by a decider. One approval step."""
    return leave_request.status == LeaveStatus.PENDING and _decider(user, leave_request, decider)


def _leave_today(leave_request):
    return site_today(read.site_on(leave_request.employee, leave_request.first_day))


def past_correction(leave_request, today=None):
    """The refusal of a correction to a leave whose last day lies more than the platform's correction window behind
    today (core.platform, the platform owner's setting), or None."""
    today = today or _leave_today(leave_request)
    window = correction_window_days()
    if (today - leave_request.last_day).days > window:
        return ValidationError(_('This leave ended on %(day)s, more than %(days)s days ago: it can no longer be '
                                 'corrected.') % {'day': date_format(leave_request.last_day), 'days': window})
    return None


def can_correct(user, leave_request, today=None, decider=None):
    """Whether `user` may shorten or cancel an approved request that has begun: a decider only, never the person (the
    days are history now; a lead or HR puts them right when the person came back early or never went), and only within
    the correction window after its last day."""
    return (leave_request.status == LeaveStatus.APPROVED and _decider(user, leave_request, decider)
            and past_correction(leave_request, today) is None)


def _refuse_correction(user, current):
    """A decider correcting a leave past the window is told why; anyone else is refused."""
    if current.status == LeaveStatus.APPROVED and _decider(user, current):
        refusal = past_correction(current)
        if refusal is not None:
            raise refusal
    raise PermissionDenied


def can_cancel(user, leave_request, today=None, decider=None):
    """Whether `user` may cancel the request: the person, or a decider; a pending request any time, an approved one only
    while its first day has not started on the site's clock (after it, a correction: `can_correct`)."""
    if leave_request.status == LeaveStatus.APPROVED:
        today = today or _leave_today(leave_request)
        if leave_request.first_day <= today:
            return can_correct(user, leave_request, today, decider)
    elif leave_request.status != LeaveStatus.PENDING:
        return False
    return _own(user, leave_request) or _decider(user, leave_request, decider)


def _lock(leave_request):
    """The request locked, after its person (HR's lock order)."""
    lock_person(leave_request.employee_id)
    return LeaveRequest.objects.select_for_update(of=('self',)).select_related('employee__user', 'leave_type').get(
        pk=leave_request.pk)


def decide_leave(user, leave_request, approve, note=''):
    """Approves or rejects a pending request, with the decider and the time. Refused (nothing changes, nothing is logged)
    for someone who may not decide it, for the person's own request, and for one that is no longer pending."""
    _verb(user, (scope.LEAVE_DECIDER,))        # only a decider holds it (_decider); the request is read after
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
    _verb(user, (scope.LEAVE_DECIDER,))        # only a decider corrects (can_correct); the request is read after
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
    zone = read.governing(record.employee, record.clock_in).zone
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
        employee = lock_person(employee.pk)
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
        employee = lock_person(employee.pk)
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


def _keeps_attendance(user, employee, moment, still_open=False):
    """`user` keeps `employee`'s attendance at `moment`: the person in their team on the day of the placement that
    governs the moment (hr.read.governing's `company_day`: the lead and the clock come from one placement) or, for a
    stretch still open, today (scope.reaches_stretch); never their own attendance."""
    if own_record(user, employee):
        raise ValidationError(_('You do not enter or correct your own attendance.'))
    if still_open and scope.can_reach(user, employee):
        return                                  # an open stretch is today's lead's too (scope.reaches_stretch)
    reached(user, [(employee, read.governing(employee, moment).company_day)],
            _('You do not see this person on this day.'))


def _note(note, needed):
    note = (note or '').strip()
    if needed and not note:
        raise ValidationError({'note': _('Say why the time was entered by hand.')})
    return note


def enter_presence(user, employee, clock_in_at, clock_out_at, note):
    """A lead records presence for a person of their team (the Attendance page's new stretch): the times as instants
    (`check_times`), and a reason (required: the CHECK on the table says so too). Needs Create on Attendance and the person
    in the user's team on the stretch's day; the person is locked before the stretch is written, and it lies inside their
    employment on its day."""
    _verb(user, ('hr.add_attendancerecord',))
    _keeps_attendance(user, employee, clock_in_at)
    check_times(clock_in_at, clock_out_at)
    note = _note(note, True)
    with transaction.atomic():
        employee = lock_employed(employee, punch_day(employee, clock_in_at),
                                 punch_day(employee, clock_out_at) if clock_out_at is not None else None)
        record = AttendanceRecord(employee=employee, clock_in=clock_in_at, clock_out=clock_out_at,
                                  via=AttendanceRecord.Via.ENTERED, note=note, created_by=user, updated_by=user)
        _save_punch(user, record, True)
        return record


def correct_presence(user, record, clock_in_at, clock_out_at, note):
    """A lead corrects a stretch (the Attendance page's edit; a forgotten clock-out is closed so): the times as instants
    and the note. A time changed is a time typed by hand, whoever clocked: the stretch is an entered one then and needs its
    reason, as an entered one always does; one whose times stay is left as it was made. Needs Edit on Attendance and the
    person in the user's team on the stretch's day, or today while it is still open (review R9); never one's own."""
    _verb(user, ('hr.change_attendancerecord',))
    with transaction.atomic():
        employee = lock_person(record.employee_id)
        current = AttendanceRecord.objects.select_for_update(of=('self',)).get(pk=record.pk)
        still_open = current.clock_out is None
        _keeps_attendance(user, employee, current.clock_in, still_open)
        _keeps_attendance(user, employee, clock_in_at, still_open)
        check_times(clock_in_at, clock_out_at)
        typed = clock_in_at != current.clock_in or clock_out_at != current.clock_out
        note = _note(note, typed or current.via == AttendanceRecord.Via.ENTERED)
        check_employed(employee, punch_day(employee, clock_in_at),
                       punch_day(employee, clock_out_at) if clock_out_at is not None else None)
        before = _punch_values(current)
        current.clock_in, current.clock_out, current.note = clock_in_at, clock_out_at, note
        if typed:
            current.via = AttendanceRecord.Via.ENTERED
        current.updated_by, current.version = user, current.version + 1
        _save_punch(user, current, False, before)
        return current


def void_presence(user, record):
    """Voids a stretch (the Attendance page's delete) as the person confirmed it (`record`, at its version:
    `as_confirmed`): Delete on Attendance and the stretch the user's to correct (`correct_presence`'s reach), never their
    own; the person is locked before the stretch; logged by the delete plan."""
    _verb(user, ('hr.delete_attendancerecord',))
    with transaction.atomic():
        employee = lock_person(record.employee_id)
        current = AttendanceRecord.objects.select_for_update(of=('self',)).filter(pk=record.pk).first()
        as_confirmed(current, record)           # voided or corrected since the confirmation: said, nothing voided
        if own_record(user, employee):
            raise PermissionDenied
        if not scope.reaches_stretch(user, employee, read.governing(employee, current.clock_in).company_day,
                                     current.clock_out is None):
            raise PermissionDenied
        plan = softdelete.plan_delete(current)
        if not plan.can_delete:
            raise ValidationError(plan.blockers)
        softdelete.execute(plan, user)
        return current

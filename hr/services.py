"""What changes people's records in HR, each function one transaction with its audit row. A service takes the person
who acts, checks the verb and their scope itself (a page that already did is not trusted), and refuses with a
ValidationError (a sentence for the person) or PermissionDenied; a refusal leaves no row and no log entry."""
from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils.translation import gettext as _

from core import audit
from core.models import AuditLog
from farm.models.site import zone_of

from . import clock, read, rules, scope, units
from .models import Employee, Holiday, Posting, SchedulingSettings, ShiftAssignment

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


# ---- the roster -------------------------------------------------------------------------------------------------
CLEAR = object()          # a cell cleared: the plan for that day is removed (a soft delete, logged)
MARGIN = 15               # days either side of a change read for the rest across a border and a run of days

def holiday_days(first, last, site):
    """The days between `first` and `last` that are holidays for `site` (None: only those of every site)."""
    scope_of_site = Q(site__isnull=True) if site is None else Q(site__isnull=True) | Q(site=site)
    return set(Holiday.objects.filter(scope_of_site, day__range=(first, last)).values_list('day', flat=True))




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
    weeks = {rules.monday(day) for day in changes}
    return rules.findings(planned, set(), holidays, settings, weeks)


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
        for employee, changes in by_person.values():
            existing = {row.day: row for row in ShiftAssignment.objects.select_for_update().filter(
                employee=employee, day__in=list(changes))}
            for day in changes:
                if not scope.can_reach(user, employee, day) or not user.has_perm(
                        _cell_permission(existing.get(day), shift)):
                    raise PermissionDenied
            if shift is CLEAR and not existing:
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

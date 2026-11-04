"""What changes people's records in HR, each function one transaction with its audit row. A service takes the person
who acts, checks the verb and their scope itself (a page that already did is not trusted), and refuses with a
ValidationError (a sentence for the person) or PermissionDenied; a refusal leaves no row and no log entry."""
from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from core import audit
from core.models import AuditLog

from . import scope, units
from .models import Employee, Posting

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

"""What the database cannot hold: rules that look at several rows and change with time. `problems()` reads the HR records and
says what disagrees (`manage.py check_hr` prints it); nothing is repaired here, a person decides. The rules the database can hold
(overlaps, orders, ranges, uniqueness, one department per placement) are constraints and need no check."""
from django.db.models import F, Q

from farm.stock.dates import site_today

from . import scope
from .models import Employee, LeaveRequest, OfficeDepartment, Posting
from .models.leave import HOLDING


def problems(today=None):
    """[(code, text)] for every disagreement found, in a fixed order."""
    today = today or site_today(None)
    found = []
    for employee in Employee.objects.filter(left_on__isnull=False).select_related('user'):
        for posting in Posting.objects.filter(employee=employee).filter(
                Q(valid_until__isnull=True) | Q(valid_until__gt=employee.left_on) | Q(valid_from__gt=employee.left_on)):
            found.append(('placement_after_last_day',
                          f'{employee} left on {employee.left_on} but is placed from {posting.valid_from} until '
                          f'{posting.valid_until or "open"}.'))
        for request in LeaveRequest.objects.filter(employee=employee, status__in=HOLDING, last_day__gt=employee.left_on):
            found.append(('leave_after_last_day',
                          f'{employee} left on {employee.left_on} but has leave until {request.last_day}.'))
    for posting in Posting.objects.select_related('employee__user').filter(valid_from__lt=F('employee__joined_on')):
        found.append(('placement_before_joined',
                      f'{posting.employee} is placed from {posting.valid_from} but joined on {posting.employee.joined_on}.'))
    working = Employee.objects.filter(joined_on__lte=today).filter(Q(left_on__isnull=True) | Q(left_on__gte=today))
    placed = Posting.objects.filter(scope.covering(today)).values('employee')
    for employee in working.exclude(pk__in=placed).select_related('user'):
        found.append(('not_placed', f'{employee} works here but is placed in no department today.'))
    for department in OfficeDepartment.objects.filter(site__isnull=True):
        if Posting.objects.filter(scope.covering(today), office_department=department).exists():
            found.append(('office_department_without_site',
                          f'{department} has people placed in it but no site, so they are read on the company clock.'))
    for department in OfficeDepartment.objects.filter(status='inactive'):
        if Posting.objects.filter(scope.covering(today), office_department=department).exists():
            found.append(('inactive_department_with_people', f'{department} is inactive but has people placed in it.'))
    return found

"""What a leave request costs and what a person has left, read from the request, the holidays and the settings: nothing
here is stored (the source stored `totalDays` and mutable balance counters, and charged calendar days: HR-07).

A day is charged when its weekday is one of the company's working weekdays (a setting, Monday to Friday by default) and
it is not a holiday (for every site, or for the site the person works on). The days of a request that crosses New Year
are split by the year they fall in."""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db.models import Q

from .models import Holiday, LeaveRequest, SchedulingSettings
from .models.leave import HOLDING, LeaveStatus


def each_day(first, last):
    day = first
    while day <= last:
        yield day
        day += timedelta(days=1)


def holiday_table(firsts, lasts):
    """Every holiday between the earliest of `firsts` and the latest of `lasts`, read once for several requests."""
    if not firsts:
        return []
    return list(Holiday.objects.filter(day__range=(min(firsts), max(lasts))))


def holidays_for(first, last, site, table=None):
    """The days between `first` and `last` that are holidays for `site` (None: only those of every site). `table` is a
    holiday_table read earlier; without it the holidays are read now."""
    if table is not None:
        return {holiday.day for holiday in table if first <= holiday.day <= last
                and (holiday.site_id is None or (site is not None and holiday.site_id == site.pk))}
    scope = Q(site__isnull=True) if site is None else Q(site__isnull=True) | Q(site=site)
    return set(Holiday.objects.filter(scope, day__range=(first, last)).values_list('day', flat=True))


def charged_by_year(first, last, site, weekdays=None, holidays=None):
    """{year: days charged} for a request from `first` to `last` for a person on `site`."""
    weekdays = set(weekdays if weekdays is not None else SchedulingSettings.get().working_weekdays)
    free = holidays_for(first, last, site, holidays)
    charged = defaultdict(Decimal)
    for day in each_day(first, last):
        if day.weekday() in weekdays and day not in free:
            charged[day.year] += Decimal(1)
    return dict(charged)


def leave_days(first, last, site, weekdays=None, holidays=None):
    """The days a request from `first` to `last` is charged for, as a Decimal."""
    return sum(charged_by_year(first, last, site, weekdays, holidays).values(), Decimal(0))


def used(employee, leave_type, year, site=None, exclude=None):
    """The days of `year` the employee's pending and approved requests of this type are charged for."""
    requests = LeaveRequest.objects.filter(employee=employee, leave_type=leave_type, status__in=HOLDING,
                                           first_day__year__lte=year, last_day__year__gte=year)
    if exclude is not None:
        requests = requests.exclude(pk=exclude.pk)
    return sum((charged_by_year(request.first_day, request.last_day, site).get(year, Decimal(0))
                for request in requests), Decimal(0))


def balance(employee, leave_type, year, site=None):
    """The days left of the type's yearly allowance, or None when it has no limit."""
    if leave_type.annual_days is None:
        return None
    return leave_type.annual_days - used(employee, leave_type, year, site)


def away_on(day, user_ids):
    """The ids of those among `user_ids` (accounts) who are on approved leave on `day`: away or not, and nothing
    more (no type, no reason), for the places that may only learn that someone is not there."""
    return set(LeaveRequest.objects.filter(
        employee__user__in=user_ids, status=LeaveStatus.APPROVED, first_day__lte=day, last_day__gte=day,
    ).values_list('employee__user', flat=True))


def approved_days(employee_ids, first, last):
    """{employee id: the days between `first` and `last` they are on approved leave}."""
    found = defaultdict(set)
    for request in LeaveRequest.objects.filter(employee__in=employee_ids, status=LeaveStatus.APPROVED,
                                               first_day__lte=last, last_day__gte=first):
        found[request.employee_id].update(each_day(max(request.first_day, first), min(request.last_day, last)))
    return dict(found)

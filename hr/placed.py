"""Where a person is placed on a day, from placements read beforehand: the one spelling of "which placement covers this
day" and of the site that goes with it, for every HR read and rule that asks it of many people or many days at once
(the week, the board, the crew, leave, the rules of a save)."""
from collections import defaultdict

from . import scope
from .models import Posting


def placements(employee_ids, first, last):
    """{employee id: their placements in force between `first` and `last`, with the departments' sites}: one query."""
    found = defaultdict(list)
    for posting in Posting.objects.filter(scope.overlapping(first, last), employee__in=employee_ids).select_related(
            'production_department__site', 'office_department__site').order_by('valid_from'):
        found[posting.employee_id].append(posting)
    return found


def placed_on(placed, day):
    """The placement among `placed` (a person's, read beforehand) that covers `day`, or None."""
    return next((p for p in placed if p.valid_from <= day and (p.valid_until is None or p.valid_until >= day)), None)


def site_of_posting(posting):
    department = posting.department
    return getattr(department, 'site', None) if department is not None else None


def site_of_day(placed, day):
    """The site whose clock and holidays govern a person's DAY (a planned day, a day of leave): the site of the
    department they are placed in on that day; None (the company's clock, the holidays of every site) without one."""
    posting = placed_on(placed, day)
    return site_of_posting(posting) if posting is not None else None

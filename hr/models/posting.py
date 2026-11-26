from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import RangeOperators
from django.db import models
from django.db.models import F, Q, Value
from django.utils.translation import gettext_lazy as _

from core.models import AuditedModel
from core.ranges import DateRange
from farm.models import ProductionDepartment

from .employee import Employee
from .office_department import OfficeDepartment

PERIOD_MESSAGE = _('A placement cannot end before it starts.')
OVERLAP_MESSAGE = _('This person is already placed in a department on some of these days.')
ONE_DEPARTMENT = _('Choose one department: a production department or an office department.')


def period():
    """The days a placement covers; an empty last day is open."""
    return DateRange(F('valid_from'), F('valid_until'), Value('[]'))


class Posting(AuditedModel):
    """Where a person works from a day: one department (a production department of the farm, or an office
    department of HR: exactly one, a database check, as a task's place is) and the title they hold there. A person has
    one placement on any day (an exclusion constraint); a move closes the open placement the day before and opens the
    next (hr.services.move), so the department of a past day is read from here and no record is rewritten.

    Both links are PROTECT: a department with people placed in it is made inactive, not deleted."""

    service_written = True       # hr.services is its one writer (core.models.AuditedModel)

    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name='postings',
                                 verbose_name=_('Employee'))
    production_department = models.ForeignKey(
        ProductionDepartment, null=True, blank=True, on_delete=models.PROTECT, related_name='postings',
        verbose_name=_('Production department'))
    office_department = models.ForeignKey(
        OfficeDepartment, null=True, blank=True, on_delete=models.PROTECT, related_name='postings',
        verbose_name=_('Office department'))
    title = models.CharField(_('Title'), max_length=100, blank=True)
    valid_from = models.DateField(_('From'))
    valid_until = models.DateField(_('Until'), null=True, blank=True)

    class Meta:
        db_table = 'postings'
        ordering = ['employee', '-valid_from']
        verbose_name = _('placement')
        verbose_name_plural = _('placements')
        constraints = [
            models.CheckConstraint(
                condition=(Q(production_department__isnull=False, office_department__isnull=True)
                           | Q(production_department__isnull=True, office_department__isnull=False)),
                name='chk_postings_one_department', violation_error_message=ONE_DEPARTMENT),
            models.CheckConstraint(
                condition=Q(valid_until__isnull=True) | Q(valid_until__gte=F('valid_from')),
                name='chk_postings_period', violation_error_message=PERIOD_MESSAGE),
            ExclusionConstraint(
                name='excl_postings_employee_period',
                expressions=[(F('employee'), RangeOperators.EQUAL), (period(), RangeOperators.OVERLAPS)],
                condition=Q(is_deleted=False), violation_error_message=OVERLAP_MESSAGE),
        ]
        indexes = [models.Index(fields=['valid_from'])]

    @property
    def department(self):
        return self.production_department or self.office_department

    @property
    def is_open(self):
        return self.valid_until is None

    def __str__(self):
        return f'{self.employee}: {self.department} from {self.valid_from}'

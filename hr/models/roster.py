from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from core.models import AuditedModel

from .employee import Employee
from .scheduling import Shift


class ShiftAssignment(AuditedModel):
    """One person's plan for one day: the shift they start that day, or none (planned off). The day is the day the
    shift starts; a night shift ends on the next one. There is one row for a person and day (a unique constraint among
    live rows) and nothing else holds the roster: leave and holidays are joined when it is read, and there is no
    publish step: every change is logged with what it was before and after. A cleared cell is a soft delete."""

    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name='assignments',
                                 verbose_name=_('Employee'))
    day = models.DateField(_('Day'))
    # No shift: the person is planned off that day (which is not the same as having no plan).
    shift = models.ForeignKey(Shift, null=True, blank=True, on_delete=models.PROTECT, related_name='assignments',
                              verbose_name=_('Shift'))
    note = models.CharField(_('Note'), max_length=200, blank=True)

    class Meta:
        db_table = 'shift_assignments'
        ordering = ['day', 'employee']
        verbose_name = _('plan')
        verbose_name_plural = _('plans')
        constraints = [
            models.UniqueConstraint(fields=['employee', 'day'], condition=Q(is_deleted=False),
                                    name='uq_shift_assignments_employee_day',
                                    violation_error_message=_('This person already has a plan for this day.')),
        ]
        indexes = [models.Index(fields=['day'])]

    def __str__(self):
        return f'{self.employee}, {self.day}: {self.shift or _("off")}'

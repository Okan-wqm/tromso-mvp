from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import RangeOperators
from django.db import models
from django.db.models import F, Q
from django.utils.translation import gettext_lazy as _

from core.models import AuditedModel
from core.ranges import InstantRange

from .employee import Employee

NOTE_MESSAGE = _('Say why the time was entered by hand.')
ORDER_MESSAGE = _('The person cannot clock out before they clocked in.')
OVERLAP_MESSAGE = _('This person is already clocked in for some of this time.')


def stretch():
    """The time a punch covers; a punch with no clock-out runs on, so it also forbids a second open one."""
    from django.db.models import Value
    return InstantRange(F('clock_in'), F('clock_out'), Value('[)'))


class AttendanceRecord(AuditedModel):
    """One stretch of presence of one person: from a clock-in to a clock-out (none while they are in). Not a day: a
    person can work in two stretches, and a night shift crosses midnight. Whether they are present, late or absent is
    read from these and the plan on the site's clock (hr.read.board), never stored; the day a stretch belongs to is the
    day of the shift whose span it falls in.

    `via` says who made it: `self` (the person clocked in and out themselves, at the server's time) or `entered` (a
    lead typed the time on the site's clock, and must say why). Two stretches of one person never overlap and at most
    one is open, as exclusion constraints on the time range."""

    class Via(models.TextChoices):
        SELF = 'self', _('Clocked in by the person')
        ENTERED = 'entered', _('Entered by hand')

    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name='attendance',
                                 verbose_name=_('Employee'))
    clock_in = models.DateTimeField(_('Clock in'))
    clock_out = models.DateTimeField(_('Clock out'), null=True, blank=True)
    via = models.CharField(_('How'), max_length=10, choices=Via.choices, default=Via.ENTERED)
    # The lead's reason for an entered time, or any remark: the person's own words, masked in the log and the viewer.
    note = models.CharField(_('Note'), max_length=200, blank=True)

    class Meta:
        db_table = 'attendance_records'
        ordering = ['-clock_in']
        verbose_name = _('attendance record')
        verbose_name_plural = _('attendance records')
        constraints = [
            models.CheckConstraint(condition=Q(clock_out__isnull=True) | Q(clock_out__gt=F('clock_in')),
                                   name='chk_attendance_records_order', violation_error_message=ORDER_MESSAGE),
            models.CheckConstraint(condition=Q(via__in=['self', 'entered']), name='chk_attendance_records_via'),
            models.CheckConstraint(condition=Q(via='self') | Q(note__regex=r'\S'), name='chk_attendance_records_note',
                                   violation_error_message=NOTE_MESSAGE),
            ExclusionConstraint(
                name='excl_attendance_employee_span',
                expressions=[(F('employee'), RangeOperators.EQUAL), (stretch(), RangeOperators.OVERLAPS)],
                condition=Q(is_deleted=False), violation_error_message=OVERLAP_MESSAGE),
        ]
        indexes = [models.Index(fields=['clock_in'])]

    def __str__(self):
        return f'{self.employee}: {self.clock_in:%Y-%m-%d %H:%M}'

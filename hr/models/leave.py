from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import RangeOperators
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.db.models import F, Q, Value
from django.utils.translation import gettext_lazy as _, pgettext_lazy

from core.models import CODE, CODE_MESSAGE, AuditedModel, CodedMixin
from core.ranges import DateRange

from .employee import Employee


class LeaveType(CodedMixin, AuditedModel):
    """A kind of leave (annual, sick, parental, unpaid): owner data, nothing is seeded. `annual_days` is the yearly
    allowance (empty: no limit). A type that does not need approval is granted the moment it is filed (and then has
    no decider)."""

    class Status(models.TextChoices):
        ACTIVE = 'active', _('Active')
        INACTIVE = 'inactive', _('Inactive')

    name = models.CharField(_('Name'), max_length=100)
    code = models.CharField(_('Code'), max_length=20, validators=[RegexValidator(CODE, CODE_MESSAGE)])
    annual_days = models.DecimalField(_('Days a year'), max_digits=5, decimal_places=2, null=True, blank=True,
                                      validators=[MinValueValidator(0)])
    needs_approval = models.BooleanField(_('Needs approval'), default=True)
    status = models.CharField(_('Status'), max_length=10, choices=Status.choices, default=Status.ACTIVE)

    class Meta:
        db_table = 'leave_types'
        ordering = ['name']
        verbose_name = _('leave type')
        verbose_name_plural = _('leave types')
        constraints = [
            models.UniqueConstraint(fields=['code'], condition=Q(is_deleted=False), name='uq_leave_types_code_live',
                                    violation_error_message=_('Another leave type already uses this code.')),
            models.CheckConstraint(condition=Q(code__regex=CODE), name='chk_leave_types_code',
                                   violation_error_message=CODE_MESSAGE),
            models.CheckConstraint(condition=Q(annual_days__isnull=True) | Q(annual_days__gte=0),
                                   name='chk_leave_types_days',
                                   violation_error_message=_('The days a year cannot be negative.')),
            models.CheckConstraint(condition=Q(status__in=['active', 'inactive']), name='chk_leave_types_status'),
        ]


class LeaveStatus(models.TextChoices):
    PENDING = 'pending', pgettext_lazy('leave status', 'Pending')
    APPROVED = 'approved', pgettext_lazy('leave status', 'Approved')
    REJECTED = 'rejected', pgettext_lazy('leave status', 'Rejected')
    CANCELLED = 'cancelled', pgettext_lazy('leave status', 'Cancelled')


# The statuses that hold the days: a pending or an approved request blocks another for the same days.
HOLDING = (LeaveStatus.PENDING, LeaveStatus.APPROVED)
OVERLAP_MESSAGE = _('This person already has a leave request for some of these days.')


def days():
    """The days a request covers, both ends included."""
    return DateRange(F('first_day'), F('last_day'), Value('[]'))


class LeaveRequest(AuditedModel):
    """A person's request to be away from the first to the last day. One approval step: whoever holds Edit on Leave
    requests for the person's team, and is not the person, approves or rejects it. What it costs in days is read
    (hr.leave.leave_days), never stored, and so is whether the person is on leave today."""

    Status = LeaveStatus

    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name='leave_requests',
                                 verbose_name=_('Employee'))
    leave_type = models.ForeignKey(LeaveType, on_delete=models.PROTECT, related_name='requests',
                                   verbose_name=_('Leave type'))
    first_day = models.DateField(_('First day'))
    last_day = models.DateField(_('Last day'))
    status = models.CharField(_('Status'), max_length=10, choices=LeaveStatus.choices, default=LeaveStatus.PENDING)
    # The person's own words: seen by them and by the holders of Everyone, masked in the log and the viewer.
    reason = models.CharField(_('Reason'), max_length=500, blank=True)
    decision_note = models.CharField(_('Decision note'), max_length=500, blank=True)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='+', verbose_name=_('Decided by'))
    decided_at = models.DateTimeField(_('Decided at'), null=True, blank=True)

    class Meta:
        db_table = 'leave_requests'
        ordering = ['-first_day', 'employee']
        verbose_name = _('leave request')
        verbose_name_plural = _('leave requests')
        constraints = [
            models.CheckConstraint(condition=Q(last_day__gte=F('first_day')), name='chk_leave_requests_days',
                                   violation_error_message=_('The last day cannot be before the first.')),
            models.CheckConstraint(condition=Q(status__in=LeaveStatus.values), name='chk_leave_requests_status'),
            # A decision has its time; a request that was never decided (pending, cancelled) may have none.
            models.CheckConstraint(
                condition=Q(status__in=['pending', 'cancelled']) | Q(decided_at__isnull=False),
                name='chk_leave_requests_decided',
                violation_error_message=_('An approved or rejected request has the time it was decided.')),
            # A request nobody has decided has no decider and no time.
            models.CheckConstraint(
                condition=~Q(status='pending') | Q(decided_at__isnull=True, decided_by__isnull=True),
                name='chk_leave_requests_pending_undecided',
                violation_error_message=_('A pending request has no decider and no decision time.')),
            ExclusionConstraint(
                name='excl_leave_requests_employee_days',
                expressions=[(F('employee'), RangeOperators.EQUAL), (days(), RangeOperators.OVERLAPS)],
                condition=Q(is_deleted=False, status__in=['pending', 'approved']),
                violation_error_message=OVERLAP_MESSAGE),
        ]
        indexes = [models.Index(fields=['first_day']), models.Index(fields=['status'])]

    def __str__(self):
        return f'{self.employee}: {self.first_day} – {self.last_day}'

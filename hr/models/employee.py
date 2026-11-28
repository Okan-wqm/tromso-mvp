from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from core.models import AuditedModel

NUMBER = r'^[A-Za-z0-9_./-]+$'
NUMBER_MESSAGE = _('Use letters, digits, dots, hyphens, slashes and underscores only.')


class EmploymentType(models.TextChoices):
    STAFF = 'staff', _('Staff')
    STUDENT = 'student', _('Student')
    RESEARCHER = 'researcher', _('Researcher')
    TECHNICIAN = 'technician', _('Technician')
    ADVISOR = 'advisor', _('Advisor')
    CONTRACTOR = 'contractor', _('Contractor')
    VOLUNTEER = 'volunteer', _('Volunteer')


class Employee(AuditedModel):
    """A person of the company, for the HR pages. One row per person; the account that signs in is `user`, and a
    person who never signs in (a student, a visiting researcher) has no account at all.

    The name exists in one place: a person with an account is named by it (first and last name stay empty here, a
    database check), one without carries their own. Where they work is not a column of the person: it is a dated
    `Posting`, so the department of a past day can be read and a move changes no old record. There is no pay, bank
    or identity-number column here or anywhere in HR, and no contact detail (a test fails on one): a later payroll
    app owns what concerns money and points at this row.

    A person who leaves is not deleted: `left_on` closes the record, the history stays readable."""

    service_written = True       # hr.services is its one writer (core.models.AuditedModel)

    # Defined outside the class so that its Meta can name their values in the constraint.
    Type = EmploymentType

    employee_number = models.CharField(_('Employee number'), max_length=20,
                                       validators=[RegexValidator(NUMBER, NUMBER_MESSAGE)])
    # PROTECT: an account with an employee row is not deleted from under it (people are deactivated, not deleted).
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                             related_name='employee', verbose_name=_('Account'))
    first_name = models.CharField(_('First name'), max_length=100, blank=True)
    last_name = models.CharField(_('Last name'), max_length=100, blank=True)
    employment_type = models.CharField(_('Employment type'), max_length=20, choices=Type.choices,
                                       default=Type.STAFF)
    joined_on = models.DateField(_('Joined on'))
    left_on = models.DateField(_('Left on'), null=True, blank=True)

    class Meta:
        db_table = 'employees'
        ordering = ['last_name', 'first_name', 'employee_number']
        verbose_name = _('employee')
        verbose_name_plural = _('employees')
        # Everyone: reads every employee, not only the team (hr.scope.team); All production: every person placed in a
        # production department, never the office's nor a leave reason. The matrix offers each as a column.
        permissions = [('all_employee', 'Can see every employee'),
                       ('all_production_employee', 'Can see every production person')]
        constraints = [
            models.UniqueConstraint(
                fields=['employee_number'], condition=Q(is_deleted=False), name='uq_employees_number_live',
                violation_error_message=_('Another employee already has this number.')),
            models.UniqueConstraint(
                fields=['user'], condition=Q(is_deleted=False), name='uq_employees_user_live',
                violation_error_message=_('This account already belongs to another employee.')),
            # The name is in one place: the account's, or the person's own.
            models.CheckConstraint(
                condition=(Q(user__isnull=False, first_name='', last_name='')
                           | Q(user__isnull=True) & ~Q(last_name='')),
                name='chk_employees_identity',
                violation_error_message=_('A person with an account is named by it; one without needs a last name.')),
            models.CheckConstraint(
                condition=Q(left_on__isnull=True) | Q(left_on__gte=models.F('joined_on')), name='chk_employees_period',
                violation_error_message=_('A person cannot leave before they joined.')),
            models.CheckConstraint(condition=Q(employment_type__in=EmploymentType.values),
                                   name='chk_employees_type'),
            models.CheckConstraint(condition=Q(employee_number__regex=NUMBER), name='chk_employees_number',
                                   violation_error_message=NUMBER_MESSAGE),
        ]

    @property
    def full_name(self):
        """The person's name: their account's, else their own."""
        if self.user_id:
            return self.user.get_full_name() or self.user.get_username()
        return f'{self.first_name} {self.last_name}'.strip()

    def __str__(self):
        return self.full_name

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import F, Q
from django.utils.translation import gettext_lazy as _

from core.models import CODE, CODE_MESSAGE, AuditedModel, CodedMixin, TreeMixin
from farm.models import Site


class OfficeDepartment(CodedMixin, TreeMixin, AuditedModel):
    """A department of the company's office side (management, Finance, administration). The production departments
    are the farm's own rows and appear in HR by themselves (hr.read.departments); HR owns only these.

    Departments nest under one another (the organisation chart); a cycle is refused by the form and, whatever
    writes, by a database trigger (migration 0001). The manager sees and plans the department's people, and those of
    the departments below it, in HR (hr.scope.team). The site gives the department's people their clock: the day
    and the time of every HR read."""

    class Status(models.TextChoices):
        ACTIVE = 'active', _('Active')
        INACTIVE = 'inactive', _('Inactive')

    # A department is nested under another; the parent is never deleted from under its children (a delete is
    # refused while they exist, they are not flattened silently).
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT, related_name='children',
                               verbose_name=_('Parent department'))
    site = models.ForeignKey(Site, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
                             verbose_name=_('Site'))
    name = models.CharField(_('Name'), max_length=100)
    code = models.CharField(_('Code'), max_length=20, validators=[RegexValidator(CODE, CODE_MESSAGE)])
    status = models.CharField(_('Status'), max_length=10, choices=Status.choices, default=Status.ACTIVE)
    manager = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                related_name='+', verbose_name=_('Manager'))
    description = models.TextField(_('Description'), blank=True)

    class Meta:
        db_table = 'office_departments'
        ordering = ['name']
        verbose_name = _('office department')
        verbose_name_plural = _('office departments')
        constraints = [
            models.UniqueConstraint(
                fields=['code'], condition=Q(is_deleted=False), name='uq_office_departments_code_live',
                violation_error_message=_('Another office department already uses this code.')),
            # Two top-level departments (no parent) with one name clash too: the missing parent counts as one value.
            models.UniqueConstraint(
                fields=['parent', 'name'], condition=Q(is_deleted=False), nulls_distinct=False,
                name='uq_office_departments_parent_name_live',
                violation_error_message=_('This department already has a department with this name.')),
            models.CheckConstraint(
                condition=Q(parent__isnull=True) | ~Q(parent=F('id')), name='chk_office_departments_parent_not_self',
                violation_error_message=_('A department cannot be its own parent.')),
            models.CheckConstraint(condition=Q(code__regex=CODE), name='chk_office_departments_code',
                                   violation_error_message=CODE_MESSAGE),
            models.CheckConstraint(condition=Q(status__in=['active', 'inactive']),
                                   name='chk_office_departments_status'),
        ]
        indexes = [models.Index(fields=['status'])]
